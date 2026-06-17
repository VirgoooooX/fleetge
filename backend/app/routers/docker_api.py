"""Docker Engine API compatibility router mounted at root for direct Homepage integration."""

import asyncio
import ipaddress
import logging
import time
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, Response, Header, Depends

from app.services.snapshot import HostSnapshot, snapshot_manager

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="",
    tags=["docker-api"],
)

STALE_THRESHOLD = 30.0  # seconds


def is_private_ip(ip: str) -> bool:
    """Check if an IP address is a private or loopback IP."""
    try:
        if ip in ("127.0.0.1", "localhost", "::1", "testclient"):
            return True
        ip_obj = ipaddress.ip_address(ip)
        return ip_obj.is_private or ip_obj.is_loopback
    except ValueError:
        return False


def verify_private_access(request: Request):
    """Raise 403 if request client IP is not from a private or loopback network."""
    client_host = request.client.host if request.client else None
    if not client_host or not is_private_ip(client_host):
        logger.warning("Unauthorized non-private access attempt to Docker API from %s", client_host)
        raise HTTPException(status_code=403, detail="Access denied: only private networks allowed")


def get_host_id(
    host_id: Optional[str] = None,
    host: Optional[str] = None,
    x_host_id: Optional[str] = Header(None, alias="X-Host-Id"),
) -> str:
    """Extract host ID from header or query parameters."""
    h_id = x_host_id or host_id or host
    if not h_id:
        raise HTTPException(
            status_code=400,
            detail="Missing host identifier. Provide X-Host-Id header or host_id/host query parameter."
        )
    return h_id


async def _get_snap(host_id: str) -> HostSnapshot:
    """Fetch snapshot and trigger background refresh if data is stale."""
    snap = snapshot_manager.get_snapshot(host_id)
    if not snap:
        raise HTTPException(status_code=404, detail=f"Host '{host_id}' not found")

    # Trigger background stale-while-revalidate update if needed
    lock = snapshot_manager._host_refresh_locks.setdefault(host_id, asyncio.Lock())
    if not lock.locked() and (time.monotonic() - snap.containers_updated) > STALE_THRESHOLD:
        logger.info("Docker API hit stale snapshot for host %s, triggering background refresh", host_id)
        asyncio.create_task(snapshot_manager.refresh_host_docker_with_retry(host_id))

    return snap


@router.get("/_ping")
@router.get("/_ping/")
async def ping(request: Request, host_id: str = Depends(get_host_id)):
    verify_private_access(request)
    await _get_snap(host_id)
    return Response(
        content="OK",
        media_type="text/plain",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
        },
    )


@router.get("/version")
@router.get("/version/")
async def version(request: Request, host_id: str = Depends(get_host_id)):
    verify_private_access(request)
    snap = await _get_snap(host_id)
    info = snap.docker_info
    return {
        "Version": info.version if info else "20.10.0",
        "ApiVersion": info.api_version if info else "1.41",
        "Os": info.os if info else "linux",
        "Arch": info.architecture if info else "amd64",
        "KernelVersion": info.kernel_version if info else "",
    }


@router.get("/info")
@router.get("/info/")
async def info(request: Request, host_id: str = Depends(get_host_id)):
    verify_private_access(request)
    snap = await _get_snap(host_id)
    info = snap.docker_info
    display_name = snap.host_config.display_name if snap.host_config else host_id
    return {
        "Name": info.name if info else display_name,
        "ServerVersion": info.server_version if info else "20.10.0",
        "NCPU": info.n_cpus if info else 1,
        "MemTotal": info.memory_total if info else 0,
        "OSType": info.os if info else "linux",
        "Architecture": info.architecture if info else "x86_64",
        "OperatingSystem": info.operating_system if info else "Linux",
        "Containers": len(snap.containers),
        "ContainersRunning": sum(1 for c in snap.containers if c.state == "running"),
        "ContainersStopped": sum(1 for c in snap.containers if c.state != "running"),
    }


@router.get("/containers/json")
@router.get("/containers/json/")
async def containers_json(request: Request, all: bool = False, host_id: str = Depends(get_host_id)):
    verify_private_access(request)
    snap = await _get_snap(host_id)

    result = []
    for c in snap.containers:
        if not all and c.state != "running":
            continue

        ports = [
            {
                "IP": p.ip or "0.0.0.0",
                "PrivatePort": p.private_port,
                "PublicPort": p.public_port,
                "Type": p.type,
            }
            for p in c.ports
        ]

        cmd = c.command
        if isinstance(cmd, list):
            cmd_str = " ".join(cmd)
        elif isinstance(cmd, str):
            cmd_str = cmd
        else:
            cmd_str = ""

        result.append({
            "Id": c.id,
            "Names": ["/" + c.name.lstrip("/")],
            "Image": c.image,
            "ImageID": c.image_id,
            "Command": cmd_str,
            "Created": c.created,
            "State": c.state,
            "Status": c.status,
            "Ports": ports,
            "Labels": c.labels or {},
            "HostConfig": {
                "NetworkMode": c.network_mode or "default",
            },
            "NetworkSettings": {
                "Networks": c.networks or {},
            },
            "Mounts": c.mounts or [],
        })
    return result


