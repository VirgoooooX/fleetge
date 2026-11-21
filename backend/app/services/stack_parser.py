"""Parse and combine Agent stacks, Compose containers and app profiles."""

import json
import logging

from app.models import HostConfig
from app.schemas import ContainerSummary, StackService, StackSummary

logger = logging.getLogger(__name__)


def parse_agent_stacks(raw_stacks: list) -> list[StackSummary]:
    """Parse raw Agent stacks payload into StackSummary schemas."""
    stacks: list[StackSummary] = []
    for s in raw_stacks:
        name = s.get("name", s.get("Name", ""))
        services_raw = s.get("services", s.get("Services", [])) or []
        compose_file = s.get("composeFile", s.get("filePath"))

        svcs: list[StackService] = []
        running = 0
        for svc in services_raw:
            state = svc.get("state", svc.get("State", "unknown"))
            if state == "running":
                running += 1
            svcs.append(
                StackService(
                    name=svc.get("name", svc.get("Name", "")),
                    container_id=svc.get("containerId"),
                    state=state,
                    status=svc.get("status", ""),
                )
            )

        # Overall stack status
        if not svcs:
            raw_status = s.get("status")
            if raw_status in ("inactive", "stopped"):
                overall = "stopped"
            elif raw_status == "exited":
                overall = "exited"
            elif raw_status in ("active", "running"):
                overall = "running"
            elif raw_status in ("partial", "partially running"):
                overall = "partially running"
            elif raw_status is None:
                overall = "stopped"
            else:
                overall = raw_status or "unknown"
        elif running == len(svcs):
            overall = "running"
        elif running == 0:
            if any(svc.state == "exited" for svc in svcs):
                overall = "exited"
            else:
                overall = "stopped"
        else:
            overall = "partially running"

        stacks.append(
            StackSummary(
                name=name,
                status=overall,
                compose_file=compose_file,
                service_count=len(svcs),
                running_count=running,
                services=svcs,
                management_status=s.get("management_status", s.get("managementStatus", "managed")),
            )
        )
    return stacks


def apply_app_profiles(
    stacks: list[StackSummary], cfg: HostConfig | None,
) -> list[StackSummary]:
    """Apply app profile metadata and fallback icons to stack summaries."""
    if cfg is None:
        return stacks

    profiles: list[dict] = []
    if cfg.app_profiles:
        try:
            parsed = json.loads(cfg.app_profiles)
            if isinstance(parsed, list):
                profiles = parsed
        except Exception as e:
            logger.warning("Failed to parse app_profiles JSON for host %s: %s", cfg.host_id, e)

    stack_icons_mapping: dict[str, str] = {}
    if cfg.stack_icons:
        try:
            parsed_icons = json.loads(cfg.stack_icons)
            if isinstance(parsed_icons, dict):
                stack_icons_mapping = parsed_icons
        except Exception as e:
            logger.warning("Failed to parse stack_icons JSON for host %s: %s", cfg.host_id, e)

    for stack in stacks:
        matched = _match_profile(stack.name, profiles)

        if matched and matched.get("title"):
            stack.title = matched["title"]
        else:
            stack.title = _format_stack_title(stack.name)

        if matched and matched.get("app_url"):
            stack.app_url = matched["app_url"]
        else:
            stack.app_url = None

        if matched and matched.get("group"):
            stack.group = matched["group"]
        else:
            stack.group = "未分组"

        icon_val = None
        if matched and matched.get("icon_value"):
            icon_val = matched["icon_value"]
        else:
            icon_val = _match_icon(stack.name, stack_icons_mapping)

        if icon_val:
            if icon_val.startswith("http://") or icon_val.startswith("https://"):
                stack.icon_url = icon_val
            else:
                filename = icon_val.lstrip("/")
                stack.icon_url = f"/api/static/icons/{filename}"
        else:
            stack.icon_url = None

    return stacks

def _format_stack_title(name: str) -> str:
    s = name.replace("-", " ").replace("_", " ")
    return s.title()

