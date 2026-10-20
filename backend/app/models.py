"""SQLModel ORM models for Fleetge configuration and audit data."""

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlmodel import SQLModel, Field
from sqlalchemy import Column, Index, Numeric, Text, UniqueConstraint


class HostConfig(SQLModel, table=True):
    __tablename__ = "host_config"

    id: int = Field(primary_key=True, default=None)
    host_id: str = Field(unique=True, index=True)  # unique identifier, e.g. "oc-chicago"
    display_name: str = ""
    enabled: bool = True
    sort_order: int = 0
    # Per-Host traffic billing cycle. Day 29-31 is clamped to month end.
    traffic_billing_day: int = 1

    # Connection URLs
    # Fleetge Agent fields (primary)
    agent_url: Optional[str] = Field(default=None)
    agent_token_encrypted: Optional[str] = Field(default=None)
    # Stable identity reported by the agent. Nullable for legacy/manual hosts.
    agent_instance_id: Optional[str] = Field(default=None, index=True)

    # Normalized, user-confirmable geographic location used by Fleet Map.
    location_latitude: Optional[float] = Field(default=None)
    location_longitude: Optional[float] = Field(default=None)
    location_city: Optional[str] = Field(default=None)
    location_region: Optional[str] = Field(default=None)
    location_country: Optional[str] = Field(default=None)
    location_country_code: Optional[str] = Field(default=None)
    location_source: Optional[str] = Field(default=None)  # ipwho.is | manual | dashboard
    location_confirmed: bool = False
    location_confidence: Optional[str] = Field(default=None)

    # Public network identity evidence. Public IPs are intentionally kept out
    # of routine logs and exposed only through authenticated APIs.
    public_ip_effective: Optional[str] = Field(default=None)
    public_ip_source: Optional[str] = Field(default=None)
    public_ip_override: Optional[str] = Field(default=None)
    network_identity_evidence: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    network_identity_checked_at: Optional[datetime] = None
    enrollment_callback_ip: Optional[str] = Field(default=None)
    enrollment_callback_mode: Optional[str] = Field(default=None)

    # Stack icon mapping — JSON string: {"stack_name": "icon_url_or_path"}
    stack_icons: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))

    # App profiles — JSON string: [{"stack_pattern": "...", "title": "...", "app_url": "...", "group": "...", "icon_value": "..."}]
    app_profiles: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))

    # Runtime state (updated by poller)
    status: str = "unknown"  # online | offline | degraded | unknown
    last_seen: Optional[datetime] = None
    error_message: Optional[str] = None

    # Timestamps
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column_kwargs={"onupdate": lambda: datetime.now(timezone.utc)},
    )


class AuditLog(SQLModel, table=True):
    __tablename__ = "audit_log"

    id: int = Field(primary_key=True, default=None)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    user: str = ""
    action: str = ""  # "stack.start", "stack.stop", "stack.restart", "stack.update", "update_checks.run"
    host_id: str = ""
    stack_name: Optional[str] = None
    result: str = ""  # "success" | "error"
    detail: Optional[str] = None
    ip_address: Optional[str] = None


class ImageUpdateCache(SQLModel, table=True):
    __tablename__ = "image_update_cache"
    __table_args__ = (
        UniqueConstraint("host_id", "image", name="uq_image_update_cache_host_image"),
    )

    id: int = Field(primary_key=True, default=None)
    host_id: str = Field(index=True)
    image: str = Field(sa_column=Column(Text, nullable=False))
    current_digest: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    registry_digest: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    registry: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    platform: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    registry_index_digest: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    registry_manifest_digest: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    registry_config_digest: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    identity_error: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    http_status: Optional[int] = None
    matched_field: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    retry_after: Optional[int] = None
    pending_current_digest: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    pending_registry_digest: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    pending_platform: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    pending_matched_field: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    pending_detected_at: Optional[datetime] = None
    status: str = Field(index=True)
    checked_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    failure_count: int = 0
    last_failure_status: Optional[str] = None
    last_failure_http_status: Optional[int] = None
    last_failure_retry_after: Optional[int] = None
    last_failure_at: Optional[datetime] = None
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column_kwargs={"onupdate": lambda: datetime.now(timezone.utc)},
    )


