from __future__ import annotations

import sqlite3
import threading
from collections import defaultdict
from pathlib import Path
from uuid import UUID

from comfycluster_common.assets import AssetMetadata, AssetRecord, AssetView
from comfycluster_common.tenancy import Principal


class AssetRepository:
    """Metadata repository for controller-owned generated assets."""

    def __init__(self, database_path: str | Path | None = None) -> None:
        self._records: dict[UUID, AssetRecord] = {}
        self._lock = threading.RLock()
        self._reserved_total_bytes = 0
        self._reserved_group_bytes: dict[str, int] = defaultdict(int)
        self._db: sqlite3.Connection | None = None
        if database_path:
            path = Path(database_path)
            if path.parent != Path("."):
                path.parent.mkdir(parents=True, exist_ok=True)
            self._db = sqlite3.connect(path, check_same_thread=False)
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute(
                """
                CREATE TABLE IF NOT EXISTS assets (
                    asset_id TEXT PRIMARY KEY,
                    data TEXT NOT NULL
                )
                """
            )
            self._db.commit()
            for (raw,) in self._db.execute("SELECT data FROM assets"):
                record = AssetRecord.model_validate_json(raw)
                self._records[record.asset_id] = record

    def _total_size_unlocked(self) -> int:
        return sum(max(0, record.size_bytes) for record in self._records.values())

    def _group_size_unlocked(self, group_id: str | None) -> int:
        return sum(
            max(0, record.size_bytes)
            for record in self._records.values()
            if record.group_id == group_id
        )

    def reserve_capacity(
        self,
        group_id: str | None,
        size_bytes: int,
        *,
        max_vault_bytes: int,
        max_group_bytes: int | None,
    ) -> str | None:
        with self._lock:
            if self._total_size_unlocked() + self._reserved_total_bytes + size_bytes > max_vault_bytes:
                return "asset vault capacity limit reached"
            if group_id and max_group_bytes is not None:
                used = self._group_size_unlocked(group_id)
                reserved = self._reserved_group_bytes[group_id]
                if used + reserved + size_bytes > max_group_bytes:
                    return "group storage quota reached"
            self._reserved_total_bytes += size_bytes
            if group_id:
                self._reserved_group_bytes[group_id] += size_bytes
            return None

    def release_capacity(self, group_id: str | None, size_bytes: int) -> None:
        with self._lock:
            self._reserved_total_bytes = max(0, self._reserved_total_bytes - size_bytes)
            if group_id:
                remaining = max(0, self._reserved_group_bytes[group_id] - size_bytes)
                if remaining:
                    self._reserved_group_bytes[group_id] = remaining
                else:
                    self._reserved_group_bytes.pop(group_id, None)

    def create(self, record: AssetRecord) -> AssetRecord:
        with self._lock:
            self._records[record.asset_id] = record.model_copy(deep=True)
            if self._db:
                self._db.execute(
                    "INSERT OR REPLACE INTO assets(asset_id, data) VALUES(?, ?)",
                    (str(record.asset_id), record.model_dump_json()),
                )
                self._db.commit()
            return record.model_copy(deep=True)

    def update_metadata(self, asset_id: UUID, metadata: AssetMetadata) -> AssetRecord | None:
        with self._lock:
            record = self._records.get(asset_id)
            if record is None:
                return None
            updated = record.model_copy(update={"metadata": metadata}, deep=True)
            self._records[asset_id] = updated
            if self._db:
                self._db.execute(
                    "INSERT OR REPLACE INTO assets(asset_id, data) VALUES(?, ?)",
                    (str(updated.asset_id), updated.model_dump_json()),
                )
                self._db.commit()
            return updated.model_copy(deep=True)

    def get(self, asset_id: UUID) -> AssetRecord | None:
        with self._lock:
            record = self._records.get(asset_id)
            return record.model_copy(deep=True) if record else None

    def list_records(self) -> list[AssetRecord]:
        with self._lock:
            return [
                record.model_copy(deep=True)
                for record in sorted(
                    self._records.values(), key=lambda item: item.created_at, reverse=True
                )
            ]

    def total_size_bytes(self) -> int:
        with self._lock:
            return self._total_size_unlocked()

    def group_size_bytes(self, group_id: str | None) -> int:
        with self._lock:
            return self._group_size_unlocked(group_id)

    def user_size_bytes(self, user_id: str | None) -> int:
        with self._lock:
            return sum(
                max(0, record.size_bytes)
                for record in self._records.values()
                if record.owner_user_id == user_id
            )

    def _authorized_records(self, principal: Principal) -> list[AssetRecord]:
        return [
            record
            for record in sorted(self._records.values(), key=lambda item: item.created_at, reverse=True)
            if principal_can_view_asset(principal, record)
        ]

    def list_for_principal(self, principal: Principal) -> list[AssetView]:
        with self._lock:
            return [AssetView.from_record(record) for record in self._authorized_records(principal)]

    def query_for_principal(
        self,
        principal: Principal,
        *,
        q: str | None = None,
        model: str | None = None,
        lora: str | None = None,
        sampler: str | None = None,
        scheduler: str | None = None,
        media_family: str | None = None,
        group_id: str | None = None,
        owner_user_id: str | None = None,
        tag: str | None = None,
        face_cluster_id: str | None = None,
        min_width: int | None = None,
        min_height: int | None = None,
        limit: int = 500,
    ) -> list[AssetView]:
        needle = q.casefold().strip() if q else None

        def contains(values: list[str], expected: str | None) -> bool:
            if not expected:
                return True
            wanted = expected.casefold()
            return any(wanted in value.casefold() for value in values)

        def matches(record: AssetRecord) -> bool:
            metadata = record.metadata
            if group_id and record.group_id != group_id:
                return False
            if owner_user_id and record.owner_user_id != owner_user_id:
                return False
            if media_family and not record.media_type.casefold().startswith(media_family.casefold() + "/"):
                return False
            if not contains(metadata.models + metadata.model_refs, model):
                return False
            if not contains(metadata.loras, lora):
                return False
            if not contains(metadata.samplers, sampler):
                return False
            if not contains(metadata.schedulers, scheduler):
                return False
            if tag and tag.casefold() not in {value.casefold() for value in metadata.tags}:
                return False
            if face_cluster_id and face_cluster_id not in metadata.face_cluster_ids:
                return False
            if min_width and (metadata.width or 0) < min_width:
                return False
            if min_height and (metadata.height or 0) < min_height:
                return False
            if needle:
                haystack = [
                    record.filename,
                    metadata.workflow_name or "",
                    *metadata.tags,
                    *metadata.models,
                    *metadata.model_refs,
                    *metadata.loras,
                    *metadata.samplers,
                    *metadata.schedulers,
                    *metadata.prompts,
                ]
                if not any(needle in value.casefold() for value in haystack if value):
                    return False
            return True

        with self._lock:
            records = [record for record in self._authorized_records(principal) if matches(record)]
            return [AssetView.from_record(record) for record in records[: max(1, min(limit, 2000))]]

    def facets_for_principal(self, principal: Principal) -> dict[str, list[str]]:
        with self._lock:
            records = self._authorized_records(principal)

        def values(name: str) -> list[str]:
            collected: set[str] = set()
            for record in records:
                collected.update(str(item) for item in getattr(record.metadata, name) if item)
            return sorted(collected, key=str.casefold)

        return {
            "models": values("models"),
            "model_refs": values("model_refs"),
            "loras": values("loras"),
            "samplers": values("samplers"),
            "schedulers": values("schedulers"),
            "tags": values("tags"),
            "face_clusters": values("face_cluster_ids"),
            "groups": sorted({record.group_id for record in records if record.group_id}),
            "media_families": sorted(
                {record.media_type.split("/", 1)[0] for record in records if "/" in record.media_type}
            ),
        }

    def delete(self, asset_id: UUID) -> AssetRecord | None:
        with self._lock:
            record = self._records.pop(asset_id, None)
            if record and self._db:
                self._db.execute("DELETE FROM assets WHERE asset_id=?", (str(asset_id),))
                self._db.commit()
            return record.model_copy(deep=True) if record else None

    def close(self) -> None:
        if self._db:
            self._db.close()
            self._db = None


def principal_can_view_asset(principal: Principal, asset: AssetRecord) -> bool:
    if principal.content_auditor:
        return True
    if asset.owner_user_id == principal.user_id:
        return True
    return bool(
        asset.visibility.value == "group"
        and asset.group_id
        and asset.group_id in principal.group_ids
    )