def _match_profile(name: str, profiles: list[dict]) -> dict | None:
    # Priority: exact match > prefix wildcard (key*) > suffix wildcard (*key).
    # 1. Exact match
    for p in profiles:
        pattern = p.get("stack_pattern", "")
        if pattern == name:
            return p

    # 2. Prefix wildcard (e.g. key*)
    for p in profiles:
        pattern = p.get("stack_pattern", "")
        if pattern.endswith("*") and not pattern.startswith("*"):
            prefix = pattern[:-1]
            if name.startswith(prefix):
                return p

    # 3. Suffix wildcard (e.g. *key)
    for p in profiles:
        pattern = p.get("stack_pattern", "")
        if pattern.startswith("*") and not pattern.endswith("*"):
            suffix = pattern[1:]
            if name.endswith(suffix):
                return p

    return None

def _match_icon(name: str, mapping: dict[str, str]) -> str | None:
    """Match a stack name against icon mapping keys.

    Priority: exact match > prefix wildcard (``key*``) > suffix wildcard (``*key``).
    """
    # 1. Exact match
    if name in mapping:
        return mapping[name]

    # 2. Prefix wildcard (e.g. key*)
    for key, value in mapping.items():
        if key.endswith("*") and not key.startswith("*"):
            if name.startswith(key[:-1]):
                return value

    # 3. Suffix wildcard (e.g. *key)
    for key, value in mapping.items():
        if key.startswith("*") and not key.endswith("*"):
            if name.endswith(key[1:]):
                return value

    return None


def merge_stacks_with_container_labels(
    agent_stacks: list[StackSummary], containers: list[ContainerSummary],
) -> list[StackSummary]:
    """Fill missing Agent stack states from Docker Compose labels.

    Some Agent versions may return only the stack names.
    When that happens the UI would show ``unknown`` even though the
    Agent already has reliable container state and compose
    labels for the same stacks.
    """
    label_stacks = stacks_from_container_labels(containers)
    label_by_name = {stack.name: stack for stack in label_stacks}

    merged: list[StackSummary] = []
    seen: set[str] = set()
    for stack in agent_stacks:
        seen.add(stack.name)
        fallback = label_by_name.get(stack.name)
        if fallback and not stack.services:
            merged.append(
                StackSummary(
                    name=stack.name,
                    status=fallback.status,
                    compose_file=stack.compose_file or fallback.compose_file,
                    service_count=fallback.service_count,
                    running_count=fallback.running_count,
                    services=fallback.services,
                    icon_url=stack.icon_url,
                    management_status="deployed",
                )
            )
        else:
            if stack.management_status == "managed":
                stack.management_status = "deployed" if fallback else "file-only"
            merged.append(stack)

    for stack in label_stacks:
        if stack.name not in seen:
            stack.management_status = "unmanaged"
            merged.append(stack)

    return merged


def stacks_from_container_labels(container_rows: list[ContainerSummary]) -> list[StackSummary]:
    """Build stack summaries from Docker Compose labels."""
    grouped: dict[str, list[ContainerSummary]] = {}
    for container in container_rows:
        if not container.stack_name:
            continue
        grouped.setdefault(container.stack_name, []).append(container)

    stacks: list[StackSummary] = []
    for stack_name, containers in sorted(grouped.items()):
        services: list[StackService] = []
        running = 0
        for container in containers:
            if container.state == "running":
                running += 1
            services.append(
                StackService(
                    name=container.service_name or container.name,
                    container_id=container.id,
                    state=container.state,
                    status=container.status,
                )
            )

        if running == len(services):
            overall = "running"
        elif running == 0:
            if any(svc.state == "exited" for svc in services):
                overall = "exited"
            else:
                overall = "stopped"
        else:
            overall = "partially running"

        compose_file = None
        labels = containers[0].labels if containers else {}
        if labels:
            compose_file = labels.get("com.docker.compose.project.config_files")

        stacks.append(
            StackSummary(
                name=stack_name,
                status=overall,
                compose_file=compose_file,
                service_count=len(services),
                running_count=running,
                services=services,
            )
        )

    return stacks
