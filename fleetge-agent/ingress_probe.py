"""Map host ingress listeners to their existing Compose services."""

import json
import os
import re
import subprocess

# Ports whose listeners are the control plane's only route to this agent.
INGRESS_PORTS = (80, 443)
_PROC_NET_LISTEN = "0A"


def _listening_inodes(proc_root: str, ports: tuple[int, ...]) -> dict[int, set[str]]:
    """Map requested listening ports to socket inodes from a /proc tree."""
    wanted = set(ports)
    inodes: dict[int, set[str]] = {port: set() for port in ports}
    for name in ("tcp", "tcp6"):
        path = os.path.join(proc_root, "net", name)
        try:
            with open(path, "r", encoding="utf-8") as handle:
                next(handle, None)
                for line in handle:
                    columns = line.split()
                    if len(columns) < 10 or columns[3] != _PROC_NET_LISTEN:
                        continue
                    port = int(columns[1].rsplit(":", 1)[1], 16)
                    if port in wanted:
                        inodes[port].add(columns[9])
        except OSError:
            continue
    return inodes


def _container_socket_inodes(container_id: str) -> set[str]:
    """Socket inodes held by a container's root process.

    The target only needs a shell. Its /proc inode numbers match the host's
    when the container uses the host network, which is the only mode checked.
    """
    if not re.fullmatch(r"[0-9a-fA-F]{12,64}", container_id):
        return set()
    try:
        completed = subprocess.run(
            [
                "docker", "exec", container_id, "sh", "-c",
                "for f in /proc/1/fd/*; do readlink \"$f\" 2>/dev/null; done",
            ],
            capture_output=True,
            text=True,
            timeout=8,
        )
    except (OSError, subprocess.TimeoutExpired):
        return set()
    if completed.returncode != 0:
        return set()
    return {
        line[8:-1]
        for line in completed.stdout.splitlines()
        if line.startswith("socket:[") and line.endswith("]")
    }


def _running_host_containers() -> list[dict]:
    """Running containers using the host network, via the Docker CLI."""
    response = subprocess.run(
        ["docker", "ps", "-q", "--filter", "network=host"],
        capture_output=True,
        text=True,
        timeout=8,
        check=True,
    )
    ids = [line.strip() for line in response.stdout.splitlines() if line.strip()]
    if not ids:
        return []
    details = subprocess.run(
        ["docker", "inspect", *ids],
        capture_output=True,
        text=True,
        timeout=8,
        check=True,
    )
    containers = []
    for item in json.loads(details.stdout or "[]"):
        container_id = str(item.get("Id") or "")
        if not container_id:
            continue
        containers.append({
            "Id": container_id,
            "Names": [item["Name"]] if item.get("Name") else [],
            "Labels": (item.get("Config") or {}).get("Labels") or {},
        })
    return containers


def ingress_services(ports: tuple[int, ...] = INGRESS_PORTS, *, listening_inodes=_listening_inodes,
                     running_host_containers=_running_host_containers,
                     container_socket_inodes=_container_socket_inodes) -> list[dict]:
    """Compose services holding the host's ingress ports, seen through Docker.

    The agent shares the host network namespace but not its PID namespace, so
    each host-network container is asked which sockets its own root process holds.
    """
    inodes = listening_inodes("/proc", ports)
    if not set().union(*inodes.values()):
        return []

    owners = []
    for container in running_host_containers():
        container_id = str(container.get("Id") or "")
        owned = container_socket_inodes(container_id)
        matched = [port for port in ports if inodes[port] & owned]
        if not matched:
            continue
        labels = container.get("Labels") or {}
        names = container.get("Names") or []
        owners.append({
            "container_id": container_id[:12],
            "container_name": names[0].lstrip("/") if names else "",
            "stack_name": labels.get("com.docker.compose.project") or "",
            "service_name": labels.get("com.docker.compose.service") or "",
            "ports": matched,
        })
    return owners
