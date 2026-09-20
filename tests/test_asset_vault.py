from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import Header, HTTPException
from fastapi.testclient import TestClient

from comfycluster_common.models import JobRecord, JobSubmitRequest
from comfycluster_common.tenancy import GroupPolicy, GroupRecord, MembershipRecord, UserRecord
from comfycluster_controller.app import create_app
from comfycluster_controller.asset_api import register_asset_routes
from comfycluster_controller.assets import AssetRepository
from comfycluster_controller.security import authenticate_principal
from comfycluster_controller.store import FleetStore


ADMIN_TOKEN = "admin-secret"
AGENT_TOKEN = "agent-secret"


async def _seed_tenants(store: FleetStore):
    await store.create_group(
        GroupRecord(
            group_id="alpha",
            name="Alpha",
            policy=GroupPolicy(max_storage_bytes=1024),
        )
    )
    await store.create_group(GroupRecord(group_id="beta", name="Beta"))
    await store.create_user(UserRecord(user_id="alice", display_name="Alice"))
    await store.create_user(UserRecord(user_id="amy", display_name="Amy"))
    await store.create_user(UserRecord(user_id="bob", display_name="Bob"))
    await store.add_membership(MembershipRecord(user_id="alice", group_id="alpha"))
    await store.add_membership(MembershipRecord(user_id="amy", group_id="alpha"))
    await store.add_membership(MembershipRecord(user_id="bob", group_id="beta"))
    alice = await store.issue_token("alice")
    amy = await store.issue_token("amy")
    bob = await store.issue_token("bob")
    return alice.token, amy.token, bob.token


def _asset_app(store: FleetStore, repository: AssetRepository, root: Path):
    app = create_app(store=store, agent_token=AGENT_TOKEN, admin_token=ADMIN_TOKEN)

    async def current_principal(authorization: str | None = Header(default=None)):
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
        max_asset_bytes=2048,
        max_vault_bytes=4096,
        min_free_bytes=0,
    )
    return app


def test_asset_content_is_private_to_owner_group(tmp_path: Path):
    import asyncio

    store = FleetStore()
    alice_token, amy_token, bob_token = asyncio.run(_seed_tenants(store))
    job = JobRecord(
        request=JobSubmitRequest(workflow={}, group_id="alpha"),
        owner_user_id="alice",
        group_id="alpha",
        assigned_host_id="render-01",
    )
    asyncio.run(store.create_job(job))

    repository = AssetRepository()
    client = TestClient(_asset_app(store, repository, tmp_path / "assets"))
    asset_id = uuid4()
    uploaded = client.put(
        f"/api/v1/agents/jobs/{job.job_id}/assets/{asset_id}",
        params={"filename": "private.png", "node_id": "12", "host_id": "render-01"},
        content=b"secret-image",
        headers={
            "Authorization": f"Bearer {AGENT_TOKEN}",
            "Content-Type": "image/png",
        },
    )
    assert uploaded.status_code == 200
    assert "storage_path" not in uploaded.json()

    alice = {"Authorization": f"Bearer {alice_token}"}
    amy = {"Authorization": f"Bearer {amy_token}"}
    bob = {"Authorization": f"Bearer {bob_token}"}
    admin = {"Authorization": f"Bearer {ADMIN_TOKEN}"}

    assert client.get("/api/v1/assets", headers=alice).json()[0]["filename"] == "private.png"
    assert client.get("/api/v1/assets", headers=amy).json()[0]["filename"] == "private.png"
    assert client.get("/api/v1/assets", headers=bob).json() == []
    assert client.get("/api/v1/assets", headers=admin).json() == []

    assert client.get(f"/api/v1/assets/{asset_id}/content", headers=alice).content == b"secret-image"
    assert client.get(f"/api/v1/assets/{asset_id}/content", headers=amy).status_code == 200
    assert client.get(f"/api/v1/assets/{asset_id}/content", headers=bob).status_code == 404
    assert client.get(f"/api/v1/assets/{asset_id}/content", headers=admin).status_code == 404

    # Infrastructure admins may perform retention cleanup without receiving content access.
    assert client.delete(f"/api/v1/assets/{asset_id}", headers=admin).status_code == 204
    assert client.get(f"/api/v1/assets/{asset_id}/content", headers=alice).status_code == 404


def test_asset_upload_enforces_group_storage_quota(tmp_path: Path):
    import asyncio

    store = FleetStore()
    alice_token, _, _ = asyncio.run(_seed_tenants(store))
    job = JobRecord(
        request=JobSubmitRequest(workflow={}, group_id="alpha"),
        owner_user_id="alice",
        group_id="alpha",
        assigned_host_id="render-01",
    )
    asyncio.run(store.create_job(job))
    client = TestClient(_asset_app(store, AssetRepository(), tmp_path / "assets"))

    too_large_for_group = b"x" * 1025
    response = client.put(
        f"/api/v1/agents/jobs/{job.job_id}/assets/{uuid4()}",
        params={"filename": "huge.bin", "host_id": "render-01"},
        content=too_large_for_group,
        headers={"Authorization": f"Bearer {AGENT_TOKEN}"},
    )
    assert response.status_code == 507
    assert response.json()["detail"] == "group storage quota reached"
    assert client.get("/api/v1/assets", headers={"Authorization": f"Bearer {alice_token}"}).json() == []


def test_asset_metadata_survives_repository_restart(tmp_path: Path):
    from comfycluster_common.assets import AssetRecord

    database = tmp_path / "fleet.db"
    first = AssetRepository(database)
    record = AssetRecord(
        asset_id=uuid4(),
        job_id=uuid4(),
        owner_user_id="alice",
        group_id="alpha",
        filename="x.png",
        media_type="image/png",
        size_bytes=3,
        storage_path=str(tmp_path / "x.png"),
    )
    first.create(record)
    first.close()

    second = AssetRepository(database)
    restored = second.get(record.asset_id)
    assert restored is not None
    assert restored.filename == "x.png"
    assert second.total_size_bytes() == 3
    second.close()


def test_agent_cannot_upload_asset_for_another_host_job(tmp_path: Path):
    import asyncio

    store = FleetStore()
    asyncio.run(_seed_tenants(store))
    job = JobRecord(
        request=JobSubmitRequest(workflow={}, group_id="alpha"),
        owner_user_id="alice",
        group_id="alpha",
        assigned_host_id="render-01",
    )
    asyncio.run(store.create_job(job))
    client = TestClient(_asset_app(store, AssetRepository(), tmp_path / "assets"))

    response = client.put(
        f"/api/v1/agents/jobs/{job.job_id}/assets/{uuid4()}",
        params={"filename": "wrong.png", "host_id": "render-99"},
        content=b"nope",
        headers={"Authorization": f"Bearer {AGENT_TOKEN}"},
    )
    assert response.status_code == 403
