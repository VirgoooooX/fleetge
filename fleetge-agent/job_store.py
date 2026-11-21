"""Persistent job status shared by the agent and detached updater."""

import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from compose_common import atomic_write_text, redact_sensitive_text

TERMINAL_JOB_STATES = frozenset({"success", "error", "uncertain", "skipped"})
JOB_RETENTION_SECONDS = 30 * 24 * 60 * 60


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def job_paths(jobs_dir: str, job_id: str) -> tuple[str, str]:
    os.makedirs(jobs_dir, exist_ok=True)
    base = os.path.join(jobs_dir, job_id)
    return f"{base}.json", f"{base}.log"


@contextmanager
def _store_lock(jobs_dir: str):
    # Keep the lock inode stable while both the agent and the updater use it.
    with open(os.path.join(jobs_dir, ".lock"), "a+b") as handle:
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(handle, fcntl.LOCK_EX)
        yield


def read_status(status_path: str | Path) -> dict:
    try:
        with open(status_path, encoding="utf-8") as handle:
            value = json.load(handle)
    except (FileNotFoundError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def write_status(jobs_dir: str, status_job_id: str, **updates) -> None:
    status_path, _ = job_paths(jobs_dir, status_job_id)
    with _store_lock(jobs_dir):
        current = read_status(status_path)
        state = current.get("status")
        requested = updates.get("status")
        if state in TERMINAL_JOB_STATES:
            # A late handoff acknowledgement may still supply the container name.
            updates = {key: value for key, value in updates.items() if key not in current and key == "updater_container"}
            if not updates:
                return
        elif state == "running" and requested == "handoff":
            updates.pop("status", None)
            updates.pop("phase", None)
        current.update(updates)
        current["updated_at"] = utc_now()
        atomic_write_text(status_path, json.dumps(current, ensure_ascii=False, indent=2))


def append_log(log_path: str, text: str) -> None:
    with open(log_path, "a", encoding="utf-8", errors="replace") as handle:
        handle.write(redact_sensitive_text(text))


def prune_finished_jobs(jobs_dir: str, *, now: float) -> None:
    cutoff = now - JOB_RETENTION_SECONDS
    with _store_lock(jobs_dir):
        for status_path in Path(jobs_dir).glob("*.json"):
            if not status_path.is_file() or status_path.stat().st_mtime >= cutoff:
                continue
            status = read_status(status_path)
            if status.get("status") not in TERMINAL_JOB_STATES:
                continue
            status_path.with_suffix(".log").unlink(missing_ok=True)
            status_path.unlink(missing_ok=True)
