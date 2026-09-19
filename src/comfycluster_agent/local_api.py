from __future__ import annotations

from typing import Any, Protocol

from fastapi import FastAPI, HTTPException


class LocalAgent(Protocol):
    def local_status(self) -> dict[str, Any]: ...

    async def execute_action(self, action: str, payload: dict[str, Any]) -> dict[str, Any]: ...


def create_local_app(agent: LocalAgent) -> FastAPI:
    """Create the loopback-only API used by ComfyCluster Desktop.

    Binding is controlled by AgentSettings and defaults to 127.0.0.1. The API
    intentionally exposes only local worker/inventory operations. Fleet policy
    such as drain/resume remains a controller responsibility.
    """

    app = FastAPI(title="ComfyCluster Local Agent", version="0.1.0")

    @app.get("/api/v1/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/v1/status")
    async def status():
        return agent.local_status()

    @app.post("/api/v1/workers/{worker_id}/{operation}")
    async def worker_action(worker_id: str, operation: str):
        if operation not in {"start", "stop", "restart"}:
            raise HTTPException(status_code=404, detail="unknown worker operation")
        try:
            return await agent.execute_action(
                f"worker.{operation}",
                {"worker_id": worker_id},
            )
        except (KeyError, RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/v1/fleet/{operation}")
    async def fleet_action(operation: str):
        if operation not in {"start", "stop"}:
            raise HTTPException(status_code=404, detail="unknown fleet operation")
        try:
            return await agent.execute_action(f"fleet.{operation}", {})
        except (KeyError, RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/v1/inventory/refresh")
    async def refresh_inventory():
        try:
            return await agent.execute_action("inventory.refresh", {})
        except (KeyError, RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    return app
