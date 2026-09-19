from __future__ import annotations

from typing import Any

from comfycluster_common.models import HostView
from comfycluster_common.releases import ReleaseManifest

from .inventory import compare_release


def plan_release_for_host(host: HostView, manifest: ReleaseManifest) -> dict[str, Any]:
    comparison = compare_release(host, manifest)
    operations: list[dict[str, Any]] = []
    blockers: list[str] = []

    for item in comparison["drift"]:
        kind = item["kind"]
        if kind == "comfy_commit":
            target = manifest.comfy.version or manifest.comfy.commit or manifest.comfy.ref
            operations.append({"action": "comfy.update", "target": target})
            if not host.comfy_cli.available:
                blockers.append("comfy_cli_unavailable")
            elif "version_switch" not in host.comfy_cli.management_features:
                blockers.append("comfy_version_management_unsupported")
            elif not manifest.comfy.version:
                blockers.append("commit_pinning_apply_not_implemented")
        elif kind in {"node_missing", "node_commit"}:
            operations.append(
                {
                    "action": "node.reconcile",
                    "name": item.get("name"),
                }
            )
            if not host.comfy_cli.available:
                blockers.append("comfy_cli_unavailable")
            blockers.append("node_reconciliation_apply_not_implemented")
        elif kind.startswith("model_"):
            operations.append(
                {
                    "action": "model.sync",
                    "category": item.get("category"),
                    "name": item.get("name"),
                }
            )
            blockers.append("model_sync_apply_not_implemented")

    # Preserve order while keeping the explanation compact.
    blockers = list(dict.fromkeys(blockers))
    return {
        **comparison,
        "operations": operations,
        "blockers": blockers,
        "can_auto_apply": bool(operations) and not blockers,
    }


def plan_release(hosts: list[HostView], manifest: ReleaseManifest) -> dict[str, Any]:
    plans = [plan_release_for_host(host, manifest) for host in hosts]
    return {
        "release": manifest.name,
        "host_count": len(plans),
        "in_sync_count": sum(1 for plan in plans if plan["in_sync"]),
        "auto_apply_count": sum(1 for plan in plans if plan["can_auto_apply"]),
        "hosts": plans,
    }
