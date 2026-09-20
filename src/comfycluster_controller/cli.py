import asyncio
import os
import secrets

import typer
import uvicorn

from comfycluster_common.tenancy import (
    GroupRecord,
    MembershipRecord,
    MembershipRole,
    UserRecord,
)

from .settings import ControllerSettings, create_configured_store

app = typer.Typer(help="Run and administer the ComfyCluster control plane.")


@app.command()
def serve(
    host: str = "0.0.0.0",
    port: int = 9320,
    reload: bool = False,
    database: str | None = None,
    ssl_certfile: str | None = typer.Option(None, help="TLS certificate file for HTTPS/WSS"),
    ssl_keyfile: str | None = typer.Option(None, help="TLS private-key file for HTTPS/WSS"),
) -> None:
    """Start the controller API and dashboard."""
    if database:
        os.environ["COMFYCLUSTER_DATABASE_PATH"] = database
    if bool(ssl_certfile) != bool(ssl_keyfile):
        raise typer.BadParameter("--ssl-certfile and --ssl-keyfile must be supplied together")

    if reload:
        uvicorn.run(
            "comfycluster_controller.runtime_app:app",
            host=host,
            port=port,
            reload=True,
            ssl_certfile=ssl_certfile,
            ssl_keyfile=ssl_keyfile,
        )
        return

    from .runtime_app import app as controller_app

    uvicorn.run(
        controller_app,
        host=host,
        port=port,
        ssl_certfile=ssl_certfile,
        ssl_keyfile=ssl_keyfile,
    )


@app.command("new-agent-token")
def new_agent_token() -> None:
    """Generate a strong bootstrap token."""
    typer.echo(secrets.token_urlsafe(32))


def _durable_store():
    settings = ControllerSettings()
    if not settings.database_path:
        raise typer.BadParameter(
            "COMFYCLUSTER_DATABASE_PATH must be configured for tenant administration"
        )
    return create_configured_store()


def _close_store(store) -> None:
    close = getattr(store, "close", None)
    if close:
        close()


@app.command("bootstrap-user")
def bootstrap_user(
    user_id: str = typer.Option(..., help="Stable user identifier"),
    display_name: str = typer.Option(..., help="Display name"),
    group_id: str = typer.Option(..., help="Private creative group identifier"),
    group_name: str | None = typer.Option(None, help="Create the group with this display name"),
    group_admin: bool = typer.Option(False, help="Make this user a group administrator"),
    max_queued: int = typer.Option(10, min=0, help="Maximum queued jobs for the user"),
    max_running: int = typer.Option(2, min=0, help="Maximum concurrent jobs for the user"),
    submissions_per_minute: int = typer.Option(20, min=1, help="Job submission rate limit"),
    label: str = typer.Option("workstation", help="Label attached to the new user token"),
) -> None:
    """Create a user/group membership and print a one-time desktop API token."""

    async def run() -> str:
        store = _durable_store()
        try:
            group = await store.get_group(group_id)
            if group is None:
                await store.create_group(GroupRecord(group_id=group_id, name=group_name or group_id))
            user = await store.get_user(user_id)
            if user is None:
                await store.create_user(
                    UserRecord(
                        user_id=user_id,
                        display_name=display_name,
                        max_queued_jobs=max_queued,
                        max_running_jobs=max_running,
                        max_submissions_per_minute=submissions_per_minute,
                    )
                )
            await store.add_membership(
                MembershipRecord(
                    user_id=user_id,
                    group_id=group_id,
                    role=MembershipRole.GROUP_ADMIN if group_admin else MembershipRole.MEMBER,
                )
            )
            issued = await store.issue_token(user_id, label)
            return issued.token
        finally:
            _close_store(store)

    token = asyncio.run(run())
    typer.echo(token)


@app.command("issue-user-token")
def issue_user_token(
    user_id: str = typer.Option(..., help="Existing user identifier"),
    label: str = typer.Option("workstation", help="Token label"),
) -> None:
    """Issue an additional one-time user API token."""

    async def run() -> str:
        store = _durable_store()
        try:
            issued = await store.issue_token(user_id, label)
            return issued.token
        finally:
            _close_store(store)

    try:
        token = asyncio.run(run())
    except KeyError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(token)


@app.command("set-face-grouping")
def set_face_grouping(
    group_id: str = typer.Option(..., help="Private group identifier"),
    enabled: bool = typer.Option(
        True,
        "--enabled/--disabled",
        help="Enable or disable anonymous face grouping for this group",
    ),
) -> None:
    """Opt a private group into or out of anonymous face clustering."""

    async def run() -> bool:
        store = _durable_store()
        try:
            group = await store.get_group(group_id)
            if group is None:
                raise KeyError(f"unknown group {group_id}")
            updated = group.model_copy(
                update={
                    "policy": group.policy.model_copy(
                        update={"face_grouping_enabled": enabled}
                    )
                }
            )
            await store.create_group(updated)
            return updated.policy.face_grouping_enabled
        finally:
            _close_store(store)

    try:
        result = asyncio.run(run())
    except KeyError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(f"{group_id}: face grouping {'enabled' if result else 'disabled'}")


if __name__ == "__main__":
    app()
