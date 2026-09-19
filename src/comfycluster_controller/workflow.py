from __future__ import annotations

from dataclasses import dataclass
from typing import Any

_MODEL_EXTENSIONS = (".safetensors", ".ckpt", ".pt", ".pth", ".bin", ".gguf")


@dataclass(frozen=True, slots=True)
class WorkflowRequirements:
    node_types: frozenset[str]
    model_refs: frozenset[str]

    def as_dict(self) -> dict[str, list[str]]:
        return {
            "node_types": sorted(self.node_types, key=str.casefold),
            "model_refs": sorted(self.model_refs, key=str.casefold),
        }


def _walk_values(value: Any):
    if isinstance(value, dict):
        for child in value.values():
            yield from _walk_values(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_values(child)
    else:
        yield value


def analyze_workflow(workflow: dict[str, Any]) -> WorkflowRequirements:
    """Extract conservative scheduling hints from API-format workflow JSON.

    This intentionally treats only strings with known model extensions as model
    references. It avoids guessing from arbitrary prompt text. Later this can be
    enriched with Comfy CLI dependency inspection and live object_info schemas.
    """
    node_types: set[str] = set()
    model_refs: set[str] = set()
    for node in workflow.values():
        if not isinstance(node, dict):
            continue
        class_type = node.get("class_type")
        if isinstance(class_type, str) and class_type:
            node_types.add(class_type)
        inputs = node.get("inputs", {})
        for value in _walk_values(inputs):
            if not isinstance(value, str):
                continue
            normalized = value.strip().replace("\\", "/")
            if normalized.casefold().endswith(_MODEL_EXTENSIONS):
                model_refs.add(normalized)
    return WorkflowRequirements(frozenset(node_types), frozenset(model_refs))


def host_has_model(host, model_ref: str) -> bool:
    wanted = model_ref.replace("\\", "/").casefold()
    wanted_base = wanted.rsplit("/", 1)[-1]
    for model in host.models:
        observed = model.name.replace("\\", "/").casefold()
        if observed == wanted or observed.endswith("/" + wanted) or observed.rsplit("/", 1)[-1] == wanted_base:
            return True
    return False
