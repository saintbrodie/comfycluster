from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from comfycluster_common.models import ComfyCliInfo


class ComfyCliError(RuntimeError):
    pass


def _command_exists(discovery: dict[str, Any], *parts: str) -> bool:
    commands = discovery.get("commands", {})
    if not isinstance(commands, dict) or not parts:
        return False
    current = commands.get(parts[0])
    if not isinstance(current, dict):
        return False
    for part in parts[1:]:
        subcommands = current.get("subcommands", {})
        if not isinstance(subcommands, dict):
            return False
        current = subcommands.get(part)
        if not isinstance(current, dict):
            return False
    return True


class ComfyCliAdapter:
    """Small boundary around the official comfy-cli executable.

    ComfyCluster owns fleet desired state. comfy-cli owns Comfy-specific
    installation, dependency and snapshot mechanics. `comfy discover` is used
    as the feature-negotiation contract rather than relying on version guesses.
    """

    def __init__(self, comfy_path: str | Path, executable: str = "comfy") -> None:
        self.comfy_path = Path(comfy_path)
        self.executable = executable

    def available(self) -> bool:
        executable = Path(self.executable)
        if executable.parent != Path(".") or executable.is_absolute():
            return executable.exists()
        return shutil.which(self.executable) is not None

    def _run(
        self,
        args: list[str],
        timeout: float = 120.0,
        *,
        workspace: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        if not self.available():
            raise ComfyCliError(f"{self.executable!r} was not found")
        global_args = ["--json"]
        if workspace:
            global_args.append("--here")
        command = [self.executable, *global_args, *args]
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

    @staticmethod
    def _last_json(stdout: str) -> dict[str, Any]:
        for line in reversed(stdout.splitlines()):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                return value
        raise ComfyCliError("comfy-cli did not emit a JSON object")

    def discover_info(self) -> ComfyCliInfo:
        """Negotiate the installed CLI's structured contract and useful features."""
        if not self.available():
            return ComfyCliInfo(available=False)
        try:
            result = self._run(["discover"], workspace=False)
            envelope = self._last_json(result.stdout)
            if envelope.get("ok") is not True:
                raise ComfyCliError(str(envelope.get("error") or "discover failed"))
            data = envelope.get("data")
            if not isinstance(data, dict):
                raise ComfyCliError("discover envelope did not contain a data object")

            features: list[str] = []
            if _command_exists(data, "node", "deps-in-workflow"):
                features.append("workflow_dependencies")
            if _command_exists(data, "node", "save-snapshot"):
                features.append("snapshots")
            if _command_exists(data, "update"):
                features.append("version_switch")
            if _command_exists(data, "run"):
                features.append("workflow_execution")

            output_contract = data.get("output_contract") or {}
            capabilities = data.get("capabilities") or {}
            return ComfyCliInfo(
                available=True,
                version=str(data.get("version") or envelope.get("version") or "") or None,
                output_contract={str(k): str(v) for k, v in output_contract.items()}
                if isinstance(output_contract, dict)
                else {},
                capabilities=capabilities if isinstance(capabilities, dict) else {},
                management_features=features,
            )
        except ComfyCliError as exc:
            return ComfyCliInfo(available=True, error=str(exc))

    def dependencies_for_workflow(self, workflow: dict[str, Any]) -> dict[str, Any]:
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
        self._run(["update", "comfy", "--version", version], timeout=900.0)

    def save_snapshot(self, output: str | Path) -> Path:
        output_path = Path(output).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        self._run(["node", "save-snapshot", "--output", str(output_path)], timeout=300.0)
        if not output_path.exists():
            raise ComfyCliError("comfy-cli completed without producing a snapshot")
        return output_path
