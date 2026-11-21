import asyncio
import json
import logging
import os
import shutil
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import Lock

import yaml
from sqlmodel import Session, select

from app.config import get_settings
from app.database import engine
from app.models import HostConfig

logger = logging.getLogger(__name__)
_write_lock = Lock()


def write_hosts_to_yaml() -> None:
    """Sync all active HostConfig entries back to hosts.yaml atomically.

    Encrypted secrets are written as [ENCRYPTED] placeholders.
    A .bak backup is kept before overwriting.
    """
    with _write_lock:
        _write_hosts(Path(get_settings().HOST_CONFIG_PATH))


async def sync_hosts_to_yaml() -> None:
    await asyncio.to_thread(write_hosts_to_yaml)


def _write_hosts(config_path: Path) -> None:
    with Session(engine) as session:
        hosts = session.exec(select(HostConfig).order_by(HostConfig.sort_order, HostConfig.host_id)).all()

    hosts_data = []
    for h in hosts:
        host_entry = {
            "host_id": h.host_id,
            "display_name": h.display_name,
            "enabled": h.enabled,
            "sort_order": h.sort_order,
            "traffic_billing_day": h.traffic_billing_day,
        }
        if h.logo:
            host_entry["logo"] = h.logo

        # Agent block
        if h.agent_url:
            host_entry["agent"] = {
                "url": h.agent_url,
                "token": "[ENCRYPTED]" if h.agent_token_encrypted else "",
                "instance_id": h.agent_instance_id or "",
            }

        if h.location_latitude is not None and h.location_longitude is not None:
            host_entry["location"] = {
                "latitude": h.location_latitude,
                "longitude": h.location_longitude,
                "city": h.location_city or "",
                "region": h.location_region or "",
                "country": h.location_country or "",
                "country_code": h.location_country_code or "",
                "source": h.location_source or "manual",
                "confirmed": bool(h.location_confirmed),
                "confidence": h.location_confidence or "",
            }

        if h.public_ip_override:
            host_entry["network_identity"] = {"fixed_public_ip": h.public_ip_override}

        # Stack icons
        try:
            if h.stack_icons:
                host_entry["stack_icons"] = json.loads(h.stack_icons)
        except (json.JSONDecodeError, TypeError):
            logger.warning("Skipping invalid stack_icons JSON for host %s", h.host_id)

        # App profiles
        try:
            if h.app_profiles:
                host_entry["app_profiles"] = json.loads(h.app_profiles)
        except (json.JSONDecodeError, TypeError):
            logger.warning("Skipping invalid app_profiles JSON for host %s", h.host_id)

        hosts_data.append(host_entry)

    output = {"hosts": hosts_data}

    config_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = None
    try:
        with NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=config_path.parent,
            prefix=f".{config_path.name}.", suffix=".tmp", delete=False,
        ) as temp_file:
            temp_path = Path(temp_file.name)
            yaml.safe_dump(output, temp_file, default_flow_style=False, sort_keys=False, allow_unicode=True)
            temp_file.flush()
            os.fsync(temp_file.fileno())

        if config_path.exists():
            try:
                shutil.copy2(config_path, config_path.with_suffix(".yaml.bak"))
            except OSError as exc:
                logger.warning("Failed to create hosts.yaml backup: %s", exc)
        os.replace(temp_path, config_path)
        logger.info("hosts.yaml synced with %d hosts", len(hosts_data))
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
