"""Rule/regex-based structured extractor.

This is the baseline extractor: pure text + regex + positional heuristics over
OCR/native words, no ML model required. It is what LayoutLMv3 (extraction/layoutlm.py)
is compared against and what the system falls back to when no trained model is
configured — the pipeline is NEVER blocked on the ML model being present.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from backend.schemas import InvoiceData, LineItem, OCRWord

GSTIN_RE = re.compile(r"\b\d{2}[A-Z]{5}\d{4}[A-Z]\d[Z][A-Z0-9]\b")
INVOICE_NO_RE = re.compile(r"\b(?:invoice|inv|bill)\b\s*(?:no\.?|number|#)?\s*[:\-]?\s*([A-Za-z0-9\-\/]{3,30})", re.I)
PO_NO_RE = re.compile(r"\b(?:p\.?o\.?|purchase\s*order)\b\s*(?:no\.?|number|#)?\s*[:\-]?\s*([A-Za-z0-9\-\/]{3,30})", re.I)
HSN_RE = re.compile(r"\b\d{4,8}\b")
DATE_PATTERNS = [
    ("%d-%m-%Y", re.compile(r"\b(\d{2}-\d{2}-\d{4})\b")),
    ("%d/%m/%Y", re.compile(r"\b(\d{2}/\d{2}/\d{4})\b")),
    ("%d-%b-%Y", re.compile(r"\b(\d{2}-[A-Za-z]{3}-\d{4})\b")),
    ("%Y-%m-%d", re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")),
]
STATE_CODE_RE = re.compile(r"place\s*of\s*supply\s*[:\-]?\s*(\d{2})", re.I)
# Matches both comma-grouped Indian numerals (1,55,698.56) and plain digit runs
# (155698.56) -- OCR/native text rarely preserves grouping consistently.
MONEY_RE = re.compile(r"[-+]?\d+(?:,\d{2,3})*(?:\.\d{1,2})?")


def _to_decimal(s: str | None) -> Decimal | None:
    if not s:
        return None
    cleaned = s.replace(",", "").replace("₹", "").replace("Rs.", "").replace("INR", "").strip()
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def _find_date(text: str) -> date | None:
    for fmt, pat in DATE_PATTERNS:
        m = pat.search(text)
        if m:
            try:
                return datetime.strptime(m.group(1), fmt).date()
            except ValueError:
                continue
    return None


def _words_to_text(words: list[OCRWord], line_tolerance_px: float = 4.0) -> str:
    """Reconstructs reading-order lines of text from individual word boxes.

    OCR/native-PDF extraction gives one box per word, not per line, so a naive
    join loses the row structure that both header labels (e.g. "Invoice No:
    1234") and item-table rows depend on. This groups words whose vertical
    centers are within `line_tolerance_px` of each other into the same line,
    then orders lines top-to-bottom and words left-to-right within a line.
    """
    if not words:
        return ""

    def y_center(w: OCRWord) -> float:
        return (w.bbox[1] + w.bbox[3]) / 2

    ordered = sorted(words, key=y_center)
    lines: list[list[OCRWord]] = []
    for w in ordered:
        yc = y_center(w)
        if lines and abs(y_center(lines[-1][-1]) - yc) <= line_tolerance_px:
            lines[-1].append(w)
        else:
            lines.append([w])

    out_lines = []
    for line_words in lines:
        line_words.sort(key=lambda w: w.bbox[0])
        out_lines.append(" ".join(w.text for w in line_words))
    return "\n".join(out_lines)


def _labelled_amount(text: str, labels: list[str]) -> Decimal | None:
    for label in labels:
        pat = re.compile(rf"{label}\s*[:\-]?\s*(?:Rs\.?|₹|INR)?\s*({MONEY_RE.pattern})", re.I)
        m = pat.search(text)
        if m:
            val = _to_decimal(m.group(1))
            if val is not None:
                return val
    return None


def _extract_header(text: str) -> dict:
    """Header fields are matched line-by-line (not against the whole blob) so
    a label on one line never "borrows" a value from an unrelated line below
    it -- important once the text has been reconstructed from word boxes
    rather than a clean paragraph.
    """
    gstins = GSTIN_RE.findall(text)
    lines = text.splitlines()

    def first_match(pattern: re.Pattern) -> re.Match | None:
        for ln in lines:
            m = pattern.search(ln)
            if m:
                return m
        return None

    def first_amount(labels: list[str]) -> Decimal | None:
        for ln in lines:
            val = _labelled_amount(ln, labels)
            if val is not None:
                return val
        return None

    inv_no = first_match(INVOICE_NO_RE)
    po_no = first_match(PO_NO_RE)
    state = first_match(STATE_CODE_RE)
    date_val = None
    for ln in lines:
        date_val = _find_date(ln)
        if date_val:
            break

    return {
        "vendor_gstin": gstins[0] if gstins else None,
        "buyer_gstin": gstins[1] if len(gstins) > 1 else None,
        "invoice_number": inv_no.group(1).strip() if inv_no else None,
        "po_number": po_no.group(1).strip() if po_no else None,
        "invoice_date": date_val,
        "place_of_supply": state.group(1) if state else None,
        "subtotal": first_amount(["taxable\\s*value", "sub\\s*total", "subtotal"]),
        "total_cgst": first_amount(["cgst"]),
        "total_sgst": first_amount(["sgst"]),
        "total_igst": first_amount(["igst"]),
        "total_cess": first_amount(["cess"]),
        "round_off": first_amount(["round\\s*off"]),
        "grand_total": first_amount(["grand\\s*total", "total\\s*amount", "amount\\s*payable", "invoice\\s*total"]),
    }


# A row of the item table is expected to look roughly like:
#   <line_no> <description...> <hsn> <qty> <unit_price> <taxable_value> <gst_rate> <line_total>
# We detect candidate rows by finding lines with an HSN-shaped token and >=3 numbers after it.
ITEM_ROW_RE = re.compile(
    rf"^\s*(?P<line_no>\d{{1,3}})?\s*(?P<desc>.+?)\s+(?P<hsn>\d{{4,8}})\s+"
    rf"(?P<qty>{MONEY_RE.pattern})\s+(?P<rate>{MONEY_RE.pattern})\s+"
    rf"(?P<taxable>{MONEY_RE.pattern})\s+(?:(?P<gst_rate>\d{{1,2}}(?:\.\d+)?)\s*%?\s+)?"
    rf"(?P<total>{MONEY_RE.pattern})\s*$"
)


def _extract_line_items(text: str) -> list[LineItem]:
    items: list[LineItem] = []
    for i, raw_line in enumerate(text.splitlines()):
        m = ITEM_ROW_RE.match(raw_line.strip())
        if not m:
            continue
        g = m.groupdict()
        qty = _to_decimal(g["qty"])
        unit_price = _to_decimal(g["rate"])
        taxable = _to_decimal(g["taxable"])
        total = _to_decimal(g["total"])
        gst_rate = _to_decimal(g["gst_rate"]) if g["gst_rate"] else None
        items.append(LineItem(
            line_no=int(g["line_no"]) if g["line_no"] else len(items) + 1,
            description=g["desc"].strip(),
            hsn_sac=g["hsn"],
            quantity=qty,
            unit_price=unit_price,
            taxable_value=taxable,
            gst_rate=gst_rate,
            line_total=total,
            confidence=0.6,  # regex-matched rows start at moderate confidence
        ))
    return items


def extract_baseline(words: list[OCRWord]) -> InvoiceData:
    text = _words_to_text(words)
    header = _extract_header(text)
    items = _extract_line_items(text)

    field_confidence = {k: (0.85 if v is not None else 0.0) for k, v in header.items()}
    if items:
        field_confidence["items"] = sum(i.confidence for i in items) / len(items)
    else:
        field_confidence["items"] = 0.0

    return InvoiceData(
        vendor_gstin=header["vendor_gstin"],
        buyer_gstin=header["buyer_gstin"],
        invoice_number=header["invoice_number"],
        invoice_date=header["invoice_date"],
        po_number=header["po_number"],
        place_of_supply=header["place_of_supply"],
        items=items,
        subtotal=header["subtotal"],
        total_cgst=header["total_cgst"],
        total_sgst=header["total_sgst"],
        total_igst=header["total_igst"],
        total_cess=header["total_cess"],
        round_off=header["round_off"],
        grand_total=header["grand_total"],
        field_confidence=field_confidence,
    )
