"""Pandas-free analytics queries for the API/frontend.

An earlier Streamlit dashboard used pandas; it has been replaced by the Next.js app. These queries return
pandas DataFrames -- pandas is deliberately excluded from api/requirements.txt
to keep the Vercel function small, so these mirror the same aggregations
using plain SQLAlchemy Core and return JSON-ready lists of dicts instead.
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.db.models import Invoice, InvoiceLine, ReconciliationResult, ValidationFinding, Vendor


def status_summary(db: Session) -> list[dict]:
    rows = db.execute(
        select(Invoice.status, func.count(Invoice.id), func.sum(Invoice.grand_total),
               func.avg(Invoice.confidence_score))
        .group_by(Invoice.status)
    ).all()
    return [
        {"status": s, "invoice_count": c, "total_value": v, "avg_confidence": a}
        for s, c, v, a in rows
    ]


def gst_by_rate(db: Session) -> list[dict]:
    rows = db.execute(
        select(
            InvoiceLine.gst_rate,
            func.count(func.distinct(InvoiceLine.invoice_id)),
            func.sum(InvoiceLine.taxable_value),
            func.sum(func.coalesce(InvoiceLine.cgst, 0) + func.coalesce(InvoiceLine.sgst, 0)
                     + func.coalesce(InvoiceLine.igst, 0)),
        )
        .join(Invoice, Invoice.id == InvoiceLine.invoice_id)
        .where(Invoice.status.in_(["AUTO_APPROVED", "APPROVED"]))
        .group_by(InvoiceLine.gst_rate)
        .order_by(InvoiceLine.gst_rate)
    ).all()
    return [
        {"gst_rate": r, "invoice_count": c, "total_taxable_value": t, "total_gst": g}
        for r, c, t, g in rows
    ]


def hsn_summary(db: Session, limit: int = 20) -> list[dict]:
    rows = db.execute(
        select(
            InvoiceLine.hsn_sac,
            func.count(InvoiceLine.id),
            func.sum(InvoiceLine.taxable_value),
            func.avg(InvoiceLine.gst_rate),
        )
        .join(Invoice, Invoice.id == InvoiceLine.invoice_id)
        .where(Invoice.status.in_(["AUTO_APPROVED", "APPROVED"]))
        .group_by(InvoiceLine.hsn_sac)
        .order_by(func.sum(InvoiceLine.taxable_value).desc())
        .limit(limit)
    ).all()
    return [
        {"hsn_sac": h, "line_count": c, "total_taxable_value": t, "avg_gst_rate": a}
        for h, c, t, a in rows
    ]


def vendor_spend(db: Session, limit: int = 20) -> list[dict]:
    rows = db.execute(
        select(
            Vendor.name, Vendor.gstin,
            func.count(Invoice.id),
            func.sum(Invoice.grand_total),
            func.avg(Invoice.confidence_score),
        )
        .join(Invoice, Invoice.vendor_id == Vendor.id)
        .group_by(Vendor.id, Vendor.name, Vendor.gstin)
        .order_by(func.sum(Invoice.grand_total).desc())
        .limit(limit)
    ).all()
    return [
        {"vendor_name": n, "gstin": g, "invoice_count": c, "total_spend": s, "avg_confidence": a}
        for n, g, c, s, a in rows
    ]


def finding_frequency(db: Session, limit: int = 30) -> list[dict]:
    rows = db.execute(
        select(
            ValidationFinding.code, ValidationFinding.category, ValidationFinding.severity,
            func.count(ValidationFinding.id), func.count(func.distinct(ValidationFinding.invoice_id)),
        )
        .group_by(ValidationFinding.code, ValidationFinding.category, ValidationFinding.severity)
        .order_by(func.count(ValidationFinding.id).desc())
        .limit(limit)
    ).all()
    return [
        {"code": code, "category": cat, "severity": sev, "occurrence_count": occ, "invoice_count": inv}
        for code, cat, sev, occ, inv in rows
    ]


def reconciliation_summary(db: Session) -> list[dict]:
    rows = db.execute(
        select(ReconciliationResult.status, func.count(ReconciliationResult.id))
        .join(Invoice, Invoice.id == ReconciliationResult.invoice_id)
        .group_by(ReconciliationResult.status)
    ).all()
    return [{"status": s, "line_count": c} for s, c in rows]


def duplicate_findings(db: Session, limit: int = 50) -> list[dict]:
    rows = db.execute(
        select(ValidationFinding, Invoice.invoice_number, Invoice.source_filename, Invoice.id)
        .join(Invoice, Invoice.id == ValidationFinding.invoice_id)
        .where(ValidationFinding.category == "duplicate")
        .order_by(ValidationFinding.created_at.desc())
        .limit(limit)
    ).all()
    return [
        {"invoice_id": str(inv_id), "invoice_number": inv_no, "source_filename": fname,
         "code": f.code, "message": f.message}
        for f, inv_no, fname, inv_id in rows
    ]


def daily_intake(db: Session, days: int = 30) -> list[dict]:
    rows = db.execute(
        select(func.date(Invoice.created_at), Invoice.status)
    ).all()
    buckets: dict[str, dict[str, int]] = {}
    for day, status in rows:
        key = str(day)
        b = buckets.setdefault(key, {"invoices_ingested": 0, "auto_approved": 0, "needs_review": 0, "rejected": 0})
        b["invoices_ingested"] += 1
        if status == "AUTO_APPROVED":
            b["auto_approved"] += 1
        elif status == "NEEDS_REVIEW":
            b["needs_review"] += 1
        elif status == "REJECTED":
            b["rejected"] += 1
    return [{"day": day, **vals} for day, vals in sorted(buckets.items())][-days:]
