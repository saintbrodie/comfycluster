from __future__ import annotations

import subprocess
from pathlib import Path

import yaml

from comfycluster_common.models import ModelInventoryItem, NodeInventoryItem

_MODEL_EXTENSIONS = {".safetensors", ".ckpt", ".pt", ".pth", ".bin", ".gguf"}
_NON_MODEL_KEYS = {"base_path", "is_default", "custom_nodes", "datasets"}


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


def _path_values(value: object) -> list[str]:
    if isinstance(value, str):
        return [line.strip() for line in value.splitlines() if line.strip()]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def discover_model_roots(comfy_home: Path | None) -> list[tuple[str, Path]]:
    """Return Comfy model categories and physical directories.

    Includes ordinary `models/<category>` directories plus paths declared in
    `extra_model_paths.yaml`. The latter matters for shared model libraries.
    """
    if comfy_home is None:
        return []

    roots: list[tuple[str, Path]] = []
    default_root = comfy_home / "models"
    if default_root.is_dir():
        try:
            children = sorted(default_root.iterdir(), key=lambda path: path.name.casefold())
        except OSError:
            children = []
        for child in children:
            if child.is_dir():
                roots.append((child.name, child))

    config_path = comfy_home / "extra_model_paths.yaml"
    if config_path.is_file():
        try:
            config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        except (OSError, UnicodeError, yaml.YAMLError):
            config = {}
        if isinstance(config, dict):
            for section in config.values():
                if not isinstance(section, dict):
                    continue
                base_value = section.get("base_path")
                base = Path(str(base_value)).expanduser() if base_value else comfy_home
                if not base.is_absolute():
                    base = (comfy_home / base).resolve()
                for category, raw_paths in section.items():
                    if category in _NON_MODEL_KEYS:
                        continue
                    for raw_path in _path_values(raw_paths):
                        path = Path(raw_path).expanduser()
                        if not path.is_absolute():
                            path = base / path
                        roots.append((str(category), path))

    deduped: list[tuple[str, Path]] = []
    seen: set[tuple[str, str]] = set()
    for category, path in roots:
        try:
            normalized = path.resolve()
        except OSError:
            normalized = path.absolute()
        key = (category.casefold(), str(normalized).casefold())
        if key not in seen:
            seen.add(key)
            deduped.append((category, normalized))
    return deduped


def scan_models(comfy_home: Path | None) -> list[ModelInventoryItem]:
    items: list[ModelInventoryItem] = []
    seen_files: set[str] = set()
    for category, root in discover_model_roots(comfy_home):
        if not root.is_dir():
            continue
        try:
            paths = root.rglob("*")
            for path in paths:
                if not path.is_file() or path.suffix.lower() not in _MODEL_EXTENSIONS:
                    continue
                try:
                    identity = str(path.resolve()).casefold()
                    size = path.stat().st_size
                    relative = path.relative_to(root)
                except (OSError, ValueError):
                    continue
                if identity in seen_files:
                    continue
                seen_files.add(identity)
                items.append(
                    ModelInventoryItem(
                        category=category,
                        name=str(relative).replace("\\", "/"),
                        path=str(path),
                        size_bytes=size,
                    )
                )
        except OSError:
            continue
    return sorted(items, key=lambda item: (item.category.casefold(), item.name.casefold()))
