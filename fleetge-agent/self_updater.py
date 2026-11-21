"""Detached Fleetge self-updater.

This module runs in a short-lived container that is not part of the Fleetge
compose project. It can recreate the agent service without killing the process
that is executing the update.
"""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import threading
from contextlib import suppress

from compose_identity import capture_pulled_images

from compose_common import SERVICE_NAME_RE as _SERVICE_NAME_RE, compose_args as build_compose_args
from job_store import append_log as append_job_log, job_paths, utc_now, write_status


def _validate_services(services: list[str]) -> list[str]:
    for svc in services:
        if ".." in svc or not _SERVICE_NAME_RE.match(svc):
            raise ValueError(f"Invalid service name: {svc!r}")
    return services


def append_log(jobs_dir: str, job_id: str, text: str) -> None:
    _, log_path = job_paths(jobs_dir, job_id)
    append_job_log(log_path, text)


def compose_args(
    stack_dir: str,
    command: str,
    *extra: str,
    host_project_dir: str = "",
    compose_file: str = "",
) -> list[str]:
    return build_compose_args(
        stack_dir, command, *extra,
        base_dir=os.path.dirname(stack_dir),
        host_project_dir=host_project_dir,
        compose_file=compose_file,
    )


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
            start_new_session=os.name == "posix",
        )
    except Exception as exc:
        append_log(jobs_dir, job_id, f"Failed to start docker command: {exc}\n")
        return 1

    assert proc.stdout is not None
    timed_out = threading.Event()

    def kill() -> None:
        with suppress(ProcessLookupError):
            if os.name == "posix":
                os.killpg(proc.pid, signal.SIGKILL)
            elif proc.poll() is None:
                proc.kill()

    def kill_on_timeout() -> None:
        timed_out.set()
        kill()

    timer = threading.Timer(600.0, kill_on_timeout)
    timer.start()
    try:
        with proc.stdout as output:
            for line in output:
                append_log(jobs_dir, job_id, line)
        code = proc.wait()
    except BaseException:
        kill()
        proc.wait()
        raise
    finally:
        timer.cancel()
        timer.join()
    if timed_out.is_set():
        append_log(jobs_dir, job_id, "\nDocker command timed out after 600 seconds.\n")
        return 124
    append_log(jobs_dir, job_id, f"\nCommand exited with code {code}\n")
    return code


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--stack-dir", required=True)
    parser.add_argument("--jobs-dir", required=True)
    parser.add_argument("--services", nargs="+", required=True)
    parser.add_argument("--host-project-dir", default="")
    parser.add_argument("--compose-file", default="")
    args = parser.parse_args()

    stack_dir = os.path.realpath(args.stack_dir)
    host_project_dir = os.path.realpath(args.host_project_dir) if args.host_project_dir else ""
    compose_file = os.path.realpath(args.compose_file) if args.compose_file else ""
    services = _validate_services(list(args.services))
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
        compose_args(stack_dir, "pull", *services, host_project_dir=host_project_dir, compose_file=compose_file),
    )
    stage = "pull"
    pulled_images: list[dict] = []
    if exit_code == 0:
        stage = "target"
        try:
            pulled_images = capture_pulled_images(
                stack_dir,
                compose_args(stack_dir, "config", "--format", "json", host_project_dir=host_project_dir, compose_file=compose_file),
                services,
            )
            pulled_images = [item for item in pulled_images if item.get("service") in services]
            if len(pulled_images) != len(services):
                raise RuntimeError("Could not resolve every requested service image.")
            write_status(args.jobs_dir, args.job_id, pulled_images=pulled_images, up_executed=False)
        except Exception as exc:
            write_status(
                args.jobs_dir,
                args.job_id,
                status="error",
                phase="target",
                message=str(exc),
                finished_at=utc_now(),
            )
            append_log(args.jobs_dir, args.job_id, f"\n{exc}\n")
            return 1
        stage = "up"
        write_status(args.jobs_dir, args.job_id, status="running", phase=stage, up_executed=True)
        exit_code = run_command(
            args.jobs_dir,
            args.job_id,
            stack_dir,
            compose_args(
                stack_dir,
                "up",
                "-d",
                "--no-deps",
                "--pull",
                "never",
                *services,
                host_project_dir=host_project_dir,
                compose_file=compose_file,
            ),
        )

    if exit_code == 124:
        write_status(
            args.jobs_dir,
            args.job_id,
            status="uncertain",
            phase="uncertain",
            message=f"Docker {stage} command timed out; result is unknown.",
            finished_at=utc_now(),
        )
    elif exit_code == 0:
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
            phase=stage,
            exit_code=exit_code,
            finished_at=utc_now(),
        )
        append_log(args.jobs_dir, args.job_id, f"\nSelf-update failed with exit code {exit_code}.\n")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
