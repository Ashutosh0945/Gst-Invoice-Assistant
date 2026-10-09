"""Investigation workspace, re-validation and the dashboard action centre. Reuses the existing
validation engine, ITC rules, duplicate checks and audit log -- nothing here re-implements GST logic."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.db.models import (AccessEvent, AnomalyScore, AuditLog, Document, DuplicateCandidate, Gstr2bRecord, Investigation,
                               InvestigationNote, Invoice, ProcessingJob, ValidationFinding)
from backend.schemas import InvoiceData, LineItem
from backend.services.audit_service import log_action

# Which rule produced each finding and what to do next (evidence panel).
RULES = {
    "GSTIN": ("GSTIN format and checksum check", "Confirm the GSTIN with the vendor or the GST portal."),
    "HSN": ("HSN/SAC code and rate table check", "Check the HSN/SAC code and the GST rate charged."),
    "LINE": ("Line arithmetic check (qty × rate = taxable; tax = taxable × rate)", "Correct the misread line or ask the vendor for a revised invoice."),
    "GRAND_TOTAL": ("Header arithmetic check (taxable + taxes + round-off = total)", "Correct the extracted totals or reject the invoice."),
    "TAX_TYPE": ("Intra/inter-state rule (CGST+SGST vs IGST)", "Check the place of supply against both GSTINs."),
    "CGST_SGST": ("CGST must equal SGST", "Check the tax columns."),
    "DUPLICATE": ("Duplicate check (file hash / vendor + number + amount window)", "Make sure it isn't paid or claimed twice; confirm or dismiss."),
    "NO_PO": ("Purchase-order reference check", "Attach a PO if your process requires one."),
    "PO": ("PO quantity / price / item comparison", "Compare with the PO and confirm with purchasing."),
    "E0": ("E-invoice signed-QR verification", "Ask the vendor for the original e-invoice."),
    "DATE": ("Invoice date check", "Correct the date if it was misread."),
}


def rule_for(code: str) -> tuple[str, str]:
    for prefix, v in RULES.items():
        if code.startswith(prefix):
            return v
    return ("Validation rule " + code, "Review the finding and correct or approve the invoice.")


def invoice_data_from_db(inv: Invoice) -> InvoiceData:
    return InvoiceData(
        vendor_name=inv.vendor_name_raw, vendor_gstin=inv.vendor_gstin_raw, buyer_gstin=getattr(inv, "buyer_gstin_raw", None),
        invoice_number=inv.invoice_number, invoice_date=inv.invoice_date, po_number=getattr(inv, "po_number_raw", None),
        place_of_supply=getattr(inv, "place_of_supply", None),
        subtotal=inv.subtotal, total_cgst=inv.total_cgst, total_sgst=inv.total_sgst, total_igst=inv.total_igst,
        total_cess=getattr(inv, "total_cess", None), round_off=getattr(inv, "round_off", None), grand_total=inv.grand_total,
        items=[LineItem(line_no=li.line_no, description=li.description, hsn_sac=li.hsn_sac, quantity=li.quantity, unit=li.unit,
                        unit_price=li.unit_price, taxable_value=li.taxable_value, gst_rate=li.gst_rate, cgst=li.cgst, sgst=li.sgst,
                        igst=li.igst, cess=li.cess, line_total=li.line_total) for li in inv.items])


def revalidate(db: Session, inv: Invoice, actor: str) -> dict:
    """Re-runs the existing validation engine and ITC rules on the invoice's CURRENT (possibly corrected) fields."""
    from backend.itc.service import assess_invoice
    from backend.validation.engine import validate_invoice

    before = sorted(f.code for f in inv.findings if f.category == "validation")
    for f in [f for f in inv.findings if f.category == "validation"]:
        db.delete(f)
    db.flush()
    new = validate_invoice(invoice_data_from_db(inv))
    for f in new:
        db.add(ValidationFinding(invoice_id=inv.id, code=f.code, category=f.category, severity=f.severity.value if hasattr(f.severity, "value") else f.severity,
                                 message=f.message, field=f.field, line_no=f.line_no, expected=f.expected, actual=f.actual))
    db.flush()
    db.refresh(inv)
    assess_invoice(db, inv)
    after = sorted(f.code for f in new)
    log_action(db, inv.id, actor=actor, action="REVALIDATED", details={"before": before, "after": after})
    db.commit()
    return {"before": before, "after": after, "resolved": sorted(set(before) - set(after)), "new": sorted(set(after) - set(before))}


