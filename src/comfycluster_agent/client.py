from __future__ import annotations

import asyncio
import contextlib
import platform
import socket
from pathlib import Path
from uuid import UUID

import websockets

from comfycluster_common.models import AgentEvent, HostHeartbeat, HostRegistration
from comfycluster_common.protocol import parse_controller_command

from .comfy import discover_comfy
from .gpu import discover_gpus
from .inventory import scan_custom_nodes, scan_models
from .runtime import NativeWindowsRuntime
from .settings import AgentSettings

AGENT_VERSION = "0.1.0"


class AgentClient:
    def __init__(self, settings: AgentSettings) -> None:
        self.settings = settings
        self.host_id = self._host_id()
        self.gpus = discover_gpus(settings.mock_gpus)
        self.comfy = discover_comfy(settings.comfy_home)
        self.runtime = NativeWindowsRuntime(self.comfy, self.gpus, settings.base_port)
        self.nodes = scan_custom_nodes(Path(self.comfy.path)) if self.comfy else []
        self.models = scan_models(Path(self.comfy.path)) if self.comfy else []

    @staticmethod
    def _host_id() -> str:
        return socket.gethostname().lower()

    def registration(self) -> HostRegistration:
        return HostRegistration(
            host_id=self.host_id,
            hostname=socket.gethostname(),
            os_name=platform.system(),
            os_version=platform.version(),
            agent_version=AGENT_VERSION,
            gpus=self.gpus,
            comfy=self.comfy,
            workers=self.runtime.snapshots(),
            nodes=self.nodes,
            models=self.models,
        )

    async def run(self) -> None:
        if self.settings.autostart_workers and self.comfy:
            self.runtime.start_all()

        backoff = 1.0
        while True:
            try:
                async with websockets.connect(
                    self.settings.controller_url,
                    ping_interval=20,
                    ping_timeout=20,
                    max_size=16 * 1024 * 1024,
                ) as websocket:
                    await websocket.send(self.registration().model_dump_json())
                    await websocket.recv()
                    backoff = 1.0
                    heartbeat_task = asyncio.create_task(self._heartbeat_loop(websocket))
                    try:
                        async for raw in websocket:
                            await self._handle_command(websocket, raw)
                    finally:
                        heartbeat_task.cancel()
                        with contextlib.suppress(asyncio.CancelledError):
                            await heartbeat_task
            except (OSError, websockets.WebSocketException):
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)

    async def _heartbeat_loop(self, websocket) -> None:
        while True:
            self.gpus = discover_gpus(self.settings.mock_gpus)
            self.runtime.gpus = self.gpus
            await self.runtime.probe_workers()
            for terminal in await self.runtime.poll_jobs():
                event = AgentEvent(
                    host_id=self.host_id,
                    event=terminal["event"],
                    job_id=terminal["job_id"],
                    payload={"prompt_id": terminal["prompt_id"], "status": terminal["status"]},
                )
                await websocket.send(event.model_dump_json())
            heartbeat = HostHeartbeat(
                host_id=self.host_id,
                gpus=self.gpus,
                workers=self.runtime.snapshots(),
            )
            await websocket.send(heartbeat.model_dump_json())
            await asyncio.sleep(self.settings.heartbeat_seconds)

    async def _handle_command(self, websocket, raw: str | bytes) -> None:
        command = parse_controller_command(raw)
        try:
            payload = await self._execute(command.action, command.payload)
            if command.action == "job.submit":
                event = AgentEvent(
                    host_id=self.host_id,
                    event="job.accepted",
                    command_id=command.command_id,
                    job_id=UUID(payload["job_id"]),
                    payload={"prompt_id": payload["prompt_id"]},
                )
            else:
                event = AgentEvent(
                    host_id=self.host_id,
                    event="command.completed",
                    command_id=command.command_id,
                    payload=payload,
                )
        except Exception as exc:
            job_id = (
                UUID(command.payload["job_id"])
                if command.action == "job.submit" and command.payload.get("job_id")
                else None
            )
            event = AgentEvent(
                host_id=self.host_id,
                event="job.failed" if job_id else "command.failed",
                command_id=command.command_id,
                job_id=job_id,
                payload={"error": str(exc)},
            )
        await websocket.send(event.model_dump_json())

    async def _execute(self, action: str, payload: dict) -> dict:
        if action == "worker.start":
            return self.runtime.start(payload["worker_id"]).model_dump(mode="json")
        if action == "worker.stop":
            return self.runtime.stop(payload["worker_id"]).model_dump(mode="json")
        if action == "worker.restart":
            return self.runtime.restart(payload["worker_id"]).model_dump(mode="json")
        if action == "fleet.start":
            return {"workers": [w.model_dump(mode="json") for w in self.runtime.start_all()]}
        if action == "fleet.stop":
            return {"workers": [w.model_dump(mode="json") for w in self.runtime.stop_all()]}
        if action == "job.submit":
            job_id = UUID(payload["job_id"])
            try:
                prompt_id = await self.runtime.submit_job(
                    payload["worker_id"],
                    job_id,
                    payload["workflow"],
                    payload.get("client_id"),
                )
            except Exception as exc:
                raise RuntimeError(f"job {job_id} failed to submit: {exc}") from exc
            return {"job_id": str(job_id), "prompt_id": prompt_id}
        if action == "inventory.refresh":
            self.gpus = discover_gpus(self.settings.mock_gpus)
            self.comfy = discover_comfy(self.settings.comfy_home)
            self.nodes = scan_custom_nodes(Path(self.comfy.path)) if self.comfy else []
            self.models = scan_models(Path(self.comfy.path)) if self.comfy else []
            return self.registration().model_dump(mode="json")
        raise ValueError(f"unknown action: {action}")
