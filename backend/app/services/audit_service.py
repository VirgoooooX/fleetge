"""Persist audit entries from API and streaming operations."""

from sqlmodel import Session

from app.models import AuditLog


def write_audit_log(
    session: Session,
    user: str,
    action: str,
    host_id: str,
    result: str,
    detail: str | None = None,
    ip_address: str | None = None,
    *,
    stack_name: str | None = None,
) -> None:
    session.add(AuditLog(
        user=user, action=action, host_id=host_id, result=result,
        detail=detail, ip_address=ip_address, stack_name=stack_name,
    ))
    session.commit()
