from __future__ import annotations

import logging

import shutil
import tempfile
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, UploadFile
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


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".bmp"}


@router.post("/invoices", response_model=InvoiceDetailOut, status_code=201)
def upload_invoice(file: UploadFile, optimize: bool = False, db: Session = Depends(get_db),
                   idempotency_key: str | None = Header(default=None, max_length=128)):
    """optimize=true (camera photos): the photo goes through the capture pipeline first and the
    OCR-ready image -- not the raw photo -- is passed to the existing OCR/extraction pipeline."""
    from backend.db.models import Document, UploadReceipt
    if idempotency_key:   # a retried upload (same client key) returns the invoice it already created
        receipt = db.get(UploadReceipt, idempotency_key)
        if receipt is not None:
            existing = db.get(Invoice, receipt.invoice_id)
            if existing is not None:
                return existing
    suffix = (Path(file.filename or "invoice").suffix or ".pdf").lower()
    allowed = {".pdf"} | IMAGE_SUFFIXES
    if suffix not in allowed:
        raise HTTPException(415, f"Unsupported file type '{suffix}'. Upload a PDF or an image (JPG, PNG, WEBP, TIFF).")
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = Path(tmp.name)
    raw_bytes = tmp_path.read_bytes()
    if not raw_bytes:
        tmp_path.unlink(missing_ok=True)
        raise HTTPException(422, "The file is empty.")
    work_path, capture, capture_error = tmp_path, None, None
    try:
        if optimize and suffix in IMAGE_SUFFIXES:
            import cv2

            from backend.capture.optimize import optimize as run_capture
            img = cv2.imread(str(tmp_path))
            if img is not None:
                try:
                    capture = run_capture(img)
                    work_path = tmp_path.with_name(tmp_path.stem + "_ocr_ready.png")
                    cv2.imwrite(str(work_path), capture.ocr_ready)
                except Exception as exc:  # noqa: BLE001 - optimisation is a bonus; never fail the upload over it
                    logging.getLogger(__name__).exception("Capture optimisation failed; using the original photo")
                    capture_error = f"{type(exc).__name__}: {str(exc)[:200]}"
                    work_path, capture = tmp_path, None
        invoice = process_invoice_file(db, work_path)
        if capture_error is not None:
            from backend.services.audit_service import log_action
            log_action(db, invoice.id, actor="system", action="CAPTURE_FAILED",
                       details={"error": capture_error, "fallback": "original photo used", "original_filename": file.filename})
            db.commit()
            db.refresh(invoice)
        if capture is not None:
            from backend.services.audit_service import log_action
            log_action(db, invoice.id, actor="system", action="CAPTURE_OPTIMIZED",
                       details={"steps": capture.steps, "quality": capture.quality, "original_filename": file.filename})
            db.commit()
            db.refresh(invoice)
        # Keep the original (and the OCR-ready copy) so the document can be reviewed later.
        import hashlib
        db.add(Document(invoice_id=invoice.id, kind="original", content_type=file.content_type or "application/octet-stream",
                        filename=file.filename, sha256=hashlib.sha256(raw_bytes).hexdigest(), size_bytes=len(raw_bytes), content=raw_bytes))
        if work_path != tmp_path and work_path.exists():
            ocr_bytes = work_path.read_bytes()
            db.add(Document(invoice_id=invoice.id, kind="ocr_ready", content_type="image/png", filename=(file.filename or "") + " (OCR-ready)",
                            sha256=hashlib.sha256(ocr_bytes).hexdigest(), size_bytes=len(ocr_bytes), content=ocr_bytes))
        if idempotency_key:
            db.add(UploadReceipt(key=idempotency_key, invoice_id=invoice.id))
        db.commit()
        db.refresh(invoice)
    finally:
        tmp_path.unlink(missing_ok=True)
        if work_path != tmp_path:
            work_path.unlink(missing_ok=True)
    # ML / similarity checks run after the invoice is safely saved and can never fail the upload.
    try:
        from backend.ml.anomaly import score_one_safely
        from backend.ml.duplicates import scan_safely
        scan_safely(db, invoice)
        score_one_safely(db, invoice)
    except Exception:  # noqa: BLE001 - a missing optional dependency must not fail a saved upload
        import logging
        logging.getLogger(__name__).exception("Post-save ML checks skipped for %s", invoice.id)
    db.refresh(invoice)
    return invoice


@router.post("/capture/analyze")
async def capture_analyze(file: UploadFile):
    """Preview only: runs the capture pipeline and returns the quality report plus the enhanced and
    OCR-ready images. Nothing is stored; the caller decides whether to upload (Retake / Use anyway)."""
    import base64

    import cv2
    import numpy as np

    from backend.capture.optimize import optimize as run_capture, to_jpeg
    raw = await file.read()
    if len(raw) > 15 * 1024 * 1024:
        raise HTTPException(413, "Photo is larger than 15 MB.")
    img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise HTTPException(422, "That file isn't a readable image.")
    try:
        r = run_capture(img)
    except Exception as exc:  # noqa: BLE001
        logging.getLogger(__name__).exception("Capture analysis failed")
        from backend.ocr.engine import engine_name
        return {"capture_failed": True, "message": "Couldn't optimise this photo; you can still upload the original.",
                "error": f"{type(exc).__name__}", "steps": [], "enhanced": None, "ocr_ready": None, "ocr_ready_same_as_enhanced": True,
                "quality": {"verdict": "fair", "score": None, "warnings": [{"code": "not_analysed", "severity": "low",
                            "message": "Photo optimisation failed, so quality couldn't be checked. The original photo will be used."}], "metrics": {}},
                "ocr_engine": engine_name(), "ocr_available": engine_name() is not None}
    b64 = lambda im: "data:image/jpeg;base64," + base64.b64encode(to_jpeg(im)).decode()  # noqa: E731
    same = r.ocr_ready is r.enhanced
    from backend.ocr.engine import engine_name
    return {"steps": r.steps, "quality": r.quality, "enhanced": b64(r.enhanced),
            "ocr_ready": None if same else b64(r.ocr_ready), "ocr_ready_same_as_enhanced": same,
            "ocr_engine": engine_name(), "ocr_available": engine_name() is not None}


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
