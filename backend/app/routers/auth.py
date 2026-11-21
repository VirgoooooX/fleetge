"""Auth router — login, logout, me."""

import hmac
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlmodel import Session

from app.auth.handler import (
    create_access_token,
    get_current_user,
    rate_limiter,
    verify_password,
)
from app.config import get_settings
from app.database import get_session
from app.schemas import LoginRequest, LoginResponse, MeResponse
from app.services.network_utils import resolve_request_source_ip

router = APIRouter(prefix="/api", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
async def login(
    req: LoginRequest,
    request: Request,
    session: Session = Depends(get_session),
):
    """Authenticate and return a JWT token.

    Rate-limited: 5 failures per 15 min per IP.
    """
    ip = resolve_request_source_ip(request) or "unknown"

    if rate_limiter.is_blocked(ip):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts. Try again later.",
        )

    settings = get_settings()

    # Verify credentials against env-configured admin
    if not hmac.compare_digest(req.username, settings.ADMIN_USERNAME):
        rate_limiter.record_failure(ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    if not verify_password(req.password, settings.ADMIN_PASSWORD):
        rate_limiter.record_failure(ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    # Success — clear rate limit for this IP
    rate_limiter.clear(ip)

    token = create_access_token(req.username)
    return LoginResponse(token=token)


@router.get("/me", response_model=MeResponse)
async def me(username: str = Depends(get_current_user)):
    """Return the current authenticated user's info."""
    return MeResponse(username=username)


@router.post("/logout")
async def logout(username: str = Depends(get_current_user)):
    """Logout — client-side token discard. Server has no session store in v1."""
    return {"message": "Logged out (discard your token client-side)"}
