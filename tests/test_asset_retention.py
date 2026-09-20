import asyncio
from pathlib import Path
from uuid import uuid4

from fastapi import Header, HTTPException
from fastapi.testclient import TestClient

from comfycluster_common.assets import AssetRecord
from comfycluster_common.models import JobVisibility, utcnow
from comfycluster_common.tenancy import GroupPolicy, GroupRecord, Principal
from comfycluster_controller.app import create_app
from comfycluster_controller.asset_api import register_asset_routes
from comfycluster_controller.assets import AssetRepository
from comfycluster_controller.security import authenticate_principal
from comfycluster_controller.store import FleetStore


ADMIN_TOKEN = "admin-secret"
AGENT_TOKEN = "agent-secret"


def _build_app(store: FleetStore, repository: AssetRepository, root: Path):
    app = create_app(store=store, agent_token=AGENT_TOKEN, admin_token=ADMIN_TOKEN)

    async def current_principal(authorization: str | None = Header(default=None)) -> Principal:
        principal = await authenticate_principal(authorization, store, ADMIN_TOKEN)
        if principal is None:
            raise HTTPException(status_code=401, detail="authentication required")
        return principal

    register_asset_routes(
        app,
        store=store,
        repository=repository,
        asset_root=root,
        agent_token=AGENT_TOKEN,
        current_principal=current_principal,
        max_asset_bytes=1024 * 1024,
        max_vault_bytes=1024 * 1024 * 10,
        min_free_bytes=0,
    )
    return app


def _asset(root: Path, *, group_id: str, age_days: int, name: str) -> AssetRecord:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(name.encode("utf-8"))
    return AssetRecord(
        asset_id=uuid4(),
        job_id=uuid4(),
        owner_user_id="alice",
        group_id=group_id,
        visibility=JobVisibility.GROUP,
        filename=name,
        media_type="application/octet-stream",
        size_bytes=path.stat().st_size,
        storage_path=str(path),
        created_at=utcnow().replace(microsecond=0),
    ).model_copy(update={"created_at": utcnow() - __import__("datetime").timedelta(days=age_days)})


def test_retention_cleanup_dry_run_then_delete(tmp_path: Path):
    store = FleetStore()
    asyncio.run(
        store.create_group(
            GroupRecord(
                group_id="alpha",
                name="Alpha",
                policy=GroupPolicy(retention_days=7),
            )
        )
    )
    asyncio.run(
        store.create_group(
            GroupRecord(
                group_id="forever",
                name="Forever",
                policy=GroupPolicy(retention_days=None),
            )
        )
    )

    repository = AssetRepository()
    root = tmp_path / "vault"
    old = _asset(root, group_id="alpha", age_days=10, name="old.bin")
    fresh = _asset(root, group_id="alpha", age_days=1, name="fresh.bin")
    permanent = _asset(root, group_id="forever", age_days=365, name="keep.bin")
    repository.create(old)
    repository.create(fresh)
    repository.create(permanent)

    client = TestClient(_build_app(store, repository, root))
    headers = {"Authorization": f"Bearer {ADMIN_TOKEN}"}

    preview = client.post(
        "/api/v1/admin/assets/retention/cleanup",
        params={"dry_run": "true"},
        headers=headers,
    )
    assert preview.status_code == 200
    assert preview.json()["dry_run"] is True
    assert preview.json()["asset_count"] == 1
    assert repository.get(old.asset_id) is not None
    assert Path(old.storage_path).exists()

    cleanup = client.post(
        "/api/v1/admin/assets/retention/cleanup",
        params={"dry_run": "false"},
        headers=headers,
    )
    assert cleanup.status_code == 200
    assert cleanup.json()["asset_count"] == 1
    assert repository.get(old.asset_id) is None
    assert not Path(old.storage_path).exists()
    assert repository.get(fresh.asset_id) is not None
    assert repository.get(permanent.asset_id) is not None
    assert Path(fresh.storage_path).exists()
    assert Path(permanent.storage_path).exists()


def test_storage_summary_exposes_capacity_not_content_names(tmp_path: Path):
    store = FleetStore()
    asyncio.run(
        store.create_group(
            GroupRecord(group_id="alpha", name="Alpha", policy=GroupPolicy(retention_days=30))
        )
    )
    repository = AssetRepository()
    root = tmp_path / "vault"
    record = _asset(root, group_id="alpha", age_days=0, name="private-client-work.bin")
    repository.create(record)

    client = TestClient(_build_app(store, repository, root))
    response = client.get(
        "/api/v1/admin/assets/storage",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["asset_count"] == 1
    assert payload["groups"][0]["group_id"] == "alpha"
    assert "private-client-work.bin" not in response.text
