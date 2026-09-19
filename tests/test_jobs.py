from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from comfycluster_common.models import JobRecord, JobState, JobSubmitRequest
from comfycluster_controller.app import create_app
from comfycluster_controller.store import FleetStore


@pytest.mark.asyncio
async def test_queued_job_can_be_canceled_without_worker():
    store = FleetStore()
    job = await store.create_job(JobRecord(request=JobSubmitRequest(workflow={})))
    assert job.state is JobState.QUEUED
    canceled = await store.set_job_state(job.job_id, JobState.CANCELED)
    assert canceled is not None
    assert canceled.state is JobState.CANCELED


def test_missing_job_cancel_returns_404():
    client = TestClient(create_app())
    response = client.post(f"/api/v1/jobs/{uuid4()}/cancel")
    assert response.status_code == 404
