"""docker-socket-proxy HTTP client.

Communicates with a remote docker-socket-proxy instance over HTTP/HTTPS.
Every request is read-only — the proxy must have POST=0.
"""

import asyncio
import logging
from typing import AsyncIterator, Optional

import httpx

from app.models import HostConfig
from app.services.crypto import decrypt_authorization_header

logger = logging.getLogger(__name__)


class DockerProxyClient:
    """Read-only HTTP client for one docker-socket-proxy instance."""

    def __init__(self, config: HostConfig):
        self._host_id = config.host_id
        self._base_url = config.docker_proxy_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=httpx.Timeout(15.0, connect=5.0),
        )

        # Decrypt stored auth header
        if config.docker_proxy_auth_encrypted:
            try:
                self._auth_header = decrypt_authorization_header(
                    config.docker_proxy_auth_encrypted
                )
            except ValueError:
                logger.error(
                    "Failed to decrypt docker-proxy auth for %s", config.host_id
                )
                self._auth_header = None
        else:
            self._auth_header = None

    def _headers(self) -> dict:
        return (
            {"Authorization": self._auth_header} if self._auth_header else {}
        )

    async def ping(self) -> bool:
        """Simple health check — GET /_ping."""
        try:
            r = await self._client.get("/_ping", headers=self._headers())
            return r.status_code == 200
        except Exception:
            return False

    async def version(self) -> dict:
        """GET /version returns Docker version info."""
        r = await self._client.get("/version", headers=self._headers())
        r.raise_for_status()
        return r.json()

    async def info(self) -> dict:
        """GET /info returns Docker engine/system info."""
        r = await self._client.get("/info", headers=self._headers())
        r.raise_for_status()
        return r.json()

    async def disk_usage(self) -> dict:
        """GET /system/df returns Docker disk usage."""
        r = await self._client.get("/system/df", headers=self._headers())
        r.raise_for_status()
        return r.json()

    async def list_containers(self, all: bool = True) -> list[dict]:
        """GET /containers/json returns container list."""
        params = {"all": "1" if all else "0"}
        r = await self._client.get(
            "/containers/json", params=params, headers=self._headers()
        )
        r.raise_for_status()
        return r.json()

    async def container_inspect(self, container_id: str) -> dict:
        """GET /containers/{id}/json returns container details.

        Includes RepoDigests in the Image field's metadata.
        """
        r = await self._client.get(
            f"/containers/{container_id}/json", headers=self._headers()
        )
        r.raise_for_status()
        return r.json()

    async def image_inspect(self, image_name: str) -> dict:
        """GET /images/{name}/json returns image details, including RepoDigests."""
        # URL-encode the image name (e.g. "library/nginx:latest")
        import urllib.parse
        encoded = urllib.parse.quote(image_name, safe="")
        r = await self._client.get(
            f"/images/{encoded}/json", headers=self._headers()
        )
        r.raise_for_status()
        return r.json()

    async def container_stats(self, container_id: str) -> Optional[dict]:
        """GET /containers/{id}/stats?stream=false returns one-shot stats.

        Returns None on any error (e.g., container not running).
        """
        try:
            r = await self._client.get(
                f"/containers/{container_id}/stats",
                params={"stream": "false"},
                headers=self._headers(),
                timeout=10.0,
            )
            r.raise_for_status()
            return r.json()
        except Exception as exc:
            logger.debug("Stats fetch failed for %s/%s: %s", self._host_id, container_id, exc)
            return None

    async def list_images(self) -> list[dict]:
        """GET /images/json returns image list."""
        r = await self._client.get("/images/json", headers=self._headers())
        r.raise_for_status()
        return r.json()

    async def container_logs(self, container_id: str, tail: int = 200) -> str:
        """GET /containers/{id}/logs returns container logs (stdout + stderr).

        Args:
            container_id: Container ID or name.
            tail: Number of recent lines (max 5000).
        """
        try:
            r = await self._client.get(
                f"/containers/{container_id}/logs",
                params={
                    "stdout": "1",
                    "stderr": "1",
                    "tail": str(min(tail, 5000)),
                },
                headers=self._headers(),
                timeout=15.0,
            )
            r.raise_for_status()
            return r.text
        except Exception as exc:
            logger.debug(
                "Container logs failed for %s/%s: %s",
                self._host_id, container_id, exc,
            )
            return f"[Error fetching container logs: {exc}]"

    async def stream_container_logs(
        self, container_id: str, tail: int = 200
    ) -> AsyncIterator[str]:
        """Stream /containers/{id}/logs?follow=1 as decoded text chunks."""
        async with self._client.stream(
            "GET",
            f"/containers/{container_id}/logs",
            params={
                "stdout": "1",
                "stderr": "1",
                "follow": "1",
                "tail": str(min(tail, 5000)),
            },
            headers=self._headers(),
            timeout=None,
        ) as response:
            response.raise_for_status()
            async for chunk in response.aiter_bytes():
                if chunk:
                    yield chunk.decode("utf-8", errors="replace")

    async def close(self) -> None:
        await self._client.aclose()
