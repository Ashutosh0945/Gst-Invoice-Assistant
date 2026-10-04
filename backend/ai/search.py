"""Natural-language search -> a whitelisted filter object -> an ORM query.

The text is never turned into SQL. A rule parser understands the common phrasings; if
it finds nothing and AI is enabled, OpenRouter may propose a filter, which is then
validated against the SearchFilters schema (unknown keys/values are rejected).
"""
from __future__ import annotations

import json
import re
from datetime import date

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.orm import Session

from backend.ai import facts as F

STATUS_WORDS = {"needs review": "NEEDS_REVIEW", "review": "NEEDS_REVIEW", "auto-approved": "AUTO_APPROVED",
                "auto approved": "AUTO_APPROVED", "approved": "APPROVED", "rejected": "REJECTED"}
MONTHS = {m.lower(): i for i, m in enumerate(["January", "February", "March", "April", "May", "June", "July",
                                              "August", "September", "October", "November", "December"], 1)}


class SearchFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    vendor: str | None = Field(None, max_length=80)
    min_amount: float | None = Field(None, ge=0)
    max_amount: float | None = Field(None, ge=0)
    status: str | None = Field(None, pattern="^(NEEDS_REVIEW|AUTO_APPROVED|APPROVED|REJECTED)$")
    gstr2b: str | None = Field(None, pattern="^(missing|mismatch|matched)$")
    vendor_has_2b_mismatch: bool = False
    has_errors: bool = False
    einvoice_problem: bool = False
    gst_rate: float | None = Field(None, ge=0, le=40)
    period: str | None = Field(None, pattern=r"^(this_month|last_month|this_quarter|this_fy|last_90_days|\d{4}-\d{2})$")


def _amount(num: str, unit: str | None) -> float:
    n = float(num.replace(",", ""))
    unit = (unit or "").lower()
    return n * (1e5 if unit in ("lakh", "lakhs", "lac", "l") else 1e7 if unit in ("crore", "crores", "cr")
                else 1e3 if unit in ("k", "thousand") else 1)


AMT = r"(?:₹|rs\.?|inr)?\s*(\d[\d,]*(?:\.\d+)?)\s*(lakhs?|lac|crores?|cr|k|thousand|l\b)?"


def parse_rules(text: str, known_vendors: list[str]) -> SearchFilters:
    t = " " + text.lower() + " "
    f: dict = {}
    if m := re.search(r"(?:above|over|more than|greater than|>|at least|min(?:imum)?)\s*" + AMT, t):
        f["min_amount"] = _amount(m.group(1), m.group(2))
    if m := re.search(r"(?:below|under|less than|<|at most|max(?:imum)?)\s*" + AMT, t):
        f["max_amount"] = _amount(m.group(1), m.group(2))
    if m := re.search(r"between\s*" + AMT + r"\s*(?:and|to|-)\s*" + AMT, t):
        f["min_amount"], f["max_amount"] = _amount(m.group(1), m.group(2)), _amount(m.group(3), m.group(4))
    if re.search(r"vendors? (?:with|having) (?:gstr-?2b|2b) (?:mismatch|issues?|problems?)", t):
        f["vendor_has_2b_mismatch"] = True
    elif re.search(r"missing (?:in|from) (?:gstr-?2b|2b)|not in (?:gstr-?2b|2b)", t):
        f["gstr2b"] = "missing"
    elif re.search(r"(?:gstr-?2b|2b) mismatch|mismatch(?:es)? (?:in|with) (?:gstr-?2b|2b)", t):
        f["gstr2b"] = "mismatch"
    elif re.search(r"(?:matched|found) in (?:gstr-?2b|2b)", t):
        f["gstr2b"] = "matched"
    if re.search(r"\berrors?\b|\bwrong\b|\bmistakes?\b", t):
        f["has_errors"] = True
    if re.search(r"e-?invoice (?:problem|mismatch|issue)|tamper|forged|qr (?:problem|mismatch)", t):
        f["einvoice_problem"] = True
    for w, st in STATUS_WORDS.items():
        if re.search(rf"\b{w}\b", t):
            f["status"] = st
            break
    if m := re.search(r"(\d{1,2}(?:\.\d+)?)\s*%\s*gst|gst (?:rate )?(?:of )?(\d{1,2})\s*%", t):
        f["gst_rate"] = float(m.group(1) or m.group(2))
    if "this month" in t:
        f["period"] = "this_month"
    elif "last month" in t:
        f["period"] = "last_month"
    elif "this quarter" in t:
        f["period"] = "this_quarter"
    elif "this year" in t or "this fy" in t or "financial year" in t:
        f["period"] = "this_fy"
    else:
        for name, mi in MONTHS.items():
            if re.search(rf"\b{name}\b", t):
                y = date.today().year if mi <= date.today().month else date.today().year - 1
                if ym := re.search(rf"{name}\s+(\d{{4}})", t):
                    y = int(ym.group(1))
                f["period"] = f"{y}-{mi:02d}"
    if m := re.search(r"\bfrom\s+([a-z0-9&.\- ]+?)(?=\s+(?:above|over|below|under|with|in|this|last|between|that|where|more|less)\b|\s*$)", t):
        cand = m.group(1).strip()
        if not re.match(r"^(vendors?|the|gstr|2b)\b", cand):
            f["vendor"] = cand
    if "vendor" not in f:
        for v in sorted(known_vendors, key=len, reverse=True):
            if v and v.lower() in t:
                f["vendor"] = v.lower()
                break
    return SearchFilters(**f)


