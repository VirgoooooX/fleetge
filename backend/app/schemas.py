"""Pydantic schemas for API responses."""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Optional
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import re

from pydantic import BaseModel, Field, field_validator, model_validator


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
    networkRxRate: Optional[float] = None
    networkTxRate: Optional[float] = None
    networkRxTotalBytes: int = 0
    networkTxTotalBytes: int = 0
    networkScope: str = "container"
    networkSelectionMode: str = "legacy"
    networkInterfaces: list[str] = Field(default_factory=list)
    networkCounterEpoch: str = "legacy"
    counterReset: bool = False
    hasGap: bool = False
    persistenceAvailable: bool = False
    diskReadBytes: int = 0
    diskWriteBytes: int = 0
    diskReadRate: Optional[float] = None
    diskWriteRate: Optional[float] = None
    loadavg: list[float]
    uptime: int
    collectorState: str = "active"
    sampleAgeSeconds: Optional[float] = None
    metricsActiveInterval: Optional[float] = None
    trafficIdleInterval: Optional[float] = None
    _warnings: Optional[dict] = None


class HostSubscriptionSummary(BaseModel):
    configured: bool = False
    provider: Optional[str] = None
    plan_name: Optional[str] = None
    payment_amount: Optional[float] = None
    currency: str = "CNY"
    payment_cycle: Optional[str] = None
    next_payment_date: Optional[str] = None
    payment_days_remaining: Optional[int] = None
    service_expiry_date: Optional[str] = None
    service_days_remaining: Optional[int] = None
    auto_renew: bool = False
    quota_enabled: bool = False
    traffic_direction: str = "both"
    management_url: Optional[str] = None


class HostSummary(BaseModel):
    host_id: str
    display_name: str
    status: str  # online | offline | degraded | unknown
    traffic_billing_day: int = 1
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
    subscription: Optional[HostSubscriptionSummary] = None


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
    image_config_digest: Optional[str] = None  # classic store: image inspect Id
    image_manifest_digest: Optional[str] = None  # containerd: running platform manifest
    repo_digests: list[str] = []  # from /images/{name}/json → RepoDigests
    tag_image_id: Optional[str] = None  # from /images/{name}/json → Id
    tag_platform: Optional[str] = None  # from /images/{name}/json → os/arch[/variant]
    state: str  # running | exited | paused
    status: str  # human-readable status text
    created: int  # Unix epoch seconds (from Docker API)
    ports: list[ContainerPort] = []
    labels: dict[str, str] = {}
    stack_name: Optional[str] = None  # derived from compose label
    service_name: Optional[str] = None
    restart_count: Optional[int] = None
    driver: Optional[str] = None
    platform: Optional[str] = None
    hostname: Optional[str] = None
    domainname: Optional[str] = None
    user: Optional[str] = None
    working_dir: Optional[str] = None
    entrypoint: Optional[list[str] | str] = None
    command: Optional[list[str] | str] = None
    restart_policy: Optional[dict] = None
    network_mode: Optional[str] = None
    privileged: Optional[bool] = None
    mounts: list[dict] = Field(default_factory=list)
    networks: dict[str, dict] = Field(default_factory=dict)
    health: Optional[dict] = None
    healthcheck_configured: bool = False
    inspection_complete: bool = True


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
    icon_url: Optional[str] = None  # 自定义图标 URL（网络或本地），由后端根据 host_config.stack_icons 匹配
    management_status: str = "managed"  # managed | deployed | file-only | unmanaged
    auto_update_enabled: bool = False
    auto_update_reason: str = ""
    title: Optional[str] = None
    app_url: Optional[str] = None
    group: Optional[str] = None

    class Config:
        from_attributes = True


class StackComposeDetail(BaseModel):
    name: str
    compose_yaml: str = ""
    compose_env: str = ""
    compose_file_name: str = "compose.yaml"
    is_managed_by_agent: bool = True


class StackComposeSaveRequest(BaseModel):
    compose_yaml: str
    compose_env: str = ""
    compose_file_name: str = "compose.yaml"
    is_add: bool = False


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
    registry_index_digest: Optional[str] = None
    registry_manifest_digest: Optional[str] = None
    registry_config_digest: Optional[str] = None
    identity_error: Optional[str] = None
    registry: Optional[str] = None
    platform: Optional[str] = None
    http_status: Optional[int] = None
    matched_field: Optional[str] = None
    retry_after: Optional[int] = None
    failure_count: int = 0
    last_failure_status: Optional[str] = None
    last_failure_http_status: Optional[int] = None
    last_failure_retry_after: Optional[int] = None
    last_failure_at: Optional[datetime] = None
    status: str  # up_to_date | updatable | needs_auth | check_failed | rate_limited


