"""Pydantic schemas for API responses."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


# ── Auth ────────────────────────────────────────────────────────────────


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str
    token_type: str = "bearer"


class MeResponse(BaseModel):
    username: str


# ── Host ────────────────────────────────────────────────────────────────


class HostMetrics(BaseModel):
    hostname: str
    timestamp: str
    cpuPercent: float
    memoryUsed: int
    memoryTotal: int
    diskUsed: int
    diskTotal: int
    networkRxBytes: int = 0
    networkTxBytes: int = 0
    networkRxRate: float = 0.0
    networkTxRate: float = 0.0
    diskReadBytes: int = 0
    diskWriteBytes: int = 0
    diskReadRate: float = 0.0
    diskWriteRate: float = 0.0
    loadavg: list[float]
    uptime: int
    _warnings: Optional[dict] = None


class HostSummary(BaseModel):
    host_id: str
    display_name: str
    status: str  # online | offline | degraded | unknown
    metrics: Optional[HostMetrics] = None
    docker_version: Optional[str] = None
    api_version: Optional[str] = None
    os_info: Optional[str] = None
    architecture: Optional[str] = None
    docker_root_dir: Optional[str] = None
    container_running: int = 0
    container_stopped: int = 0
    container_total: int = 0
    image_count: int = 0
    docker_disk_images: Optional[int] = None
    docker_disk_containers: Optional[int] = None
    docker_disk_volumes: Optional[int] = None
    docker_disk_build_cache: Optional[int] = None
    update_count: int = 0
    error_message: Optional[str] = None


class HostListResponse(BaseModel):
    hosts: list[HostSummary]


# ── Container ───────────────────────────────────────────────────────────


class ContainerPort(BaseModel):
    private_port: int
    public_port: Optional[int] = None
    ip: Optional[str] = None
    type: str = "tcp"


class ContainerSummary(BaseModel):
    id: str
    name: str
    image: str
    image_id: str
    repo_digests: list[str] = []  # from /images/{name}/json → RepoDigests
    state: str  # running | exited | paused
    status: str  # human-readable status text
    created: int  # Unix epoch seconds (from Docker API)
    ports: list[ContainerPort] = []
    labels: dict[str, str] = {}
    stack_name: Optional[str] = None  # derived from compose label
    service_name: Optional[str] = None


class ContainerStats(BaseModel):
    cpu_percent: float = 0.0
    memory_usage: int = 0
    memory_limit: int = 0
    memory_percent: float = 0.0
    network_rx_bytes: int = 0
    network_tx_bytes: int = 0
    block_read_bytes: int = 0
    block_write_bytes: int = 0


class ContainerDetail(BaseModel):
    summary: ContainerSummary
    stats: Optional[ContainerStats] = None
    env: Optional[list[str]] = None
    mounts: Optional[list[dict]] = None


# ── Stack ────────────────────────────────────────────────────────────────


class StackService(BaseModel):
    name: str
    container_id: Optional[str] = None
    state: str = "unknown"
    status: str = ""


class StackSummary(BaseModel):
    name: str
    status: str  # running | stopped | partially running
    compose_file: Optional[str] = None
    service_count: int = 0
    running_count: int = 0
    services: list[StackService] = []


class StackComposeDetail(BaseModel):
    name: str
    compose_yaml: str = ""
    compose_env: str = ""
    compose_file_name: str = "compose.yaml"
    is_managed_by_dockge: bool = False


class StackComposeSaveRequest(BaseModel):
    compose_yaml: str
    compose_env: str = ""


class StackOperationResponse(BaseModel):
    success: bool
    message: str
    detail: Optional[str] = None
    log_tail: Optional[str] = None
    duration_ms: Optional[int] = None


# ── Docker Info ─────────────────────────────────────────────────────────


class DockerInfo(BaseModel):
    version: Optional[str] = None
    api_version: Optional[str] = None
    os: Optional[str] = None
    architecture: Optional[str] = None
    docker_root_dir: Optional[str] = None
    server_version: Optional[str] = None
    kernel_version: Optional[str] = None
    operating_system: Optional[str] = None
    n_cpus: Optional[int] = None
    memory_total: Optional[int] = None
    name: Optional[str] = None


class DockerDiskUsage(BaseModel):
    images_total: int = 0
    images_size: Optional[int] = None
    containers_total: int = 0
    containers_size: Optional[int] = None
    volumes_total: int = 0
    volumes_size: Optional[int] = None
    build_cache_total: int = 0
    build_cache_size: Optional[int] = None


# ── Update Check ────────────────────────────────────────────────────────


class UpdateCheckResult(BaseModel):
    host_id: str
    image: str
    current_digest: Optional[str] = None
    registry_digest: Optional[str] = None
    status: str  # up_to_date | updatable | needs_auth | check_failed


class UpdateCheckRunResponse(BaseModel):
    started: bool
    results: Optional[list[UpdateCheckResult]] = None


# ── Audit Log ──────────────────────────────────────────────────────────


class AuditLogEntry(BaseModel):
    id: int
    timestamp: datetime
    user: str
    action: str
    host_id: str
    stack_name: Optional[str] = None
    result: str
    detail: Optional[str] = None
    ip_address: Optional[str] = None
