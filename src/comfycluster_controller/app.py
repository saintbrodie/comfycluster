from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

from comfycluster_common.models import (
    AgentEvent,
    HostHeartbeat,
    HostRegistration,
    JobRecord,
    JobState,
    JobSubmitRequest,
    WorkerState,
)
from comfycluster_common.protocol import parse_agent_message
from comfycluster_common.releases import ReleaseManifest
from comfycluster_common.tenancy import (
    GroupRecord,
    MembershipRecord,
    Principal,
    UserRecord,
)

from .connections import AgentConnectionManager
from .inventory import compare_release, model_matrix, node_matrix
from .releases import plan_release
from .scheduler import Scheduler
from .security import agent_authorized, authenticate_principal
from .settings import ControllerSettings, create_configured_store
from .store import FleetStore, QuotaExceededError
from .workflow import analyze_workflow

STATIC_DIR = Path(__file__).parent / "static"


def create_app(
    store: FleetStore | None = None,
    connections: AgentConnectionManager | None = None,
    agent_token: str | None = None,
    admin_token: str | None = None,
) -> FastAPI:
    app = FastAPI(title="ComfyCluster Controller", version="0.2.0")
    app.state.store = store or FleetStore()
    app.state.connections = connections or AgentConnectionManager()
    app.state.scheduler = Scheduler()
    app.state.dispatch_lock = asyncio.Lock()
    app.state.agent_token = agent_token
    app.state.admin_token = admin_token

    async def current_principal(
        authorization: str | None = Header(default=None),
    ) -> Principal:
        principal = await authenticate_principal(
            authorization,
            app.state.store,
            app.state.admin_token,
        )
        if principal is None:
            raise HTTPException(
                status_code=401,
                detail="authentication required",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return principal

    async def require_admin(principal: Principal = Depends(current_principal)) -> Principal:
        if not principal.platform_admin:
            raise HTTPException(status_code=403, detail="platform administrator required")
        return principal

    async def dispatch_job(job: JobRecord):
        async with app.state.dispatch_lock:
            fresh_job = await app.state.store.get_job(job.job_id)
            if fresh_job is None or fresh_job.state is not JobState.QUEUED:
                return fresh_job
            allowed, _ = await app.state.store.can_dispatch(fresh_job)
            if not allowed:
                return fresh_job
            candidate = app.state.scheduler.choose(
                fresh_job.request, await app.state.store.list_workers()
            )
            if candidate is None:
                return fresh_job

            await app.state.store.update_worker(
                candidate.host.host_id,
                candidate.worker.worker_id,
                state=WorkerState.BUSY,
                current_job_id=fresh_job.job_id,
            )
            await app.state.store.set_job_state(
                fresh_job.job_id,
                JobState.DISPATCHING,
                assigned_host_id=candidate.host.host_id,
                assigned_worker_id=candidate.worker.worker_id,
                error=None,
            )
            try:
                await app.state.connections.send(
                    candidate.host.host_id,
                    "job.submit",
                    {
                        "job_id": str(fresh_job.job_id),
                        "worker_id": candidate.worker.worker_id,
                        "workflow": fresh_job.request.workflow,
                        "client_id": fresh_job.request.client_id,
                    },
                )
            except KeyError as exc:
                await app.state.store.update_worker(
                    candidate.host.host_id,
                    candidate.worker.worker_id,
                    state=WorkerState.IDLE,
                    current_job_id=None,
                )
                return await app.state.store.set_job_state(
                    fresh_job.job_id, JobState.QUEUED, error=str(exc)
                )
            groups = await app.state.store.list_groups()
            app.state.scheduler.note_dispatch(fresh_job.group_id, groups)
            return await app.state.store.get_job(fresh_job.job_id)

    async def dispatch_queued_jobs() -> None:
        while True:
            jobs = [
                job for job in await app.state.store.list_jobs() if job.state is JobState.QUEUED
            ]
            if not jobs:
                return
            groups = await app.state.store.list_groups()
            dispatched = False
            for group_id in app.state.scheduler.fair_group_order(jobs, groups):
                group_jobs = sorted(
                    (job for job in jobs if job.group_id == group_id),
                    key=lambda item: item.created_at,
                )
                for queued in group_jobs:
                    allowed, _ = await app.state.store.can_dispatch(queued)
                    if not allowed:
                        continue
                    candidate = app.state.scheduler.choose(
                        queued.request, await app.state.store.list_workers()
                    )
                    if candidate is None:
                        continue
                    result = await dispatch_job(queued)
                    if result and result.state is not JobState.QUEUED:
                        dispatched = True
                        break
                if dispatched:
                    break
            if not dispatched:
                return

    @app.get("/")
    async def dashboard() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/v1/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/v1/me")
    async def me(principal: Principal = Depends(current_principal)):
        return principal

    @app.get("/api/v1/groups")
    async def my_groups(principal: Principal = Depends(current_principal)):
        groups = await app.state.store.list_groups()
        return [group for group in groups if group.group_id in principal.group_ids]

    @app.get("/api/v1/queue/summary")
    async def queue_summary(principal: Principal = Depends(current_principal)):
        return await app.state.store.queue_summary(principal)

    @app.post("/api/v1/admin/groups")
    async def create_group(
        group: GroupRecord,
        _: Principal = Depends(require_admin),
    ):
        return await app.state.store.create_group(group)

    @app.get("/api/v1/admin/groups")
    async def admin_groups(_: Principal = Depends(require_admin)):
        return await app.state.store.list_groups()

    @app.post("/api/v1/admin/users")
    async def create_user(
        user: UserRecord,
        _: Principal = Depends(require_admin),
    ):
        return await app.state.store.create_user(user)

    @app.get("/api/v1/admin/users")
    async def admin_users(_: Principal = Depends(require_admin)):
        return await app.state.store.list_users()

    @app.post("/api/v1/admin/memberships")
    async def add_membership(
        membership: MembershipRecord,
        _: Principal = Depends(require_admin),
    ):
        try:
            return await app.state.store.add_membership(membership)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/v1/admin/users/{user_id}/tokens")
    async def issue_user_token(
        user_id: str,
        payload: dict | None = None,
        _: Principal = Depends(require_admin),
    ):
        try:
            return await app.state.store.issue_token(user_id, (payload or {}).get("label"))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.delete("/api/v1/admin/tokens/{token_id}", status_code=204)
    async def revoke_user_token(
        token_id: UUID,
        _: Principal = Depends(require_admin),
    ):
        if not await app.state.store.revoke_token(token_id):
            raise HTTPException(status_code=404, detail="token not found")

    @app.get("/api/v1/admin/jobs")
    async def admin_job_summaries(_: Principal = Depends(require_admin)):
        return await app.state.store.list_job_summaries()

    @app.get("/api/v1/hosts")
    async def hosts(_: Principal = Depends(current_principal)):
        return await app.state.store.list_hosts()

    @app.post("/api/v1/hosts/{host_id}/drain")
    async def drain_host(host_id: str, _: Principal = Depends(require_admin)):
        host = await app.state.store.set_host_draining(host_id, True)
        if host is None:
            raise HTTPException(status_code=404, detail="host not found")
        return host

    @app.post("/api/v1/hosts/{host_id}/resume")
    async def resume_host(host_id: str, _: Principal = Depends(require_admin)):
        host = await app.state.store.set_host_draining(host_id, False)
        if host is None:
            raise HTTPException(status_code=404, detail="host not found")
        await dispatch_queued_jobs()
        return host

    @app.get("/api/v1/workers")
    async def workers(_: Principal = Depends(current_principal)):
        entries = await app.state.store.list_workers()
        return [{"host": host, "worker": worker} for host, worker in entries]

    @app.get("/api/v1/hosts/{host_id}/inventory")
    async def host_inventory(host_id: str, _: Principal = Depends(current_principal)):
        host = await app.state.store.get_host(host_id)
        if not host:
            raise HTTPException(status_code=404, detail="host not found")
        return {"host_id": host_id, "nodes": host.nodes, "models": host.models}

    @app.get("/api/v1/models")
    async def cluster_models(_: Principal = Depends(current_principal)):
        return model_matrix(await app.state.store.list_hosts())

    @app.get("/api/v1/nodes")
    async def cluster_nodes(_: Principal = Depends(current_principal)):
        return node_matrix(await app.state.store.list_hosts())

    @app.post("/api/v1/releases/compare")
    async def release_compare(
        manifest: ReleaseManifest,
        _: Principal = Depends(current_principal),
    ):
        hosts = await app.state.store.list_hosts()
        return {
            "release": manifest.name,
            "hosts": [compare_release(host, manifest) for host in hosts],
        }

    @app.put("/api/v1/releases/desired")
    async def set_desired_release(
        manifest: ReleaseManifest,
        _: Principal = Depends(require_admin),
    ):
        return await app.state.store.set_desired_release(manifest)

    @app.get("/api/v1/releases/desired")
    async def get_desired_release(_: Principal = Depends(current_principal)):
        manifest = await app.state.store.get_desired_release()
        if manifest is None:
            raise HTTPException(status_code=404, detail="desired release not configured")
        return manifest

    @app.get("/api/v1/releases/plan")
    async def release_plan(_: Principal = Depends(current_principal)):
        manifest = await app.state.store.get_desired_release()
        if manifest is None:
            raise HTTPException(status_code=404, detail="desired release not configured")
        return plan_release(await app.state.store.list_hosts(), manifest)

    @app.post("/api/v1/workflows/analyze")
    async def workflow_analyze(
        workflow: dict,
        _: Principal = Depends(current_principal),
    ):
        return analyze_workflow(workflow).as_dict()

    @app.post("/api/v1/workflows/compatibility")
    async def workflow_compatibility(
        request: JobSubmitRequest,
        _: Principal = Depends(current_principal),
    ):
        requirements = analyze_workflow(request.workflow)
        assessments = app.state.scheduler.evaluate(
            request,
            await app.state.store.list_workers(),
        )
        return {
            "requirements": requirements.as_dict(),
            "eligible_workers": [
                assessment.worker.worker_id for assessment in assessments if assessment.eligible
            ],
            "workers": [assessment.as_dict() for assessment in assessments],
        }

    @app.post("/api/v1/hosts/{host_id}/commands/{action}")
    async def host_command(
        host_id: str,
        action: str,
        payload: dict | None = None,
        _: Principal = Depends(require_admin),
    ):
        try:
            command_id = await app.state.connections.send(host_id, action, payload or {})
        except KeyError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"command_id": command_id, "status": "sent"}

    @app.get("/api/v1/jobs")
    async def list_jobs(principal: Principal = Depends(current_principal)):
        return await app.state.store.list_jobs_for_principal(principal)

    @app.get("/api/v1/jobs/{job_id}")
    async def get_job(job_id: UUID, principal: Principal = Depends(current_principal)):
        job = await app.state.store.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="job not found")
        if not app.state.store.principal_can_view_job(principal, job):
            raise HTTPException(status_code=404, detail="job not found")
        return job

    @app.post("/api/v1/jobs", status_code=202)
    async def submit_job(
        request: JobSubmitRequest,
        principal: Principal = Depends(current_principal),
    ):
        group_id = request.group_id
        if group_id:
            if not principal.belongs_to(group_id) and not principal.content_auditor:
                raise HTTPException(status_code=403, detail="not a member of requested group")
            if not await app.state.store.get_group(group_id):
                raise HTTPException(status_code=404, detail="group not found")
        elif len(principal.group_ids) == 1:
            group_id = principal.group_ids[0]
        elif principal.user_id != "dev-admin":
            raise HTTPException(status_code=400, detail="group_id is required")

        request = request.model_copy(update={"group_id": group_id})
        job = JobRecord(
            request=request,
            owner_user_id=principal.user_id,
            group_id=group_id,
            visibility=request.visibility,
        )
        try:
            created = await app.state.store.create_job_enforcing_quotas(job)
        except QuotaExceededError as exc:
            raise HTTPException(
                status_code=429,
                detail={
                    "error": "queue_limit_reached",
                    "scope": exc.scope,
                    "limit": exc.limit,
                    "current": exc.current,
                },
            ) from exc
        await dispatch_queued_jobs()
        return await app.state.store.get_job(created.job_id)

    @app.post("/api/v1/jobs/{job_id}/cancel", status_code=202)
    async def cancel_job(
        job_id: UUID,
        principal: Principal = Depends(current_principal),
    ):
        job = await app.state.store.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="job not found")
        can_cancel = (
            principal.platform_admin
            or job.owner_user_id == principal.user_id
            or principal.administers(job.group_id)
        )
        if not can_cancel:
            raise HTTPException(status_code=404, detail="job not found")
        if job.state in {JobState.SUCCEEDED, JobState.FAILED, JobState.CANCELED}:
            return job
        if job.state is JobState.QUEUED:
            return await app.state.store.set_job_state(job_id, JobState.CANCELED)
        if not job.assigned_host_id or not job.assigned_worker_id:
            return await app.state.store.set_job_state(job_id, JobState.CANCELED)
        try:
            await app.state.connections.send(
                job.assigned_host_id,
                "job.cancel",
                {
                    "job_id": str(job.job_id),
                    "worker_id": job.assigned_worker_id,
                    "prompt_id": job.comfy_prompt_id,
                },
            )
        except KeyError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return job

    @app.websocket("/api/v1/agents/ws")
    async def agent_socket(websocket: WebSocket):
        if not agent_authorized(websocket.headers.get("authorization"), app.state.agent_token):
            await websocket.close(code=1008, reason="unauthorized agent")
            return

        await websocket.accept()
        host_id: str | None = None
        try:
            first = parse_agent_message(await websocket.receive_text())
            if not isinstance(first, HostRegistration):
                await websocket.close(code=1008, reason="first message must be register")
                return
            host_id = first.host_id
            await app.state.store.register_host(first)
            await app.state.connections.attach(host_id, websocket)
            await websocket.send_json({"type": "registered", "host_id": host_id})

            while True:
                message = parse_agent_message(await websocket.receive_text())
                if isinstance(message, HostHeartbeat):
                    await app.state.store.heartbeat(message)
                    await dispatch_queued_jobs()
                elif isinstance(message, HostRegistration):
                    await app.state.store.register_host(message)
                elif isinstance(message, AgentEvent):
                    if message.event == "job.accepted" and message.job_id:
                        await app.state.store.set_job_state(
                            message.job_id,
                            JobState.RUNNING,
                            comfy_prompt_id=message.payload.get("prompt_id"),
                            error=None,
                        )
                    elif message.event == "job.completed" and message.job_id:
                        finished = await app.state.store.set_job_state(
                            message.job_id,
                            JobState.SUCCEEDED,
                            error=None,
                            outputs=message.payload.get("outputs", {}),
                        )
                        if finished and finished.assigned_host_id and finished.assigned_worker_id:
                            await app.state.store.update_worker(
                                finished.assigned_host_id,
                                finished.assigned_worker_id,
                                state=WorkerState.IDLE,
                                current_job_id=None,
                            )
                        await dispatch_queued_jobs()
                    elif message.event == "job.canceled" and message.job_id:
                        canceled = await app.state.store.set_job_state(
                            message.job_id,
                            JobState.CANCELED,
                            error=None,
                        )
                        if canceled and canceled.assigned_host_id and canceled.assigned_worker_id:
                            await app.state.store.update_worker(
                                canceled.assigned_host_id,
                                canceled.assigned_worker_id,
                                state=WorkerState.IDLE,
                                current_job_id=None,
                            )
                        await dispatch_queued_jobs()
                    elif message.event == "job.cancel_failed" and message.job_id:
                        await app.state.store.update_job(
                            message.job_id,
                            error=message.payload.get("error", "worker failed to cancel job"),
                        )
                    elif message.event == "job.failed" and message.job_id:
                        failed = await app.state.store.set_job_state(
                            message.job_id,
                            JobState.FAILED,
                            error=message.payload.get("error", "worker reported failure"),
                        )
                        if failed and failed.assigned_host_id and failed.assigned_worker_id:
                            await app.state.store.update_worker(
                                failed.assigned_host_id,
                                failed.assigned_worker_id,
                                state=WorkerState.IDLE,
                                current_job_id=None,
                            )
                        await dispatch_queued_jobs()
        except WebSocketDisconnect:
            pass
        finally:
            if host_id:
                await app.state.connections.detach(host_id, websocket)
                await app.state.store.mark_disconnected(host_id)

    return app


_controller_settings = ControllerSettings()
app = create_app(
    create_configured_store(),
    agent_token=_controller_settings.agent_token,
    admin_token=_controller_settings.admin_token,
)
