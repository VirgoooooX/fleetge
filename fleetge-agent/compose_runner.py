import os
import re
import shutil
import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

STACKS_BASE_DIR = os.environ.get("STACKS_BASE_DIR", "/opt/stacks")
FLEETGE_STACK_NAME = os.environ.get("FLEETGE_STACK_NAME", "").strip()
FLEETGE_AGENT_SERVICE = os.environ.get("FLEETGE_AGENT_SERVICE", "").strip()
FLEETGE_UPDATER_IMAGE = os.environ.get("FLEETGE_UPDATER_IMAGE", "").strip()

router = APIRouter()

# Dockge-compatible stack names. Keep this aligned with frontend/backend validation.
STACK_NAME_RE = re.compile(r"^[a-z0-9_-]+$")
SERVICE_NAME_RE = re.compile(r"^[a-zA-Z0-9_.-]+$")

# Recognized docker-compose file names
_COMPOSE_FILE_NAMES = [
    "docker-compose.yml",
    "docker-compose.yaml",
    "compose.yml",
    "compose.yaml",
]

# Concurrent locks per stack name
_locks: dict[str, asyncio.Lock] = {}
_locks_lock = asyncio.Lock()


async def get_stack_lock(stack_name: str) -> asyncio.Lock:
    """Get or create an asyncio.Lock for a specific stack name."""
    async with _locks_lock:
        if stack_name not in _locks:
            _locks[stack_name] = asyncio.Lock()
        return _locks[stack_name]


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
    if not SERVICE_NAME_RE.match(service):
        raise HTTPException(
            status_code=400,
            detail="Invalid service name. Only letters, numbers, dots, hyphens, and underscores are allowed.",
        )
    return service


def _validate_services(services: object) -> list[str]:
    if not isinstance(services, list) or not services:
        raise HTTPException(status_code=400, detail="services must be a non-empty list")
    return [_validate_service_name(str(service)) for service in services]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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


async def _write_job_status(job_id: str, **updates) -> None:
    status_path, _ = _job_paths(job_id)

    def write() -> None:
        current = {}
        if os.path.isfile(status_path):
            try:
                with open(status_path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    current.update(loaded)
            except Exception:
                pass
        current.update(updates)
        current["updated_at"] = _utc_now_iso()
        tmp_path = f"{status_path}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(current, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, status_path)

    await asyncio.to_thread(write)


async def _append_job_log(job_id: str, text: str) -> None:
    _, log_path = _job_paths(job_id)
    await asyncio.to_thread(_append_job_log_sync, log_path, text)


def _append_job_log_sync(log_path: str, text: str) -> None:
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "a", encoding="utf-8", errors="replace") as f:
        f.write(text)


async def _create_job(action: str, stack_name: str, services: list[str]) -> str:
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
        with open("/proc/self/cgroup", "r", encoding="utf-8") as f:
            text = f.read()
        for match in re.finditer(r"([0-9a-f]{12,64})", text):
            value = match.group(1)
            if value not in candidates:
                candidates.append(value)
    except Exception:
        pass

    return candidates


async def _inspect_container(container_id: str) -> Optional[dict]:
    try:
        process = await asyncio.create_subprocess_exec(
            "docker", "container", "inspect", container_id,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout=10.0)
    except Exception:
        return None
    if process.returncode != 0:
        return None
    try:
        payload = json.loads(stdout.decode("utf-8", errors="replace"))
    except Exception:
        return None
    if isinstance(payload, list) and payload and isinstance(payload[0], dict):
        return payload[0]
    return None


def _host_mount_for_path(inspect: dict, container_path: str) -> tuple[str, str]:
    """Return (host_source, container_destination) mount covering container_path."""
    path = os.path.realpath(container_path)
    mounts = inspect.get("Mounts", []) if isinstance(inspect, dict) else []
    best: tuple[str, str] | None = None
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
        if best is None or len(dest_real) > len(best[1]):
            rel = os.path.relpath(path, dest_real)
            host_source = source if rel == "." else os.path.join(source, rel)
            best = (host_source, path)
    if best:
        return best
    return path, path


