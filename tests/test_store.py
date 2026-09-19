from uuid import uuid4

import pytest

from comfycluster_common.models import GPUInfo, HostHeartbeat, HostRegistration, WorkerSnapshot, WorkerState
from comfycluster_controller.store import FleetStore


@pytest.mark.asyncio
async def test_heartbeat_does_not_clear_controller_reservation():
    store = FleetStore()
    worker = WorkerSnapshot(worker_id="w", gpu_uuid="GPU-A", gpu_index=0, port=8188, state=WorkerState.IDLE)
    registration = HostRegistration(
        host_id="host",
        hostname="host",
        os_name="Windows",
        os_version="11",
        agent_version="test",
        gpus=[GPUInfo(index=0, uuid="GPU-A", name="GPU", memory_total_mb=32768)],
        workers=[worker],
    )
    await store.register_host(registration)
    job_id = uuid4()
    await store.update_worker("host", "w", state=WorkerState.BUSY, current_job_id=job_id)

    heartbeat = HostHeartbeat(
        host_id="host",
        gpus=registration.gpus,
        workers=[worker],
    )
    view = await store.heartbeat(heartbeat)
    assert view is not None
    assert view.workers[0].state is WorkerState.BUSY
    assert view.workers[0].current_job_id == job_id
