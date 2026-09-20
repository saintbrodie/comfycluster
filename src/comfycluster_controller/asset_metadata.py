from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from comfycluster_common.assets import AssetMetadata
from comfycluster_common.models import JobRecord

_MODEL_EXTENSIONS = (".safetensors", ".ckpt", ".pt", ".pth", ".bin", ".gguf")
_PROMPT_KEYS = {"text", "prompt", "positive", "negative"}


def _unique(values: Iterable[Any]) -> list[Any]:
    seen = set()
    result = []
    for value in values:
        marker = value.casefold() if isinstance(value, str) else value
        if marker in seen:
            continue
        seen.add(marker)
        result.append(value)
    return result


def _normalized_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip().replace("\\", "/")
    return value or None


def _classify_model(key: str, class_type: str, value: str, buckets: dict[str, list[str]]) -> None:
    folded_key = key.casefold()
    folded_class = class_type.casefold()
    if "lora" in folded_key or "lora" in folded_class:
        buckets["loras"].append(value)
    elif "vae" in folded_key or "vae" in folded_class:
        buckets["vaes"].append(value)
    elif "clip" in folded_key or "clip" in folded_class:
        buckets["clips"].append(value)
    elif any(token in folded_key or token in folded_class for token in ("ckpt", "checkpoint", "unet", "model")):
        buckets["models"].append(value)


def extract_asset_metadata(job: JobRecord) -> AssetMetadata:
    """Extract searchable provenance without guessing from arbitrary strings.

    Metadata remains attached to the same tenant-scoped asset authorization boundary
    as the generated file itself. Infrastructure summary endpoints must not expose it.
    """
    workflow = job.request.workflow or {}
    buckets: dict[str, list[str]] = {
        "model_refs": [],
        "models": [],
        "loras": [],
        "vaes": [],
        "clips": [],
        "samplers": [],
        "schedulers": [],
        "prompts": [],
        "node_types": [],
    }
    seeds: list[int] = []
    steps: list[int] = []
    cfg_scales: list[float] = []
    widths: list[int] = []
    heights: list[int] = []

    for node in workflow.values():
        if not isinstance(node, dict):
            continue
        class_type = str(node.get("class_type") or "")
        if class_type:
            buckets["node_types"].append(class_type)
        inputs = node.get("inputs") or {}
        if not isinstance(inputs, dict):
            continue
        for raw_key, raw_value in inputs.items():
            key = str(raw_key)
            folded = key.casefold()
            value = _normalized_string(raw_value)
            if value:
                if value.casefold().endswith(_MODEL_EXTENSIONS):
                    buckets["model_refs"].append(value)
                    _classify_model(key, class_type, value, buckets)
                if folded in {"sampler", "sampler_name"}:
                    buckets["samplers"].append(value)
                elif folded == "scheduler":
                    buckets["schedulers"].append(value)
                if folded in _PROMPT_KEYS and (
                    "text" in class_type.casefold() or "prompt" in folded or folded in {"positive", "negative"}
                ):
                    buckets["prompts"].append(value[:20000])
            if isinstance(raw_value, bool):
                continue
            if isinstance(raw_value, int):
                if "seed" in folded:
                    seeds.append(raw_value)
                elif folded == "steps":
                    steps.append(raw_value)
                elif folded == "width" and raw_value > 0:
                    widths.append(raw_value)
                elif folded == "height" and raw_value > 0:
                    heights.append(raw_value)
            elif isinstance(raw_value, float) and folded in {"cfg", "cfg_scale"}:
                cfg_scales.append(raw_value)
            elif isinstance(raw_value, int) and folded in {"cfg", "cfg_scale"}:
                cfg_scales.append(float(raw_value))

    request_metadata = job.request.metadata or {}
    tags = request_metadata.get("tags") or []
    if isinstance(tags, str):
        tags = [tags]
    workflow_name = request_metadata.get("workflow_name") or request_metadata.get("name")

    return AssetMetadata(
        workflow_name=str(workflow_name) if workflow_name else None,
        tags=_unique(str(tag).strip() for tag in tags if str(tag).strip()),
        node_types=_unique(buckets["node_types"]),
        model_refs=_unique(buckets["model_refs"]),
        models=_unique(buckets["models"]),
        loras=_unique(buckets["loras"]),
        vaes=_unique(buckets["vaes"]),
        clips=_unique(buckets["clips"]),
        samplers=_unique(buckets["samplers"]),
        schedulers=_unique(buckets["schedulers"]),
        seeds=_unique(seeds),
        steps=_unique(steps),
        cfg_scales=_unique(cfg_scales),
        prompts=_unique(buckets["prompts"]),
        width=max(widths, default=None),
        height=max(heights, default=None),
        host_id=job.assigned_host_id,
        worker_id=job.assigned_worker_id,
        gpu_name=job.assigned_gpu_name,
        runtime_seconds=job.runtime_seconds,
    )