@router.get("/containers/{container_id}/json")
async def container_inspect(container_id: str, request: Request, host_id: str = Depends(get_host_id)):
    verify_private_access(request)
    snap = await _get_snap(host_id)

    c = next(
        (
            container for container in snap.containers
            if container.id.startswith(container_id) or container.name.lstrip("/") == container_id.lstrip("/")
        ),
        None
    )
    if not c:
        raise HTTPException(status_code=404, detail="Container not found")

    return {
        "Id": c.id,
        "Name": "/" + c.name.lstrip("/"),
        "State": {
            "Status": c.state,
            "Running": c.state == "running",
            "Health": c.health,
        },
        "Config": {
            "Hostname": c.hostname,
            "Domainname": c.domainname,
            "User": c.user,
            "WorkingDir": c.working_dir,
            "Entrypoint": c.entrypoint,
            "Cmd": c.command,
            "Labels": c.labels or {},
        },
        "HostConfig": {
            "RestartPolicy": c.restart_policy,
            "NetworkMode": c.network_mode or "default",
            "Privileged": c.privileged or False,
        },
        "NetworkSettings": {
            "Networks": c.networks or {},
        },
        "Mounts": c.mounts or [],
    }


@router.get("/containers/{container_id}/stats")
async def container_stats(container_id: str, request: Request, stream: bool = False, host_id: str = Depends(get_host_id)):
    verify_private_access(request)
    snap = await _get_snap(host_id)

    c = next(
        (
            container for container in snap.containers
            if container.id.startswith(container_id) or container.name.lstrip("/") == container_id.lstrip("/")
        ),
        None
    )
    if not c:
        raise HTTPException(status_code=404, detail="Container not found")

    stats = snap.container_stats.get(c.id)
    cpu_percent = stats.cpu_percent if stats else 0.0
    memory_usage = stats.memory_usage if stats else 0
    memory_limit = stats.memory_limit if stats else 0
    rx_bytes = stats.network_rx_bytes if stats else 0
    tx_bytes = stats.network_tx_bytes if stats else 0

    # Mock system cpu math to match cpu_percent
    # cpu_percent = (cpu_delta / system_delta) * online_cpus * 100.0
    system_cpu = 1000000000
    presystem_cpu = 999000000  # delta = 1,000,000
    cpu_total = int(cpu_percent * 10000)
    precpu_total = 0

    return {
        "read": "2026-01-01T00:00:00Z",
        "preread": "2026-01-01T00:00:00Z",
        "cpu_stats": {
            "cpu_usage": {
                "total_usage": cpu_total,
                "usage_in_kernelmode": 0,
                "usage_in_usermode": 0,
            },
            "system_cpu_usage": system_cpu,
            "online_cpus": 1,
        },
        "precpu_stats": {
            "cpu_usage": {
                "total_usage": precpu_total,
                "usage_in_kernelmode": 0,
                "usage_in_usermode": 0,
            },
            "system_cpu_usage": presystem_cpu,
            "online_cpus": 1,
        },
        "memory_stats": {
            "usage": memory_usage,
            "max_usage": memory_usage,
            "limit": memory_limit,
            "stats": {},
        },
        "networks": {
            "eth0": {
                "rx_bytes": rx_bytes,
                "tx_bytes": tx_bytes,
                "rx_packets": 0,
                "rx_errors": 0,
                "rx_dropped": 0,
                "tx_packets": 0,
                "tx_errors": 0,
                "tx_dropped": 0,
            },
        },
        "blkio_stats": {
            "io_service_bytes_recursive": [
                {"major": 8, "minor": 0, "op": "read", "value": stats.block_read_bytes if stats else 0},
                {"major": 8, "minor": 0, "op": "write", "value": stats.block_write_bytes if stats else 0},
            ],
        },
    }


@router.get("/images/json")
@router.get("/images/json/")
async def images_json(request: Request, host_id: str = Depends(get_host_id)):
    verify_private_access(request)
    snap = await _get_snap(host_id)

    unique_images = {}
    for c in snap.containers:
        if c.image and c.image not in unique_images:
            unique_images[c.image] = {
                "Id": c.image_id or c.image,
                "RepoTags": [c.image],
                "RepoDigests": c.repo_digests or [],
                "Created": c.created,
                "Size": 0,
                "VirtualSize": 0,
                "Labels": {},
            }

    return list(unique_images.values())
