"""Duplicate invoice detection.

Two layers:
  1. Exact document-hash match (byte-identical re-upload) -- always checked.
  2. Fuzzy match on (vendor GSTIN/name, invoice number, date window, amount) --
     catches the same invoice re-typed, re-scanned, or resubmitted with a
     trivial formatting change.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from difflib import SequenceMatcher

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.config import get_settings
from backend.db.models import Invoice
from backend.schemas import Finding, InvoiceData, Severity


@dataclass
class DuplicateCandidate:
    invoice_id: str
    reason: str
    similarity: float


def _similar(a: str | None, b: str | None) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def find_duplicates(db: Session, doc_hash: str, inv: InvoiceData, exclude_invoice_id=None) -> list[Finding]:
    settings = get_settings()
    findings: list[Finding] = []

    # --- exact byte-for-byte re-upload ---
    stmt = select(Invoice).where(Invoice.document_hash == doc_hash)
    if exclude_invoice_id is not None:
        stmt = stmt.where(Invoice.id != exclude_invoice_id)
    exact = db.execute(stmt).scalars().first()
    if exact is not None:
        findings.append(Finding(
            code="DUPLICATE_EXACT_FILE", severity=Severity.ERROR, category="duplicate",
            message=f"This exact file was already ingested as invoice {exact.id} ({exact.invoice_number}).",
            actual=str(exact.id),
        ))
        return findings  # exact match makes fuzzy checks redundant

    if not inv.invoice_number:
        return findings

    window_start: date | None = None
    window_end: date | None = None
    if inv.invoice_date:
        window_start = inv.invoice_date - timedelta(days=settings.duplicate_date_window_days)
        window_end = inv.invoice_date + timedelta(days=settings.duplicate_date_window_days)

    candidates_stmt = select(Invoice).where(Invoice.invoice_number.isnot(None))
    if exclude_invoice_id is not None:
        candidates_stmt = candidates_stmt.where(Invoice.id != exclude_invoice_id)
    if inv.vendor_gstin:
        candidates_stmt = candidates_stmt.where(Invoice.vendor_gstin_raw == inv.vendor_gstin)
    candidates = db.execute(candidates_stmt).scalars().all()

    for cand in candidates:
        num_sim = _similar(cand.invoice_number, inv.invoice_number)
        if num_sim < settings.duplicate_similarity:
            continue
        if window_start and cand.invoice_date and not (window_start <= cand.invoice_date <= window_end):
            continue
        amounts_match = (
            cand.grand_total is not None and inv.grand_total is not None
            and abs(Decimal(cand.grand_total) - inv.grand_total) <= settings.amount_tolerance
        )
        if num_sim > 0.97 or (num_sim >= settings.duplicate_similarity and amounts_match):
            findings.append(Finding(
                code="DUPLICATE_LIKELY", severity=Severity.ERROR, category="duplicate",
                message=(f"Likely duplicate of invoice {cand.id}: invoice_number similarity={num_sim:.2f}, "
                         f"same vendor, dates within {settings.duplicate_date_window_days} days"
                         + (", matching amount." if amounts_match else ".")),
                field="invoice_number", expected=cand.invoice_number, actual=inv.invoice_number,
            ))

    return findings
