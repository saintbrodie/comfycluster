import os
import secrets

import typer
import uvicorn

app = typer.Typer(help="Run the ComfyCluster control plane.")


@app.command()
def serve(
    host: str = "0.0.0.0",
    port: int = 9320,
    reload: bool = False,
    database: str | None = None,
) -> None:
    """Start the controller API and dashboard."""
    if database:
        os.environ["COMFYCLUSTER_DATABASE_PATH"] = database
    uvicorn.run("comfycluster_controller.app:app", host=host, port=port, reload=reload)


@app.command("new-agent-token")
def new_agent_token() -> None:
    """Generate a strong bootstrap token for controller-to-agent enrollment."""
    typer.echo(secrets.token_urlsafe(32))


if __name__ == "__main__":
    app()
