from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import UUID

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
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

from .connections import AgentConnectionManager
from .inventory import compare_release, model_matrix, node_matrix
from .scheduler import Scheduler
from .security import agent_authorized
from .settings import ControllerSettings, create_configured_store
from .store import FleetStore
from .workflow import analyze_workflow

STATIC_DIR = Path(__file__).parent / "static"


def create_app(
    store: FleetStore | None = None,
    connections: AgentConnectionManager | None = None,
    agent_token: str | None = None,
) -> FastAPI:
    app = FastAPI(title="ComfyCluster Controller", version="0.1.0")
    app.state.store = store or FleetStore()
    app.state.connections = connections or AgentConnectionManager()
    app.state.scheduler = Scheduler()
    app.state.dispatch_lock = asyncio.Lock()
    app.state.agent_token = agent_token

    async def dispatch_job(job: JobRecord):
        async with app.state.dispatch_lock:
            fresh_job = await app.state.store.get_job(job.job_id)
            if fresh_job is None or fresh_job.state is not JobState.QUEUED:
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
            return await app.state.store.get_job(fresh_job.job_id)

    async def dispatch_queued_jobs() -> None:
        jobs = await app.state.store.list_jobs()
        for queued in reversed(jobs):
            if queued.state is JobState.QUEUED:
                await dispatch_job(queued)

    @app.get("/")
    async def dashboard() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/v1/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/v1/hosts")
    async def hosts():
        return await app.state.store.list_hosts()

    @app.get("/api/v1/workers")
    async def workers():
        entries = await app.state.store.list_workers()
        return [{"host": host, "worker": worker} for host, worker in entries]

    @app.get("/api/v1/hosts/{host_id}/inventory")
    async def host_inventory(host_id: str):
        host = await app.state.store.get_host(host_id)
        if not host:
            raise HTTPException(status_code=404, detail="host not found")
        return {"host_id": host_id, "nodes": host.nodes, "models": host.models}

    @app.get("/api/v1/models")
    async def cluster_models():
        return model_matrix(await app.state.store.list_hosts())

    @app.get("/api/v1/nodes")
    async def cluster_nodes():
        return node_matrix(await app.state.store.list_hosts())

    @app.post("/api/v1/releases/compare")
    async def release_compare(manifest: dict):
        hosts = await app.state.store.list_hosts()
        return {
            "release": manifest.get("name"),
            "hosts": [compare_release(host, manifest) for host in hosts],
        }

    @app.post("/api/v1/workflows/analyze")
    async def workflow_analyze(workflow: dict):
        return analyze_workflow(workflow).as_dict()

    @app.post("/api/v1/workflows/compatibility")
    async def workflow_compatibility(request: JobSubmitRequest):
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
    async def host_command(host_id: str, action: str, payload: dict | None = None):
        try:
            command_id = await app.state.connections.send(host_id, action, payload or {})
        except KeyError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"command_id": command_id, "status": "sent"}

    @app.get("/api/v1/jobs")
    async def list_jobs():
        return await app.state.store.list_jobs()

    @app.get("/api/v1/jobs/{job_id}")
    async def get_job(job_id: UUID):
        job = await app.state.store.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="job not found")
        return job

    @app.post("/api/v1/jobs", status_code=202)
    async def submit_job(request: JobSubmitRequest):
        job = await app.state.store.create_job(JobRecord(request=request))
        return await dispatch_job(job)

    @app.post("/api/v1/jobs/{job_id}/cancel", status_code=202)
    async def cancel_job(job_id: UUID):
        job = await app.state.store.get_job(job_id)
        if not job:
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
app = create_app(create_configured_store(), agent_token=_controller_settings.agent_token)
