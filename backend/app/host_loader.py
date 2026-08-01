"""Host config loader — reads hosts from a YAML file and seeds the database."""

import json
import logging
from pathlib import Path
from typing import Optional

import yaml
from sqlmodel import Session, select

from app.config import get_settings
from app.database import engine
from app.models import HostConfig
from app.services.crypto import encrypt_string

logger = logging.getLogger(__name__)


def load_hosts_from_yaml() -> int:
    """Read the HOST_CONFIG_PATH YAML file and upsert into the database.

    YAML format:
    ```yaml
    hosts:
      - host_id: oc-chicago
        display_name: OC Chicago
        agent:
          url: http://localhost:8080
          token: "secret-token"
        sort_order: 1
        enabled: true
    ```

    Returns the number of hosts loaded/updated.
    """
    settings = get_settings()
    config_path = Path(settings.HOST_CONFIG_PATH)

    if not config_path.exists() or config_path.is_dir():
        logger.warning("Host config file not found: %s", config_path)
        return 0

    with config_path.open("r", encoding="utf-8-sig") as f:
        data = yaml.safe_load(f)

    if not data or "hosts" not in data:
        logger.warning("No 'hosts' key found in %s", config_path)
        return 0

    count = 0
    with Session(engine) as session:
        for entry in data["hosts"]:
            host_id = entry.get("host_id", "")
            if not host_id:
                continue

            agent = entry.get("agent", {})
            location = entry.get("location", {}) or {}

            # 1. Fetch existing host config first
            existing = session.exec(
                select(HostConfig).where(HostConfig.host_id == host_id)
            ).first()

            # 2. agent token
            agent_url = agent.get("url")
            agent_token = agent.get("token", "")
            if agent_token == "[ENCRYPTED]":
                if existing:
                    agent_token_encrypted = existing.agent_token_encrypted
                else:
                    logger.warning("Ignoring [ENCRYPTED] agent token for new host %s", host_id)
                    agent_token_encrypted = None
            else:
                agent_token_encrypted = None
                if agent_url and agent_token:
                    agent_token_encrypted = encrypt_string(agent_token)

            # Upsert
            if existing:
                existing.display_name = entry.get("display_name", host_id)
                existing.enabled = entry.get("enabled", True)
                existing.sort_order = entry.get("sort_order", 0)
                existing.agent_url = agent_url
                existing.agent_token_encrypted = agent_token_encrypted
                existing.agent_instance_id = agent.get("instance_id") or existing.agent_instance_id
                if location:
                    existing.location_latitude = location.get("latitude")
                    existing.location_longitude = location.get("longitude")
                    existing.location_city = location.get("city") or None
                    existing.location_region = location.get("region") or None
                    existing.location_country = location.get("country") or None
                    existing.location_country_code = location.get("country_code") or None
                    existing.location_source = location.get("source") or "manual"
                    existing.location_confirmed = bool(location.get("confirmed", False))
                # Stack icons
                stack_icons = entry.get("stack_icons")
                existing.stack_icons = json.dumps(stack_icons, ensure_ascii=False) if stack_icons else None
                # App profiles
                app_profiles = entry.get("app_profiles")
                existing.app_profiles = json.dumps(app_profiles, ensure_ascii=False) if app_profiles else None
            else:
                host = HostConfig(
                    host_id=host_id,
                    display_name=entry.get("display_name", host_id),
                    enabled=entry.get("enabled", True),
                    sort_order=entry.get("sort_order", 0),
                    agent_url=agent_url,
                    agent_token_encrypted=agent_token_encrypted,
                    agent_instance_id=agent.get("instance_id") or None,
                    location_latitude=location.get("latitude"),
                    location_longitude=location.get("longitude"),
                    location_city=location.get("city") or None,
                    location_region=location.get("region") or None,
                    location_country=location.get("country") or None,
                    location_country_code=location.get("country_code") or None,
                    location_source=location.get("source") or None,
                    location_confirmed=bool(location.get("confirmed", False)),
                    stack_icons=json.dumps(stack_icons, ensure_ascii=False) if (stack_icons := entry.get("stack_icons")) else None,
                    app_profiles=json.dumps(app_profiles, ensure_ascii=False) if (app_profiles := entry.get("app_profiles")) else None,
                )
                session.add(host)

            count += 1

        session.commit()

    logger.info("Loaded %d hosts from %s", count, config_path)
    return count
