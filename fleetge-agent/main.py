import os
import sys
import logging
import asyncio
import time
import re

# Configure Logging
LOG_LEVEL_STR = os.environ.get("AGENT_LOG_LEVEL", os.environ.get("LOG_LEVEL", "INFO")).upper()
LEVELS = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "WARN": logging.WARNING,
    "WARING": logging.WARNING,
    "ERROR": logging.ERROR,
}
log_level = LEVELS.get(LOG_LEVEL_STR, logging.INFO)


class _SuppressInvalidHttpRequestWarning(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return "Invalid HTTP request received" not in record.getMessage()


logger = logging.getLogger("fleetge-agent")
logger.setLevel(log_level)
if not logger.handlers:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    logger.addHandler(handler)

# Configure Uvicorn loggers to respect AGENT_LOG_LEVEL
for uvicorn_logger in ("uvicorn", "uvicorn.error", "uvicorn.access"):
    uv_logger = logging.getLogger(uvicorn_logger)
    uv_logger.setLevel(log_level)
    uv_logger.addFilter(_SuppressInvalidHttpRequestWarning())

from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException, Query
from starlette.types import ASGIApp, Receive, Scope, Send
from starlette.requests import HTTPConnection
from metrics_runner import (
    get_metrics,
    get_traffic_current,
    get_traffic_history,
    start_metrics_collector,
    stop_metrics_collector,
)
from network_identity import probe_network_identity
import docker_client
import compose_runner

# Retrieve Agent security settings from environment
AGENT_TOKEN = os.environ.get("AGENT_TOKEN", "").strip()
AGENT_REQUIRE_TOKEN = os.environ.get("AGENT_REQUIRE_TOKEN", "true").strip().lower() != "false"
AGENT_PUBLIC_HEALTH = os.environ.get("AGENT_PUBLIC_HEALTH", "false").strip().lower() == "true"
AGENT_SECRET_PATH = os.environ.get("AGENT_SECRET_PATH", "").strip()
AGENT_TOKEN_MIN_LENGTH = int(os.environ.get("AGENT_TOKEN_MIN_LENGTH", "32") or "32")
_AUTH_FAILURES: dict[str, tuple[int, float]] = {}
_AUTH_FAILURE_WINDOW_SECONDS = 300.0
_AUTH_FAILURE_DELAY_AFTER = 3
_AUTH_FAILURE_MAX_DELAY_SECONDS = 10.0

if AGENT_SECRET_PATH:
    AGENT_SECRET_PATH = "/" + AGENT_SECRET_PATH.strip("/")
    if not re.match(r"^/[A-Za-z0-9._~-]{8,128}$", AGENT_SECRET_PATH):
        logger.error("AGENT_SECRET_PATH must be 8-128 URL-safe characters when set.")
        sys.exit(1)

if not AGENT_TOKEN:
    if AGENT_REQUIRE_TOKEN:
        logger.error("AGENT_TOKEN is required. Set AGENT_TOKEN to a long random value or set AGENT_REQUIRE_TOKEN=false.")
        sys.exit(1)
    logger.warning("AGENT_TOKEN is not set. Authentication is disabled. Set AGENT_TOKEN to secure this agent.")
elif len(AGENT_TOKEN) < AGENT_TOKEN_MIN_LENGTH:
    logger.error(
        "AGENT_TOKEN is too short (%d chars). Use at least %d characters.",
        len(AGENT_TOKEN),
        AGENT_TOKEN_MIN_LENGTH,
    )
    sys.exit(1)


class SecretPathMiddleware:
    """Optionally hide the agent behind a configured URL prefix."""

    def __init__(self, app: ASGIApp, secret_path: str = "") -> None:
        self.app = app
        self.secret_path = secret_path

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not self.secret_path or scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if not path.startswith(self.secret_path + "/"):
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": 1008})
                return
            body = b'{"detail":"Not found"}'
            await send({
                "type": "http.response.start",
                "status": 404,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("ascii")),
                ],
            })
            await send({"type": "http.response.body", "body": body})
            return

        rewritten = dict(scope)
        rewritten["path"] = path[len(self.secret_path):] or "/"
        rewritten["root_path"] = (scope.get("root_path") or "") + self.secret_path
        await self.app(rewritten, receive, send)


def _client_key(connection: HTTPConnection) -> str:
    if connection.client and connection.client.host:
        return connection.client.host
    return "unknown"


