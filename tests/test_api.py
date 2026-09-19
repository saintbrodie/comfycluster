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


def test_workflow_compatibility_empty_fleet():
    client = TestClient(create_app())
    response = client.post(
        "/api/v1/workflows/compatibility",
        json={
            "workflow": {
                "1": {
                    "class_type": "FancyCustomNode",
                    "inputs": {"ckpt_name": "flux.safetensors"},
                }
            }
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["requirements"]["node_types"] == ["FancyCustomNode"]
    assert body["requirements"]["model_refs"] == ["flux.safetensors"]
    assert body["eligible_workers"] == []
    assert body["workers"] == []
