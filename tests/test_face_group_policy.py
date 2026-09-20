import asyncio
from pathlib import Path
from uuid import uuid4

from fastapi import Header, HTTPException
from fastapi.testclient import TestClient

from comfycluster_common.assets import AssetRecord
from comfycluster_common.models import JobRecord, JobSubmitRequest
from comfycluster_common.tenancy import GroupRecord, Principal
from comfycluster_controller.app import create_app
from comfycluster_controller.asset_api import register_asset_routes
from comfycluster_controller.assets import AssetRepository
from comfycluster_controller.security import authenticate_principal
from comfycluster_controller.store import FleetStore


def test_face_grouping_requires_group_opt_in(tmp_path: Path):
    store = FleetStore()
    asyncio.run(store.create_group(GroupRecord(group_id="alpha", name="Alpha")))
    job = JobRecord(
        request=JobSubmitRequest(workflow={}, group_id="alpha"),
        owner_user_id="alice",
        group_id="alpha",
        assigned_host_id="render-01",
    )
    asyncio.run(store.create_job(job))
    repository = AssetRepository()
    record = AssetRecord(
        asset_id=uuid4(),
        job_id=job.job_id,
        owner_user_id="alice",
        group_id="alpha",
        filename="person.png",
        media_type="image/png",
        storage_path=str(tmp_path / "person.png"),
    )
    repository.create(record)

    app = create_app(store=store, agent_token="agent", admin_token="admin")

    async def current_principal(authorization: str | None = Header(default=None)) -> Principal:
        principal = await authenticate_principal(authorization, store, "admin")
        if principal is None:
            raise HTTPException(status_code=401, detail="authentication required")
        return principal

    register_asset_routes(
        app,
        store=store,
        repository=repository,
        asset_root=tmp_path / "vault",
        agent_token="agent",
        current_principal=current_principal,
        max_asset_bytes=1024,
        max_vault_bytes=4096,
        min_free_bytes=0,
    )
    response = TestClient(app).put(
        f"/api/v1/agents/assets/{record.asset_id}/face-groups",
        params={"host_id": "render-01"},
        json={"face_count": 1, "face_cluster_ids": ["face_0123456789abcdef"]},
        headers={"Authorization": "Bearer agent"},
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "face grouping is disabled for this group"
