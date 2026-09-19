from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class ControllerSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="COMFYCLUSTER_", env_file=".env", extra="ignore")

    database_path: Path | None = None


def create_configured_store():
    from .sqlite_store import SQLiteFleetStore
    from .store import FleetStore

    settings = ControllerSettings()
    if settings.database_path:
        return SQLiteFleetStore(settings.database_path)
    return FleetStore()
