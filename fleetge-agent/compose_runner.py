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

# Safe regex pattern to match stack name. Only allows letters, numbers, underscores, and hyphens.
STACK_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]+$")

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


def _validate_stack_name(name: str) -> None:
    """Ensure stack name is safe and does not contain path traversal characters."""
    if not STACK_NAME_RE.match(name):
        raise HTTPException(
            status_code=400,
            detail="Invalid stack name. Only alphanumeric characters, hyphens, and underscores are allowed."
        )


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
    if not stack_real.startswith(base_real) or stack_real == base_real:
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
    os.makedirs(stack_path, exist_ok=True)

    compose_filename = _validate_compose_file_name(payload.compose_file_name)
    compose_path = os.path.join(stack_path, compose_filename)
    env_path = os.path.join(stack_path, ".env")

    try:
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
            shutil.rmtree(stack_path)
            return {"success": True, "message": f"Stack '{name}' deleted successfully."}
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Failed to delete stack directory: {exc}")


# Action to Docker Compose argument mapping
ACTION_ARGS = {
    "up": ["compose", "up", "-d", "--remove-orphans"],
    "down": ["compose", "down"],
    "restart": ["compose", "restart"],
    "pull": ["compose", "pull"],
}


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
            dimensions=(24, 160),
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


async def _has_running_services(stack_path: str) -> bool:
    """Return True if the stack has any container in the running state."""
    try:
        process = await asyncio.create_subprocess_exec(
            "docker", "compose", "ps", "--format", "json",
            cwd=stack_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30.0)
    except Exception:
        return False

    if process.returncode != 0:
        return False

    text = stdout.decode("utf-8", errors="replace").strip()
    if not text:
        return False

    # docker compose ps may emit a JSON array or one JSON object per line
    try:
        services = json.loads(text)
        if isinstance(services, dict):
            services = [services]
    except json.JSONDecodeError:
        services = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                services.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    for service in services:
        if isinstance(service, dict) and service.get("State") == "running":
            return True

    return False


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
        if action not in ACTION_ARGS and action != "update":
            await websocket.send_json({
                "type": "error",
                "message": f"Invalid action '{action}'. Supported: {list(ACTION_ARGS.keys()) + ['update']}"
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
                exit_code = await _stream_docker_command(websocket, stack_path, ["compose", "pull"])
                if exit_code == 0 and await _has_running_services(stack_path):
                    # 2) Recreate running services with new images
                    exit_code = await _stream_docker_command(
                        websocket, stack_path, ["compose", "up", "-d", "--remove-orphans"]
                    )
                await websocket.send_json({"type": "exit", "code": exit_code})
            else:
                args = ACTION_ARGS[action]
                exit_code = await _stream_docker_command(websocket, stack_path, args)
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
