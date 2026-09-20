from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from comfycluster_common.models import JobRecord, JobState, JobSubmitRequest
from comfycluster_controller.app import create_app
from comfycluster_controller.store import FleetStore


ADMIN = {"Authorization": "Bearer admin-secret"}


def test_job_summary_runtime_excludes_private_payload():
    started = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)
    job = JobRecord(
        request=JobSubmitRequest(workflow={"secret": {"class_type": "SecretNode"}}),
        owner_user_id="alice",
        group_id="creative",
        state=JobState.SUCCEEDED,
        started_at=started,
        completed_at=started + timedelta(seconds=12.5),
        outputs={"private": {"images": [{"filename": "secret.png"}]}},
        assigned_gpu_name="RTX 5000 Ada",
    )

    summary = job.model_dump()
    assert summary["request"]["workflow"]
    from comfycluster_common.models import JobSummary

    safe = JobSummary.from_job(job).model_dump()
    assert safe["runtime_seconds"] == 12.5
    assert safe["assigned_gpu_name"] == "RTX 5000 Ada"
    assert "request" not in safe
    assert "outputs" not in safe


def test_admin_usage_aggregates_runtime_without_content():
    store = FleetStore()
    started = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)
    import asyncio

    async def seed():
        await store.create_job(
            JobRecord(
                request=JobSubmitRequest(workflow={"private": "alpha"}),
                owner_user_id="alice",
                group_id="alpha",
                state=JobState.SUCCEEDED,
                started_at=started,
                completed_at=started + timedelta(seconds=30),
            )
        )
        await store.create_job(
            JobRecord(
                request=JobSubmitRequest(workflow={"private": "beta"}),
                owner_user_id="bob",
                group_id="beta",
                state=JobState.SUCCEEDED,
                started_at=started,
                completed_at=started + timedelta(seconds=10),
            )
        )

    asyncio.run(seed())
    client = TestClient(create_app(store=store, admin_token="admin-secret"))
    response = client.get("/api/v1/admin/usage", headers=ADMIN)
    assert response.status_code == 200
    body = response.json()
    assert body["gpu_seconds"] == 40.0
    assert body["groups"][0] == {
        "group_id": "alpha",
        "gpu_seconds": 30.0,
        "completed_jobs": 1,
    }
    serialized = str(body)
    assert "private" not in serialized
    assert "alpha\"" not in serialized
