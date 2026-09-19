from comfycluster_common.models import (
    ComfyCliInfo,
    ComfyInstallation,
    HostView,
    ModelInventoryItem,
    NodeInventoryItem,
)
from comfycluster_common.releases import ReleaseManifest
from comfycluster_controller.inventory import compare_release
from comfycluster_controller.releases import plan_release_for_host


def _host() -> HostView:
    return HostView(
        host_id="render-01",
        hostname="render-01",
        os_name="Windows",
        os_version="11",
        agent_version="test",
        comfy=ComfyInstallation(
            path="D:/ComfyUI",
            python_executable="python.exe",
            main_py="D:/ComfyUI/main.py",
            git_commit="old-comfy",
        ),
        comfy_cli=ComfyCliInfo(
            available=True,
            version="1.6.1",
            management_features=["version_switch", "snapshots"],
        ),
        nodes=[
            NodeInventoryItem(name="KJNodes", path="D:/ComfyUI/custom_nodes/KJNodes", git_commit="old-node")
        ],
        models=[
            ModelInventoryItem(
                category="checkpoints",
                name="flux.safetensors",
                path="D:/models/flux.safetensors",
                size_bytes=100,
            )
        ],
    )


def test_compare_release_reports_typed_drift():
    manifest = ReleaseManifest.model_validate(
        {
            "name": "prod-2",
            "comfy": {"version": "0.4.0", "commit": "new-comfy"},
            "nodes": [
                {"name": "KJNodes", "commit": "new-node"},
                {"name": "MissingNode", "commit": "abc"},
            ],
            "models": [
                {"category": "checkpoints", "name": "flux.safetensors", "size_bytes": 101},
                {"category": "loras", "name": "style.safetensors"},
            ],
        }
    )

    result = compare_release(_host(), manifest)
    kinds = [item["kind"] for item in result["drift"]]

    assert kinds == [
        "comfy_commit",
        "node_commit",
        "node_missing",
        "model_size",
        "model_missing",
    ]


def test_release_plan_separates_safe_plan_from_unimplemented_mutations():
    manifest = ReleaseManifest.model_validate(
        {
            "name": "prod-2",
            "comfy": {"version": "0.4.0", "commit": "new-comfy"},
            "nodes": [{"name": "KJNodes", "commit": "new-node"}],
        }
    )

    plan = plan_release_for_host(_host(), manifest)

    assert plan["in_sync"] is False
    assert {op["action"] for op in plan["operations"]} == {"comfy.update", "node.reconcile"}
    assert "node_reconciliation_apply_not_implemented" in plan["blockers"]
    assert plan["can_auto_apply"] is False


def test_release_plan_allows_supported_comfy_version_change():
    host = _host()
    host.nodes = []
    host.models = []
    manifest = ReleaseManifest.model_validate(
        {
            "name": "prod-2",
            "comfy": {"version": "0.4.0", "commit": "new-comfy"},
        }
    )

    plan = plan_release_for_host(host, manifest)

    assert plan["operations"] == [{"action": "comfy.update", "target": "0.4.0"}]
    assert plan["blockers"] == []
    assert plan["can_auto_apply"] is True
