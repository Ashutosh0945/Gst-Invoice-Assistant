"""v0.6 endpoints: investigation workspace, duplicate review, anomaly ML, forecasts, GSTR-2B work queue,
action centre and documents. Same access rule as the rest of the API (require_api_key)."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.api.deps import require_api_key
from backend.db.base import get_db
from backend.db.models import AnomalyScore, Document, DuplicateCandidate, ForecastRun, Gstr2bRecord, Invoice, MlModel
from backend.services import workspace as WS
from backend.services.audit_service import log_action

router = APIRouter(dependencies=[Depends(require_api_key)])


def _inv(db, invoice_id) -> Invoice:
    inv = db.get(Invoice, invoice_id)
    if inv is None:
        raise HTTPException(404, "Invoice not found.")
    return inv


class ActorIn(BaseModel):
    actor: str = Field(min_length=1, max_length=120)
    note: str | None = Field(None, max_length=2000)


class InvestigationIn(ActorIn):
    status: str | None = Field(None, pattern="^(open|under_review|resolved)$")
    decision: str | None = Field(None, pattern="^(accepted|rejected|corrected|escalated)$")


class DecisionIn(ActorIn):
    decision: str = Field(pattern="^(confirmed|dismissed)$")


class ReviewIn(ActorIn):
    status: str = Field(pattern="^(reviewed|dismissed|confirmed)$")


class RecordPatch(BaseModel):
    actor: str = Field(min_length=1, max_length=120)
    resolution_status: str | None = Field(None, pattern="^(open|under_review|resolved)$")
    assigned_to: str | None = Field(None, max_length=120)
    note: str | None = Field(None, max_length=2000)


# ----------------------------------------------------------------------------- documents + investigation (1, 3)
@router.get("/invoices/{invoice_id}/document")
def document(invoice_id: UUID, kind: str = Query("original", pattern="^(original|ocr_ready)$"), db: Session = Depends(get_db)):
    d = db.execute(select(Document).where(Document.invoice_id == invoice_id, Document.kind == kind)).scalars().first()
    if d is None:
        raise HTTPException(404, "No stored document (invoices uploaded before v0.6 didn't keep the original file).")
    return Response(d.content, media_type=d.content_type, headers={"Content-Disposition": f'inline; filename="{(d.filename or "invoice").replace(chr(34), "")}"'})


@router.get("/invoices/{invoice_id}/workspace")
def get_workspace(invoice_id: UUID, db: Session = Depends(get_db)):
    return WS.workspace(db, _inv(db, invoice_id))


@router.post("/invoices/{invoice_id}/investigation")
def update_investigation(invoice_id: UUID, body: InvestigationIn, db: Session = Depends(get_db)):
    inv = _inv(db, invoice_id)
    WS.set_investigation(db, inv, body.status, body.decision, body.note, body.actor)
    return WS.workspace(db, inv)


@router.post("/invoices/{invoice_id}/revalidate")
def revalidate(invoice_id: UUID, body: ActorIn, db: Session = Depends(get_db)):
    return WS.revalidate(db, _inv(db, invoice_id), body.actor)


# ----------------------------------------------------------------------------- duplicates (10)
@router.get("/duplicates/candidates")
def dup_candidates(status: str | None = Query("open", pattern="^(open|confirmed|dismissed)$"), db: Session = Depends(get_db)):
    from backend.ml.duplicates import open_candidates
    out = []
    for c in open_candidates(db, status):
        a, b = db.get(Invoice, c.invoice_a), db.get(Invoice, c.invoice_b)
        row = lambda i: {"id": str(i.id), "invoice_number": i.invoice_number, "vendor": i.vendor_name_raw, "vendor_gstin": i.vendor_gstin_raw,  # noqa: E731
                         "invoice_date": i.invoice_date.isoformat() if i.invoice_date else None, "taxable": str(i.subtotal),
                         "tax": str(sum((x or 0) for x in (i.total_cgst, i.total_sgst, i.total_igst))), "total": str(i.grand_total), "status": i.status}
        out.append({"id": str(c.id), "tier": c.tier, "score": float(c.score), "score_label": "similarity score (not a probability)",
                    "signals": c.signals, "status": c.status, "a": row(a), "b": row(b), "decided_by": c.decided_by, "note": c.decision_note})
    return out


@router.post("/duplicates/candidates/{cid}/decision")
def dup_decision(cid: UUID, body: DecisionIn, db: Session = Depends(get_db)):
    c = db.get(DuplicateCandidate, cid)
    if c is None:
        raise HTTPException(404, "Candidate not found.")
    c.status, c.decided_by, c.decision_note, c.decided_at = body.decision, body.actor, body.note, datetime.now(timezone.utc)
    for iid in (c.invoice_a, c.invoice_b):
        log_action(db, iid, actor=body.actor, action=f"DUPLICATE_{body.decision.upper()}", details={"candidate": str(c.id), "note": body.note})
    db.commit()
    return {"id": str(c.id), "status": c.status}


@router.post("/duplicates/scan")
def dup_scan(db: Session = Depends(get_db)):
    from backend.ml.duplicates import candidates_for
    n = 0
    for inv in db.execute(select(Invoice)).scalars().all():
        n += len(candidates_for(db, inv))
    db.commit()
    return {"new_candidates": n}


# ----------------------------------------------------------------------------- anomaly ML (9)
@router.post("/ml/anomaly/train")
def anomaly_train(db: Session = Depends(get_db)):
    from backend.ml.anomaly import train
    return train(db)


@router.get("/ml/anomaly/model")
def anomaly_model(db: Session = Depends(get_db)):
    from backend.ml.anomaly import active_model
    m = active_model(db)
    if m is None:
        return {"status": "not_trained", "message": "No anomaly model has been trained yet."}
    return {"status": "active", "name": m.name, "version": m.version, "trained_on": m.trained_on, "params": m.params, "metrics": m.metrics,
            "created_at": m.created_at.isoformat() if m.created_at else None}


@router.get("/ml/anomaly/scores")
def anomaly_scores(priority: str | None = Query(None, pattern="^(high|medium|low)$"), status: str | None = Query(None, pattern="^(open|reviewed|dismissed|confirmed)$"),
                   limit: int = Query(100, le=500), db: Session = Depends(get_db)):
    q = select(AnomalyScore).order_by(AnomalyScore.score.desc()).limit(limit)
    if priority:
        q = q.where(AnomalyScore.priority == priority)
    if status:
        q = q.where(AnomalyScore.review_status == status)
    out = []
    for a in db.execute(q).scalars():
        inv = db.get(Invoice, a.invoice_id)
        out.append({"id": str(a.id), "invoice_id": str(a.invoice_id), "invoice_number": inv.invoice_number if inv else None,
                    "vendor": inv.vendor_name_raw if inv else None, "total": str(inv.grand_total) if inv else None,
                    "score": float(a.score), "rank_pct": float(a.rank_pct), "priority": a.priority, "signals": a.signals,
                    "data_sufficiency": a.data_sufficiency, "model_version": a.model_version, "review_status": a.review_status,
                    "review_note": a.review_note, "reviewed_by": a.reviewed_by})
    return out


@router.post("/ml/anomaly/scores/{sid}/review")
def anomaly_review(sid: UUID, body: ReviewIn, db: Session = Depends(get_db)):
    a = db.get(AnomalyScore, sid)
    if a is None:
        raise HTTPException(404, "Score not found.")
    a.review_status, a.review_note, a.reviewed_by, a.reviewed_at = body.status, body.note, body.actor, datetime.now(timezone.utc)
    log_action(db, a.invoice_id, actor=body.actor, action=f"ANOMALY_{body.status.upper()}", details={"score_id": str(a.id), "note": body.note})
    db.commit()
    return {"id": str(a.id), "review_status": a.review_status}


# ----------------------------------------------------------------------------- forecasting (11)
@router.get("/ml/forecast")
def ml_forecast(db: Session = Depends(get_db)):
    from backend.ml.forecasting import SERIES, forecast_series, monthly
    invs = db.execute(select(Invoice).where(Invoice.status.notin_(["REJECTED", "FAILED"]))).scalars().all()
    pts = {"purchase_value": [(i.invoice_date, float(i.grand_total or 0)) for i in invs if i.invoice_date],
           "gst_on_purchases": [(i.invoice_date, float(sum((x or 0) for x in (i.total_cgst, i.total_sgst, i.total_igst, i.total_cess)))) for i in invs if i.invoice_date],
           "invoice_count": [(i.invoice_date, 1.0) for i in invs if i.invoice_date],
           "gstr2b_records": [(r.invoice_date, 1.0) for r in db.execute(select(Gstr2bRecord)).scalars() if r.invoice_date],
           "issues": [(i.invoice_date, 1.0) for i in invs if i.invoice_date and i.status == "NEEDS_REVIEW"]}
    out = {}
    for key, label in SERIES.items():
        months, y, filled = monthly(pts[key])
        try:
            res = forecast_series(months, y, filled=filled)
        except Exception as exc:  # noqa: BLE001 - a forecasting failure must not break Analytics
            res = {"status": "error", "message": f"Forecast failed: {type(exc).__name__}", "history": []}
        res["title"] = label
        db.add(ForecastRun(series=key, status=res["status"], model=res.get("model"), result={k: v for k, v in res.items() if k != "history"}))
        out[key] = res
    db.commit()
    return out


# ----------------------------------------------------------------------------- GSTR-2B work queue (4)
CATEGORY = {"MATCHED": "Matched", "FUZZY_MATCHED": "Invoice-number mismatch", "DATE_MISMATCH": "Date mismatch",
            "MISSING_IN_BOOKS": "Missing from purchase records", "GSTIN_MISMATCH": "GSTIN mismatch",
            "REVIEW_REQUIRED": "Review required", "POTENTIAL_DUPLICATE": "Potential duplicate"}


def _category(r: Gstr2bRecord) -> str:
    if r.match_status == "AMOUNT_MISMATCH":
        f = r.mismatch_fields or []
        return "Taxable-value mismatch" if "taxable_value" in f else "Tax mismatch"
    return CATEGORY.get(r.match_status, r.match_status)


@router.get("/gstr2b/queue")
def gstr2b_queue(category: str | None = None, status: str | None = Query(None, pattern="^(open|under_review|resolved)$"),
                 db: Session = Depends(get_db)):
    rows = []
    for r in db.execute(select(Gstr2bRecord).order_by(Gstr2bRecord.match_status)).scalars():
        cat = _category(r)
        if category and cat != category:
            continue
        rs = r.resolution_status or ("resolved" if r.match_status == "MATCHED" else "open")
        if status and rs != status:
            continue
        rows.append({"id": str(r.id), "category": cat, "match_status": r.match_status, "supplier": r.supplier_name, "supplier_gstin": r.supplier_gstin,
                     "invoice_number": r.invoice_number, "invoice_date": r.invoice_date.isoformat() if r.invoice_date else None,
                     "taxable_value": str(r.taxable_value), "tax": str((r.igst or 0) + (r.cgst or 0) + (r.sgst or 0) + (r.cess or 0)),
                     "notes": r.match_notes, "mismatch_fields": r.mismatch_fields, "candidates": r.candidates,
                     "matched_invoice_id": str(r.matched_invoice_id) if r.matched_invoice_id else None,
                     "resolution_status": rs, "assigned_to": r.assigned_to, "resolution_note": r.resolution_note})
    from backend.db.models import Invoice as I
    if category in (None, "Missing from GSTR-2B"):
        for i in db.execute(select(I).where(I.gstr2b_status == "MISSING_IN_2B")).scalars():
            rows.append({"id": f"inv:{i.id}", "category": "Missing from GSTR-2B", "match_status": "MISSING_IN_2B", "supplier": i.vendor_name_raw,
                         "supplier_gstin": i.vendor_gstin_raw, "invoice_number": i.invoice_number,
                         "invoice_date": i.invoice_date.isoformat() if i.invoice_date else None, "taxable_value": str(i.subtotal),
                         "tax": str(sum((x or 0) for x in (i.total_cgst, i.total_sgst, i.total_igst))), "notes": "Vendor hasn't reported this invoice.",
                         "matched_invoice_id": str(i.id), "resolution_status": "open", "assigned_to": None, "resolution_note": None})
    return rows


@router.patch("/gstr2b/records/{rid}")
def gstr2b_patch(rid: UUID, body: RecordPatch, db: Session = Depends(get_db)):
    r = db.get(Gstr2bRecord, rid)
    if r is None:
        raise HTTPException(404, "GSTR-2B record not found.")
    if body.resolution_status:
        r.resolution_status = body.resolution_status
        if body.resolution_status == "resolved":
            r.resolved_by, r.resolved_at = body.actor, datetime.now(timezone.utc)
    if body.assigned_to is not None:
        r.assigned_to = body.assigned_to or None
    if body.note:
        r.resolution_note = body.note
    log_action(db, r.matched_invoice_id, actor=body.actor, action="GSTR2B_RECORD_UPDATED",
               details={"record": str(r.id), "status": r.resolution_status, "assigned_to": r.assigned_to, "note": body.note})
    db.commit()
    return {"id": str(r.id), "resolution_status": r.resolution_status, "assigned_to": r.assigned_to}


@router.get("/gstr2b/metrics")
def gstr2b_metrics(db: Session = Depends(get_db)):
    recs = db.execute(select(Gstr2bRecord)).scalars().all()
    tax = lambda r: (r.igst or 0) + (r.cgst or 0) + (r.sgst or 0) + (r.cess or 0)  # noqa: E731
    matched = [r for r in recs if r.match_status in ("MATCHED", "FUZZY_MATCHED", "DATE_MISMATCH")]
    amt = [r for r in recs if r.match_status == "AMOUNT_MISMATCH" and r.matched_invoice_id]
    tx_diff = taxable_diff = 0
    for r in amt:
        i = db.get(Invoice, r.matched_invoice_id)
        taxable_diff += abs((r.taxable_value or 0) - (i.subtotal or 0))
        tx_diff += abs(tax(r) - sum((x or 0) for x in (i.total_cgst, i.total_sgst, i.total_igst, i.total_cess)))
    missing_2b = db.execute(select(Invoice).where(Invoice.gstr2b_status == "MISSING_IN_2B")).scalars().all()
    from backend.db.models import ItcAssessment
    itc_aff = sum(float(a.at_risk_itc or 0) for a in db.execute(select(ItcAssessment)).scalars())
    return {
        "total_imported_records": len(recs), "matched_records": len(matched), "unmatched_records": len(recs) - len(matched),
        "mismatch_count": sum(1 for r in recs if r.match_status not in ("MATCHED",)),
        "taxable_value_difference": float(taxable_diff), "tax_difference": float(tx_diff),
        "invoices_missing_from_gstr2b": len(missing_2b), "potential_itc_affected": round(itc_aff, 2),
        "resolved_issues": sum(1 for r in recs if r.resolution_status == "resolved"),
        "definitions": {
            "matched_records": "GSTR-2B lines matched to one register invoice with agreeing amounts (exact, number-variant or date-variant).",
            "mismatch_count": "GSTR-2B lines that are not an exact match (each line counted once).",
            "tax_difference": "Sum of |GSTR-2B tax − register tax| over amount-mismatched pairs only (no double counting).",
            "potential_itc_affected": "ITC at risk per the ITC rules (e.g. invoice missing from GSTR-2B). Not confirmed lost, not confirmed eligible.",
            "unsupported": "Credit/debit notes (CDNR) and amendments (B2BA) are counted on import but not reconciled yet."}}


# ----------------------------------------------------------------------------- action centre (6)
@router.get("/ai/action-center")
def action_center(db: Session = Depends(get_db)):
    return WS.action_center(db)
