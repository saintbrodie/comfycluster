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


def test_desired_release_roundtrip_and_plan():
    client = TestClient(create_app())
    manifest = {
        "name": "production-17",
        "comfy": {"version": "0.4.0", "commit": "abc123"},
        "nodes": [{"name": "KJNodes", "commit": "def456"}],
    }

    missing = client.get("/api/v1/releases/desired")
    assert missing.status_code == 404

    saved = client.put("/api/v1/releases/desired", json=manifest)
    assert saved.status_code == 200
    assert saved.json()["name"] == "production-17"

    loaded = client.get("/api/v1/releases/desired")
    assert loaded.status_code == 200
    assert loaded.json()["comfy"]["commit"] == "abc123"

    plan = client.get("/api/v1/releases/plan")
    assert plan.status_code == 200
    assert plan.json() == {
        "release": "production-17",
        "host_count": 0,
        "in_sync_count": 0,
        "auto_apply_count": 0,
        "hosts": [],
    }


def test_release_manifest_rejects_unknown_fields():
    client = TestClient(create_app())
    response = client.put(
        "/api/v1/releases/desired",
        json={"name": "bad", "mystery": True},
    )
    assert response.status_code == 422