async def _get_agent_self_info() -> dict:
    """Return the current agent's compose identity as observed through Docker."""
    inspect: dict = {}
    container_id = ""
    for candidate in _current_container_candidates():
        found = await _inspect_container(candidate)
        if found:
            inspect = found
            container_id = str(found.get("Id") or candidate)
            break

    config = inspect.get("Config", {}) if inspect else {}
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
        "container_id": container_id[:12] if container_id else "",
        "stack_name": stack_name,
        "service_name": service_name,
        "stack_path": stack_path,
        "image": image,
        "version": labels.get("org.opencontainers.image.version") or "",
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
async def save_global_env(payload: GlobalEnvRequest):
    """Write or remove STACKS_BASE_DIR/global.env."""
    os.makedirs(STACKS_BASE_DIR, exist_ok=True)
    env_path = os.path.join(os.path.realpath(STACKS_BASE_DIR), "global.env")
    try:
        if payload.content.strip():
            with open(env_path, "w", encoding="utf-8") as f:
                f.write(payload.content)
        elif os.path.isfile(env_path):
            os.remove(env_path)
        return {"success": True, "message": "global.env saved successfully."}
    except Exception as exc:
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
async def save_stack(name: str, payload: StackSaveRequest):
    """Create or update a stack's configuration files."""
    stack_path = _get_stack_path(name)
    compose_filename = _validate_stack_payload(payload)
    compose_path = os.path.join(stack_path, compose_filename)
    env_path = os.path.join(stack_path, ".env")

    try:
        exists = os.path.isdir(stack_path)
        if payload.is_add and exists:
            raise HTTPException(status_code=409, detail=f"Stack '{name}' already exists.")
        if not payload.is_add and not exists:
            raise HTTPException(status_code=404, detail=f"Stack '{name}' directory not found.")

        os.makedirs(stack_path, exist_ok=True)

        # Write compose file
        with open(compose_path, "w", encoding="utf-8") as f:
            f.write(payload.compose_yaml)

        # Remove any old compose file(s) with a different name so only one remains
        for filename in _COMPOSE_FILE_NAMES:
            if filename == compose_filename:
                continue
            old_path = os.path.join(stack_path, filename)
            if os.path.isfile(old_path):
                os.remove(old_path)

        # Write or remove env file
        if payload.compose_env and payload.compose_env.strip():
            with open(env_path, "w", encoding="utf-8") as f:
                f.write(payload.compose_env)
        elif os.path.isfile(env_path):
            os.remove(env_path)

        return {"success": True, "message": f"Stack '{name}' saved successfully."}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to write stack files: {exc}")


@router.delete("/stacks/{name}")
async def delete_stack(name: str):
    """Safely delete a stack directory."""
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
    if lock.locked():
        raise HTTPException(status_code=409, detail=f"Stack '{name}' is currently busy with an active command.")

    async with lock:
        try:
            exit_code, output = await _delete_stack_after_down(
                stack_path, _compose_args(stack_path, "down", "--remove-orphans")
            )
            if exit_code != 0:
                raise HTTPException(status_code=502, detail=output.strip() or "docker compose down failed")
            return {"success": True, "message": f"Stack '{name}' deleted successfully."}
        except HTTPException:
            raise
        except Exception as exc:
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


def _compose_args(stack_path: str, command: str, *extra_options: str) -> list[str]:
    """Build docker compose arguments using Dockge's env-file behavior."""
    args = ["compose", command, *extra_options]
    base_real = os.path.realpath(STACKS_BASE_DIR)
    global_env_path = os.path.join(base_real, "global.env")

    if os.path.isfile(global_env_path):
        if os.path.isfile(os.path.join(stack_path, ".env")):
            args[1:1] = ["--env-file", "./.env"]
        args[1:1] = ["--env-file", "../global.env"]

    return args


def _compose_status_convert(status: str) -> str:
    """Convert docker compose ls status using Dockge's status precedence."""
    if status.startswith("created"):
        return "created"
    if "exited" in status:
        return "exited"
    if status.startswith("running"):
        return "running"
    return "unknown"


