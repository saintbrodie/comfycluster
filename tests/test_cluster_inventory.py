from comfycluster_common.models import (
    ComfyInstallation,
    HostView,
    ModelInventoryItem,
    NodeInventoryItem,
)
from comfycluster_controller.inventory import compare_release, model_matrix, node_matrix


def _host(host_id: str, *, commit: str = "comfy-a") -> HostView:
    return HostView(
        host_id=host_id,
        hostname=host_id,
        os_name="Windows",
        os_version="11",
        agent_version="test",
        comfy=ComfyInstallation(
            path="C:/ComfyUI",
            python_executable="python.exe",
            main_py="C:/ComfyUI/main.py",
            git_commit=commit,
        ),
        nodes=[NodeInventoryItem(name="KJNodes", path="nodes/KJNodes", git_commit="node-a")],
        models=[
            ModelInventoryItem(
                category="checkpoints",
                name="flux.safetensors",
                path="models/checkpoints/flux.safetensors",
                size_bytes=100,
            )
        ],
    )


def test_model_and_node_matrices_aggregate_hosts():
    models = model_matrix([_host("a"), _host("b")])
    assert models[0]["host_count"] == 2
    assert models[0]["hosts"] == ["a", "b"]

    nodes = node_matrix([_host("a"), _host("b")])
    assert sorted(nodes[0]["hosts"]) == ["a", "b"]


def test_release_comparison_reports_real_drift():
    manifest = {
        "name": "prod-2",
        "comfy": {"commit": "comfy-b"},
        "nodes": [
            {"name": "KJNodes", "commit": "node-b"},
            {"name": "Impact-Pack", "commit": "impact-a"},
        ],
        "models": [
            {"category": "checkpoints", "name": "flux.safetensors"},
            {"category": "loras", "name": "style.safetensors"},
        ],
    }
    result = compare_release(_host("render-01"), manifest)
    assert result["in_sync"] is False
    assert {item["kind"] for item in result["drift"]} == {
        "comfy_commit",
        "node_commit",
        "node_missing",
        "model_missing",
    }
