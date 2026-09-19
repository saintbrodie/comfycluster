from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ComfyReleaseSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str | None = None
    ref: str | None = None
    commit: str | None = None


class PythonReleaseSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str | None = None


class NodeReleaseSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    repo: str | None = None
    version: str | None = None
    commit: str | None = None


class ModelReleaseSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: str
    name: str
    sha256: str | None = None
    size_bytes: int | None = Field(default=None, ge=0)
    source: str | None = None


class LaunchReleaseSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_port: int = Field(default=8188, ge=1, le=65535)
    listen: str = "127.0.0.1"


class ReleaseManifest(BaseModel):
    """Desired ComfyCluster fleet state.

    Models are listed here for availability/integrity policy, but remain data
    assets rather than part of a worker software image.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    comfy: ComfyReleaseSpec = Field(default_factory=ComfyReleaseSpec)
    python: PythonReleaseSpec = Field(default_factory=PythonReleaseSpec)
    nodes: list[NodeReleaseSpec] = Field(default_factory=list)
    models: list[ModelReleaseSpec] = Field(default_factory=list)
    launch: LaunchReleaseSpec = Field(default_factory=LaunchReleaseSpec)
