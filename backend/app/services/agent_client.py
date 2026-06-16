import asyncio
import logging
import urllib.parse
from typing import Any, AsyncIterator, Optional
import httpx
import websockets

from app.models import HostConfig
from app.schemas import HostMetrics
from app.services.crypto import decrypt_string

logger = logging.getLogger(__name__)


class AgentClient:
    """Unified HTTP/WebSocket client to communicate with the remote Fleetge Agent.
    
    Acts as a drop-in replacement that implements all methods of:
      - MetricsClient
      - DockerProxyClient
      - DockgeConnection (except Socket.IO features)
    """

    def __init__(self, config: HostConfig):
        self._host_id = config.host_id
        self._base_url = config.agent_url.rstrip("/")
        
        # Resolve WS URL from HTTP URL
        if self._base_url.startswith("https://"):
            self._ws_base_url = "wss://" + self._base_url[8:]
        elif self._base_url.startswith("http://"):
            self._ws_base_url = "ws://" + self._base_url[7:]
        else:
            self._ws_base_url = "ws://" + self._base_url

        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=httpx.Timeout(15.0, connect=5.0),
        )

        # Decrypt token
        self._token = ""
        if config.agent_token_encrypted:
            try:
                self._token = decrypt_string(config.agent_token_encrypted)
            except Exception as exc:
                logger.error("Failed to decrypt agent token for host %s: %s", self._host_id, exc)

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._token}"} if self._token else {}

    async def close(self) -> None:
        await self._client.aclose()

    # ── 1. Metrics API (replaces MetricsClient) ───────────────────────────

    async def fetch_metrics(self) -> HostMetrics:
        """GET /api/agent/metrics returns system metrics."""
        r = await self._client.get("/api/agent/metrics", headers=self._headers())
        r.raise_for_status()
        return HostMetrics(**r.json())

    # ── 2. Docker Proxy API (replaces DockerProxyClient) ──────────────────

    async def ping(self) -> bool:
        """GET /api/agent/docker/_ping check Docker daemon health."""
        try:
            r = await self._client.get("/api/agent/docker/_ping", headers=self._headers())
            return r.status_code == 200
        except Exception:
            return False

    async def version(self) -> dict:
        """GET /api/agent/docker/version."""
        r = await self._client.get("/api/agent/docker/version", headers=self._headers())
        r.raise_for_status()
        return r.json()

    async def info(self) -> dict:
        """GET /api/agent/docker/info."""
        r = await self._client.get("/api/agent/docker/info", headers=self._headers())
        r.raise_for_status()
        return r.json()

    async def disk_usage(self) -> dict:
        """GET /api/agent/docker/system/df."""
        r = await self._client.get("/api/agent/docker/system/df", headers=self._headers())
        r.raise_for_status()
        return r.json()

    async def list_containers(self, all: bool = True) -> list[dict]:
        """GET /api/agent/docker/containers/json."""
        params = {"all": "1" if all else "0"}
        r = await self._client.get(
            "/api/agent/docker/containers/json", params=params, headers=self._headers()
        )
        r.raise_for_status()
        return r.json()

    async def container_inspect(self, container_id: str) -> dict:
        """GET /api/agent/docker/containers/{id}/json."""
        r = await self._client.get(
            f"/api/agent/docker/containers/{container_id}/json", headers=self._headers()
        )
        r.raise_for_status()
        return r.json()

    async def image_inspect(self, image_name: str) -> dict:
        """GET /api/agent/docker/images/{encoded}/json."""
        encoded = urllib.parse.quote(image_name, safe="")
        r = await self._client.get(
            f"/api/agent/docker/images/{encoded}/json", headers=self._headers()
        )
        r.raise_for_status()
        return r.json()

    async def container_stats(self, container_id: str) -> Optional[dict]:
        """GET /api/agent/docker/containers/{id}/stats (one-shot)."""
        try:
            r = await self._client.get(
                f"/api/agent/docker/containers/{container_id}/stats",
                params={"stream": "false"},
                headers=self._headers(),
                timeout=10.0,
            )
            r.raise_for_status()
            return r.json()
        except Exception as exc:
            logger.debug("Stats fetch failed via agent for %s/%s: %s", self._host_id, container_id, exc)
            return None

    async def list_images(self) -> list[dict]:
        """GET /api/agent/docker/images/json."""
        r = await self._client.get("/api/agent/docker/images/json", headers=self._headers())
        r.raise_for_status()
        return r.json()

    async def container_logs(self, container_id: str, tail: int = 200) -> str:
        """GET /api/agent/docker/containers/{id}/logs (non-streaming, pre-demuxed/cleaned)."""
        try:
            r = await self._client.get(
                f"/api/agent/docker/containers/{container_id}/logs",
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
            logger.debug("Container logs via agent failed for %s/%s: %s", self._host_id, container_id, exc)
            return f"[Error fetching container logs: {exc}]"

    async def stream_container_logs(
        self, container_id: str, tail: int = 200
    ) -> AsyncIterator[str]:
        """Stream /api/agent/docker/containers/{id}/logs?follow=1 (already clean text)."""
        headers = self._headers()
        async with self._client.stream(
            "GET",
            f"/api/agent/docker/containers/{container_id}/logs",
            params={
                "stdout": "1",
                "stderr": "1",
                "follow": "1",
                "tail": str(min(tail, 5000)),
            },
            headers=headers,
            timeout=None,
        ) as response:
            response.raise_for_status()
            async for chunk in response.aiter_text():
                yield chunk

    # ── 3. Compose Stack API (replaces DockgeClient) ─────────────────────

    async def list_stacks(self) -> list[dict]:
        """GET /api/agent/stacks (returns list of stack names, mock status format)."""
        r = await self._client.get("/api/agent/stacks", headers=self._headers())
        r.raise_for_status()
        
        # Agent lists folder names. We format them as mock dicts: {"name": name}
        # snapshot_manager will merge this with compose labels to resolve service lists.
        return [{"name": name} for name in r.json()]

    async def get_stack(self, name: str) -> Optional[dict]:
        """GET /api/agent/stacks/{name}."""
        try:
            r = await self._client.get(f"/api/agent/stacks/{name}", headers=self._headers())
            r.raise_for_status()
            data = r.json()
            # Wrap to match Dockge's return shape: {"stack": {"name": ..., "composeYAML": ..., "composeENV": ...}}
            return {
                "stack": {
                    "name": data.get("name"),
                    "composeYAML": data.get("compose_yaml"),
                    "composeENV": data.get("compose_env"),
                    "composeFileName": data.get("compose_file_name", "compose.yaml"),
                    "isManagedByDockge": True
                }
            }
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return None
            raise
        except Exception as exc:
            logger.error("Failed to get stack details via agent for %s/%s: %s", self._host_id, name, exc)
            raise

    async def delete_stack(self, name: str) -> dict:
        """DELETE /api/agent/stacks/{name}."""
        r = await self._client.delete(
            f"/api/agent/stacks/{name}", headers=self._headers()
        )
        r.raise_for_status()
        return r.json()

    async def save_stack(
        self,
        name: str,
        compose_yaml: str,
        compose_env: str,
        deploy: bool = False,
        is_add: bool = False,
        log_queue: Optional[asyncio.Queue] = None,
    ) -> dict:
        """Save compose stack configuration. If deploy=True, stream control output."""
        # Save first
        payload = {
            "compose_yaml": compose_yaml,
            "compose_env": compose_env
        }
        r = await self._client.put(
            f"/api/agent/stacks/{name}", json=payload, headers=self._headers()
        )
        r.raise_for_status()

        if deploy:
            # Run deploy stream command
            return await self.stack_action(name, "up", log_queue=log_queue)
            
        return r.json()

    async def service_status(self, name: str) -> list[dict]:
        """Agent does not track live status inside stacks list; return empty.
        
        snapshot_manager will merge container labels to find statuses.
        """
        return []

    async def stack_action(
        self, name: str, action: str, log_queue: Optional[asyncio.Queue] = None
    ) -> dict:
        """Execute docker compose command on the agent and stream control output via WebSocket."""
        # Convert start/stop/restart/update actions to Agent supported compose commands
        agent_action = action
        if action == "startStack" or action == "start":
            agent_action = "up"
        elif action == "stopStack" or action == "stop":
            agent_action = "down"
        elif action == "restartStack":
            agent_action = "restart"
        elif action == "updateStack" or action == "update":
            agent_action = "update"

        # Establish WebSocket URI — token passed via Authorization header
        ws_uri = f"{self._ws_base_url}/api/agent/stacks/{name}/execute"
        extra_headers = self._headers()

        # Run process via WebSocket connection
        try:
            async with websockets.connect(ws_uri, extra_headers=extra_headers) as ws:
                # Send action payload
                await ws.send(f'{{"action": "{agent_action}"}}')
                
                exit_code = 0
                error_msg = ""
                
                # Consume lines
                while True:
                    try:
                        msg_str = await ws.recv()
                        import json
                        msg = json.loads(msg_str)
                        msg_type = msg.get("type")
                        
                        if msg_type == "stdout":
                            chunk = msg.get("chunk", "")
                            if log_queue is not None:
                                await log_queue.put(chunk)
                        elif msg_type == "exit":
                            exit_code = msg.get("code", 0)
                            break
                        elif msg_type == "error":
                            error_msg = msg.get("message", "Unknown error")
                            if log_queue is not None:
                                await log_queue.put(f"ERROR: {error_msg}")
                            exit_code = -1
                            break
                    except websockets.ConnectionClosed:
                        break

                if log_queue is not None:
                    # Put EOF sentinel
                    await log_queue.put(None)

                if exit_code != 0:
                    return {"success": False, "ok": False, "message": error_msg or f"Command failed with exit code {exit_code}"}
                return {"success": True, "ok": True, "message": "Operation completed successfully"}

        except Exception as exc:
            if log_queue is not None:
                await log_queue.put(f"WebSocket execution connection failed: {exc}")
                await log_queue.put(None)
            return {"success": False, "ok": False, "message": str(exc)}

    async def prune_system(
        self, log_queue: Optional[asyncio.Queue] = None
    ) -> dict:
        """Run ``docker system prune -a -f`` on the agent host via WebSocket.

        Streams raw terminal chunks to ``log_queue`` and returns a
        ``{"success": bool, "message": str}`` dict.
        """
        ws_uri = f"{self._ws_base_url}/api/agent/host/prune"
        extra_headers = self._headers()

        try:
            async with websockets.connect(ws_uri, extra_headers=extra_headers) as ws:
                exit_code = 0
                error_msg = ""

                while True:
                    try:
                        msg_str = await ws.recv()
                        import json
                        msg = json.loads(msg_str)
                        msg_type = msg.get("type")

                        if msg_type == "stdout":
                            chunk = msg.get("chunk", "")
                            if log_queue is not None:
                                await log_queue.put(chunk)
                        elif msg_type == "exit":
                            exit_code = msg.get("code", 0)
                            break
                        elif msg_type == "error":
                            error_msg = msg.get("message", "Unknown error")
                            if log_queue is not None:
                                await log_queue.put(f"ERROR: {error_msg}")
                            exit_code = -1
                            break
                    except websockets.ConnectionClosed:
                        break

                if log_queue is not None:
                    await log_queue.put(None)

                if exit_code != 0:
                    return {"success": False, "message": error_msg or f"Prune failed with exit code {exit_code}"}
                return {"success": True, "message": "Docker system prune completed successfully"}

        except Exception as exc:
            if log_queue is not None:
                await log_queue.put(f"Prune connection failed: {exc}")
                await log_queue.put(None)
            return {"success": False, "message": str(exc)}
