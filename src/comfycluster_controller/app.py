from __future__ import annotations

from pathlib import Path
from uuid import UUID

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

from comfycluster_common.models import AgentEvent, HostHeartbeat, HostRegistration, JobRecord, JobState, JobSubmitRequest
from comfycluster_common.protocol import parse_agent_message

from .connections import AgentConnectionManager
from .scheduler import Scheduler
from .store import FleetStore

STATIC_DIR = Path(__file__).parent / "static"


def create_app(store: FleetStore | None = None, connections: AgentConnectionManager | None = None) -> FastAPI:
    app = FastAPI(title="ComfyCluster Controller", version="0.1.0")
    app.state.store = store or FleetStore()
    app.state.connections = connections or AgentConnectionManager()
    app.state.scheduler = Scheduler()

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
        candidate = app.state.scheduler.choose(request, await app.state.store.list_workers())
        if candidate is None:
            return job

        await app.state.store.set_job_state(
            job.job_id,
            JobState.DISPATCHING,
            assigned_host_id=candidate.host.host_id,
            assigned_worker_id=candidate.worker.worker_id,
        )
        try:
            await app.state.connections.send(
                candidate.host.host_id,
                "job.submit",
                {
                    "job_id": str(job.job_id),
                    "worker_id": candidate.worker.worker_id,
                    "workflow": request.workflow,
                    "client_id": request.client_id,
                },
            )
        except KeyError as exc:
            return await app.state.store.set_job_state(job.job_id, JobState.QUEUED, error=str(exc))
        return await app.state.store.get_job(job.job_id)

    @app.websocket("/api/v1/agents/ws")
    async def agent_socket(websocket: WebSocket):
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
                        await app.state.store.set_job_state(
                            message.job_id,
                            JobState.SUCCEEDED,
                            error=None,
                        )
                    elif message.event == "job.failed" and message.job_id:
                        await app.state.store.set_job_state(
                            message.job_id,
                            JobState.FAILED,
                            error=message.payload.get("error", "worker reported failure"),
                        )
        except WebSocketDisconnect:
            pass
        finally:
            if host_id:
                await app.state.connections.detach(host_id, websocket)
                await app.state.store.mark_disconnected(host_id)

    return app


app = create_app()
