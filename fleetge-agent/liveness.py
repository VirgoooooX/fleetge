"""Lightweight host boot identity and graceful-shutdown lifecycle tracking."""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import time
from datetime import datetime, timezone
from typing import Any

import psutil

logger = logging.getLogger("fleetge-agent.liveness")

BOOT_ID_PATH = "/proc/sys/kernel/random/boot_id"


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _default_state_dir() -> str:
    configured = os.environ.get("AGENT_STATE_DIR", "").strip()
    if configured:
        return configured
    stacks_dir = os.environ.get("STACKS_BASE_DIR", "/opt/stacks").strip() or "/opt/stacks"
    return os.path.join(os.path.realpath(stacks_dir), ".fleetge")


def read_boot_id(path: str = BOOT_ID_PATH) -> str | None:
    """Return the Linux kernel boot UUID shared by host and containers, or None."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            value = handle.read().strip()
        return value or None
    except OSError:
        return None


def _atomic_write_json(path: str, data: dict[str, Any]) -> None:
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".lifecycle.", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


class LifecycleTracker:
    """Persist boot_id and clean_shutdown across Agent and host restarts."""

    def __init__(self, *, state_dir: str | None = None, boot_id_path: str = BOOT_ID_PATH) -> None:
        self._state_dir = state_dir
        self._boot_id_path = boot_id_path
        self._lock = threading.Lock()
        self._boot_id: str | None = None
        self._boot_time: int | None = None
        self._agent_started_at: str = _utc_iso()
        self._previous_boot_id: str | None = None
        self._last_boot_shutdown_clean: bool | None = None
        self._initialized = False

    def _lifecycle_path(self) -> str:
        base = self._state_dir or _default_state_dir()
        return os.path.join(base, "lifecycle.json")

    def _read_existing(self, path: str) -> dict[str, Any] | None:
        try:
            with open(path, "r", encoding="utf-8") as handle:
                raw = json.load(handle)
            return raw if isinstance(raw, dict) else None
        except (OSError, ValueError):
            return None

    def record_startup(self) -> dict[str, Any]:
        """Inspect prior lifecycle file, detect host reboot, and mark clean_shutdown=False."""
        with self._lock:
            now_iso = _utc_iso()
            current_boot_id = read_boot_id(self._boot_id_path)
            try:
                boot_time = int(psutil.boot_time())
            except Exception:
                boot_time = None

            path = self._lifecycle_path()
            prev = self._read_existing(path)
            prev_boot_id = prev.get("boot_id") if isinstance(prev, dict) else None

            previous_boot_id: str | None = None
            last_boot_shutdown_clean: bool | None = None

            if isinstance(prev, dict) and prev_boot_id and current_boot_id:
                if prev_boot_id != current_boot_id:
                    previous_boot_id = str(prev_boot_id)
                    last_boot_shutdown_clean = bool(prev.get("clean_shutdown", False))
                else:
                    # Same host boot (Agent container restarted/upgraded): preserve prior boot verdict.
                    previous_boot_id = prev.get("previous_boot_id")
                    prev_clean = prev.get("last_boot_shutdown_clean")
                    last_boot_shutdown_clean = prev_clean if isinstance(prev_clean, bool) else None

            self._boot_id = current_boot_id
            self._boot_time = boot_time
            self._agent_started_at = now_iso
            self._previous_boot_id = previous_boot_id
            self._last_boot_shutdown_clean = last_boot_shutdown_clean
            self._initialized = True

            record = {
                "boot_id": current_boot_id,
                "boot_time": boot_time,
                "clean_shutdown": False,
                "previous_boot_id": previous_boot_id,
                "last_boot_shutdown_clean": last_boot_shutdown_clean,
                "agent_started_at": now_iso,
                "updated_at": now_iso,
            }
            try:
                _atomic_write_json(path, record)
            except OSError as exc:
                logger.warning("Could not persist lifecycle startup state to %s: %s", path, exc)
            return record

    def record_graceful_shutdown(self) -> None:
        """Mark the current boot's agent shutdown as clean before process exit."""
        with self._lock:
            if not self._initialized:
                return
            now_iso = _utc_iso()
            path = self._lifecycle_path()
            record = {
                "boot_id": self._boot_id,
                "boot_time": self._boot_time,
                "clean_shutdown": True,
                "previous_boot_id": self._previous_boot_id,
                "last_boot_shutdown_clean": self._last_boot_shutdown_clean,
                "agent_started_at": self._agent_started_at,
                "stopped_at": now_iso,
                "updated_at": now_iso,
            }
            try:
                _atomic_write_json(path, record)
            except OSError as exc:
                logger.warning("Could not persist lifecycle shutdown state to %s: %s", path, exc)

    def payload(self) -> dict[str, Any]:
        """Return lightweight liveness info without waking metrics collection."""
        with self._lock:
            if not self._initialized:
                self._boot_id = read_boot_id(self._boot_id_path)
                try:
                    self._boot_time = int(psutil.boot_time())
                except Exception:
                    self._boot_time = None
            boot_time = self._boot_time
            uptime_seconds = max(0, int(time.time() - boot_time)) if boot_time is not None else None
            return {
                "status": "ok",
                "boot_id": self._boot_id,
                "boot_time": boot_time,
                "uptime_seconds": uptime_seconds,
                "agent_started_at": self._agent_started_at,
                "previous_boot_id": self._previous_boot_id,
                "last_boot_shutdown_clean": self._last_boot_shutdown_clean,
            }


_tracker = LifecycleTracker()


def record_startup() -> dict[str, Any]:
    return _tracker.record_startup()


def record_graceful_shutdown() -> None:
    _tracker.record_graceful_shutdown()


def get_liveness_payload() -> dict[str, Any]:
    return _tracker.payload()
