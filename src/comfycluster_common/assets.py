from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from .models import JobVisibility, utcnow


class AssetMetadata(BaseModel):
    workflow_name: str | None = None
    tags: list[str] = Field(default_factory=list)
    node_types: list[str] = Field(default_factory=list)
    model_refs: list[str] = Field(default_factory=list)
    models: list[str] = Field(default_factory=list)
    loras: list[str] = Field(default_factory=list)
    vaes: list[str] = Field(default_factory=list)
    clips: list[str] = Field(default_factory=list)
    samplers: list[str] = Field(default_factory=list)
    schedulers: list[str] = Field(default_factory=list)
    seeds: list[int] = Field(default_factory=list)
    steps: list[int] = Field(default_factory=list)
    cfg_scales: list[float] = Field(default_factory=list)
    prompts: list[str] = Field(default_factory=list)
    width: int | None = None
    height: int | None = None
    duration_seconds: float | None = None
    frame_count: int | None = None
    host_id: str | None = None
    worker_id: str | None = None
    gpu_name: str | None = None
    runtime_seconds: float | None = None
    face_count: int = 0
    face_cluster_ids: list[str] = Field(default_factory=list)


class AssetRecord(BaseModel):
    asset_id: UUID
    job_id: UUID
    owner_user_id: str | None = None
    group_id: str | None = None
    visibility: JobVisibility = JobVisibility.GROUP
    filename: str
    media_type: str = "application/octet-stream"
    size_bytes: int = 0
    node_id: str | None = None
    metadata: AssetMetadata = Field(default_factory=AssetMetadata)
    storage_path: str
    created_at: datetime = Field(default_factory=utcnow)


class AssetView(BaseModel):
    asset_id: UUID
    job_id: UUID
    owner_user_id: str | None = None
    group_id: str | None = None
    visibility: JobVisibility = JobVisibility.GROUP
    filename: str
    media_type: str
    size_bytes: int
    node_id: str | None = None
    metadata: AssetMetadata = Field(default_factory=AssetMetadata)
    created_at: datetime

    @classmethod
    def from_record(cls, record: AssetRecord) -> "AssetView":
        return cls(
            asset_id=record.asset_id,
            job_id=record.job_id,
            owner_user_id=record.owner_user_id,
            group_id=record.group_id,
            visibility=record.visibility,
            filename=record.filename,
            media_type=record.media_type,
            size_bytes=record.size_bytes,
            node_id=record.node_id,
            metadata=record.metadata.model_copy(deep=True),
            created_at=record.created_at,
        )