def workspace(db: Session, inv: Invoice) -> dict:
    inv_q = db.execute(select(Investigation).where(Investigation.invoice_id == inv.id)).scalars().first()
    notes = db.execute(select(InvestigationNote).where(InvestigationNote.invoice_id == inv.id).order_by(InvestigationNote.created_at)).scalars().all()
    audit = db.execute(select(AuditLog).where(AuditLog.invoice_id == inv.id).order_by(AuditLog.created_at)).scalars().all()
    docs = db.execute(select(Document.kind, Document.filename, Document.size_bytes, Document.content_type).where(Document.invoice_id == inv.id)).all()
    dups = db.execute(select(DuplicateCandidate).where((DuplicateCandidate.invoice_a == inv.id) | (DuplicateCandidate.invoice_b == inv.id))).scalars().all()
    an = db.execute(select(AnomalyScore).where(AnomalyScore.invoice_id == inv.id).order_by(AnomalyScore.created_at.desc())).scalars().first()
    rec = db.get(Gstr2bRecord, inv.gstr2b_record_id) if inv.gstr2b_record_id else None
    findings = []
    for f in inv.findings:
        rule, action = rule_for(f.code)
        diff = None
        try:
            if f.expected is not None and f.actual is not None:
                diff = str(Decimal(str(f.actual)) - Decimal(str(f.expected)))
        except Exception:  # noqa: BLE001 - non-numeric expected/actual
            diff = None
        findings.append({"id": str(f.id), "code": f.code, "category": f.category, "severity": f.severity, "message": f.message,
                         "field": f.field, "line_no": f.line_no, "expected": f.expected, "actual": f.actual, "difference": diff,
                         "rule": rule, "recommended_action": action})
    return {
        "invoice_id": str(inv.id), "status": inv.status,
        "investigation": {"status": inv_q.status if inv_q else "open", "decision": inv_q.decision if inv_q else None,
                          "decision_note": inv_q.decision_note if inv_q else None, "decided_by": inv_q.decided_by if inv_q else None,
                          "decided_at": inv_q.decided_at.isoformat() if inv_q and inv_q.decided_at else None},
        "field_confidence": inv.extraction_confidence or {},
        "documents": [{"kind": k, "filename": fn, "size_bytes": sz, "content_type": ct} for k, fn, sz, ct in docs],
        "findings": findings,
        "gstr2b": {"status": inv.gstr2b_status, "record": {"id": str(rec.id), "match_status": rec.match_status, "notes": rec.match_notes,
                   "mismatch_fields": rec.mismatch_fields, "taxable_value": str(rec.taxable_value), "supplier_gstin": rec.supplier_gstin} if rec else None},
        "duplicates": [{"id": str(d.id), "other_invoice_id": str(d.invoice_b if d.invoice_a == inv.id else d.invoice_a), "tier": d.tier,
                        "score": float(d.score), "status": d.status, "signals": d.signals} for d in dups],
        "anomaly": {"score": float(an.score), "rank_pct": float(an.rank_pct), "priority": an.priority, "signals": an.signals,
                    "data_sufficiency": an.data_sufficiency, "model_version": an.model_version, "review_status": an.review_status,
                    "id": str(an.id)} if an else None,
        "notes": [{"author": n.author, "text": n.text, "at": n.created_at.isoformat() if n.created_at else None} for n in notes],
        "audit": [{"action": a.action, "actor": a.actor, "at": a.created_at.isoformat() if a.created_at else None, "details": a.details} for a in audit],
    }


def set_investigation(db: Session, inv: Invoice, status: str | None, decision: str | None, note: str | None, actor: str) -> None:
    row = db.execute(select(Investigation).where(Investigation.invoice_id == inv.id)).scalars().first() or Investigation(invoice_id=inv.id)
    db.add(row)
    before = {"status": row.status, "decision": row.decision}
    if status:
        row.status = status
    if decision:
        row.decision, row.decision_note, row.decided_by, row.decided_at = decision, note, actor, datetime.now(timezone.utc)
        row.status = "resolved"
    if note and not decision:
        db.add(InvestigationNote(invoice_id=inv.id, author=actor, text=note))
    log_action(db, inv.id, actor=actor, action="INVESTIGATION_UPDATED", details={"before": before, "status": row.status, "decision": decision, "note": note})
    db.commit()


