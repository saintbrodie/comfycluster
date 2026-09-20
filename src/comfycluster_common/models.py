from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


def utcnow() -> datetime:
    return datetime.now(UTC)


class WorkerState(StrEnum):
    OFFLINE = "offline"
    STOPPED = "stopped"
    STARTING = "starting"
    IDLE = "idle"
    BUSY = "busy"
    DRAINING = "draining"
    ERROR = "error"


class JobState(StrEnum):
    QUEUED = "queued"
    DISPATCHING = "dispatching"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"


class JobVisibility(StrEnum):
    PRIVATE = "private"
    GROUP = "group"


class GPUInfo(BaseModel):
    index: int
    uuid: str
    name: str
    memory_total_mb: int
    memory_used_mb: int = 0
    utilization_percent: int = 0
    temperature_c: int | None = None
    driver_version: str | None = None

    @property
    def memory_free_mb(self) -> int:
        return max(0, self.memory_total_mb - self.memory_used_mb)


class ComfyInstallation(BaseModel):
    path: str
    python_executable: str
    main_py: str
    version: str | None = None
    git_commit: str | None = None


class ComfyCliInfo(BaseModel):
    available: bool = False
    version: str | None = None
    output_contract: dict[str, str] = Field(default_factory=dict)
    capabilities: dict[str, Any] = Field(default_factory=dict)
    management_features: list[str] = Field(default_factory=list)
    error: str | None = None


class NodeInventoryItem(BaseModel):
    name: str
    path: str
    git_commit: str | None = None


class ModelInventoryItem(BaseModel):
    category: str
    name: str
    path: str
    size_bytes: int
    sha256: str | None = None


class WorkerSnapshot(BaseModel):
    worker_id: str
    gpu_uuid: str
    gpu_index: int
    port: int
    state: WorkerState = WorkerState.STOPPED
    pid: int | None = None
    comfy_url: str | None = None
    current_job_id: UUID | None = None
    error: str | None = None
    node_types: list[str] = Field(default_factory=list)


class HostRegistration(BaseModel):
    type: Literal["register"] = "register"
    host_id: str
    hostname: str
    os_name: str
    os_version: str
    agent_version: str
    gpus: list[GPUInfo]
    comfy: ComfyInstallation | None = None
    comfy_cli: ComfyCliInfo = Field(default_factory=ComfyCliInfo)
    workers: list[WorkerSnapshot] = Field(default_factory=list)
    nodes: list[NodeInventoryItem] = Field(default_factory=list)
    models: list[ModelInventoryItem] = Field(default_factory=list)


class HostHeartbeat(BaseModel):
    type: Literal["heartbeat"] = "heartbeat"
    host_id: str
    sent_at: datetime = Field(default_factory=utcnow)
    gpus: list[GPUInfo]
    workers: list[WorkerSnapshot]


class AgentEvent(BaseModel):
    type: Literal["event"] = "event"
    host_id: str
    event: str
    command_id: UUID | None = None
    job_id: UUID | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    sent_at: datetime = Field(default_factory=utcnow)


class ControllerCommand(BaseModel):
    type: Literal["command"] = "command"
    command_id: UUID = Field(default_factory=uuid4)
    action: str
    payload: dict[str, Any] = Field(default_factory=dict)


class HostView(BaseModel):
    host_id: str
    hostname: str
    os_name: str
    os_version: str
    agent_version: str
    connected: bool = True
    draining: bool = False
    last_seen: datetime = Field(default_factory=utcnow)
    gpus: list[GPUInfo] = Field(default_factory=list)
    comfy: ComfyInstallation | None = None
    comfy_cli: ComfyCliInfo = Field(default_factory=ComfyCliInfo)
    workers: list[WorkerSnapshot] = Field(default_factory=list)
    nodes: list[NodeInventoryItem] = Field(default_factory=list)
    models: list[ModelInventoryItem] = Field(default_factory=list)


class JobSubmitRequest(BaseModel):
    workflow: dict[str, Any]
    group_id: str | None = None
    visibility: JobVisibility = JobVisibility.GROUP
    client_id: str | None = None
    preferred_worker_id: str | None = None
    minimum_vram_mb: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class JobRecord(BaseModel):
    job_id: UUID = Field(default_factory=uuid4)
    state: JobState = JobState.QUEUED
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    owner_user_id: str | None = None
    group_id: str | None = None
    visibility: JobVisibility = JobVisibility.GROUP
    assigned_host_id: str | None = None
    assigned_worker_id: str | None = None
    assigned_gpu_uuid: str | None = None
    assigned_gpu_name: str | None = None
    assigned_gpu_memory_mb: int | None = None
    comfy_prompt_id: str | None = None
    error: str | None = None
    outputs: dict[str, Any] = Field(default_factory=dict)
    request: JobSubmitRequest

    @property
    def runtime_seconds(self) -> float | None:
        if not self.started_at or not self.completed_at:
            return None
        return max(0.0, (self.completed_at - self.started_at).total_seconds())


class JobSummary(BaseModel):
    job_id: UUID
    state: JobState
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    runtime_seconds: float | None = None
    owner_user_id: str | None = None
    group_id: str | None = None
    visibility: JobVisibility = JobVisibility.GROUP
    assigned_host_id: str | None = None
    assigned_worker_id: str | None = None
    assigned_gpu_uuid: str | None = None
    assigned_gpu_name: str | None = None
    error: str | None = None
    output_count: int = 0

    @classmethod
    def from_job(cls, job: JobRecord) -> "JobSummary":
        output_count = len(job.outputs) if isinstance(job.outputs, dict) else 0
        return cls(
            job_id=job.job_id,
            state=job.state,
            created_at=job.created_at,
            updated_at=job.updated_at,
            started_at=job.started_at,
            completed_at=job.completed_at,
            runtime_seconds=job.runtime_seconds,
            owner_user_id=job.owner_user_id,
            group_id=job.group_id,
            visibility=job.visibility,
            assigned_host_id=job.assigned_host_id,
            assigned_worker_id=job.assigned_worker_id,
            assigned_gpu_uuid=job.assigned_gpu_uuid,
            assigned_gpu_name=job.assigned_gpu_name,
            error=job.error,
            output_count=output_count,
        )
