from __future__ import annotations

import asyncio
import hashlib
import secrets
from collections.abc import Iterable
from datetime import UTC, datetime
from uuid import UUID

from comfycluster_common.models import (
    HostHeartbeat,
    HostRegistration,
    HostView,
    JobRecord,
    JobState,
    JobSummary,
    WorkerSnapshot,
    WorkerState,
)
from comfycluster_common.releases import ReleaseManifest
from comfycluster_common.tenancy import (
    ApiTokenRecord,
    GroupRecord,
    IssuedToken,
    MembershipRecord,
    MembershipRole,
    Principal,
    UserRecord,
)


class QuotaExceededError(RuntimeError):
    def __init__(self, scope: str, limit: int, current: int) -> None:
        self.scope = scope
        self.limit = limit
        self.current = current
        super().__init__(f"{scope} queue limit reached ({current}/{limit})")


class FleetStore:
    """In-memory repository contract used by the controller."""

    def __init__(self) -> None:
        self._hosts: dict[str, HostView] = {}
        self._jobs: dict[UUID, JobRecord] = {}
        self._desired_release: ReleaseManifest | None = None
        self._groups: dict[str, GroupRecord] = {}
        self._users: dict[str, UserRecord] = {}
        self._memberships: dict[tuple[str, str], MembershipRecord] = {}
        self._tokens: dict[str, ApiTokenRecord] = {}
        self._lock = asyncio.Lock()

    async def register_host(self, registration: HostRegistration) -> HostView:
        async with self._lock:
            previous = self._hosts.get(registration.host_id)
            view = HostView(
                host_id=registration.host_id,
                hostname=registration.hostname,
                os_name=registration.os_name,
                os_version=registration.os_version,
                agent_version=registration.agent_version,
                connected=True,
                draining=previous.draining if previous else False,
                last_seen=datetime.now(UTC),
                gpus=registration.gpus,
                comfy=registration.comfy,
                comfy_cli=registration.comfy_cli,
                workers=registration.workers,
                nodes=registration.nodes,
                models=registration.models,
            )
            self._hosts[registration.host_id] = view
            return view.model_copy(deep=True)

    async def heartbeat(self, heartbeat: HostHeartbeat) -> HostView | None:
        async with self._lock:
            host = self._hosts.get(heartbeat.host_id)
            if host is None:
                return None
            host.last_seen = datetime.now(UTC)
            host.connected = True
            host.gpus = heartbeat.gpus
            existing = {worker.worker_id: worker for worker in host.workers}
            merged: list[WorkerSnapshot] = []
            for incoming in heartbeat.workers:
                previous = existing.get(incoming.worker_id)
                if previous and previous.current_job_id and not incoming.current_job_id:
                    incoming = incoming.model_copy(deep=True)
                    incoming.current_job_id = previous.current_job_id
                    incoming.state = WorkerState.BUSY
                merged.append(incoming)
            host.workers = merged
            return host.model_copy(deep=True)

    async def mark_disconnected(self, host_id: str) -> None:
        async with self._lock:
            host = self._hosts.get(host_id)
            if host:
                host.connected = False
                for worker in host.workers:
                    worker.state = WorkerState.OFFLINE

    async def set_host_draining(self, host_id: str, draining: bool) -> HostView | None:
        async with self._lock:
            host = self._hosts.get(host_id)
            if host is None:
                return None
            host.draining = draining
            return host.model_copy(deep=True)

    async def list_hosts(self) -> list[HostView]:
        async with self._lock:
            return [host.model_copy(deep=True) for host in self._hosts.values()]

    async def get_host(self, host_id: str) -> HostView | None:
        async with self._lock:
            host = self._hosts.get(host_id)
            return host.model_copy(deep=True) if host else None

    async def list_workers(self) -> list[tuple[HostView, WorkerSnapshot]]:
        async with self._lock:
            result: list[tuple[HostView, WorkerSnapshot]] = []
            for host in self._hosts.values():
                for worker in host.workers:
                    result.append((host.model_copy(deep=True), worker.model_copy(deep=True)))
            return result

    async def update_worker(
        self,
        host_id: str,
        worker_id: str,
        *,
        state: WorkerState | None = None,
        current_job_id: UUID | None = None,
    ) -> WorkerSnapshot | None:
        async with self._lock:
            host = self._hosts.get(host_id)
            if not host:
                return None
            worker = next((item for item in host.workers if item.worker_id == worker_id), None)
            if not worker:
                return None
            if state is not None:
                worker.state = state
            worker.current_job_id = current_job_id
            return worker.model_copy(deep=True)

    async def create_job(self, job: JobRecord) -> JobRecord:
        async with self._lock:
            self._jobs[job.job_id] = job
            return job.model_copy(deep=True)

    async def create_job_enforcing_quotas(self, job: JobRecord) -> JobRecord:
        async with self._lock:
            queued = [item for item in self._jobs.values() if item.state is JobState.QUEUED]
            if job.owner_user_id and job.owner_user_id in self._users:
                user = self._users[job.owner_user_id]
                current = sum(1 for item in queued if item.owner_user_id == job.owner_user_id)
                if current >= user.max_queued_jobs:
                    raise QuotaExceededError("user", user.max_queued_jobs, current)
            if job.group_id and job.group_id in self._groups:
                group = self._groups[job.group_id]
                current = sum(1 for item in queued if item.group_id == job.group_id)
                if current >= group.policy.max_queued_jobs:
                    raise QuotaExceededError("group", group.policy.max_queued_jobs, current)
            self._jobs[job.job_id] = job
            return job.model_copy(deep=True)

    async def can_dispatch(self, job: JobRecord) -> tuple[bool, list[str]]:
        async with self._lock:
            active = {JobState.DISPATCHING, JobState.RUNNING}
            reasons: list[str] = []
            if job.owner_user_id and job.owner_user_id in self._users:
                user = self._users[job.owner_user_id]
                running = sum(
                    1
                    for item in self._jobs.values()
                    if item.owner_user_id == job.owner_user_id and item.state in active
                )
                if running >= user.max_running_jobs:
                    reasons.append("user_running_limit")
            if job.group_id and job.group_id in self._groups:
                group = self._groups[job.group_id]
                running = sum(
                    1
                    for item in self._jobs.values()
                    if item.group_id == job.group_id and item.state in active
                )
                if running >= group.policy.max_running_jobs:
                    reasons.append("group_running_limit")
            return not reasons, reasons

    async def get_job(self, job_id: UUID) -> JobRecord | None:
        async with self._lock:
            job = self._jobs.get(job_id)
            return job.model_copy(deep=True) if job else None

    async def list_jobs(self) -> list[JobRecord]:
        async with self._lock:
            jobs = sorted(self._jobs.values(), key=lambda item: item.created_at, reverse=True)
            return [job.model_copy(deep=True) for job in jobs]

    async def list_job_summaries(self) -> list[JobSummary]:
        return [JobSummary.from_job(job) for job in await self.list_jobs()]

    async def list_jobs_for_principal(self, principal: Principal) -> list[JobRecord]:
        jobs = await self.list_jobs()
        return [job for job in jobs if self.principal_can_view_job(principal, job)]

    @staticmethod
    def principal_can_view_job(principal: Principal, job: JobRecord) -> bool:
        if principal.content_auditor:
            return True
        if job.owner_user_id == principal.user_id:
            return True
        return bool(
            job.visibility.value == "group"
            and job.group_id
            and job.group_id in principal.group_ids
        )

    async def update_job(self, job_id: UUID, **changes: object) -> JobRecord | None:
        async with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            for key, value in changes.items():
                setattr(job, key, value)
            job.updated_at = datetime.now(UTC)
            return job.model_copy(deep=True)

    async def set_job_state(self, job_id: UUID, state: JobState, **changes: object) -> JobRecord | None:
        return await self.update_job(job_id, state=state, **changes)

    async def create_group(self, group: GroupRecord) -> GroupRecord:
        async with self._lock:
            self._groups[group.group_id] = group.model_copy(deep=True)
            return group.model_copy(deep=True)

    async def list_groups(self) -> list[GroupRecord]:
        async with self._lock:
            return [item.model_copy(deep=True) for item in self._groups.values()]

    async def get_group(self, group_id: str) -> GroupRecord | None:
        async with self._lock:
            item = self._groups.get(group_id)
            return item.model_copy(deep=True) if item else None

    async def create_user(self, user: UserRecord) -> UserRecord:
        async with self._lock:
            self._users[user.user_id] = user.model_copy(deep=True)
            return user.model_copy(deep=True)

    async def list_users(self) -> list[UserRecord]:
        async with self._lock:
            return [item.model_copy(deep=True) for item in self._users.values()]

    async def get_user(self, user_id: str) -> UserRecord | None:
        async with self._lock:
            item = self._users.get(user_id)
            return item.model_copy(deep=True) if item else None

    async def add_membership(self, membership: MembershipRecord) -> MembershipRecord:
        async with self._lock:
            if membership.user_id not in self._users:
                raise KeyError(f"unknown user {membership.user_id}")
            if membership.group_id not in self._groups:
                raise KeyError(f"unknown group {membership.group_id}")
            self._memberships[(membership.user_id, membership.group_id)] = membership.model_copy(
                deep=True
            )
            return membership.model_copy(deep=True)

    async def list_memberships(self, user_id: str | None = None) -> list[MembershipRecord]:
        async with self._lock:
            items = self._memberships.values()
            if user_id is not None:
                items = [item for item in items if item.user_id == user_id]
            return [item.model_copy(deep=True) for item in items]

    async def principal_for_user(self, user_id: str) -> Principal | None:
        async with self._lock:
            user = self._users.get(user_id)
            if not user or not user.active:
                return None
            memberships = [item for item in self._memberships.values() if item.user_id == user_id]
            return Principal(
                user_id=user.user_id,
                display_name=user.display_name,
                group_ids=[item.group_id for item in memberships],
                group_admin_ids=[
                    item.group_id for item in memberships if item.role is MembershipRole.GROUP_ADMIN
                ],
            )

    @staticmethod
    def _hash_token(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    async def issue_token(self, user_id: str, label: str | None = None) -> IssuedToken:
        raw = secrets.token_urlsafe(32)
        record = ApiTokenRecord(user_id=user_id, token_hash=self._hash_token(raw), label=label)
        async with self._lock:
            if user_id not in self._users:
                raise KeyError(f"unknown user {user_id}")
            self._tokens[record.token_hash] = record
        return IssuedToken(token_id=record.token_id, user_id=user_id, token=raw, label=label)

    async def principal_for_token(self, token: str) -> Principal | None:
        token_hash = self._hash_token(token)
        async with self._lock:
            record = self._tokens.get(token_hash)
            if not record or record.revoked:
                return None
            user_id = record.user_id
        return await self.principal_for_user(user_id)

    async def revoke_token(self, token_id: UUID) -> bool:
        async with self._lock:
            record = next((item for item in self._tokens.values() if item.token_id == token_id), None)
            if not record:
                return False
            record.revoked = True
            return True

    async def queue_summary(self, principal: Principal) -> dict:
        jobs = await self.list_jobs()
        active = {JobState.DISPATCHING, JobState.RUNNING}
        visible_groups = set(principal.group_ids)
        return {
            "user": {
                "queued": sum(
                    1 for job in jobs if job.owner_user_id == principal.user_id and job.state is JobState.QUEUED
                ),
                "running": sum(
                    1 for job in jobs if job.owner_user_id == principal.user_id and job.state in active
                ),
            },
            "groups": [
                {
                    "group_id": group.group_id,
                    "name": group.name,
                    "queued": sum(
                        1 for job in jobs if job.group_id == group.group_id and job.state is JobState.QUEUED
                    ),
                    "running": sum(
                        1 for job in jobs if job.group_id == group.group_id and job.state in active
                    ),
                    "policy": group.policy.model_dump(),
                }
                for group in await self.list_groups()
                if group.group_id in visible_groups
            ],
        }

    async def set_desired_release(self, manifest: ReleaseManifest) -> ReleaseManifest:
        async with self._lock:
            self._desired_release = manifest.model_copy(deep=True)
            return self._desired_release.model_copy(deep=True)

    async def get_desired_release(self) -> ReleaseManifest | None:
        async with self._lock:
            return self._desired_release.model_copy(deep=True) if self._desired_release else None

    async def seed_hosts(self, hosts: Iterable[HostView]) -> None:
        async with self._lock:
            self._hosts = {host.host_id: host.model_copy(deep=True) for host in hosts}
