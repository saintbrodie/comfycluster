from __future__ import annotations

from collections import defaultdict
from typing import Any

from comfycluster_common.models import HostView
from comfycluster_common.releases import ReleaseManifest


def model_matrix(hosts: list[HostView]) -> list[dict[str, Any]]:
    """Build a cluster-wide availability matrix without forcing model hashing."""
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


def compare_release(host: HostView, manifest: ReleaseManifest) -> dict[str, Any]:
    """Compare observed host state to a typed release manifest."""
    drift: list[dict[str, Any]] = []
    desired_commit = manifest.comfy.commit
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
    for desired in manifest.nodes:
        observed = observed_nodes.get(desired.name.casefold())
        if observed is None:
            drift.append({"kind": "node_missing", "name": desired.name})
            continue
        if desired.commit and observed.git_commit != desired.commit:
            drift.append(
                {
                    "kind": "node_commit",
                    "name": desired.name,
                    "expected": desired.commit,
                    "observed": observed.git_commit,
                }
            )

    observed_models = {
        (model.category.casefold(), model.name.casefold()): model for model in host.models
    }
    for desired in manifest.models:
        key = (desired.category.casefold(), desired.name.casefold())
        observed = observed_models.get(key)
        if observed is None:
            drift.append(
                {
                    "kind": "model_missing",
                    "category": desired.category,
                    "name": desired.name,
                }
            )
            continue
        if desired.size_bytes is not None and observed.size_bytes != desired.size_bytes:
            drift.append(
                {
                    "kind": "model_size",
                    "category": desired.category,
                    "name": desired.name,
                    "expected": desired.size_bytes,
                    "observed": observed.size_bytes,
                }
            )
        if desired.sha256 and observed.sha256 and observed.sha256.casefold() != desired.sha256.casefold():
            drift.append(
                {
                    "kind": "model_hash",
                    "category": desired.category,
                    "name": desired.name,
                    "expected": desired.sha256,
                    "observed": observed.sha256,
                }
            )

    return {
        "host_id": host.host_id,
        "release": manifest.name,
        "in_sync": not drift,
        "drift": drift,
    }
