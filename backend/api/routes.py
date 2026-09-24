from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.api.deps import require_api_key
from backend.api.schemas_api import (
    CorrectionIn, DailyIntakeOut, DuplicateFindingOut, FindingFrequencyOut,
    GstByRateOut, HsnSummaryOut, InvoiceDetailOut, InvoiceSummaryOut,
    ReconciliationSummaryOut, ReviewActionIn, StatusSummaryOut, VendorSpendOut,
)
from backend.analytics import api_queries as analytics
from backend.db.base import get_db
from backend.db.models import Invoice
from backend.services.pipeline_service import process_invoice_file
from backend.services.review_service import approve_invoice, correct_invoice, reject_invoice

router = APIRouter(dependencies=[Depends(require_api_key)])


@router.post("/invoices", response_model=InvoiceDetailOut, status_code=201)
def upload_invoice(file: UploadFile, db: Session = Depends(get_db)):
    suffix = Path(file.filename or "invoice").suffix or ".pdf"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = Path(tmp.name)
    try:
        invoice = process_invoice_file(db, tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)
    return invoice


@router.get("/invoices", response_model=list[InvoiceSummaryOut])
def list_invoices(
    status: str | None = None,
    vendor_gstin: str | None = None,
    limit: int = Query(50, le=500),
    offset: int = 0,
    db: Session = Depends(get_db),
):
    stmt = select(Invoice).order_by(Invoice.created_at.desc()).limit(limit).offset(offset)
    if status:
        stmt = stmt.where(Invoice.status == status)
    if vendor_gstin:
        stmt = stmt.where(Invoice.vendor_gstin_raw == vendor_gstin)
    return db.execute(stmt).scalars().all()


@router.get("/invoices/{invoice_id}", response_model=InvoiceDetailOut)
def get_invoice(invoice_id: UUID, db: Session = Depends(get_db)):
    invoice = db.get(Invoice, invoice_id)
    if invoice is None:
        raise HTTPException(404, "Invoice not found.")
    return invoice


@router.get("/invoices/{invoice_id}/review-queue-position")
def review_position(invoice_id: UUID, db: Session = Depends(get_db)):
    invoice = db.get(Invoice, invoice_id)
    if invoice is None:
        raise HTTPException(404, "Invoice not found.")
    ahead = db.execute(
        select(Invoice).where(Invoice.status == "NEEDS_REVIEW", Invoice.created_at < invoice.created_at)
    ).scalars().all()
    return {"position": len(ahead) + 1}


@router.post("/invoices/{invoice_id}/approve", response_model=InvoiceDetailOut)
def approve(invoice_id: UUID, body: ReviewActionIn, db: Session = Depends(get_db)):
    invoice = db.get(Invoice, invoice_id)
    if invoice is None:
        raise HTTPException(404, "Invoice not found.")
    return approve_invoice(db, invoice, body.reviewer, body.notes)


@router.post("/invoices/{invoice_id}/reject", response_model=InvoiceDetailOut)
def reject(invoice_id: UUID, body: ReviewActionIn, db: Session = Depends(get_db)):
    invoice = db.get(Invoice, invoice_id)
    if invoice is None:
        raise HTTPException(404, "Invoice not found.")
    return reject_invoice(db, invoice, body.reviewer, body.notes)


@router.post("/invoices/{invoice_id}/correct", response_model=InvoiceDetailOut)
def correct(invoice_id: UUID, body: CorrectionIn, db: Session = Depends(get_db)):
    invoice = db.get(Invoice, invoice_id)
    if invoice is None:
        raise HTTPException(404, "Invoice not found.")
    return correct_invoice(db, invoice, body.reviewer, body.header_fields, body.line_corrections, body.notes)


# --- Analytics (pandas-free; powers the Next.js dashboard) ---

@router.get("/analytics/status-summary", response_model=list[StatusSummaryOut])
def analytics_status_summary(db: Session = Depends(get_db)):
    return analytics.status_summary(db)


@router.get("/analytics/daily-intake", response_model=list[DailyIntakeOut])
def analytics_daily_intake(days: int = Query(30, le=365), db: Session = Depends(get_db)):
    return analytics.daily_intake(db, days)


@router.get("/analytics/gst-by-rate", response_model=list[GstByRateOut])
def analytics_gst_by_rate(db: Session = Depends(get_db)):
    return analytics.gst_by_rate(db)


@router.get("/analytics/hsn-summary", response_model=list[HsnSummaryOut])
def analytics_hsn_summary(limit: int = Query(20, le=100), db: Session = Depends(get_db)):
    return analytics.hsn_summary(db, limit)


@router.get("/analytics/vendor-spend", response_model=list[VendorSpendOut])
def analytics_vendor_spend(limit: int = Query(20, le=100), db: Session = Depends(get_db)):
    return analytics.vendor_spend(db, limit)


@router.get("/analytics/finding-frequency", response_model=list[FindingFrequencyOut])
def analytics_finding_frequency(limit: int = Query(30, le=100), db: Session = Depends(get_db)):
    return analytics.finding_frequency(db, limit)


@router.get("/analytics/reconciliation-summary", response_model=list[ReconciliationSummaryOut])
def analytics_reconciliation_summary(db: Session = Depends(get_db)):
    return analytics.reconciliation_summary(db)


@router.get("/analytics/duplicates", response_model=list[DuplicateFindingOut])
def analytics_duplicates(limit: int = Query(50, le=200), db: Session = Depends(get_db)):
    return analytics.duplicate_findings(db, limit)
