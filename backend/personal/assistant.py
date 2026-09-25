"""The AI tax assistant.

Design rule, same as the rest of the system: the language model understands the
question and explains the answer; every number comes from a deterministic tool
(tax.py, bills, invoices). Each reply lists which tools produced its figures so
the user can see where a number came from.

Two modes:
  * With OPENROUTER_API_KEY: the model chooses tools (OpenAI-style tool calling).
  * Without a key: a built-in intent router answers the supported question types
    with the same tools and fixed wording. The app is fully usable either way.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date
from decimal import Decimal

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.config import get_settings
from backend.db.models import SalesInvoice, User, UserBill
from backend.personal import tax
from backend.personal.bills import CATEGORY_LABELS, DEDUCTION_HINTS, overcharges
from backend.personal.money import inr

logger = logging.getLogger(__name__)
ZERO = Decimal("0")

DISCLAIMER = ("I'm an AI assistant, not a chartered accountant. For notices, audits, disputes or large "
              "amounts, have a qualified professional review this.")


# ----------------------------------------------------------------------------- tools
def _bills(db: Session, user: User) -> list[UserBill]:
    return db.execute(select(UserBill).where(UserBill.owner_id == user.id)
                      .order_by(UserBill.created_at.desc())).scalars().all()


def tool_snapshot(db: Session, user: User, _args: dict) -> dict:
    today = date.today()
    bills = _bills(db, user)
    month = [b for b in bills if b.invoice.invoice_date and b.invoice.invoice_date.year == today.year
             and b.invoice.invoice_date.month == today.month]
    spend = lambda bs: sum(((b.invoice.grand_total or ZERO) for b in bs), ZERO)  # noqa: E731
    over = sum((Decimal(o["extra"]) for b in bills for o in overcharges(b.invoice)), ZERO)
    claimable = sum(((b.invoice.itc.eligible_itc if b.invoice.itc else ZERO) for b in bills), ZERO) \
        if user.profile_type != "individual" else None
    sales = db.execute(select(SalesInvoice).where(SalesInvoice.owner_id == user.id)).scalars().all()
    unpaid = [s for s in sales if s.status != "PAID"]
    overdue = [s for s in unpaid if s.due_date and s.due_date < today]
    warranties = [b for b in bills if b.warranty_until and 0 <= (b.warranty_until - today).days <= 60]
    by_cat: dict[str, Decimal] = {}
    for b in bills:
        by_cat[b.category] = by_cat.get(b.category, ZERO) + (b.invoice.grand_total or ZERO)
    return {
        "bills": len(bills), "spend_this_month": str(spend(month)), "spend_total": str(spend(bills)),
        "overcharged_total": str(over), "gst_claimable": str(claimable) if claimable is not None else None,
        "owed_to_you": str(sum((s.total for s in unpaid), ZERO)), "unpaid_invoices": len(unpaid),
        "overdue_invoices": len(overdue),
        "spend_by_category": [{"category": CATEGORY_LABELS.get(k, k), "amount": str(v)}
                              for k, v in sorted(by_cat.items(), key=lambda kv: -kv[1])],
        "warranties_expiring": [{"bill_id": str(b.id), "vendor": b.invoice.vendor_name_raw,
                                 "until": b.warranty_until.isoformat()} for b in warranties],
    }


def _tax_inputs(user: User, overrides: dict) -> tax.TaxInputs:
    merged = {**(user.tax_inputs or {}), **{k: v for k, v in (overrides or {}).items() if v is not None}}
    return tax.TaxInputs.from_dict(merged)


def tool_compare_regimes(db: Session, user: User, args: dict) -> dict:
    inp = _tax_inputs(user, args)
    if not (inp.salary_income or inp.business_income or inp.other_income):
        return {"needs_input": True, "message": "I need your yearly income to compare regimes."}
    return tax.compare_regimes(inp)


def tool_gst_registration(db: Session, user: User, args: dict) -> dict:
    turnover = args.get("turnover")
    if turnover is None:
        sales = db.execute(select(SalesInvoice).where(SalesInvoice.owner_id == user.id)).scalars().all()
        fy_start = date(date.today().year if date.today().month >= 4 else date.today().year - 1, 4, 1)
        turnover = float(sum((s.subtotal for s in sales if s.issue_date >= fy_start), ZERO))
        if turnover:
            turnover = turnover * 12 / max(1, (date.today() - fy_start).days / 30.4)   # annualise
    return tax.gst_registration_check(float(turnover or 0), args.get("supply_type") or
                                      ("services" if user.profile_type == "freelancer" else "goods"),
                                      user.state_code, bool(args.get("interstate_goods")),
                                      bool(args.get("ecommerce_goods")))


def tool_advance_tax(db: Session, user: User, args: dict) -> dict:
    inp = _tax_inputs(user, args)
    cmp = tax.compare_regimes(inp)
    best = cmp[cmp["better"]]["total_tax"]
    return {**tax.advance_tax_schedule(best, inp.tds_paid, date.today(), bool(args.get("presumptive"))),
            "based_on": f"{cmp['better']} regime tax of {inr(best)}"}


def tool_presumptive(db: Session, user: User, args: dict) -> dict:
    return tax.presumptive_income(args.get("scheme") or "44ADA", float(args.get("receipts") or 0),
                                  float(args.get("digital_share") or 1.0))


def tool_deadlines(db: Session, user: User, _args: dict) -> dict:
    return {"deadlines": tax.upcoming_deadlines(user.profile_type, date.today(), bool(user.gstin))}


def tool_search_bills(db: Session, user: User, args: dict) -> dict:
    q = (args.get("query") or "").lower()
    out = []
    for b in _bills(db, user):
        inv = b.invoice
        hay = " ".join([inv.vendor_name_raw or "", inv.invoice_number or "", b.category, b.note or ""] +
                       [li.description or "" for li in inv.items]).lower()
        if not q or all(w in hay for w in q.split()):
            out.append({"bill_id": str(b.id), "vendor": inv.vendor_name_raw, "date": inv.invoice_date.isoformat()
                        if inv.invoice_date else None, "total": str(inv.grand_total or 0),
                        "category": CATEGORY_LABELS.get(b.category, b.category)})
    return {"matches": out[:10], "count": len(out)}


def tool_unpaid_invoices(db: Session, user: User, _args: dict) -> dict:
    today = date.today()
    rows = db.execute(select(SalesInvoice).where(SalesInvoice.owner_id == user.id, SalesInvoice.status != "PAID")
                      .order_by(SalesInvoice.due_date)).scalars().all()
    return {"invoices": [{"id": str(s.id), "number": s.number, "client": s.client_name, "total": str(s.total),
                          "due_date": s.due_date.isoformat() if s.due_date else None,
                          "days_overdue": (today - s.due_date).days if s.due_date and s.due_date < today else 0}
                         for s in rows],
            "total": str(sum((s.total for s in rows), ZERO))}


def tool_deduction_hints(db: Session, user: User, _args: dict) -> dict:
    found = {}
    for b in _bills(db, user):
        if b.category in DEDUCTION_HINTS:
            found.setdefault(b.category, ZERO)
            found[b.category] += b.invoice.grand_total or ZERO
    return {"hints": [{"category": CATEGORY_LABELS[c], "amount": str(v), "hint": DEDUCTION_HINTS[c]}
                      for c, v in found.items()]}


TOOLS = {
    "financial_snapshot": (tool_snapshot, "Overview of the user's bills, spending, overcharges, GST claimable, money owed and warranties.", {}),
    "compare_tax_regimes": (tool_compare_regimes, "Compare income tax under the old and new regimes. Missing inputs come from the user's saved tax profile.", {
        "salary_income": {"type": "number"}, "business_income": {"type": "number"}, "other_income": {"type": "number"},
        "sec_80c": {"type": "number"}, "sec_80d_self": {"type": "number"}, "home_loan_interest": {"type": "number"},
        "hra_exempt": {"type": "number"}, "age_band": {"type": "string", "enum": ["below_60", "60_to_80", "above_80"]}}),
    "check_gst_registration": (tool_gst_registration, "Whether the user must register for GST.", {
        "turnover": {"type": "number", "description": "Yearly turnover in rupees; omit to estimate from their invoices"},
        "supply_type": {"type": "string", "enum": ["goods", "services"]},
        "interstate_goods": {"type": "boolean"}, "ecommerce_goods": {"type": "boolean"}}),
    "advance_tax_plan": (tool_advance_tax, "Advance tax instalments and amounts for this financial year.", {
        "presumptive": {"type": "boolean"}}),
    "presumptive_income": (tool_presumptive, "Income under presumptive taxation (44ADA professionals, 44AD small business).", {
        "scheme": {"type": "string", "enum": ["44ADA", "44AD"]}, "receipts": {"type": "number"},
        "digital_share": {"type": "number", "description": "0..1 share of receipts received digitally"}}),
    "upcoming_deadlines": (tool_deadlines, "The user's next tax and GST deadlines.", {}),
    "search_bills": (tool_search_bills, "Find bills in the user's wallet by words (vendor, item, category).", {
        "query": {"type": "string"}}),
    "unpaid_invoices": (tool_unpaid_invoices, "Invoices the user sent that customers haven't paid.", {}),
    "deduction_hints": (tool_deduction_hints, "Bills that may reduce income tax (health insurance, tuition…).", {}),
}


def run_tool(db: Session, user: User, name: str, args: dict) -> dict:
    fn = TOOLS[name][0]
    try:
        return fn(db, user, args or {})
    except Exception as exc:  # noqa: BLE001 - a tool failure becomes a message, never a crash
        logger.exception("tool %s failed", name)
        return {"error": f"Could not compute this: {exc}"}


# ----------------------------------------------------------------------------- offline mode
NUM = r"(\d[\d,]*(?:\.\d+)?)\s*(lakh|lac|l|crore|cr|k)?"


def _amount(text: str) -> float | None:
    m = re.search(NUM, text.lower().replace("₹", "").replace("rs.", "").replace("rs ", ""))
    if not m:
        return None
    n = float(m.group(1).replace(",", ""))
    mult = {"lakh": 1e5, "lac": 1e5, "l": 1e5, "crore": 1e7, "cr": 1e7, "k": 1e3}.get(m.group(2) or "", 1)
    return n * mult


INTENTS = [
    ("compare_tax_regimes", r"regime|income tax|how much tax|my tax|tax (?:do|will|should) i"),
    ("check_gst_registration", r"gst regist|register for gst|need gst|gstin"),
    ("advance_tax_plan", r"advance tax|instal+ment"),
    ("presumptive_income", r"44ada|44ad|presumptive"),
    ("upcoming_deadlines", r"deadline|due date|when .*(file|pay)|last date"),
    ("unpaid_invoices", r"owe|unpaid|pending payment|not paid|who hasn"),
    ("deduction_hints", r"deduct|save tax|80c|80d|claim.*tax"),
    ("search_bills", r"find|show|where.*bill|my bills?\b|receipt"),
    ("financial_snapshot", r"overview|summary|spend|spent|overcharg|how am i doing|snapshot|warrant"),
]


def _offline(db: Session, user: User, message: str) -> tuple[str, list[dict]]:
    text = message.lower()
    for name, pattern in INTENTS:
        if re.search(pattern, text):
            args: dict = {}
            amt = _amount(text)
            if name == "compare_tax_regimes" and amt:
                args["salary_income"] = amt
            if name == "check_gst_registration":
                if amt:
                    args["turnover"] = amt
                if "service" in text or "freelanc" in text:
                    args["supply_type"] = "services"
                elif "goods" in text or "product" in text:
                    args["supply_type"] = "goods"
            if name == "presumptive_income":
                args["scheme"] = "44AD" if re.search(r"44ad\b", text) else "44ADA"
                if amt:
                    args["receipts"] = amt
            if name == "search_bills":
                args["query"] = re.sub(r"\b(find|show|me|my|bills?|receipts?|where|is|are|the|for|from)\b", " ", text).strip()
            result = run_tool(db, user, name, args)
            return _template(name, result), [{"tool": name, "args": args, "result": result}]
    snap = run_tool(db, user, "financial_snapshot", {})
    return ("I can help with: comparing tax regimes, GST registration, advance tax, deadlines, finding bills, "
            "overcharges, money clients owe you and tax-saving deductions. Try one of the suggestions below. "
            f"Right now you have {snap['bills']} bills saved."), [{"tool": "financial_snapshot", "args": {}, "result": snap}]


def _template(name: str, r: dict) -> str:
    if r.get("error"):
        return r["error"]
    if name == "compare_tax_regimes":
        if r.get("needs_input"):
            return "Tell me your yearly income (e.g. \"my salary is 14 lakh\"), or fill in the Tax planner, and I'll compare both regimes."
        o, n = r["old"], r["new"]
        return (f"{r['summary']} Under the new regime you'd pay {inr(n['total_tax'])}; under the old regime "
                f"{inr(o['total_tax'])} (FY {r['financial_year']}). Open the Tax planner to add deductions like 80C or 80D.")
    if name == "check_gst_registration":
        verdict = "Yes, you need to register for GST." if r["required"] else "No, you don't need GST registration yet."
        room = "" if r["required"] else f"You have {inr(r['headroom'])} of room left. "
        return f"{verdict} {' '.join(r['reasons'])} {room}{r['note']}"
    if name == "advance_tax_plan":
        if not r["required"]:
            return r["note"]
        nxt = next((i for i in r["instalments"] if i["status"] == "upcoming"), None)
        s = f"Your estimated tax still to pay is {inr(r['liability'])} ({r['based_on']})."
        if nxt:
            s += f" Next instalment: {inr(nxt['pay_now'])} by {nxt['due_date']}."
        return s + " " + r["note"]
    if name == "presumptive_income":
        return (f"Under {r['label']}, receipts of {inr(r['receipts'])} give a taxable income of "
                f"{inr(r['deemed_income'])}. {r['note']}") if r["receipts"] else \
            f"{r['label']}: {r['note']} Tell me your yearly receipts and I'll work out the income."
    if name == "upcoming_deadlines":
        d = r["deadlines"][:4]
        return "Your next deadlines: " + "; ".join(f"{x['title']} on {x['date']} ({x['days_left']} days)" for x in d) + "."
    if name == "unpaid_invoices":
        inv = r["invoices"]
        if not inv:
            return "Nobody owes you money right now. 🎉"
        late = [i for i in inv if i["days_overdue"]]
        return (f"{len(inv)} invoice{'s' if len(inv) > 1 else ''} unpaid, {inr(r['total'])} in total"
                + (f"; {len(late)} overdue — oldest {late[0]['client']} ({late[0]['days_overdue']} days)." if late else "."))
    if name == "deduction_hints":
        h = r["hints"]
        return " ".join(f"{x['category']}: {inr(x['amount'])} of bills. {x['hint']}" for x in h) if h else \
            "I didn't find bills that reduce income tax yet. Health insurance and tuition fee receipts are the usual ones."
    if name == "search_bills":
        m = r["matches"]
        return f"I found {r['count']} bill{'s' if r['count'] != 1 else ''}." + (
            " " + "; ".join(f"{x['vendor'] or 'Unknown'} {inr(x['total'])} ({x['date']})" for x in m[:5]) if m else "")
    if name == "financial_snapshot":
        s = f"You have {r['bills']} bills saved, {inr(r['spend_this_month'])} spent this month."
        if Decimal(r["overcharged_total"]) > 0:
            s += f" I found {inr(r['overcharged_total'])} of possible GST overcharges."
        if r["gst_claimable"] is not None:
            s += f" GST you can claim back: {inr(r['gst_claimable'])}."
        if Decimal(r["owed_to_you"]) > 0:
            s += f" Clients owe you {inr(r['owed_to_you'])}."
        return s
    return json.dumps(r)[:500]


# ----------------------------------------------------------------------------- LLM mode
SYSTEM = """You are a friendly AI tax and money assistant for people in India: salaried individuals,
shop owners and freelancers. Speak simply, like a helpful accountant friend. Keep answers short.

