"""ProxyService: normalized async calls to a project server's REST API."""

from __future__ import annotations

from typing import Any

import httpx

from brainpalace_dashboard.services.instances import InstanceService

_instances = InstanceService()


def instance_base_url(id_: str) -> str:
    """Resolve an instance id to its live base_url ('' if not running)."""
    for row in _instances.list():
        if row["id"] == id_:
            base: str = row.get("base_url", "")
            return base
    return ""


class UpstreamError(Exception):
    """A project server returned an error or was unreachable."""

    def __init__(self, detail: str, upstream_status: int) -> None:
        self.detail = detail
        self.upstream_status = upstream_status
        super().__init__(detail)


class ProxyService:
    """Hold a shared async httpx client and proxy calls to a project server."""

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=15.0)
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def request(
        self,
        id_: str,
        method: str,
        path: str,
        json: Any | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        base = instance_base_url(id_)
        if not base:
            raise UpstreamError("instance not running or unknown", 502)
        url = f"{base}{path}"
        try:
            resp = await self._get_client().request(
                method, url, json=json, params=params
            )
        except httpx.HTTPError as e:
            raise UpstreamError(f"upstream unreachable: {e}", 502) from e
        if resp.status_code >= 400:
            detail: Any = ""
            try:
                body = resp.json()
                detail = body.get("detail", body) if isinstance(body, dict) else body
            except Exception:
                detail = resp.text
            raise UpstreamError(str(detail), resp.status_code)
        if resp.headers.get("content-type", "").startswith("application/json"):
            return resp.json()
        return {"raw": resp.text}
