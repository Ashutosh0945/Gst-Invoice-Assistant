"""Rule-based extractor (OCR text + layout heuristics).

Serves two purposes: (1) the fallback that keeps the system working without LayoutLMv3 weights, and
(2) baseline #1 for the research evaluation (OCR + rules vs OCR + LayoutLMv3).
Limitation: table parsing needs a single-row header; exotic layouts are what LayoutLMv3 is for.
"""
from __future__ import annotations

import re
from decimal import Decimal

from backend.extraction.common import DATE_PAT, Line, parse_date, parse_decimal, words_to_lines
from backend.schemas import InvoiceData, LineItem, OCRWord, PageData
from backend.validation.gst import GSTIN_RE, state_code_from_text

GSTIN_ANY = re.compile(r"\b(\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z])\b")
AMOUNT = re.compile(r"-?\(?\d[\d,]*\.\d{1,2}\)?|-?\(?\d[\d,]*\)?")
BUYER_MARK = re.compile(r"(?i)\b(bill(?:ed)?\s*to|buyer|consignee|ship(?:ped)?\s*to|recipient|customer|sold\s+to)\b")
INV_NO = re.compile(r"(?i)\b(?:tax\s+)?(?:invoice|inv|bill)\s*(?:no\.?|number|#)\s*[:\-]?\s*([A-Z0-9][A-Z0-9/\-]*)")
INV_DATE = re.compile(rf"(?i)invoice\s+date\s*[:\-]?\s*({DATE_PAT})")
ANY_DATE = re.compile(rf"(?i)(?<!due )(?<!po )(?<!order )\bdate\s*[:\-]?\s*({DATE_PAT})")
PO_NO = re.compile(r"(?i)\b(?:P\.?O\.?|Purchase\s+Order)\s*(?:(?:No\.?|Number|#)\s*[:\-]?|[:\-])\s*([A-Z0-9][A-Z0-9/\-]{2,})")
POS = re.compile(r"(?i)place\s+of\s+supply\s*[:\-]?\s*(.+)$")
TITLE_SKIP = re.compile(r"(?i)invoice|original|duplicate|triplicate|gstin|date|bill|page|e-?way|irn|ack")
STOP_TABLE = re.compile(r"(?i)^\s*(total|sub\s*-?\s*total|grand|amount\s+in\s+words|bank|terms|declaration|hsn\s*/?\s*sac\s+summary|tax\s+summary)")

TOTAL_LABELS: list[tuple[str, re.Pattern]] = [
    ("subtotal", re.compile(r"(?i)(total\s+)?taxable\s+(value|amount)|sub\s*-?\s*total")),
    ("total_cgst", re.compile(r"(?i)\bcgst\b")),
    ("total_sgst", re.compile(r"(?i)\b(sgst|utgst)\b")),
    ("total_igst", re.compile(r"(?i)\bigst\b")),
    ("round_off", re.compile(r"(?i)round\s*-?\s*off")),
    ("grand_total", re.compile(r"(?i)grand\s+total|total\s+invoice\s+value|invoice\s+total|net\s+(amount\s+)?payable|total\s+amount(\s+payable)?|amount\s+payable")),
]

COLUMN_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"(?i)hsn|sac"), "hsn_sac"),
    (re.compile(r"(?i)taxable"), "taxable_value"),
    (re.compile(r"(?i)cgst"), "cgst"),
    (re.compile(r"(?i)sgst|utgst"), "sgst"),
    (re.compile(r"(?i)igst"), "igst"),
    (re.compile(r"(?i)cess"), "cess"),
    (re.compile(r"(?i)(gst|tax)\s*(%|rate)|^%$|^rate\s*%"), "gst_rate"),
    (re.compile(r"(?i)disc"), "discount"),
    (re.compile(r"(?i)qty|quantity"), "quantity"),
    (re.compile(r"(?i)^unit$|uom"), "unit"),
    (re.compile(r"(?i)desc|particular|item|product|goods"), "description"),
    (re.compile(r"(?i)rate|price"), "unit_price"),
    (re.compile(r"(?i)total|amount|amt"), "line_total"),
    (re.compile(r"(?i)^(s\.?\s?no\.?|sr\.?(\s?no\.?)?|#)$"), "_serial"),
]
NUMERIC_COLS = {"quantity", "unit_price", "discount", "taxable_value", "gst_rate", "cgst", "sgst", "igst", "cess", "line_total"}


def _last_amount(text: str):
    ms = AMOUNT.findall(text)
    return parse_decimal(ms[-1]) if ms else None


def _is_header(line: Line) -> bool:
    t = line.text.lower()
    hit = sum(bool(re.search(p, t)) for p in (r"desc|item|particular|product|goods", r"hsn|sac", r"qty|quantity",
                                              r"rate|price", r"amount|taxable|value|total", r"cgst|sgst|igst|gst|tax"))
    return hit >= 3 and bool(re.search(r"hsn|sac|qty|quantity", t))


def _header_cells(line: Line) -> list[tuple[str, float, float, str]]:
    """Merge adjacent header words into cells -> [(text, x0, x1, canonical)]."""
    gap = 0.7 * line.height
    cells: list[list[OCRWord]] = []
    for w in line.words:
        if cells and w.bbox[0] - cells[-1][-1].bbox[2] < gap:
            cells[-1].append(w)
        else:
            cells.append([w])
    out = []
    for c in cells:
        text = " ".join(w.text for w in c)
        canon = next((name for pat, name in COLUMN_RULES if pat.search(text)), "_other")
        out.append((text, c[0].bbox[0], c[-1].bbox[2], canon))
    return out


