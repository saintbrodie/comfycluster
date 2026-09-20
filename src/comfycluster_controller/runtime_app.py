from __future__ import annotations

from fastapi import Header, HTTPException

from comfycluster_common.tenancy import Principal

from .app import app
from .asset_api import register_asset_routes
from .security import authenticate_principal
from .settings import ControllerSettings, create_configured_asset_repository

_settings = ControllerSettings()
_assets = create_configured_asset_repository()


async def current_principal(authorization: str | None = Header(default=None)) -> Principal:
    principal = await authenticate_principal(
        authorization,
        app.state.store,
        app.state.admin_token,
    )
    if principal is None:
        raise HTTPException(
            status_code=401,
            detail="authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return principal


register_asset_routes(
    app,
    store=app.state.store,
    repository=_assets,
    asset_root=_settings.asset_root,
    agent_token=app.state.agent_token,
    current_principal=current_principal,
    max_asset_bytes=_settings.max_asset_bytes,
    max_vault_bytes=_settings.max_asset_vault_bytes,
    min_free_bytes=_settings.min_asset_free_bytes,
    ffprobe_path=_settings.ffprobe_path,
    ffmpeg_path=_settings.ffmpeg_path,
    video_preview_seconds=_settings.video_preview_seconds,
    video_preview_max_size=_settings.video_preview_max_size,
)
