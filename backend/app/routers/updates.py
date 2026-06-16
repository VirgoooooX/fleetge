"""Update check router — run manual checks, get cached results."""

from fastapi import APIRouter, Depends, Request
from sqlmodel import Session

from app.auth.handler import get_current_user
from app.database import get_session
from app.models import AuditLog
from app.schemas import UpdateCheckResult, UpdateCheckRunResponse
from app.services.snapshot import snapshot_manager
from app.services.update_check import clear_cache

router = APIRouter(
    prefix="/api",
    tags=["update_checks"],
    dependencies=[Depends(get_current_user)],
)


@router.get("/update-checks", response_model=list[UpdateCheckResult])
async def get_update_checks():
    """Return cached update check results for all hosts.

    Results are refreshed every 12h by default by the background task,
    or immediately by POST /api/update-checks/run.
    """
    return snapshot_manager.get_update_check_results()


@router.post("/update-checks/run", response_model=UpdateCheckRunResponse)
async def run_manual_update_check(
    request: Request,
    session: Session = Depends(get_session),
    username: str = Depends(get_current_user),
):
    """Clear the update check cache and trigger a fresh check for all hosts.

    This may take a while depending on the number of images.
    """
    clear_cache()

    # Log the action
    log = AuditLog(
        user=username,
        action="update_checks.run",
        result="success",
        detail="Manual update check triggered",
        ip_address=request.client.host if request.client else None,
    )
    session.add(log)
    session.commit()

    results = await snapshot_manager.refresh_update_checks_now()
    return UpdateCheckRunResponse(started=True, results=results)
