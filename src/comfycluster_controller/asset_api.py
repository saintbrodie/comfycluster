from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from uuid import UUID

from fastapi import Depends, Header, HTTPException, Request
from fastapi.responses import FileResponse

from comfycluster_common.assets import AssetRecord, AssetView
from comfycluster_common.tenancy import Principal

from .assets import AssetRepository, principal_can_view_asset
from .security import agent_authorized
from .store import FleetStore

_SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._ -]+")


def _safe_filename(filename: str) -> str:
    name = Path(filename).name.strip()
    name = _SAFE_FILENAME.sub("_", name)
    return name[:220] or "output.bin"


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
) -> None:
    asset_root.mkdir(parents=True, exist_ok=True)
    app.state.assets = repository
    app.state.asset_root = asset_root

    async def enforce_capacity(job, incoming_bytes: int) -> None:
        if incoming_bytes > max_asset_bytes:
            raise HTTPException(status_code=413, detail="asset exceeds per-file size limit")
        vault_bytes = repository.total_size_bytes()
        if vault_bytes + incoming_bytes > max_vault_bytes:
            raise HTTPException(status_code=507, detail="asset vault capacity limit reached")
        if job.group_id:
            group = await store.get_group(job.group_id)
            if group:
                group_bytes = repository.group_size_bytes(job.group_id)
                if group_bytes + incoming_bytes > group.policy.max_storage_bytes:
                    raise HTTPException(status_code=507, detail="group storage quota reached")
        free_bytes = shutil.disk_usage(asset_root).free
        if free_bytes - incoming_bytes < min_free_bytes:
            raise HTTPException(status_code=507, detail="controller minimum free-space reserve reached")

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

        content_length = request.headers.get("content-length")
        declared_size = int(content_length) if content_length else 0
        if declared_size:
            await enforce_capacity(job, declared_size)

        safe_name = _safe_filename(filename)
        job_dir = asset_root / str(job_id)
        job_dir.mkdir(parents=True, exist_ok=True)
        final_path = job_dir / f"{asset_id}_{safe_name}"
        temp_path = final_path.with_suffix(final_path.suffix + ".partial")
        size = 0
        base_vault_bytes = repository.total_size_bytes()
        base_group_bytes = repository.group_size_bytes(job.group_id)
        group = await store.get_group(job.group_id) if job.group_id else None
        try:
            with temp_path.open("wb") as handle:
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > max_asset_bytes:
                        raise HTTPException(status_code=413, detail="asset exceeds per-file size limit")
                    if base_vault_bytes + size > max_vault_bytes:
                        raise HTTPException(status_code=507, detail="asset vault capacity limit reached")
                    if group and base_group_bytes + size > group.policy.max_storage_bytes:
                        raise HTTPException(status_code=507, detail="group storage quota reached")
                    if shutil.disk_usage(asset_root).free < min_free_bytes:
                        raise HTTPException(
                            status_code=507,
                            detail="controller minimum free-space reserve reached",
                        )
                    handle.write(chunk)
            os.replace(temp_path, final_path)
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise

        record = AssetRecord(
            asset_id=asset_id,
            job_id=job_id,
            owner_user_id=job.owner_user_id,
            group_id=job.group_id,
            visibility=job.visibility,
            filename=safe_name,
            media_type=request.headers.get("content-type") or "application/octet-stream",
            size_bytes=size,
            node_id=node_id,
            storage_path=str(final_path),
        )
        return AssetView.from_record(repository.create(record))

    @app.get("/api/v1/assets", response_model=list[AssetView])
    async def list_assets(principal: Principal = Depends(current_principal)):
        return repository.list_for_principal(principal)

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
