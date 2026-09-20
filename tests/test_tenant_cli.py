import asyncio

from typer.testing import CliRunner

from comfycluster_controller.cli import app
from comfycluster_controller.sqlite_store import SQLiteFleetStore


runner = CliRunner()


def test_bootstrap_user_cli_creates_durable_tenant(monkeypatch, tmp_path):
    database = tmp_path / "fleet.db"
    monkeypatch.setenv("COMFYCLUSTER_DATABASE_PATH", str(database))

    result = runner.invoke(
        app,
        [
            "bootstrap-user",
            "--user-id",
            "alice",
            "--display-name",
            "Alice",
            "--group-id",
            "creative",
            "--group-name",
            "Creative",
            "--group-admin",
        ],
    )
    assert result.exit_code == 0, result.output
    raw_token = result.output.strip()
    assert len(raw_token) > 20

    async def verify():
        store = SQLiteFleetStore(database)
        try:
            principal = await store.principal_for_token(raw_token)
            assert principal is not None
            assert principal.user_id == "alice"
            assert principal.group_ids == ["creative"]
            assert principal.group_admin_ids == ["creative"]
        finally:
            store.close()

    asyncio.run(verify())


def test_issue_user_token_cli_rejects_unknown_user(monkeypatch, tmp_path):
    database = tmp_path / "fleet.db"
    monkeypatch.setenv("COMFYCLUSTER_DATABASE_PATH", str(database))
    SQLiteFleetStore(database).close()

    result = runner.invoke(app, ["issue-user-token", "--user-id", "missing"])
    assert result.exit_code != 0
