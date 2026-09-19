from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

import httpx

from .settings import DesktopSettings

AGENT_WS_PATH = "/api/v1/agents/ws"


def controller_http_base(controller_url: str) -> str:
    parts = urlsplit(controller_url)
    scheme = {"ws": "http", "wss": "https"}.get(parts.scheme, parts.scheme or "http")
    path = parts.path.rstrip("/")
    if path.endswith(AGENT_WS_PATH):
        path = path[: -len(AGENT_WS_PATH)]
    return urlunsplit((scheme, parts.netloc, path.rstrip("/"), "", "")).rstrip("/")


class DesktopApi:
    def __init__(self, settings: DesktopSettings) -> None:
        self.settings = settings
        self.controller_base = controller_http_base(settings.controller_url)
        self.local_base = settings.local_api_url.rstrip("/")

    @staticmethod
    def _request(method: str, url: str, *, payload: dict | None = None, timeout: float = 3.0):
        with httpx.Client(timeout=timeout) as client:
            response = client.request(method, url, json=payload)
            response.raise_for_status()
            if not response.content:
                return None
            return response.json()

    def local_status(self) -> dict:
        return self._request("GET", f"{self.local_base}/api/v1/status")

    def local_worker_action(self, worker_id: str, operation: str):
        return self._request(
            "POST", f"{self.local_base}/api/v1/workers/{worker_id}/{operation}", timeout=15.0
        )

    def local_fleet_action(self, operation: str):
        return self._request("POST", f"{self.local_base}/api/v1/fleet/{operation}", timeout=30.0)

    def refresh_local_inventory(self):
        return self._request("POST", f"{self.local_base}/api/v1/inventory/refresh", timeout=30.0)

    def host_mode(self, host_id: str, operation: str):
        return self._request(
            "POST", f"{self.controller_base}/api/v1/hosts/{host_id}/{operation}"
        )

    def controller_worker_action(self, host_id: str, worker_id: str, operation: str):
        return self._request(
            "POST",
            f"{self.controller_base}/api/v1/hosts/{host_id}/commands/worker.{operation}",
            payload={"worker_id": worker_id},
        )

    def _controller_get(self, path: str):
        return self._request("GET", f"{self.controller_base}{path}")

    def _controller_optional(self, path: str):
        try:
            return self._controller_get(path)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return None
            raise

    def snapshot(self) -> dict:
        snapshot = {
            "local": None,
            "hosts": [],
            "models": [],
            "nodes": [],
            "jobs": [],
            "desired_release": None,
            "release_plan": None,
            "local_error": None,
            "controller_error": None,
            "controller_base": self.controller_base,
            "host_id": self.settings.host_id,
        }

        try:
            snapshot["local"] = self.local_status()
        except (httpx.HTTPError, ValueError) as exc:
            snapshot["local_error"] = str(exc)

        try:
            snapshot["hosts"] = self._controller_get("/api/v1/hosts")
            snapshot["models"] = self._controller_get("/api/v1/models")
            snapshot["nodes"] = self._controller_get("/api/v1/nodes")
            snapshot["jobs"] = self._controller_get("/api/v1/jobs")
            snapshot["desired_release"] = self._controller_optional("/api/v1/releases/desired")
            snapshot["release_plan"] = self._controller_optional("/api/v1/releases/plan")
        except (httpx.HTTPError, ValueError) as exc:
            snapshot["controller_error"] = str(exc)

        if snapshot["local"]:
            registration = snapshot["local"].get("registration") or {}
            snapshot["host_id"] = registration.get("host_id") or snapshot["host_id"]

        snapshot["local_host"] = next(
            (host for host in snapshot["hosts"] if host.get("host_id") == snapshot["host_id"]),
            None,
        )
        return snapshot
