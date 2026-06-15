from fastapi import APIRouter, Query
from typing import Optional, List
from ..services.alert import get_alert_service

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


@router.get("/")
def list_alerts(
    tent_id: Optional[int] = None,
    hours: int = Query(default=24, le=168),
):
    svc = get_alert_service()
    return svc.get_active_alerts(tent_id=tent_id, hours=hours)


@router.post("/check")
def trigger_alert_check():
    svc = get_alert_service()
    svc.check_alerts()
    return {"status": "ok", "message": "Alert check completed"}
