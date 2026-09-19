from __future__ import annotations

import socket

from pydantic_settings import BaseSettings, SettingsConfigDict


class DesktopSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="COMFYCLUSTER_", env_file=".env", extra="ignore")

    controller_url: str = "ws://127.0.0.1:9320/api/v1/agents/ws"
    local_api_url: str = "http://127.0.0.1:9321"
    desktop_refresh_seconds: float = 3.0

    @property
    def host_id(self) -> str:
        return socket.gethostname().lower()
