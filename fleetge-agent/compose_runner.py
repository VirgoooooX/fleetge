import os
import re
import shutil
import logging
import threading
import time
import asyncio
from weakref import WeakValueDictionary
import json
import uuid
import socket
import subprocess
from contextlib import ExitStack, suppress
from typing import Optional
from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from compose_identity import capture_pulled_images
from compose_common import (
    COMPOSE_FILE_NAMES as _COMPOSE_FILE_NAMES,
    SERVICE_NAME_RE,
    atomic_write_text,
    commit_stack_files,
    compose_args as build_compose_args,
    redact_sensitive_text as _redact_sensitive_text,
    staged_text,
)
import ingress_probe
from ingress_probe import INGRESS_PORTS, _container_socket_inodes, _listening_inodes, _running_host_containers
import job_store
from job_store import TERMINAL_JOB_STATES as _TERMINAL_JOB_STATES, utc_now as _utc_now_iso
import pty_executor

logger = logging.getLogger("fleetge-agent.compose")

STACKS_BASE_DIR = os.environ.get("STACKS_BASE_DIR", "/opt/stacks")
FLEETGE_STACK_NAME = os.environ.get("FLEETGE_STACK_NAME", "").strip()
FLEETGE_AGENT_SERVICE = os.environ.get("FLEETGE_AGENT_SERVICE", "").strip()
FLEETGE_UPDATER_IMAGE = os.environ.get("FLEETGE_UPDATER_IMAGE", "").strip()
AGENT_INSTANCE_ID = os.environ.get("AGENT_INSTANCE_ID", "").strip()
AGENT_VERSION = os.environ.get("AGENT_VERSION", "").strip()


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


AGENT_ENABLE_WRITE = _env_bool("AGENT_ENABLE_WRITE", True)
AGENT_ENABLE_DELETE = _env_bool("AGENT_ENABLE_DELETE", True)
AGENT_ENABLE_GLOBAL_ENV = _env_bool("AGENT_ENABLE_GLOBAL_ENV", True)
AGENT_ENABLE_PRUNE = _env_bool("AGENT_ENABLE_PRUNE", False)
AGENT_ENABLE_SELF_UPDATE = _env_bool("AGENT_ENABLE_SELF_UPDATE", True)

router = APIRouter()

# Dockge-compatible stack names. Keep this aligned with frontend/backend validation.
STACK_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
SERVICE_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]*$")

def _client_host(request: Request | WebSocket | None) -> str:
    if request and request.client and request.client.host:
        return request.client.host
    return "-"


def _audit_log_path() -> str:
    path = os.path.join(os.path.realpath(STACKS_BASE_DIR), ".fleetge")
    os.makedirs(path, exist_ok=True)
    return os.path.join(path, "audit.log")


async def _write_audit(action: str, result: str, *, stack: str = "", client: str = "-", detail: str = "") -> None:
    safe_detail = _redact_sensitive_text((detail or "").replace("\r", " ").replace("\n", " "))[:500]
    line = "\t".join([
        _utc_now_iso(),
        client or "-",
        action,
        stack or "-",
        result,
        safe_detail,
    ]) + "\n"

    def append() -> None:
        with open(_audit_log_path(), "a", encoding="utf-8", errors="replace") as f:
            f.write(line)

    await asyncio.to_thread(append)


def _require_enabled(enabled: bool, feature: str) -> None:
    if not enabled:
        raise HTTPException(status_code=403, detail=f"{feature} is disabled by agent policy.")

# Concurrent locks per stack name
_locks: WeakValueDictionary[str, asyncio.Lock] = WeakValueDictionary()
_active_job_stacks: dict[str, str] = {}
_job_watchers: set[asyncio.Task] = set()


async def get_stack_lock(stack_name: str) -> asyncio.Lock:
    """Keep each lock alive while a task can still acquire or release it."""
    lock = _locks.get(stack_name)
    if lock is None:
        lock = asyncio.Lock()
        _locks[stack_name] = lock
    return lock


def _track_job(task: asyncio.Task, stack_name: str, job_id: str) -> None:
    _job_watchers.add(task)

    def finish(finished: asyncio.Task) -> None:
        _job_watchers.discard(finished)
        if _active_job_stacks.get(stack_name) == job_id:
            _active_job_stacks.pop(stack_name, None)
        if not finished.cancelled() and (error := finished.exception()) is not None:
            logger.error("Job %s watcher failed", job_id, exc_info=error)

    task.add_done_callback(finish)


async def stop_job_watchers() -> None:
    tasks = tuple(_job_watchers)
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


class StackSaveRequest(BaseModel):
    compose_yaml: str
    compose_env: Optional[str] = ""
    compose_file_name: Optional[str] = "compose.yaml"
    is_add: bool = False


class GlobalEnvRequest(BaseModel):
    content: str = ""


class JobLogResponse(BaseModel):
    content: str = ""
    size: int = 0


def _validate_stack_name(name: str) -> None:
    """Ensure stack name is safe and does not contain path traversal characters."""
    if not STACK_NAME_RE.match(name):
        raise HTTPException(
            status_code=400,
            detail="Invalid stack name. Only lowercase letters, numbers, hyphens, and underscores are allowed."
        )


def _validate_service_name(name: Optional[str]) -> str:
    service = name or ""
    if ".." in service or not SERVICE_NAME_RE.match(service):
        raise HTTPException(
            status_code=400,
            detail="Invalid service name. Only letters, numbers, dots, hyphens, and underscores are allowed.",
        )
    return service


def _validate_services(services: object) -> list[str]:
    if not isinstance(services, list) or not services:
        raise HTTPException(status_code=400, detail="services must be a non-empty list")
    return [_validate_service_name(str(service)) for service in services]


def ingress_services(ports: tuple[int, ...] = INGRESS_PORTS) -> list[dict]:
    return ingress_probe.ingress_services(
        ports,
        listening_inodes=_listening_inodes,
        running_host_containers=_running_host_containers,
        container_socket_inodes=_container_socket_inodes,
    )


def _jobs_dir() -> str:
    path = os.path.join(os.path.realpath(STACKS_BASE_DIR), ".fleetge", "jobs")
    os.makedirs(path, exist_ok=True)
    return path


def _validate_job_id(job_id: str) -> str:
    if not re.match(r"^[a-zA-Z0-9_.-]+$", job_id or ""):
        raise HTTPException(status_code=400, detail="Invalid job id")
    return job_id


