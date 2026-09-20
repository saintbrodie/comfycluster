from __future__ import annotations

import sqlite3
import threading
from collections import defaultdict
from pathlib import Path
from typing import Any
from uuid import UUID

from comfycluster_common.assets import (
    AssetMetadata,
    AssetPage,
    AssetRecord,
    AssetSortField,
    AssetSortOrder,
    AssetSummaryView,
    AssetView,
)
from comfycluster_common.tenancy import Principal


class AssetRepository:
    """Metadata repository for controller-owned generated assets.

    SQLite deployments maintain a compact scalar/search index alongside the canonical
    JSON records. Gallery paging can therefore filter/count/sort without serializing
    every rich AssetView (including prompts) into a response.
    """

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
            self._db.execute(
                """
                CREATE TABLE IF NOT EXISTS asset_index (
                    asset_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    owner_user_id TEXT,
                    group_id TEXT,
                    visibility TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    media_type TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    width INTEGER,
                    height INTEGER,
                    duration_seconds REAL,
                    video_codec TEXT,
                    audio_codec TEXT,
                    container_format TEXT,
                    workflow_name TEXT,
                    models_text TEXT NOT NULL,
                    loras_text TEXT NOT NULL,
                    samplers_text TEXT NOT NULL,
                    schedulers_text TEXT NOT NULL,
                    tags_text TEXT NOT NULL,
                    face_clusters_text TEXT NOT NULL,
                    search_text TEXT NOT NULL
                )
                """
            )
            for statement in (
                "CREATE INDEX IF NOT EXISTS idx_asset_created ON asset_index(created_at DESC)",
                "CREATE INDEX IF NOT EXISTS idx_asset_group_created ON asset_index(group_id, created_at DESC)",
                "CREATE INDEX IF NOT EXISTS idx_asset_owner_created ON asset_index(owner_user_id, created_at DESC)",
                "CREATE INDEX IF NOT EXISTS idx_asset_media_created ON asset_index(media_type, created_at DESC)",
                "CREATE INDEX IF NOT EXISTS idx_asset_video_codec ON asset_index(video_codec)",
                "CREATE INDEX IF NOT EXISTS idx_asset_duration ON asset_index(duration_seconds)",
                "CREATE INDEX IF NOT EXISTS idx_asset_dimensions ON asset_index(width, height)",
            ):
                self._db.execute(statement)
            self._db.commit()
            for (raw,) in self._db.execute("SELECT data FROM assets"):
                record = AssetRecord.model_validate_json(raw)
                self._records[record.asset_id] = record
            # Idempotent migration/backfill for databases created before asset_index.
            for record in self._records.values():
                self._write_index_unlocked(record)
            self._db.commit()

    @staticmethod
    def _joined(values: list[Any]) -> str:
        return "\n" + "\n".join(str(value).casefold() for value in values if value is not None) + "\n"

    @classmethod
    def _search_text(cls, record: AssetRecord) -> str:
        metadata = record.metadata
        values: list[Any] = [
            record.filename,
            metadata.workflow_name,
            *metadata.tags,
            *metadata.models,
            *metadata.model_refs,
            *metadata.loras,
            *metadata.samplers,
            *metadata.schedulers,
            *metadata.prompts,
            metadata.video_codec,
            metadata.audio_codec,
            metadata.container_format,
        ]
        return "\n".join(str(value).casefold() for value in values if value)

    def _write_index_unlocked(self, record: AssetRecord) -> None:
        if not self._db:
            return
        metadata = record.metadata
        self._db.execute(
            """
            INSERT OR REPLACE INTO asset_index(
                asset_id, created_at, owner_user_id, group_id, visibility, filename,
                media_type, size_bytes, width, height, duration_seconds, video_codec,
                audio_codec, container_format, workflow_name, models_text, loras_text,
                samplers_text, schedulers_text, tags_text, face_clusters_text, search_text
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                str(record.asset_id),
                record.created_at.isoformat(),
                record.owner_user_id,
                record.group_id,
                record.visibility.value,
                record.filename,
                record.media_type,
                max(0, record.size_bytes),
                metadata.width,
                metadata.height,
                metadata.duration_seconds,
                metadata.video_codec.casefold() if metadata.video_codec else None,
                metadata.audio_codec.casefold() if metadata.audio_codec else None,
                metadata.container_format.casefold() if metadata.container_format else None,
                metadata.workflow_name,
                self._joined(metadata.models + metadata.model_refs),
                self._joined(metadata.loras),
                self._joined(metadata.samplers),
                self._joined(metadata.schedulers),
                self._joined(metadata.tags),
                self._joined(metadata.face_cluster_ids),
                self._search_text(record),
            ),
        )

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
                self._write_index_unlocked(record)
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
                self._write_index_unlocked(updated)
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
            for record in self._records.values()
            if principal_can_view_asset(principal, record)
        ]

    def list_for_principal(self, principal: Principal) -> list[AssetView]:
        with self._lock:
            records = sorted(
                self._authorized_records(principal), key=lambda item: item.created_at, reverse=True
            )
            return [AssetView.from_record(record) for record in records]

    @staticmethod
    def _record_matches(
        record: AssetRecord,
        *,
        q: str | None = None,
        model: str | None = None,
        lora: str | None = None,
        sampler: str | None = None,
        scheduler: str | None = None,
        media_family: str | None = None,
        video_codec: str | None = None,
        audio_codec: str | None = None,
        container_format: str | None = None,
        group_id: str | None = None,
        owner_user_id: str | None = None,
        tag: str | None = None,
        face_cluster_id: str | None = None,
        min_width: int | None = None,
        min_height: int | None = None,
        min_duration_seconds: float | None = None,
        max_duration_seconds: float | None = None,
    ) -> bool:
        metadata = record.metadata

        def contains(values: list[str], expected: str | None) -> bool:
            if not expected:
                return True
            wanted = expected.casefold()
            return any(wanted in value.casefold() for value in values)

        def scalar_contains(value: str | None, expected: str | None) -> bool:
            if not expected:
                return True
            return bool(value and expected.casefold() in value.casefold())

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
        if not scalar_contains(metadata.video_codec, video_codec):
            return False
        if not scalar_contains(metadata.audio_codec, audio_codec):
            return False
        if not scalar_contains(metadata.container_format, container_format):
            return False
        if tag and tag.casefold() not in {value.casefold() for value in metadata.tags}:
            return False
        if face_cluster_id and face_cluster_id not in metadata.face_cluster_ids:
            return False
        if min_width and (metadata.width or 0) < min_width:
            return False
        if min_height and (metadata.height or 0) < min_height:
            return False
        if min_duration_seconds is not None and (metadata.duration_seconds or 0) < min_duration_seconds:
            return False
        if max_duration_seconds is not None:
            if metadata.duration_seconds is None or metadata.duration_seconds > max_duration_seconds:
                return False
        if q:
            needle = q.casefold().strip()
            if needle and needle not in AssetRepository._search_text(record):
                return False
        return True

    @staticmethod
    def _sort_value(record: AssetRecord, sort_by: AssetSortField):
        if sort_by == "created_at":
            return record.created_at
        if sort_by == "filename":
            return record.filename.casefold()
        if sort_by == "size_bytes":
            return record.size_bytes
        if sort_by == "duration_seconds":
            return record.metadata.duration_seconds if record.metadata.duration_seconds is not None else -1.0
        if sort_by == "width":
            return record.metadata.width if record.metadata.width is not None else -1
        if sort_by == "height":
            return record.metadata.height if record.metadata.height is not None else -1
        return record.created_at

    @staticmethod
    def _filter_kwargs(**kwargs) -> dict[str, Any]:
        return {key: value for key, value in kwargs.items() if value is not None}

    def query_for_principal(
        self,
        principal: Principal,
        *,
        limit: int = 500,
        **filters,
    ) -> list[AssetView]:
        """Backward-compatible rich list API. Prefer query_page_for_principal for galleries."""
        with self._lock:
            records = [
                record
                for record in self._authorized_records(principal)
                if self._record_matches(record, **self._filter_kwargs(**filters))
            ]
            records.sort(key=lambda item: item.created_at, reverse=True)
            return [AssetView.from_record(record) for record in records[: max(1, min(limit, 2000))]]

    def _sqlite_authorization(self, principal: Principal) -> tuple[str, list[Any]]:
        if principal.content_auditor:
            return "1=1", []
        clauses: list[str] = []
        params: list[Any] = []
        if principal.user_id:
            clauses.append("owner_user_id = ?")
            params.append(principal.user_id)
        if principal.group_ids:
            placeholders = ",".join("?" for _ in principal.group_ids)
            clauses.append(f"(visibility = 'group' AND group_id IN ({placeholders}))")
            params.extend(principal.group_ids)
        if not clauses:
            return "0=1", []
        return "(" + " OR ".join(clauses) + ")", params

    def _sqlite_page(
        self,
        principal: Principal,
        *,
        q: str | None,
        model: str | None,
        lora: str | None,
        sampler: str | None,
        scheduler: str | None,
        media_family: str | None,
        video_codec: str | None,
        audio_codec: str | None,
        container_format: str | None,
        group_id: str | None,
        owner_user_id: str | None,
        tag: str | None,
        face_cluster_id: str | None,
        min_width: int | None,
        min_height: int | None,
        min_duration_seconds: float | None,
        max_duration_seconds: float | None,
        offset: int,
        limit: int,
        sort_by: AssetSortField,
        sort_order: AssetSortOrder,
    ) -> AssetPage:
        assert self._db is not None
        auth_sql, params = self._sqlite_authorization(principal)
        where = [auth_sql]

        def like(column: str, value: str | None) -> None:
            if value:
                where.append(f"{column} LIKE ?")
                params.append(f"%{value.casefold()}%")

        if q and q.strip():
            like("search_text", q.strip())
        like("models_text", model)
        like("loras_text", lora)
        like("samplers_text", sampler)
        like("schedulers_text", scheduler)
        like("video_codec", video_codec)
        like("audio_codec", audio_codec)
        like("container_format", container_format)
        if media_family:
            where.append("media_type LIKE ?")
            params.append(f"{media_family.casefold()}/%")
        if group_id:
            where.append("group_id = ?")
            params.append(group_id)
        if owner_user_id:
            where.append("owner_user_id = ?")
            params.append(owner_user_id)
        if tag:
            where.append("tags_text LIKE ?")
            params.append(f"%\n{tag.casefold()}\n%")
        if face_cluster_id:
            where.append("face_clusters_text LIKE ?")
            params.append(f"%\n{face_cluster_id.casefold()}\n%")
        if min_width is not None:
            where.append("COALESCE(width, 0) >= ?")
            params.append(min_width)
        if min_height is not None:
            where.append("COALESCE(height, 0) >= ?")
            params.append(min_height)
        if min_duration_seconds is not None:
            where.append("COALESCE(duration_seconds, 0) >= ?")
            params.append(min_duration_seconds)
        if max_duration_seconds is not None:
            where.append("duration_seconds IS NOT NULL AND duration_seconds <= ?")
            params.append(max_duration_seconds)

        where_sql = " AND ".join(where)
        total = int(
            self._db.execute(
                f"SELECT COUNT(*) FROM asset_index WHERE {where_sql}", params
            ).fetchone()[0]
        )
        column = {
            "created_at": "created_at",
            "filename": "filename COLLATE NOCASE",
            "size_bytes": "size_bytes",
            "duration_seconds": "COALESCE(duration_seconds, -1)",
            "width": "COALESCE(width, -1)",
            "height": "COALESCE(height, -1)",
        }[sort_by]
        direction = "ASC" if sort_order == "asc" else "DESC"
        rows = self._db.execute(
            f"""
            SELECT asset_id FROM asset_index
            WHERE {where_sql}
            ORDER BY {column} {direction}, asset_id {direction}
            LIMIT ? OFFSET ?
            """,
            [*params, limit, offset],
        ).fetchall()
        items = [
            AssetSummaryView.from_record(self._records[UUID(asset_id)])
            for (asset_id,) in rows
            if UUID(asset_id) in self._records
        ]
        return AssetPage(
            items=items,
            total=total,
            offset=offset,
            limit=limit,
            has_more=offset + len(items) < total,
            sort_by=sort_by,
            sort_order=sort_order,
        )

    def query_page_for_principal(
        self,
        principal: Principal,
        *,
        q: str | None = None,
        model: str | None = None,
        lora: str | None = None,
        sampler: str | None = None,
        scheduler: str | None = None,
        media_family: str | None = None,
        video_codec: str | None = None,
        audio_codec: str | None = None,
        container_format: str | None = None,
        group_id: str | None = None,
        owner_user_id: str | None = None,
        tag: str | None = None,
        face_cluster_id: str | None = None,
        min_width: int | None = None,
        min_height: int | None = None,
        min_duration_seconds: float | None = None,
        max_duration_seconds: float | None = None,
        offset: int = 0,
        limit: int = 60,
        sort_by: AssetSortField = "created_at",
        sort_order: AssetSortOrder = "desc",
    ) -> AssetPage:
        offset = max(0, offset)
        limit = max(1, min(limit, 200))
        filters = dict(
            q=q,
            model=model,
            lora=lora,
            sampler=sampler,
            scheduler=scheduler,
            media_family=media_family,
            video_codec=video_codec,
            audio_codec=audio_codec,
            container_format=container_format,
            group_id=group_id,
            owner_user_id=owner_user_id,
            tag=tag,
            face_cluster_id=face_cluster_id,
            min_width=min_width,
            min_height=min_height,
            min_duration_seconds=min_duration_seconds,
            max_duration_seconds=max_duration_seconds,
        )
        with self._lock:
            if self._db:
                return self._sqlite_page(
                    principal,
                    offset=offset,
                    limit=limit,
                    sort_by=sort_by,
                    sort_order=sort_order,
                    **filters,
                )
            records = [
                record
                for record in self._authorized_records(principal)
                if self._record_matches(record, **self._filter_kwargs(**filters))
            ]
            reverse = sort_order == "desc"
            records.sort(key=lambda item: self._sort_value(item, sort_by), reverse=reverse)
            page_records = records[offset : offset + limit]
            return AssetPage(
                items=[AssetSummaryView.from_record(record) for record in page_records],
                total=len(records),
                offset=offset,
                limit=limit,
                has_more=offset + len(page_records) < len(records),
                sort_by=sort_by,
                sort_order=sort_order,
            )

    def facets_for_principal(self, principal: Principal) -> dict[str, list[str]]:
        with self._lock:
            records = self._authorized_records(principal)

        def values(name: str) -> list[str]:
            collected: set[str] = set()
            for record in records:
                collected.update(str(item) for item in getattr(record.metadata, name) if item)
            return sorted(collected, key=str.casefold)

        def scalar_values(name: str) -> list[str]:
            collected = {
                str(value)
                for record in records
                if (value := getattr(record.metadata, name))
            }
            return sorted(collected, key=str.casefold)

        return {
            "models": values("models"),
            "model_refs": values("model_refs"),
            "loras": values("loras"),
            "samplers": values("samplers"),
            "schedulers": values("schedulers"),
            "tags": values("tags"),
            "face_clusters": values("face_cluster_ids"),
            "video_codecs": scalar_values("video_codec"),
            "audio_codecs": scalar_values("audio_codec"),
            "container_formats": scalar_values("container_format"),
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
                self._db.execute("DELETE FROM asset_index WHERE asset_id=?", (str(asset_id),))
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
