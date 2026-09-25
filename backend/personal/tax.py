"""Deterministic Indian tax calculators. Pure functions; the assistant calls these,
it never does tax arithmetic itself.

All figures come from data/tax/rules_india.json. Every result carries the rule
set's financial year and plain-language notes, so the UI and the assistant can
show *why*, not just *what*.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date
from functools import lru_cache
from pathlib import Path

from backend.config import get_settings
from backend.personal.money import inr

DEFAULT_RULES = Path(__file__).resolve().parents[2] / "data" / "tax" / "rules_india.json"


@lru_cache(maxsize=1)
def rules() -> dict:
    return json.loads(Path(get_settings().tax_rules_path or DEFAULT_RULES).read_text())


def _r(x: float) -> int:
    return int(round(x))


# ------------------------------------------------------------------ income tax
@dataclass
class TaxInputs:
    age_band: str = "below_60"          # below_60 / 60_to_80 / above_80
    salary_income: float = 0            # gross salary (standard deduction applies)
    business_income: float = 0          # profit from business/profession (after presumptive calc if used)
    other_income: float = 0             # interest, rent, etc.
    sec_80c: float = 0
    sec_80d_self: float = 0
    sec_80d_parents: float = 0
    parents_senior: bool = False
    sec_80ccd_1b: float = 0
    home_loan_interest: float = 0
    hra_exempt: float = 0
    sec_80tta: float = 0
    tds_paid: float = 0

    @classmethod
    def from_dict(cls, d: dict) -> "TaxInputs":
        known = {k: d[k] for k in cls.__dataclass_fields__ if k in d and d[k] not in (None, "")}
        for k, v in list(known.items()):
            if k not in ("age_band", "parents_senior"):
                known[k] = max(0.0, float(v))
        if "parents_senior" in known:
            known["parents_senior"] = bool(known["parents_senior"])
        return cls(**known)


@dataclass
class RegimeResult:
    regime: str
    label: str
    gross_income: int
    standard_deduction: int
    deductions: list[dict] = field(default_factory=list)
    taxable_income: int = 0
    tax_on_slabs: int = 0
    rebate: int = 0
    marginal_relief: int = 0
    cess: int = 0
    total_tax: int = 0
    slab_breakdown: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _slab_tax(income: float, slabs: list) -> tuple[float, list[dict]]:
    tax, lower, parts = 0.0, 0.0, []
    for upper, rate in slabs:
        top = income if upper is None else min(income, upper)
        if top > lower:
            portion = top - lower
            t = portion * rate / 100
            parts.append({"from": _r(lower), "to": None if upper is None else _r(upper), "rate": rate,
                          "amount": _r(portion), "tax": _r(t)})
            tax += t
        if upper is None or income <= upper:
            break
        lower = upper
    return tax, parts


def compute_regime(regime: str, inp: TaxInputs) -> RegimeResult:
    R = rules()
    cfg = R["regimes"][regime]
    caps = R["deduction_caps"]
    senior = inp.age_band in ("60_to_80", "above_80")
    gross = inp.salary_income + inp.business_income + inp.other_income
    std = min(cfg["standard_deduction"], inp.salary_income)
    res = RegimeResult(regime, cfg["label"], _r(gross), _r(std))

    total_ded = 0.0
    for key in cfg["allowed_deductions"]:
        claimed = getattr(inp, key, 0) or 0
        if not claimed:
            continue
        cap = caps[key].get("cap")
        if key == "sec_80d_self" and senior:
            cap = caps[key]["cap_senior"]
        if key == "sec_80d_parents" and inp.parents_senior:
            cap = caps[key]["cap_senior_parents"]
        allowed = claimed if cap is None else min(claimed, cap)
        total_ded += allowed
        res.deductions.append({"key": key, "label": caps[key]["label"], "claimed": _r(claimed), "allowed": _r(allowed)})
        if cap is not None and claimed > cap:
            res.notes.append(f"{caps[key]['label']}: only {inr(cap)} of {inr(_r(claimed))} counts (limit).")

    taxable = max(0.0, gross - std - total_ded)
    res.taxable_income = _r(taxable)
    slabs = cfg["slabs"]
    if regime == "old" and inp.age_band == "60_to_80":
        slabs = cfg["slabs_senior"]
    elif regime == "old" and inp.age_band == "above_80":
        slabs = cfg["slabs_super_senior"]
    tax, parts = _slab_tax(taxable, slabs)
    res.tax_on_slabs, res.slab_breakdown = _r(tax), parts

    if taxable <= cfg["rebate_limit"]:
        res.rebate = _r(min(tax, cfg["rebate_max"]))
        if res.rebate:
            res.notes.append(f"Section 87A rebate applies because taxable income is within {inr(cfg['rebate_limit'])}.")
    elif cfg.get("marginal_relief"):
        excess = taxable - cfg["rebate_limit"]
        if tax > excess:   # tax cannot exceed the income earned above the rebate limit
            res.marginal_relief = _r(tax - excess)
            res.notes.append("Marginal relief applies: your tax is capped at the income above the rebate limit.")
    after = max(0, res.tax_on_slabs - res.rebate - res.marginal_relief)
    res.cess = _r(after * R["cess_rate"] / 100)
    res.total_tax = after + res.cess
    if gross > R["surcharge_threshold"]:
        res.notes.append("Income above ₹50 lakh attracts a surcharge, which this calculator does not include. "
                         "Get a professional review.")
    return res


def compare_regimes(inp: TaxInputs) -> dict:
    old, new = compute_regime("old", inp), compute_regime("new", inp)
    better = "new" if new.total_tax <= old.total_tax else "old"
    saving = abs(old.total_tax - new.total_tax)
    return {"financial_year": rules()["financial_year"], "old": asdict(old), "new": asdict(new),
            "better": better, "saving": saving,
            "summary": (f"The {'new' if better == 'new' else 'old'} regime is better for you by {inr(saving)}."
                        if saving else "Both regimes give the same tax for you."),
            "balance_payable": max(0, min(old.total_tax, new.total_tax) - _r(inp.tds_paid))}


# ------------------------------------------------------------------ GST registration
def gst_registration_check(turnover: float, supply_type: str, state_code: str | None,
                           interstate_goods: bool = False, ecommerce_goods: bool = False) -> dict:
    g = rules()["gst_registration"]
    sc = (state_code or "").zfill(2) if state_code else ""
    if supply_type == "services":
        limit = g["services_threshold_special"] if sc in g["special_category_states_services"] else g["services_threshold"]
    else:
        limit = (g["goods_threshold_10l_states"] and sc in g["goods_threshold_10l_states"] and 1000000) or \
                (sc in g["goods_threshold_20l_states"] and 2000000) or g["goods_threshold"]
    reasons = []
    required = turnover > limit
    if required:
        reasons.append(f"Your yearly turnover {inr(_r(turnover))} is above the {inr(limit)} limit for {supply_type}.")
    else:
        reasons.append(f"Your yearly turnover {inr(_r(turnover))} is within the {inr(limit)} limit for {supply_type}.")
    if supply_type == "goods" and interstate_goods:
        required = True
        reasons.append("You sell goods to other states, which needs GST registration at any turnover.")
    if supply_type == "goods" and ecommerce_goods:
        required = True
        reasons.append("You sell goods through e-commerce marketplaces, which generally needs registration.")
    headroom = max(0, limit - _r(turnover))
    return {"required": required, "threshold": limit, "turnover": _r(turnover), "headroom": headroom,
            "reasons": reasons, "note": "Voluntary registration is allowed even below the limit, and lets you claim GST credit."}


# ------------------------------------------------------------------ presumptive income & advance tax
def presumptive_income(scheme: str, receipts: float, digital_share: float = 1.0) -> dict:
    p = rules()["presumptive"][scheme]
    mostly_digital = digital_share >= 0.95
    limit = p["limit_if_mostly_digital"] if mostly_digital else p["limit"]
    if scheme == "44ADA":
        pct = p["deemed_percent"]
        income = receipts * pct / 100
    else:
        pct = None
        income = receipts * digital_share * p["deemed_percent_digital"] / 100 + \
            receipts * (1 - digital_share) * p["deemed_percent_cash"] / 100
    eligible = receipts <= limit
    return {"scheme": scheme, "label": p["label"], "eligible": eligible, "limit": limit, "receipts": _r(receipts),
            "deemed_income": _r(income), "deemed_percent": pct,
            "note": (f"You can declare {pct}% of receipts as income without keeping detailed books."
                     if scheme == "44ADA" else "You can declare 6% of digital and 8% of cash turnover as income.")
            if eligible else f"Receipts exceed the {inr(limit)} limit, so this scheme is not available."}


def advance_tax_schedule(total_tax: float, tds_paid: float, today: date, presumptive: bool = False) -> dict:
    a = rules()["advance_tax"]
    liability = max(0, _r(total_tax - tds_paid))
    fy_start = today.year if today.month >= 4 else today.year - 1
    if liability < a["min_liability"]:
        return {"required": False, "liability": liability, "instalments": [],
                "note": f"Advance tax is only needed when tax after TDS is {inr(a['min_liability'])} or more."}
    plan = [a["presumptive_single"]] if presumptive else a["instalments"]
    out, prev = [], 0
    for mmdd, pct in plan:
        m, d = map(int, mmdd.split("-"))
        due = date(fy_start + (1 if m < 4 else 0), m, d)
        cumulative = _r(liability * pct / 100)
        out.append({"due_date": due.isoformat(), "cumulative_percent": pct, "pay_now": cumulative - prev,
                    "cumulative": cumulative, "status": "past" if due < today else "upcoming"})
        prev = cumulative
    return {"required": True, "liability": liability, "instalments": out,
            "note": "Missing an instalment adds interest (sections 234B/234C)."}


# ------------------------------------------------------------------ deadlines
def upcoming_deadlines(profile_type: str, today: date, gst_registered: bool, limit: int = 8) -> list[dict]:
    R = rules()
    items: list[dict] = []
    fy_start = today.year if today.month >= 4 else today.year - 1
    for yr in (fy_start, fy_start + 1):
        m, d = map(int, R["deadlines"]["itr_non_audit"].split("-"))
        items.append({"date": date(yr, m, d), "title": "Income tax return due",
                      "detail": f"ITR for FY {yr - 1}-{str(yr)[2:]} (if no audit is needed)", "kind": "income_tax"})
    if profile_type in ("freelancer", "business"):
        for mmdd, pct in R["advance_tax"]["instalments"]:
            m, d = map(int, mmdd.split("-"))
            for base in (fy_start, fy_start + 1):
                items.append({"date": date(base + (1 if m < 4 else 0), m, d), "title": "Advance tax instalment",
                              "detail": f"Pay up to {pct}% of the year's tax", "kind": "advance_tax"})
    if gst_registered:
        for k in range(0, 3):
            mm = (today.month - 1 + k) % 12 + 1
            yy = today.year + (today.month - 1 + k) // 12
            items.append({"date": date(yy, mm, R["deadlines"]["gstr1_monthly_day"]), "title": "GSTR-1 due",
                          "detail": "Report last month's sales", "kind": "gst"})
            items.append({"date": date(yy, mm, R["deadlines"]["gstr3b_monthly_day"]), "title": "GSTR-3B due",
                          "detail": "Pay last month's GST", "kind": "gst"})
    seen, out = set(), []
    for it in sorted(items, key=lambda x: x["date"]):
        key = (it["date"], it["title"])
        if it["date"] >= today and key not in seen:
            seen.add(key)
            out.append({**it, "date": it["date"].isoformat(), "days_left": (it["date"] - today).days})
    return out[:limit]
