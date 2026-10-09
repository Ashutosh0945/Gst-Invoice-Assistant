"""Smart duplicate detection: exact checks (existing) + near-duplicate similarity scoring.
Blocking: same vendor (GSTIN, else normalised name) within 180 days. Signals: invoice-number similarity
(RapidFuzz), date gap, total / taxable / tax differences, line-description similarity.
Recurring-invoice guard: different invoice numbers are never flagged on similar amounts alone.
The score is a weighted similarity, NOT a calibrated probability. Nothing is deleted or merged."""
from __future__ import annotations

import re

from rapidfuzz import fuzz
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from backend.db.models import DuplicateCandidate, Invoice

LIKELY, POSSIBLE, WINDOW_DAYS = 0.85, 0.72, 180


def norm_no(s: str | None) -> str:
    s = re.sub(r"[^A-Z0-9]", "", (s or "").upper())
    return re.sub(r"0+(\d)", r"\1", s)


def _rel(a, b) -> float | None:
    if a is None or b is None:
        return None
    a, b = float(a), float(b)
    return abs(a - b) / max(abs(a), abs(b), 1.0)


def pair_signals(a: Invoice, b: Invoice) -> dict:
    na, nb = norm_no(a.invoice_number), norm_no(b.invoice_number)
    num_sim = fuzz.ratio(na, nb) / 100 if na and nb else 0.0
    tax = lambda i: sum(float(x or 0) for x in (i.total_cgst, i.total_sgst, i.total_igst))  # noqa: E731
    desc = lambda i: " ".join(sorted((li.description or "").lower() for li in i.items))      # noqa: E731
    da, db_ = re.sub(r"\D", "", na).lstrip("0"), re.sub(r"\D", "", nb).lstrip("0")
    return {"same_file": a.document_hash == b.document_hash,
            "number_digits_differ": bool(da and db_ and da != db_),
            "same_vendor_gstin": bool(a.vendor_gstin_raw) and a.vendor_gstin_raw == b.vendor_gstin_raw,
            "invoice_number_similarity": round(num_sim, 3), "invoice_number_exact": bool(na) and na == nb,
            "date_gap_days": abs((a.invoice_date - b.invoice_date).days) if a.invoice_date and b.invoice_date else None,
            "total_diff": _rel(a.grand_total, b.grand_total), "taxable_diff": _rel(a.subtotal, b.subtotal),
            "tax_diff": _rel(tax(a), tax(b)),
            "description_similarity": round(fuzz.token_set_ratio(desc(a), desc(b)) / 100, 3) if a.items and b.items else None}


def score_pair(s: dict) -> tuple[float, str | None]:
    if s["same_file"]:
        return 1.0, "exact"
    if s["invoice_number_exact"] and s["same_vendor_gstin"]:
        return 0.99, "exact"
    amt = lambda d: 0.5 if d is None else (1.0 if d <= 0.005 else max(0.0, 1 - d * 10))  # noqa: E731
    date_close = 0.5 if s["date_gap_days"] is None else max(0.0, 1 - s["date_gap_days"] / 30)
    desc = 0.5 if s["description_similarity"] is None else s["description_similarity"]
    score = (0.45 * s["invoice_number_similarity"] + 0.2 * amt(s["total_diff"]) + 0.1 * amt(s["tax_diff"])
             + 0.05 * amt(s["taxable_diff"]) + 0.1 * date_close + 0.1 * desc)
    # Recurring-invoice guard: a different number in the sequence (RENT/07 vs RENT/08) or a clearly different
    # invoice number means a different invoice, however similar the amounts and descriptions are.
    if s["invoice_number_similarity"] < 0.6 or s.get("number_digits_differ"):
        score = min(score, 0.5)
    tier = "likely" if score >= LIKELY else "possible" if score >= POSSIBLE else None
    return round(score, 4), tier


def _vendor_key(i: Invoice) -> str:
    return i.vendor_gstin_raw or f"name:{(i.vendor_name_raw or '').strip().lower()}"


def candidates_for(db: Session, inv: Invoice) -> list[DuplicateCandidate]:
    others = db.execute(select(Invoice).options(selectinload(Invoice.items)).where(Invoice.id != inv.id)).scalars().all()
    made = []
    for o in others:
        if _vendor_key(o) != _vendor_key(inv) or (_vendor_key(inv).startswith("name:") and _vendor_key(inv) == "name:"):
            if o.document_hash != inv.document_hash:
                continue
        if inv.invoice_date and o.invoice_date and abs((inv.invoice_date - o.invoice_date).days) > WINDOW_DAYS:
            continue
        s = pair_signals(inv, o)
        sc, tier = score_pair(s)
        if not tier:
            continue
        a, b = sorted([inv.id, o.id], key=str)
        exists = db.execute(select(DuplicateCandidate).where(DuplicateCandidate.invoice_a == a, DuplicateCandidate.invoice_b == b)).scalars().first()
        if exists:
            continue
        c = DuplicateCandidate(invoice_a=a, invoice_b=b, tier=tier, score=sc, signals=s)
        db.add(c)
        made.append(c)
    db.flush()
    return made


def scan_safely(db: Session, inv: Invoice) -> None:
    import logging
    try:
        candidates_for(db, inv)
        db.commit()
    except Exception:  # noqa: BLE001 - duplicate scoring must never break invoice processing
        db.rollback()
        logging.getLogger(__name__).exception("Duplicate scan failed for %s", inv.id)


def open_candidates(db: Session, status: str | None = "open"):
    q = select(DuplicateCandidate).order_by(DuplicateCandidate.score.desc())
    if status:
        q = q.where(DuplicateCandidate.status == status)
    return db.execute(q).scalars().all()