async def _stream_with_subprocess(
    websocket: WebSocket,
    stack_path: str,
    args: list[str],
) -> int:
    """Fallback streamer using asyncio subprocess when PTY is unavailable."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "docker", *args,
            cwd=stack_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
    except Exception as exc:
        await websocket.send_json({
            "type": "error",
            "message": f"Failed to start docker command: {exc}",
        })
        return 1

    stdout = proc.stdout
    assert stdout is not None

    try:
        while True:
            chunk = await stdout.read(4096)
            if not chunk:
                break
            await websocket.send_json({
                "type": "stdout",
                "chunk": chunk.decode("utf-8", errors="replace"),
            })

        await proc.wait()
        return proc.returncode if proc.returncode is not None else 0
    except WebSocketDisconnect:
        try:
            proc.kill()
        except Exception:
            pass
        raise
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
        raise
    finally:
        if proc.returncode is None:
            try:
                proc.kill()
            except Exception:
                pass


async def _stream_docker_command(
    websocket: WebSocket,
    stack_path: str,
    args: list[str],
    cols: int = 160,
    rows: int = 24,
) -> int:
    """Spawn a docker command in a PTY and stream raw chunks to the WebSocket.

    Falls back to a plain subprocess when PTY support is unavailable (e.g. Windows).
    """
    ptyprocess = None
    try:
        import ptyprocess as _ptyprocess
        ptyprocess = _ptyprocess
    except Exception:
        pass

    if ptyprocess is None:
        return await _stream_with_subprocess(websocket, stack_path, args)

    try:
        proc = ptyprocess.PtyProcessUnicode.spawn(
            ["docker", *args],
            cwd=stack_path,
            dimensions=(rows, cols),
        )
    except Exception:
        return await _stream_with_subprocess(websocket, stack_path, args)

    try:
        while True:
            try:
                chunk = await asyncio.to_thread(proc.read, 4096)
            except EOFError:
                break
            if not chunk:
                break
            await websocket.send_json({"type": "stdout", "chunk": chunk})

        if proc.isalive():
            await asyncio.to_thread(proc.wait)

        return proc.exitstatus if proc.exitstatus is not None else 0
    except WebSocketDisconnect:
        if proc.isalive():
            try:
                proc.terminate(force=True)
            except Exception:
                pass
        raise
    except Exception:
        if proc.isalive():
            try:
                proc.terminate(force=True)
            except Exception:
                pass
        raise
    finally:
        if proc.isalive():
            try:
                proc.terminate(force=True)
            except Exception:
                pass


async def _run_docker_command_capture(stack_path: str, args: list[str]) -> tuple[int, str]:
    """Run a docker command without a WebSocket and return exit code plus output."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "docker", *args,
            cwd=stack_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=300.0)
        return proc.returncode if proc.returncode is not None else 0, stdout.decode("utf-8", errors="replace")
    except Exception as exc:
        return 1, f"Failed to run docker command: {exc}"


