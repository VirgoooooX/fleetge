"""Fernet-based credential encryption/decryption.

Uses CREDENTIALS_KEY from config — a separate key from JWT_SECRET.
Key must be a 32-byte URL-safe base64 string (Fernet format).
"""

import json
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings

_fernet: Optional[Fernet] = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        settings = get_settings()
        _fernet = Fernet(settings.CREDENTIALS_KEY.encode("utf-8"))
    return _fernet


def encrypt_credentials(username: str, password: str) -> str:
    """Encrypt structured credentials into a Fernet token string.

    The stored ciphertext is a JSON blob: {"username": ..., "password": ...}
    encrypted with Fernet.
    """
    data = json.dumps({"username": username, "password": password})
    return _get_fernet().encrypt(data.encode("utf-8")).decode("utf-8")


def decrypt_credentials(ciphertext: str) -> dict:
    """Decrypt a Fernet token to structured credentials.

    Returns {"username": str, "password": str}.
    Raises ValueError on invalid or tampered data.
    """
    try:
        plain = _get_fernet().decrypt(ciphertext.encode("utf-8"))
    except InvalidToken:
        raise ValueError("Invalid or tampered credential ciphertext")
    return json.loads(plain.decode("utf-8"))


def encrypt_authorization_header(username: str, password: str) -> str:
    """Encrypt credentials and return the 'Authorization' header value.

    Stores the full Base64-encoded Basic Auth header inside the Fernet token,
    so callers don't need to re-encode.
    """
    import base64

    raw = f"{username}:{password}"
    encoded = base64.b64encode(raw.encode("utf-8")).decode("utf-8")
    header_value = f"Basic {encoded}"
    return _get_fernet().encrypt(header_value.encode("utf-8")).decode("utf-8")


def decrypt_authorization_header(ciphertext: str) -> str:
    """Decrypt to an 'Authorization' header value ready for HTTP requests."""
    try:
        return _get_fernet().decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        raise ValueError("Invalid or tampered auth header ciphertext")


def encrypt_string(plain: str) -> str:
    """Encrypt a plain string using the Fernet credentials key."""
    return _get_fernet().encrypt(plain.encode("utf-8")).decode("utf-8")


def decrypt_string(ciphertext: str) -> str:
    """Decrypt a Fernet cipher string back to plain text."""
    try:
        return _get_fernet().decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        raise ValueError("Invalid or tampered string ciphertext")

