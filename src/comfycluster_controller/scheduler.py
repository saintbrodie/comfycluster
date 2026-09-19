from __future__ import annotations

from dataclasses import dataclass, field

from comfycluster_common.models import (
    HostView,
    JobRecord,
    JobSubmitRequest,
    WorkerSnapshot,
    WorkerState,
)
from comfycluster_common.tenancy import GroupRecord

from .workflow import analyze_workflow, host_has_model


@dataclass(slots=True)
class Candidate:
    host: HostView
    worker: WorkerSnapshot
    free_vram_mb: int


@dataclass(slots=True)
class WorkerAssessment:
    host: HostView
    worker: WorkerSnapshot
    eligible: bool
    free_vram_mb: int | None = None
    reasons: list[str] = field(default_factory=list)
    missing_models: list[str] = field(default_factory=list)
    missing_node_types: list[str] = field(default_factory=list)
    capabilities_known: bool = False

    def as_dict(self) -> dict:
        return {
            "host_id": self.host.host_id,
            "hostname": self.host.hostname,
            "worker_id": self.worker.worker_id,
            "gpu_uuid": self.worker.gpu_uuid,
            "state": self.worker.state.value,
            "eligible": self.eligible,
            "free_vram_mb": self.free_vram_mb,
            "reasons": list(self.reasons),
            "missing_models": list(self.missing_models),
            "missing_node_types": list(self.missing_node_types),
            "capabilities_known": self.capabilities_known,
        }


class Scheduler:
    """Compatibility-first scheduler with weighted fair sharing between groups."""

    def __init__(self) -> None:
        self._group_virtual_runtime: dict[str, float] = {}

    def evaluate(
        self,
        request: JobSubmitRequest,
        workers: list[tuple[HostView, WorkerSnapshot]],
    ) -> list[WorkerAssessment]:
        requirements = analyze_workflow(request.workflow)
        assessments: list[WorkerAssessment] = []

        for host, worker in workers:
            reasons: list[str] = []
            free_vram_mb: int | None = None

            if not host.connected:
                reasons.append("host_disconnected")
            if host.draining:
                reasons.append("host_draining")
            if worker.state is not WorkerState.IDLE:
                reasons.append("worker_not_idle")
            if request.preferred_worker_id and worker.worker_id != request.preferred_worker_id:
                reasons.append("preferred_worker_mismatch")

            gpu = next((gpu for gpu in host.gpus if gpu.uuid == worker.gpu_uuid), None)
            if gpu is None:
                reasons.append("gpu_not_found")
            else:
                free_vram_mb = gpu.memory_free_mb
                if request.minimum_vram_mb and gpu.memory_total_mb < request.minimum_vram_mb:
                    reasons.append("insufficient_vram")

            missing_models = sorted(
                (
                    model_ref
                    for model_ref in requirements.model_refs
                    if not host_has_model(host, model_ref)
                ),
                key=str.casefold,
            )
            if missing_models:
                reasons.append("missing_models")

            capabilities_known = bool(worker.node_types)
            missing_node_types: list[str] = []
            if capabilities_known:
                available = set(worker.node_types)
                missing_node_types = sorted(
                    requirements.node_types - available,
                    key=str.casefold,
                )
                if missing_node_types:
                    reasons.append("missing_node_types")

            assessments.append(
                WorkerAssessment(
                    host=host,
                    worker=worker,
                    eligible=not reasons,
                    free_vram_mb=free_vram_mb,
                    reasons=reasons,
                    missing_models=missing_models,
                    missing_node_types=missing_node_types,
                    capabilities_known=capabilities_known,
                )
            )

        return assessments

    def choose(
        self,
        request: JobSubmitRequest,
        workers: list[tuple[HostView, WorkerSnapshot]],
    ) -> Candidate | None:
        candidates = [assessment for assessment in self.evaluate(request, workers) if assessment.eligible]
        if not candidates:
            return None
        selected = max(candidates, key=lambda item: item.free_vram_mb or 0)
        return Candidate(
            host=selected.host,
            worker=selected.worker,
            free_vram_mb=selected.free_vram_mb or 0,
        )

    def fair_group_order(
        self,
        jobs: list[JobRecord],
        groups: list[GroupRecord],
    ) -> list[str | None]:
        """Return queued groups in weighted-fair order.

        The score only advances after a successful dispatch. A weight of 2 therefore
        accrues half as much virtual runtime as a weight of 1 and receives roughly
        twice the dispatch opportunities when both groups remain backlogged.
        """
        group_map = {group.group_id: group for group in groups}
        present: list[str | None] = []
        for job in sorted(jobs, key=lambda item: item.created_at):
            if job.group_id not in present:
                present.append(job.group_id)

        def score(group_id: str | None) -> tuple[float, str]:
            return (
                self._group_virtual_runtime.get(group_id or "__legacy__", 0.0),
                group_id or "",
            )

        return sorted(present, key=score)

    def note_dispatch(self, group_id: str | None, groups: list[GroupRecord]) -> None:
        key = group_id or "__legacy__"
        group = next((item for item in groups if item.group_id == group_id), None)
        weight = group.policy.weight if group else 1.0
        self._group_virtual_runtime[key] = self._group_virtual_runtime.get(key, 0.0) + (1.0 / weight)
