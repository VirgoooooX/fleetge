import os
import re
import shutil
import asyncio
import json
from typing import Optional
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

STACKS_BASE_DIR = os.environ.get("STACKS_BASE_DIR", "/opt/stacks")

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
        exit_code = await _stream_docker_command(
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
        cols = data.get("cols", 160)
        rows = data.get("rows", 24)
        service_actions = {"startService", "stopService", "restartService"}
        special_actions = {"update", "delete"} | service_actions
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
