"""Update check router — run manual checks, get cached results."""

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlmodel import Session

from app.auth.handler import get_current_user
from app.database import get_session
from app.models import AuditLog
from app.schemas import UpdateCheckResult, UpdateCheckRunResponse
from app.services.snapshot import snapshot_manager

router = APIRouter(
    prefix="/api",
    tags=["update_checks"],
    dependencies=[Depends(get_current_user)],
)


@router.get("/update-checks", response_model=list[UpdateCheckResult])
async def get_update_checks(
    response: Response,
    include_failures: bool = Query(default=False),
):
    """Return cached update check results for all hosts.

    Results are refreshed every 12h by default by the background task,
    or immediately by POST /api/update-checks/run.
    """
    response.headers["X-Update-Check-Running"] = (
        "1" if snapshot_manager.is_update_check_running() else "0"
    )
    return snapshot_manager.get_update_check_results(include_failures=include_failures)


@router.post("/update-checks/run", response_model=UpdateCheckRunResponse)
async def run_manual_update_check(
    request: Request,
    include_failures: bool = Query(default=False),
    session: Session = Depends(get_session),
    username: str = Depends(get_current_user),
):
    """Trigger a fresh update check for all hosts.

    Returns ``started=True`` with fresh results when this call ran the sweep,
    or ``started=False`` with the current cache when a manual sweep is already
    in flight — the second trigger is coalesced rather than queued, so it never
    doubles registry traffic. The frontend should treat ``started=False`` as
    "results are still being computed; showing the last known state".

    This may take a while depending on the number of images.
    """
    started, results = await snapshot_manager.try_refresh_update_checks_now(
        include_failures=include_failures
    )

    log = AuditLog(
        user=username,
        action="update_checks.run",
        result="success",
        detail=(
            "Manual update check ran" if started
            else "Manual update check skipped: another run is in progress"
        ),
        ip_address=request.client.host if request.client else None,
    )
    session.add(log)
    session.commit()

    return UpdateCheckRunResponse(started=started, results=results)
