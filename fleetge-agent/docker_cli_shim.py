#!/usr/bin/env python3
"""Lightweight Docker Socket client and /usr/local/bin/docker shim.

Replaces the 40.4 MB `/usr/local/bin/docker` binary inside the agent image:
- `docker compose ...` execs `/usr/local/bin/docker-compose ...` directly.
- `inspect`, `ps`, `exec`, `run -d`, and `system prune` talk directly to
  `/var/run/docker.sock` over HTTP, avoiding the standalone Docker CLI binary.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from urllib.parse import quote

import httpx

from docker_client import _DockerLogDemuxer


def _make_sync_client(timeout: float = 30.0) -> httpx.Client:
    docker_host = os.environ.get("DOCKER_HOST", "").strip()
    if docker_host:
        if docker_host.startswith("tcp://"):
            return httpx.Client(base_url=docker_host.replace("tcp://", "http://"), timeout=timeout)
        if docker_host.startswith("unix://"):
            uds = docker_host.replace("unix://", "")
            return httpx.Client(transport=httpx.HTTPTransport(uds=uds), base_url="http://localhost", timeout=timeout)
        return httpx.Client(base_url=docker_host, timeout=timeout)
    if sys.platform == "win32":
        return httpx.Client(base_url="http://127.0.0.1:2375", timeout=timeout)
    return httpx.Client(
        transport=httpx.HTTPTransport(uds="/var/run/docker.sock"),
        base_url="http://localhost",
        timeout=timeout,
    )


def inspect_object(kind: str, target: str, timeout: float = 15.0) -> dict | None:
    encoded = quote(target, safe="")
    path = f"/images/{encoded}/json" if kind == "image" else f"/containers/{encoded}/json"
    with _make_sync_client(timeout=timeout) as client:
        resp = client.get(path)
        if resp.status_code == 200:
            data = resp.json()
            return data if isinstance(data, dict) else None
        if kind == "any":
            resp_img = client.get(f"/images/{encoded}/json")
            if resp_img.status_code == 200:
                data = resp_img.json()
                return data if isinstance(data, dict) else None
    return None


def _cmd_inspect(kind: str, argv: list[str]) -> int:
    fmt = ""
    targets: list[str] = []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg in ("-f", "--format") and i + 1 < len(argv):
            fmt = argv[i + 1]
            i += 2
            continue
        if arg.startswith("--format="):
            fmt = arg.split("=", 1)[1]
            i += 1
            continue
        if arg.startswith("-"):
            i += 1
            continue
        targets.append(arg)
        i += 1

    if not targets:
        sys.stderr.write("docker inspect requires at least 1 argument\n")
        return 1

    results: list[dict] = []
    for target in targets:
        info = inspect_object(kind, target)
        if info is None:
            sys.stderr.write(f"Error: No such object: {target}\n")
            return 1
        results.append(info)

    if fmt == "{{.State.Running}}":
        for item in results:
            running = bool((item.get("State") or {}).get("Running"))
            sys.stdout.write("true\n" if running else "false\n")
        return 0

    sys.stdout.write(json.dumps(results) + "\n")
    return 0


def _cmd_ps(argv: list[str]) -> int:
    quiet = False
    all_containers = False
    filters: dict[str, list[str]] = {}
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg in ("-q", "--quiet"):
            quiet = True
            i += 1
        elif arg in ("-a", "--all"):
            all_containers = True
            i += 1
        elif arg in ("-f", "--filter") and i + 1 < len(argv):
            fval = argv[i + 1]
            if "=" in fval:
                k, v = fval.split("=", 1)
                filters.setdefault(k, []).append(v)
            i += 2
        elif arg.startswith("--filter="):
            fval = arg.split("=", 1)[1]
            if "=" in fval:
                k, v = fval.split("=", 1)
                filters.setdefault(k, []).append(v)
            i += 1
        else:
            i += 1

    params: dict[str, str] = {}
    if all_containers:
        params["all"] = "true"
    if filters:
        params["filters"] = json.dumps(filters)

    with _make_sync_client() as client:
        resp = client.get("/containers/json", params=params)
        if resp.status_code != 200:
            sys.stderr.write(resp.text + "\n")
            return 1
        items = resp.json()

    for item in items if isinstance(items, list) else []:
        cid = str(item.get("Id") or "")
        if quiet:
            sys.stdout.write(cid[:12] + "\n")
        else:
            sys.stdout.write(cid + "\n")
    return 0


def _cmd_exec(argv: list[str]) -> int:
    i = 0
    while i < len(argv) and argv[i].startswith("-"):
        i += 1
    if i + 1 >= len(argv):
        sys.stderr.write("docker exec requires container and command\n")
        return 1
    container_id = argv[i]
    cmd = argv[i + 1 :]

    with _make_sync_client(timeout=15.0) as client:
        create_resp = client.post(
            f"/containers/{quote(container_id, safe='')}/exec",
            json={
                "AttachStdout": True,
                "AttachStderr": True,
                "Tty": False,
                "Cmd": cmd,
            },
        )
        if create_resp.status_code >= 300:
            sys.stderr.write(create_resp.text + "\n")
            return 1
        exec_id = create_resp.json().get("Id")
        start_resp = client.post(f"/exec/{exec_id}/start", json={"Detach": False, "Tty": False})
        if start_resp.status_code >= 300:
            sys.stderr.write(start_resp.text + "\n")
            return 1
        demux = _DockerLogDemuxer()
        chunks = demux.feed(start_resp.content)
        tail = demux.flush()
        if tail:
            chunks.append(tail)
        sys.stdout.buffer.write(b"".join(chunks))
        sys.stdout.buffer.flush()

        inspect_resp = client.get(f"/exec/{exec_id}/json")
        if inspect_resp.status_code == 200:
            return int(inspect_resp.json().get("ExitCode") or 0)
    return 0


def _cmd_run(argv: list[str]) -> int:
    auto_remove = False
    name = ""
    binds: list[str] = []
    envs: list[str] = []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg in ("-d", "--detach"):
            i += 1
        elif arg == "--rm":
            auto_remove = True
            i += 1
        elif arg == "--name" and i + 1 < len(argv):
            name = argv[i + 1]
            i += 2
        elif arg in ("-v", "--volume") and i + 1 < len(argv):
            binds.append(argv[i + 1])
            i += 2
        elif arg in ("-e", "--env") and i + 1 < len(argv):
            envs.append(argv[i + 1])
            i += 2
        elif arg.startswith("-"):
            i += 1
        else:
            break

    if i >= len(argv):
        sys.stderr.write("docker run requires an image\n")
        return 1

    image = argv[i]
    cmd = argv[i + 1 :]
    params = {"name": name} if name else {}
    body = {
        "Image": image,
        "Cmd": cmd,
        "Env": envs,
        "HostConfig": {
            "Binds": binds,
            "AutoRemove": auto_remove,
        },
    }
    with _make_sync_client(timeout=60.0) as client:
        create_resp = client.post("/containers/create", params=params, json=body)
        if create_resp.status_code >= 300:
            sys.stderr.write(create_resp.text + "\n")
            return 1
        cid = create_resp.json().get("Id")
        start_resp = client.post(f"/containers/{cid}/start")
        if start_resp.status_code >= 300:
            sys.stderr.write(start_resp.text + "\n")
            return 1
        sys.stdout.write(f"{cid}\n")
    return 0


def _format_bytes(num: int) -> str:
    value = float(max(0, num))
    for unit in ("B", "kB", "MB", "GB", "TB"):
        if value < 1000.0 or unit == "TB":
            return f"{int(value)}B" if unit == "B" else f"{value:.2f}{unit}"
        value /= 1000.0
    return f"{value:.2f}TB"


def _cmd_system_prune() -> int:
    reclaimed = 0
    with _make_sync_client(timeout=300.0) as client:
        c_resp = client.post("/containers/prune")
        if c_resp.status_code == 200:
            data = c_resp.json()
            deleted = data.get("ContainersDeleted") or []
            if deleted:
                sys.stdout.write("Deleted Containers:\n" + "\n".join(deleted) + "\n\n")
            reclaimed += int(data.get("SpaceReclaimed") or 0)

        n_resp = client.post("/networks/prune")
        if n_resp.status_code == 200:
            data = n_resp.json()
            deleted = data.get("NetworksDeleted") or []
            if deleted:
                sys.stdout.write("Deleted Networks:\n" + "\n".join(deleted) + "\n\n")

        i_resp = client.post("/images/prune", params={"filters": json.dumps({"dangling": ["false"]})})
        if i_resp.status_code == 200:
            data = i_resp.json()
            deleted = data.get("ImagesDeleted") or []
            if deleted:
                sys.stdout.write("Deleted Images:\n")
                for item in deleted:
                    for key in ("Untagged", "Deleted"):
                        if item.get(key):
                            sys.stdout.write(f"{key.lower()}: {item[key]}\n")
                sys.stdout.write("\n")
            reclaimed += int(data.get("SpaceReclaimed") or 0)

        b_resp = client.post("/build/prune", params={"all": "true"})
        if b_resp.status_code == 200:
            data = b_resp.json()
            reclaimed += int(data.get("SpaceReclaimed") or 0)

    sys.stdout.write(f"Total reclaimed space: {_format_bytes(reclaimed)}\n")
    sys.stdout.flush()
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in ("-v", "--version", "version"):
        sys.stdout.write("Docker version 27.5.1, build fleetge-shim\n")
        return 0

    sub = args[0]
    if sub == "compose":
        compose_bin = shutil.which("docker-compose") or "/usr/local/bin/docker-compose"
        os.execv(compose_bin, [compose_bin, *args[1:]])

    try:
        if sub == "inspect":
            return _cmd_inspect("any", args[1:])
        if sub == "image" and len(args) >= 2 and args[1] == "inspect":
            return _cmd_inspect("image", args[2:])
        if sub == "container" and len(args) >= 2 and args[1] == "inspect":
            return _cmd_inspect("container", args[2:])
        if sub == "ps":
            return _cmd_ps(args[1:])
        if sub == "exec":
            return _cmd_exec(args[1:])
        if sub == "run":
            return _cmd_run(args[1:])
        if sub == "system" and len(args) >= 2 and args[1] == "prune":
            return _cmd_system_prune()
    except httpx.HTTPError as exc:
        sys.stderr.write(f"Docker socket request failed: {exc}\n")
        return 1

    sys.stderr.write(f"Unsupported docker subcommand in fleetge-shim: {' '.join(args)}\n")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