def _job_paths(job_id: str) -> tuple[str, str]:
    safe_job_id = _validate_job_id(job_id)
    base = os.path.join(_jobs_dir(), safe_job_id)
    return f"{base}.json", f"{base}.log"


async def _write_job_status(status_job_id: str, **updates) -> None:
    await asyncio.to_thread(job_store.write_status, _jobs_dir(), _validate_job_id(status_job_id), **updates)


async def _append_job_log(job_id: str, text: str) -> None:
    _, log_path = _job_paths(job_id)
    await asyncio.to_thread(job_store.append_log, log_path, text)


_pruned_jobs_dir = ""
_pruned_jobs_at = float("-inf")


async def _prune_finished_jobs(jobs_dir: str) -> None:
    global _pruned_jobs_dir, _pruned_jobs_at
    now = time.monotonic()
    if jobs_dir == _pruned_jobs_dir and now - _pruned_jobs_at < 24 * 60 * 60:
        return
    _pruned_jobs_dir, _pruned_jobs_at = jobs_dir, now
    try:
        await asyncio.to_thread(job_store.prune_finished_jobs, jobs_dir, now=time.time())
    except OSError:
        logger.warning("Could not prune old agent jobs", exc_info=True)


async def _create_job(action: str, stack_name: str, services: list[str]) -> str:
    await _prune_finished_jobs(_jobs_dir())
    job_id = uuid.uuid4().hex[:12]
    await _write_job_status(
        job_id,
        job_id=job_id,
        action=action,
        stack_name=stack_name,
        services=services,
        status="queued",
        started_at=_utc_now_iso(),
    )
    await _append_job_log(job_id, f"Fleetge job {job_id} queued: {action}\n")
    return job_id


def _get_stack_path(name: str) -> str:
    """Resolve and validate the absolute path for a stack directory."""
    _validate_stack_name(name)

    # Check parent directory existence
    os.makedirs(STACKS_BASE_DIR, exist_ok=True)

    # Resolve paths
    base_real = os.path.realpath(STACKS_BASE_DIR)
    stack_path = os.path.join(base_real, name)
    stack_real = os.path.realpath(stack_path)

    # Ensure resolved path is strictly a child directory of the base stacks directory
    if os.path.commonpath([base_real, stack_real]) != base_real or stack_real == base_real:
        raise HTTPException(
            status_code=403,
            detail="Forbidden. Path traversal detected."
        )

    return stack_real


def _current_container_candidates() -> list[str]:
    candidates: list[str] = []
    try:
        with open("/etc/hostname", "r", encoding="utf-8") as f:
            hostname = f.read().strip()
        if hostname:
            candidates.append(hostname)
    except Exception:
        pass

    try:
        with open("/proc/self/mountinfo", "r", encoding="utf-8") as f:
            text = f.read()
        for match in re.finditer(r"/containers/([0-9a-f]{12,64})/", text):
            value = match.group(1)
            if value not in candidates:
                candidates.append(value)
    except Exception:
        pass

    return candidates


def _host_mount_for_path(inspect: dict, container_path: str) -> tuple[str, str]:
    """Return (host_source, container_destination) mount covering container_path."""
    path = os.path.realpath(container_path)
    mounts = inspect.get("Mounts", []) if isinstance(inspect, dict) else []
    best: tuple[str, str] | None = None
    best_destination_length = 0
    for mount in mounts or []:
        dest = mount.get("Destination")
        source = mount.get("Source")
        if not dest or not source:
            continue
        dest_real = os.path.realpath(dest)
        try:
            common = os.path.commonpath([path, dest_real])
        except ValueError:
            continue
        if common != dest_real:
            continue
        if len(dest_real) > best_destination_length:
            rel = os.path.relpath(path, dest_real)
            host_source = source if rel == "." else os.path.join(source, rel)
            best = (host_source, path)
            best_destination_length = len(dest_real)
    if best:
        return best
    return path, path


async def _get_agent_self_info() -> dict:
    """Return the current agent's compose identity as observed through Docker."""
    inspect = await asyncio.to_thread(_current_container_inspect_sync)
    container_id = str(inspect.get("Id") or "")
    config = inspect.get("Config") or {}
    labels = config.get("Labels", {}) if isinstance(config, dict) else {}
    labels = labels or {}
    image = str(config.get("Image") or inspect.get("Image") or "")
    stack_name = FLEETGE_STACK_NAME or labels.get("com.docker.compose.project") or ""
    service_name = FLEETGE_AGENT_SERVICE or labels.get("com.docker.compose.service") or ""
    working_dir = labels.get("com.docker.compose.project.working_dir") or ""
    stack_path = os.path.realpath(working_dir) if working_dir else (
        _get_stack_path(stack_name) if stack_name and STACK_NAME_RE.match(stack_name) else ""
    )
    stacks_host_path, stacks_container_path = _host_mount_for_path(inspect, STACKS_BASE_DIR)

    return {
        "instance_id": AGENT_INSTANCE_ID,
        "hostname": socket.gethostname(),
        "container_id": container_id[:12] if container_id else "",
        "stack_name": stack_name,
        "service_name": service_name,
        "stack_path": stack_path,
        "image": image,
        "version": AGENT_VERSION or labels.get("org.opencontainers.image.version") or "",
        "revision": labels.get("org.opencontainers.image.revision") or "",
        "stacks_base_dir": os.path.realpath(STACKS_BASE_DIR),
        "stacks_host_path": stacks_host_path,
        "stacks_container_path": stacks_container_path,
    }


def _find_compose_file(stack_path: str) -> Optional[str]:
    """Find the first matching docker-compose file name in a directory."""
    for filename in _COMPOSE_FILE_NAMES:
        full_path = os.path.join(stack_path, filename)
        if os.path.isfile(full_path):
            return filename
    return None


def _validate_compose_file_name(name: Optional[str]) -> str:
    """Return a valid compose file name or raise HTTPException."""
    filename = name or "compose.yaml"
    if filename not in _COMPOSE_FILE_NAMES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid compose file name '{filename}'. Allowed: {_COMPOSE_FILE_NAMES}"
        )
    return filename


def _validate_stack_payload(payload: StackSaveRequest) -> str:
    """Validate compose save payload and return the compose file name."""
    compose_filename = _validate_compose_file_name(payload.compose_file_name)
    if not payload.compose_yaml.strip():
        raise HTTPException(status_code=400, detail="compose_yaml cannot be empty")

    try:
        import yaml
        yaml.safe_load(payload.compose_yaml)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid compose YAML: {exc}")

    env_text = payload.compose_env or ""
    lines = env_text.splitlines()
    if len(lines) == 1 and lines[0].strip() and "=" not in lines[0]:
        raise HTTPException(status_code=400, detail="Invalid .env format: single non-empty line must contain '='")

    return compose_filename


