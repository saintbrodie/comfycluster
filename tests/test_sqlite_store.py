from pathlib import Path

import pytest

from comfycluster_common.models import (
    GPUInfo,
    HostRegistration,
    JobRecord,
    JobState,
    JobSubmitRequest,
    WorkerSnapshot,
    WorkerState,
)
from comfycluster_common.releases import ReleaseManifest
from comfycluster_controller.sqlite_store import SQLiteFleetStore


@pytest.mark.asyncio
async def test_sqlite_store_survives_restart(tmp_path: Path):
    path = tmp_path / "fleet.db"
    first = SQLiteFleetStore(path)
    registration = HostRegistration(
        host_id="render-01",
        hostname="render-01",
        os_name="Windows",
        os_version="11",
        agent_version="test",
        gpus=[GPUInfo(index=0, uuid="GPU-A", name="GPU", memory_total_mb=32768)],
        workers=[
            WorkerSnapshot(
                worker_id="w0",
                gpu_uuid="GPU-A",
                gpu_index=0,
                port=8188,
                state=WorkerState.IDLE,
            )
        ],
    )
    await first.register_host(registration)
    job = await first.create_job(JobRecord(request=JobSubmitRequest(workflow={"1": {}})))
    await first.set_job_state(job.job_id, JobState.SUCCEEDED)
    first.close()

    second = SQLiteFleetStore(path)
    hosts = await second.list_hosts()
    restored_job = await second.get_job(job.job_id)
    assert len(hosts) == 1
    assert hosts[0].connected is False
    assert hosts[0].workers[0].state is WorkerState.OFFLINE
    assert restored_job is not None
    assert restored_job.state is JobState.SUCCEEDED
    second.close()


@pytest.mark.asyncio
async def test_active_job_is_failed_after_controller_restart(tmp_path: Path):
    path = tmp_path / "fleet.db"
    first = SQLiteFleetStore(path)
    job = await first.create_job(JobRecord(request=JobSubmitRequest(workflow={})))
    await first.set_job_state(job.job_id, JobState.RUNNING)
    first.close()

    second = SQLiteFleetStore(path)
    restored = await second.get_job(job.job_id)
    assert restored is not None
    assert restored.state is JobState.FAILED
    assert "terminal state is unknown" in (restored.error or "")
    second.close()


@pytest.mark.asyncio
async def test_desired_release_survives_restart(tmp_path: Path):
    path = tmp_path / "fleet.db"
    first = SQLiteFleetStore(path)
    desired = ReleaseManifest.model_validate(
        {
            "name": "production-17",
            "comfy": {"version": "0.4.0", "commit": "abc123"},
            "nodes": [{"name": "KJNodes", "commit": "def456"}],
        }
    )
    await first.set_desired_release(desired)
    first.close()

    second = SQLiteFleetStore(path)
    restored = await second.get_desired_release()
    assert restored is not None
    assert restored == desired
    second.close()
