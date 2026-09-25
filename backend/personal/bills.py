"""Turn a checked bill into plain-language insights for a non-accountant."""
from __future__ import annotations

import re
from decimal import Decimal

from backend.db.models import Invoice, UserBill
from backend.personal.money import inr

CATEGORY_RULES = [  # (category, HSN/SAC prefixes, words in description)
    ("food", ("99633", "2106", "1905", "2202"), ("restaurant", "food", "meal", "dinner", "lunch", "cafe", "catering")),
    ("travel", ("9964", "9966", "99631", "9985"), ("flight", "air", "cab", "taxi", "hotel", "train", "bus", "tour")),
    ("health", ("3004", "9993", "997132", "997131"), ("medicine", "pharma", "hospital", "clinic", "insurance")),
    ("electronics", ("84", "85"), ("laptop", "phone", "monitor", "tv", "keyboard", "printer")),
    ("education", ("9992",), ("tuition", "school", "course", "college")),
    ("utilities", ("9969", "2716", "9984"), ("electricity", "internet", "broadband", "mobile bill", "gas")),
    ("office", ("4802", "4820", "9403", "9401", "9608"), ("paper", "chair", "stationery", "office")),
    ("professional", ("9982", "9983", "998"), ("consulting", "services", "design", "development")),
]

CATEGORY_LABELS = {"food": "Food & dining", "travel": "Travel", "health": "Health", "electronics": "Electronics",
                   "education": "Education", "utilities": "Utilities", "office": "Office & supplies",
                   "professional": "Professional services", "other": "Other"}

DEDUCTION_HINTS = {
    "health": "Health insurance premiums can reduce your tax under section 80D (old regime).",
    "education": "Children's tuition fees count towards section 80C (old regime).",
}

FRIENDLY = {
    "GRAND_TOTAL_MISMATCH": "The total doesn't add up: items plus tax don't equal the amount charged.",
    "LINE_ARITHMETIC_MISMATCH": "A line's quantity × price doesn't match the amount shown.",
    "LINE_GST_MISMATCH": "The GST on a line doesn't match its rate.",
    "LINE_TOTAL_MISMATCH": "A line total doesn't add up.",
    "TAX_TYPE_CONFLICT": "A line charges both CGST/SGST and IGST, which isn't allowed.",
    "CGST_SGST_MISMATCH": "CGST and SGST should be equal, but they aren't.",
    "DUPLICATE_EXACT_FILE": "You've already added this exact bill before.",
    "DUPLICATE_LIKELY": "This looks like a bill you've already added.",
}


def guess_category(inv: Invoice) -> str:
    text = " ".join((li.description or "") for li in inv.items).lower() + " " + (inv.vendor_name_raw or "").lower()
    codes = [li.hsn_sac or "" for li in inv.items]
    for cat, prefixes, words in CATEGORY_RULES:
        if any(c.startswith(p) for c in codes for p in prefixes) or \
                any(re.search(rf"\b{re.escape(w)}\b", text) for w in words):
            return cat
    return "other"


def overcharges(inv: Invoice) -> list[dict]:
    """GST charged above the standard rate for that HSN/SAC -> money the customer may have overpaid."""
    out = []
    lines = {li.line_no: li for li in inv.items}
    for f in inv.findings:
        if f.code != "HSN_RATE_MISMATCH" or not f.expected or "|" in f.expected or f.line_no not in lines:
            continue
        try:
            expected, actual = Decimal(f.expected), Decimal(f.actual)
        except Exception:  # noqa: BLE001
            continue
        li = lines[f.line_no]
        if actual > expected and li.taxable_value:
            extra = (li.taxable_value * (actual - expected) / 100).quantize(Decimal("0.01"))
            out.append({"line_no": li.line_no, "description": li.description, "charged_rate": str(actual),
                        "expected_rate": str(expected), "extra": str(extra)})
    return out


def insights(bill: UserBill, profile_type: str) -> dict:
    inv = bill.invoice
    oc = overcharges(inv)
    problems = []
    for f in inv.findings:
        if f.severity == "INFO" or f.code in ("NO_PO_REFERENCE", "HSN_RATE_MISMATCH") or f.category == "reconciliation":
            continue
        if f.code.startswith("HSN_"):
            continue  # unknown codes are an accounting concern, not a consumer one
        problems.append(FRIENDLY.get(f.code, f.message))
    if inv.einvoice_status in ("MISMATCH", "SIGNATURE_INVALID"):
        problems.insert(0, "The bill doesn't match its government QR code. It may have been edited — ask the seller.")
    extra_total = sum(Decimal(o["extra"]) for o in oc)
    if oc:
        headline, tone = f"You may have been overcharged {inr(extra_total, True)} in GST", "bad"
    elif problems:
        headline, tone = "Something on this bill doesn't add up", "warn"
    elif not inv.grand_total:
        headline, tone = "We couldn't read this bill fully", "warn"
    else:
        headline, tone = "This bill looks correct", "good"
    tips = []
    for o in oc:
        charged, usual = (f"{Decimal(o[k]).normalize():f}" for k in ("charged_rate", "expected_rate"))
        tips.append(f"'{o['description']}' was charged {charged}% GST; the usual rate is {usual}%. "
                    "You can ask the seller to correct it.")
    if bill.category in DEDUCTION_HINTS:
        tips.append(DEDUCTION_HINTS[bill.category])
    gst_paid = sum((x or 0) for x in (inv.total_cgst, inv.total_sgst, inv.total_igst))
    claimable = None
    if profile_type in ("business", "freelancer") and inv.itc:
        claimable = str(inv.itc.eligible_itc)
        if inv.itc.eligible_itc and inv.itc.eligible_itc > 0:
            tips.append(f"As a business expense, {inr(inv.itc.eligible_itc, True)} of GST on this bill can be claimed "
                        "back (if you're GST-registered).")
        blocked = [r["message"] for r in (inv.itc.reasons or []) if r["code"] in ("I010", "I011")]
        tips += blocked[:2]
    return {"headline": headline, "tone": tone, "problems": problems, "overcharges": oc,
            "overcharge_total": str(extra_total), "tips": tips, "gst_paid": str(gst_paid),
            "gst_claimable": claimable}
