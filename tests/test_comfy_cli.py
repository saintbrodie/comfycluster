from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from comfycluster_agent.comfy_cli import ComfyCliAdapter, ComfyCliError


def test_comfy_cli_dependencies_for_workflow_reads_generated_file(monkeypatch, tmp_path):
    captured: list[list[str]] = []

    monkeypatch.setattr("comfycluster_agent.comfy_cli.shutil.which", lambda _name: "comfy.exe")

    def fake_run(command, **kwargs):
        captured.append(command)
        output_arg = next(arg for arg in command if arg.startswith("--output="))
        output_path = Path(output_arg.split("=", 1)[1])
        output_path.write_text(json.dumps({"custom_nodes": {"example": "1.0"}}), encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, stdout="{}", stderr="")

    monkeypatch.setattr("comfycluster_agent.comfy_cli.subprocess.run", fake_run)

    adapter = ComfyCliAdapter(tmp_path)
    result = adapter.dependencies_for_workflow(
        {"1": {"class_type": "ExampleNode", "inputs": {}}}
    )

    assert result == {"custom_nodes": {"example": "1.0"}}
    assert captured
    assert captured[0][:4] == ["comfy", "--json", "--here", "node"]
    assert "deps-in-workflow" in captured[0]


def test_comfy_cli_reports_missing_executable(monkeypatch, tmp_path):
    monkeypatch.setattr("comfycluster_agent.comfy_cli.shutil.which", lambda _name: None)
    adapter = ComfyCliAdapter(tmp_path)

    with pytest.raises(ComfyCliError, match="not found on PATH"):
        adapter.dependencies_for_workflow({})


def test_comfy_cli_surfaces_command_failure(monkeypatch, tmp_path):
    monkeypatch.setattr("comfycluster_agent.comfy_cli.shutil.which", lambda _name: "comfy.exe")

    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(command, 7, stdout="", stderr="manager exploded")

    monkeypatch.setattr("comfycluster_agent.comfy_cli.subprocess.run", fake_run)
    adapter = ComfyCliAdapter(tmp_path)

    with pytest.raises(ComfyCliError, match="manager exploded"):
        adapter.switch_comfy_version("0.3.0")
