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
        Path(sys.executable),
    ]
    return next((p for p in candidates if p.exists()), Path(sys.executable))


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
            Path("C:/ComfyUI"),
            Path("C:/AI/ComfyUI"),
        ]
    )

    seen: set[Path] = set()
    for candidate in candidates:
        candidate = candidate.expanduser().resolve()
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
