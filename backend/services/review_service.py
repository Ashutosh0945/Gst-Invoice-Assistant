"""Human-in-the-loop review actions: approve, reject, correct. Every action
is written to audit_logs so the full decision history is reconstructable.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from backend.db.models import Invoice, InvoiceLine
from backend.schemas import InvoiceStatus
from backend.services.audit_service import log_action


def approve_invoice(db: Session, invoice: Invoice, reviewer: str, notes: str | None = None) -> Invoice:
    invoice.status = InvoiceStatus.APPROVED.value
    invoice.reviewed_by = reviewer
    invoice.reviewed_at = datetime.now(timezone.utc)
    invoice.review_notes = notes
    log_action(db, invoice.id, actor=reviewer, action="APPROVED", details={"notes": notes})
    _reassess_itc(db, invoice)
    db.commit()
    db.refresh(invoice)
    return invoice


def reject_invoice(db: Session, invoice: Invoice, reviewer: str, notes: str | None = None) -> Invoice:
    invoice.status = InvoiceStatus.REJECTED.value
    invoice.reviewed_by = reviewer
    invoice.reviewed_at = datetime.now(timezone.utc)
    invoice.review_notes = notes
    log_action(db, invoice.id, actor=reviewer, action="REJECTED", details={"notes": notes})
    _reassess_itc(db, invoice)
    db.commit()
    db.refresh(invoice)
    return invoice


def correct_invoice(db: Session, invoice: Invoice, reviewer: str, header_fields: dict[str, Any],
                     line_corrections: list[dict[str, Any]] | None = None, notes: str | None = None) -> Invoice:
    """Applies reviewer corrections and re-marks the invoice APPROVED with a
    recorded diff. This does not re-run the rule engine automatically —
    callers may call process_invoice_file's validation helpers again if a
    full re-validation is desired.
    """
    before = {k: getattr(invoice, k, None) for k in header_fields}
    for k, v in header_fields.items():
        setattr(invoice, k, v)

    line_diffs = []
    for corr in line_corrections or []:
        line = db.get(InvoiceLine, corr["line_id"])
        if line is None or line.invoice_id != invoice.id:
            continue
        before_line = {k: getattr(line, k, None) for k in corr["fields"]}
        for k, v in corr["fields"].items():
            setattr(line, k, v)
        line_diffs.append({"line_id": str(corr["line_id"]), "before": before_line, "after": corr["fields"]})

    _record_feedback(db, invoice, reviewer, before, header_fields, line_diffs)
    invoice.status = InvoiceStatus.APPROVED.value
    invoice.reviewed_by = reviewer
    invoice.reviewed_at = datetime.now(timezone.utc)
    invoice.review_notes = notes
    log_action(db, invoice.id, actor=reviewer, action="CORRECTED", details={
        "header_before": before, "header_after": header_fields, "line_diffs": line_diffs, "notes": notes,
    })
    _reassess_itc(db, invoice)
    db.commit()
    db.refresh(invoice)
    return invoice


def _reassess_itc(db: Session, invoice: Invoice) -> None:
    from backend.itc.service import assess_invoice  # local import: itc -> db models only
    db.flush()
    assess_invoice(db, invoice)


def record_payment(db: Session, invoice: Invoice, paid_on, actor: str) -> Invoice:
    """Records when the vendor was paid (Rule 37's 180-day condition) and re-assesses ITC."""
    before = invoice.payment_date.isoformat() if invoice.payment_date else None
    invoice.payment_date = paid_on
    log_action(db, invoice.id, actor=actor, action="PAYMENT_RECORDED",
               details={"before": before, "after": paid_on.isoformat() if paid_on else None})
    _reassess_itc(db, invoice)
    db.commit()
    db.refresh(invoice)
    return invoice


def _norm_fb(v) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    try:
        from decimal import Decimal
        return format(Decimal(s).normalize(), "f")
    except Exception:  # noqa: BLE001 - not a number
        return s.upper()


def _record_feedback(db: Session, invoice: Invoice, reviewer: str, before: dict, after: dict, line_diffs: list) -> None:
    """Feedback loop: store the extractor's prediction next to the human's answer.
    Never changes any model; evaluation happens offline (see backend/ai/feedback.py)."""
    from backend.db.models import FeedbackRecord

    conf = invoice.extraction_confidence or {}
    for field, new in after.items():
        old = before.get(field)
        db.add(FeedbackRecord(invoice_id=invoice.id, scope="header", field=field, predicted_value=None if old is None else str(old),
                              corrected_value=None if new is None else str(new),
                              predicted_confidence=conf.get(field) if isinstance(conf.get(field), (int, float)) else None,
                              was_correct=_norm_fb(old) == _norm_fb(new), reviewer=reviewer))
    for d in line_diffs:
        line = db.get(InvoiceLine, d["line_id"])
        for field, new in d["after"].items():
            old = d["before"].get(field)
            db.add(FeedbackRecord(invoice_id=invoice.id, scope="line", field=field, line_no=line.line_no if line else None,
                                  predicted_value=None if old is None else str(old), corrected_value=None if new is None else str(new),
                                  was_correct=_norm_fb(old) == _norm_fb(new), reviewer=reviewer))
