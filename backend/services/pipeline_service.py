"""End-to-end invoice processing: ingest -> preprocess -> OCR -> extract ->
validate -> duplicate-check -> reconcile -> score -> (optional) LLM explain ->
persist -> route to auto-approval or the human review queue.

This is the single function Prefect flows, the FastAPI upload endpoint, and
CLI scripts all call — there is exactly one code path that produces a stored
invoice, so every entry point is bound by the same rules.
"""
from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy.orm import Session

from backend.db.models import Invoice, InvoiceLine, ReconciliationResult, ValidationFinding
from backend.einvoice.qr import find_signed_qr
from backend.einvoice.verify import verify_einvoice
from backend.itc.service import assess_invoice
from backend.extraction.pipeline import extract_invoice
from backend.ingestion.loader import load_document
from backend.llm.explain import explain_findings
from backend.reconciliation.matcher import reconcile_invoice
from backend.schemas import Finding, InvoiceData, InvoiceStatus
from backend.scoring.confidence import compute_confidence, decide_status
from backend.services.audit_service import log_action
from backend.services.vendor_service import get_or_create_vendor
from backend.validation.duplicate import find_duplicates
from backend.validation.engine import validate_invoice

logger = logging.getLogger(__name__)


def process_invoice_file(db: Session, path: str | Path) -> Invoice:
    path = Path(path)
    doc_hash, pages = load_document(path)
    inv_data, page_sources = extract_invoice(pages)
    qr_token = find_signed_qr([p.image for p in pages])
    einv = verify_einvoice(qr_token, inv_data)

    vendor = get_or_create_vendor(db, inv_data.vendor_gstin, inv_data.vendor_name)

    invoice = Invoice(
        source_filename=path.name,
        document_hash=doc_hash,
        vendor_id=vendor.id if vendor else None,
        vendor_name_raw=inv_data.vendor_name,
        vendor_gstin_raw=inv_data.vendor_gstin,
        buyer_gstin_raw=inv_data.buyer_gstin,
        invoice_number=inv_data.invoice_number,
        invoice_date=inv_data.invoice_date,
        po_number_raw=inv_data.po_number,
        place_of_supply=inv_data.place_of_supply,
        subtotal=inv_data.subtotal,
        total_cgst=inv_data.total_cgst,
        total_sgst=inv_data.total_sgst,
        total_igst=inv_data.total_igst,
        total_cess=inv_data.total_cess,
        round_off=inv_data.round_off,
        grand_total=inv_data.grand_total,
        extraction_confidence=inv_data.field_confidence,
        status=InvoiceStatus.PROCESSING.value,
        irn=einv.irn,
        einvoice_status=einv.status.value,
        einvoice_data={"payload": einv.data, "comparisons": einv.comparisons,
                       "signature_checked": einv.signature_checked,
                       "signature_valid": einv.signature_valid} if einv.data else None,
    )
    db.add(invoice)
    db.flush()  # assigns invoice.id

    for li in inv_data.items:
        db.add(InvoiceLine(
            invoice_id=invoice.id, line_no=li.line_no, description=li.description,
            hsn_sac=li.hsn_sac, quantity=li.quantity, unit=li.unit, unit_price=li.unit_price,
            discount=li.discount, taxable_value=li.taxable_value, gst_rate=li.gst_rate,
            cgst=li.cgst, sgst=li.sgst, igst=li.igst, cess=li.cess, line_total=li.line_total,
            confidence=li.confidence,
        ))

    findings: list[Finding] = []
    findings.extend(validate_invoice(inv_data))
    findings.extend(find_duplicates(db, doc_hash, inv_data, exclude_invoice_id=invoice.id))
    recon_findings, recon_rows = reconcile_invoice(db, inv_data)
    findings.extend(recon_findings)
    findings.extend(einv.findings)

    for f in findings:
        db.add(ValidationFinding(
            invoice_id=invoice.id, code=f.code, category=f.category, severity=f.severity.value,
            message=f.message, field=f.field, line_no=f.line_no, expected=f.expected, actual=f.actual,
        ))
    for row in recon_rows:
        db.add(ReconciliationResult(invoice_id=invoice.id, **row))

    confidence = compute_confidence(inv_data, findings)
    status = decide_status(confidence, findings)
    invoice.confidence_score = confidence
    invoice.status = status.value

    explanation = explain_findings(inv_data, findings)
    if explanation:
        invoice.llm_explanation = explanation

    db.flush()
    db.refresh(invoice)
    assess_invoice(db, invoice)

    log_action(db, invoice.id, actor="system", action="PROCESSED", details={
        "einvoice_status": einv.status.value,
        "page_sources": page_sources, "confidence": confidence, "status": status.value,
        "finding_count": len(findings),
    })

    db.commit()
    db.refresh(invoice)
    return invoice
