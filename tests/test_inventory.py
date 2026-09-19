from pathlib import Path

from comfycluster_agent.inventory import discover_model_roots, scan_custom_nodes, scan_models


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
    assert models[0].name == "example.safetensors"
    assert models[0].size_bytes == 4


def test_inventory_reads_extra_model_paths(tmp_path: Path):
    shared = tmp_path / "shared"
    lora = shared / "loras" / "style.safetensors"
    clip = shared / "text" / "clip.safetensors"
    lora.parent.mkdir(parents=True)
    clip.parent.mkdir(parents=True)
    lora.write_bytes(b"lora")
    clip.write_bytes(b"clip")

    (tmp_path / "extra_model_paths.yaml").write_text(
        """
shared:
  base_path: shared
  loras: loras
  text_encoders: |
    text
""",
        encoding="utf-8",
    )

    roots = discover_model_roots(tmp_path)
    models = scan_models(tmp_path)
    assert ("loras", (shared / "loras").resolve()) in roots
    assert {(item.category, item.name) for item in models} == {
        ("loras", "style.safetensors"),
        ("text_encoders", "clip.safetensors"),
    }


def test_inventory_deduplicates_same_physical_model(tmp_path: Path):
    model = tmp_path / "models" / "checkpoints" / "same.safetensors"
    model.parent.mkdir(parents=True)
    model.write_bytes(b"same")
    (tmp_path / "extra_model_paths.yaml").write_text(
        """
local:
  base_path: .
  checkpoints: models/checkpoints
""",
        encoding="utf-8",
    )

    models = scan_models(tmp_path)
    assert len(models) == 1
