"""API for the personal app ("an accountant in your pocket"). Every route is scoped
to the signed-in user; nobody can read another user's bills, invoices or chats."""
from __future__ import annotations

import re
import tempfile
from datetime import date, timedelta
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, UploadFile
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.base import get_db
from backend.db.models import ChatMessage, Invoice, SalesInvoice, User, UserBill
from backend.personal import assistant, tax
from backend.personal.auth import (clear_session_cookie, current_user, hash_password, set_session_cookie,
                                   verify_password)
from backend.personal.bills import CATEGORY_LABELS, guess_category, insights
from backend.personal.invoicing import compute_invoice, next_number, render_pdf
from backend.services.pipeline_service import process_invoice_file
from backend.validation.gst import STATE_CODES, gstin_checksum

router = APIRouter(prefix="/app")
PROFILE_TYPES = ("individual", "business", "freelancer")
MAX_UPLOAD = 15 * 1024 * 1024
ALLOWED = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"}


# ----------------------------------------------------------------------------- schemas
class SignupIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)
    profile_type: str = "individual"
    business_name: str | None = None
    gstin: str | None = None
    state_code: str | None = None

    @field_validator("profile_type")
    @classmethod
    def _pt(cls, v):
        if v not in PROFILE_TYPES:
            raise ValueError("profile_type must be individual, business or freelancer")
        return v


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class ProfileIn(BaseModel):
    name: str | None = None
    profile_type: str | None = None
    business_name: str | None = None
    gstin: str | None = None
    state_code: str | None = None


class BillPatch(BaseModel):
    category: str | None = None
    note: str | None = None
    warranty_until: date | None = None
    clear_warranty: bool = False


class InvoiceItemIn(BaseModel):
    description: str
    hsn_sac: str | None = None
    quantity: float = Field(gt=0, default=1)
    rate: float = Field(ge=0)
    gst_rate: float = Field(ge=0, le=40, default=18)


class InvoiceIn(BaseModel):
    client_name: str = Field(min_length=1)
    client_email: EmailStr | None = None
    client_gstin: str | None = None
    place_of_supply: str | None = None
    issue_date: date | None = None
    due_in_days: int = Field(ge=0, le=365, default=15)
    items: list[InvoiceItemIn] = Field(min_length=1)
    notes: str | None = None


class PaidIn(BaseModel):
    paid_on: date | None = None


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


# ----------------------------------------------------------------------------- helpers
def _clean_gstin(g: str | None) -> str | None:
    if not g:
        return None
    g = re.sub(r"\s", "", g).upper()
    if len(g) != 15 or not re.match(r"^\d{2}[A-Z0-9]{13}$", g) or gstin_checksum(g[:14]) != g[14]:
        raise HTTPException(422, "That GSTIN doesn't look right. Check it on your registration certificate.")
    return g


def _state(code: str | None) -> str | None:
    if not code:
        return None
    code = code.zfill(2)
    if code not in STATE_CODES:
        raise HTTPException(422, "Unknown state code.")
    return code


def _m(x) -> str | None:
    """Money always leaves the API as a 2-decimal string (never a float)."""
    return None if x is None else f"{x:.2f}"


def _num(x) -> str | None:
    """15.000 -> '15', 12.50 -> '12.5'."""
    return None if x is None else f"{x.normalize():f}"


def _me(u: User) -> dict:
    return {"id": str(u.id), "name": u.name, "email": u.email, "profile_type": u.profile_type,
            "business_name": u.business_name, "gstin": u.gstin, "state_code": u.state_code,
            "state_name": STATE_CODES.get(u.state_code or "", None), "has_tax_profile": bool(u.tax_inputs)}


def _bill_row(b: UserBill) -> dict:
    inv = b.invoice
    return {"id": str(b.id), "vendor": inv.vendor_name_raw, "invoice_number": inv.invoice_number,
            "date": inv.invoice_date, "total": _m(inv.grand_total), "category": b.category,
            "category_label": CATEGORY_LABELS.get(b.category, b.category), "warranty_until": b.warranty_until,
            "einvoice_status": inv.einvoice_status, "added": b.created_at, "file": inv.source_filename}


def _get_bill(db: Session, user: User, bill_id: UUID) -> UserBill:
    b = db.get(UserBill, bill_id)
    if b is None or b.owner_id != user.id:
        raise HTTPException(404, "Bill not found.")
    return b


