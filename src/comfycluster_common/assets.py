from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from .models import JobVisibility, utcnow


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
            created_at=record.created_at,
        )
