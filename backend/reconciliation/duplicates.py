"""Duplicate detection: exact file hash, (vendor GSTIN + invoice number), and fuzzy matches."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import timedelta
from difflib import SequenceMatcher

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from backend.config import Settings, get_settings
from backend.db.models import Invoice
from backend.schemas import Finding, InvoiceData, Severity

_LIVE = ("PROCESSING", "NEEDS_REVIEW", "AUTO_APPROVED", "APPROVED")


def normalize_invoice_no(s: str | None) -> str | None:
    """'INV-0012' / 'inv/12' / 'INV 012' -> 'INV12' (case, separators and leading zeros ignored)."""
    if not s:
        return None
    t = re.sub(r"[^A-Z0-9]", "", s.upper())
    t = re.sub(r"(?<=\D)0+(?=\d)", "", t)
    return t.lstrip("0") or t


@dataclass
class DuplicateMatch:
    match_type: str      # FILE_HASH | INVOICE_NO | FUZZY
    matched_invoice_id: int
    score: float
    detail: str


def find_duplicates(session: Session, inv: InvoiceData, doc_hash: str, exclude_id: int | None = None,
                    settings: Settings | None = None) -> list[DuplicateMatch]:
    s = settings or get_settings()
    out: dict[int, DuplicateMatch] = {}
    base = [Invoice.status.in_(_LIVE)]
    if exclude_id is not None:
        base.append(Invoice.id != exclude_id)

    def put(m: DuplicateMatch) -> None:
        cur = out.get(m.matched_invoice_id)
        if cur is None or m.score > cur.score:
            out[m.matched_invoice_id] = m

    for row in session.scalars(select(Invoice).where(and_(*base, Invoice.document_hash == doc_hash))):
        put(DuplicateMatch("FILE_HASH", row.id, 1.0, "identical file content"))

    norm = normalize_invoice_no(inv.invoice_number)
    gstin = (inv.vendor_gstin or "").upper() or None
    if norm and gstin:
        q = select(Invoice).where(and_(*base, Invoice.vendor_gstin == gstin, Invoice.invoice_number_norm == norm))
        for row in session.scalars(q):
            put(DuplicateMatch("INVOICE_NO", row.id, 0.98, f"same vendor GSTIN and invoice number '{row.invoice_number}'"))

    # fuzzy: same vendor, near-identical amount, close date, similar number or same PO
    if gstin and inv.grand_total is not None:
        q = select(Invoice).where(and_(*base, Invoice.vendor_gstin == gstin))
        for row in session.scalars(q):
            if row.grand_total is None or abs(row.grand_total - inv.grand_total) > s.amount_tolerance:
                continue
            if inv.invoice_date and row.invoice_date and abs(row.invoice_date - inv.invoice_date) > timedelta(
                    days=s.duplicate_date_window_days):
                continue
            sim = SequenceMatcher(None, norm or "", row.invoice_number_norm or "").ratio()
            same_po = bool(inv.po_number and row.po_number and inv.po_number == row.po_number)
            if sim >= s.duplicate_similarity or same_po:
                put(DuplicateMatch("FUZZY", row.id, round(max(sim, 0.75), 2),
                                   f"same vendor, amount and date window; number similarity {sim:.2f}"
                                   + ("; same PO" if same_po else "")))
    elif norm and inv.grand_total is not None:
        # vendor GSTIN unreadable: fall back to number + amount (weaker evidence)
        q = select(Invoice).where(and_(*base, Invoice.invoice_number_norm == norm))
        for row in session.scalars(q):
            if row.grand_total is not None and abs(row.grand_total - inv.grand_total) <= s.amount_tolerance:
                put(DuplicateMatch("FUZZY", row.id, 0.70, "same invoice number and amount; vendor GSTIN unreadable"))
    return sorted(out.values(), key=lambda m: -m.score)


def duplicate_findings(matches: list[DuplicateMatch]) -> list[Finding]:
    codes = {"FILE_HASH": ("D001", Severity.ERROR, "Identical file already processed"),
             "INVOICE_NO": ("D002", Severity.ERROR, "Invoice number already exists for this vendor"),
             "FUZZY": ("D003", Severity.WARNING, "Possible duplicate of an existing invoice")}
    return [Finding(code=codes[m.match_type][0], severity=codes[m.match_type][1], category="duplicate",
                    message=f"{codes[m.match_type][2]} (invoice id {m.matched_invoice_id}): {m.detail}.",
                    field="invoice_number", actual=str(m.matched_invoice_id)) for m in matches]