def _get_sales(db: Session, user: User, inv_id: UUID) -> SalesInvoice:
    s = db.get(SalesInvoice, inv_id)
    if s is None or s.owner_id != user.id:
        raise HTTPException(404, "Invoice not found.")
    return s


def _sales_row(s: SalesInvoice) -> dict:
    today = date.today()
    return {"id": str(s.id), "number": s.number, "client_name": s.client_name, "client_email": s.client_email,
            "client_gstin": s.client_gstin, "issue_date": s.issue_date, "due_date": s.due_date,
            "total": _m(s.total), "subtotal": _m(s.subtotal), "cgst": _m(s.cgst), "sgst": _m(s.sgst),
            "igst": _m(s.igst),
            "status": s.status, "paid_on": s.paid_on, "items": s.items, "notes": s.notes,
            "place_of_supply": s.place_of_supply,
            "days_overdue": (today - s.due_date).days if s.status != "PAID" and s.due_date and s.due_date < today else 0}


# ----------------------------------------------------------------------------- auth
@router.post("/auth/signup", status_code=201)
def signup(body: SignupIn, response: Response, db: Session = Depends(get_db)):
    email = body.email.lower()
    if db.execute(select(User).where(User.email == email)).scalars().first():
        raise HTTPException(409, "An account with this email already exists. Sign in instead.")
    u = User(email=email, name=body.name.strip(), password_hash=hash_password(body.password),
             profile_type=body.profile_type, business_name=(body.business_name or "").strip() or None,
             gstin=_clean_gstin(body.gstin), state_code=_state(body.state_code))
    if u.gstin and not u.state_code:
        u.state_code = u.gstin[:2]
    db.add(u)
    db.commit()
    set_session_cookie(response, u.id)
    return _me(u)


@router.post("/auth/login")
def login(body: LoginIn, response: Response, db: Session = Depends(get_db)):
    u = db.execute(select(User).where(User.email == body.email.lower())).scalars().first()
    if u is None or not verify_password(body.password, u.password_hash):
        raise HTTPException(401, "Email or password is incorrect.")
    set_session_cookie(response, u.id)
    return _me(u)


@router.post("/auth/logout", status_code=204)
def logout(response: Response):
    clear_session_cookie(response)


@router.get("/me")
def me(user: User = Depends(current_user)):
    return _me(user)