# ----------------------------------------------------------------------------- action centre (Improvement 6)
def action_center(db: Session) -> dict:
    from backend.ai import facts as F

    k = F.kpis(db, "all")
    recs = db.execute(select(Gstr2bRecord)).scalars().all()
    total_2b = len(recs)
    matched = sum(1 for r in recs if r.match_status in ("MATCHED", "FUZZY_MATCHED", "DATE_MISMATCH"))
    unresolved = [r for r in recs if r.match_status != "MATCHED" and (r.resolution_status or "open") != "resolved"]
    tax = lambda r: (r.igst or 0) + (r.cgst or 0) + (r.sgst or 0) + (r.cess or 0)  # noqa: E731
    confirmed_diff = Decimal(0)
    for r in recs:
        if r.match_status == "AMOUNT_MISMATCH" and r.matched_invoice_id:
            inv = db.get(Invoice, r.matched_invoice_id)
            if inv:
                confirmed_diff += abs(tax(r) - sum((x or 0) for x in (inv.total_cgst, inv.total_sgst, inv.total_igst, inv.total_cess)))
    low_conf = db.execute(select(Invoice).where(Invoice.confidence_score < 0.6, Invoice.status == "NEEDS_REVIEW")).scalars().all()
    failed = db.execute(select(ProcessingJob).where(ProcessingJob.status == "FAILED").order_by(ProcessingJob.created_at.desc()).limit(10)).scalars().all()
    open_inv = db.execute(select(func.count()).select_from(Investigation).where(Investigation.status != "resolved")).scalar() or 0
    dup_open = db.execute(select(func.count()).select_from(DuplicateCandidate).where(DuplicateCandidate.status == "open")).scalar() or 0
    an_hi = db.execute(select(AnomalyScore).where(AnomalyScore.priority.in_(["high", "medium"]), AnomalyScore.review_status == "open")
                       .order_by(AnomalyScore.score.desc()).limit(20)).scalars().all()
    # Priority = severity weight + log-scaled amount at stake (transparent; shown to the user).
    import math
    W = {"Critical": 100, "High": 60, "Review": 30}
    actions = []
    for x in F.risk_items(db):
        amt = x.get("amount_at_stake") or 0
        actions.append({**x, "priority_score": round(W[x["severity"]] + 10 * math.log10(1 + amt), 1)})
    for inv in low_conf:
        actions.append({"key": f"lowconf:{inv.id}", "severity": "Review", "category": "Extraction", "title": "Low-confidence extraction",
                        "reason": f"Read confidence {round(float(inv.confidence_score or 0) * 100)}%", "invoice_id": str(inv.id),
                        "invoice_number": inv.invoice_number, "vendor": inv.vendor_name_raw, "amount_at_stake": None,
                        "next_action": "Check the extracted fields against the document.", "priority_score": 30})
    for a in an_hi:
        inv = db.get(Invoice, a.invoice_id)
        actions.append({"key": f"ml:{a.id}", "severity": "Review", "category": "ML anomaly", "title": f"Unusual invoice ({a.priority} priority)",
                        "reason": "; ".join(s["label"] for s in (a.signals or []) if s.get("feature") != "history")[:160] or "Unusual combination of features",
                        "invoice_id": str(a.invoice_id), "invoice_number": inv.invoice_number if inv else None, "vendor": inv.vendor_name_raw if inv else None,
                        "amount_at_stake": float(inv.grand_total) if inv and inv.grand_total else None,
                        "next_action": "Review the evidence; this is a signal, not proof.", "priority_score": 40 if a.priority == "high" else 32})
    actions.sort(key=lambda a: -a["priority_score"])
    act = db.execute(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(15)).scalars().all()
    return {
        "definitions": {
            "gstr2b_match_rate": "Matched GSTR-2B records (exact, number-variant or date-variant) ÷ all imported GSTR-2B records.",
            "confirmed_differences": "Absolute tax difference on GSTR-2B lines matched to your invoice but with different amounts.",
            "potentially_affected_itc": "ITC on invoices missing from GSTR-2B or with unresolved decisions — at risk, not lost and not confirmed.",
            "requiring_review": "ITC whose eligibility depends on a human decision (e.g. possibly blocked credits).",
            "priority_score": "Severity weight (Critical 100, High 60, Review 30) + 10 × log10(1 + amount at stake)."},
        "overview": {"total_invoices": k["total_invoices"], "purchase_value": k["total_purchase_value"], "gst_amount": k["gst_amount"],
                     "itc_claimable": k["itc_eligible"], "gstr2b_match_rate": round(matched / total_2b, 4) if total_2b else None,
                     "gstr2b_records": total_2b, "unresolved_mismatches": len(unresolved), "needs_review": k["needs_review"],
                     "open_investigations": open_inv, "open_duplicate_candidates": dup_open},
        "financial_impact": {"confirmed_differences": float(confirmed_diff), "potentially_affected_itc": k["itc_at_risk"] - 0,
                             "requiring_review": float(sum((x.review_itc or 0) for x in [i.itc for i in db.execute(select(Invoice)).scalars()] if x)),
                             "estimated_note": "Forecasts are shown on the Analytics page and are estimates only."},
        "priority_actions": actions[:25],
        "failed_jobs": [{"file": j.source_filename, "error": (j.error_message or "")[:160], "at": j.created_at.isoformat() if j.created_at else None} for j in failed],
        "recent_activity": [{"action": a.action, "actor": a.actor, "invoice_id": str(a.invoice_id) if a.invoice_id else None,
                             "at": a.created_at.isoformat() if a.created_at else None} for a in act],
    }
