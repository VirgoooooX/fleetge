import json
import os
import logging
import yaml
from pathlib import Path
from sqlmodel import Session, select

from app.config import get_settings
from app.database import engine
from app.models import HostConfig

logger = logging.getLogger(__name__)


def write_hosts_to_yaml() -> None:
    """Sync all active HostConfig entries back to hosts.yaml atomically.

    Encrypted secrets are written as [ENCRYPTED] placeholders.
    A .bak backup is kept before overwriting.
    """
    settings = get_settings()
    config_path = Path(settings.HOST_CONFIG_PATH)

    with Session(engine) as session:
        hosts = session.exec(select(HostConfig)).all()

    hosts_data = []
    for h in hosts:
        host_entry = {
            "host_id": h.host_id,
            "display_name": h.display_name,
            "enabled": h.enabled,
            "sort_order": h.sort_order,
        }

        # Agent block
        if h.agent_url:
            host_entry["agent"] = {
                "url": h.agent_url,
                "token": "[ENCRYPTED]" if h.agent_token_encrypted else ""
            }



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

    # Backup existing file before overwrite
    if config_path.exists():
        bak_path = config_path.with_suffix(".yaml.bak")
        try:
            import shutil
            shutil.copy2(config_path, bak_path)
        except Exception as exc:
            logger.warning("Failed to create hosts.yaml backup: %s", exc)

    # Atomic file replacement
    temp_file = config_path.with_suffix(".tmp")
    config_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(temp_file, "w", encoding="utf-8") as f:
            yaml.safe_dump(output, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_file, config_path)
        logger.info("hosts.yaml synced with %d hosts", len(hosts_data))
    except Exception as exc:
        logger.error("Failed to write to config path %s: %s", config_path, exc)
        if os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except Exception:
                pass
        raise
