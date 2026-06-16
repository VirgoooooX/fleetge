import os
import sys
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException
from starlette.requests import HTTPConnection
from metrics_runner import start_metrics_collector, get_metrics
import docker_client
import compose_runner

# Retrieve Agent secret token from environment
AGENT_TOKEN = os.environ.get("AGENT_TOKEN", "").strip()
AGENT_REQUIRE_TOKEN = os.environ.get("AGENT_REQUIRE_TOKEN", "").strip().lower() == "true"

if not AGENT_TOKEN:
    print(
        "WARNING: AGENT_TOKEN is not set. Authentication is disabled. "
        "Set AGENT_TOKEN to secure this agent.",
        file=sys.stderr,
    )
    if AGENT_REQUIRE_TOKEN:
        print("ERROR: AGENT_REQUIRE_TOKEN=true but AGENT_TOKEN is empty.", file=sys.stderr)
        sys.exit(1)


async def verify_token(connection: HTTPConnection):
    """Enforce token validation for all endpoints, excluding health check."""
    if not AGENT_TOKEN:
        # Token is empty, authentication is disabled
        return

    path = connection.url.path.rstrip("/")
    if path in ("/api/agent/health", "/health"):
        return

    # 1. Check Authorization Header (Standard Bearer Token)
    auth_header = connection.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header[7:]
        if token == AGENT_TOKEN:
            return

    # 2. Check Query Parameters (Fallback for WebSockets/SSE)
    token_param = connection.query_params.get("token")
    if token_param == AGENT_TOKEN:
        return

    raise HTTPException(
        status_code=401,
        detail="Unauthorized. Missing or invalid Agent Token."
    )


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Startup: begin metrics collection.  Shutdown: close Docker proxy client."""
    print("[agent] Starting Fleetge Agent metrics collector thread...")
    start_metrics_collector()
    yield
    await docker_client.close_docker_client()


# Apply the token verification globally
app = FastAPI(
    title="Fleetge Agent",
    version="1.0.0",
    dependencies=[Depends(verify_token)],
    lifespan=lifespan,
)


@app.get("/api/agent/health")
async def health_check():
    """Liveness probe / health check endpoint."""
    return {"status": "ok", "agent": "fleetge-agent"}


@app.get("/api/agent/metrics")
async def read_metrics():
    """Retrieve cached system performance metrics immediately."""
    try:
        return get_metrics()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


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
