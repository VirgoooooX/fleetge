import os
import sys
import subprocess
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

# Mock settings before importing app
os.environ["AGENT_TOKEN"] = "test-secret-token"
os.environ["STACKS_BASE_DIR"] = "/tmp/test-stacks"

from main import app
import compose_runner

client = TestClient(app)


@pytest.fixture
def stack_base(monkeypatch, tmp_path):
    """Route stack storage into a temporary directory for a single test."""
    monkeypatch.setattr(compose_runner, "STACKS_BASE_DIR", str(tmp_path))
    return tmp_path


def test_unauthorized():
    """Ensure requests without valid token are blocked."""
    response = client.get("/api/agent/metrics")
    assert response.status_code == 401
    assert "Unauthorized" in response.json()["detail"]


def test_authorized_header():
    """Ensure standard Bearer token header works."""
    headers = {"Authorization": "Bearer test-secret-token"}
    response = client.get("/api/agent/health", headers=headers)
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_authorized_query_param():
    """Ensure token in query param fallback works."""
    response = client.get("/api/agent/health?token=test-secret-token")
    assert response.status_code == 200


def test_health_check_bypasses_auth():
    """Ensure health check is accessible without a token."""
    response = client.get("/api/agent/health")
    assert response.status_code == 200


def test_docker_only_get_allowed():
    """Ensure POST/PUT methods to docker proxy are forbidden (403 or 405)."""
    headers = {"Authorization": "Bearer test-secret-token"}
    
    # POST to a whitelisted path
    response = client.post("/api/agent/docker/containers/json", headers=headers)
    assert response.status_code in (403, 405)


def test_docker_whitelist_only():
    """Ensure non-whitelisted paths are rejected."""
    headers = {"Authorization": "Bearer test-secret-token"}
    
    # Try to access a path not in whitelist
    response = client.get("/api/agent/docker/containers/create", headers=headers)
    assert response.status_code == 403
    assert "not in the read-only whitelist" in response.json()["detail"]
    
    # Try to access a malicious path
    response = client.get("/api/agent/docker/containers/123/stop", headers=headers)
    assert response.status_code == 403


def test_path_traversal_blocked():
    """Ensure stack names with path traversal characters are blocked or resolved to 404."""
    headers = {"Authorization": "Bearer test-secret-token"}
    
    # Path traversal stack name: server path normalization resolves this outside route matching -> 404
    response = client.get("/api/agent/stacks/..%2Fsubfolder", headers=headers)
    assert response.status_code in (400, 404)

    # Traversal in name via raw dots resolves to 404
    response = client.get("/api/agent/stacks/../another-dir", headers=headers)
    assert response.status_code in (400, 404)


def test_invalid_stack_name_rejected():
    """Ensure stack names with invalid characters are rejected with 400."""
    headers = {"Authorization": "Bearer test-secret-token"}
    response = client.get("/api/agent/stacks/invalid$name", headers=headers)
    assert response.status_code == 400
    assert "Only lowercase letters" in response.json()["detail"]

    response = client.get("/api/agent/stacks/InvalidName", headers=headers)
    assert response.status_code == 400


def test_safe_stack_name():
    """Ensure a safe stack name gets processed normally (e.g. 404 if compose missing)."""
    headers = {"Authorization": "Bearer test-secret-token"}
    response = client.get("/api/agent/stacks/my-safe-stack", headers=headers)
    # my-safe-stack doesn't exist, should return 404, not 400 or 403
    assert response.status_code == 404
    assert "compose file not found" in response.json()["detail"]


def test_save_stack_cleans_up_old_compose_file(stack_base):
    """Saving with a different compose file name removes the old file."""
    stack_dir = stack_base / "test-stack"
    stack_dir.mkdir()
    old_file = stack_dir / "docker-compose.yml"
    old_file.write_text("version: '3'\n")

    headers = {"Authorization": "Bearer test-secret-token"}
    response = client.put(
        "/api/agent/stacks/test-stack",
        headers=headers,
        json={
            "compose_yaml": "services:\n  app:\n    image: nginx\n",
            "compose_file_name": "compose.yaml",
        },
    )

    assert response.status_code == 200
    assert not old_file.exists()
    new_file = stack_dir / "compose.yaml"
    assert new_file.exists()
    assert "image: nginx" in new_file.read_text()


