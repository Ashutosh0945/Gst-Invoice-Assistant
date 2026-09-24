"""Synthetic GST invoice generator.

Produces (a) a rendered PDF invoice and (b) the ground-truth InvoiceData it
was rendered from. Used to build test fixtures, to bootstrap LayoutLMv3
training data (image + word boxes + BIO labels can be derived from the same
ground truth), and to smoke-test the full pipeline without real vendor data.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import pymupdf as fitz  # PyMuPDF

from backend.schemas import InvoiceData, LineItem

_STATE_CODES = ["27", "24", "29", "07", "19"]  # MH, GJ, KA, DL, WB
_ADJ = ["Shree", "Om", "Jai", "Sai", "National", "United"]
_NOUN = ["Traders", "Enterprises", "Industries", "Suppliers", "Electricals", "Textiles"]
_ITEMS = [
    ("Notebooks A4 200pg", "4820", Decimal("0")),
    ("Office Chair", "9401", Decimal("18")),
    ("LED Monitor 24in", "8528", Decimal("18")),
    ("Cotton T-Shirt", "6109", Decimal("5")),
    ("Air Conditioner 1.5T", "8415", Decimal("18")),
    ("Packaged Namkeen 1kg", "2106", Decimal("5")),
    ("IT Consulting Services", "998314", Decimal("18")),
]


_CHARSET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _gstin_checksum(gstin_14: str) -> str:
    """Computes the mod-36 checksum digit for the first 14 characters of a GSTIN
    (same algorithm as app.validation.gstin.checksum_valid, kept in sync so
    every synthetic GSTIN passes real checksum validation)."""
    factor = 1
    total = 0
    for ch in gstin_14:
        digit = _CHARSET.index(ch)
        val = digit * factor
        val = (val // 36) + (val % 36)
        total += val
        factor = 2 if factor == 1 else 1
    return _CHARSET[(36 - (total % 36)) % 36]


def _rand_gstin(state_code: str) -> str:
    letters = "".join(random.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ") for _ in range(5))
    digits = "".join(random.choice("0123456789") for _ in range(4))
    body = f"{state_code}{letters}{digits}A1Z"  # entity code fixed at "1", default "Z"
    return body + _gstin_checksum(body)


def _company_name() -> str:
    return f"{random.choice(_ADJ)} {random.choice(_NOUN)}"


@dataclass
class SyntheticInvoice:
    ground_truth: InvoiceData
    pdf_bytes: bytes


def generate_invoice(
    invoice_no: str | None = None,
    invoice_date=None,
    n_items: int = 3,
    inject_error: str | None = None,   # None | "arithmetic" | "gst_rate" | "hsn_invalid" | "tax_type"
    seed: int | None = None,
) -> SyntheticInvoice:
    if seed is not None:
        random.seed(seed)

    import datetime as _dt
    invoice_no = invoice_no or f"INV-{random.randint(1000, 9999)}"
    invoice_date = invoice_date or _dt.date.today()

    vendor_state = random.choice(_STATE_CODES)
    buyer_state = vendor_state if inject_error != "tax_type" else random.choice([s for s in _STATE_CODES if s != vendor_state])
    same_state = vendor_state == buyer_state

    vendor_gstin = _rand_gstin(vendor_state)
    buyer_gstin = _rand_gstin(buyer_state)

    items: list[LineItem] = []
    subtotal = Decimal("0")
    total_cgst = Decimal("0")
    total_sgst = Decimal("0")
    total_igst = Decimal("0")

    for i in range(n_items):
        desc, hsn, rate = random.choice(_ITEMS)
        qty = Decimal(random.randint(1, 20))
        unit_price = Decimal(random.randint(100, 5000))
        taxable = (qty * unit_price).quantize(Decimal("0.01"))

        if inject_error == "arithmetic" and i == 0:
            taxable += Decimal("50.00")  # deliberately break qty*price=taxable

        line_rate = rate
        if inject_error == "gst_rate" and i == 0:
            line_rate = (rate + Decimal("5")) % Decimal("40")
        if inject_error == "hsn_invalid" and i == 0:
            hsn = "12A4"  # not all-digit -> invalid format

        tax_amt = (taxable * line_rate / Decimal("100")).quantize(Decimal("0.01"))
        if same_state and inject_error != "tax_type":
            cgst, sgst, igst = (tax_amt / 2).quantize(Decimal("0.01")), (tax_amt / 2).quantize(Decimal("0.01")), Decimal("0")
        else:
            cgst, sgst, igst = Decimal("0"), Decimal("0"), tax_amt

        line_total = (taxable + cgst + sgst + igst).quantize(Decimal("0.01"))

        items.append(LineItem(
            line_no=i + 1, description=desc, hsn_sac=hsn, quantity=qty, unit_price=unit_price,
            taxable_value=taxable, gst_rate=line_rate, cgst=cgst, sgst=sgst, igst=igst,
            line_total=line_total, confidence=1.0,
        ))
        subtotal += taxable
        total_cgst += cgst
        total_sgst += sgst
        total_igst += igst

    grand_total = (subtotal + total_cgst + total_sgst + total_igst).quantize(Decimal("0.01"))

    inv = InvoiceData(
        vendor_name=_company_name(), vendor_gstin=vendor_gstin,
        buyer_name="Buyer Co Pvt Ltd", buyer_gstin=buyer_gstin,
        invoice_number=invoice_no, invoice_date=invoice_date,
        place_of_supply=buyer_state, items=items,
        subtotal=subtotal.quantize(Decimal("0.01")), total_cgst=total_cgst.quantize(Decimal("0.01")),
        total_sgst=total_sgst.quantize(Decimal("0.01")), total_igst=total_igst.quantize(Decimal("0.01")),
        total_cess=Decimal("0"), round_off=Decimal("0"), grand_total=grand_total,
        field_confidence={f: 1.0 for f in ["vendor_gstin", "invoice_number", "invoice_date", "grand_total", "subtotal", "items"]},
    )
    pdf_bytes = render_pdf(inv)
    return SyntheticInvoice(ground_truth=inv, pdf_bytes=pdf_bytes)


def render_pdf(inv: InvoiceData) -> bytes:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)  # A4
    y = 40
    def line(text, size=10, dy=16):
        nonlocal y
        page.insert_text((40, y), text, fontsize=size)
        y += dy

    line(f"TAX INVOICE", size=14, dy=24)
    line(f"Invoice No: {inv.invoice_number}    Date: {inv.invoice_date}")
    line(f"Vendor GSTIN: {inv.vendor_gstin}    Name: {inv.vendor_name}")
    line(f"Buyer GSTIN: {inv.buyer_gstin}")
    if inv.po_number:
        line(f"PO No: {inv.po_number}")
    line(f"Place of Supply: {inv.place_of_supply}")
    y += 8
    line("No  Description               HSN     Qty   Rate    Taxable   GST%  Total")
    for li in inv.items:
        row = (f"{li.line_no:<3} {li.description[:22]:<22} {li.hsn_sac:<7} "
               f"{li.quantity:<5} {li.unit_price:<7} {li.taxable_value:<9} {li.gst_rate:<5} {li.line_total}")
        line(row, size=9)
    y += 8
    line(f"Taxable Value: {inv.subtotal}")
    line(f"CGST: {inv.total_cgst}   SGST: {inv.total_sgst}   IGST: {inv.total_igst}")
    line(f"Round Off: {inv.round_off}")
    line(f"Grand Total: {inv.grand_total}", size=12)

    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def save_invoice(si: SyntheticInvoice, out_dir: str | Path, filename: str | None = None) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    filename = filename or f"{si.ground_truth.invoice_number}.pdf"
    path = out_dir / filename
    path.write_bytes(si.pdf_bytes)
    return path
