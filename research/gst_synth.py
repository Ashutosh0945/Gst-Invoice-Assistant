"""GSTInvoice-Synth: a multi-layout synthetic Indian GST invoice generator with word-level labels.

Each *layout* (an integer id) fixes the structure: where the vendor/invoice/buyer blocks sit, which label
words are used ("Invoice No" vs "Bill No." vs "Inv #"), date and number formats, the order and names of
table columns, fonts, the totals block position and the distractor text (bank details, terms...).
Each *document* then fills that layout with random content. Every rendered word gets a BIO label from
backend/extraction/labels.py, and the exact ground truth is kept, so models can be trained and scored
without any human labelling. Unseen-layout generalisation is tested by holding layout ids out.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

import pymupdf

STATES = {"27": "Maharashtra", "29": "Karnataka", "07": "Delhi", "33": "Tamil Nadu", "24": "Gujarat", "09": "Uttar Pradesh",
          "19": "West Bengal", "36": "Telangana", "06": "Haryana", "08": "Rajasthan"}
VENDORS = ["Sunrise Traders Pvt Ltd", "Apex Electronics", "Kaveri IT Solutions LLP", "Om Sai Enterprises", "Nexa Stationers",
           "Shree Ganesh Hardware", "Bharat Steel Corporation", "Green Leaf Agro Pvt Ltd", "Metro Office Supplies", "Royal Textiles",
           "Vardhman Packaging", "Patel Brothers & Co", "Coastal Logistics", "Lakshmi Pharma Distributors", "Indus Cables Ltd"]
BUYERS = ["Demo Buyer Pvt Ltd", "Konkan Health Services", "Vidyalankar Tech Labs", "Shiv Shakti Builders", "Northstar Retail LLP"]
ITEMS = [("A4 Copier Paper Ream", "4802", "NOS", 260, 18), ("Wireless Keyboard", "8471", "NOS", 1200, 18), ("LED Monitor 24 inch", "8528", "NOS", 9500, 18),
         ("Office Chair", "9403", "NOS", 6200, 18), ("Copper Cable 2.5mm", "8544", "MTR", 38, 18), ("Portland Cement Bag", "2523", "BAG", 380, 28),
         ("Steel Frame Structure", "7308", "KGS", 74, 18), ("Software Consulting", "998313", "HRS", 1800, 18), ("Packaged Namkeen 1kg", "2106", "PKT", 240, 5),
         ("Cotton T-Shirt", "6109", "PCS", 450, 5), ("Hand Sanitizer 500ml", "3808", "BTL", 120, 18), ("Printer Toner Cartridge", "8443", "NOS", 2400, 18),
         ("Notebook 200 pages", "4820", "NOS", 60, 12), ("Ceiling Fan", "8414", "NOS", 2100, 18), ("Annual Maintenance Contract", "998719", "NOS", 15000, 18)]

LABEL_WORDS = {
    "INVOICE_NO": ["Invoice No:", "Invoice No.", "Bill No:", "Inv #", "Invoice Number:", "Tax Invoice No:", "Bill #"],
    "INVOICE_DATE": ["Date:", "Invoice Date:", "Dated:", "Bill Date:", "Inv. Date:"],
    "VENDOR_GSTIN": ["GSTIN:", "GSTIN/UIN:", "GST No:", "Our GSTIN:", "GSTIN No."],
    "BUYER_GSTIN": ["GSTIN:", "Buyer GSTIN:", "GSTIN/UIN:", "Customer GSTIN:", "Party GSTIN:"],
    "PLACE_OF_SUPPLY": ["Place of Supply:", "POS:", "State:", "Supply State:"],
    "PO_NO": ["PO No:", "P.O. No.", "Order No:", "Your PO:"],
    "SUBTOTAL": ["Taxable Value", "Sub Total", "Total Taxable Value", "Taxable Amount", "Amount before Tax"],
    "TOTAL_CGST": ["CGST", "Central Tax", "Add: CGST", "CGST Amount"],
    "TOTAL_SGST": ["SGST", "State Tax", "Add: SGST", "SGST Amount"],
    "TOTAL_IGST": ["IGST", "Integrated Tax", "Add: IGST", "IGST Amount"],
    "ROUND_OFF": ["Round Off", "Rounding", "R/O"],
    "GRAND_TOTAL": ["Grand Total", "Total Amount", "Invoice Total", "Net Payable", "Total Invoice Value", "Amount Payable"],
}
BUYER_TITLES = ["Bill To:", "Billed To:", "Buyer:", "Customer:", "Consignee:", "Details of Receiver:"]
TITLES = ["TAX INVOICE", "Tax Invoice", "INVOICE", "GST INVOICE", "TAX INVOICE (ORIGINAL)"]
COLS = {"ITEM_DESC": ["Description", "Item", "Particulars", "Product", "Description of Goods"],
        "ITEM_HSN": ["HSN/SAC", "HSN", "HSN Code", "SAC/HSN"], "ITEM_QTY": ["Qty", "Quantity", "Qty."],
        "ITEM_UNIT": ["Unit", "UOM", "Per"], "ITEM_PRICE": ["Rate", "Price", "Unit Price", "Rate/Unit"],
        "ITEM_TAXABLE": ["Taxable Value", "Amount", "Taxable Amt", "Value"], "ITEM_GSTRATE": ["GST %", "Tax %", "GST Rate", "Rate %"],
        "ITEM_CGST": ["CGST", "CGST Amt"], "ITEM_SGST": ["SGST", "SGST Amt"], "ITEM_IGST": ["IGST", "IGST Amt"],
        "ITEM_TOTAL": ["Total", "Amount", "Line Total", "Net Amount"]}
DISTRACTORS = ["Bank: HDFC Bank, A/c No. 50200012345678, IFSC HDFC0000123", "Terms: Payment due within 30 days.",
               "Subject to Mumbai jurisdiction.", "E. & O.E.", "Thank you for your business!", "PAN: AAACX1234A",
               "Declaration: We declare that this invoice shows the actual price of the goods described.",
               "Authorised Signatory", "Phone: +91 98200 12345  Email: accounts@example.in", "Goods once sold will not be taken back."]
Q = Decimal("0.01")


def q2(x) -> Decimal:
    return Decimal(str(x)).quantize(Q, rounding=ROUND_HALF_UP)


def gstin(rng: random.Random, state: str) -> str:
    from backend.validation.gst import gstin_checksum
    letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    body = state + "".join(rng.choice(letters) for _ in range(5)) + "".join(rng.choice("0123456789") for _ in range(4)) + \
        rng.choice(letters) + rng.choice("123456789") + "Z"
    return body + gstin_checksum(body)


@dataclass
class Layout:
    lid: int
    landscape: bool
    font: str
    header_style: str          # "split" (vendor left, invoice right) | "stacked" (vendor top, invoice below) | "right_vendor"
    labels: dict
    buyer_title: str
    title: str
    date_fmt: str
    num_fmt: str               # "indian" | "plain" | "western"
    currency: str              # "" | "Rs. " | "INR "
    cols: list[str]
    col_names: dict
    totals_side: str           # "right" | "left"
    distractors: list[str]
    fs: float
    show_po: bool
    label_sep_newline: bool    # label on one line and value below (instead of "Label: value")
    inline_pairs: bool = False # v2: two fields on one line ("Invoice No: X    Date: Y")
    colon_totals: bool = False # v2: totals written "Grand Total: 12,345.00" left-aligned


V2_LABELS = {"VENDOR_GSTIN": ["Vendor GSTIN:", "Supplier GSTIN:", "Seller GSTIN:"], "BUYER_GSTIN": ["Buyer GSTIN:", "Recipient GSTIN:"],
             "SUBTOTAL": ["Taxable Value:", "Sub Total:", "Taxable Amount:"], "TOTAL_CGST": ["CGST:"], "TOTAL_SGST": ["SGST:"], "TOTAL_IGST": ["IGST:"],
             "ROUND_OFF": ["Round Off:"], "GRAND_TOTAL": ["Grand Total:", "Total:", "Invoice Total:"], "INVOICE_DATE": ["Date:", "Dated:"]}


def make_layout(lid: int) -> Layout:
    if lid >= 24:
        L = make_layout(lid - 24)                # same base structure, then v2 variations on top
        r = random.Random(20_000 + lid)
        L.lid = lid
        L.inline_pairs, L.colon_totals = r.random() < 0.7, r.random() < 0.7
        L.header_style = "stacked" if L.inline_pairs else L.header_style
        L.label_sep_newline = False
        for k, opts in V2_LABELS.items():
            if r.random() < 0.7:
                L.labels[k] = r.choice(opts)
        L.date_fmt = r.choice([L.date_fmt, "%Y-%m-%d"])
        L.num_fmt = r.choice([L.num_fmt, "plain"])
        return L
    r = random.Random(10_000 + lid)
    cols = ["ITEM_DESC", "ITEM_HSN", "ITEM_QTY"] + (["ITEM_UNIT"] if r.random() < 0.6 else []) + ["ITEM_PRICE", "ITEM_TAXABLE", "ITEM_GSTRATE"]
    tax_cols = r.choice([["ITEM_CGST", "ITEM_SGST", "ITEM_IGST"], [], ["ITEM_CGST", "ITEM_SGST"]])
    cols += tax_cols + ["ITEM_TOTAL"]
    if r.random() < 0.3:      # swap HSN and Qty order in some layouts
        i, j = cols.index("ITEM_HSN"), cols.index("ITEM_QTY")
        cols[i], cols[j] = cols[j], cols[i]
    return Layout(
        lid=lid, landscape=r.random() < 0.5, font=r.choice(["helv", "tiro", "cour", "helv"]),
        header_style=r.choice(["split", "stacked", "right_vendor"]),
        labels={k: r.choice(v) for k, v in LABEL_WORDS.items()}, buyer_title=r.choice(BUYER_TITLES), title=r.choice(TITLES),
        date_fmt=r.choice(["%d/%m/%Y", "%d-%m-%Y", "%d-%b-%Y", "%Y-%m-%d", "%d.%m.%Y"]),
        num_fmt=r.choice(["indian", "plain", "western"]), currency=r.choice(["", "Rs. ", "INR ", ""]),
        cols=cols, col_names={c: r.choice(COLS[c]) for c in cols}, totals_side=r.choice(["right", "left", "right"]),
        distractors=r.sample(DISTRACTORS, r.randint(1, 4)), fs=r.choice([8.0, 8.5, 9.0, 9.5]),
        show_po=r.random() < 0.5, label_sep_newline=r.random() < 0.25)


def fmt_num(x: Decimal, style: str) -> str:
    s = f"{x:.2f}"
    if style == "plain":
        return s
    whole, frac = s.split(".")
    neg = whole.startswith("-")
    whole = whole.lstrip("-")
    if style == "western":
        body = f"{int(whole):,}"
    else:
        head, tail = whole[:-3], whole[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        body = ",".join(parts + [tail]) if parts else tail
    return ("-" if neg else "") + body + "." + frac


@dataclass
class Doc:
    pdf: bytes
    words: list[tuple[str, tuple[float, float, float, float]]]
    labels: list[str]
    truth: dict
    layout: int
    width: float
    height: float
    spans: list = field(default_factory=list)


def generate(lid: int, seed: int) -> Doc:
    L = make_layout(lid)
    rng = random.Random(seed * 7919 + lid)
    W, H = (842, 595) if L.landscape else (595, 842)
    doc = pymupdf.open()
    page = doc.new_page(width=W, height=H)
    spans: list[tuple[str, tuple[float, float, float, float]]] = []   # (entity, rect) for labelled text

    def put(x, y, text, label=None, fs=None, bold=False, right=False):
        fs = fs or L.fs
        font = {"helv": "hebo", "tiro": "tibo", "cour": "cobo"}[L.font] if bold else L.font
        w = pymupdf.get_text_length(text, fontname=font, fontsize=fs)
        if right:
            x -= w
        page.insert_text((x, y), text, fontsize=fs, fontname=font)
        if label:
            spans.append((label, (x - 0.5, y - fs, x + w + 0.5, y + fs * 0.3)))
        return x + w

    def field_(x, y, ent, value, right=False):
        lab = L.labels[ent]
        if L.label_sep_newline:
            put(x, y, lab, right=right, fs=L.fs - 0.5)
            put(x, y + L.fs + 3, value, ent, right=right)
            return y + 2 * (L.fs + 3)
        if right:
            put(x, y, value, ent, right=True)
            vx = x - pymupdf.get_text_length(value, fontname=L.font, fontsize=L.fs) - 4
            put(vx, y, lab, right=True)
        else:
            end = put(x, y, lab + " ")
            put(end, y, value, ent)
        return y + L.fs + 5

    vstate = rng.choice(list(STATES))
    intra = rng.random() < 0.55
    bstate = vstate if intra else rng.choice([s for s in STATES if s != vstate])
    vname, bname = rng.choice(VENDORS), rng.choice(BUYERS)
    vg, bg = gstin(rng, vstate), gstin(rng, bstate)
    inv_no = rng.choice(["INV", "BILL", "SI", "TI", vname[:3].upper()]) + rng.choice(["/", "-", ""]) + \
        rng.choice(["2026/", "25-26/", "", "26-"]) + str(rng.randint(1, 9999)).zfill(rng.choice([3, 4]))
    d = date(2026, 1, 1) + timedelta(days=rng.randint(0, 270))
    po = f"PO-{rng.randint(1000, 9999)}" if L.show_po and rng.random() < 0.7 else None
    items = []
    for desc, hsn, unit, price, rate in rng.sample(ITEMS, rng.randint(1, 6)):
        qty = Decimal(rng.choice([1, 2, 3, 4, 5, 6, 8, 10, 12, 15, 20, 25, 50]))
        unit_price = q2(Decimal(price) * Decimal(str(rng.uniform(0.85, 1.15))))
        taxable = q2(qty * unit_price)
        tax = q2(taxable * Decimal(rate) / 100)
        c = s = q2(tax / 2) if intra else Decimal(0)
        i = Decimal(0) if intra else tax
        items.append(dict(description=desc, hsn_sac=hsn, unit=unit, quantity=qty, unit_price=unit_price, taxable_value=taxable,
                          gst_rate=Decimal(rate), cgst=c, sgst=s, igst=i, line_total=taxable + c + s + i))
    sub = sum(x["taxable_value"] for x in items)
    cg, sg, ig = sum(x["cgst"] for x in items), sum(x["sgst"] for x in items), sum(x["igst"] for x in items)
    raw = sub + cg + sg + ig
    grand = raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    ro = grand - raw
    num = lambda v: L.currency + fmt_num(q2(v), L.num_fmt)  # noqa: E731
    nnum = lambda v: fmt_num(q2(v), L.num_fmt)             # noqa: E731 (table cells: no currency)
    m = 36
    # ---------------- header blocks
    if L.header_style == "stacked":
        put(W / 2 - 40, 40, L.title, fs=L.fs + 4, bold=True)
        y = 62
        put(m, y, vname, "VENDOR_NAME", fs=L.fs + 2, bold=True); y += L.fs + 6
        y = field_(m, y, "VENDOR_GSTIN", vg)
        put(m, y, f"{rng.randint(1, 99)}, {rng.choice(['MG Road', 'Station Road', 'MIDC Industrial Area', 'Ring Road'])}, {STATES[vstate]}"); y += L.fs + 8
        if L.inline_pairs:
            end = put(m, y, L.labels["INVOICE_NO"] + " ")
            end = put(end, y, inv_no, "INVOICE_NO")
            end = put(end + 30, y, L.labels["INVOICE_DATE"] + " ")
            put(end, y, d.strftime(L.date_fmt), "INVOICE_DATE")
            y += L.fs + 5
        else:
            y = field_(m, y, "INVOICE_NO", inv_no)
            y = field_(m, y, "INVOICE_DATE", d.strftime(L.date_fmt))
        if po:
            y = field_(m, y, "PO_NO", po)
        y = field_(m, y, "PLACE_OF_SUPPLY", f"{bstate}-{STATES[bstate]}")
        put(W / 2 + 20, 62 + 2 * (L.fs + 6), L.buyer_title, bold=True)
        put(W / 2 + 20, 62 + 3 * (L.fs + 6), bname)
        field_(W / 2 + 20, 62 + 4 * (L.fs + 6), "BUYER_GSTIN", bg)
        y += 10
    else:
        vx, ix = (m, W - m) if L.header_style == "split" else (W - m, m)
        right_v = L.header_style == "right_vendor"
        put(vx, 40, vname, "VENDOR_NAME", fs=L.fs + 2, bold=True, right=right_v)
        yv = field_(vx, 40 + L.fs + 8, "VENDOR_GSTIN", vg, right=right_v)
        put(vx, yv, f"{rng.randint(1, 99)}, {rng.choice(['MG Road', 'Station Road', 'MIDC Area', 'Ring Road'])}, {STATES[vstate]}", right=right_v)
        yi = 40
        yi = field_(ix, yi, "INVOICE_NO", inv_no, right=not right_v)
        yi = field_(ix, yi, "INVOICE_DATE", d.strftime(L.date_fmt), right=not right_v)
        if po:
            yi = field_(ix, yi, "PO_NO", po, right=not right_v)
        yi = field_(ix, yi, "PLACE_OF_SUPPLY", f"{bstate}-{STATES[bstate]}", right=not right_v)
        put(W / 2 - 40, max(yv, yi) + 16, L.title, fs=L.fs + 4, bold=True)
        y = max(yv, yi) + 38
        put(m, y, L.buyer_title, bold=True); y += L.fs + 4
        put(m, y, bname); y += L.fs + 4
        y = field_(m, y, "BUYER_GSTIN", bg) + 12
    # ---------------- table
    usable = W - 2 * m
    widths = {"ITEM_DESC": 3.2, "ITEM_HSN": 1.0, "ITEM_QTY": 0.7, "ITEM_UNIT": 0.7, "ITEM_PRICE": 1.1, "ITEM_TAXABLE": 1.3,
              "ITEM_GSTRATE": 0.8, "ITEM_CGST": 1.0, "ITEM_SGST": 1.0, "ITEM_IGST": 1.0, "ITEM_TOTAL": 1.3}
    tot_w = sum(widths[c] for c in L.cols)
    xs, x = {}, m + 18
    for c in L.cols:
        xs[c] = x
        x += (usable - 18) * widths[c] / tot_w
    put(m, y, "#", bold=True)
    for c in L.cols:
        put(xs[c], y, L.col_names[c], bold=True, fs=L.fs - 0.5)
    page.draw_line((m, y + 4), (W - m, y + 4), width=0.4)
    y += L.fs + 8
    for n, it in enumerate(items, 1):
        put(m, y, str(n))
        vals = {"ITEM_DESC": it["description"], "ITEM_HSN": it["hsn_sac"], "ITEM_QTY": f"{it['quantity']:g}", "ITEM_UNIT": it["unit"],
                "ITEM_PRICE": nnum(it["unit_price"]), "ITEM_TAXABLE": nnum(it["taxable_value"]), "ITEM_GSTRATE": f"{it['gst_rate']:g}%",
                "ITEM_CGST": nnum(it["cgst"]) if it["cgst"] else "-", "ITEM_SGST": nnum(it["sgst"]) if it["sgst"] else "-",
                "ITEM_IGST": nnum(it["igst"]) if it["igst"] else "-", "ITEM_TOTAL": nnum(it["line_total"])}
        for c in L.cols:
            v = vals[c]
            put(xs[c], y, v, None if v == "-" else c, fs=L.fs - 0.5)
        y += L.fs + 7
    page.draw_line((m, y - 4), (W - m, y - 4), width=0.4)
    # ---------------- totals
    tx_l, tx_v = (W - 230, W - m) if L.totals_side == "right" else (m, m + 200)
    rows = [("SUBTOTAL", sub)] + ([("TOTAL_CGST", cg), ("TOTAL_SGST", sg)] if intra else [("TOTAL_IGST", ig)])
    if ro:
        rows.append(("ROUND_OFF", ro))
    rows.append(("GRAND_TOTAL", grand))
    y += 8
    for ent, val in rows:
        if L.colon_totals:
            end = put(tx_l, y, L.labels[ent] + " ", bold=ent == "GRAND_TOTAL")
            put(end, y, nnum(val), ent, bold=ent == "GRAND_TOTAL")
        else:
            put(tx_l, y, L.labels[ent], bold=ent == "GRAND_TOTAL")
            put(tx_v, y, num(val), ent, bold=ent == "GRAND_TOTAL", right=True)
        y += L.fs + 6
    # ---------------- distractors
    dy = max(y + 20, H - 30 - 14 * len(L.distractors))
    for t in L.distractors:
        put(m if L.totals_side == "right" else W / 2, dy, t, fs=L.fs - 1)
        dy += 14
    pdf = doc.tobytes()
    words = [(w[4], (w[0], w[1], w[2], w[3])) for w in page.get_text("words")]
    labels = label_words(words, spans)
    doc.close()
    truth = dict(vendor_name=vname, vendor_gstin=vg, buyer_gstin=bg, invoice_number=inv_no, invoice_date=d, po_number=po,
                 place_of_supply=bstate, subtotal=q2(sub), total_cgst=q2(cg), total_sgst=q2(sg), total_igst=q2(ig), round_off=q2(ro),
                 grand_total=q2(grand), items=items)
    return Doc(pdf=pdf, words=words, labels=labels, truth=truth, layout=lid, width=W, height=H, spans=spans)


def label_words(words, spans) -> list[str]:
    labels = []
    last_span = {}
    for i, (_, (x0, y0, x1, y1)) in enumerate(words):
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        lab = "O"
        for si, (ent, (a, b, c, d)) in enumerate(spans):
            if a <= cx <= c and b <= cy <= d:
                lab = ("I-" if last_span.get("idx") == si else "B-") + ent
                last_span = {"idx": si}
                break
        else:
            last_span = {}
        labels.append(lab)
    return labels
