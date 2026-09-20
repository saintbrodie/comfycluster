from __future__ import annotations

import os
import re
import shutil
from datetime import timedelta
from pathlib import Path
from uuid import UUID

from fastapi import Body, Depends, Header, HTTPException, Request
from fastapi.responses import FileResponse
from PIL import Image, ImageOps, UnidentifiedImageError

from comfycluster_common.assets import (
    AssetPage,
    AssetRecord,
    AssetSortField,
    AssetSortOrder,
    AssetView,
    FaceGroupingUpdate,
)
from comfycluster_common.models import utcnow
from comfycluster_common.tenancy import Principal

from .asset_metadata import extract_asset_metadata
from .assets import AssetRepository, principal_can_view_asset
from .media import generate_video_poster, generate_video_preview, probe_video
from .security import agent_authorized
from .store import FleetStore

_SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._ -]+")
_FACE_CLUSTER_ID = re.compile(r"^face_[0-9a-f]{12,64}$")


def _safe_filename(filename: str) -> str:
    name = Path(filename).name.strip()
    name = _SAFE_FILENAME.sub("_", name)
    return name[:220] or "output.bin"


def _image_dimensions(path: Path) -> tuple[int, int] | None:
    try:
        with Image.open(path) as image:
            image = ImageOps.exif_transpose(image)
            return image.size
    except (OSError, UnidentifiedImageError):
        return None


