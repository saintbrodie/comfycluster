from datetime import timedelta
from pathlib import Path
from uuid import uuid4

from comfycluster_common.assets import AssetMetadata, AssetRecord
from comfycluster_common.models import JobVisibility, utcnow
from comfycluster_common.tenancy import Principal
from comfycluster_controller.assets import AssetRepository


def _record(index: int, *, group_id: str = "alpha", owner: str = "alice") -> AssetRecord:
    created = utcnow() - timedelta(seconds=index)
    return AssetRecord(
        asset_id=uuid4(),
        job_id=uuid4(),
        owner_user_id=owner,
        group_id=group_id,
        visibility=JobVisibility.GROUP,
        filename=f"output-{index:04d}.png",
        media_type="image/png",
        size_bytes=1000 + index,
        metadata=AssetMetadata(
            workflow_name="Campaign Portrait",
            models=["flux/dev.safetensors" if index % 2 == 0 else "sdxl/base.safetensors"],
            loras=["brand/style.safetensors"],
            samplers=["euler"],
            seeds=[1000 + index],
            prompts=[f"private campaign prompt number {index}"],
            width=1024,
            height=768,
        ),
        storage_path=f"x/{index}.png",
        created_at=created,
    )


def test_paged_asset_search_returns_lightweight_summaries_and_total():
    repository = AssetRepository()
    alice = Principal(user_id="alice", display_name="Alice", group_ids=["alpha"])
    for index in range(125):
        repository.create(_record(index))
    for index in range(8):
        repository.create(_record(1000 + index, group_id="beta", owner="bob"))

    page = repository.query_page_for_principal(alice, offset=20, limit=20)
    assert page.total == 125
    assert page.offset == 20
    assert page.limit == 20
    assert len(page.items) == 20
    assert page.has_more is True
    assert not hasattr(page.items[0].metadata, "prompts")

    prompt_page = repository.query_page_for_principal(
        alice,
        q="private campaign prompt number 42",
        offset=0,
        limit=20,
    )
    assert prompt_page.total == 1
    assert prompt_page.items[0].filename == "output-0042.png"


def test_paged_search_respects_tenant_boundary_and_server_sorting():
    repository = AssetRepository()
    alice = Principal(user_id="alice", display_name="Alice", group_ids=["alpha"])
    bob = Principal(user_id="bob", display_name="Bob", group_ids=["beta"])
    for index in range(5):
        repository.create(_record(index))
    repository.create(_record(99, group_id="beta", owner="bob"))

    alpha = repository.query_page_for_principal(
        alice,
        sort_by="filename",
        sort_order="asc",
        offset=0,
        limit=10,
    )
    assert alpha.total == 5
    assert [item.filename for item in alpha.items] == sorted(item.filename for item in alpha.items)
    assert all(item.group_id == "alpha" for item in alpha.items)

    beta = repository.query_page_for_principal(bob, q="campaign")
    assert beta.total == 1
    assert beta.items[0].group_id == "beta"


def test_sqlite_asset_index_survives_restart_and_filters_without_rich_response(tmp_path: Path):
    database = tmp_path / "fleet.sqlite"
    alice = Principal(user_id="alice", display_name="Alice", group_ids=["alpha"])
    repository = AssetRepository(database)
    for index in range(35):
        record = _record(index)
        if index == 17:
            record.metadata = record.metadata.model_copy(
                update={
                    "video_codec": "h264",
                    "duration_seconds": 12.5,
                    "prompts": ["needle prompt only in full metadata"],
                }
            )
            record.media_type = "video/mp4"
        repository.create(record)
    repository.close()

    reopened = AssetRepository(database)
    page = reopened.query_page_for_principal(
        alice,
        q="needle prompt",
        video_codec="h264",
        min_duration_seconds=10,
        max_duration_seconds=15,
        offset=0,
        limit=10,
    )
    assert page.total == 1
    assert page.items[0].media_type == "video/mp4"
    assert page.items[0].metadata.video_codec == "h264"
    assert not hasattr(page.items[0].metadata, "prompts")
    reopened.close()
