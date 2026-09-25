"""Compliance endpoints: GSTR-2B reconciliation, ITC eligibility, e-invoice QR checks,
vendor risk, and the extraction-model benchmark."""
from __future__ import annotations

import tempfile
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from backend.analytics import compliance
from backend.api.deps import require_api_key
from backend.api.schemas_api import InvoiceDetailOut, PaymentIn, QrVerifyIn
from backend.api.deps import get_console_db as get_db
from backend.db.models import Gstr2bImport, Invoice
from backend.einvoice.qr import find_signed_qr
from backend.einvoice.verify import verify_einvoice
from backend.gstr2b.parser import Gstr2bFormatError
from backend.gstr2b.service import delete_import, import_gstr2b
from backend.itc.service import reassess_all
from backend.services.review_service import record_payment

router = APIRouter(dependencies=[Depends(require_api_key)])

MAX_2B_BYTES = 25 * 1024 * 1024


# --- overview -----------------------------------------------------------------
@router.get("/compliance/overview")
def overview(db: Session = Depends(get_db)):
    itc = compliance.itc_summary(db)
    imports = compliance.gstr2b_imports(db)
    einv = compliance.einvoice_summary(db)["counts"]
    return {"itc": itc, "itc_by_month": compliance.itc_by_month(db),
            "latest_gstr2b": imports[0] if imports else None, "einvoice_counts": einv}


# --- GSTR-2B -------------------------------------------------------------------
@router.post("/gstr2b/import", status_code=201)
async def gstr2b_import(file: UploadFile, db: Session = Depends(get_db)):
    raw = await file.read()
    if len(raw) > MAX_2B_BYTES:
        raise HTTPException(413, "File is larger than 25 MB.")
    try:
        imp = import_gstr2b(db, raw, file.filename or "gstr2b.json")
    except Gstr2bFormatError as exc:
        raise HTTPException(422, str(exc)) from exc
    return next(i for i in compliance.gstr2b_imports(db) if i["id"] == str(imp.id))


@router.get("/gstr2b/imports")
def gstr2b_imports(db: Session = Depends(get_db)):
    return compliance.gstr2b_imports(db)


@router.get("/gstr2b/imports/{import_id}/records")
def gstr2b_records(import_id: UUID, status: str | None = None, db: Session = Depends(get_db)):
    if db.get(Gstr2bImport, import_id) is None:
        raise HTTPException(404, "GSTR-2B import not found.")
    return compliance.gstr2b_records(db, import_id, status)


@router.delete("/gstr2b/imports/{import_id}", status_code=204)
def gstr2b_delete(import_id: UUID, db: Session = Depends(get_db)):
    delete_import(db, import_id)


@router.get("/gstr2b/missing")
def gstr2b_missing(db: Session = Depends(get_db)):
    return compliance.missing_in_2b(db)


# --- ITC ------------------------------------------------------------------------
@router.get("/itc/summary")
def itc_summary(db: Session = Depends(get_db)):
    return compliance.itc_summary(db)


@router.get("/itc/assessments")
def itc_assessments(status: str | None = None, limit: int = Query(200, le=1000), db: Session = Depends(get_db)):
    return compliance.itc_assessments(db, status, limit)


@router.post("/itc/reassess")
def itc_reassess(db: Session = Depends(get_db)):
    return {"reassessed": reassess_all(db)}


@router.post("/invoices/{invoice_id}/payment", response_model=InvoiceDetailOut)
def invoice_payment(invoice_id: UUID, body: PaymentIn, db: Session = Depends(get_db)):
    invoice = db.get(Invoice, invoice_id)
    if invoice is None:
        raise HTTPException(404, "Invoice not found.")
    return record_payment(db, invoice, body.paid_on, body.actor)


# --- e-invoice --------------------------------------------------------------------
def _result_json(res) -> dict:
    return {"status": res.status.value, "irn": res.irn, "data": res.data,
            "signature_checked": res.signature_checked, "signature_valid": res.signature_valid,
            "comparisons": res.comparisons,
            "findings": [f.model_dump(mode="json") for f in res.findings]}


@router.get("/einvoice/summary")
def einvoice_summary(db: Session = Depends(get_db)):
    return compliance.einvoice_summary(db)


@router.post("/einvoice/verify")
def einvoice_verify(body: QrVerifyIn):
    return _result_json(verify_einvoice(body.qr_text.strip(), None))


@router.post("/einvoice/verify-file")
async def einvoice_verify_file(file: UploadFile):
    from backend.ingestion.loader import load_document

    suffix = Path(file.filename or "qr.png").suffix or ".png"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(await file.read())
        tmp_path = Path(tmp.name)
    try:
        _, pages = load_document(tmp_path)
        token = find_signed_qr([p.image for p in pages])
    finally:
        tmp_path.unlink(missing_ok=True)
    return _result_json(verify_einvoice(token, None))


# --- vendors + model --------------------------------------------------------------
@router.get("/analytics/vendor-risk")
def vendor_risk(limit: int = Query(50, le=200), db: Session = Depends(get_db)):
    return compliance.vendor_risk(db, limit)


@router.get("/ml/benchmark")
def ml_benchmark():
    res = compliance.benchmark_results()
    if res is None:
        raise HTTPException(404, "No benchmark has been run yet. Run: python -m ml.benchmark")
    return res
