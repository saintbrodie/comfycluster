from __future__ import annotations

import asyncio

import typer

from .client import AgentClient
from .gpu import discover_gpus
from .settings import AgentSettings

app = typer.Typer(help="Run the ComfyCluster Windows worker agent.")


@app.command()
def run(
    controller: str | None = typer.Option(None, help="Controller WebSocket URL"),
    agent_token: str | None = typer.Option(
        None,
        help="Controller bootstrap token. Prefer COMFYCLUSTER_AGENT_TOKEN or the installer config so it is not exposed in process arguments.",
    ),
    comfy_home: str | None = typer.Option(None, help="Path to ComfyUI"),
    mock_gpus: int | None = typer.Option(None, help="Create fake GPUs for development"),
) -> None:
    settings = AgentSettings()
    updates = {}
    if controller is not None:
        updates["controller_url"] = controller
    if agent_token is not None:
        updates["agent_token"] = agent_token
    if comfy_home is not None:
        updates["comfy_home"] = comfy_home
    if mock_gpus is not None:
        updates["mock_gpus"] = mock_gpus
    settings = settings.model_copy(update=updates)
    asyncio.run(AgentClient(settings).run())


@app.command()
def doctor(mock_gpus: int = 0) -> None:
    """Print the local NVIDIA inventory without joining a cluster."""
    for gpu in discover_gpus(mock_gpus):
        typer.echo(f"GPU {gpu.index}: {gpu.name} | {gpu.memory_total_mb} MB | {gpu.uuid}")


if __name__ == "__main__":
    app()
