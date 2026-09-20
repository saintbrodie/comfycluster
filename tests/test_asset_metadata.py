import asyncio
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from fastapi import Header, HTTPException
from fastapi.testclient import TestClient
from PIL import Image

from comfycluster_common.assets import AssetRecord
from comfycluster_common.models import JobRecord, JobSubmitRequest
from comfycluster_common.tenancy import GroupPolicy, GroupRecord, MembershipRecord, Principal, UserRecord
from comfycluster_controller.app import create_app
from comfycluster_controller.asset_api import register_asset_routes
from comfycluster_controller.asset_metadata import extract_asset_metadata
from comfycluster_controller.assets import AssetRepository
from comfycluster_controller.security import authenticate_principal
from comfycluster_controller.store import FleetStore

ADMIN_TOKEN = "admin-secret"
AGENT_TOKEN = "agent-secret"


def _workflow() -> dict:
    return {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "flux/dev.safetensors"}},
        "2": {"class_type": "LoraLoader", "inputs": {"lora_name": "people/style.safetensors"}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": "orange cat in a studio"}},
        "4": {
            "class_type": "KSampler",
            "inputs": {
                "sampler_name": "euler",
                "scheduler": "normal",
                "seed": 12345,
                "steps": 28,
                "cfg": 4,
            },
        },
        "5": {"class_type": "EmptyLatentImage", "inputs": {"width": 1024, "height": 768}},
    }


def test_extract_asset_metadata_from_comfy_workflow():
    job = JobRecord(
        request=JobSubmitRequest(
            workflow=_workflow(),
            metadata={"workflow_name": "Product Portrait", "tags": ["client-a", "portrait"]},
        ),
        assigned_host_id="render-01",
        assigned_worker_id="render-01-gpu0",
        assigned_gpu_name="RTX 5000 Ada",
    )
    metadata = extract_asset_metadata(job)
    assert metadata.workflow_name == "Product Portrait"
    assert metadata.models == ["flux/dev.safetensors"]
    assert metadata.loras == ["people/style.safetensors"]
    assert metadata.samplers == ["euler"]
    assert metadata.schedulers == ["normal"]
    assert metadata.seeds == [12345]
    assert metadata.steps == [28]
    assert metadata.cfg_scales == [4.0]
    assert metadata.width == 1024
    assert metadata.height == 768
    assert "orange cat in a studio" in metadata.prompts


def test_repository_filters_only_authorized_metadata():
    repository = AssetRepository()
    alice = Principal(user_id="alice", display_name="Alice", group_ids=["alpha"])
    bob = Principal(user_id="bob", display_name="Bob", group_ids=["beta"])
    job = JobRecord(
        request=JobSubmitRequest(workflow=_workflow(), group_id="alpha"),
        owner_user_id="alice",
        group_id="alpha",
    )
    record = AssetRecord(
        asset_id=uuid4(),
        job_id=job.job_id,
        owner_user_id="alice",
        group_id="alpha",
        filename="portrait.png",
        media_type="image/png",
        size_bytes=10,
        metadata=extract_asset_metadata(job),
        storage_path="x",
    )
    repository.create(record)

    assert len(repository.query_for_principal(alice, model="flux")) == 1
    assert len(repository.query_for_principal(alice, lora="style")) == 1
    assert len(repository.query_for_principal(alice, q="orange cat")) == 1
    assert repository.query_for_principal(bob, q="orange cat") == []
    facets = repository.facets_for_principal(alice)
    assert "flux/dev.safetensors" in facets["models"]
    assert "people/style.safetensors" in facets["loras"]
    assert repository.facets_for_principal(bob)["models"] == []


def _app(store: FleetStore, repository: AssetRepository, root: Path):
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
        max_asset_bytes=1024 * 1024,
        max_vault_bytes=1024 * 1024 * 20,
        min_free_bytes=0,
    )
    return app


def test_uploaded_image_gets_real_dimensions_thumbnail_and_provenance(tmp_path: Path):
    store = FleetStore()
    asyncio.run(store.create_group(GroupRecord(group_id="alpha", name="Alpha")))
    asyncio.run(store.create_user(UserRecord(user_id="alice", display_name="Alice")))
    asyncio.run(store.add_membership(MembershipRecord(user_id="alice", group_id="alpha")))
    token = asyncio.run(store.issue_token("alice")).token
    job = JobRecord(
        request=JobSubmitRequest(workflow=_workflow(), group_id="alpha"),
        owner_user_id="alice",
        group_id="alpha",
        assigned_host_id="render-01",
    )
    asyncio.run(store.create_job(job))

    image = Image.new("RGB", (640, 360), "orange")
    data = BytesIO()
    image.save(data, "PNG")
    body = data.getvalue()
    client = TestClient(_app(store, AssetRepository(), tmp_path / "vault"))
    asset_id = uuid4()
    upload = client.put(
        f"/api/v1/agents/jobs/{job.job_id}/assets/{asset_id}",
        params={"filename": "output.png", "host_id": "render-01"},
        content=body,
        headers={
            "Authorization": f"Bearer {AGENT_TOKEN}",
            "Content-Type": "image/png",
        },
    )
    assert upload.status_code == 200
    assert upload.json()["metadata"]["width"] == 640
    assert upload.json()["metadata"]["height"] == 360
    assert upload.json()["metadata"]["models"] == ["flux/dev.safetensors"]

    headers = {"Authorization": f"Bearer {token}"}
    thumbnail = client.get(f"/api/v1/assets/{asset_id}/thumbnail", headers=headers)
    assert thumbnail.status_code == 200
    assert thumbnail.headers["content-type"].startswith("image/jpeg")


def test_face_groups_are_opaque_and_filterable(tmp_path: Path):
    store = FleetStore()
    asyncio.run(
        store.create_group(
            GroupRecord(
                group_id="alpha",
                name="Alpha",
                policy=GroupPolicy(face_grouping_enabled=True),
            )
        )
    )
    asyncio.run(store.create_user(UserRecord(user_id="alice", display_name="Alice")))
    asyncio.run(store.add_membership(MembershipRecord(user_id="alice", group_id="alpha")))
    token = asyncio.run(store.issue_token("alice")).token
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
    client = TestClient(_app(store, repository, tmp_path / "vault"))

    bad = client.put(
        f"/api/v1/agents/assets/{record.asset_id}/face-groups",
        params={"host_id": "render-01"},
        json={"face_count": 1, "face_cluster_ids": ["face_alice"]},
        headers={"Authorization": f"Bearer {AGENT_TOKEN}"},
    )
    assert bad.status_code == 400

    cluster_id = "face_0123456789abcdef"
    good = client.put(
        f"/api/v1/agents/assets/{record.asset_id}/face-groups",
        params={"host_id": "render-01"},
        json={"face_count": 1, "face_cluster_ids": [cluster_id]},
        headers={"Authorization": f"Bearer {AGENT_TOKEN}"},
    )
    assert good.status_code == 200
    headers = {"Authorization": f"Bearer {token}"}
    filtered = client.get(
        "/api/v1/assets", params={"face_cluster_id": cluster_id}, headers=headers
    )
    assert filtered.status_code == 200
    assert len(filtered.json()) == 1
