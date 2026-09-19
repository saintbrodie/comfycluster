from pathlib import Path

from comfycluster_agent.inventory import scan_custom_nodes, scan_models


def test_inventory_scans_nodes_and_models(tmp_path: Path):
    (tmp_path / "custom_nodes" / "ExampleNode").mkdir(parents=True)
    model = tmp_path / "models" / "checkpoints" / "example.safetensors"
    model.parent.mkdir(parents=True)
    model.write_bytes(b"1234")

    nodes = scan_custom_nodes(tmp_path)
    models = scan_models(tmp_path)

    assert [item.name for item in nodes] == ["ExampleNode"]
    assert len(models) == 1
    assert models[0].category == "checkpoints"
    assert models[0].size_bytes == 4