def register_asset_routes(
    app,
    *,
    store: FleetStore,
    repository: AssetRepository,
    asset_root: Path,
    agent_token: str | None,
    current_principal,
    max_asset_bytes: int,
    max_vault_bytes: int,
    min_free_bytes: int,
    ffprobe_path: str | Path | None = None,
    ffmpeg_path: str | Path | None = None,
    video_preview_seconds: float = 8.0,
    video_preview_max_size: int = 720,
) -> None:
    asset_root.mkdir(parents=True, exist_ok=True)
    thumbnail_root = asset_root / ".thumbnails"
    preview_root = asset_root / ".previews"
    thumbnail_root.mkdir(parents=True, exist_ok=True)
    preview_root.mkdir(parents=True, exist_ok=True)
    app.state.assets = repository
    app.state.asset_root = asset_root

    @app.put("/api/v1/agents/jobs/{job_id}/assets/{asset_id}", response_model=AssetView)
    async def upload_asset(
        job_id: UUID,
        asset_id: UUID,
        request: Request,
        filename: str,
        node_id: str | None = None,
        host_id: str | None = None,
        authorization: str | None = Header(default=None),
    ):
        if not agent_authorized(authorization, agent_token):
            raise HTTPException(status_code=401, detail="unauthorized agent")
        job = await store.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="job not found")
        if host_id and job.assigned_host_id and host_id != job.assigned_host_id:
            raise HTTPException(status_code=403, detail="job is assigned to another host")

        raw_length = request.headers.get("content-length")
        if not raw_length:
            raise HTTPException(status_code=411, detail="content-length is required for asset uploads")
        try:
            declared_size = int(raw_length)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="invalid content-length") from exc
        if declared_size < 0:
            raise HTTPException(status_code=400, detail="invalid content-length")
        if declared_size > max_asset_bytes:
            raise HTTPException(status_code=413, detail="asset exceeds per-file size limit")

        group = await store.get_group(job.group_id) if job.group_id else None
        reason = repository.reserve_capacity(
            job.group_id,
            declared_size,
            max_vault_bytes=max_vault_bytes,
            max_group_bytes=group.policy.max_storage_bytes if group else None,
        )
        if reason:
            raise HTTPException(status_code=507, detail=reason)

        safe_name = _safe_filename(filename)
        job_dir = asset_root / str(job_id)
        job_dir.mkdir(parents=True, exist_ok=True)
        final_path = job_dir / f"{asset_id}_{safe_name}"
        temp_path = final_path.with_suffix(final_path.suffix + ".partial")
        committed = False
        try:
            if shutil.disk_usage(asset_root).free - declared_size < min_free_bytes:
                raise HTTPException(
                    status_code=507,
                    detail="controller minimum free-space reserve reached",
                )

            size = 0
            with temp_path.open("wb") as handle:
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > declared_size or size > max_asset_bytes:
                        raise HTTPException(status_code=400, detail="asset size exceeded content-length")
                    handle.write(chunk)
            if size != declared_size:
                raise HTTPException(status_code=400, detail="asset size did not match content-length")

            os.replace(temp_path, final_path)
            metadata = extract_asset_metadata(job)
            media_type = request.headers.get("content-type") or "application/octet-stream"
            if media_type.startswith("image/"):
                dimensions = _image_dimensions(final_path)
                if dimensions:
                    metadata = metadata.model_copy(
                        update={"width": dimensions[0], "height": dimensions[1]}
                    )
            elif media_type.startswith("video/"):
                probe = probe_video(final_path, ffprobe_path=ffprobe_path)
                if probe:
                    metadata = metadata.model_copy(update=probe.as_metadata_update())
            record = AssetRecord(
                asset_id=asset_id,
                job_id=job_id,
                owner_user_id=job.owner_user_id,
                group_id=job.group_id,
                visibility=job.visibility,
                filename=safe_name,
                media_type=media_type,
                size_bytes=size,
                node_id=node_id,
                metadata=metadata,
                storage_path=str(final_path),
            )
            stored = repository.create(record)
            committed = True
            return AssetView.from_record(stored)
        finally:
            repository.release_capacity(job.group_id, declared_size)
            temp_path.unlink(missing_ok=True)
            if not committed:
                final_path.unlink(missing_ok=True)

    def search_filters(
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
    ) -> dict:
        return {
            "q": q,
            "model": model,
            "lora": lora,
            "sampler": sampler,
            "scheduler": scheduler,
            "media_family": media_family,
            "video_codec": video_codec,
            "audio_codec": audio_codec,
            "container_format": container_format,
            "group_id": group_id,
            "owner_user_id": owner_user_id,
            "tag": tag,
            "face_cluster_id": face_cluster_id,
            "min_width": min_width,
            "min_height": min_height,
            "min_duration_seconds": min_duration_seconds,
            "max_duration_seconds": max_duration_seconds,
        }

    @app.get("/api/v1/assets/search", response_model=AssetPage)
    async def search_assets(
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
        principal: Principal = Depends(current_principal),
    ):
        return repository.query_page_for_principal(
            principal,
            **search_filters(
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
            ),
            offset=offset,
            limit=limit,
            sort_by=sort_by,
            sort_order=sort_order,
        )

    @app.get("/api/v1/assets", response_model=list[AssetView])
    async def list_assets(
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
        limit: int = 100,
        principal: Principal = Depends(current_principal),
    ):
        """Compatibility endpoint returning rich records. New galleries should use /search."""
        return repository.query_for_principal(
            principal,
            **search_filters(
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
            ),
            limit=limit,
        )

    @app.get("/api/v1/assets/facets")
    async def asset_facets(principal: Principal = Depends(current_principal)):
        return repository.facets_for_principal(principal)

    def authorized_asset(asset_id: UUID, principal: Principal) -> AssetRecord:
        record = repository.get(asset_id)
        if record is None or not principal_can_view_asset(principal, record):
            raise HTTPException(status_code=404, detail="asset not found")
        return record

    @app.get("/api/v1/assets/{asset_id}", response_model=AssetView)
    async def get_asset(asset_id: UUID, principal: Principal = Depends(current_principal)):
        return AssetView.from_record(authorized_asset(asset_id, principal))

    @app.get("/api/v1/assets/{asset_id}/content")
    async def get_asset_content(
        asset_id: UUID,
        principal: Principal = Depends(current_principal),
    ):
        record = authorized_asset(asset_id, principal)
        path = Path(record.storage_path)
        if not path.is_file():
            raise HTTPException(status_code=410, detail="asset content is no longer available")
        return FileResponse(path, media_type=record.media_type, filename=record.filename)

    @app.get("/api/v1/assets/{asset_id}/thumbnail")
    async def get_asset_thumbnail(
        asset_id: UUID,
        size: int = 320,
        principal: Principal = Depends(current_principal),
    ):
        record = authorized_asset(asset_id, principal)
        source = Path(record.storage_path)
        if not source.is_file():
            raise HTTPException(status_code=410, detail="asset content is no longer available")
        size = max(96, min(size, 1024))
        thumbnail_path = thumbnail_root / f"{asset_id}-{size}.jpg"
        if thumbnail_path.is_file() and thumbnail_path.stat().st_mtime >= source.stat().st_mtime:
            return FileResponse(thumbnail_path, media_type="image/jpeg")

        if record.media_type.startswith("image/"):
            try:
                with Image.open(source) as image:
                    image = ImageOps.exif_transpose(image)
                    image.thumbnail((size, size))
                    if image.mode not in {"RGB", "L"}:
                        background = Image.new("RGB", image.size, "black")
                        if "A" in image.getbands():
                            background.paste(image, mask=image.getchannel("A"))
                        else:
                            background.paste(image)
                        image = background
                    elif image.mode == "L":
                        image = image.convert("RGB")
                    image.save(thumbnail_path, "JPEG", quality=82, optimize=True)
            except (OSError, UnidentifiedImageError) as exc:
                raise HTTPException(status_code=415, detail="unable to create image thumbnail") from exc
        elif record.media_type.startswith("video/"):
            created = generate_video_poster(
                source,
                thumbnail_path,
                size=size,
                duration_seconds=record.metadata.duration_seconds,
                ffmpeg_path=ffmpeg_path,
            )
            if not created:
                raise HTTPException(
                    status_code=503,
                    detail="video poster generation requires a working ffmpeg installation",
                )
        else:
            raise HTTPException(status_code=415, detail="thumbnail is available for images and videos")
        return FileResponse(thumbnail_path, media_type="image/jpeg")

    @app.get("/api/v1/assets/{asset_id}/preview")
    async def get_asset_preview(
        asset_id: UUID,
        principal: Principal = Depends(current_principal),
    ):
        record = authorized_asset(asset_id, principal)
        if not record.media_type.startswith("video/"):
            raise HTTPException(status_code=415, detail="preview proxy is available for videos only")
        source = Path(record.storage_path)
        if not source.is_file():
            raise HTTPException(status_code=410, detail="asset content is no longer available")
        preview_path = preview_root / f"{asset_id}-{int(video_preview_seconds)}s-{video_preview_max_size}.mp4"
        if not preview_path.is_file() or preview_path.stat().st_mtime < source.stat().st_mtime:
            created = generate_video_preview(
                source,
                preview_path,
                duration_seconds=record.metadata.duration_seconds,
                preview_seconds=video_preview_seconds,
                max_size=video_preview_max_size,
                ffmpeg_path=ffmpeg_path,
            )
            if not created:
                raise HTTPException(
                    status_code=503,
                    detail="video preview generation requires ffmpeg with libx264 support",
                )
        return FileResponse(preview_path, media_type="video/mp4", filename=f"preview-{record.filename}.mp4")

    @app.put("/api/v1/agents/assets/{asset_id}/face-groups", response_model=AssetView)
    async def update_face_groups(
        asset_id: UUID,
        update: FaceGroupingUpdate = Body(...),
        host_id: str | None = None,
        authorization: str | None = Header(default=None),
    ):
        if not agent_authorized(authorization, agent_token):
            raise HTTPException(status_code=401, detail="unauthorized agent")
        record = repository.get(asset_id)
        if record is None:
            raise HTTPException(status_code=404, detail="asset not found")
        job = await store.get_job(record.job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="job not found")
        if host_id and job.assigned_host_id and host_id != job.assigned_host_id:
            raise HTTPException(status_code=403, detail="job is assigned to another host")
        group = await store.get_group(record.group_id) if record.group_id else None
        if group is None or not group.policy.face_grouping_enabled:
            raise HTTPException(status_code=409, detail="face grouping is disabled for this group")
        if any(not _FACE_CLUSTER_ID.fullmatch(value) for value in update.face_cluster_ids):
            raise HTTPException(status_code=400, detail="face cluster IDs must be opaque hashes")
        metadata = record.metadata.model_copy(
            update={
                "face_count": update.face_count,
                "face_cluster_ids": sorted(set(update.face_cluster_ids)),
            }
        )
        updated = repository.update_metadata(asset_id, metadata)
        if updated is None:
            raise HTTPException(status_code=404, detail="asset not found")
        return AssetView.from_record(updated)

    def cleanup_derivatives(asset_id: UUID) -> None:
        for thumbnail in thumbnail_root.glob(f"{asset_id}-*.jpg"):
            thumbnail.unlink(missing_ok=True)
        for preview in preview_root.glob(f"{asset_id}-*.mp4"):
            preview.unlink(missing_ok=True)

    @app.delete("/api/v1/assets/{asset_id}", status_code=204)
    async def delete_asset(
        asset_id: UUID,
        principal: Principal = Depends(current_principal),
    ):
        record = repository.get(asset_id)
        if record is None:
            raise HTTPException(status_code=404, detail="asset not found")
        allowed = (
            principal.platform_admin
            or record.owner_user_id == principal.user_id
            or principal.administers(record.group_id)
        )
        if not allowed:
            raise HTTPException(status_code=404, detail="asset not found")
        removed = repository.delete(asset_id)
        if removed:
            Path(removed.storage_path).unlink(missing_ok=True)
            cleanup_derivatives(asset_id)

    @app.get("/api/v1/admin/assets/storage")
    async def storage_summary(principal: Principal = Depends(current_principal)):
        if not principal.platform_admin:
            raise HTTPException(status_code=403, detail="platform administrator required")
        records = repository.list_records()
        groups: dict[str, dict[str, int | str | None]] = {}
        for record in records:
            key = record.group_id or "unassigned"
            entry = groups.setdefault(
                key,
                {"group_id": record.group_id, "asset_count": 0, "bytes": 0},
            )
            entry["asset_count"] = int(entry["asset_count"]) + 1
            entry["bytes"] = int(entry["bytes"]) + max(0, record.size_bytes)
        return {
            "asset_count": len(records),
            "bytes": sum(max(0, record.size_bytes) for record in records),
            "max_vault_bytes": max_vault_bytes,
            "free_disk_bytes": shutil.disk_usage(asset_root).free,
            "groups": sorted(groups.values(), key=lambda item: int(item["bytes"]), reverse=True),
        }

    @app.post("/api/v1/admin/assets/retention/cleanup")
    async def cleanup_retention(
        dry_run: bool = True,
        principal: Principal = Depends(current_principal),
    ):
        if not principal.platform_admin:
            raise HTTPException(status_code=403, detail="platform administrator required")

        now = utcnow()
        groups = {group.group_id: group for group in await store.list_groups()}
        expired: list[AssetRecord] = []
        for record in repository.list_records():
            if not record.group_id:
                continue
            group = groups.get(record.group_id)
            if group is None or group.policy.retention_days is None:
                continue
            cutoff = now - timedelta(days=group.policy.retention_days)
            if record.created_at <= cutoff:
                expired.append(record)

        by_group: dict[str, dict[str, int | str]] = {}
        for record in expired:
            key = record.group_id or "unassigned"
            entry = by_group.setdefault(key, {"group_id": key, "asset_count": 0, "bytes": 0})
            entry["asset_count"] = int(entry["asset_count"]) + 1
            entry["bytes"] = int(entry["bytes"]) + max(0, record.size_bytes)

        if not dry_run:
            for record in expired:
                removed = repository.delete(record.asset_id)
                if removed:
                    Path(removed.storage_path).unlink(missing_ok=True)
                    cleanup_derivatives(record.asset_id)

        return {
            "dry_run": dry_run,
            "asset_count": len(expired),
            "bytes": sum(max(0, record.size_bytes) for record in expired),
            "groups": sorted(by_group.values(), key=lambda item: str(item["group_id"])),
        }
