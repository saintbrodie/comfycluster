from __future__ import annotations

import asyncio
from uuid import UUID

from fastapi import WebSocket

from comfycluster_common.models import ControllerCommand


class AgentConnectionManager:
    def __init__(self) -> None:
        self._connections: dict[str, WebSocket] = {}
        self._lock = asyncio.Lock()

    async def attach(self, host_id: str, websocket: WebSocket) -> None:
        async with self._lock:
            self._connections[host_id] = websocket

    async def detach(self, host_id: str, websocket: WebSocket | None = None) -> None:
        async with self._lock:
            current = self._connections.get(host_id)
            if current and (websocket is None or current is websocket):
                self._connections.pop(host_id, None)

    async def connected_hosts(self) -> set[str]:
        async with self._lock:
            return set(self._connections)

    async def send(self, host_id: str, action: str, payload: dict | None = None) -> UUID:
        async with self._lock:
            websocket = self._connections.get(host_id)
        if websocket is None:
            raise KeyError(f"host {host_id!r} is not connected")
        command = ControllerCommand(action=action, payload=payload or {})
        await websocket.send_text(command.model_dump_json())
        return command.command_id
