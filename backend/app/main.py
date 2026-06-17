"""FastAPI application entry point."""

import logging
from pathlib import Path

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.database import engine
from app.models import HostConfig, AuditLog
from app.host_loader import load_hosts_from_yaml
from app.routers import auth, hosts, stacks, containers, updates, audit, host_mgmt
from app.routers import settings as settings_router
from app.services.snapshot import snapshot_manager
from app.version import __version__

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan — startup and shutdown."""
    # ── Startup ────────────────────────────────────────────────────
    logger.info("Starting Fleetge backend")

    # Seed settings table with defaults on first run
    from app.services.settings_service import populate_defaults_if_empty
    populate_defaults_if_empty()

    # Load host configs from YAML
    load_hosts_from_yaml()

    # Refresh snapshot manager from DB
    await snapshot_manager.refresh_hosts()
    snapshot_manager.load_update_check_cache_from_db()

    # Start background polling
    await snapshot_manager.start()

    yield

    # ── Shutdown ───────────────────────────────────────────────────
    logger.info("Shutting down Fleetge backend")
    await snapshot_manager.stop()


# Create app
settings = get_settings()
app = FastAPI(
    title="Fleetge API",
    version=__version__,
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
app.include_router(settings_router.router)
app.include_router(host_mgmt.router)

# ── Static files: stack icons ─────────────────────────────────────────────

# Fix SVG MIME type on Windows (Python returns 'image/svg' instead of 'image/svg+xml')
import mimetypes
mimetypes.add_type("image/svg+xml", ".svg")

_HOST_CONFIG_PATH = Path(settings.HOST_CONFIG_PATH).expanduser()
if not _HOST_CONFIG_PATH.is_absolute():
    _HOST_CONFIG_PATH = Path.cwd() / _HOST_CONFIG_PATH
_STACK_ICONS_DIR = _HOST_CONFIG_PATH.parent / "stack_icons"
_STACK_ICONS_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/api/static/icons", StaticFiles(directory=str(_STACK_ICONS_DIR)), name="stack_icons")


# ── Health check ───────────────────────────────────────────────────────


@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "fleetge"}


# ── Serve static frontend ──────────────────────────────────────────────


_FRONTEND_DIST_DIR = Path(__file__).resolve().parent.parent / "frontend_dist"
_FRONTEND_ASSETS_DIR = _FRONTEND_DIST_DIR / "assets"
_FRONTEND_INDEX = _FRONTEND_DIST_DIR / "index.html"

if _FRONTEND_ASSETS_DIR.exists():
    app.mount("/assets", StaticFiles(directory=str(_FRONTEND_ASSETS_DIR)), name="assets")


@app.get("/")
async def root():
    if _FRONTEND_INDEX.exists():
        return FileResponse(_FRONTEND_INDEX)
    return {"message": "Fleetge API — see /api/docs for Swagger"}


@app.get("/{path:path}")
async def spa_fallback(path: str):
    if not _FRONTEND_DIST_DIR.exists() or not _FRONTEND_INDEX.exists():
        raise HTTPException(status_code=404, detail="Not found")

    requested = (_FRONTEND_DIST_DIR / path).resolve()
    if (
        requested.is_file()
        and _FRONTEND_DIST_DIR.resolve() in requested.parents
    ):
        return FileResponse(requested)

    return FileResponse(_FRONTEND_INDEX)
