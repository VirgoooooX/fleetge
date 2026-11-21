"""Convert common Docker run options into a Compose draft."""

import shlex
from typing import Any

from fastapi import HTTPException


def convert_docker_run_to_compose(command: str) -> str:
    """Small v1 docker-run-to-compose converter for common flags."""
    try:
        tokens = shlex.split(command)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid docker run command: {exc}")

    if len(tokens) >= 2 and tokens[0] == "docker" and tokens[1] == "run":
        tokens = tokens[2:]
    elif tokens and tokens[0] == "run":
        tokens = tokens[1:]
    else:
        raise HTTPException(status_code=400, detail="Command must start with 'docker run' or 'run'")

    service: dict[str, Any] = {}
    ports: list[str] = []
    volumes: list[str] = []
    env: list[str] = []
    image = ""
    cmd: list[str] = []

    flag_value = {
        "--name", "--restart", "--network", "--hostname", "--user", "--workdir",
        "-p", "--publish", "-v", "--volume", "-e", "--env",
    }
    bool_flags = {"-d", "--detach", "--rm", "--privileged"}

    i = 0
    while i < len(tokens):
        token = tokens[i]
        if image:
            cmd.append(token)
            i += 1
            continue

        key = token
        value: str | None = None
        if token.startswith("--") and "=" in token:
            key, value = token.split("=", 1)
        elif token in flag_value:
            i += 1
            if i >= len(tokens):
                raise HTTPException(status_code=400, detail=f"Missing value for {token}")
            value = tokens[i]

        if key in ("--name",):
            service["container_name"] = value
        elif key in ("--restart",):
            service["restart"] = value
        elif key in ("--network",):
            service["network_mode"] = value
        elif key in ("--hostname",):
            service["hostname"] = value
        elif key in ("--user",):
            service["user"] = value
        elif key in ("--workdir",):
            service["working_dir"] = value
        elif key in ("-p", "--publish"):
            ports.append(value or "")
        elif key in ("-v", "--volume"):
            volumes.append(value or "")
        elif key in ("-e", "--env"):
            env.append(value or "")
        elif key in bool_flags:
            if key == "--privileged":
                service["privileged"] = True
            # -d and --rm do not map cleanly for persistent compose stacks.
        elif token.startswith("-"):
            raise HTTPException(status_code=400, detail=f"Unsupported docker run flag: {token}")
        else:
            image = token
        i += 1

    if not image:
        raise HTTPException(status_code=400, detail="Docker image is required")

    service["image"] = image
    if ports:
        service["ports"] = ports
    if volumes:
        service["volumes"] = volumes
    if env:
        service["environment"] = env
    if cmd:
        service["command"] = cmd

    service_name = service.get("container_name") or image.split("/")[-1].split(":")[0] or "app"
    service_name = "".join(ch if ch.isalnum() or ch in "_-" else "-" for ch in service_name.lower()).strip("-") or "app"

    try:
        import yaml
        return yaml.safe_dump(
            {"services": {service_name: service}},
            sort_keys=False,
            allow_unicode=True,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to render compose YAML: {exc}")