class UpdateRunSubmitRequest(BaseModel):
    request_id: str
    mode: Literal["manual", "bulk"]
    stack_names: list[str] = Field(min_length=1, max_length=100)


class UpdateRunItem(BaseModel):
    id: int
    host_id: str
    request_id: str
    source: str
    requested_by: str
    stack_name: str
    status: str
    stage: str = ""
    attempts: int = 0
    detail: str = ""
    log_tail: str = ""
    targets_json: str = "{}"
    agent_job_id: Optional[str] = None
    started_at: datetime
    finished_at: Optional[datetime] = None


class UpdateRunCounts(BaseModel):
    queued: int = 0
    running: int = 0
    success: int = 0
    failed: int = 0
    uncertain: int = 0
    skipped: int = 0


class UpdateRunBatch(BaseModel):
    host_id: str
    request_id: str
    mode: str
    items: list[UpdateRunItem]
    finished: bool
    counts: UpdateRunCounts


class UpdateRunList(BaseModel):
    active: list[UpdateRunItem]
    recent: list[UpdateRunItem]


class UpdateCheckRunResponse(BaseModel):
    # started=True: this /run executed the force sweep; results are fresh.
    # started=False: a manual sweep was already in flight, so this trigger was
    #   coalesced and results hold the last known cache. The client should keep
    #   the cached view rather than treating this as an error.
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


# ── Settings ────────────────────────────────────────────────────────────

class SettingItem(BaseModel):
    key: str
    value: str
    type: str           # "number" | "string" | "password"
    is_writable: bool
    description: str
    min_value: Optional[float] = None  # for number type validation
    max_value: Optional[float] = None
    unit: Optional[str] = None         # "秒", "小时" etc.


class SettingsResponse(BaseModel):
    settings: list[SettingItem]


class SettingsUpdateRequest(BaseModel):
    settings: dict[str, str]  # key → new value


# ── Host Management ─────────────────────────────────────────────────────

class HostCreateRequest(BaseModel):
    host_id: str               # unique id, pattern: [a-z0-9-]+
    display_name: str
    enabled: bool = True
    sort_order: int = 0
    traffic_billing_day: int = Field(default=1, ge=1, le=31)
    # Agent connection (primary)
    agent_url: Optional[str] = None
    agent_token: Optional[str] = None


class HostUpdateRequest(BaseModel):
    display_name: str
    enabled: bool = True
    sort_order: int = 0
    traffic_billing_day: int | None = Field(default=None, ge=1, le=31)
    agent_url: Optional[str] = None
    agent_token: Optional[str] = None  # None = keep existing, "" = clear


class AppProfileEntry(BaseModel):
    stack_pattern: str
    title: Optional[str] = None
    app_url: Optional[str] = None
    group: Optional[str] = None
    icon_value: Optional[str] = None


class HostSubscriptionUpdate(BaseModel):
    provider: Optional[str] = Field(default=None, max_length=120)
    plan_name: Optional[str] = Field(default=None, max_length=160)
    payment_amount: Optional[Decimal] = Field(default=None, ge=0, max_digits=14, decimal_places=4)
    currency: str = Field(default="CNY", min_length=3, max_length=3)
    payment_cycle: Optional[Literal["monthly", "quarterly", "semiannual", "annual", "once"]] = None
    next_payment_date: Optional[date] = None
    service_expiry_date: Optional[date] = None
    auto_renew: bool = False
    management_url: Optional[str] = Field(default=None, max_length=2048)
    notes: Optional[str] = Field(default=None, max_length=4000)
    quota_enabled: bool = False
    traffic_quota_value: Optional[Decimal] = Field(default=None, gt=0, max_digits=16, decimal_places=6)
    traffic_quota_unit: Literal["GB", "TB", "GiB", "TiB"] = "GiB"
    traffic_direction: Literal["upload", "download", "both", "max"] = "both"
    billing_timezone: str = Field(default="Asia/Shanghai", min_length=1, max_length=100)
    alerts_enabled: bool = True

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, value: str) -> str:
        value = value.strip().upper()
        if not re.fullmatch(r"[A-Z]{3}", value):
            raise ValueError("currency must be a three-letter code")
        return value

    @field_validator("provider", "plan_name", "notes")
    @classmethod
    def normalize_optional_text(cls, value: Optional[str]) -> Optional[str]:
        value = value.strip() if value else None
        return value or None

    @field_validator("management_url")
    @classmethod
    def validate_management_url(cls, value: Optional[str]) -> Optional[str]:
        value = value.strip() if value else None
        if not value:
            return None
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("management_url must be an HTTP(S) URL without credentials")
        return value

    @field_validator("billing_timezone")
    @classmethod
    def validate_billing_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("billing_timezone must be a valid IANA time zone") from exc
        return value

    @model_validator(mode="after")
    def validate_quota(self):
        if self.quota_enabled and self.traffic_quota_value is None:
            raise ValueError("traffic_quota_value is required when quota management is enabled")
        return self


