from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class MembershipRole(StrEnum):
    MEMBER = "member"
    GROUP_ADMIN = "group_admin"


class GroupPolicy(BaseModel):
    max_queued_jobs: int = Field(default=50, ge=0)
    max_running_jobs: int = Field(default=2, ge=0)
    weight: float = Field(default=1.0, gt=0)


class GroupRecord(BaseModel):
    group_id: str
    name: str
    active: bool = True
    policy: GroupPolicy = Field(default_factory=GroupPolicy)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class UserRecord(BaseModel):
    user_id: str
    display_name: str
    active: bool = True
    max_queued_jobs: int = Field(default=10, ge=0)
    max_running_jobs: int = Field(default=2, ge=0)
    max_submissions_per_minute: int = Field(default=20, ge=1)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class MembershipRecord(BaseModel):
    user_id: str
    group_id: str
    role: MembershipRole = MembershipRole.MEMBER
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ApiTokenRecord(BaseModel):
    token_id: UUID = Field(default_factory=uuid4)
    user_id: str
    token_hash: str
    label: str | None = None
    revoked: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class IssuedToken(BaseModel):
    token_id: UUID
    user_id: str
    token: str
    label: str | None = None


class Principal(BaseModel):
    user_id: str
    display_name: str
    platform_admin: bool = False
    content_auditor: bool = False
    group_ids: list[str] = Field(default_factory=list)
    group_admin_ids: list[str] = Field(default_factory=list)

    def belongs_to(self, group_id: str | None) -> bool:
        return bool(group_id and group_id in self.group_ids)

    def administers(self, group_id: str | None) -> bool:
        return bool(group_id and group_id in self.group_admin_ids)
