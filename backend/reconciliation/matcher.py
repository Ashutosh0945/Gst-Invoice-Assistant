"""PO <-> invoice reconciliation: vendor, quantity, price, item and amount
matching, including missing-PO and partial-quantity scenarios.
"""
from __future__ import annotations

from decimal import Decimal
from difflib import SequenceMatcher

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.config import get_settings
from backend.db.models import POLine, PurchaseOrder
from backend.schemas import Finding, InvoiceData, LineItem, ReconStatus, Severity


def _desc_similarity(a: str | None, b: str | None) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def _match_po_line(inv_line: LineItem, po_lines: list[POLine]) -> POLine | None:
    """Match by HSN first (exact), else by description similarity."""
    by_hsn = [p for p in po_lines if inv_line.hsn_sac and p.hsn_sac == inv_line.hsn_sac]
    if len(by_hsn) == 1:
        return by_hsn[0]
    candidates = by_hsn or po_lines
    best, best_score = None, 0.0
    for p in candidates:
        score = _desc_similarity(inv_line.description, p.description)
        if score > best_score:
            best, best_score = p, score
    return best if best_score >= 0.5 else None


def reconcile_invoice(db: Session, inv: InvoiceData) -> tuple[list[Finding], list[dict]]:
    """Returns (findings, reconciliation_rows). reconciliation_rows are plain
    dicts ready to become ReconciliationResult ORM rows once the invoice_id
    and po_id are known to the caller.
    """
    settings = get_settings()
    findings: list[Finding] = []
    rows: list[dict] = []

    if not inv.po_number:
        findings.append(Finding(
            code="NO_PO_REFERENCE",
            severity=Severity.WARNING if get_settings().po_required else Severity.INFO,
            category="reconciliation",
            message="Invoice does not reference a purchase order.",
        ))
        for li in inv.items:
            rows.append({"po_id": None, "invoice_line_no": li.line_no, "po_line_no": None,
                         "status": ReconStatus.NO_PO.value})
        return findings, rows

    po = db.execute(
        select(PurchaseOrder).where(PurchaseOrder.po_number == inv.po_number)
    ).scalars().first()
    if po is None:
        findings.append(Finding(
            code="PO_NOT_FOUND", severity=Severity.ERROR, category="reconciliation",
            message=f"Referenced PO '{inv.po_number}' was not found in the system.",
            field="po_number", actual=inv.po_number,
        ))
        for li in inv.items:
            rows.append({"po_id": None, "invoice_line_no": li.line_no, "po_line_no": None,
                         "status": ReconStatus.PO_NOT_FOUND.value})
        return findings, rows

    # Vendor mismatch check.
    if po.vendor and inv.vendor_gstin and po.vendor.gstin and po.vendor.gstin != inv.vendor_gstin:
        findings.append(Finding(
            code="PO_VENDOR_MISMATCH", severity=Severity.ERROR, category="reconciliation",
            message=f"PO {inv.po_number} is registered to a different vendor GSTIN than the invoice.",
            field="vendor_gstin", expected=po.vendor.gstin, actual=inv.vendor_gstin,
        ))

    po_lines = list(po.lines)
    matched_po_line_ids = set()

    for li in inv.items:
        po_line = _match_po_line(li, po_lines)
        if po_line is None:
            findings.append(Finding(
                code="PO_LINE_NOT_FOUND", severity=Severity.WARNING, category="reconciliation",
                message=f"Invoice line {li.line_no} could not be matched to any line on PO {inv.po_number}.",
                line_no=li.line_no,
            ))
            rows.append({"po_id": po.id, "invoice_line_no": li.line_no, "po_line_no": None,
                         "status": ReconStatus.MISMATCH.value})
            continue

        matched_po_line_ids.add(po_line.id)
        remaining_qty = (po_line.quantity or Decimal("0")) - (po_line.quantity_invoiced or Decimal("0"))
        qty_ok = li.quantity is not None and remaining_qty >= (li.quantity - settings.po_qty_epsilon)

        price_variance_pct = None
        price_ok = True
        if li.unit_price is not None and po_line.unit_price:
            price_variance_pct = abs(li.unit_price - po_line.unit_price) / po_line.unit_price * 100
            price_ok = price_variance_pct <= settings.po_price_tolerance_pct

        # "Partial" describes a legitimate partial shipment/invoice against a
        # PO line that still has quantity left over *after* this invoice --
        # it is informational, not an error. Billing MORE than what remains
        # open is always a mismatch, never "partial".
        fully_consumes_remaining = (
            li.quantity is not None and remaining_qty is not None
            and abs(remaining_qty - li.quantity) <= settings.po_qty_epsilon
        )

        if qty_ok and price_ok:
            status = ReconStatus.MATCHED if fully_consumes_remaining or po_line.quantity == li.quantity else ReconStatus.PARTIAL
            if status == ReconStatus.PARTIAL:
                findings.append(Finding(
                    code="PO_PARTIAL_QUANTITY", severity=Severity.INFO, category="reconciliation",
                    message=(f"Invoice line {li.line_no} bills {li.quantity} of the {remaining_qty} "
                             f"units remaining open on PO line {po_line.line_no}; PO line stays open."),
                    line_no=li.line_no, expected=str(remaining_qty), actual=str(li.quantity),
                ))
        else:
            status = ReconStatus.MISMATCH
            if not qty_ok and li.quantity is not None:
                findings.append(Finding(
                    code="PO_QUANTITY_EXCEEDS", severity=Severity.ERROR, category="reconciliation",
                    message=(f"Invoice line {li.line_no} bills {li.quantity} units, exceeding the "
                             f"{remaining_qty} remaining open on PO line {po_line.line_no}."),
                    line_no=li.line_no, expected=str(remaining_qty), actual=str(li.quantity),
                ))
            if not price_ok:
                findings.append(Finding(
                    code="PO_PRICE_MISMATCH", severity=Severity.ERROR, category="reconciliation",
                    message=(f"Invoice line {li.line_no} unit price {li.unit_price} deviates "
                             f"{price_variance_pct:.1f}% from PO price {po_line.unit_price} "
                             f"(tolerance {settings.po_price_tolerance_pct}%)."),
                    line_no=li.line_no, expected=str(po_line.unit_price), actual=str(li.unit_price),
                ))

        rows.append({
            "po_id": po.id, "invoice_line_no": li.line_no, "po_line_no": po_line.line_no,
            "status": status.value,
            "qty_invoiced": li.quantity, "qty_po": po_line.quantity,
            "price_invoiced": li.unit_price, "price_po": po_line.unit_price,
            "variance_pct": price_variance_pct,
        })

    unmatched_po_lines = [p for p in po_lines if p.id not in matched_po_line_ids]
    if unmatched_po_lines:
        findings.append(Finding(
            code="PO_LINES_NOT_INVOICED", severity=Severity.INFO, category="reconciliation",
            message=f"{len(unmatched_po_lines)} PO line(s) on {inv.po_number} were not billed on this invoice.",
        ))

    return findings, rows