def _llm_filters(text: str) -> SearchFilters | None:
    from backend.llm.explain import chat

    schema = json.dumps(SearchFilters.model_json_schema()["properties"])
    out = chat([{"role": "system", "content": "Convert the user's invoice search into a JSON object using ONLY these keys: "
                 f"{schema}. Reply with the JSON object only."},
                {"role": "user", "content": text}], max_tokens=200, retries=1)
    if not out:
        return None
    try:
        raw = json.loads(out[out.find("{"): out.rfind("}") + 1])
        return SearchFilters(**{k: v for k, v in raw.items() if v not in (None, "", False)})
    except (ValueError, ValidationError):
        return None   # anything malformed or outside the whitelist is ignored


def describe(f: SearchFilters) -> list[str]:
    d = []
    if f.vendor:
        d.append(f"vendor contains “{f.vendor}”")
    if f.min_amount is not None:
        d.append(f"total ≥ {F.inr(f.min_amount)}")
    if f.max_amount is not None:
        d.append(f"total ≤ {F.inr(f.max_amount)}")
    if f.status:
        d.append(f"status {f.status.replace('_', ' ').lower()}")
    if f.gstr2b:
        d.append({"missing": "missing from GSTR-2B", "mismatch": "GSTR-2B mismatch", "matched": "found in GSTR-2B"}[f.gstr2b])
    if f.vendor_has_2b_mismatch:
        d.append("vendor has GSTR-2B mismatches")
    if f.has_errors:
        d.append("has GST validation errors")
    if f.einvoice_problem:
        d.append("e-invoice QR problem")
    if f.gst_rate is not None:
        d.append(f"a line at {f.gst_rate:g}% GST")
    if f.period:
        d.append(F.resolve_period(f.period)["label"])
    return d


def run(db: Session, f: SearchFilters, limit: int = 200) -> list[dict]:
    period = F.resolve_period(f.period) if f.period else None
    invs = F._invoices(db, period)
    bad_vendors = set()
    if f.vendor_has_2b_mismatch:
        bad_vendors = {v["vendor_key"] for v in F.vendor_profiles(db) if v["gstr2b_mismatches"] > 0}
    rows = []
    for i in invs:
        total = float(i.grand_total or 0)
        if f.vendor and f.vendor.lower() not in (i.vendor_name_raw or "").lower() and f.vendor.lower() not in (i.vendor_gstin_raw or "").lower():
            continue
        if f.min_amount is not None and total < f.min_amount:
            continue
        if f.max_amount is not None and total > f.max_amount:
            continue
        if f.status and i.status != f.status:
            continue
        if f.gstr2b == "missing" and i.gstr2b_status != "MISSING_IN_2B":
            continue
        if f.gstr2b == "matched" and i.gstr2b_status != "IN_2B":
            continue
        if f.gstr2b == "mismatch" and i.gstr2b_status != "MISSING_IN_2B":
            rec = db.get(F.Gstr2bRecord, i.gstr2b_record_id) if i.gstr2b_record_id else None
            if not rec or rec.match_status not in ("AMOUNT_MISMATCH", "DATE_MISMATCH", "FUZZY_MATCHED"):
                continue
        if f.vendor_has_2b_mismatch and (i.vendor_gstin_raw or f"name:{(i.vendor_name_raw or 'Unknown vendor').strip()}") not in bad_vendors:
            continue
        if f.has_errors and not any(x.severity == "ERROR" and x.category == "validation" for x in i.findings):
            continue
        if f.einvoice_problem and i.einvoice_status not in ("MISMATCH", "SIGNATURE_INVALID"):
            continue
        if f.gst_rate is not None and not any(li.gst_rate is not None and float(li.gst_rate) == f.gst_rate for li in i.items):
            continue
        rows.append({"invoice_id": str(i.id), "invoice_number": i.invoice_number, "vendor": i.vendor_name_raw,
                     "invoice_date": i.invoice_date.isoformat() if i.invoice_date else None,
                     "grand_total": F.money(i.grand_total), "status": i.status, "gstr2b_status": i.gstr2b_status})
    rows.sort(key=lambda r: -r["grand_total"])
    return rows[:limit]


def smart_search(db: Session, text: str) -> dict:
    known = sorted({v["vendor_name"] for v in F.vendor_profiles(db) if v["vendor_name"]})
    f = parse_rules(text, known)
    understood_by = "rules"
    if f == SearchFilters():
        llm = _llm_filters(text)
        if llm and llm != SearchFilters():
            f, understood_by = llm, "ai (validated)"
    results = run(db, f) if f != SearchFilters() else []
    return {"query": text, "filters": f.model_dump(exclude_defaults=True), "understood_as": describe(f),
            "understood_by": understood_by, "results": results, "count": len(results),
            "note": None if f != SearchFilters() else
            "I couldn't turn that into a search. Try e.g. “invoices above 50,000 from Apex this month”."}
