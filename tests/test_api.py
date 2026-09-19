from fastapi.testclient import TestClient

from comfycluster_controller.app import create_app


def test_health():
    client = TestClient(create_app())
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_empty_fleet():
    client = TestClient(create_app())
    response = client.get("/api/v1/hosts")
    assert response.status_code == 200
    assert response.json() == []
