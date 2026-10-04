"""Security & Compliance Center API. Same access rule as the rest of the API (require_api_key)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.api.deps import require_api_key
from backend.db.base import get_db
from backend.db.models import AccessEvent
from backend.security import checks as C

router = APIRouter(prefix="/security", dependencies=[Depends(require_api_key)])


@router.get("/overview")
def overview(db: Session = Depends(get_db)):
    health = C.system_health()
    try:
        rls = C.rls_status()
    except Exception as exc:  # noqa: BLE001
        rls = {"status": C.U, "verification": C.U, "detail": f"Couldn't check: {type(exc).__name__}", "tables": []}
    posture = C.security_posture()
    rls_factor = C._chk("Row-level security", rls["status"], rls["detail"], verified=rls["verification"] == C.V,
                        weight=2 if rls["verification"] == C.V else 0, passed=rls["status"] == "Enabled" if rls["verification"] == C.V else None,
                        category="Configuration")
    factors = health + posture + [rls_factor]
    return {"checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "health": health, "posture": posture,
            "rls": rls, "configuration": C.configuration(), "alerts": C.alerts(db, health, rls),
            "activity_24h": C.events_summary(db, 24), "score": C.score(factors)}


@router.get("/events")
def events(kind: str | None = Query(None, pattern="^(auth|access)$"), outcome: str | None = Query(None, pattern="^(success|failure|denied)$"),
           days: int = Query(7, ge=1, le=90), limit: int = Query(200, le=1000), db: Session = Depends(get_db)):
    q = select(AccessEvent).where(AccessEvent.created_at >= datetime.now(timezone.utc) - timedelta(days=days)).order_by(AccessEvent.created_at.desc()).limit(limit)
    if kind:
        q = q.where(AccessEvent.kind == kind)
    if outcome:
        q = q.where(AccessEvent.outcome == outcome)
    return [{"at": e.created_at.isoformat() if e.created_at else None, "kind": e.kind, "action": e.action, "outcome": e.outcome,
             "actor": e.actor, "ip": e.ip_masked, "method": e.method, "path": e.path, "resource_id": e.resource_id,
             "status_code": e.status_code, "client": e.user_agent} for e in db.execute(q).scalars()]
