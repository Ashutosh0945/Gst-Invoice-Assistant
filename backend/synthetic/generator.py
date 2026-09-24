"""Synthetic Indian GST invoice generator with exact ground truth and controllable error injection.

Produces digital PDFs (A4 landscape) via PyMuPDF plus:
  * `truth`   - the values printed on the page (what an extractor should return),
  * `injected_errors` - which compliance errors were deliberately planted (what the rule engine should flag),
  * `cells`   - labelled boxes, used to auto-label words for LayoutLMv3 training (see scripts/generate_dataset.py).
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import pymupdf

from backend.validation.gst import STATE_CODES, gstin_checksum

ERROR_KINDS = ("bad_gstin", "bad_total", "bad_tax", "wrong_igst", "bad_rate")
FS = 8.0
COLS = [("#", 30), ("Description", 55), ("HSN/SAC", 250), ("Qty", 310), ("Unit", 350), ("Rate", 390),
        ("Taxable Value", 450), ("GST %", 535), ("CGST", 585), ("SGST", 635), ("IGST", 685), ("Total", 738)]
COLX = dict(COLS)
CATALOG = [("Dell Inspiron Laptop", "8471", "NOS", 42000, 18), ("A4 Copier Paper Ream", "4802", "NOS", 260, 18),
           ("Wireless Keyboard", "8471", "NOS", 1200, 18), ("LED Monitor 24 inch", "8528", "NOS", 9500, 18),
           ("Laser Printer", "8443", "NOS", 15500, 18), ("Office Chair", "9403", "NOS", 6200, 18),
           ("Copper Cable 2.5mm", "8544", "MTR", 38, 18), ("Software Consulting", "998313", "HRS", 1800, 18),
           ("Website Development", "998314", "NOS", 55000, 18), ("Steel Frame Structure", "7308", "KGS", 74, 18),
           ("Notebook Register", "4820", "NOS", 90, 5), ("Portland Cement Bag", "2523", "BAG", 380, 18)]
NAMES = ["Sunrise Traders Pvt Ltd", "Apex Electronics", "Bharat Office Supplies", "Kaveri IT Solutions LLP",
         "Vasai Industrial Works", "Om Sai Enterprises", "Nexa Stationers", "Tirumala Steel Corp"]
BUYERS = ["Vidyalankar Tech Labs Pvt Ltd", "Mumbai Innovation Hub", "Konkan Health Services"]


def q2(x: Decimal) -> Decimal:
    return x.quantize(Decimal("0.01"), ROUND_HALF_UP)


def make_gstin(rng: random.Random, state: str) -> str:
    pan = "".join(rng.choice("ABCDEFGHJKLMNPRSTUVWXY") for _ in range(3)) + rng.choice("PFCHT") \
          + rng.choice("ABCDEFGHJKLMNPRSTUVWXY") + f"{rng.randint(0, 9999):04d}" + rng.choice("ABCDEFGHJKLMNPRSTUVWXY")
    first14 = f"{state}{pan}{rng.choice('123456789')}Z"
    return first14 + gstin_checksum(first14)


@dataclass
class SyntheticInvoice:
    pdf_path: Path
    truth: dict
    injected_errors: list[str]
    cells: list[dict] = field(default_factory=list)   # {text, bbox(points), etype|None}


class _Page:
    def __init__(self) -> None:
        self.doc = pymupdf.open()
        self.page = self.doc.new_page(width=842, height=595)
        self.cells: list[dict] = []

    def put(self, x: float, y: float, text: str, etype: str | None = None, bold: bool = False) -> float:
        font = "hebo" if bold else "helv"
        self.page.insert_text((x, y), text, fontsize=FS, fontname=font)
        w = pymupdf.get_text_length(text, fontname=font, fontsize=FS)
        self.cells.append({"text": text, "bbox": (x, y - 0.95 * FS, x + w, y + 0.25 * FS), "etype": etype})
        return x + w


def generate(path: Path, seed: int, *, intra: bool | None = None, errors: tuple[str, ...] = (),
             po_number: str | None = None, po_items: list[tuple] | None = None, vendor_state: str | None = None,
             invoice_date: date | None = None, invoice_number: str | None = None,
             vendor_gstin: str | None = None, vendor_name: str | None = None,
             buyer_name: str | None = None, printed_total_delta: Decimal | None = None) -> SyntheticInvoice:
    rng = random.Random(seed)
    buyer_state = "27"
    vs = vendor_state or (buyer_state if (intra is None or intra) else rng.choice([c for c in STATE_CODES if c not in ("27", "97", "99", "26")]))
    intra_state = vs == buyer_state
    vendor_gstin = vendor_gstin or make_gstin(rng, vs)
    buyer_gstin = make_gstin(random.Random(9999), buyer_state)
    inv_no = invoice_number or f"INV/{rng.randint(2026, 2026)}/{rng.randint(1, 9999):04d}"
    inv_date = invoice_date or (date(2026, 1, 1) + timedelta(days=rng.randint(0, 240)))
    vname, bname = rng.choice(NAMES), rng.choice(BUYERS)
    vname, bname = vendor_name or vname, buyer_name or bname

    lines = po_items or []
    if not lines:
        picks = rng.sample(CATALOG, rng.randint(1, 5))
        lines = [(d, h, u, Decimal(p), r, rng.randint(1, 12)) for d, h, u, p, r in picks]
    items = []
    for n, (desc, hsn, unit, price, rate, qty) in enumerate(lines, start=1):
        price = Decimal(price)
        taxable = q2(Decimal(qty) * price)
        rate = Decimal(rate)
        if "bad_rate" in errors and n == 1:
            rate = Decimal("7")
        half = q2(taxable * rate / 200)
        it = dict(line_no=n, description=desc, hsn_sac=hsn, quantity=Decimal(qty), unit=unit, unit_price=price,
                  taxable_value=taxable, gst_rate=rate, cgst=None, sgst=None, igst=None)
        if intra_state and "wrong_igst" not in errors:
            it["cgst"], it["sgst"] = half, half
        else:
            it["igst"] = q2(taxable * rate / 100)
        if "bad_tax" in errors and n == 1 and it["cgst"] is not None:
            it["cgst"] += Decimal("10.00")
        it["line_total"] = q2(taxable + sum((it[k] or Decimal(0)) for k in ("cgst", "sgst", "igst")))
        items.append(it)

    def tot(k: str) -> Decimal | None:
        vals = [i[k] for i in items if i[k] is not None]
        return q2(sum(vals, Decimal(0))) if vals else None

    subtotal, tc, ts, ti = tot("taxable_value"), tot("cgst"), tot("sgst"), tot("igst")
    raw = subtotal + (tc or 0) + (ts or 0) + (ti or 0)
    if "bad_tax" in errors and tc is not None:
        raw = subtotal + (tc - Decimal("10.00")) + (ts or 0) + (ti or 0)   # totals stay honest -> line/total mismatch
    round_off = q2(raw.to_integral_value(ROUND_HALF_UP) - raw)
    grand = q2(raw + round_off)
    if "bad_total" in errors:
        grand += Decimal("100.00")
    if printed_total_delta:  # demo of a tampered printout: only the printed grand total changes
        grand += printed_total_delta
    shown_gstin = vendor_gstin[:-1] + ("A" if vendor_gstin[-1] != "A" else "B") if "bad_gstin" in errors else vendor_gstin

    pg = _Page()
    pg.put(40, 45, vname, "VENDOR_NAME", bold=True)
    x = pg.put(40, 58, "GSTIN: ")
    pg.put(x, 58, shown_gstin, "VENDOR_GSTIN")
    pg.put(40, 71, "Plot 12, MIDC Industrial Area")
    pg.put(360, 95, "TAX INVOICE", bold=True)
    x = pg.put(560, 45, "Invoice No: ")
    pg.put(x, 45, inv_no, "INVOICE_NO")
    x = pg.put(560, 58, "Invoice Date: ")
    pg.put(x, 58, inv_date.strftime("%d/%m/%Y"), "INVOICE_DATE")
    ypos = 71
    if po_number:
        x = pg.put(560, ypos, "PO No: ")
        pg.put(x, ypos, po_number, "PO_NO")
        ypos += 13
    x = pg.put(560, ypos, "Place of Supply: ")
    pg.put(x, ypos, f"{buyer_state}-Maharashtra", "PLACE_OF_SUPPLY")
    pg.put(40, 120, "Bill To:", bold=True)
    pg.put(40, 133, bname)
    x = pg.put(40, 146, "GSTIN: ")
    pg.put(x, 146, buyer_gstin, "BUYER_GSTIN")

    y = 190
    for name, cx in COLS:
        pg.put(cx, y, name, None, bold=True)
    items_attr = [("line_no", "#", None), ("description", "Description", "ITEM_DESC"), ("hsn_sac", "HSN/SAC", "ITEM_HSN"),
                  ("quantity", "Qty", "ITEM_QTY"), ("unit", "Unit", "ITEM_UNIT"), ("unit_price", "Rate", "ITEM_PRICE"),
                  ("taxable_value", "Taxable Value", "ITEM_TAXABLE"), ("gst_rate", "GST %", "ITEM_GSTRATE"),
                  ("cgst", "CGST", "ITEM_CGST"), ("sgst", "SGST", "ITEM_SGST"), ("igst", "IGST", "ITEM_IGST"),
                  ("line_total", "Total", "ITEM_TOTAL")]
    for it in items:
        y += 16
        for attr, col, etype in items_attr:
            v = it[attr]
            if v is None:
                continue
            txt = f"{v:,.2f}" if isinstance(v, Decimal) and attr not in ("quantity", "gst_rate") else (f"{v:g}" if isinstance(v, Decimal) else str(v))
            pg.put(COLX[col], y, txt, etype)
    y += 24
    for label, val, etype in (("Total Taxable Value:", subtotal, "SUBTOTAL"), ("CGST:", tc, "TOTAL_CGST"),
                              ("SGST:", ts, "TOTAL_SGST"), ("IGST:", ti, "TOTAL_IGST"),
                              ("Round Off:", round_off, "ROUND_OFF"), ("Grand Total:", grand, "GRAND_TOTAL")):
        if val is None:
            continue
        x = pg.put(600, y, label, None, bold=(etype == "GRAND_TOTAL"))
        pg.put(x + 6, y, f"{val:,.2f}", etype, bold=(etype == "GRAND_TOTAL"))
        y += 14
    pg.put(40, 540, "Declaration: We declare that this invoice shows the actual price of the goods described.")
    path.parent.mkdir(parents=True, exist_ok=True)
    pg.doc.save(str(path))
    pg.doc.close()

    truth = dict(vendor_name=vname, vendor_gstin=shown_gstin, buyer_name=bname, buyer_gstin=buyer_gstin,
                 invoice_number=inv_no, invoice_date=inv_date.isoformat(), po_number=po_number,
                 place_of_supply=buyer_state, subtotal=subtotal, total_cgst=tc, total_sgst=ts, total_igst=ti,
                 round_off=round_off, grand_total=grand, items=items)
    return SyntheticInvoice(path, truth, list(errors), pg.cells)


def label_words(words_px: list[tuple[str, tuple[float, float, float, float]]], cells: list[dict], scale: float) -> list[str]:
    """BIO-label extracted words by locating them inside labelled cell boxes (points -> pixels via `scale`)."""
    labels = ["O"] * len(words_px)
    for cell in cells:
        if not cell["etype"]:
            continue
        x0, y0, x1, y1 = (v * scale for v in cell["bbox"])
        first = True
        for i, (_, (a, b, c, d)) in enumerate(words_px):
            cx, cy = (a + c) / 2, (b + d) / 2
            if x0 - 1 <= cx <= x1 + 1 and y0 - 1 <= cy <= y1 + 1 and labels[i] == "O":
                labels[i] = ("B-" if first else "I-") + cell["etype"]
                first = False
    return labels
