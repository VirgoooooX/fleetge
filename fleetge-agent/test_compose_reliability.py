import asyncio
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi import WebSocketDisconnect

import compose_common
import job_store
import pty_executor


def test_concurrent_status_updates_and_stale_handoff(tmp_path):
    jobs_dir = str(tmp_path)
    job_id = "fast-updater"
    job_store.write_status(jobs_dir, job_id, status="running", phase="pull")
    with ThreadPoolExecutor(max_workers=4) as writers:
        writes = [writers.submit(job_store.write_status, jobs_dir, job_id, **{f"field_{n}": n}) for n in range(8)]
        for write in writes:
            write.result()
    job_store.write_status(jobs_dir, job_id, status="success", phase="done", finished_at="completed")
    job_store.write_status(jobs_dir, job_id, status="uncertain", phase="uncertain", finished_at="later")
    job_store.write_status(jobs_dir, job_id, status="handoff", updater_container="fleetge-updater")
    state = job_store.read_status(tmp_path / f"{job_id}.json")
    assert [state[f"field_{n}"] for n in range(8)] == list(range(8))
    assert (state["status"], state["phase"], state["finished_at"]) == ("success", "done", "completed")
    assert state["updater_container"] == "fleetge-updater"


def test_retention_removes_only_old_terminal_jobs(tmp_path):
    now = time.time()
    expired = now - job_store.JOB_RETENTION_SECONDS - 10
    for job_id, status in [("expired", "success"), ("recent", "error"), ("active", "running")]:
        status_path, log_path = job_store.job_paths(str(tmp_path), job_id)
        job_store.write_status(str(tmp_path), job_id, status=status)
        job_store.append_log(log_path, f"{job_id}\n")
        if job_id != "recent":
            os.utime(status_path, (expired, expired))
    (tmp_path / "corrupt.json").write_text("invalid json", encoding="utf-8")
    os.utime(tmp_path / "corrupt.json", (expired, expired))

    job_store.prune_finished_jobs(str(tmp_path), now=now)

    assert {path.name for path in tmp_path.iterdir() if path.suffix} == {
        "recent.json", "recent.log", "active.json", "active.log", "corrupt.json",
    }


def test_stack_file_commit_restores_earlier_file_if_later_replace_fails(tmp_path, monkeypatch):
    compose = tmp_path / "compose.yaml"
    env = tmp_path / ".env"
    compose.write_text("original compose", encoding="utf-8")
    env.write_text("original environment", encoding="utf-8")
    real_replace = os.replace

    def replace(src, dst):
        if dst == str(env):
            raise PermissionError("simulated replace failure")
        return real_replace(src, dst)

    monkeypatch.setattr(compose_common.os, "replace", replace)
    with compose_common.staged_text(str(compose), "new compose") as compose_write:
        with compose_common.staged_text(str(env), "new environment") as env_write:
            with pytest.raises(PermissionError):
                compose_common.commit_stack_files([compose_write, env_write])

    assert compose.read_text(encoding="utf-8") == "original compose"
    assert env.read_text(encoding="utf-8") == "original environment"
    assert set(tmp_path.iterdir()) == {compose, env}


@pytest.fixture
def quiet_command(monkeypatch):
    processes = []

    async def spawn(*_args, stderr, **_kwargs):
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-c", "import time; time.sleep(60)",
            stdout=subprocess.PIPE, stderr=stderr, start_new_session=os.name == "posix",
        )
        processes.append(proc)
        return proc

    monkeypatch.setattr(pty_executor, "spawn_docker", spawn)
    return processes


def test_capture_timeout_reaps_quiet_process(quiet_command):
    async def check():
        with pytest.raises(TimeoutError):
            await pty_executor.capture_docker(["test"], timeout=0.05)
        assert quiet_command[0].returncode is not None

    asyncio.run(check())


def test_log_stream_reaps_quiet_process_on_disconnect(quiet_command):
    class DisconnectedSocket:
        async def receive(self):
            return {"type": "websocket.disconnect"}

    async def check():
        with pytest.raises(WebSocketDisconnect):
            await asyncio.wait_for(
                pty_executor.stream_with_subprocess(DisconnectedSocket(), str(Path.cwd()), ["test"]),
                timeout=3,
            )
        assert quiet_command[0].returncode is not None

    asyncio.run(check())


def test_job_log_redacts_authorization_bearer_value(tmp_path):
    log = tmp_path / "job.log"
    job_store.append_log(str(log), "Authorization: Bearer example-token\n")
    assert log.read_text(encoding="utf-8") == "Authorization: [REDACTED]\n"
