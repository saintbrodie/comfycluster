from __future__ import annotations

from dataclasses import dataclass

from comfycluster_common.models import HostView, JobSubmitRequest, WorkerSnapshot, WorkerState

from .workflow import analyze_workflow, host_has_model


@dataclass(slots=True)
class Candidate:
    host: HostView
    worker: WorkerSnapshot
    free_vram_mb: int


class Scheduler:
    """Deliberately boring first scheduler: compatible + idle + most free VRAM."""

    def choose(
        self,
        request: JobSubmitRequest,
        workers: list[tuple[HostView, WorkerSnapshot]],
    ) -> Candidate | None:
        candidates: list[Candidate] = []
        requirements = analyze_workflow(request.workflow)
        for host, worker in workers:
            if not host.connected or worker.state is not WorkerState.IDLE:
                continue
            if request.preferred_worker_id and worker.worker_id != request.preferred_worker_id:
                continue
            gpu = next((gpu for gpu in host.gpus if gpu.uuid == worker.gpu_uuid), None)
            if gpu is None:
                continue
            if request.minimum_vram_mb and gpu.memory_total_mb < request.minimum_vram_mb:
                continue
            if any(not host_has_model(host, model_ref) for model_ref in requirements.model_refs):
                continue
            candidates.append(Candidate(host=host, worker=worker, free_vram_mb=gpu.memory_free_mb))

        if not candidates:
            return None
        return max(candidates, key=lambda item: item.free_vram_mb)