Hard rules:
- NEVER calculate tax, GST or any amount yourself. Always call a tool and use only numbers it returns.
- If a tool says it needs input, ask the user for exactly that input.
- If the question is outside the tools (legal disputes, notices needing a reply, audits, foreign income,
  capital gains, company law), say you can't handle it reliably and recommend a qualified CA.
- Use Indian number formatting (₹12,34,567). Mention the financial year when giving tax figures.
User profile: {profile}. Today is {today}."""


def _openai_tools() -> list[dict]:
    return [{"type": "function", "function": {"name": n, "description": d,
             "parameters": {"type": "object", "properties": props}}} for n, (_, d, props) in TOOLS.items()]


def _llm(db: Session, user: User, message: str, history: list[dict]) -> tuple[str, list[dict]]:
    s = get_settings()
    profile = {"name": user.name, "type": user.profile_type, "state": user.state_code,
               "gst_registered": bool(user.gstin), "has_tax_profile": bool(user.tax_inputs)}
    msgs = [{"role": "system", "content": SYSTEM.format(profile=json.dumps(profile), today=date.today())}]
    msgs += history[-8:] + [{"role": "user", "content": message}]
    used: list[dict] = []
    for _ in range(4):
        resp = httpx.post(f"{s.openrouter_base_url}/chat/completions", timeout=s.llm_timeout_s,
                          headers={"Authorization": f"Bearer {s.openrouter_api_key}"},
                          json={"model": s.assistant_model, "messages": msgs, "tools": _openai_tools(),
                                "temperature": 0.2, "max_tokens": 700})
        resp.raise_for_status()
        choice = resp.json()["choices"][0]["message"]
        calls = choice.get("tool_calls") or []
        if not calls:
            return (choice.get("content") or "").strip(), used
        msgs.append({"role": "assistant", "content": choice.get("content") or "", "tool_calls": calls})
        for c in calls:
            name = c["function"]["name"]
            args = json.loads(c["function"].get("arguments") or "{}")
            result = run_tool(db, user, name, args) if name in TOOLS else {"error": "unknown tool"}
            used.append({"tool": name, "args": args, "result": result})
            msgs.append({"role": "tool", "tool_call_id": c["id"], "content": json.dumps(result, default=str)})
    return "I couldn't finish that — please try asking in a simpler way.", used


def answer(db: Session, user: User, message: str, history: list[dict]) -> dict:
    s = get_settings()
    mode = "offline"
    if s.openrouter_api_key and s.llm_enabled:
        try:
            reply, used = _llm(db, user, message, history)
            mode = "ai"
        except Exception as exc:  # noqa: BLE001 - fall back to the offline router
            logger.warning("Assistant LLM failed, using offline router: %s", exc)
            reply, used = _offline(db, user, message)
    else:
        reply, used = _offline(db, user, message)
    return {"reply": reply, "mode": mode, "tools": used, "disclaimer": DISCLAIMER}


SUGGESTIONS = {
    "individual": ["Old or new tax regime for me?", "How much did I spend this month?",
                   "Which bills can save me tax?", "Was I overcharged on any bill?"],
    "business": ["Do I need GST registration?", "How much GST can I claim back?",
                 "When is my next GST deadline?", "Who hasn't paid me?"],
    "freelancer": ["Who hasn't paid me?", "Do I need GST registration for 18 lakh of services?",
                   "How much advance tax should I pay?", "What is 44ADA and should I use it?"],
}