def _parse_table(lines: list[Line], start: int) -> tuple[list[LineItem], int]:
    cells = _header_cells(lines[start])
    centers = [((x0 + x1) / 2, canon) for _, x0, x1, canon in cells]
    items: list[LineItem] = []
    raw: list[dict[str, list[OCRWord]]] = []
    i = start + 1
    while i < len(lines):
        ln = lines[i]
        if STOP_TABLE.match(ln.text):
            break
        if _is_header(ln):        # repeated header on a following page
            i += 1
            continue
        cols: dict[str, list[OCRWord]] = {}
        for w in ln.words:
            xc = (w.bbox[0] + w.bbox[2]) / 2
            canon = min(centers, key=lambda c: abs(c[0] - xc))[1]
            cols.setdefault(canon, []).append(w)
        n_num = sum(1 for c in cols if c in NUMERIC_COLS and parse_decimal(" ".join(w.text for w in cols[c])) is not None)
        if n_num >= 2:
            raw.append(cols)
        elif raw and "description" in cols and n_num == 0:      # wrapped description line
            raw[-1].setdefault("description", []).extend(cols["description"])
        i += 1
    for k, cols in enumerate(raw, start=1):
        txt = {c: " ".join(w.text for w in ws) for c, ws in cols.items()}
        allw = [w for ws in cols.values() for w in ws]
        li = LineItem(line_no=k, description=txt.get("description"), hsn_sac=re.sub(r"\D", "", txt.get("hsn_sac", "")) or None)
        for c in NUMERIC_COLS:
            if c in txt:
                setattr(li, c, parse_decimal(txt[c]))
        if "quantity" in txt:
            m = re.match(r"\s*[\d.,]+\s*([A-Za-z]+)", txt["quantity"])
            if m:
                li.unit = m.group(1).upper()
        if "unit" in txt:
            li.unit = txt["unit"].upper()
        li.confidence = round(0.85 * sum(w.conf for w in allw) / len(allw), 4)
        items.append(li)
    return items, i


def extract(pages: list[PageData]) -> InvoiceData:
    lines = words_to_lines(pages)
    inv = InvoiceData()
    fc = inv.field_confidence

    def setf(name: str, value, line: Line, base: float = 0.9) -> None:
        setattr(inv, name, value)
        fc[name] = round(base * line.conf, 4)

    section = "vendor"
    table_start = next((i for i, l in enumerate(lines) if _is_header(l)), None)
    header_zone = lines[:table_start] if table_start is not None else lines

    for ln in header_zone:
        t = ln.text
        if BUYER_MARK.search(t):
            section = "buyer"
        if m := GSTIN_ANY.search(t.upper().replace(" ", "")) or GSTIN_ANY.search(t.upper()):
            field = "buyer_gstin" if section == "buyer" else "vendor_gstin"
            if getattr(inv, field) is None:
                setf(field, m.group(1), ln)
        if inv.invoice_number is None and (m := INV_NO.search(t)):
            setf("invoice_number", m.group(1), ln)
        if inv.invoice_date is None and (m := INV_DATE.search(t) or ANY_DATE.search(t)):
            if d := parse_date(m.group(1)):
                setf("invoice_date", d, ln)
        if inv.po_number is None and (m := PO_NO.search(t)):
            setf("po_number", m.group(1), ln)
        if inv.place_of_supply is None and (m := POS.search(t)):
            if code := state_code_from_text(m.group(1)):
                setf("place_of_supply", code, ln)
        if section == "buyer" and inv.buyer_name is None:
            rest = BUYER_MARK.sub("", t, count=1).strip(" :-")
            if rest and not GSTIN_ANY.search(rest.upper()):
                setf("buyer_name", rest, ln, 0.6)

    first_page = [l for l in lines if l.page == pages[0].page][:8] if pages else []
    for ln in first_page:
        # Two-column headers put the vendor block and the invoice block on the same
        # visual line; judge the left-most column segment on its own.
        seg = _segments(ln)[0]
        if len(re.findall(r"[A-Za-z]", seg.text)) >= 3 and not TITLE_SKIP.search(seg.text) and not GSTIN_ANY.search(seg.text.upper()):
            setf("vendor_name", seg.text, seg, 0.7)
            break

    if table_start is not None:
        inv.items, end = _parse_table(lines, table_start)
        summary = lines[end:]
    else:
        summary = lines
    for attr, pat in TOTAL_LABELS:
        for ln in summary:                      # keep the LAST labelled line that carries an amount
            if pat.search(ln.text) and not re.search(r"(?i)in\s+words", ln.text):
                if (v := _last_amount(ln.text)) is not None:
                    setf(attr, v, ln)
    return inv


def _segments(line: Line, gap_factor: float = 3.0) -> list[Line]:
    """Split a visual line wherever the horizontal gap between words exceeds gap_factor x word height."""
    segs: list[list] = [[line.words[0]]]
    h = line.height or 1.0
    for prev, w in zip(line.words, line.words[1:]):
        if w.bbox[0] - prev.bbox[2] > gap_factor * h:
            segs.append([])
        segs[-1].append(w)
    return [Line(line.page, ws) for ws in segs]


class HeuristicExtractor:
    name = "heuristic"

    def extract(self, pages: list[PageData], images=None) -> InvoiceData:
        return extract(pages)
