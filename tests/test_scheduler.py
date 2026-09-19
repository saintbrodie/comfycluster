from comfycluster_common.models import GPUInfo, HostView, JobSubmitRequest, WorkerSnapshot, WorkerState
from comfycluster_controller.scheduler import Scheduler


def _host(host_id: str, uuid: str, total: int, used: int, state: WorkerState):
    worker = WorkerSnapshot(
        worker_id=f"{host_id}-worker",
        gpu_uuid=uuid,
        gpu_index=0,
        port=8188,
        state=state,
    )
    host = HostView(
        host_id=host_id,
        hostname=host_id,
        os_name="Windows",
        os_version="11",
        agent_version="test",
        gpus=[GPUInfo(index=0, uuid=uuid, name="GPU", memory_total_mb=total, memory_used_mb=used)],
        workers=[worker],
    )
    return host, worker


def test_scheduler_prefers_most_free_vram():
    scheduler = Scheduler()
    workers = [
        _host("a", "GPU-A", 32768, 20000, WorkerState.IDLE),
        _host("b", "GPU-B", 32768, 2000, WorkerState.IDLE),
        _host("c", "GPU-C", 32768, 0, WorkerState.BUSY),
    ]
    candidate = scheduler.choose(JobSubmitRequest(workflow={}), workers)
    assert candidate is not None
    assert candidate.host.host_id == "b"


def test_scheduler_honors_minimum_vram():
    scheduler = Scheduler()
    workers = [_host("a", "GPU-A", 16384, 0, WorkerState.IDLE)]
    candidate = scheduler.choose(JobSubmitRequest(workflow={}, minimum_vram_mb=24000), workers)
    assert candidate is None


def test_scheduler_avoids_reserved_worker():
    scheduler = Scheduler()
    host, worker = _host("a", "GPU-A", 32768, 0, WorkerState.BUSY)
    worker.current_job_id = __import__("uuid").uuid4()
    host.workers = [worker]
    candidate = scheduler.choose(JobSubmitRequest(workflow={}), [(host, worker)])
    assert candidate is None