def test_save_stack_rejects_invalid_compose_file_name(stack_base):
    """Only recognized compose file names are accepted."""
    headers = {"Authorization": "Bearer test-secret-token"}
    response = client.put(
        "/api/agent/stacks/test-stack",
        headers=headers,
        json={"compose_yaml": "x", "compose_file_name": "malicious.yml"},
    )
    assert response.status_code == 400


def test_save_stack_is_add_rejects_existing_stack(stack_base):
    """Creating a stack refuses to overwrite an existing directory."""
    stack_dir = stack_base / "test-stack"
    stack_dir.mkdir()
    headers = {"Authorization": "Bearer test-secret-token"}
    response = client.put(
        "/api/agent/stacks/test-stack",
        headers=headers,
        json={
            "compose_yaml": "services:\n  app:\n    image: nginx\n",
            "is_add": True,
        },
    )
    assert response.status_code == 409


def test_save_stack_edit_rejects_missing_stack(stack_base):
    """Editing a missing stack returns 404 instead of creating it silently."""
    headers = {"Authorization": "Bearer test-secret-token"}
    response = client.put(
        "/api/agent/stacks/missing-stack",
        headers=headers,
        json={"compose_yaml": "services:\n  app:\n    image: nginx\n"},
    )
    assert response.status_code == 404


def test_save_stack_rejects_invalid_yaml(stack_base):
    """Invalid compose YAML returns a clear validation error."""
    stack_dir = stack_base / "test-stack"
    stack_dir.mkdir()
    headers = {"Authorization": "Bearer test-secret-token"}
    response = client.put(
        "/api/agent/stacks/test-stack",
        headers=headers,
        json={"compose_yaml": "services:\n  app: [broken\n"},
    )
    assert response.status_code == 400
    assert "Invalid compose YAML" in response.json()["detail"]


def test_save_stack_rejects_single_line_env_without_equals(stack_base):
    """.env single-line content must be KEY=value."""
    stack_dir = stack_base / "test-stack"
    stack_dir.mkdir()
    headers = {"Authorization": "Bearer test-secret-token"}
    response = client.put(
        "/api/agent/stacks/test-stack",
        headers=headers,
        json={
            "compose_yaml": "services:\n  app:\n    image: nginx\n",
            "compose_env": "TOKEN_ONLY",
        },
    )
    assert response.status_code == 400
    assert "Invalid .env format" in response.json()["detail"]


def test_save_stack_writes_and_removes_env(stack_base):
    """.env is written when provided and removed when omitted."""
    stack_dir = stack_base / "test-stack"
    stack_dir.mkdir()
    headers = {"Authorization": "Bearer test-secret-token"}

    response = client.put(
        "/api/agent/stacks/test-stack",
        headers=headers,
        json={
            "compose_yaml": "services:\n  app:\n    image: nginx\n",
            "compose_env": "FOO=bar\n",
        },
    )
    assert response.status_code == 200
    env_file = stack_dir / ".env"
    assert env_file.exists()
    assert "FOO=bar" in env_file.read_text()

    response = client.put(
        "/api/agent/stacks/test-stack",
        headers=headers,
        json={"compose_yaml": "services:\n  app:\n    image: nginx\n"},
    )
    assert response.status_code == 200
    assert not env_file.exists()


def test_delete_stack_refuses_non_compose_directory(stack_base):
    """Deleting a directory with no compose file is rejected."""
    stack_dir = stack_base / "test-stack"
    stack_dir.mkdir()

    headers = {"Authorization": "Bearer test-secret-token"}
    response = client.delete("/api/agent/stacks/test-stack", headers=headers)
    assert response.status_code == 400
    assert "does not contain a compose file" in response.json()["detail"]
    assert stack_dir.exists()


def test_delete_stack_removes_directory(stack_base, monkeypatch):
    """Deleting a stack with a compose file removes the directory."""
    stack_dir = stack_base / "test-stack"
    stack_dir.mkdir()
    (stack_dir / "compose.yaml").write_text("services:\n  app:\n    image: nginx\n")
    calls = []

    async def fake_delete(path, args):
        calls.append((path, args))
        assert path == str(stack_dir)
        assert args == ["compose", "down", "--remove-orphans"]
        await compose_runner.asyncio.to_thread(compose_runner.shutil.rmtree, path)
        return 0, "down ok\n"

    monkeypatch.setattr(compose_runner, "_delete_stack_after_down", fake_delete)

    headers = {"Authorization": "Bearer test-secret-token"}
    response = client.delete("/api/agent/stacks/test-stack", headers=headers)
    assert response.status_code == 200
    assert not stack_dir.exists()
    assert len(calls) == 1


