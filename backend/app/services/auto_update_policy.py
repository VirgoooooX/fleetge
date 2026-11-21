"""Stack policy persistence and eligibility rules for updates."""

from sqlmodel import Session, select

from app.models import AutoUpdateRun, StackAutoUpdate


def _find_policy(session: Session, host_id: str, stack_name: str) -> StackAutoUpdate | None:
    return session.exec(select(StackAutoUpdate).where(
        StackAutoUpdate.host_id == host_id,
        StackAutoUpdate.stack_name == stack_name,
    )).first()


def stack_policy(session: Session, host_id: str, stack_name: str) -> StackAutoUpdate:
    return _find_policy(session, host_id, stack_name) or StackAutoUpdate(host_id=host_id, stack_name=stack_name)


def policy_map(session: Session, host_id: str) -> dict[str, StackAutoUpdate]:
    rows = session.exec(select(StackAutoUpdate).where(StackAutoUpdate.host_id == host_id)).all()
    return {row.stack_name: row for row in rows}


def stack_summaries(snap, policies: dict[str, StackAutoUpdate]) -> list:
    return [stack.model_copy(update={
        "auto_update_enabled": policies[stack.name].enabled if stack.name in policies else False,
        "auto_update_reason": policies[stack.name].reason if stack.name in policies else "",
    }) for stack in snap.stacks]


def set_policy(session: Session, host_id: str, stack_name: str, enabled: bool) -> StackAutoUpdate:
    row = stack_policy(session, host_id, stack_name)
    row.enabled = enabled
    row.reason = ""
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def disable_policy_on_failure(session: Session, run: AutoUpdateRun) -> None:
    if run.source != "auto" or run.status not in {"partial", "failed", "uncertain"}:
        return
    policy = _find_policy(session, run.host_id, run.stack_name)
    if policy is not None:
        policy.enabled = False
        policy.reason = run.detail
        session.add(policy)


def ingress_services(snap, stack_name: str, ingress: dict) -> list[str]:
    """Services of this stack that currently hold the agent's ingress ports."""
    services = []
    for item in ingress.get("services") or []:
        if not isinstance(item, dict) or item.get("stack_name") != stack_name:
            continue
        service = str(item.get("service_name") or "")
        if service and any(
            container.stack_name == stack_name and container.service_name == service
            for container in snap.containers
        ):
            services.append(service)
    return services


def control_stack(snap, stack_name: str, self_info: dict) -> bool:
    if self_info.get("stack_name") == stack_name:
        return True
    for container in snap.containers:
        if container.stack_name != stack_name:
            continue
        repository = container.image.split("@", 1)[0].rsplit("/", 1)[-1].split(":", 1)[0]
        if repository in {"fleetge", "fleetge-agent"}:
            return True
    return False


def bulk_skip_reason(stack, is_control_stack: bool) -> str:
    if is_control_stack:
        return "Fleetge／Agent 自身所在的 Stack，请使用单独更新入口。"
    if stack.management_status == "unmanaged":
        return "该 Stack 没有可管理的 Compose 配置。"
    if stack.status != "running":
        return "Stack 当前未运行，未提交更新。"
    return ""


def can_run_stack(snap, stack_name: str) -> bool:
    if not snap or not snap.host_config or not snap.host_config.enabled or not snap.host_config.agent_url or snap.status != "online":
        return False
    stack = next((stack for stack in snap.stacks if stack.name == stack_name), None)
    return bool(stack and stack.status == "running" and stack.management_status != "unmanaged")
