from __future__ import annotations

from collections import defaultdict
from typing import Any

from comfycluster_common.models import HostView


def model_matrix(hosts: list[HostView]) -> list[dict[str, Any]]:
    """Build a cluster-wide availability matrix without hashing model files yet."""
    records: dict[tuple[str, str, int], set[str]] = defaultdict(set)
    for host in hosts:
        for model in host.models:
            records[(model.category, model.name, model.size_bytes)].add(host.host_id)

    return [
        {
            "category": category,
            "name": name,
            "size_bytes": size_bytes,
            "hosts": sorted(host_ids),
            "host_count": len(host_ids),
        }
        for (category, name, size_bytes), host_ids in sorted(
            records.items(), key=lambda item: (item[0][0], item[0][1].lower(), item[0][2])
        )
    ]


def node_matrix(hosts: list[HostView]) -> list[dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for host in hosts:
        for node in host.nodes:
            entry = records.setdefault(node.name, {"name": node.name, "hosts": {}})
            entry["hosts"][host.host_id] = {"git_commit": node.git_commit, "path": node.path}
    return [records[name] for name in sorted(records, key=str.lower)]


def compare_release(host: HostView, manifest: dict[str, Any]) -> dict[str, Any]:
    """Compare observed host state to a release manifest.

    Manifest shape intentionally stays close to manifests/release.example.json.
    Missing pins are ignored rather than treated as drift.
    """
    drift: list[dict[str, Any]] = []
    desired_comfy = manifest.get("comfy", {})
    desired_commit = desired_comfy.get("commit")
    observed_commit = host.comfy.git_commit if host.comfy else None
    if desired_commit and observed_commit != desired_commit:
        drift.append(
            {
                "kind": "comfy_commit",
                "expected": desired_commit,
                "observed": observed_commit,
            }
        )

    observed_nodes = {node.name.casefold(): node for node in host.nodes}
    for desired in manifest.get("nodes", []):
        name = desired.get("name")
        if not name:
            continue
        observed = observed_nodes.get(name.casefold())
        if observed is None:
            drift.append({"kind": "node_missing", "name": name})
            continue
        desired_node_commit = desired.get("commit")
        if desired_node_commit and observed.git_commit != desired_node_commit:
            drift.append(
                {
                    "kind": "node_commit",
                    "name": name,
                    "expected": desired_node_commit,
                    "observed": observed.git_commit,
                }
            )

    observed_models = {(m.category.casefold(), m.name.casefold()) for m in host.models}
    for desired in manifest.get("models", []):
        category = str(desired.get("category", "")).casefold()
        name = str(desired.get("name", "")).casefold()
        if category and name and (category, name) not in observed_models:
            drift.append(
                {
                    "kind": "model_missing",
                    "category": desired.get("category"),
                    "name": desired.get("name"),
                }
            )

    return {
        "host_id": host.host_id,
        "release": manifest.get("name"),
        "in_sync": not drift,
        "drift": drift,
    }
