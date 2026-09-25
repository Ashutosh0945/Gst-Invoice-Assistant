"""Create three demo accounts for the personal app, with bills, invoices and tax details.

    DATABASE_URL=sqlite:///./gst.db PYTHONPATH=. python scripts/seed_personal_demo.py

Sign in with any of (password: demo12345):
    freelancer@demo.in   Aarav — freelance designer, GST-registered
    shop@demo.in         Meera — runs a stationery shop
    me@demo.in           Rohan — salaried, personal bills
"""
from __future__ import annotations

import tempfile
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select

from backend.db.base import Base, SessionLocal, engine
from backend.db import models  # noqa: F401
from backend.db.models import SalesInvoice, User, UserBill
from backend.personal.auth import hash_password
from backend.personal.bills import guess_category, overcharges
from backend.personal.invoicing import compute_invoice, next_number
from backend.services.pipeline_service import process_invoice_file
from backend.synthetic.generate import generate_invoice
from backend.synthetic.generator import generate, make_gstin
import random

PASSWORD = "demo12345"
TODAY = date.today()


def user(db, email, name, profile, **kw) -> User:
    u = db.execute(select(User).where(User.email == email)).scalars().first()
    if u:
        return u
    u = User(email=email, name=name, password_hash=hash_password(PASSWORD), profile_type=profile, **kw)
    db.add(u)
    db.flush()
    return u


def add_bill(db, u: User, pdf: bytes, name: str, category: str | None = None, warranty_days: int | None = None):
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as t:
        t.write(pdf)
        p = Path(t.name)
    inv = process_invoice_file(db, p, owner_id=u.id, source_name=name)
    p.unlink(missing_ok=True)
    b = UserBill(owner_id=u.id, invoice_id=inv.id, category=category or guess_category(inv),
                 warranty_until=TODAY + timedelta(days=warranty_days) if warranty_days else None)
    db.add(b)
    db.flush()
    return b


def layout_b(seed: int, items, vendor: str, days_ago: int, state="27") -> bytes:
    with tempfile.TemporaryDirectory() as d:
        si = generate(Path(d) / "x.pdf", seed=seed, vendor_name=vendor, vendor_state=state,
                      invoice_date=TODAY - timedelta(days=days_ago),
                      po_items=[(a, h, un, Decimal(p), r, q) for a, h, un, p, r, q in items])
        return si.pdf_path.read_bytes()


def overcharged_bill(db, u: User) -> None:
    for seed in range(1, 200):
        si = generate_invoice(seed=seed, n_items=2, inject_error="gst_rate", invoice_date=TODAY - timedelta(days=3))
        first = si.ground_truth.items[0]
        if first.hsn_sac in ("6109", "2106") and first.gst_rate == Decimal("10"):
            b = add_bill(db, u, si.pdf_bytes, "showroom-bill.pdf")
            if overcharges(b.invoice):
                return


def sales(db, u: User, client: str, items: list[dict], days_ago: int, due: int, paid_after: int | None, pos="27"):
    issue = TODAY - timedelta(days=days_ago)
    calc = compute_invoice(items, u.state_code, pos, bool(u.gstin))
    existing = [s.number for s in db.execute(select(SalesInvoice).where(SalesInvoice.owner_id == u.id)).scalars()]
    db.add(SalesInvoice(owner_id=u.id, number=next_number(existing, issue), issue_date=issue,
                        due_date=issue + timedelta(days=due), client_name=client, place_of_supply=pos,
                        items=calc["items"], subtotal=calc["subtotal"], cgst=calc["cgst"], sgst=calc["sgst"],
                        igst=calc["igst"], total=calc["total"],
                        status="PAID" if paid_after is not None else "SENT",
                        paid_on=issue + timedelta(days=paid_after) if paid_after is not None else None))
    db.flush()


def main() -> None:
    Base.metadata.create_all(engine)
    db = SessionLocal()
    if db.execute(select(User).where(User.email == "freelancer@demo.in")).scalars().first():
        print("Demo accounts already exist.")
        return

    # Freelancer
    f = user(db, "freelancer@demo.in", "Aarav Shah", "freelancer", business_name="Aarav Designs",
             gstin="27AAPFU0939F1ZV", state_code="27",
             tax_inputs={"business_income": 1400000, "other_income": 40000, "sec_80c": 150000,
                         "sec_80d_self": 18000, "age_band": "below_60", "tds_paid": 60000})
    add_bill(db, f, layout_b(11, [("LED Monitor 24 inch", "8528", "NOS", 9500, 18, 1)], "Apex Electronics", 20),
             "monitor-invoice.pdf", warranty_days=40)
    add_bill(db, f, layout_b(12, [("Software Consulting", "998313", "HRS", 1800, 18, 6)], "Kaveri IT Solutions LLP", 12),
             "kaveri-consulting.pdf")
    add_bill(db, f, layout_b(13, [("Team dinner catering", "996334", "NOS", 450, 5, 12)], "Harbour View Hospitality", 8),
             "client-dinner.pdf", "food")
    sales(db, f, "Bluewave Media Pvt Ltd", [{"description": "Brand identity design", "hsn_sac": "998391", "quantity": 1,
          "rate": 85000, "gst_rate": 18}], 52, 15, None)
    sales(db, f, "Tiffin Tales (Bengaluru)", [{"description": "Menu & packaging design", "hsn_sac": "998391",
          "quantity": 1, "rate": 42000, "gst_rate": 18}], 20, 30, None, pos="29")
    sales(db, f, "Studio Kala", [{"description": "Social media templates", "hsn_sac": "998391", "quantity": 10,
          "rate": 3500, "gst_rate": 18}], 35, 15, 12)

    # Shop owner
    s = user(db, "shop@demo.in", "Meera Iyer", "business", business_name="Iyer Stationers",
             gstin=make_gstin(random.Random(5), "27"), state_code="27")
    add_bill(db, s, layout_b(21, [("A4 Copier Paper Ream", "4802", "NOS", 260, 18, 50),
                                  ("Whiteboard Marker Pens (box)", "9608", "BOX", 240, 18, 20)], "Sunrise Traders Pvt Ltd", 15),
             "sunrise-stock.pdf", "office")
    add_bill(db, s, layout_b(22, [("Office Chair", "9403", "NOS", 6200, 18, 2)], "Nexa Stationers", 30), "chairs.pdf")
    sales(db, s, "Little Stars School", [{"description": "Notebooks and stationery kits", "quantity": 120,
          "rate": 180, "gst_rate": 5}], 18, 7, None)

    # Individual
    m = user(db, "me@demo.in", "Rohan Mehta", "individual", state_code="27",
             tax_inputs={"salary_income": 1500000, "sec_80c": 150000, "sec_80d_self": 25000,
                         "hra_exempt": 120000, "age_band": "below_60", "tds_paid": 90000})
    overcharged_bill(db, m)
    add_bill(db, m, layout_b(31, [("Dell Inspiron Laptop", "8471", "NOS", 42000, 18, 1)], "Apex Electronics", 200),
             "laptop.pdf", warranty_days=45)
    add_bill(db, m, layout_b(32, [("Family health insurance premium", "997132", "NOS", 21000, 18, 1)],
                             "Secure Health Insurance", 60), "health-insurance.pdf", "health")
    db.commit()
    print("Demo accounts ready (password: demo12345): freelancer@demo.in, shop@demo.in, me@demo.in")


if __name__ == "__main__":
    main()
