from fastapi.testclient import TestClient

from comfycluster_common.models import AgentEvent, GPUInfo, HostRegistration, WorkerSnapshot, WorkerState
from comfycluster_controller.app import create_app


def test_agent_registration_job_dispatch_and_completion():
    client = TestClient(create_app())
    registration = HostRegistration(
        host_id="render-01",
        hostname="render-01",
        os_name="Windows",
        os_version="11",
        agent_version="test",
        gpus=[GPUInfo(index=0, uuid="GPU-A", name="RTX", memory_total_mb=32768)],
        workers=[
            WorkerSnapshot(
                worker_id="render-01-gpu0",
                gpu_uuid="GPU-A",
                gpu_index=0,
                port=8188,
                state=WorkerState.IDLE,
            )
        ],
    )

    with client.websocket_connect("/api/v1/agents/ws") as ws:
        ws.send_text(registration.model_dump_json())
        assert ws.receive_json()["type"] == "registered"

        response = client.post("/api/v1/jobs", json={"workflow": {"1": {"class_type": "Test"}}})
        assert response.status_code == 202
        job = response.json()
        assert job["state"] == "dispatching"

        command = ws.receive_json()
        assert command["action"] == "job.submit"
        assert command["payload"]["worker_id"] == "render-01-gpu0"

        ws.send_text(
            AgentEvent(
                host_id="render-01",
                event="job.accepted",
                job_id=job["job_id"],
                payload={"prompt_id": "prompt-123"},
            ).model_dump_json()
        )
        running = client.get(f"/api/v1/jobs/{job['job_id']}").json()
        assert running["state"] == "running"
        assert running["comfy_prompt_id"] == "prompt-123"

        ws.send_text(
            AgentEvent(
                host_id="render-01",
                event="job.completed",
                job_id=job["job_id"],
                payload={"outputs": {"9": {"images": [{"filename": "out.png"}]}}},
            ).model_dump_json()
        )
        completed = client.get(f"/api/v1/jobs/{job['job_id']}").json()
        assert completed["state"] == "succeeded"
        assert completed["outputs"]["9"]["images"][0]["filename"] == "out.png"


def test_cancel_failure_does_not_mark_job_failed():
    client = TestClient(create_app())
    registration = HostRegistration(
        host_id="render-01",
        hostname="render-01",
        os_name="Windows",
        os_version="11",
        agent_version="test",
        gpus=[GPUInfo(index=0, uuid="GPU-A", name="RTX", memory_total_mb=32768)],
        workers=[
            WorkerSnapshot(
                worker_id="render-01-gpu0",
                gpu_uuid="GPU-A",
                gpu_index=0,
                port=8188,
                state=WorkerState.IDLE,
            )
        ],
    )

    with client.websocket_connect("/api/v1/agents/ws") as ws:
        ws.send_text(registration.model_dump_json())
        ws.receive_json()
        job = client.post("/api/v1/jobs", json={"workflow": {}}).json()
        ws.receive_json()
        ws.send_text(
            AgentEvent(
                host_id="render-01",
                event="job.accepted",
                job_id=job["job_id"],
                payload={"prompt_id": "prompt-123"},
            ).model_dump_json()
        )
        assert client.get(f"/api/v1/jobs/{job['job_id']}").json()["state"] == "running"

        response = client.post(f"/api/v1/jobs/{job['job_id']}/cancel")
        assert response.status_code == 202
        cancel_command = ws.receive_json()
        assert cancel_command["action"] == "job.cancel"
        ws.send_text(
            AgentEvent(
                host_id="render-01",
                event="job.cancel_failed",
                job_id=job["job_id"],
                payload={"error": "cancel endpoint unavailable"},
            ).model_dump_json()
        )
        current = client.get(f"/api/v1/jobs/{job['job_id']}").json()
        assert current["state"] == "running"
        assert current["error"] == "cancel endpoint unavailable"
