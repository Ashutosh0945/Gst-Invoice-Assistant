"""Persist ITC decisions for invoices."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from backend.config import get_settings
from backend.db.models import Gstr2bRecord, Invoice, ItcAssessment
from backend.itc.eligibility import ItcInput, ItcLine, assess

ZERO = Decimal("0")


def build_input(db: Session, inv: Invoice) -> ItcInput:
    lines = [ItcLine(li.line_no, li.description, li.hsn_sac,
                     sum((x or ZERO) for x in (li.cgst, li.sgst, li.igst, li.cess)))
             for li in inv.items]
    header_tax = sum((x or ZERO) for x in (inv.total_cgst, inv.total_sgst, inv.total_igst, inv.total_cess))
    rec = db.get(Gstr2bRecord, inv.gstr2b_record_id) if inv.gstr2b_record_id else None
    return ItcInput(
        invoice_status=inv.status, invoice_date=inv.invoice_date, lines=lines, header_tax=header_tax,
        gstr2b_status=inv.gstr2b_status,
        twob_itc_available=rec.itc_available if rec else None,
        twob_reason=rec.itc_unavailable_reason if rec else None,
        reverse_charge=bool(rec.reverse_charge) if rec else False,
        payment_date=inv.payment_date,
        possible_duplicate=is_possible_duplicate(inv),
        einvoice_problem=inv.einvoice_status in ("MISMATCH", "SIGNATURE_INVALID"),
    )


def is_possible_duplicate(inv: Invoice) -> bool:
    return any(f.category == "duplicate" and f.severity == "ERROR" for f in inv.findings)


def assess_invoice(db: Session, inv: Invoice, today: date | None = None) -> ItcAssessment:
    s = get_settings()
    d = assess(build_input(db, inv), today=today or date.today(),
               same_line_prefixes=s.same_line_prefixes, payment_days=s.itc_payment_days)
    row = inv.itc or ItcAssessment(invoice_id=inv.id)
    row.status = d.status
    row.total_itc, row.eligible_itc, row.blocked_itc = d.total_itc, d.eligible_itc, d.blocked_itc
    row.review_itc, row.at_risk_itc = d.review_itc, d.at_risk_itc
    row.claim_deadline, row.payment_due_by, row.reasons = d.claim_deadline, d.payment_due_by, d.reasons
    if inv.itc is None:
        db.add(row)
        inv.itc = row
    return row


def assess_invoices(db: Session, invoices: list[Invoice], today: date | None = None) -> None:
    for inv in invoices:
        assess_invoice(db, inv, today)
    db.flush()


def reassess_all(db: Session, today: date | None = None) -> int:
    from sqlalchemy import select

    invoices = db.execute(select(Invoice)).scalars().all()
    assess_invoices(db, invoices, today)
    db.commit()
    return len(invoices)