async def _record_auth_failure(connection: HTTPConnection) -> None:
    key = _client_key(connection)
    now = time.monotonic()
    count, last_seen = _AUTH_FAILURES.get(key, (0, 0.0))
    if now - last_seen > _AUTH_FAILURE_WINDOW_SECONDS:
        count = 0
    count += 1
    _AUTH_FAILURES[key] = (count, now)
    if count > _AUTH_FAILURE_DELAY_AFTER:
        delay = min((count - _AUTH_FAILURE_DELAY_AFTER) * 0.75, _AUTH_FAILURE_MAX_DELAY_SECONDS)
        await asyncio.sleep(delay)


def _record_auth_success(connection: HTTPConnection) -> None:
    _AUTH_FAILURES.pop(_client_key(connection), None)


async def verify_token(connection: HTTPConnection):
    """Enforce token validation for all endpoints, excluding health check."""
    if not AGENT_TOKEN:
        # Token is empty, authentication is disabled
        return

    path = connection.url.path.rstrip("/")
    if AGENT_PUBLIC_HEALTH and path in ("/api/agent/health", "/health"):
        return

    # 1. Check Authorization Header (Standard Bearer Token)
    auth_header = connection.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header[7:]
        if token == AGENT_TOKEN:
            _record_auth_success(connection)
            return

    # 2. Check Query Parameters (Fallback for WebSockets/SSE)
    token_param = connection.query_params.get("token")
    if token_param == AGENT_TOKEN:
        _record_auth_success(connection)
        return

    await _record_auth_failure(connection)
    raise HTTPException(
        status_code=401,
        detail="Unauthorized. Missing or invalid Agent Token."
    )


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Startup: begin metrics collection.  Shutdown: close Docker proxy client."""
    logger.info("Starting Fleetge Agent metrics collector thread...")
    start_metrics_collector()
    yield
    stop_metrics_collector()
    await docker_client.close_docker_client()


# Apply the token verification globally
app = FastAPI(
    title="Fleetge Agent",
    version="1.0.0",
    dependencies=[Depends(verify_token)],
    lifespan=lifespan,
)
app.add_middleware(SecretPathMiddleware, secret_path=AGENT_SECRET_PATH)


@app.get("/api/agent/health")
async def health_check():
    """Liveness probe / health check endpoint."""
    return {"status": "ok"}


@app.get("/api/agent/metrics")
async def read_metrics():
    """Wake adaptive collection and return a fresh or explicitly warming snapshot."""
    try:
        return await asyncio.to_thread(get_metrics, 1.0)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@app.get("/api/agent/traffic/current")
async def read_current_traffic(activate: bool = Query(False)):
    """Return selected WAN counters without waking telemetry unless requested."""
    return await asyncio.to_thread(get_traffic_current, activate)


@app.get("/api/agent/traffic/history")
async def read_traffic_history(cursor: int = Query(0, ge=0), limit: int = Query(1000, ge=1, le=2000)):
    """Return completed five-minute traffic buckets after an opaque integer cursor."""
    return await asyncio.to_thread(get_traffic_history, cursor, limit)


@app.get("/api/agent/network-identity")
async def read_network_identity(refresh: bool = Query(False)):
    """Probe public IPv4/IPv6 with fixed providers and environment proxies disabled."""
    return await probe_network_identity(force=refresh)


# Mount the sub-routers for Docker proxy and Compose Stack runner
app.include_router(docker_client.router, prefix="/api/agent")
app.include_router(compose_runner.router, prefix="/api/agent")


@app.get("/api/agent/diagnostic")
async def run_diagnostic():
    """Diagnostic endpoint to inspect Agent context and Docker command path resolution."""
    import subprocess
    import sys
    
    diagnostic_info = {
        "sys.platform": sys.platform,
        "os.environ.DOCKER_HOST": os.environ.get("DOCKER_HOST"),
        "os.environ.PATH": os.environ.get("PATH"),
        "docker_compose_version_run": {},
    }
    
    try:
        res = subprocess.run(
            ["docker", "compose", "version"],
            capture_output=True,
            text=True,
            timeout=5.0
        )
        diagnostic_info["docker_compose_version_run"] = {
            "success": True,
            "returncode": res.returncode,
            "stdout": res.stdout,
            "stderr": res.stderr,
        }
    except Exception as exc:
        diagnostic_info["docker_compose_version_run"] = {
            "success": False,
            "error_type": type(exc).__name__,
            "error_message": str(exc),
        }
        
    return diagnostic_info
