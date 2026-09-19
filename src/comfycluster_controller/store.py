from __future__ import annotations

import asyncio
from collections.abc import Iterable
from datetime import UTC, datetime
from uuid import UUID

from comfycluster_common.models import (
    HostHeartbeat,
    HostRegistration,
    HostView,
    JobRecord,
    JobState,
    WorkerSnapshot,
    WorkerState,
)


class FleetStore:
    """Small in-memory store for the first vertical slice.

    The public methods intentionally resemble repository operations so this can
    be swapped for SQLAlchemy/PostgreSQL without changing the scheduler/API.
    """

    def __init__(self) -> None:
        self._hosts: dict[str, HostView] = {}
        self._jobs: dict[UUID, JobRecord] = {}
        self._lock = asyncio.Lock()

    async def register_host(self, registration: HostRegistration) -> HostView:
        async with self._lock:
            view = HostView(
                host_id=registration.host_id,
                hostname=registration.hostname,
                os_name=registration.os_name,
                os_version=registration.os_version,
                agent_version=registration.agent_version,
                connected=True,
                last_seen=datetime.now(UTC),
                gpus=registration.gpus,
                comfy=registration.comfy,
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
            host.workers = heartbeat.workers
            return host.model_copy(deep=True)

    async def mark_disconnected(self, host_id: str) -> None:
        async with self._lock:
            host = self._hosts.get(host_id)
            if host:
                host.connected = False
                for worker in host.workers:
                    worker.state = WorkerState.OFFLINE

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

    async def create_job(self, job: JobRecord) -> JobRecord:
        async with self._lock:
            self._jobs[job.job_id] = job
            return job.model_copy(deep=True)

    async def get_job(self, job_id: UUID) -> JobRecord | None:
        async with self._lock:
            job = self._jobs.get(job_id)
            return job.model_copy(deep=True) if job else None

    async def list_jobs(self) -> list[JobRecord]:
        async with self._lock:
            jobs = sorted(self._jobs.values(), key=lambda item: item.created_at, reverse=True)
            return [job.model_copy(deep=True) for job in jobs]

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

    async def seed_hosts(self, hosts: Iterable[HostView]) -> None:
        async with self._lock:
            self._hosts = {host.host_id: host.model_copy(deep=True) for host in hosts}
