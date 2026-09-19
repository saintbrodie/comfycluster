from fastapi.testclient import TestClient

from comfycluster_agent.local_api import create_local_app


class DummyAgent:
    def __init__(self) -> None:
        self.actions: list[tuple[str, dict]] = []

    def local_status(self) -> dict:
        return {
            "controller_connected": True,
            "controller_url": "ws://controller:9320/api/v1/agents/ws",
            "registration": {"host_id": "render-01", "workers": []},
        }

    async def execute_action(self, action: str, payload: dict) -> dict:
        self.actions.append((action, payload))
        return {"action": action, "payload": payload}


def test_local_agent_status_and_worker_controls():
    agent = DummyAgent()
    client = TestClient(create_local_app(agent))

    response = client.get("/api/v1/status")
    assert response.status_code == 200
    assert response.json()["registration"]["host_id"] == "render-01"

    response = client.post("/api/v1/workers/gpu-0/restart")
    assert response.status_code == 200
    assert agent.actions[-1] == ("worker.restart", {"worker_id": "gpu-0"})


def test_local_agent_rejects_unknown_operations():
    agent = DummyAgent()
    client = TestClient(create_local_app(agent))

    assert client.post("/api/v1/workers/gpu-0/explode").status_code == 404
    assert client.post("/api/v1/fleet/restart").status_code == 404


def test_local_agent_inventory_refresh():
    agent = DummyAgent()
    client = TestClient(create_local_app(agent))

    response = client.post("/api/v1/inventory/refresh")
    assert response.status_code == 200
    assert agent.actions[-1] == ("inventory.refresh", {})
