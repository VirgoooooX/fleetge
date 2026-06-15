"""SQLModel ORM models for HostConfig and AuditLog."""

from datetime import datetime, timezone
from typing import Optional

from sqlmodel import SQLModel, Field
from sqlalchemy import Column, Text


class HostConfig(SQLModel, table=True):
    __tablename__ = "host_config"

    id: int = Field(primary_key=True, default=None)
    host_id: str = Field(unique=True, index=True)  # unique identifier, e.g. "oc-chicago"
    display_name: str = ""
    enabled: bool = True
    sort_order: int = 0

    # Connection URLs
    dockge_url: str = ""
    dockge_username: str = ""
    dockge_password_encrypted: str = ""

    docker_proxy_url: str = ""
    # Fernet-encrypted JSON: {"username": "...", "password": "..."}
    docker_proxy_auth_encrypted: Optional[str] = None

    metrics_url: str = ""
    # Fernet-encrypted JSON: {"username": "...", "password": "..."}
    metrics_auth_encrypted: Optional[str] = None

    # Stack icon mapping — JSON string: {"stack_name": "icon_url_or_path"}
    stack_icons: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))

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
