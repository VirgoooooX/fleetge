"""Application configuration — all values from environment variables."""

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
import yaml

# Auto-load .env from project root (works whether cwd is backend/ or project root)
_ROOT = Path(__file__).resolve().parent.parent.parent  # backend/app/ → backend/ → root
_ENV_FILE = _ROOT / ".env"
if _ENV_FILE.exists():
    load_dotenv(_ENV_FILE, override=False)  # override=False: don't override existing env vars

# Default paths resolved relative to project root (not CWD)
# docker-compose.yml overrides these for production via environment:
_ROOT_DATA_DIR = str(_ROOT / "data")


class Settings:
    # ── Auth ──────────────────────────────────────────────────────────
    JWT_SECRET: str = os.environ.get("JWT_SECRET", "")
    JWT_ALGORITHM: str = "HS256"

    @property
    def JWT_EXPIRE_HOURS(self) -> int:
        from app.services.settings_service import get_setting_value
        return int(get_setting_value("JWT_EXPIRE_HOURS", "24"))

    # Admin account (created on first start if missing)
    @property
    def ADMIN_USERNAME(self) -> str:
        from app.services.settings_service import get_setting_value
        return get_setting_value("ADMIN_USERNAME", "admin")

    ADMIN_PASSWORD_HASH: str = os.environ.get("ADMIN_PASSWORD_HASH", "")

    # ── Credential encryption ─────────────────────────────────────────
    # 32-byte URL-safe base64 Fernet key, separate from JWT_SECRET.
    CREDENTIALS_KEY: str = os.environ.get("CREDENTIALS_KEY", "")

    # ── Database ──────────────────────────────────────────────────────
    DATABASE_URL: str = os.environ.get(
        "DATABASE_URL", f"sqlite:///{_ROOT_DATA_DIR}/dashboard-local.db"
    )

    # ── Host configuration (YAML file) ────────────────────────────────
    HOST_CONFIG_PATH: str = os.environ.get(
        "HOST_CONFIG_PATH", str(_ROOT / "data" / "hosts.yaml")
    )

    # ── Poll intervals (seconds) ──────────────────────────────────────
    @property
    def METRICS_STREAM_INTERVAL(self) -> float:
        from app.services.settings_service import get_setting_value
        return float(get_setting_value("METRICS_STREAM_INTERVAL", "1"))

    @property
    def DOCKER_POLL_INTERVAL(self) -> int:
        from app.services.settings_service import get_setting_value
        return int(get_setting_value("DOCKER_POLL_INTERVAL", "10"))

    @property
    def BACKGROUND_STRUCTURE_REFRESH_INTERVAL(self) -> int:
        from app.services.settings_service import get_setting_value
        return int(get_setting_value("BACKGROUND_STRUCTURE_REFRESH_INTERVAL", "3600"))

    @property
    def UPDATE_CHECK_INTERVAL(self) -> int:
        from app.services.settings_service import get_setting_value
        return int(get_setting_value("UPDATE_CHECK_INTERVAL", "43200"))

    # ── Uvicorn ───────────────────────────────────────────────────────
    LOG_LEVEL: str = os.environ.get("LOG_LEVEL", "info")

    # ── CORS ──────────────────────────────────────────────────────────
    # Comma-separated origins allowed for browser CORS.
    # Default: empty (same-origin only via nginx), set to
    # "http://127.0.0.1:5173,http://localhost:5173" for dev.
    CORS_ORIGINS: str = os.environ.get("CORS_ORIGINS", "")

    def validate(self):
        errors: list[str] = []
        if not self.JWT_SECRET:
            errors.append("JWT_SECRET is required")
        if not self.CREDENTIALS_KEY:
            errors.append("CREDENTIALS_KEY is required")
        else:
            # Validate Fernet key format (32-byte URL-safe base64)
            import base64

            try:
                key_bytes = base64.urlsafe_b64decode(self.CREDENTIALS_KEY)
                if len(key_bytes) != 32:
                    errors.append(
                        f"CREDENTIALS_KEY decoded to {len(key_bytes)} bytes, expected 32"
                    )
            except Exception:
                errors.append(
                    "CREDENTIALS_KEY is not valid URL-safe base64. "
                    "Generate one with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
                )
        if not self.ADMIN_PASSWORD_HASH:
            errors.append("ADMIN_PASSWORD_HASH is required (use pwdlib to hash the admin password)")
        if errors:
            raise ValueError("Configuration errors:\n  - " + "\n  - ".join(errors))


@lru_cache()
def get_settings() -> Settings:
    s = Settings()
    s.validate()
    return s
