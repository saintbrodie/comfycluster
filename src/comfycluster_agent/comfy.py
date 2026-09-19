from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from comfycluster_common.models import ComfyInstallation


def _git_commit(path: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout.strip() or None
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None


def _python_for_comfy(home: Path) -> Path:
    candidates = [
        home.parent / "python_embeded" / "python.exe",
        home / "python_embeded" / "python.exe",
        home / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python"),
        home / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python"),
        Path(sys.executable),
    ]
    return next((p for p in candidates if p.exists()), Path(sys.executable))


def _stability_matrix_candidates() -> list[Path]:
    roots: list[Path] = []
    explicit = os.getenv("STABILITY_MATRIX_HOME")
    if explicit:
        roots.append(Path(explicit))
    appdata = os.getenv("APPDATA")
    if appdata:
        roots.append(Path(appdata) / "StabilityMatrix")

    candidates: list[Path] = []
    for root in roots:
        for packages_dir in (root / "Packages", root / "Data" / "Packages"):
            if not packages_dir.is_dir():
                continue
            direct = packages_dir / "ComfyUI"
            if direct.is_dir():
                candidates.append(direct)
            try:
                package_dirs = sorted(packages_dir.iterdir(), key=lambda item: item.name.casefold())
            except OSError:
                continue
            for package in package_dirs:
                if package.is_dir() and "comfy" in package.name.casefold():
                    candidates.append(package)
    return candidates


def discover_comfy(explicit_home: Path | None = None) -> ComfyInstallation | None:
    candidates: list[Path] = []
    if explicit_home:
        candidates.append(explicit_home)
    env_home = os.getenv("COMFYUI_HOME")
    if env_home:
        candidates.append(Path(env_home))

    cwd = Path.cwd()
    candidates.extend(
        [
            cwd,
            cwd / "ComfyUI",
            cwd.parent / "ComfyUI",
            *_stability_matrix_candidates(),
            Path("C:/ComfyUI"),
            Path("C:/AI/ComfyUI"),
        ]
    )

    seen: set[Path] = set()
    for candidate in candidates:
        try:
            candidate = candidate.expanduser().resolve()
        except OSError:
            continue
        if candidate in seen:
            continue
        seen.add(candidate)
        main_py = candidate / "main.py"
        if main_py.is_file():
            return ComfyInstallation(
                path=str(candidate),
                python_executable=str(_python_for_comfy(candidate)),
                main_py=str(main_py),
                git_commit=_git_commit(candidate),
            )
    return None