def test_delete_stack_down_failure_preserves_directory(stack_base, monkeypatch):
    """Deleting a stack keeps files if compose down fails."""
    stack_dir = stack_base / "test-stack"
    stack_dir.mkdir()
    (stack_dir / "compose.yaml").write_text("services:\n  app:\n    image: nginx\n")

    async def fake_delete(path, args):
        return 1, "down failed\n"

    monkeypatch.setattr(compose_runner, "_delete_stack_after_down", fake_delete)

    headers = {"Authorization": "Bearer test-secret-token"}
    response = client.delete("/api/agent/stacks/test-stack", headers=headers)
    assert response.status_code == 502
    assert "down failed" in response.json()["detail"]
    assert stack_dir.exists()


def test_global_env_read_write_delete(stack_base):
    """global.env can be saved, read, and removed."""
    headers = {"Authorization": "Bearer test-secret-token"}
    response = client.get("/api/agent/global-env", headers=headers)
    assert response.status_code == 200
    assert response.json()["content"] == ""

    response = client.put("/api/agent/global-env", headers=headers, json={"content": "TZ=Asia/Shanghai\n"})
    assert response.status_code == 200
    assert (stack_base / "global.env").read_text() == "TZ=Asia/Shanghai\n"

    response = client.get("/api/agent/global-env", headers=headers)
    assert response.status_code == 200
    assert response.json()["content"] == "TZ=Asia/Shanghai\n"

    response = client.put("/api/agent/global-env", headers=headers, json={"content": ""})
    assert response.status_code == 200
    assert not (stack_base / "global.env").exists()


def test_compose_args_match_dockge_env_file_order(stack_base):
    """global.env enables explicit env-file arguments in Dockge order."""
    stack_dir = stack_base / "test-stack"
    stack_dir.mkdir()
    (stack_dir / ".env").write_text("LOCAL=1\n")
    (stack_base / "global.env").write_text("GLOBAL=1\n")

    assert compose_runner._compose_args(str(stack_dir), "up", "-d", "--remove-orphans") == [
        "compose",
        "--env-file",
        "../global.env",
        "--env-file",
        "./.env",
        "up",
        "-d",
        "--remove-orphans",
    ]


def test_compose_status_convert_uses_dockge_precedence():
    """Partially exited stacks are treated as exited, not running."""
    assert compose_runner._compose_status_convert("running(2)") == "running"
    assert compose_runner._compose_status_convert("exited(1), running(1)") == "exited"
    assert compose_runner._compose_status_convert("created(1)") == "created"
    assert compose_runner._compose_status_convert("") == "unknown"


def test_update_runs_up_only_when_compose_project_is_running(stack_base, monkeypatch):
    """Dockge update behavior: pull first, then up only for running stacks."""
    stack_dir = stack_base / "running-stack"
    stack_dir.mkdir()
    (stack_dir / "compose.yaml").write_text("services:\n  app:\n    image: nginx\n")
    commands = []

    async def fake_stream(websocket, stack_path, args, cols=160, rows=24):
        commands.append(args)
        await websocket.send_json({"type": "stdout", "chunk": "ok\n"})
        return 0

    async def fake_status(name):
        assert name == "running-stack"
        return "running"

    monkeypatch.setattr(compose_runner, "_stream_docker_command", fake_stream)
    monkeypatch.setattr(compose_runner, "_get_compose_project_status", fake_status)

    with client.websocket_connect(
        "/api/agent/stacks/running-stack/execute?token=test-secret-token"
    ) as ws:
        ws.send_json({"action": "update"})
        assert ws.receive_json()["type"] == "stdout"
        assert ws.receive_json()["type"] == "stdout"
        exit_msg = ws.receive_json()
        assert exit_msg == {"type": "exit", "code": 0}

    assert commands == [
        ["compose", "pull"],
        ["compose", "up", "-d", "--remove-orphans"],
    ]