@router.patch("/me")
def update_me(body: ProfileIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if body.name is not None:
        user.name = body.name.strip() or user.name
    if body.profile_type is not None:
        if body.profile_type not in PROFILE_TYPES:
            raise HTTPException(422, "Unknown profile type.")
        user.profile_type = body.profile_type
    if body.business_name is not None:
        user.business_name = body.business_name.strip() or None
    if body.gstin is not None:
        user.gstin = _clean_gstin(body.gstin) if body.gstin.strip() else None
        if user.gstin:
            user.state_code = user.gstin[:2]
    if body.state_code is not None:
        user.state_code = _state(body.state_code)
    db.commit()
    return _me(user)


@router.get("/states")
def states():
    return [{"code": k, "name": v} for k, v in STATE_CODES.items() if k not in ("97", "99")]


# ----------------------------------------------------------------------------- home
@router.get("/home")
def home(user: User = Depends(current_user), db: Session = Depends(get_db)):
    snap = assistant.tool_snapshot(db, user, {})
    bills = db.execute(select(UserBill).where(UserBill.owner_id == user.id)
                       .order_by(UserBill.created_at.desc()).limit(5)).scalars().all()
    return {"me": _me(user), "snapshot": snap, "recent_bills": [_bill_row(b) for b in bills],
            "deadlines": tax.upcoming_deadlines(user.profile_type, date.today(), bool(user.gstin), 4),
            "suggestions": assistant.SUGGESTIONS[user.profile_type]}


# ----------------------------------------------------------------------------- bills
@router.get("/bills")
def list_bills(category: str | None = None, q: str | None = None,
               user: User = Depends(current_user), db: Session = Depends(get_db)):
    stmt = select(UserBill).where(UserBill.owner_id == user.id).order_by(UserBill.created_at.desc())
    if category:
        stmt = stmt.where(UserBill.category == category)
    rows = [_bill_row(b) for b in db.execute(stmt).scalars().all()]
    if q:
        ql = q.lower()
        rows = [r for r in rows if ql in " ".join(str(r[k] or "") for k in ("vendor", "invoice_number",
                                                                          "category_label", "file")).lower()]
    return rows


@router.post("/bills", status_code=201)
async def upload_bill(file: UploadFile, user: User = Depends(current_user), db: Session = Depends(get_db)):
    suffix = Path(file.filename or "bill.pdf").suffix.lower() or ".pdf"
    if suffix not in ALLOWED:
        raise HTTPException(415, "Upload a PDF or a photo (JPG, PNG, WEBP).")
    raw = await file.read()
    if len(raw) > MAX_UPLOAD:
        raise HTTPException(413, "That file is larger than 15 MB.")
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(raw)
        tmp_path = Path(tmp.name)
    try:
        inv = process_invoice_file(db, tmp_path, owner_id=user.id, source_name=file.filename or tmp_path.name)
    finally:
        tmp_path.unlink(missing_ok=True)
    bill = UserBill(owner_id=user.id, invoice_id=inv.id, category=guess_category(inv))
    db.add(bill)
    db.commit()
    db.refresh(bill)
    return bill_detail(bill.id, user, db)


@router.get("/bills/{bill_id}")
def bill_detail(bill_id: UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    b = _get_bill(db, user, bill_id)
    inv = b.invoice
    return {**_bill_row(b), "note": b.note, "vendor_gstin": inv.vendor_gstin_raw,
            "subtotal": _m(inv.subtotal), "cgst": _m(inv.total_cgst), "sgst": _m(inv.total_sgst),
            "igst": _m(inv.total_igst),
            "items": [{"line_no": li.line_no, "description": li.description, "hsn_sac": li.hsn_sac,
                       "quantity": _num(li.quantity), "rate": _m(li.unit_price), "gst_rate": _num(li.gst_rate),
                       "amount": _m(li.line_total or li.taxable_value)} for li in inv.items],
            "insights": insights(b, user.profile_type), "categories": CATEGORY_LABELS}


@router.patch("/bills/{bill_id}")
def update_bill(bill_id: UUID, body: BillPatch, user: User = Depends(current_user), db: Session = Depends(get_db)):
    b = _get_bill(db, user, bill_id)
    if body.category is not None:
        if body.category not in CATEGORY_LABELS:
            raise HTTPException(422, "Unknown category.")
        b.category = body.category
    if body.note is not None:
        b.note = body.note.strip() or None
    if body.clear_warranty:
        b.warranty_until = None
    elif body.warranty_until is not None:
        b.warranty_until = body.warranty_until
    db.commit()
    return bill_detail(bill_id, user, db)


@router.delete("/bills/{bill_id}", status_code=204)
def delete_bill(bill_id: UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    b = _get_bill(db, user, bill_id)
    inv = db.get(Invoice, b.invoice_id)
    db.delete(b)
    if inv is not None:
        db.delete(inv)
    db.commit()


# ----------------------------------------------------------------------------- invoices I send
@router.get("/invoices")
def list_invoices(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.execute(select(SalesInvoice).where(SalesInvoice.owner_id == user.id)
                      .order_by(SalesInvoice.issue_date.desc(), SalesInvoice.created_at.desc())).scalars().all()
    return [_sales_row(s) for s in rows]


@router.post("/invoices", status_code=201)
def create_invoice(body: InvoiceIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    issue = body.issue_date or date.today()
    pos = _state(body.place_of_supply) or (body.client_gstin[:2] if body.client_gstin else None) or user.state_code
    calc = compute_invoice([i.model_dump() for i in body.items], user.state_code, pos, bool(user.gstin))
    existing = [n for (n,) in db.execute(select(SalesInvoice.number).where(SalesInvoice.owner_id == user.id)).all()]
    s = SalesInvoice(owner_id=user.id, number=next_number(existing, issue), issue_date=issue,
                     due_date=issue + timedelta(days=body.due_in_days), client_name=body.client_name.strip(),
                     client_email=body.client_email, client_gstin=_clean_gstin(body.client_gstin),
                     place_of_supply=pos, items=calc["items"], subtotal=calc["subtotal"], cgst=calc["cgst"],
                     sgst=calc["sgst"], igst=calc["igst"], total=calc["total"], status="SENT",
                     notes=(body.notes or "").strip() or None)
    db.add(s)
    db.commit()
    return _sales_row(s)


@router.get("/invoices/{inv_id}")
def get_invoice(inv_id: UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return _sales_row(_get_sales(db, user, inv_id))


@router.post("/invoices/{inv_id}/paid")
def mark_paid(inv_id: UUID, body: PaidIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    s = _get_sales(db, user, inv_id)
    if body.paid_on is None and s.status == "PAID":
        s.status, s.paid_on = "SENT", None           # undo
    else:
        s.status, s.paid_on = "PAID", body.paid_on or date.today()
    db.commit()
    return _sales_row(s)


@router.delete("/invoices/{inv_id}", status_code=204)
def delete_invoice(inv_id: UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.delete(_get_sales(db, user, inv_id))
    db.commit()


@router.get("/invoices/{inv_id}/pdf")
def invoice_pdf(inv_id: UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    s = _get_sales(db, user, inv_id)
    name = s.number.replace("/", "-")
    return Response(render_pdf(s, user), media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{name}.pdf"'})


# ----------------------------------------------------------------------------- tax tools
@router.get("/tax/profile")
def tax_profile(user: User = Depends(current_user)):
    return {"inputs": user.tax_inputs or {}, "financial_year": tax.rules()["financial_year"],
            "deduction_caps": tax.rules()["deduction_caps"]}


@router.post("/tax/compare")
def tax_compare(body: dict, save: bool = Query(True), user: User = Depends(current_user),
                db: Session = Depends(get_db)):
    inp = tax.TaxInputs.from_dict(body)
    if save:
        user.tax_inputs = {k: v for k, v in inp.__dict__.items()}
        db.commit()
    return tax.compare_regimes(inp)


@router.post("/tax/gst-registration")
def tax_gst(body: dict, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return assistant.tool_gst_registration(db, user, body)


@router.post("/tax/advance")
def tax_advance(body: dict, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not (user.tax_inputs or body):
        raise HTTPException(422, "Fill in the income tax planner first.")
    return assistant.tool_advance_tax(db, user, body)


@router.post("/tax/presumptive")
def tax_presumptive(body: dict, user: User = Depends(current_user)):
    return tax.presumptive_income(body.get("scheme") or "44ADA", float(body.get("receipts") or 0),
                                  float(body.get("digital_share") or 1.0))


@router.get("/deadlines")
def deadlines(user: User = Depends(current_user)):
    return tax.upcoming_deadlines(user.profile_type, date.today(), bool(user.gstin), 12)


# ----------------------------------------------------------------------------- assistant
@router.get("/assistant/history")
def chat_history(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.execute(select(ChatMessage).where(ChatMessage.owner_id == user.id)
                      .order_by(ChatMessage.created_at, ChatMessage.id)).scalars().all()
    return {"messages": [{"id": str(m.id), "role": m.role, "content": m.content, "meta": m.meta} for m in rows][-60:],
            "suggestions": assistant.SUGGESTIONS[user.profile_type]}


@router.post("/assistant")
def chat(body: ChatIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    prev = db.execute(select(ChatMessage).where(ChatMessage.owner_id == user.id)
                      .order_by(ChatMessage.created_at.desc()).limit(8)).scalars().all()
    history = [{"role": m.role, "content": m.content} for m in reversed(prev)]
    db.add(ChatMessage(owner_id=user.id, role="user", content=body.message))
    db.flush()
    out = assistant.answer(db, user, body.message, history)
    meta = {"mode": out["mode"], "tools": [{"tool": t["tool"], "args": t["args"]} for t in out["tools"]],
            "cards": [{"tool": t["tool"], "result": t["result"]} for t in out["tools"]],
            "disclaimer": out["disclaimer"]}
    msg = ChatMessage(owner_id=user.id, role="assistant", content=out["reply"], meta=_jsonable(meta))
    db.add(msg)
    db.commit()
    return {"id": str(msg.id), "role": "assistant", "content": out["reply"], "meta": msg.meta}


@router.delete("/assistant/history", status_code=204)
def clear_chat(user: User = Depends(current_user), db: Session = Depends(get_db)):
    for m in db.execute(select(ChatMessage).where(ChatMessage.owner_id == user.id)).scalars().all():
        db.delete(m)
    db.commit()


def _jsonable(o):
    import json
    return json.loads(json.dumps(o, default=str))
