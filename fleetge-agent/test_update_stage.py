import pytest

from test_agent import client, stack_base
import compose_runner


@pytest.mark.parametrize("pull_code,up_code,expected_stage", [(1, 0, "pull"), (0, 2, "up"), (0, 0, "up")])
def test_update_reports_failure_stage_without_changing_sequence(stack_base, monkeypatch, pull_code, up_code, expected_stage):
    folder = stack_base / "stage-test"
    folder.mkdir()
    (folder / "compose.yaml").write_text("services:\n  app:\n    image: example/app\n")
    commands = []

    async def stream(websocket, stack_path, args, **kwargs):
        commands.append(args)
        return pull_code if args == ["compose", "pull"] else up_code

    async def status(name):
        return "running"

    monkeypatch.setattr(compose_runner, "_stream_docker_command", stream)
    monkeypatch.setattr(compose_runner, "_get_compose_project_status", status)
    with client.websocket_connect("/api/agent/stacks/stage-test/execute?token=test-secret-token-0123456789abcdef") as ws:
        ws.send_json({"action": "update"})
        result = ws.receive_json()
    assert result["stage"] == expected_stage
    assert result["code"] == (pull_code or up_code)
    assert result["up_executed"] is (pull_code == 0)
    assert commands == ([["compose", "pull"]] if pull_code else [["compose", "pull"], ["compose", "up", "-d", "--remove-orphans"]])


def test_capture_only_selected_service_ignores_unrelated_build(monkeypatch):
    import json
    from types import SimpleNamespace
    from unittest.mock import Mock
    from compose_identity import capture_pulled_images
    run = Mock(side_effect=[
        SimpleNamespace(returncode=0, stdout=json.dumps({"services": {
            "local": {"build": "."}, "db": {"image": "postgres:16-alpine"},
        }})),
        SimpleNamespace(returncode=0, stdout=json.dumps([{
            "Id": "sha256:new", "Os": "linux", "Architecture": "amd64", "RepoDigests": [],
        }])),
    ])
    monkeypatch.setattr("compose_identity.subprocess.run", run)
    targets = capture_pulled_images("/stack", ["compose", "config", "--format", "json"], ["db"])
    assert [target["service"] for target in targets] == ["db"]
    assert run.call_count == 2
    assert run.call_args.args[0] == ["docker", "image", "inspect", "postgres:16-alpine"]


@pytest.mark.parametrize("exit_code,stage,up_executed", [(1, "pull", False), (0, "up", True)])
def test_selected_update_reports_stage_and_evidence(stack_base, monkeypatch, exit_code, stage, up_executed):
    from unittest.mock import AsyncMock
    folder = stack_base / "selected"
    folder.mkdir()
    (folder / "compose.yaml").write_text("services:\n  db:\n    image: postgres:16-alpine\n")
    commands = []
    async def stream(websocket, stack_path, args, **kwargs):
        commands.append(args)
        return exit_code if "pull" in args else 0
    monkeypatch.setattr(compose_runner, "_stream_docker_command", stream)
    monkeypatch.setattr(compose_runner, "_get_agent_self_info", AsyncMock(return_value={"stack_name": "fleetge"}))
    monkeypatch.setattr(compose_runner, "_selected_services_running", AsyncMock(return_value=True))
    capture = AsyncMock(return_value=[{"service": "db", "image": "postgres:16-alpine", "image_id": "sha256:new", "platform": "linux/amd64"}])
    monkeypatch.setattr(compose_runner, "_capture_pulled_images", capture)
    with client.websocket_connect("/api/agent/stacks/selected/execute?token=test-secret-token-0123456789abcdef") as ws:
        ws.send_json({"action": "updateServices", "services": ["db"]})
        result = ws.receive_json()
    assert result["stage"] == stage
    assert result["up_executed"] == up_executed
    assert commands[0] == ["compose", "pull", "db"]
    if exit_code:
        assert len(commands) == 1
        capture.assert_not_awaited()
    else:
        assert commands[1] == ["compose", "up", "-d", "--no-deps", "--pull", "never", "db"]
        assert result["pulled_images"][0]["service"] == "db"


def test_selected_service_status_ignores_unrelated_failure(monkeypatch):
    from unittest.mock import AsyncMock
    monkeypatch.setattr(compose_runner, "_get_compose_services", AsyncMock(return_value=[
        {"Service": "app", "State": "exited"}, {"Service": "db", "State": "running"},
    ]))
    assert compose_runner.asyncio.run(compose_runner._selected_services_running("/stack", ["db"]))
    assert not compose_runner.asyncio.run(compose_runner._selected_services_running("/stack", ["app"]))


def test_config_failure_exposes_redacted_stderr_without_resolved_environment(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock
    from compose_identity import capture_pulled_images
    monkeypatch.setattr("compose_identity.subprocess.run", Mock(return_value=SimpleNamespace(
        returncode=1, stdout='{"environment":{"PASSWORD":"stdout-secret"}}',
        stderr='env file /host/metarail.env not found\nAPI_TOKEN="private value" PASSWORD=hidden https://user:pass@registry.invalid',
    )))
    with pytest.raises(RuntimeError) as error:
        capture_pulled_images("/stack", ["compose", "config", "--format", "json"], ["db"])
    message = str(error.value)
    assert "/host/metarail.env not found" in message
    assert "exit 1" in message
    assert "stdout-secret" not in message
    assert "private value" not in message
    assert "hidden" not in message
    assert "user:pass" not in message


def test_target_capture_error_reports_target_stage_and_does_not_recreate(stack_base, monkeypatch):
    from unittest.mock import AsyncMock
    folder = stack_base / "target-error"
    folder.mkdir()
    (folder / "compose.yaml").write_text("services:\n  db:\n    image: postgres:16-alpine\n")
    commands = []
    async def stream(websocket, stack_path, args, **kwargs):
        commands.append(args)
        return 0
    monkeypatch.setattr(compose_runner, "_stream_docker_command", stream)
    monkeypatch.setattr(compose_runner, "_get_agent_self_info", AsyncMock(return_value={"stack_name": "fleetge"}))
    monkeypatch.setattr(compose_runner, "_capture_pulled_images", AsyncMock(side_effect=RuntimeError(
        "Could not resolve the effective Compose service configuration: env file /host/metarail.env not found"
    )))
    with client.websocket_connect("/api/agent/stacks/target-error/execute?token=test-secret-token-0123456789abcdef") as ws:
        ws.send_json({"action": "updateServices", "services": ["db"]})
        result = ws.receive_json()
    assert result["type"] == "error"
    assert result["stage"] == "target"
    assert result["up_executed"] is False
    assert "/host/metarail.env not found" in result["message"]
    assert commands == [["compose", "pull", "db"]]
