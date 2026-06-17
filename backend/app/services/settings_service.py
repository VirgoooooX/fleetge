"""Settings lookup service — DB-first with env fallback and in-memory cache.

NOTE: _SETTINGS_CACHE is process-local. This design assumes single-worker
deployment (uvicorn without multiple workers). If scaling to multi-worker,
add TTL expiry or switch to shared cache.
"""

import logging
import os
from typing import Optional
from sqlmodel import Session, select

logger = logging.getLogger(__name__)

# In-memory settings cache (single-worker only — see module docstring)
_SETTINGS_CACHE: dict[str, str] = {}

SYSTEM_DEFAULTS = {
    "DOCKER_POLL_INTERVAL": "10",
    "METRICS_STREAM_INTERVAL": "1",
    "BACKGROUND_STRUCTURE_REFRESH_INTERVAL": "3600",
    "UPDATE_CHECK_INTERVAL": "43200",
    "ADMIN_USERNAME": "admin",
    "JWT_EXPIRE_HOURS": "24",
}

WRITABLE_KEYS = set(SYSTEM_DEFAULTS.keys())

READ_ONLY_KEYS = {
    "JWT_SECRET",
    "CREDENTIALS_KEY",
    "ADMIN_PASSWORD_HASH",
}


def get_setting_value(key: str, default: Optional[str] = None) -> str:
    """Retrieve setting value: Cache → DB → Env → Hardcoded default."""
    if key in _SETTINGS_CACHE:
        return _SETTINGS_CACHE[key]

    # 1. DB lookup (lazy import to avoid circular dependency with database.py)
    try:
        from app.database import engine
        from app.models import Setting

        with Session(engine) as session:
            record = session.exec(
                select(Setting).where(Setting.setting_key == key)
            ).first()
            if record:
                _SETTINGS_CACHE[key] = record.setting_value
                return record.setting_value
    except Exception as exc:
        logger.debug("DB settings read failed, falling back to env: %s", exc)

    # 2. Environment variable
    env_val = os.environ.get(key)
    if env_val is not None:
        _SETTINGS_CACHE[key] = env_val
        return env_val

    # 3. Hardcoded default
    fallback = default or SYSTEM_DEFAULTS.get(key, "")
    _SETTINGS_CACHE[key] = fallback
    return fallback


def update_setting_value(session: Session, key: str, value: str) -> None:
    """Write setting to DB and invalidate cache. Caller must commit."""
    if key not in WRITABLE_KEYS:
        raise ValueError(f"Setting '{key}' is read-only.")

    from app.models import Setting

    record = session.exec(
        select(Setting).where(Setting.setting_key == key)
    ).first()

    if record:
        record.setting_value = str(value)
    else:
        session.add(Setting(setting_key=key, setting_value=str(value)))

    _SETTINGS_CACHE.pop(key, None)


def clear_cache() -> None:
    """Invalidate all cached settings (called after bulk update)."""
    _SETTINGS_CACHE.clear()


def populate_defaults_if_empty() -> None:
    """Seed settings table on first startup. Prefers env vars over hardcoded."""
    from app.database import engine
    from app.models import Setting

    with Session(engine) as session:
        existing = session.exec(select(Setting)).all()
        if len(existing) == 0:
            logger.info("Seeding settings table with defaults...")
            for key, val in SYSTEM_DEFAULTS.items():
                initial_val = os.environ.get(key, val)
                session.add(Setting(setting_key=key, setting_value=str(initial_val)))
            session.commit()
            _SETTINGS_CACHE.clear()