@router.get("/ingress")
async def read_ingress():
    """Report the compose services currently holding the host ingress ports."""
    try:
        services = await asyncio.to_thread(ingress_services)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to inspect ingress listeners: {exc}")
    return {"ports": list(INGRESS_PORTS), "services": services}


@router.get("/stacks")
async def list_stacks():
    """List all directories containing a docker-compose file."""
    if not os.path.isdir(STACKS_BASE_DIR):
        return []

    stacks = []
    try:
        for entry in os.scandir(STACKS_BASE_DIR):
            if entry.is_dir() and STACK_NAME_RE.match(entry.name):
                stack_real = os.path.realpath(entry.path)
                if _find_compose_file(stack_real) is not None:
                    stacks.append(entry.name)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to scan stacks directory: {exc}")

    return sorted(stacks)


@router.get("/self")
async def get_self():
    """Return this agent container's compose identity for backend update planning."""
    return await _get_agent_self_info()


@router.get("/jobs/{job_id}")
async def get_job(job_id: str):
    """Return a persisted Fleetge agent job status."""
    status_path, _ = _job_paths(job_id)
    if not os.path.isfile(status_path):
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")
    try:
        with open(status_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read job status: {exc}")


@router.get("/jobs/{job_id}/logs", response_model=JobLogResponse)
async def get_job_logs(job_id: str):
    """Return a persisted Fleetge agent job log."""
    _, log_path = _job_paths(job_id)
    if not os.path.isfile(log_path):
        return JobLogResponse()
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        return JobLogResponse(content=content, size=len(content))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read job log: {exc}")


@router.get("/global-env")
async def get_global_env():
    """Read STACKS_BASE_DIR/global.env."""
    os.makedirs(STACKS_BASE_DIR, exist_ok=True)
    env_path = os.path.join(os.path.realpath(STACKS_BASE_DIR), "global.env")
    try:
        if not os.path.isfile(env_path):
            return {"content": ""}
        with open(env_path, "r", encoding="utf-8") as f:
            return {"content": f.read()}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read global.env: {exc}")


@router.put("/global-env")
async def save_global_env(payload: GlobalEnvRequest, request: Request):
    """Write or remove STACKS_BASE_DIR/global.env."""
    _require_enabled(AGENT_ENABLE_GLOBAL_ENV, "global-env writes")
    if _active_job_stacks or any(lock.locked() for lock in _locks.values()):
        raise HTTPException(status_code=409, detail="global.env cannot be changed while a Stack operation is active.")
    os.makedirs(STACKS_BASE_DIR, exist_ok=True)
    env_path = os.path.join(os.path.realpath(STACKS_BASE_DIR), "global.env")
    try:
        if payload.content.strip():
            atomic_write_text(env_path, payload.content)
        elif os.path.isfile(env_path):
            os.remove(env_path)
        await _write_audit("global_env.save", "success", client=_client_host(request))
        return {"success": True, "message": "global.env saved successfully."}
    except Exception as exc:
        await _write_audit("global_env.save", "error", client=_client_host(request), detail=str(exc))
        raise HTTPException(status_code=500, detail=f"Failed to write global.env: {exc}")


@router.get("/stacks/{name}")
async def get_stack(name: str):
    """Retrieve compose.yaml and .env contents for a stack."""
    stack_path = _get_stack_path(name)

    compose_filename = _find_compose_file(stack_path)
    if compose_filename is None:
        raise HTTPException(
            status_code=404,
            detail=f"Stack '{name}' compose file not found."
        )

    compose_path = os.path.join(stack_path, compose_filename)
    env_path = os.path.join(stack_path, ".env")

    try:
        with open(compose_path, "r", encoding="utf-8") as f:
            compose_yaml = f.read()

        compose_env = ""
        if os.path.isfile(env_path):
            with open(env_path, "r", encoding="utf-8") as f:
                compose_env = f.read()

        return {
            "name": name,
            "compose_yaml": compose_yaml,
            "compose_env": compose_env,
            "compose_file_name": compose_filename
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read stack configuration: {exc}")


@router.put("/stacks/{name}")
async def save_stack(name: str, payload: StackSaveRequest, request: Request):
    """Create or update a stack's configuration files."""
    _require_enabled(AGENT_ENABLE_WRITE, "stack writes")
    stack_path = _get_stack_path(name)
    compose_filename = _validate_stack_payload(payload)
    compose_path = os.path.join(stack_path, compose_filename)
    env_path = os.path.join(stack_path, ".env")

    lock = await get_stack_lock(name)
    if lock.locked() or name in _active_job_stacks:
        raise HTTPException(status_code=409, detail=f"Stack '{name}' is currently busy with an active command.")
    await lock.acquire()
    created = False
    try:
        exists = os.path.isdir(stack_path)
        if payload.is_add and exists:
            raise HTTPException(status_code=409, detail=f"Stack '{name}' already exists.")
        if not payload.is_add and not exists:
            raise HTTPException(status_code=404, detail=f"Stack '{name}' directory not found.")

        if not exists:
            os.makedirs(stack_path)
            created = True

        # Stage both files before replacing either one, so a failed write leaves
        # the previous Compose configuration and environment intact.
        with ExitStack() as staged:
            compose_write = staged.enter_context(staged_text(compose_path, payload.compose_yaml))
            changes: list[tuple[str | None, str]] = [compose_write]
            if payload.compose_env and payload.compose_env.strip():
                changes.append(staged.enter_context(staged_text(env_path, payload.compose_env)))
            elif os.path.isfile(env_path):
                changes.append((None, env_path))
            for filename in _COMPOSE_FILE_NAMES:
                if filename != compose_filename:
                    old_path = os.path.join(stack_path, filename)
                    if os.path.isfile(old_path):
                        changes.append((None, old_path))
            commit_stack_files(changes)

        await _write_audit("stack.save", "success", stack=name, client=_client_host(request))
        return {"success": True, "message": f"Stack '{name}' saved successfully."}
    except HTTPException as exc:
        await _write_audit("stack.save", "error", stack=name, client=_client_host(request), detail=str(exc.detail))
        raise
    except Exception as exc:
        if created:
            with suppress(OSError):
                os.rmdir(stack_path)
        await _write_audit("stack.save", "error", stack=name, client=_client_host(request), detail=str(exc))
        raise HTTPException(status_code=500, detail=f"Failed to write stack files: {exc}")
    finally:
        lock.release()


@router.delete("/stacks/{name}")
async def delete_stack(name: str, request: Request):
    """Safely delete a stack directory."""
    _require_enabled(AGENT_ENABLE_DELETE, "stack deletes")
    stack_path = _get_stack_path(name)

    if not os.path.isdir(stack_path):
        raise HTTPException(status_code=404, detail=f"Stack '{name}' directory not found.")

    # Guard: only delete directories that actually contain a compose file
    if _find_compose_file(stack_path) is None:
        raise HTTPException(
            status_code=400,
            detail=f"Stack '{name}' does not contain a compose file; refusing to delete."
        )

    lock = await get_stack_lock(name)
    if lock.locked() or name in _active_job_stacks:
        raise HTTPException(status_code=409, detail=f"Stack '{name}' is currently busy with an active command.")

    async with lock:
        if name in _active_job_stacks:
            raise HTTPException(status_code=409, detail=f"Stack '{name}' is currently busy with an active command.")
        try:
            exit_code, output = await _delete_stack_after_down(
                stack_path, await _compose_args_async(stack_path, "down", "--remove-orphans")
            )
            if exit_code != 0:
                raise HTTPException(status_code=502, detail=output.strip() or "docker compose down failed")
            await _write_audit("stack.delete", "success", stack=name, client=_client_host(request))
            return {"success": True, "message": f"Stack '{name}' deleted successfully."}
        except HTTPException as exc:
            await _write_audit("stack.delete", "error", stack=name, client=_client_host(request), detail=str(exc.detail))
            raise
        except Exception as exc:
            await _write_audit("stack.delete", "error", stack=name, client=_client_host(request), detail=str(exc))
            raise HTTPException(status_code=500, detail=f"Failed to delete stack directory: {exc}")


# Action to Docker Compose argument mapping. These are the subcommands passed
# through _compose_args(), which mirrors Dockge's centralized compose option
# builder.
ACTION_ARGS = {
    "up": ["up", "-d", "--remove-orphans"],
    "stop": ["stop"],
    "down": ["down"],
    "restart": ["restart"],
    "pull": ["pull"],
}


def _expose_host_path(host_path: str, container_path: str) -> None:
    """Link a translated host path to the mount that holds the same files.

    Docker Compose resolves relative file references (``env_file``, ``extends``,
    ``configs`` and ``secrets``) against the project directory, so using the
    host project directory for daemon-side bind paths must not hide those files
    from the Compose CLI running inside this container.
    """
    try:
        if os.path.normpath(host_path) == os.path.normpath(container_path):
            return
        if os.path.lexists(host_path):
            return
        os.makedirs(os.path.dirname(host_path), exist_ok=True)
        os.symlink(container_path, host_path)
    except OSError:
        pass


def _compose_host_project_dir(stack_path: str) -> str | None:
    """Return the host path when the stack directory is only a container mount.

    Docker Compose resolves relative bind mounts against its project directory.
    The agent runs inside a container while the Docker daemon runs on the host,
    so leaving the container path as the project directory makes the daemon
    create missing files and directories on the host.
    """
    stack_real = os.path.realpath(stack_path)
    base_real = os.path.realpath(STACKS_BASE_DIR)
    try:
        if os.path.commonpath([base_real, stack_real]) != base_real:
            return None
    except ValueError:
        return None
    inspect = _current_container_inspect_sync()
    host_base, container_base = _host_mount_for_path(inspect, base_real)
    if os.path.normpath(host_base) == os.path.normpath(container_base):
        return None
    _expose_host_path(host_base, container_base)
    relative = os.path.relpath(stack_real, base_real)
    return host_base if relative == "." else os.path.join(host_base, relative)


_self_inspect_lock = threading.Lock()
_self_inspect_result: dict = {}
_self_inspect_expires = 0.0


def _current_container_inspect_sync() -> dict:
    global _self_inspect_result, _self_inspect_expires
    with _self_inspect_lock:
        if time.monotonic() >= _self_inspect_expires:
            _self_inspect_result = _load_container_inspect()
            _self_inspect_expires = time.monotonic() + (60.0 if _self_inspect_result else 5.0)
        return _self_inspect_result


def _load_container_inspect() -> dict:
    from docker_cli_shim import inspect_object

    for candidate in _current_container_candidates():
        try:
            direct = inspect_object("container", candidate, timeout=5.0)
        except Exception:
            direct = None
        if isinstance(direct, dict) and direct:
            return {**direct, "Id": direct.get("Id") or candidate}
        try:
            result = subprocess.run(
                ["docker", "container", "inspect", candidate],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
                check=False,
            )
        except Exception:
            continue
        if result.returncode != 0:
            continue
        try:
            payload = json.loads(result.stdout)
        except Exception:
            continue
        if isinstance(payload, list) and payload and isinstance(payload[0], dict):
            return {**payload[0], "Id": payload[0].get("Id") or candidate}
    return {}


def _compose_args(stack_path: str, command: str, *extra_options: str) -> list[str]:
    """Build docker compose arguments using Dockge's env-file behavior."""
    host_project_dir = _compose_host_project_dir(stack_path)
    compose_file = _find_compose_file(stack_path) if host_project_dir else None
    return build_compose_args(
        stack_path, command, *extra_options,
        base_dir=STACKS_BASE_DIR,
        host_project_dir=host_project_dir,
        compose_file=os.path.join(stack_path, compose_file) if compose_file else None,
    )


async def _compose_args_async(stack_path: str, command: str, *options: str) -> list[str]:
    return await asyncio.to_thread(_compose_args, stack_path, command, *options)


async def _capture_pulled_images(stack_path: str, services: list[str] | None = None) -> list[dict]:
    return await asyncio.to_thread(
        capture_pulled_images,
        stack_path,
        await _compose_args_async(stack_path, "config", "--format", "json"),
        services,
    )


def _compose_status_convert(status: str) -> str:
    """Convert docker compose ls status using Dockge's status precedence."""
    if status.startswith("created"):
        return "created"
    if "exited" in status:
        return "exited"
    if status.startswith("running"):
        return "running"
    return "unknown"


_stream_with_subprocess = pty_executor.stream_with_subprocess


async def _stream_docker_command(
    websocket: WebSocket,
    stack_path: str,
    args: list[str],
    cols: int = 160,
    rows: int = 24,
) -> int:
    try:
        async with asyncio.timeout(pty_executor.COMMAND_TIMEOUT):
            return await pty_executor.stream_in_pty(websocket, stack_path, args, cols, rows, _stream_with_subprocess)
    except TimeoutError:
        await websocket.send_json({"type": "stdout", "chunk": "\nDocker command timed out.\n"})
        return 124


async def _run_docker_command_capture(stack_path: str, args: list[str]) -> tuple[int, str]:
    try:
        code, stdout, _ = await pty_executor.capture_docker(
            args, cwd=stack_path, timeout=300.0, stderr=asyncio.subprocess.STDOUT,
        )
        return code, _redact_sensitive_text(stdout.decode("utf-8", errors="replace"))
    except TimeoutError:
        return 124, "Docker command timed out after 300 seconds."
    except OSError as exc:
        return 1, f"Failed to run docker command: {exc}"


async def _run_job_command(job_id: str, stack_path: str, args: list[str], timeout: float = 600.0) -> int:
    await _append_job_log(job_id, f"\n$ docker {' '.join(args)}\n")
    try:
        proc = await pty_executor.spawn_docker(args, cwd=stack_path, stderr=asyncio.subprocess.STDOUT)
    except OSError as exc:
        await _append_job_log(job_id, f"Failed to start docker command: {exc}\n")
        return 1

    async def emit(chunk: str) -> None:
        await _append_job_log(job_id, chunk)

    try:
        async with asyncio.timeout(timeout):
            code = await pty_executor.stream_output(proc, emit)
    except TimeoutError:
        await _append_job_log(job_id, f"\nDocker command timed out after {timeout:g} seconds.\n")
        return 124
    await _append_job_log(job_id, f"\nCommand exited with code {code}\n")
    return code


async def _run_update_services_job(job_id: str, stack_path: str, services: list[str]) -> None:
    stage = "pull"
    try:
        await _write_job_status(job_id, status="running", phase=stage)
        exit_code = await _run_job_command(job_id, stack_path, await _compose_args_async(stack_path, "pull", *services))
        if exit_code == 0:
            stage = "target"
            await _write_job_status(job_id, status="running", phase=stage)
            try:
                pulled_images = await asyncio.to_thread(
                    capture_pulled_images,
                    stack_path,
                    await _compose_args_async(stack_path, "config", "--format", "json"),
                    services,
                )
                pulled_images = [item for item in pulled_images if item.get("service") in services]
                if len(pulled_images) != len(services):
                    raise RuntimeError("Could not resolve every requested service image.")
                await _write_job_status(job_id, pulled_images=pulled_images, up_executed=False)
            except Exception as exc:
                await _append_job_log(job_id, f"\n{exc}\n")
                await _write_job_status(job_id, status="error", phase="target", message=str(exc), finished_at=_utc_now_iso())
                return
            stage = "up"
            await _write_job_status(job_id, status="running", phase=stage, up_executed=True)
            exit_code = await _run_job_command(
                job_id,
                stack_path,
                await _compose_args_async(stack_path, "up", "-d", "--no-deps", "--pull", "never", *services),
            )

        if exit_code == 124:
            await _write_job_status(job_id, status="uncertain", phase="uncertain", message=f"Docker {stage} command timed out; result is unknown.", finished_at=_utc_now_iso())
        elif exit_code == 0:
            await _write_job_status(job_id, status="success", phase="done", exit_code=0, finished_at=_utc_now_iso())
            await _append_job_log(job_id, "\nFleetge update job completed successfully.\n")
        else:
            await _write_job_status(job_id, status="error", phase=stage, exit_code=exit_code, finished_at=_utc_now_iso())
            await _append_job_log(job_id, f"\nFleetge update job failed with exit code {exit_code}.\n")
    except asyncio.CancelledError:
        await _write_job_status(job_id, status="uncertain", phase="uncertain", message="Agent stopped while the update was running.", finished_at=_utc_now_iso())
        raise
    except Exception as exc:
        await _write_job_status(job_id, status="uncertain", phase="uncertain", message=f"Update job ended without a confirmed result: {exc}", finished_at=_utc_now_iso())


async def _start_update_services_job(stack_name: str, stack_path: str, services: list[str]) -> str:
    job_id = await _create_job("updateServicesJob", stack_name, services)
    lock = await get_stack_lock(stack_name)
    _active_job_stacks[stack_name] = job_id

    async def run() -> None:
        async with lock:
            await _run_update_services_job(job_id, stack_path, services)

    _track_job(asyncio.create_task(run()), stack_name, job_id)
    return job_id


def _read_job_status(job_id: str) -> dict:
    status_path, _ = _job_paths(job_id)
    return job_store.read_status(status_path)


async def _container_is_running(container_name: str) -> bool | None:
    try:
        code, stdout, errors = await pty_executor.capture_docker(
            ["inspect", "--format", "{{.State.Running}}", container_name], timeout=15.0,
        )
    except (OSError, TimeoutError):
        return None
    if code == 0:
        return stdout.strip().lower() == b"true"
    detail = (errors or b"").lower()
    if b"no such object" in detail or b"no such container" in detail:
        return False
    return None


def _start_self_update_watcher(job_id: str, stack_name: str, container_name: str) -> None:
    _active_job_stacks[stack_name] = job_id
    task = asyncio.create_task(_watch_self_update_job(job_id, stack_name, container_name))
    _track_job(task, stack_name, job_id)


async def _watch_self_update_job(job_id: str, stack_name: str, container_name: str) -> None:
    while True:
        status = await asyncio.to_thread(_read_job_status, job_id)
        if status.get("status") in _TERMINAL_JOB_STATES:
            return
        if await _container_is_running(container_name) is False:
            await _write_job_status(
                job_id,
                status="uncertain",
                phase="uncertain",
                message="Updater container stopped before recording a final result.",
                finished_at=_utc_now_iso(),
            )
            return
        await asyncio.sleep(2.0)


async def reconcile_jobs() -> None:
    """Recover job state after Agent restart without replaying Docker commands."""
    jobs_dir = _jobs_dir()
    await _prune_finished_jobs(jobs_dir)
    with os.scandir(jobs_dir) as entries:
        job_ids = [
            entry.name[:-5] for entry in entries
            if entry.is_file() and re.fullmatch(r"[a-zA-Z0-9_.-]+\.json", entry.name)
        ]
    for job_id in job_ids:
        status = await asyncio.to_thread(_read_job_status, job_id)
        state = status.get("status")
        if state in _TERMINAL_JOB_STATES or not status.get("stack_name"):
            continue
        stack_name = status["stack_name"]
        if status.get("action") == "selfUpdate" and state in {"handoff", "running"}:
            container_name = status.get("updater_container") or f"fleetge-self-updater-{job_id}"
            _start_self_update_watcher(job_id, stack_name, container_name)
        elif state == "queued":
            await _write_job_status(
                job_id,
                status="skipped",
                phase="skipped",
                message="Agent restarted before this queued job began; it was not replayed.",
                finished_at=_utc_now_iso(),
            )
        else:
            await _write_job_status(
                job_id,
                status="uncertain",
                phase="uncertain",
                message="Agent restarted while the job was running; execution was not replayed.",
                finished_at=_utc_now_iso(),
            )


async def _start_self_updater_container(stack_name: str, stack_path: str, services: list[str]) -> str:
    job_id = await _create_job("selfUpdate", stack_name, services)
    container_name = f"fleetge-self-updater-{job_id}"
    _active_job_stacks[stack_name] = job_id
    launch_attempted = False
    handoff_finished = False
    try:
        cmd = await _self_updater_args(job_id, container_name, stack_path, services)
        await _write_job_status(job_id, status="handoff", phase="starting-updater", updater_container=container_name)
        await _append_job_log(job_id, f"Starting temporary updater container for services: {', '.join(services)}\n")
        launch_attempted = True
        exit_code, output = await _run_docker_command_capture("/", cmd)
        if exit_code == 0 or exit_code == 124:
            _start_self_update_watcher(job_id, stack_name, container_name)
            handoff_finished = True
            await _append_job_log(job_id, output)
            if exit_code == 0:
                await _append_job_log(job_id, f"Temporary updater started: {container_name}\n")
            return job_id

        launch_attempted = False
        await _write_job_status(
            job_id,
            status="error",
            phase="start-updater-failed",
            exit_code=exit_code,
            finished_at=_utc_now_iso(),
        )
        await _append_job_log(job_id, output)
        raise HTTPException(status_code=502, detail=output.strip() or "Failed to start self-updater container")
    except BaseException:
        if launch_attempted and not handoff_finished:
            _start_self_update_watcher(job_id, stack_name, container_name)
        elif not handoff_finished:
            try:
                await _write_job_status(
                    job_id, status="skipped", phase="skipped", message="Updater container was not started.",
                    finished_at=_utc_now_iso(),
                )
            finally:
                _active_job_stacks.pop(stack_name, None)
        raise


async def _self_updater_args(job_id: str, container_name: str, stack_path: str, services: list[str]) -> list[str]:
    self_info = await _get_agent_self_info()
    updater_image = FLEETGE_UPDATER_IMAGE or self_info.get("image") or "ghcr.io/virgooooox/fleetge-agent:latest"
    stacks_host_path = self_info.get("stacks_host_path") or os.path.realpath(STACKS_BASE_DIR)
    stacks_container_path = self_info.get("stacks_container_path") or os.path.realpath(STACKS_BASE_DIR)
    job_status_path, _ = _job_paths(job_id)

    mounts = [
        "-v", "/var/run/docker.sock:/var/run/docker.sock",
        "-v", f"{stacks_host_path}:{stacks_container_path}",
    ]
    if os.path.normpath(stacks_host_path) != os.path.normpath(stacks_container_path):
        # The updater runs Compose with the host project directory, so relative
        # file references need the same host path to resolve inside it too.
        mounts += ["-v", f"{stacks_host_path}:{stacks_host_path}"]
    cmd = [
        "run", "-d", "--rm",
        "--name", container_name,
        *mounts,
        "-e", f"STACKS_BASE_DIR={stacks_container_path}",
        updater_image,
        "python", "-m", "self_updater",
        "--job-id", job_id,
        "--stack-dir", stack_path,
        "--jobs-dir", os.path.dirname(job_status_path),
        "--services", *services,
    ]
    host_project_dir = await asyncio.to_thread(_compose_host_project_dir, stack_path)
    if host_project_dir:
        handoff_args = ["--host-project-dir", host_project_dir]
        compose_file = _find_compose_file(stack_path)
        if compose_file:
            handoff_args += ["--compose-file", os.path.join(stack_path, compose_file)]
        services_index = cmd.index("--services")
        cmd[services_index:services_index] = handoff_args

    return cmd


async def _delete_stack_after_down(stack_path: str, args: list[str]) -> tuple[int, str]:
    exit_code, output = await _run_docker_command_capture(stack_path, args)
    if exit_code != 0:
        return exit_code, output
    try:
        await asyncio.to_thread(shutil.rmtree, stack_path)
        return 0, output
    except Exception as exc:
        return 1, output + f"\nFailed to delete stack directory: {exc}"


async def _get_compose_project_status(stack_name: str) -> str:
    """Return stack status from docker compose ls, matching Dockge update logic."""
    try:
        code, stdout, _ = await pty_executor.capture_docker(
            ["compose", "ls", "--all", "--format", "json"], timeout=30.0,
        )
    except Exception:
        return "unknown"

    if code != 0:
        return "unknown"

    text = stdout.decode("utf-8", errors="replace").strip()
    if not text:
        return "unknown"

    # docker compose ls normally emits a JSON array, but tolerate one object
    # per line to keep compatibility with Docker CLI output variations.
    try:
        projects = json.loads(text)
        if isinstance(projects, dict):
            projects = [projects]
    except json.JSONDecodeError:
        projects = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                projects.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    for project in projects:
        if not isinstance(project, dict):
            continue
        if project.get("Name") == stack_name:
            return _compose_status_convert(str(project.get("Status") or ""))

    return "unknown"


async def _get_compose_services(stack_path: str) -> list[dict]:
    """Return docker compose ps rows for a stack."""
    try:
        args = await _compose_args_async(stack_path, "ps", "--format", "json")
        code, stdout, stderr = await pty_executor.capture_docker(args, cwd=stack_path, timeout=30.0)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to inspect compose services: {exc}")

    if code != 0:
        detail = (stderr or b"").decode("utf-8", errors="replace").strip() or "docker compose ps failed"
        raise HTTPException(status_code=502, detail=_redact_sensitive_text(detail))

    text = stdout.decode("utf-8", errors="replace").strip()
    if not text:
        return []

    try:
        services = json.loads(text)
        if isinstance(services, dict):
            services = [services]
        if isinstance(services, list):
            return [svc for svc in services if isinstance(svc, dict)]
    except json.JSONDecodeError:
        rows = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
                if isinstance(item, dict):
                    rows.append(item)
            except json.JSONDecodeError:
                continue
        return rows

    return []


async def _selected_services_running(stack_path: str, services: list[str]) -> bool:
    """Do not let an unrelated stopped service block a selected update."""
    rows = await _get_compose_services(stack_path)
    running = {row.get("Service") for row in rows if str(row.get("State", "")).lower() == "running"}
    return all(service in running for service in services)


@router.get("/stacks/{name}/services")
async def list_stack_services(name: str):
    """Return service status from docker compose ps."""
    stack_path = _get_stack_path(name)
    if _find_compose_file(stack_path) is None:
        raise HTTPException(status_code=404, detail=f"Stack '{name}' compose file not found.")
    return {"services": await _get_compose_services(stack_path)}


@router.websocket("/host/prune")
async def prune_system(websocket: WebSocket):
    """Run ``docker system prune -a -f`` and stream output in real-time."""
    await websocket.accept()
    client = _client_host(websocket)

    try:
        if not AGENT_ENABLE_PRUNE:
            await _write_audit("host.prune", "denied", client=client)
            await websocket.send_json({"type": "error", "message": "host prune is disabled by agent policy."})
            return

        exit_code = await _stream_docker_command(
            websocket, "/", ["system", "prune", "-a", "-f"]
        )
        await websocket.send_json({"type": "exit", "code": exit_code})
        await _write_audit(
            "host.prune",
            "success" if exit_code == 0 else "error",
            client=client,
            detail=f"exit_code={exit_code}",
        )
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        import traceback
        traceback.print_exc()
        await _write_audit("host.prune", "error", client=client, detail=str(exc))
        try:
            await websocket.send_json({"type": "error", "message": f"Prune failed: {exc}"})
        except Exception:
            pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


@router.websocket("/stacks/{name}/logs")
async def stream_stack_compose_logs(websocket: WebSocket, name: str, tail: int = 100):
    """Stream combined stack logs using docker compose logs -f.

    This mirrors Dockge's combined terminal behavior: the stream is tied to the
    compose project, not to the container IDs that happen to be running when the
    UI opens the log panel.
    """
    await websocket.accept()

    if tail < 1:
        tail = 100
    if tail > 5000:
        tail = 5000

    try:
        try:
            stack_path = _get_stack_path(name)
        except HTTPException as exc:
            await websocket.send_json({"type": "error", "message": exc.detail})
            await websocket.close()
            return

        if _find_compose_file(stack_path) is None:
            await websocket.send_json({
                "type": "error",
                "message": f"No compose file found in stack '{name}'.",
            })
            await websocket.close()
            return

        await websocket.send_json({"type": "ready"})
        # Logs are not interactive. Use a pipe-based subprocess so quiet streams
        # still flush their initial tail instead of waiting inside PTY reads.
        exit_code = await _stream_with_subprocess(
            websocket,
            stack_path,
            await _compose_args_async(stack_path, "logs", "--no-color", "-f", "--tail", str(tail)),
        )
        await websocket.send_json({"type": "exit", "code": exit_code})
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        import traceback
        traceback.print_exc()
        try:
            await websocket.send_json({"type": "error", "message": f"Unexpected log stream error: {exc}"})
        except Exception:
            pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


@router.websocket("/stacks/{name}/execute")
async def execute_stack_command(websocket: WebSocket, name: str):
    """WebSocket endpoint to execute a Docker Compose command and stream output in real-time."""
    await websocket.accept()
    client = _client_host(websocket)
    action = ""
    stage = "preflight"
    up_executed = False

    try:
        # Validate path
        try:
            stack_path = _get_stack_path(name)
        except HTTPException as exc:
            await websocket.send_json({"type": "error", "message": exc.detail})
            await websocket.close()
            return

        # Receive execution options (e.g. {"action": "up"})
        data = await websocket.receive_json()
        action = data.get("action")
        service = data.get("service")
        services = data.get("services")
        cols = data.get("cols", 160)
        rows = data.get("rows", 24)
        service_actions = {"startService", "stopService", "restartService"}
        service_update_actions = {"updateServices", "updateServicesJob", "selfUpdate"}
        special_actions = {"update", "delete"} | service_actions | service_update_actions
        if action not in ACTION_ARGS and action not in special_actions:
            await _write_audit("stack.execute", "denied", stack=name, client=client, detail=f"invalid action {action}")
            await websocket.send_json({
                "type": "error",
                "message": f"Invalid action '{action}'. Supported: {list(ACTION_ARGS.keys()) + sorted(special_actions)}"
            })
            await websocket.close()
            return

        if action == "delete" and not AGENT_ENABLE_DELETE:
            await _write_audit(f"stack.{action}", "denied", stack=name, client=client)
            await websocket.send_json({"type": "error", "message": "stack deletes are disabled by agent policy."})
            await websocket.close()
            return
        if action == "selfUpdate" and not AGENT_ENABLE_SELF_UPDATE:
            await _write_audit(f"stack.{action}", "denied", stack=name, client=client)
            await websocket.send_json({"type": "error", "message": "self update is disabled by agent policy."})
            await websocket.close()
            return
        if not AGENT_ENABLE_WRITE:
            await _write_audit(f"stack.{action}", "denied", stack=name, client=client)
            await websocket.send_json({"type": "error", "message": "stack writes are disabled by agent policy."})
            await websocket.close()
            return

        # Acquire lock to prevent concurrent actions on the same stack
        lock = await get_stack_lock(name)
        if lock.locked() or name in _active_job_stacks:
            await _write_audit(f"stack.{action}", "busy", stack=name, client=client)
            await websocket.send_json({
                "type": "error",
                "message": f"Another operation is already running for stack '{name}'.",
                "error_code": "stack_busy",
            })
            await websocket.close()
            return

        async with lock:
            # Check compose file existence
            if _find_compose_file(stack_path) is None:
                await _write_audit(f"stack.{action}", "error", stack=name, client=client, detail="compose file not found")
                await websocket.send_json({
                    "type": "error",
                    "message": f"No compose file found in stack '{name}'."
                })
                await websocket.close()
                return

            if action == "update":
                exit_code = await _stream_docker_command(
                    websocket, stack_path, await _compose_args_async(stack_path, "pull"), cols=cols, rows=rows
                )
                stage = "pull"
                up_executed = False
                pulled_images: list[dict] = []
                if exit_code == 0:
                    try:
                        pulled_images = await _capture_pulled_images(stack_path)
                    except Exception:
                        pulled_images = []
                if exit_code == 0 and await _get_compose_project_status(name) == "running":
                    stage = "up"
                    up_executed = True
                    exit_code = await _stream_docker_command(
                        websocket, stack_path, await _compose_args_async(stack_path, "up", "-d", "--remove-orphans"), cols=cols, rows=rows
                    )
                exit_payload = {
                    "type": "exit",
                    "code": exit_code,
                    "stage": stage,
                    "up_executed": up_executed,
                }
                if pulled_images:
                    exit_payload["pulled_images"] = pulled_images
                await websocket.send_json(exit_payload)
                await _write_audit(f"stack.{action}", "success" if exit_code == 0 else "error", stack=name, client=client, detail=f"stage={stage} exit_code={exit_code}")
            elif action == "delete":
                exit_code = await _stream_docker_command(
                    websocket, stack_path, await _compose_args_async(stack_path, "down", "--remove-orphans"), cols=cols, rows=rows
                )
                if exit_code == 0:
                    try:
                        await asyncio.to_thread(shutil.rmtree, stack_path)
                        await websocket.send_json({"type": "stdout", "chunk": f"\r\nStack '{name}' directory deleted.\r\n"})
                    except Exception as exc:
                        await _write_audit(f"stack.{action}", "error", stack=name, client=client, detail=str(exc))
                        await websocket.send_json({"type": "error", "message": f"Failed to delete stack directory: {exc}"})
                        await websocket.close()
                        return
                await websocket.send_json({"type": "exit", "code": exit_code})
                await _write_audit(f"stack.{action}", "success" if exit_code == 0 else "error", stack=name, client=client, detail=f"exit_code={exit_code}")
            elif action in service_actions:
                service_name = _validate_service_name(service)
                if action == "startService":
                    args = await _compose_args_async(stack_path, "up", "-d", service_name)
                elif action == "stopService":
                    args = await _compose_args_async(stack_path, "stop", service_name)
                else:
                    args = await _compose_args_async(stack_path, "restart", service_name)
                exit_code = await _stream_docker_command(websocket, stack_path, args, cols=cols, rows=rows)
                await websocket.send_json({"type": "exit", "code": exit_code})
                await _write_audit(f"stack.{action}", "success" if exit_code == 0 else "error", stack=name, client=client, detail=f"service={service_name} exit_code={exit_code}")
            elif action in service_update_actions:
                service_names = _validate_services(services)
                self_info = await _get_agent_self_info()
                is_self_stack = self_info.get("stack_name") == name
                self_service = self_info.get("service_name") or FLEETGE_AGENT_SERVICE
                if action != "selfUpdate" and is_self_stack and self_service in service_names:
                    await _write_audit(f"stack.{action}", "denied", stack=name, client=client, detail="current agent service")
                    await websocket.send_json({
                        "type": "error",
                        "message": "Refusing to update the current agent service without selfUpdate handoff.",
                    })
                    await websocket.close()
                    return

                if action == "updateServices":
                    stage = "pull"
                    up_executed = False
                    pulled_images: list[dict] = []
                    exit_code = await _stream_docker_command(
                        websocket,
                        stack_path,
                        await _compose_args_async(stack_path, "pull", *service_names),
                        cols=cols,
                        rows=rows,
                    )
                    if exit_code == 0:
                        stage = "target"
                        pulled_images = await _capture_pulled_images(stack_path, service_names)
                        if len(pulled_images) != len(service_names):
                            raise RuntimeError("Could not resolve every requested service image.")
                        if await _selected_services_running(stack_path, service_names):
                            stage = "up"
                            up_executed = True
                            exit_code = await _stream_docker_command(
                                websocket,
                                stack_path,
                                await _compose_args_async(stack_path, "up", "-d", "--no-deps", "--pull", "never", *service_names),
                                cols=cols,
                                rows=rows,
                            )
                    await websocket.send_json({
                        "type": "exit", "code": exit_code, "stage": stage,
                        "up_executed": up_executed, "pulled_images": pulled_images,
                    })
                    await _write_audit(f"stack.{action}", "success" if exit_code == 0 else "error", stack=name, client=client, detail=f"services={','.join(service_names)} exit_code={exit_code}")
                elif action == "updateServicesJob":
                    job_id = await _start_update_services_job(name, stack_path, service_names)
                    await websocket.send_json({
                        "type": "job",
                        "job_id": job_id,
                        "message": f"Started Fleetge service update job {job_id}.",
                    })
                    await websocket.send_json({"type": "exit", "code": 0})
                    await _write_audit(f"stack.{action}", "success", stack=name, client=client, detail=f"services={','.join(service_names)} job_id={job_id}")
                else:
                    job_id = await _start_self_updater_container(name, stack_path, service_names)
                    await websocket.send_json({
                        "type": "job",
                        "job_id": job_id,
                        "message": f"Handed off Fleetge self-update to job {job_id}.",
                    })
                    await websocket.send_json({"type": "exit", "code": 0})
                    await _write_audit(f"stack.{action}", "success", stack=name, client=client, detail=f"services={','.join(service_names)} job_id={job_id}")
            else:
                args = await _compose_args_async(stack_path, *ACTION_ARGS[action])
                exit_code = await _stream_docker_command(websocket, stack_path, args, cols=cols, rows=rows)
                await websocket.send_json({"type": "exit", "code": exit_code})
                await _write_audit(f"stack.{action}", "success" if exit_code == 0 else "error", stack=name, client=client, detail=f"exit_code={exit_code}")

    except WebSocketDisconnect:
        # Client disconnected prematurely; any spawned process was already terminated
        # by _stream_docker_command before the exception propagated.
        pass
    except Exception as exc:
        import traceback
        traceback.print_exc()
        await _write_audit(f"stack.{action or 'execute'}", "error", stack=name, client=client, detail=str(exc))
        try:
            message = _redact_sensitive_text(f"Unexpected execution error: {exc}")
            payload = {"type": "error", "message": message}
            if action in {"update", "updateServices"}:
                payload.update(stage=stage, up_executed=up_executed)
            await websocket.send_json(payload)
        except Exception:
            pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass
