"""Seed a realistic demo: ~28 invoices from 8 vendors over four months, signed
e-invoice QR codes (including one tampered printout and one forged QR), two
months of GSTR-2B statements with deliberate gaps, purchase orders, and a
duplicate upload. Every screen of the web app has something to show afterwards.

    DATABASE_URL=sqlite:///./gst.db PYTHONPATH=. python scripts/seed_demo_data.py

The e-invoice QR codes are signed with a locally generated DEMO key
(data/samples/demo_einvoice_keys/). Point EINVOICE_PUBLIC_KEY_PATHS at
data/samples/demo_einvoice_keys/public.pem for them to show as VERIFIED.
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import shutil
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "data" / "samples"
KEYS = SAMPLES / "demo_einvoice_keys"
PUBLIC_KEY = KEYS / "public.pem"
os.environ.setdefault("EINVOICE_PUBLIC_KEY_PATHS", str(PUBLIC_KEY))

from backend.config import reset_settings_cache  # noqa: E402

reset_settings_cache()

from backend.db.base import Base, SessionLocal, engine  # noqa: E402
from backend.db.models import Invoice, POLine, PurchaseOrder, Vendor  # noqa: E402
from backend.einvoice.signing import generate_demo_keypair, sign_qr_payload, stamp_qr_on_pdf  # noqa: E402
from backend.gstr2b.service import import_gstr2b  # noqa: E402
from backend.itc.service import reassess_all  # noqa: E402
from backend.services.pipeline_service import process_invoice_file  # noqa: E402
from backend.synthetic.generator import generate, make_gstin  # noqa: E402

BUYER = "Demo Buyer Pvt Ltd"
QR_RECT = (716, 86, 806, 176)
rng = random.Random(2026)

VENDORS = {  # key: (name, state)
    "sunrise": ("Sunrise Traders Pvt Ltd", "27"),
    "apex": ("Apex Electronics", "29"),
    "kaveri": ("Kaveri IT Solutions LLP", "27"),
    "omsai": ("Om Sai Enterprises", "27"),
    "coastal": ("Coastal Cabs and Coaches", "27"),
    "harbour": ("Harbour View Hospitality", "27"),
    "tirumala": ("Tirumala Steel Corp", "24"),
    "nexa": ("Nexa Stationers", "27"),
}
GSTINS = {k: make_gstin(random.Random(sum(map(ord, k))), st) for k, (_, st) in VENDORS.items()}  # stable across runs

OFFICE = [("A4 Copier Paper Ream", "4802", "NOS", 260, 18, 20), ("Wireless Keyboard", "8471", "NOS", 1200, 18, 4),
          ("LED Monitor 24 inch", "8528", "NOS", 9500, 18, 2), ("Office Chair", "9403", "NOS", 6200, 18, 3),
          ("Whiteboard Marker Pens (box)", "9608", "BOX", 240, 18, 25)]
IT = [("Software Consulting", "998313", "HRS", 1800, 18, 40), ("Website Development", "998314", "NOS", 55000, 18, 1)]
STEEL = [("Steel Frame Structure", "7308", "KGS", 74, 18, 600), ("Portland Cement Bag", "2523", "BAG", 380, 18, 50)]
CABS = [("Rent-a-cab airport transfers", "996601", "NOS", 2400, 5, 6),
        ("Coach hire for client group tour", "996425", "NOS", 38000, 5, 1)]
FOOD = [("Team dinner catering", "996334", "NOS", 450, 5, 40), ("Diwali gift hampers", "2106", "NOS", 1500, 5, 12)]
CAR = [("Company car - sedan", "8703", "NOS", 1150000, 18, 1)]


def month_start(d: date, back: int) -> date:
    y, m = d.year, d.month - back
    while m <= 0:
        m += 12
        y -= 1
    return date(y, m, 1)


def main() -> None:
    Base.metadata.create_all(engine)
    db = SessionLocal()
    if db.query(Invoice).count():
        print("Database already has invoices; run on an empty database (e.g. delete gst.db).")
        return

    work = ROOT / "data" / "inbox" / "demo"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True, exist_ok=True)
    SAMPLES.mkdir(parents=True, exist_ok=True)
    if not PUBLIC_KEY.exists():
        generate_demo_keypair(KEYS / "private.pem", PUBLIC_KEY)
    rogue_key = KEYS / "rogue_private.pem"
    if not rogue_key.exists():
        generate_demo_keypair(rogue_key, KEYS / "rogue_public.pem")

    today = date.today()
    m2, m1, m0 = month_start(today, 2), month_start(today, 1), month_start(today, 0)
    old = month_start(today, 6)

    # A purchase order for Sunrise so PO reconciliation has data.
    v = Vendor(gstin=GSTINS["sunrise"], name=VENDORS["sunrise"][0], normalized_name=VENDORS["sunrise"][0].lower(),
               state_code="27")
    db.add(v)
    db.flush()
    po = PurchaseOrder(po_number="PO-4501", vendor_id=v.id, status="OPEN", po_date=m2)
    db.add(po)
    db.flush()
    po_items = [OFFICE[0], OFFICE[1]]
    for n, (desc, hsn, unit, price, rate, qty) in enumerate(po_items, start=1):
        db.add(POLine(po_id=po.id, line_no=n, description=desc, hsn_sac=hsn, quantity=Decimal(qty),
                      unit_price=Decimal(price)))
    db.commit()

    plan = [
        # (vendor, base month, day, items, kwargs)
        ("sunrise", m2, 3, po_items, {"po_number": "PO-4501", "einv": "ok"}),
        ("sunrise", m2, 17, OFFICE[2:4], {"einv": "ok"}),
        ("apex", m2, 8, [OFFICE[2], OFFICE[1]], {"einv": "ok"}),
        ("kaveri", m2, 11, IT[:1], {}),
        ("omsai", m2, 14, OFFICE[3:], {}),
        ("omsai", m2, 26, OFFICE[:2], {}),
        ("coastal", m2, 20, CABS, {}),
        ("harbour", m2, 22, FOOD, {}),
        ("tirumala", m2, 5, STEEL, {"einv": "ok"}),
        ("nexa", m2, 9, [OFFICE[4], OFFICE[0]], {}),
        ("nexa", m2, 28, [OFFICE[4]], {"errors": ("bad_total",)}),
        ("sunrise", m1, 4, OFFICE[:3], {"einv": "ok"}),
        ("sunrise", m1, 19, [OFFICE[3]], {"einv": "tamper"}),
        ("apex", m1, 6, [OFFICE[2]], {"einv": "forged"}),
        ("apex", m1, 21, [OFFICE[1], OFFICE[2]], {"einv": "ok"}),
        ("kaveri", m1, 2, IT, {"einv": "ok"}),
        ("kaveri", m1, 23, IT[:1], {}),
        ("omsai", m1, 12, OFFICE[1:3], {}),
        ("omsai", m1, 25, [OFFICE[0]], {}),
        ("coastal", m1, 15, CABS[:1], {}),
        ("harbour", m1, 18, FOOD[:1], {}),
        ("tirumala", m1, 7, STEEL[:1], {"einv": "ok", "errors": ("wrong_igst",)}),
        ("tirumala", m1, 27, STEEL, {}),
        ("nexa", m1, 13, [OFFICE[4]], {}),
        ("sunrise", m1, 29, CAR, {"einv": "ok"}),
        ("kaveri", m0, 2, IT[:1], {"einv": "ok", "unpaid": True}),
        ("nexa", m0, 3, [OFFICE[0]], {"unpaid": True}),
        ("omsai", old, 10, OFFICE[:2], {"unpaid": True}),
    ]

    processed: list[tuple[Invoice, dict]] = []
    counter = 100
    for key, base, day, items, kw in plan:
        counter += rng.randint(3, 17)
        inv_date = base + timedelta(days=min(day, 28) - 1)
        if inv_date > today:
            inv_date = today
        name, state = VENDORS[key]
        inv_no = f"{key[:3].upper()}/{inv_date.year % 100}-{counter:04d}"
        path = work / f"{inv_no.replace('/', '_')}.pdf"
        si = generate(path, seed=counter, vendor_state=state, vendor_gstin=GSTINS[key], vendor_name=name,
                      buyer_name=BUYER, invoice_date=inv_date, invoice_number=inv_no,
                      po_number=kw.get("po_number"), errors=kw.get("errors", ()),
                      po_items=[(d, h, u, Decimal(p), r, q) for d, h, u, p, r, q in items],
                      printed_total_delta=Decimal("5000.00") if kw.get("einv") == "tamper" else None)
        t = si.truth
        if kw.get("einv"):
            qr_total = t["grand_total"] - (Decimal("5000.00") if kw["einv"] == "tamper" else 0)
            data = {"SellerGstin": t["vendor_gstin"], "BuyerGstin": t["buyer_gstin"], "DocNo": inv_no,
                    "DocTyp": "INV", "DocDt": inv_date.strftime("%d/%m/%Y"), "TotInvVal": float(qr_total),
                    "ItemCnt": len(t["items"]), "MainHsnCode": t["items"][0]["hsn_sac"],
                    "Irn": hashlib.sha256(f"{t['vendor_gstin']}{inv_no}".encode()).hexdigest(),
                    "IrnDt": f"{inv_date.isoformat()} 11:20:00"}
            key_path = rogue_key if kw["einv"] == "forged" else KEYS / "private.pem"
            stamp_qr_on_pdf(path, sign_qr_payload(data, key_path), QR_RECT)
        inv = process_invoice_file(db, path)
        if not kw.get("unpaid"):
            inv.payment_date = min(today, inv_date + timedelta(days=rng.randint(10, 40)))
        processed.append((inv, t | {"_key": key}))
        print(f"  {inv_no:16s} {name:28s} {inv.status:14s} e-invoice={inv.einvoice_status}")
    db.commit()

    # A duplicate upload (same file again).
    dup_src = work / f"{processed[3][0].invoice_number.replace('/', '_')}.pdf"
    dup = work / "duplicate_upload.pdf"
    shutil.copy(dup_src, dup)
    process_invoice_file(db, dup)

    # GSTR-2B statements for the last two full months, with realistic gaps.
    for period_start in (m2, m1):
        in_period = [(i, t) for i, t in processed if i.invoice_date and i.invoice_date.year == period_start.year
                     and i.invoice_date.month == period_start.month]
        doc = build_gstr2b(period_start, in_period)
        fname = f"gstr2b_{period_start.strftime('%m%Y')}.json"
        (SAMPLES / fname).write_text(json.dumps(doc, indent=2, default=str))
        imp = import_gstr2b(db, (SAMPLES / fname).read_bytes(), fname)
        print(f"Imported GSTR-2B {imp.return_period}: {imp.record_count} records")

    n = reassess_all(db)
    print(f"Assessed ITC for {n} invoices.")
    print(f"\nSample files are in {SAMPLES}. Demo key: {PUBLIC_KEY}")
    db.close()


def build_gstr2b(period_start: date, invoices: list[tuple[Invoice, dict]]) -> dict:
    """What the government would show: most invoices, minus the ones the vendor forgot."""
    by_vendor: dict[str, list[dict]] = {}
    for inv, t in invoices:
        key = t["_key"]
        if key == "omsai" and inv.invoice_date.day > 20:
            continue                                       # vendor did not file -> MISSING_IN_2B
        if key == "omsai" and period_start.month == (date.today().month - 1 or 12):
            continue
        items = t["items"]
        txval = sum(i["taxable_value"] for i in items)
        igst = sum((i["igst"] or 0) for i in items)
        cgst = sum((i["cgst"] or 0) for i in items)
        sgst = sum((i["sgst"] or 0) for i in items)
        inum = t["invoice_number"]
        entry = {"inum": inum, "typ": "R", "dt": inv.invoice_date.strftime("%d-%m-%Y"),
                 "val": float(t["grand_total"]), "pos": "27", "rev": "N", "itcavl": "Y", "rsn": "",
                 "srctyp": "e-Invoice" if inv.irn else "", "irn": inv.irn or "",
                 "items": [{"num": 1, "rt": 18, "txval": float(txval), "igst": float(igst),
                            "cgst": float(cgst), "sgst": float(sgst), "cess": 0}]}
        if key == "kaveri" and inv.invoice_date.day > 20:
            entry["items"][0]["txval"] += 1000.0              # vendor reported a different amount
            entry["items"][0]["cgst"] += 90.0
            entry["items"][0]["sgst"] += 90.0
        if key == "nexa" and inv.invoice_date.day < 10:
            entry["inum"] = inum[:-2] + inum[-1] + inum[-2]    # vendor typo (transposed digits) -> fuzzy match
        if key == "tirumala" and inv.invoice_date.day < 6:
            entry["dt"] = (inv.invoice_date + timedelta(days=1)).strftime("%d-%m-%Y")  # date differs
        if key == "coastal":
            entry["rev"] = "Y"                                # reverse charge supply
        by_vendor.setdefault(t["vendor_gstin"], []).append(entry)

    # Two invoices the supplier reported that are not in the register.
    ghost_gstin = make_gstin(random.Random(77), "27")
    by_vendor[ghost_gstin] = [
        {"inum": f"GH/{n}", "typ": "R", "dt": (period_start + timedelta(days=9 + n)).strftime("%d-%m-%Y"),
         "val": 11800.0, "pos": "27", "rev": "N", "itcavl": "Y" if n == 1 else "N", "rsn": "" if n == 1 else "C",
         "items": [{"num": 1, "rt": 18, "txval": 10000.0, "igst": 0, "cgst": 900.0, "sgst": 900.0, "cess": 0}]}
        for n in (1, 2)]
    names = {GSTINS[k]: VENDORS[k][0] for k in VENDORS} | {ghost_gstin: "Unknown Supplies Co"}
    return {"data": {
        "gstin": "27AAACD1234E1Z5", "rtnprd": period_start.strftime("%m%Y"), "version": "1.0",
        "gendt": (period_start + timedelta(days=45)).strftime("%d-%m-%Y"),
        "docdata": {"b2b": [{"ctin": g, "trdnm": names.get(g), "supfildt": "11-" + (
            period_start + timedelta(days=40)).strftime("%m-%Y"), "supprd": period_start.strftime("%m%Y"),
            "inv": invs} for g, invs in by_vendor.items()]},
    }}


if __name__ == "__main__":
    main()
