from __future__ import annotations

import subprocess
from pathlib import Path

from comfycluster_common.models import ModelInventoryItem, NodeInventoryItem

_MODEL_EXTENSIONS = {".safetensors", ".ckpt", ".pt", ".pth", ".bin", ".gguf"}


def _git_commit(path: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=3,
        )
        return result.stdout.strip() or None
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None


def scan_custom_nodes(comfy_home: Path | None) -> list[NodeInventoryItem]:
    if comfy_home is None:
        return []
    root = comfy_home / "custom_nodes"
    if not root.is_dir():
        return []
    items: list[NodeInventoryItem] = []
    for path in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        if path.is_dir() and not path.name.startswith((".", "__")):
            items.append(NodeInventoryItem(name=path.name, path=str(path), git_commit=_git_commit(path)))
    return items


def scan_models(comfy_home: Path | None) -> list[ModelInventoryItem]:
    if comfy_home is None:
        return []
    root = comfy_home / "models"
    if not root.is_dir():
        return []
    items: list[ModelInventoryItem] = []
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in _MODEL_EXTENSIONS:
            continue
        relative = path.relative_to(root)
        category = relative.parts[0] if len(relative.parts) > 1 else "other"
        try:
            size = path.stat().st_size
        except OSError:
            continue
        items.append(
            ModelInventoryItem(
                category=category,
                name=str(relative).replace("\\", "/"),
                path=str(path),
                size_bytes=size,
            )
        )
    return sorted(items, key=lambda item: (item.category, item.name.lower()))
