from __future__ import annotations

import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlencode, urlsplit, urlunsplit
from uuid import UUID, uuid4

import httpx


@dataclass(slots=True)
class OutputFile:
    node_id: str
    path: Path
    filename: str
    media_type: str


def controller_http_base(controller_url: str) -> str:
    parts = urlsplit(controller_url)
    scheme = {"ws": "http", "wss": "https"}.get(parts.scheme, parts.scheme or "http")
    path = parts.path.rstrip("/")
    suffix = "/api/v1/agents/ws"
    if path.endswith(suffix):
        path = path[: -len(suffix)]
    return urlunsplit((scheme, parts.netloc, path.rstrip("/"), "", "")).rstrip("/")


def _iter_file_descriptors(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        if value.get("filename"):
            yield value
        for child in value.values():
            yield from _iter_file_descriptors(child)
    elif isinstance(value, list):
        for child in value:
            yield from _iter_file_descriptors(child)


def discover_output_files(comfy_home: Path, outputs: dict[str, Any]) -> list[OutputFile]:
    """Resolve files referenced by Comfy history without allowing path traversal."""
    output_root = (comfy_home / "output").resolve()
    discovered: list[OutputFile] = []
    seen: set[Path] = set()

    for node_id, node_outputs in outputs.items():
        for descriptor in _iter_file_descriptors(node_outputs):
            if str(descriptor.get("type") or "output").casefold() != "output":
                continue
            filename = Path(str(descriptor.get("filename"))).name
            subfolder = str(descriptor.get("subfolder") or "")
            candidate = (output_root / subfolder / filename).resolve()
            try:
                candidate.relative_to(output_root)
            except ValueError:
                continue
            if candidate in seen or not candidate.is_file():
                continue
            seen.add(candidate)
            media_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
            discovered.append(
                OutputFile(
                    node_id=str(node_id),
                    path=candidate,
                    filename=filename,
                    media_type=media_type,
                )
            )
    return discovered


class AssetUploader:
    def __init__(
        self,
        controller_url: str,
        agent_token: str | None,
        host_id: str,
        comfy_home: Path,
    ) -> None:
        self.base_url = controller_http_base(controller_url)
        self.agent_token = agent_token
        self.host_id = host_id
        self.comfy_home = comfy_home

    async def upload_job_outputs(self, job_id: UUID, outputs: dict[str, Any]) -> list[dict[str, Any]]:
        files = discover_output_files(self.comfy_home, outputs)
        uploaded: list[dict[str, Any]] = []
        headers: dict[str, str] = {}
        if self.agent_token:
            headers["Authorization"] = f"Bearer {self.agent_token}"

        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, read=300.0)) as client:
            for item in files:
                asset_id = uuid4()
                query = urlencode(
                    {
                        "filename": item.filename,
                        "node_id": item.node_id,
                        "host_id": self.host_id,
                    }
                )
                url = f"{self.base_url}/api/v1/agents/jobs/{job_id}/assets/{asset_id}?{query}"
                file_size = item.path.stat().st_size
                request_headers = {
                    **headers,
                    "Content-Type": item.media_type,
                    "Content-Length": str(file_size),
                }
                with item.path.open("rb") as handle:
                    response = await client.put(url, content=handle, headers=request_headers)
                response.raise_for_status()
                uploaded.append(response.json())
        return uploaded