def test_update_skips_up_when_compose_project_is_not_running(stack_base, monkeypatch):
    """Dockge update behavior: stopped/exited stacks are pulled but not recreated."""
    stack_dir = stack_base / "stopped-stack"
    stack_dir.mkdir()
    (stack_dir / "compose.yaml").write_text("services:\n  app:\n    image: nginx\n")
    commands = []

    async def fake_stream(websocket, stack_path, args, cols=160, rows=24):
        commands.append(args)
        await websocket.send_json({"type": "stdout", "chunk": "ok\n"})
        return 0

    async def fake_status(name):
        assert name == "stopped-stack"
        return "exited"

    monkeypatch.setattr(compose_runner, "_stream_docker_command", fake_stream)
    monkeypatch.setattr(compose_runner, "_get_compose_project_status", fake_status)

    with client.websocket_connect(
        "/api/agent/stacks/stopped-stack/execute?token=test-secret-token"
    ) as ws:
        ws.send_json({"action": "update"})
        assert ws.receive_json()["type"] == "stdout"
        exit_msg = ws.receive_json()
        assert exit_msg == {"type": "exit", "code": 0}

    assert commands == [["compose", "pull"]]


@pytest.mark.parametrize(
    ("action", "expected"),
    [
        ("startService", ["compose", "up", "-d", "web"]),
        ("stopService", ["compose", "stop", "web"]),
        ("restartService", ["compose", "restart", "web"]),
    ],
)
def test_service_actions_generate_compose_args(stack_base, monkeypatch, action, expected):
    """Service-level actions route through _compose_args with the service name."""
    stack_dir = stack_base / "test-stack"
    stack_dir.mkdir()
    (stack_dir / "compose.yaml").write_text("services:\n  web:\n    image: nginx\n")
    commands = []

    async def fake_stream(websocket, stack_path, args, cols=160, rows=24):
        commands.append(args)
        await websocket.send_json({"type": "stdout", "chunk": "ok\n"})
        return 0

    monkeypatch.setattr(compose_runner, "_stream_docker_command", fake_stream)

    with client.websocket_connect(
        "/api/agent/stacks/test-stack/execute?token=test-secret-token"
    ) as ws:
        ws.send_json({"action": action, "service": "web"})
        assert ws.receive_json()["type"] == "stdout"
        assert ws.receive_json() == {"type": "exit", "code": 0}

    assert commands == [expected]


def test_compose_logs_stream_uses_compose_project_logs(stack_base, monkeypatch):
    """The stack log terminal follows docker compose logs, not container IDs."""
    stack_dir = stack_base / "test-stack"
    stack_dir.mkdir()
    (stack_dir / "compose.yaml").write_text("services:\n  web:\n    image: nginx\n")
    commands = []

    async def fake_stream(websocket, stack_path, args, cols=160, rows=24):
        commands.append(args)
        await websocket.send_json({"type": "stdout", "chunk": "web  | boot\n"})
        return 0

    monkeypatch.setattr(compose_runner, "_stream_docker_command", fake_stream)

    with client.websocket_connect(
        "/api/agent/stacks/test-stack/logs?tail=42&token=test-secret-token"
    ) as ws:
        assert ws.receive_json() == {"type": "ready"}
        assert ws.receive_json() == {"type": "stdout", "chunk": "web  | boot\n"}
        assert ws.receive_json() == {"type": "exit", "code": 0}

    assert commands == [["compose", "logs", "-f", "--tail", "42"]]


def test_websocket_invalid_action(stack_base):
    """Execute endpoint returns an error for unsupported actions."""
    stack_dir = stack_base / "test-stack"
    stack_dir.mkdir()
    (stack_dir / "compose.yaml").write_text("services:\n  app:\n    image: nginx\n")

    with client.websocket_connect(
        "/api/agent/stacks/test-stack/execute?token=test-secret-token"
    ) as ws:
        ws.send_json({"action": "not-an-action"})
        msg = ws.receive_json()
        assert msg["type"] == "error"
        assert "Invalid action" in msg["message"]


def test_empty_agent_token_warns_on_stderr():
    """Importing the app with an empty token prints a warning to stderr."""
    env = os.environ.copy()
    env.pop("AGENT_TOKEN", None)
    env.pop("AGENT_REQUIRE_TOKEN", None)
    result = subprocess.run(
        [sys.executable, "-c", "import main"],
        cwd=Path(__file__).parent,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "AGENT_TOKEN is not set" in result.stderr


def test_agent_require_token_empty_exits():
    """AGENT_REQUIRE_TOKEN=true with an empty token exits with an error."""
    env = os.environ.copy()
    env.pop("AGENT_TOKEN", None)
    env["AGENT_REQUIRE_TOKEN"] = "true"
    result = subprocess.run(
        [sys.executable, "-c", "import main"],
        cwd=Path(__file__).parent,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "AGENT_REQUIRE_TOKEN=true but AGENT_TOKEN is empty" in result.stderr
