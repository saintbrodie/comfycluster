import asyncio

import pytest
from fastapi.testclient import TestClient

from comfycluster_common.models import (
    GPUInfo,
    HostRegistration,
    HostView,
    JobSubmitRequest,
    WorkerSnapshot,
    WorkerState,
)
from comfycluster_controller.app import create_app
from comfycluster_controller.scheduler import Scheduler
from comfycluster_controller.sqlite_store import SQLiteFleetStore
from comfycluster_controller.store import FleetStore


def _registration() -> HostRegistration:
    return HostRegistration(
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


def test_draining_host_is_not_schedulable():
    registration = _registration()
    host = HostView(
        host_id=registration.host_id,
        hostname=registration.hostname,
        os_name=registration.os_name,
        os_version=registration.os_version,
        agent_version=registration.agent_version,
        connected=True,
        draining=True,
        gpus=registration.gpus,
        workers=registration.workers,
    )
    worker = host.workers[0]

    assessment = Scheduler().evaluate(JobSubmitRequest(workflow={}), [(host, worker)])[0]

    assert assessment.eligible is False
    assert "host_draining" in assessment.reasons


@pytest.mark.asyncio
async def test_drain_survives_reregistration():
    store = FleetStore()
    await store.register_host(_registration())
    drained = await store.set_host_draining("render-01", True)
    assert drained is not None and drained.draining is True

    reregistered = await store.register_host(_registration())
    assert reregistered.draining is True


@pytest.mark.asyncio
async def test_drain_survives_sqlite_restart(tmp_path):
    path = tmp_path / "fleet.db"
    first = SQLiteFleetStore(path)
    await first.register_host(_registration())
    await first.set_host_draining("render-01", True)
    first.close()

    second = SQLiteFleetStore(path)
    restored = await second.get_host("render-01")
    assert restored is not None
    assert restored.draining is True
    second.close()


def test_drain_and_resume_api():
    store = FleetStore()
    asyncio.run(store.register_host(_registration()))
    client = TestClient(create_app(store=store))

    drained = client.post("/api/v1/hosts/render-01/drain")
    assert drained.status_code == 200
    assert drained.json()["draining"] is True

    resumed = client.post("/api/v1/hosts/render-01/resume")
    assert resumed.status_code == 200
    assert resumed.json()["draining"] is False


def test_drain_unknown_host_is_404():
    client = TestClient(create_app())
    assert client.post("/api/v1/hosts/missing/drain").status_code == 404
