from pathlib import Path

from comfycluster_agent.comfy import discover_comfy


def test_discovers_stability_matrix_comfy(monkeypatch, tmp_path: Path):
    appdata = tmp_path / "Roaming"
    comfy = appdata / "StabilityMatrix" / "Packages" / "ComfyUI"
    comfy.mkdir(parents=True)
    (comfy / "main.py").write_text("# fake comfy", encoding="utf-8")
    monkeypatch.setenv("APPDATA", str(appdata))
    monkeypatch.chdir(tmp_path)

    found = discover_comfy()
    assert found is not None
    assert Path(found.path) == comfy.resolve()


def test_explicit_comfy_path_wins(monkeypatch, tmp_path: Path):
    explicit = tmp_path / "chosen"
    explicit.mkdir()
    (explicit / "main.py").write_text("# chosen", encoding="utf-8")

    appdata = tmp_path / "Roaming"
    other = appdata / "StabilityMatrix" / "Packages" / "ComfyUI"
    other.mkdir(parents=True)
    (other / "main.py").write_text("# other", encoding="utf-8")
    monkeypatch.setenv("APPDATA", str(appdata))

    found = discover_comfy(explicit)
    assert found is not None
    assert Path(found.path) == explicit.resolve()
