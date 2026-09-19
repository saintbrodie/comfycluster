from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class AgentSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="COMFYCLUSTER_", env_file=".env", extra="ignore")

    controller_url: str = "ws://127.0.0.1:9320/api/v1/agents/ws"
    comfy_home: Path | None = None
    comfy_cli_executable: str = "comfy"
    base_port: int = 8188
    heartbeat_seconds: float = 5.0
    autostart_workers: bool = True
    mock_gpus: int = 0