async def _run_job_command(job_id: str, stack_path: str, args: list[str]) -> int:
    await _append_job_log(job_id, f"\n$ docker {' '.join(args)}\n")
    try:
        proc = await asyncio.create_subprocess_exec(
            "docker", *args,
            cwd=stack_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
    except Exception as exc:
        await _append_job_log(job_id, f"Failed to start docker command: {exc}\n")
        return 1

    assert proc.stdout is not None
    while True:
        chunk = await proc.stdout.read(4096)
        if not chunk:
            break
        await _append_job_log(job_id, chunk.decode("utf-8", errors="replace"))

    await proc.wait()
    code = proc.returncode if proc.returncode is not None else 0
    await _append_job_log(job_id, f"\nCommand exited with code {code}\n")
    return code


async def _run_update_services_job(job_id: str, stack_path: str, services: list[str]) -> None:
    await _write_job_status(job_id, status="running", phase="pull")
    exit_code = await _run_job_command(job_id, stack_path, _compose_args(stack_path, "pull", *services))
    if exit_code == 0:
        await _write_job_status(job_id, status="running", phase="up")
        exit_code = await _run_job_command(
            job_id,
            stack_path,
            _compose_args(stack_path, "up", "-d", "--no-deps", *services),
        )

    if exit_code == 0:
        await _write_job_status(job_id, status="success", phase="done", exit_code=0, finished_at=_utc_now_iso())
        await _append_job_log(job_id, "\nFleetge update job completed successfully.\n")
    else:
        await _write_job_status(job_id, status="error", phase="failed", exit_code=exit_code, finished_at=_utc_now_iso())
        await _append_job_log(job_id, f"\nFleetge update job failed with exit code {exit_code}.\n")


async def _start_update_services_job(stack_name: str, stack_path: str, services: list[str]) -> str:
    job_id = await _create_job("updateServicesJob", stack_name, services)
    asyncio.create_task(_run_update_services_job(job_id, stack_path, services))
    return job_id


async def _start_self_updater_container(stack_name: str, stack_path: str, services: list[str]) -> str:
    job_id = await _create_job("selfUpdate", stack_name, services)
    self_info = await _get_agent_self_info()
    updater_image = FLEETGE_UPDATER_IMAGE or self_info.get("image") or "ghcr.io/virgoooox/fleetge-agent:latest"
    stacks_host_path = self_info.get("stacks_host_path") or os.path.realpath(STACKS_BASE_DIR)
    stacks_container_path = self_info.get("stacks_container_path") or os.path.realpath(STACKS_BASE_DIR)
    job_status_path, _ = _job_paths(job_id)

    await _write_job_status(job_id, status="handoff", phase="starting-updater")
    await _append_job_log(job_id, f"Starting temporary updater container for services: {', '.join(services)}\n")

    container_name = f"fleetge-self-updater-{job_id}"
    cmd = [
        "run", "-d", "--rm",
        "--name", container_name,
        "-v", "/var/run/docker.sock:/var/run/docker.sock",
        "-v", f"{stacks_host_path}:{stacks_container_path}",
        "-e", f"STACKS_BASE_DIR={stacks_container_path}",
        updater_image,
        "python", "-m", "self_updater",
        "--job-id", job_id,
        "--stack-dir", stack_path,
        "--jobs-dir", os.path.dirname(job_status_path),
        "--services", *services,
    ]

    exit_code, output = await _run_docker_command_capture("/", cmd)
    await _append_job_log(job_id, output)
    if exit_code != 0:
        await _write_job_status(
            job_id,
            status="error",
            phase="start-updater-failed",
            exit_code=exit_code,
            finished_at=_utc_now_iso(),
        )
        raise HTTPException(status_code=502, detail=output.strip() or "Failed to start self-updater container")

    await _write_job_status(
        job_id,
        status="handoff",
        phase="updater-started",
        updater_container=container_name,
    )
    await _append_job_log(job_id, f"Temporary updater started: {container_name}\n")
    return job_id


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
        process = await asyncio.create_subprocess_exec(
            "docker", "compose", "ls", "--all", "--format", "json",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30.0)
    except Exception:
        return "unknown"

    if process.returncode != 0:
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
        process = await asyncio.create_subprocess_exec(
            "docker", *_compose_args(stack_path, "ps", "--format", "json"),
            cwd=stack_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30.0)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to inspect compose services: {exc}")

    if process.returncode != 0:
        detail = stderr.decode("utf-8", errors="replace").strip() or "docker compose ps failed"
        raise HTTPException(status_code=502, detail=detail)

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

    try:
        exit_code = await _stream_docker_command(
            websocket, "/", ["system", "prune", "-a", "-f"]
        )
        await websocket.send_json({"type": "exit", "code": exit_code})
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        import traceback
        traceback.print_exc()
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
            _compose_args(stack_path, "logs", "--no-color", "-f", "--tail", str(tail)),
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
            await websocket.send_json({
                "type": "error",
                "message": f"Invalid action '{action}'. Supported: {list(ACTION_ARGS.keys()) + sorted(special_actions)}"
            })
            await websocket.close()
            return

        # Acquire lock to prevent concurrent actions on the same stack
        lock = await get_stack_lock(name)
        if lock.locked():
            await websocket.send_json({
                "type": "error",
                "message": f"Another operation is already running for stack '{name}'."
            })
            await websocket.close()
            return

        async with lock:
            # Check compose file existence
            if _find_compose_file(stack_path) is None:
                await websocket.send_json({
                    "type": "error",
                    "message": f"No compose file found in stack '{name}'."
                })
                await websocket.close()
                return

            if action == "update":
                # 1) Pull latest images
                exit_code = await _stream_docker_command(
                    websocket, stack_path, _compose_args(stack_path, "pull"), cols=cols, rows=rows
                )
                if exit_code == 0 and await _get_compose_project_status(name) == "running":
                    # 2) Recreate running services with new images
                    exit_code = await _stream_docker_command(
                        websocket, stack_path, _compose_args(stack_path, "up", "-d", "--remove-orphans"), cols=cols, rows=rows
                    )
                await websocket.send_json({"type": "exit", "code": exit_code})
            elif action == "delete":
                exit_code = await _stream_docker_command(
                    websocket, stack_path, _compose_args(stack_path, "down", "--remove-orphans"), cols=cols, rows=rows
                )
                if exit_code == 0:
                    try:
                        await asyncio.to_thread(shutil.rmtree, stack_path)
                        await websocket.send_json({"type": "stdout", "chunk": f"\r\nStack '{name}' directory deleted.\r\n"})
                    except Exception as exc:
                        await websocket.send_json({"type": "error", "message": f"Failed to delete stack directory: {exc}"})
                        await websocket.close()
                        return
                await websocket.send_json({"type": "exit", "code": exit_code})
            elif action in service_actions:
                service_name = _validate_service_name(service)
                if action == "startService":
                    args = _compose_args(stack_path, "up", "-d", service_name)
                elif action == "stopService":
                    args = _compose_args(stack_path, "stop", service_name)
                else:
                    args = _compose_args(stack_path, "restart", service_name)
                exit_code = await _stream_docker_command(websocket, stack_path, args, cols=cols, rows=rows)
                await websocket.send_json({"type": "exit", "code": exit_code})
            elif action in service_update_actions:
                service_names = _validate_services(services)
                self_info = await _get_agent_self_info()
                is_self_stack = self_info.get("stack_name") == name
                self_service = self_info.get("service_name") or FLEETGE_AGENT_SERVICE
                if action != "selfUpdate" and is_self_stack and self_service in service_names:
                    await websocket.send_json({
                        "type": "error",
                        "message": "Refusing to update the current agent service without selfUpdate handoff.",
                    })
                    await websocket.close()
                    return

                if action == "updateServices":
                    exit_code = await _stream_docker_command(
                        websocket,
                        stack_path,
                        _compose_args(stack_path, "pull", *service_names),
                        cols=cols,
                        rows=rows,
                    )
                    if exit_code == 0:
                        exit_code = await _stream_docker_command(
                            websocket,
                            stack_path,
                            _compose_args(stack_path, "up", "-d", "--no-deps", *service_names),
                            cols=cols,
                            rows=rows,
                        )
                    await websocket.send_json({"type": "exit", "code": exit_code})
                elif action == "updateServicesJob":
                    job_id = await _start_update_services_job(name, stack_path, service_names)
                    await websocket.send_json({
                        "type": "job",
                        "job_id": job_id,
                        "message": f"Started Fleetge service update job {job_id}.",
                    })
                    await websocket.send_json({"type": "exit", "code": 0})
                else:
                    job_id = await _start_self_updater_container(name, stack_path, service_names)
                    await websocket.send_json({
                        "type": "job",
                        "job_id": job_id,
                        "message": f"Handed off Fleetge self-update to job {job_id}.",
                    })
                    await websocket.send_json({"type": "exit", "code": 0})
            else:
                args = _compose_args(stack_path, *ACTION_ARGS[action])
                exit_code = await _stream_docker_command(websocket, stack_path, args, cols=cols, rows=rows)
                await websocket.send_json({"type": "exit", "code": exit_code})

    except WebSocketDisconnect:
        # Client disconnected prematurely; any spawned process was already terminated
        # by _stream_docker_command before the exception propagated.
        pass
    except Exception as exc:
        import traceback
        traceback.print_exc()
        try:
            await websocket.send_json({"type": "error", "message": f"Unexpected execution error: {exc}"})
        except Exception:
            pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass
