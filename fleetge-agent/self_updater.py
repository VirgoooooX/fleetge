"""Detached Fleetge self-updater.

This module runs in a short-lived container that is not part of the Fleetge
compose project. It can recreate the agent service without killing the process
that is executing the update.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import datetime, timezone


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def job_paths(jobs_dir: str, job_id: str) -> tuple[str, str]:
    os.makedirs(jobs_dir, exist_ok=True)
    base = os.path.join(jobs_dir, job_id)
    return f"{base}.json", f"{base}.log"


def write_status(jobs_dir: str, job_id: str, **updates) -> None:
    status_path, _ = job_paths(jobs_dir, job_id)
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
    current["updated_at"] = utc_now()
    tmp_path = f"{status_path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(current, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, status_path)


def append_log(jobs_dir: str, job_id: str, text: str) -> None:
    _, log_path = job_paths(jobs_dir, job_id)
    with open(log_path, "a", encoding="utf-8", errors="replace") as f:
        f.write(text)


def compose_args(stack_dir: str, command: str, *extra: str) -> list[str]:
    args = ["compose", command, *extra]
    base_dir = os.path.realpath(os.path.dirname(stack_dir))
    global_env_path = os.path.join(base_dir, "global.env")
    if os.path.isfile(global_env_path):
        if os.path.isfile(os.path.join(stack_dir, ".env")):
            args[1:1] = ["--env-file", "./.env"]
        args[1:1] = ["--env-file", "../global.env"]
    return args


def run_command(jobs_dir: str, job_id: str, stack_dir: str, args: list[str]) -> int:
    append_log(jobs_dir, job_id, f"\n$ docker {' '.join(args)}\n")
    try:
        proc = subprocess.Popen(
            ["docker", *args],
            cwd=stack_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except Exception as exc:
        append_log(jobs_dir, job_id, f"Failed to start docker command: {exc}\n")
        return 1

    assert proc.stdout is not None
    for line in proc.stdout:
        append_log(jobs_dir, job_id, line)
    code = proc.wait()
    append_log(jobs_dir, job_id, f"\nCommand exited with code {code}\n")
    return code


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--stack-dir", required=True)
    parser.add_argument("--jobs-dir", required=True)
    parser.add_argument("--services", nargs="+", required=True)
    args = parser.parse_args()

    stack_dir = os.path.realpath(args.stack_dir)
    services = list(args.services)
    write_status(
        args.jobs_dir,
        args.job_id,
        status="running",
        phase="pull",
        stack_path=stack_dir,
        services=services,
    )
    append_log(args.jobs_dir, args.job_id, "Self-updater container started.\n")

    exit_code = run_command(
        args.jobs_dir,
        args.job_id,
        stack_dir,
        compose_args(stack_dir, "pull", *services),
    )
    if exit_code == 0:
        write_status(args.jobs_dir, args.job_id, status="running", phase="up")
        exit_code = run_command(
            args.jobs_dir,
            args.job_id,
            stack_dir,
            compose_args(stack_dir, "up", "-d", "--no-deps", *services),
        )

    if exit_code == 0:
        write_status(
            args.jobs_dir,
            args.job_id,
            status="success",
            phase="done",
            exit_code=0,
            finished_at=utc_now(),
        )
        append_log(args.jobs_dir, args.job_id, "\nSelf-update completed successfully.\n")
    else:
        write_status(
            args.jobs_dir,
            args.job_id,
            status="error",
            phase="failed",
            exit_code=exit_code,
            finished_at=utc_now(),
        )
        append_log(args.jobs_dir, args.job_id, f"\nSelf-update failed with exit code {exit_code}.\n")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
