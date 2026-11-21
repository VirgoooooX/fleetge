"""Authentication handler — password verification, JWT, admin RBAC, and login rate limiting."""

import hashlib
import hmac
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.config import get_settings

# ── Password verification ─────────────────────────────────────────────────

_PBKDF2_PREFIX = "pbkdf2_sha256$"
_PBKDF2_ITERATIONS = 210_000


def hash_password(password: str) -> str:
    """Hash a password using PBKDF2-HMAC-SHA256 with a random 16-byte salt."""
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        _PBKDF2_ITERATIONS,
    ).hex()
    return f"{_PBKDF2_PREFIX}{_PBKDF2_ITERATIONS}${salt}${digest}"


def verify_password(plain: str, expected: str) -> bool:
    """Verify a password against either a PBKDF2 hash or plaintext using constant-time comparison."""
    if not expected:
        return False
    if expected.startswith(_PBKDF2_PREFIX):
        parts = expected.split("$")
        if len(parts) != 4:
            return False
        _, iter_str, salt, expected_hex = parts
        try:
            iterations = int(iter_str)
        except ValueError:
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            plain.encode("utf-8"),
            salt.encode("utf-8"),
            iterations,
        ).hex()
        return hmac.compare_digest(digest, expected_hex)
    return hmac.compare_digest(plain, expected)


# ── JWT ─────────────────────────────────────────────────────────────────

security_scheme = HTTPBearer(auto_error=False)


def create_access_token(username: str) -> str:
    """Create a JWT access token with username claim and expiration."""
    settings = get_settings()
    now = datetime.now(timezone.utc)
    expire = now + timedelta(hours=settings.JWT_EXPIRE_HOURS)
    payload = {"sub": username, "exp": expire, "iat": now}
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> Optional[str]:
    """Decode a JWT token and return the username. Returns None on any error."""
    settings = get_settings()
    try:
        payload = jwt.decode(
            token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM]
        )
        return payload.get("sub")
    except jwt.PyJWTError:
        return None


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security_scheme),
) -> str:
    """FastAPI dependency: extract and validate the current user from Bearer token."""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    username = decode_access_token(credentials.credentials)
    if username is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )
    return username


async def require_admin(
    username: str = Depends(get_current_user),
) -> str:
    """FastAPI dependency: require the authenticated user to match ADMIN_USERNAME."""
    expected_admin = get_settings().ADMIN_USERNAME
    if not hmac.compare_digest(username, expected_admin):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator access required",
        )
    return username


# ── Login rate limiter (in-memory, single-worker) ──────────────────────


class LoginRateLimiter:
    """Bounded sliding-window login rate limiter.

    Allows up to `max_attempts` failed logins per `window_seconds` per IP.
    """

    def __init__(self, max_attempts: int = 5, window_seconds: int = 900, max_tracked_ips: int = 4096):
        self._max = max_attempts
        self._window = window_seconds
        self._max_tracked = max_tracked_ips
        self._attempts: dict[str, list[float]] = {}

    def _prune_key(self, ip: str, now: float) -> list[float]:
        window_start = now - self._window
        valid = [t for t in self._attempts.get(ip, ()) if t > window_start]
        if valid:
            self._attempts[ip] = valid
        else:
            self._attempts.pop(ip, None)
        return valid

    def record_failure(self, ip: str) -> bool:
        """Record a failed login attempt. Returns True if the IP is now blocked."""
        now = time.monotonic()
        if ip not in self._attempts and len(self._attempts) >= self._max_tracked:
            # Purge expired entries first, then oldest entry if still full
            window_start = now - self._window
            for k in list(self._attempts.keys()):
                if not any(t > window_start for t in self._attempts[k]):
                    self._attempts.pop(k, None)
            if len(self._attempts) >= self._max_tracked:
                oldest = min(self._attempts.items(), key=lambda item: item[1][-1])[0]
                self._attempts.pop(oldest, None)

        valid = self._prune_key(ip, now)
        valid.append(now)
        self._attempts[ip] = valid
        return len(valid) >= self._max

    def is_blocked(self, ip: str) -> bool:
        """Check if an IP is currently rate-limited without allocating empty entries."""
        if ip not in self._attempts:
            return False
        valid = self._prune_key(ip, time.monotonic())
        return len(valid) >= self._max

    def clear(self, ip: str) -> None:
        """Clear all failed attempts for a given IP (e.g. after successful login)."""
        self._attempts.pop(ip, None)


rate_limiter = LoginRateLimiter()