class StackAutoUpdate(SQLModel, table=True):
    __tablename__ = "stack_auto_update"
    __table_args__ = (UniqueConstraint("host_id", "stack_name", name="uq_stack_auto_update"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    host_id: str = Field(index=True)
    stack_name: str
    enabled: bool = False
    reason: str = ""


class AutoUpdateRun(SQLModel, table=True):
    __tablename__ = "auto_update_run"
    __table_args__ = (
        Index("uq_auto_update_run_host_request_stack", "host_id", "request_id", "stack_name", unique=True),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    host_id: str = Field(index=True)
    request_id: Optional[str] = Field(default=None, index=True)
    source: str = Field(default="auto", index=True)
    requested_by: str = "system"
    stack_name: str
    status: str = Field(default="running", index=True)
    attempts: int = 0
    stage: str = "queued"
    detail: str = ""
    log_tail: str = Field(default="", sa_column=Column(Text, nullable=False))
    targets_json: str = Field(default="{}", sa_column=Column(Text, nullable=False))
    agent_job_id: Optional[str] = None
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: Optional[datetime] = None
    notify_url: str = ""
    notify_recipient: str = ""
    notify_payload: str = Field(default="", sa_column=Column(Text, nullable=False))
    notify_status: str = Field(default="none", index=True)
    notify_attempts: int = 0
    notify_next_at: Optional[datetime] = None
    notify_expires_at: Optional[datetime] = None
    notify_error: str = ""


class Setting(SQLModel, table=True):
    __tablename__ = "settings"

    setting_key: str = Field(primary_key=True, max_length=255)
    setting_value: str = Field(default="", sa_column=Column(Text, nullable=False))
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column_kwargs={"onupdate": lambda: datetime.now(timezone.utc)},
    )


class EnrollmentInvite(SQLModel, table=True):
    """Single-use, short-lived enrollment invitation state."""

    __tablename__ = "enrollment_invite"

    id: int = Field(primary_key=True, default=None)
    invite_id: str = Field(unique=True, index=True)
    install_token_hash: str = Field(index=True)
    claim_token_hash: str = Field(index=True)
    agent_token_encrypted: Optional[str] = Field(default=None)
    secret_path: Optional[str] = Field(default=None)
    agent_public_host: str = ""
    agent_instance_id: str = Field(index=True)
    hostname: Optional[str] = None
    location_payload: Optional[str] = None
    callback_ip: Optional[str] = None
    callback_mode: Optional[str] = None
    agent_port: int = 8080
    stack_root: str = "/opt/stacks"
    agent_image: str = ""
    dashboard_url: str = ""
    status: str = "issued"  # issued/downloaded/verifying/active/needs_url/failed/expired/revoked
    expires_at: datetime
    downloaded_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    host_id: Optional[str] = None
    failure_reason: Optional[str] = None
    created_by: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column_kwargs={"onupdate": lambda: datetime.now(timezone.utc)},
    )


class HostSubscription(SQLModel, table=True):
    """Optional billing and traffic-quota settings for one Host."""

    __tablename__ = "host_subscription"

    id: int = Field(primary_key=True, default=None)
    host_id: str = Field(unique=True, index=True)
    provider: Optional[str] = None
    plan_name: Optional[str] = None
    payment_amount: Optional[Decimal] = Field(
        default=None,
        sa_column=Column(Numeric(14, 4), nullable=True),
    )
    currency: str = "CNY"
    payment_cycle: Optional[str] = None
    next_payment_date: Optional[date] = None
    service_expiry_date: Optional[date] = None
    auto_renew: bool = False
    management_url: Optional[str] = None
    notes: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    quota_enabled: bool = False
    traffic_quota_value: Optional[Decimal] = Field(
        default=None,
        sa_column=Column(Numeric(16, 6), nullable=True),
    )
    traffic_quota_unit: str = "GiB"
    traffic_direction: str = "both"
    billing_timezone: str = "Asia/Shanghai"
    alerts_enabled: bool = True
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column_kwargs={"onupdate": lambda: datetime.now(timezone.utc)},
    )


class HostBillingAlertState(SQLModel, table=True):
    """Durable outbox and de-duplication state for billing notifications."""

    __tablename__ = "host_billing_alert_state"
    __table_args__ = (UniqueConstraint("alert_key", name="uq_host_billing_alert_key"),)

    id: int = Field(primary_key=True, default=None)
    alert_key: str = Field(index=True)
    host_id: str = Field(index=True)
    alert_type: str = Field(index=True)
    status: str = Field(default="pending", index=True)
    notify_url: str = ""
    notify_recipient: str = ""
    payload: str = Field(default="{}", sa_column=Column(Text, nullable=False))
    attempts: int = 0
    next_attempt_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime
    sent_at: Optional[datetime] = None
    last_error: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class HostTrafficBucket(SQLModel, table=True):
    __tablename__ = "host_traffic_bucket"
    __table_args__ = (
        UniqueConstraint("host_id", "ledger_id", "agent_bucket_id", name="uq_host_traffic_agent_bucket"),
    )

    id: int = Field(primary_key=True, default=None)
    host_id: str = Field(index=True)
    ledger_id: str = Field(index=True)
    agent_bucket_id: int = Field(index=True)
    bucket_start: datetime = Field(index=True)
    bucket_seconds: int = 300
    counter_epoch: str = Field(index=True)
    rx_bytes: int = 0
    tx_bytes: int = 0
    has_gap: bool = False
    counter_reset: bool = False
    interfaces_json: str = Field(default="[]", sa_column=Column(Text, nullable=False))
    synced_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class HostTrafficDaily(SQLModel, table=True):
    __tablename__ = "host_traffic_daily"
    __table_args__ = (
        UniqueConstraint("host_id", "day_utc", name="uq_host_traffic_daily"),
    )

    id: int = Field(primary_key=True, default=None)
    host_id: str = Field(index=True)
    day_utc: str = Field(index=True)
    rx_bytes: int = 0
    tx_bytes: int = 0
    has_gap: bool = False
    bucket_count: int = 0


class HostTrafficCursor(SQLModel, table=True):
    __tablename__ = "host_traffic_cursor"

    host_id: str = Field(primary_key=True)
    cursor: int = 0
    ledger_id: Optional[str] = None
    last_sync_at: Optional[datetime] = None
    last_error: Optional[str] = None
