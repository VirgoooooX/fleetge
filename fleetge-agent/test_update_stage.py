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
