from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any


class ComfyCliError(RuntimeError):
    pass


class ComfyCliAdapter:
    """Small boundary around the official comfy-cli executable.

    ComfyCluster should orchestrate desired state, not reimplement Comfy's own
    package-management behavior. Keeping subprocess details here also makes it
    straightforward to replace or expand comfy-cli integrations independently
    of the Windows runtime.
    """

    def __init__(self, comfy_path: str | Path, executable: str = "comfy") -> None:
        self.comfy_path = Path(comfy_path)
        self.executable = executable

    def available(self) -> bool:
        return shutil.which(self.executable) is not None

    def _run(self, args: list[str], timeout: float = 120.0) -> subprocess.CompletedProcess[str]:
        if not self.available():
            raise ComfyCliError(f"{self.executable!r} was not found on PATH")
        command = [self.executable, "--json", "--here", *args]
        try:
            result = subprocess.run(
                command,
                cwd=self.comfy_path,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ComfyCliError(f"failed to run comfy-cli: {exc}") from exc
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip() or "unknown comfy-cli error"
            raise ComfyCliError(f"comfy-cli exited {result.returncode}: {detail}")
        return result

    def dependencies_for_workflow(self, workflow: dict[str, Any]) -> dict[str, Any]:
        """Ask comfy-cli/ComfyUI-Manager to resolve workflow custom-node dependencies.

        The dependency file format belongs to comfy-cli/Manager, so this method
        intentionally returns it as an opaque dict. Higher layers can consume
        stable fields as we validate them without coupling the subprocess layer
        to a particular Manager release.
        """
        with tempfile.TemporaryDirectory(prefix="comfycluster-deps-") as temp_dir:
            temp = Path(temp_dir)
            workflow_path = temp / "workflow.json"
            output_path = temp / "dependencies.json"
            workflow_path.write_text(json.dumps(workflow), encoding="utf-8")
            self._run(
                [
                    "node",
                    "deps-in-workflow",
                    f"--workflow={workflow_path}",
                    f"--output={output_path}",
                ]
            )
            if not output_path.exists():
                raise ComfyCliError("comfy-cli completed without producing a dependency file")
            try:
                value = json.loads(output_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ComfyCliError(f"could not read comfy-cli dependency output: {exc}") from exc
            if not isinstance(value, dict):
                raise ComfyCliError("comfy-cli dependency output was not a JSON object")
            return value

    def switch_comfy_version(self, version: str) -> None:
        """Move the local Comfy checkout to a specific comfy-cli version target."""
        self._run(["update", "comfy", "--version", version], timeout=900.0)

    def save_snapshot(self, output: str | Path) -> Path:
        """Save the current custom-node environment using comfy-cli."""
        output_path = Path(output).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        self._run(["node", "save-snapshot", "--output", str(output_path)], timeout=300.0)
        if not output_path.exists():
            raise ComfyCliError("comfy-cli completed without producing a snapshot")
        return output_path
