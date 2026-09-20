from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class ControllerSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="COMFYCLUSTER_", env_file=".env", extra="ignore")

    database_path: Path | None = None
    asset_root: Path = Path("assets")
    agent_token: str | None = None
    admin_token: str | None = None


def create_configured_store():
    from .sqlite_store import SQLiteFleetStore
    from .store import FleetStore

    settings = ControllerSettings()
    if settings.database_path:
        return SQLiteFleetStore(settings.database_path)
    return FleetStore()


def create_configured_asset_repository():
    from .assets import AssetRepository

    settings = ControllerSettings()
    return AssetRepository(settings.database_path)
