from __future__ import annotations

import sqlite3
import threading
from collections import defaultdict
from pathlib import Path
from uuid import UUID

from comfycluster_common.assets import AssetRecord, AssetView
from comfycluster_common.tenancy import Principal


class AssetRepository:
    """Small metadata repository for controller-owned generated assets."""

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
        """Atomically reserve expected upload bytes and return a rejection reason if full."""
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

    def list_for_principal(self, principal: Principal) -> list[AssetView]:
        with self._lock:
            records = sorted(self._records.values(), key=lambda item: item.created_at, reverse=True)
            return [
                AssetView.from_record(record)
                for record in records
                if principal_can_view_asset(principal, record)
            ]

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
