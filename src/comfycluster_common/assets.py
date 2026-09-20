from __future__ import annotations

from datetime import datetime
from typing import Literal
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
    frame_rate: float | None = None
    video_codec: str | None = None
    audio_codec: str | None = None
    container_format: str | None = None
    bit_rate_bps: int | None = None
    host_id: str | None = None
    worker_id: str | None = None
    gpu_name: str | None = None
    runtime_seconds: float | None = None
    face_count: int = 0
    face_cluster_ids: list[str] = Field(default_factory=list)


class AssetSummaryMetadata(BaseModel):
    """Small metadata subset safe and cheap enough for gallery grids."""

    workflow_name: str | None = None
    tags: list[str] = Field(default_factory=list)
    model_refs: list[str] = Field(default_factory=list)
    models: list[str] = Field(default_factory=list)
    loras: list[str] = Field(default_factory=list)
    samplers: list[str] = Field(default_factory=list)
    seeds: list[int] = Field(default_factory=list)
    width: int | None = None
    height: int | None = None
    duration_seconds: float | None = None
    frame_count: int | None = None
    frame_rate: float | None = None
    video_codec: str | None = None
    audio_codec: str | None = None
    container_format: str | None = None
    face_count: int = 0
    face_cluster_ids: list[str] = Field(default_factory=list)

    @classmethod
    def from_metadata(cls, metadata: AssetMetadata) -> "AssetSummaryMetadata":
        return cls(
            workflow_name=metadata.workflow_name,
            tags=list(metadata.tags),
            model_refs=list(metadata.model_refs),
            models=list(metadata.models),
            loras=list(metadata.loras),
            samplers=list(metadata.samplers),
            seeds=list(metadata.seeds[:3]),
            width=metadata.width,
            height=metadata.height,
            duration_seconds=metadata.duration_seconds,
            frame_count=metadata.frame_count,
            frame_rate=metadata.frame_rate,
            video_codec=metadata.video_codec,
            audio_codec=metadata.audio_codec,
            container_format=metadata.container_format,
            face_count=metadata.face_count,
            face_cluster_ids=list(metadata.face_cluster_ids),
        )


class FaceGroupingUpdate(BaseModel):
    """Anonymous face clustering result; never carries a person's name or identity."""

    face_count: int = Field(default=0, ge=0)
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


class AssetSummaryView(BaseModel):
    asset_id: UUID
    job_id: UUID
    owner_user_id: str | None = None
    group_id: str | None = None
    visibility: JobVisibility = JobVisibility.GROUP
    filename: str
    media_type: str
    size_bytes: int
    metadata: AssetSummaryMetadata = Field(default_factory=AssetSummaryMetadata)
    created_at: datetime

    @classmethod
    def from_record(cls, record: AssetRecord) -> "AssetSummaryView":
        return cls(
            asset_id=record.asset_id,
            job_id=record.job_id,
            owner_user_id=record.owner_user_id,
            group_id=record.group_id,
            visibility=record.visibility,
            filename=record.filename,
            media_type=record.media_type,
            size_bytes=record.size_bytes,
            metadata=AssetSummaryMetadata.from_metadata(record.metadata),
            created_at=record.created_at,
        )


AssetSortField = Literal[
    "created_at",
    "filename",
    "size_bytes",
    "duration_seconds",
    "width",
    "height",
]
AssetSortOrder = Literal["asc", "desc"]


class AssetPage(BaseModel):
    items: list[AssetSummaryView] = Field(default_factory=list)
    total: int = 0
    offset: int = 0
    limit: int = 60
    has_more: bool = False
    sort_by: AssetSortField = "created_at"
    sort_order: AssetSortOrder = "desc"
