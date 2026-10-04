"""AI endpoints. All read-only: they never change invoices, findings, ITC or reconciliation.
Same access rule as the rest of the API (require_api_key). OpenRouter is called only from
here (server-side); its key is never sent to the browser."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.ai import copilot, facts as F, search as S
from backend.api.deps import require_api_key
from backend.db.base import get_db
from backend.llm.explain import explain_facts

router = APIRouter(prefix="/ai", dependencies=[Depends(require_api_key)])


class ChatTurn(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str = Field(max_length=4000)


class CopilotIn(BaseModel):
    message: str = Field(min_length=1, max_length=1000)
    history: list[ChatTurn] = Field(default_factory=list, max_length=20)
    context: dict | None = None


class SearchIn(BaseModel):
    query: str = Field(min_length=2, max_length=300)


@router.get("/kpis")
def ai_kpis(period: str = Query("all", max_length=20), db: Session = Depends(get_db)):
    return F.kpis(db, period)


@router.get("/suggestions")
def ai_suggestions():
    return {"suggestions": copilot.SUGGESTIONS}


@router.post("/copilot")
def ai_copilot(body: CopilotIn, db: Session = Depends(get_db)):
    ctx = body.context if isinstance(body.context, dict) else None
    if ctx and ctx.get("intent") not in {i for i, _ in copilot.INTENTS}:
        ctx = None   # never trust client-supplied context beyond a known intent name
    return copilot.answer(db, body.message, [t.model_dump() for t in body.history], ctx)


@router.get("/risks")
def ai_risks(db: Session = Depends(get_db)):
    items = F.risk_items(db)
    return {"items": items, "counts": {s: sum(1 for x in items if x["severity"] == s) for s in ("Critical", "High", "Review")}}


@router.get("/anomalies")
def ai_anomalies(db: Session = Depends(get_db)):
    return F.anomalies(db)


@router.get("/vendors")
def ai_vendors(period: str = Query("all", max_length=20), db: Session = Depends(get_db)):
    return F.vendor_profiles(db, period)


@router.post("/search")
def ai_search(body: SearchIn, db: Session = Depends(get_db)):
    return S.smart_search(db, body.query)


@router.get("/investigate/{invoice_id}")
def ai_investigate(invoice_id: UUID, explain: bool = False, db: Session = Depends(get_db)):
    res = F.investigate(db, invoice_id)
    if res is None:
        raise HTTPException(404, "Invoice not found.")
    if explain:
        bad = [s for s in res["stages"] if s["status"] in ("fail", "warn")]
        fallback = ("Every check passed for this invoice." if not bad else
                    " ".join(f"{s['stage']}: {s['summary']}" for s in bad))
        res["explanation"] = explain_facts("invoice investigation", {"invoice": res["invoice"], "stages": res["stages"]},
                                           question="Explain to the business owner what was found on this invoice, "
                                                    "stage by stage, and what they should do next.", fallback=fallback)
    return res


@router.post("/brief")
def ai_brief(period: str = Query("this_month", max_length=20), db: Session = Depends(get_db)):
    return copilot.cfo_brief(db, period)


@router.get("/monthly")
def ai_monthly(months: int = Query(12, ge=1, le=36), db: Session = Depends(get_db)):
    return F.monthly_series(db, months)


# ----------------------------------------------------------------------------- batch 2
from fastapi.responses import PlainTextResponse  # noqa: E402

from backend.ai import insights as I  # noqa: E402


class WhatIfIn(BaseModel):
    scenario: str = Field(pattern="^(purchases_change|not_in_2b|unpaid_180)$")
    pct: float = Field(0, ge=-90, le=500)
    invoice_id: UUID | None = None


class VendorMsgIn(BaseModel):
    invoice_id: UUID
    issue: str | None = Field(None, max_length=300)


@router.get("/vendors/{vendor_key:path}/profile")
def ai_vendor_profile(vendor_key: str, explain: bool = False, db: Session = Depends(get_db)):
    res = I.vendor_detail(db, vendor_key, explain)
    if res is None:
        raise HTTPException(404, "Vendor not found.")
    return res


@router.get("/reconcile/gstr2b/{record_id}")
def ai_recon_2b(record_id: UUID, db: Session = Depends(get_db)):
    res = I.recon_2b(db, record_id)
    if res is None:
        raise HTTPException(404, "GSTR-2B record not found.")
    return res


@router.get("/reconcile/po/{invoice_id}")
def ai_recon_po(invoice_id: UUID, db: Session = Depends(get_db)):
    res = I.recon_po(db, invoice_id)
    if res is None:
        raise HTTPException(404, "Invoice not found.")
    return res


@router.post("/reports/monthly")
def ai_report_monthly(period: str = Query("this_month", max_length=20), db: Session = Depends(get_db)):
    return I.monthly_report(db, period)


@router.post("/reports/audit")
def ai_report_audit(period: str = Query("this_fy", max_length=20), db: Session = Depends(get_db)):
    return I.audit_report(db, period)


@router.get("/forecast")
def ai_forecast(months: int = Query(3, ge=1, le=12), db: Session = Depends(get_db)):
    return I.forecast(db, months)


@router.post("/whatif")
def ai_whatif(body: WhatIfIn, db: Session = Depends(get_db)):
    try:
        return I.what_if(db, body.scenario, pct=body.pct, invoice_id=body.invoice_id)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/vendor-message")
def ai_vendor_message(body: VendorMsgIn, db: Session = Depends(get_db)):
    res = I.vendor_message(db, body.invoice_id, body.issue)
    if res is None:
        raise HTTPException(404, "Invoice not found.")
    return res


@router.get("/feedback/metrics")
def ai_feedback_metrics(db: Session = Depends(get_db)):
    return I.feedback_metrics(db)


@router.get("/feedback/export", response_class=PlainTextResponse)
def ai_feedback_export(db: Session = Depends(get_db)):
    import json
    return PlainTextResponse("\n".join(json.dumps(r) for r in I.feedback_export(db)), media_type="application/x-ndjson",
                             headers={"Content-Disposition": 'attachment; filename="feedback_dataset.jsonl"'})
