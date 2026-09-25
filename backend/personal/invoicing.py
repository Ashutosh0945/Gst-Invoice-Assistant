"""Create GST-correct invoices for the user's own customers, and render them as PDF."""
from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from backend.personal.money import inr
from backend.validation.gst import STATE_CODES

Q = Decimal("0.01")


def q2(x) -> Decimal:
    return Decimal(str(x)).quantize(Q, rounding=ROUND_HALF_UP)


def compute_invoice(items: list[dict], seller_state: str | None, place_of_supply: str | None,
                    gst_registered: bool) -> dict:
    """items: [{description, hsn_sac, quantity, rate, gst_rate}] -> computed lines + totals.
    Intra-state -> CGST+SGST split; inter-state -> IGST; unregistered sellers charge no GST."""
    intra = not seller_state or not place_of_supply or seller_state == place_of_supply
    lines, sub, cg, sg, ig = [], Decimal(0), Decimal(0), Decimal(0), Decimal(0)
    for n, it in enumerate(items, start=1):
        qty = Decimal(str(it.get("quantity") or 1))
        rate = Decimal(str(it.get("rate") or 0))
        gst_rate = Decimal(str(it.get("gst_rate") or 0)) if gst_registered else Decimal(0)
        taxable = q2(qty * rate)
        tax = q2(taxable * gst_rate / 100)
        c = s = i = Decimal(0)
        if intra:
            c = q2(tax / 2)
            s = tax - c
        else:
            i = tax
        lines.append({"line_no": n, "description": (it.get("description") or "").strip() or "Item",
                      "hsn_sac": (it.get("hsn_sac") or "").strip() or None, "quantity": str(qty), "rate": str(q2(rate)),
                      "gst_rate": str(gst_rate), "taxable": str(taxable), "cgst": str(c), "sgst": str(s),
                      "igst": str(i), "total": str(taxable + tax)})
        sub += taxable
        cg += c
        sg += s
        ig += i
    return {"items": lines, "subtotal": q2(sub), "cgst": q2(cg), "sgst": q2(sg), "igst": q2(ig),
            "total": q2(sub + cg + sg + ig), "supply": "intra" if intra else "inter"}


def render_pdf(inv, seller) -> bytes:
    """A clean one-page A4 invoice (PyMuPDF)."""
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    ink, soft = (0.1, 0.1, 0.15), (0.45, 0.45, 0.5)

    def t(x, y, s, size=9.5, bold=False, color=ink, right=False):
        font = "hebo" if bold else "helv"
        if right:
            x -= pymupdf.get_text_length(str(s), fontname=font, fontsize=size)
        page.insert_text((x, y), str(s), fontsize=size, fontname=font, color=color)

    registered = bool(seller.gstin)
    t(40, 56, "TAX INVOICE" if registered else "INVOICE", 18, True)
    t(555, 50, f"No. {inv.number}", 10, True, right=True)
    t(555, 64, f"Date {inv.issue_date:%d %b %Y}", 9, color=soft, right=True)
    if inv.due_date:
        t(555, 77, f"Due {inv.due_date:%d %b %Y}", 9, color=soft, right=True)
    t(40, 100, "From", 8, color=soft)
    t(40, 114, seller.business_name or seller.name, 11, True)
    if seller.gstin:
        t(40, 128, f"GSTIN {seller.gstin}", 9)
    t(40, 142, seller.email, 9, color=soft)
    t(320, 100, "Bill to", 8, color=soft)
    t(320, 114, inv.client_name, 11, True)
    y = 128
    if inv.client_gstin:
        t(320, y, f"GSTIN {inv.client_gstin}", 9)
        y += 14
    if inv.place_of_supply:
        t(320, y, f"Place of supply: {inv.place_of_supply}-{STATE_CODES.get(inv.place_of_supply, '')}", 9, color=soft)

    y = 190
    page.draw_line((40, y - 12), (555, y - 12), color=(0.85, 0.85, 0.88))
    cols = [(40, "#"), (60, "Description"), (270, "HSN/SAC"), (330, "Qty"), (400, "Rate"), (470, "GST"), (555, "Amount")]
    for x, h in cols:
        t(x, y, h, 8, True, soft, right=x in (400, 470, 555))
    y += 18
    for li in inv.items:
        t(40, y, li["line_no"], 9, color=soft)
        t(60, y, li["description"][:38], 9)
        t(270, y, li["hsn_sac"] or "—", 9, color=soft)
        t(330, y, f"{Decimal(li['quantity']):g}", 9)
        t(400, y, inr(li["rate"], True), 9, right=True)
        t(470, y, f"{Decimal(li['gst_rate']):g}%", 9, right=True)
        t(555, y, inr(li["taxable"], True), 9, right=True)
        y += 16
    page.draw_line((40, y), (555, y), color=(0.85, 0.85, 0.88))
    y += 20
    rows = [("Taxable value", inv.subtotal)]
    if inv.igst:
        rows.append(("IGST", inv.igst))
    if inv.cgst:
        rows += [("CGST", inv.cgst), ("SGST", inv.sgst)]
    for label, val in rows:
        t(470, y, label, 9, color=soft, right=True)
        t(555, y, inr(val, True), 9, right=True)
        y += 15
    t(470, y + 6, "Total", 11, True, right=True)
    t(555, y + 6, inr(inv.total, True), 11, True, right=True)
    if inv.notes:
        t(40, y + 50, inv.notes[:110], 9, color=soft)
    t(40, 800, "Generated with your AI accountant.", 8, color=soft)
    data = doc.tobytes()
    doc.close()
    return data


def next_number(existing: list[str], today: date) -> str:
    fy = today.year if today.month >= 4 else today.year - 1
    prefix = f"INV/{str(fy)[2:]}-{str(fy + 1)[2:]}/"
    nums = [int(n.rsplit("/", 1)[-1]) for n in existing if n.startswith(prefix) and n.rsplit("/", 1)[-1].isdigit()]
    return f"{prefix}{(max(nums) + 1) if nums else 1:03d}"
