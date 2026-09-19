import os

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


if __name__ == "__main__":
    app()