class RenewalRequest(BaseModel):
    paid_on: Optional[date] = None
    # The billing endpoint suggests dates; confirmation always saves explicit values.
    next_payment_date: Optional[date] = Field(...)
    service_expiry_date: date


class BillingAlertsUpdateRequest(BaseModel):
    enabled: bool


class HostSubscriptionResponse(BaseModel):
    host_id: str
    configured: bool
    provider: Optional[str] = None
    plan_name: Optional[str] = None
    payment_amount: Optional[float] = None
    currency: str = "CNY"
    payment_cycle: Optional[str] = None
    next_payment_date: Optional[date] = None
    service_expiry_date: Optional[date] = None
    auto_renew: bool = False
    management_url: Optional[str] = None
    notes: Optional[str] = None
    quota_enabled: bool = False
    traffic_quota_value: Optional[float] = None
    traffic_quota_unit: str = "GiB"
    traffic_direction: str = "both"
    billing_timezone: str = "Asia/Shanghai"
    alerts_enabled: bool = True


class HostConfigResponse(BaseModel):
    """Host config for management UI (secrets masked)."""
    host_id: str
    display_name: str
    enabled: bool
    sort_order: int
    traffic_billing_day: int = 1
    agent_url: Optional[str] = None
    has_agent_token: bool = False     # masked: only show whether token exists
    agent_instance_id: Optional[str] = None
    location_latitude: Optional[float] = None
    location_longitude: Optional[float] = None
    location_city: Optional[str] = None
    location_region: Optional[str] = None
    location_country: Optional[str] = None
    location_country_code: Optional[str] = None
    location_source: Optional[str] = None
    location_confirmed: bool = False
    location_confidence: Optional[str] = None
    public_ip_effective: Optional[str] = None
    public_ip_source: Optional[str] = None
    public_ip_override: Optional[str] = None
    network_identity_checked_at: Optional[datetime] = None
    stack_icons: Optional[dict[str, str]] = None  # parsed JSON mapping
    app_profiles: Optional[list[AppProfileEntry]] = None


class ConnectionTestResponse(BaseModel):
    success: bool
    response_time_ms: int
    message: str


# ── Enrollment ──────────────────────────────────────────────────────────

class EnrollmentInviteCreateRequest(BaseModel):
    dashboard_url: Optional[str] = None
    agent_public_host: str
    stack_root: str = "/opt/stacks"
    agent_port: int = 8080
    agent_image: Optional[str] = None


class EnrollmentInviteResponse(BaseModel):
    invite_id: str
    status: str
    expires_at: datetime
    downloaded_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    host_id: Optional[str] = None
    agent_instance_id: str
    agent_port: int
    stack_root: str
    agent_image: str
    agent_public_host: str
    agent_public_url: str
    failure_reason: Optional[str] = None
    install_command: Optional[str] = None


class EnrollmentClaimRequest(BaseModel):
    claim_token: str
    hostname: str
    instance_id: str
    agent_public_host: str
    geolocation: Optional[dict] = None


class EnrollmentClaimResponse(BaseModel):
    status: str
    host_id: Optional[str] = None
    agent_url: Optional[str] = None
    agent_public_url: Optional[str] = None
    location: Optional[dict] = None
    message: str = ""


class EnrollmentRetryRequest(BaseModel):
    pass


class HostLocationRequest(BaseModel):
    city: Optional[str] = None
    region: Optional[str] = None
    country: Optional[str] = None
    country_code: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    source: str = "manual"
    confirmed: bool = True


class FleetMapSettingsRequest(BaseModel):
    name: str = "Fleetge Control Center"
    city: Optional[str] = None
    region: Optional[str] = None
    country: Optional[str] = None
    country_code: Optional[str] = None
    latitude: float
    longitude: float
    confirmed: bool = True


# ── Stack Icons ─────────────────────────────────────────────────────────

class StackIconEntry(BaseModel):
    stack_pattern: str    # stack name or wildcard pattern (e.g. "rsshub", "emby*")
    icon_value: str       # URL or local filename


class StackIconsUpdateRequest(BaseModel):
    icons: list[StackIconEntry]  # ordered list → converted to dict for storage


# ── App Profiles ─────────────────────────────────────────────────────────

class AppProfilesUpdateRequest(BaseModel):
    profiles: list[AppProfileEntry]


class AppSummary(BaseModel):
    host_id: str
    host_name: str
    host_status: str
    stack_name: str
    status: str
    service_count: int
    running_count: int
    management_status: str
    title: Optional[str] = None
    app_url: Optional[str] = None
    group: Optional[str] = None
    icon_url: Optional[str] = None
    services: list[StackService] = []
    update_status: str = "up_to_date"
