"""FastAPI application entry point."""

import logging
from pathlib import Path

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.database import engine
from app.models import HostConfig, AuditLog
from app.host_loader import load_hosts_from_yaml
from app.routers import auth, hosts, stacks, containers, updates, audit
from app.services.snapshot import snapshot_manager

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan — startup and shutdown."""
    # ── Startup ────────────────────────────────────────────────────
    logger.info("Starting Docker Dashboard backend")

    # Load host configs from YAML
    load_hosts_from_yaml()

    # Refresh snapshot manager from DB
    await snapshot_manager.refresh_hosts()

    # Start background polling
    await snapshot_manager.start()

    yield

    # ── Shutdown ───────────────────────────────────────────────────
    logger.info("Shutting down Docker Dashboard backend")
    await snapshot_manager.stop()


# Create app
settings = get_settings()
app = FastAPI(
    title="Docker Dashboard API",
    version="0.1.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    lifespan=lifespan,
)

# CORS — restricted by env var; empty list = same-origin only (production)
cors_origins_env = get_settings().CORS_ORIGINS
allowed_origins = (
    [o.strip() for o in cors_origins_env.split(",") if o.strip()]
    if cors_origins_env
    else []
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins or [],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(auth.router)
app.include_router(hosts.router)
app.include_router(stacks.router)
app.include_router(containers.router)
app.include_router(updates.router)
app.include_router(audit.router)

# ── Static files: stack icons ─────────────────────────────────────────────

# Fix SVG MIME type on Windows (Python returns 'image/svg' instead of 'image/svg+xml')
import mimetypes
mimetypes.add_type("image/svg+xml", ".svg")

_STACK_ICONS_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "stack_icons"
_STACK_ICONS_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/api/static/icons", StaticFiles(directory=str(_STACK_ICONS_DIR)), name="stack_icons")


# ── Health check ───────────────────────────────────────────────────────


@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "docker-dashboard"}


# ── Serve static frontend (optional, nginx frontend preferred) ─────────


@app.get("/")
async def root():
    return {"message": "Docker Dashboard API — see /api/docs for Swagger"}
