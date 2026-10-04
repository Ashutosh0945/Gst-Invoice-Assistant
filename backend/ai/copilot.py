"""AI GST Copilot and AI CFO Business Brief.

Flow for every question:  detect intent (rules)  ->  run a fixed, read-only query from
facts.py  ->  build a rule-written answer  ->  let OpenRouter re-word it from the same
facts  ->  fact-check every number (explain_facts). Data cards are always the raw facts,
so the user can see exactly where each number came from.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from backend.ai import facts as F
from backend.ai import search as S
from backend.llm.explain import explain_facts

SUGGESTIONS = [
    "Give me this month's GST summary",
    "How much ITC is currently at risk?",
    "Which vendor has the most GST errors?",
    "Show invoices with GSTR-2B mismatches",
    "Which vendors need attention?",
    "What needs my attention right now?",
]

INTENTS = [  # order matters: first match wins
    ("search", r"invoices?\b.*\b(?:above|over|below|under|between|more than|less than|greater than)\s*(?:₹|rs\.?)?\s*\d"),
    ("investigate", r"\b(?:investigate|explain|check|tell me about)\b.*\binvoice\b\s+([A-Z0-9][A-Z0-9/\-]{2,})"),
    ("vendor_errors", r"vendor.*(?:most|highest|top|max).*(?:error|mistake|issue)|(?:most|highest).*(?:error|mistake).*vendor"),
    ("vendors_attention", r"vendors?.*(?:attention|risk|risky|problem|watch|worst)|(?:risky|problem) vendors?"),
    ("itc_at_risk", r"\bitc\b.*(?:risk|stuck|lost|losing|block|hold)|(?:risk|stuck|blocked).*\bitc\b|credit at risk|input tax credit"),
    ("gstr2b_mismatches", r"(?:gstr-?2b|\b2b\b).*(?:mismatch|missing|not|issue|difference)|(?:mismatch|missing).*(?:gstr-?2b|\b2b\b)"),
    ("anomalies", r"anomal|unusual|suspicious|fraud|odd|strange"),
    ("risks", r"attention|priorit|urgent|what should i|issues|problems|risk"),
    ("search", r"^(?:show|find|list|get|search|which invoices)\b|invoices? (?:above|over|below|under|from|with|between)"),
    ("summary", r"summary|overview|how (?:are|is) (?:we|my|the business)|total|spent|purchase|gst (?:paid|amount)|this month|last month|kpi"),
]


def _period_from(text: str) -> str | None:
    t = text.lower()
    for k, v in (("last month", "last_month"), ("this month", "this_month"), ("this quarter", "this_quarter"),
                 ("this year", "this_fy"), ("financial year", "this_fy"), ("last 90 days", "last_90_days"),
                 ("all time", "all"), ("overall", "all")):
        if k in t:
            return v
    return None


FOLLOW_UP = r"^\s*(?:what|how) about\b|^\s*and\b|^\s*(?:same|now) (?:for|but)\b|^\s*for (?:last|this) (?:month|quarter|year)"


def detect(text: str, context: dict | None) -> tuple[str, dict]:
    if context and context.get("intent") not in (None, "help") and re.search(FOLLOW_UP, text, re.I):
        return context["intent"], dict(context.get("params") or {})
    for name, pat in INTENTS:
        m = re.search(pat, text, re.I)
        if m:
            params = {"invoice_ref": m.group(1)} if name == "investigate" else {}
            return name, params
    if context and context.get("intent"):   # follow-up like "what about last month?" or "and for Apex?"
        return context["intent"], dict(context.get("params") or {})
    return "help", {}


def _table(title, columns, rows, link=None):
    return {"type": "table", "title": title, "columns": columns, "rows": rows, "link": link}


def answer(db: Session, message: str, history: list[dict] | None = None, context: dict | None = None) -> dict:
    intent, params = detect(message, context)
    period_key = _period_from(message) or (context or {}).get("period") if intent != "help" else None
    if intent in ("summary",) and not period_key:
        period_key = "this_month" if "month" in message.lower() else "all"
    facts: dict = {}
    cards: list[dict] = []
    followups: list[str] = []
    rule_text = ""

    if intent == "summary":
        k = F.kpis(db, period_key)
        facts = {"kpis": k}
        p = k["period"]["label"]
        if not k["total_invoices"]:
            rule_text = f"There are no invoices for {p} yet, so there's no GST summary to show."
        else:
            rule_text = (f"{p}: {k['total_invoices']} invoices worth {F.inr(k['total_purchase_value'])}, with "
                         f"{F.inr(k['gst_amount'])} GST. Claimable ITC is {F.inr(k['itc_eligible'])} and "
                         f"{F.inr(k['itc_at_risk'])} is at risk. {k['needs_review']} invoices need review and "
                         f"{k['gstr2b_mismatches']} have GSTR-2B mismatches.")
        cards.append({"type": "kpis", "title": f"GST summary · {p}", "items": [
            ["Invoices", k["total_invoices"]], ["Purchase value", F.inr(k["total_purchase_value"])],
            ["GST", F.inr(k["gst_amount"])], ["ITC claimable", F.inr(k["itc_eligible"])],
            ["ITC at risk", F.inr(k["itc_at_risk"])], ["GSTR-2B mismatches", k["gstr2b_mismatches"]]]})
        followups = ["How much ITC is at risk?", "What about last month?", "Which vendors need attention?"]
    elif intent == "itc_at_risk":
        k = F.kpis(db, period_key)
        risky = [r for r in F.risk_items(db) if r["category"] in ("ITC", "GSTR-2B") and r["invoice_id"]][:10]
        facts = {"itc_at_risk": k["itc_at_risk"], "itc_eligible": k["itc_eligible"], "itc_blocked": k["itc_blocked"],
                 "period": k["period"]["label"], "invoices_missing_in_2b": k["invoices_missing_in_2b"],
                 "top_items": [{k2: r[k2] for k2 in ("invoice_number", "vendor", "title", "amount_at_stake")} for r in risky]}
        rule_text = (f"{F.inr(k['itc_at_risk'])} of input tax credit is at risk ({k['period']['label']}). "
                     f"{k['invoices_missing_in_2b']} invoices are missing from GSTR-2B. Claimable now: {F.inr(k['itc_eligible'])}; "
                     f"blocked by law: {F.inr(k['itc_blocked'])}.") if k["total_invoices"] else "There are no invoices yet."
        cards.append(_table("Where the ITC is at risk", ["Invoice", "Vendor", "Issue", "Amount"],
                            [[r["invoice_number"], r["vendor"], r["title"], F.inr(r["amount_at_stake"])] for r in risky], "/itc"))
        cards[-1]["row_links"] = [f"/invoices/{r['invoice_id']}" for r in risky]
        followups = ["Show invoices missing from GSTR-2B", "Which vendors need attention?"]
    elif intent in ("vendor_errors", "vendors_attention"):
        vp = F.vendor_profiles(db, period_key)
        key = "gst_errors" if intent == "vendor_errors" else "attention_score"
        top = [v for v in sorted(vp, key=lambda v: -v[key]) if v[key] > 0][:5]
        facts = {"ranked_by": key, "vendors": [{k2: v[k2] for k2 in ("vendor_name", "vendor_gstin", "invoice_count", "purchase_value",
                 "gst_errors", "gstr2b_mismatches", "itc_at_risk", "einvoice_problems", "filing_rate_pct")} for v in top]}
        if not vp:
            rule_text = "There are no vendors yet."
        elif not top:
            rule_text = "No vendor has GST errors right now." if intent == "vendor_errors" else "No vendor needs special attention right now."
        else:
            v = top[0]
            rule_text = (f"{v['vendor_name']} has the most GST errors: {v['gst_errors']} across {v['invoice_count']} invoices."
                         if intent == "vendor_errors" else
                         f"{v['vendor_name']} needs the most attention: {v['gst_errors']} GST errors, {v['gstr2b_mismatches']} "
                         f"GSTR-2B mismatches and {F.inr(v['itc_at_risk'])} ITC at risk.")
        cards.append(_table("Vendors", ["Vendor", "Invoices", "GST errors", "2B mismatches", "ITC at risk"],
                            [[v["vendor_name"], v["invoice_count"], v["gst_errors"], v["gstr2b_mismatches"], F.inr(v["itc_at_risk"])] for v in top], "/vendors"))
        cards[-1]["row_links"] = [f"/invoices?q={(v['vendor_gstin'] or v['vendor_name'])}" for v in top]
        followups = ["Show invoices with GSTR-2B mismatches", "What needs my attention right now?"]
    elif intent == "gstr2b_mismatches":
        items = [r for r in F.risk_items(db) if r["category"] == "GSTR-2B"][:15]
        k = F.kpis(db, period_key)
        facts = {"gstr2b_imported": k["gstr2b_imported"], "mismatch_count": len(items),
                 "items": [{k2: r[k2] for k2 in ("title", "invoice_number", "vendor", "reason", "amount_at_stake")} for r in items]}
        rule_text = ("No GSTR-2B has been imported yet, so there's nothing to compare. Import it on the GSTR-2B page."
                     if not k["gstr2b_imported"] else f"{len(items)} GSTR-2B mismatches found." if items else "No GSTR-2B mismatches.")
        cards.append(_table("GSTR-2B mismatches", ["Issue", "Invoice", "Vendor", "Reason", "Tax"],
                            [[r["title"], r["invoice_number"] or "—", r["vendor"], r["reason"], F.inr(r["amount_at_stake"])] for r in items], "/gstr2b"))
        cards[-1]["row_links"] = [f"/invoices/{r['invoice_id']}" if r["invoice_id"] else "/gstr2b" for r in items]
        followups = ["How much ITC is at risk?", "Draft a message to the vendor"]
    elif intent == "anomalies":
        an = F.anomalies(db)
        top = an["items"][:10]
        facts = {"count": len(an["items"]), "items": top, "note": an["note"]}
        rule_text = (f"{len(an['items'])} unusual invoices found. These are risk indicators, not proof of fraud."
                     if an["items"] else "Nothing unusual found compared with your history.")
        cards.append(_table("Unusual invoices (risk indicators)", ["Invoice", "Vendor", "Why", "Score"],
                            [[x["invoice_number"], x["vendor"], x["reason"], x["score"]] for x in top], "/risk"))
        cards[-1]["row_links"] = [f"/invoices/{x['invoice_id']}" for x in top]
    elif intent == "risks":
        items = F.risk_items(db)
        counts = {s: sum(1 for x in items if x["severity"] == s) for s in ("Critical", "High", "Review")}
        facts = {"counts": counts, "top": [{k2: x[k2] for k2 in ("severity", "title", "invoice_number", "vendor", "next_action")} for x in items[:8]]}
        rule_text = (f"{counts['Critical']} critical, {counts['High']} high and {counts['Review']} review items. "
                     + (f"Start with: {items[0]['title']} ({items[0]['invoice_number'] or items[0]['vendor']})." if items else "")
                     if items else "Nothing needs your attention right now.")
        cards.append(_table("What needs your attention", ["Severity", "Issue", "Invoice / vendor", "Next step"],
                            [[x["severity"], x["title"], x["invoice_number"] or x["vendor"], x["next_action"]] for x in items[:8]], "/risk"))
        cards[-1]["row_links"] = [f"/invoices/{x['invoice_id']}" if x["invoice_id"] else "/risk" for x in items[:8]]
    elif intent == "search":
        res = S.smart_search(db, message)
        facts = {"understood_as": res["understood_as"], "count": res["count"],
                 "top": res["results"][:10]}
        rule_text = (res["note"] or f"Found {res['count']} invoice{'s' if res['count'] != 1 else ''} "
                     f"({'; '.join(res['understood_as'])}).")
        cards.append(_table("Matching invoices", ["Invoice", "Vendor", "Date", "Total", "Status"],
                            [[r["invoice_number"], r["vendor"], r["invoice_date"], F.inr(r["grand_total"]), r["status"]] for r in res["results"][:25]]))
        cards[-1]["row_links"] = [f"/invoices/{r['invoice_id']}" for r in res["results"][:25]]
    elif intent == "investigate":
        ref = params.get("invoice_ref", "")
        from sqlalchemy import select

        from backend.db.models import Invoice
        inv = db.execute(select(Invoice).where(Invoice.invoice_number == ref)).scalars().first()
        if not inv:
            rule_text = f"I couldn't find an invoice numbered {ref}."
        else:
            inv_facts = F.investigate(db, inv.id)
            facts = {"invoice": inv_facts["invoice"], "verdict": inv_facts["verdict"],
                     "stages": [{k2: s[k2] for k2 in ("stage", "status", "summary")} for s in inv_facts["stages"]]}
            problems = [s for s in inv_facts["stages"] if s["status"] in ("fail", "warn")]
            rule_text = (f"Invoice {ref}: " + ("; ".join(f"{s['stage']}: {s['summary']}" for s in problems)
                         if problems else "every check passed."))
            cards.append({"type": "link", "title": f"Open the full investigation of {ref}", "href": f"/invoices/{inv.id}/investigate"})
    else:
        rule_text = ("I can answer questions about your GST data, for example: " + "; ".join(SUGGESTIONS[:4]) + ".")

    if intent == "help" or not facts:
        reply = {"text": rule_text, "source": "rules", "note": None}
    else:
        reply = explain_facts(intent.replace("_", " "), facts, question=message, history=history, fallback=rule_text)
    return {"answer": reply["text"], "answer_source": reply["source"], "note": reply.get("note"),
            "intent": intent, "context": {"intent": intent, "params": params, "period": period_key},
            "facts": facts, "cards": cards, "followups": followups or SUGGESTIONS[:3]}


# ----------------------------------------------------------------------------- CFO brief
def cfo_brief(db: Session, period_key: str | None = "this_month") -> dict:
    k = F.kpis(db, period_key)
    allk = F.kpis(db, "all")
    series = F.monthly_series(db, 6)
    risks = F.risk_items(db)
    vendors = [v for v in F.vendor_profiles(db) if v["attention_score"] > 0][:3]
    trend = None
    if len(series) >= 2 and series[-2]["purchase_value"]:
        a, b = series[-2], series[-1]
        trend = {"previous_month": a["month"], "latest_month": b["month"],
                 "purchase_change_pct": round(100 * (b["purchase_value"] - a["purchase_value"]) / a["purchase_value"], 1),
                 "gst_change_pct": round(100 * (b["gst"] - a["gst"]) / a["gst"], 1) if a["gst"] else None}
    counts = {s: sum(1 for x in risks if x["severity"] == s) for s in ("Critical", "High", "Review")}
    facts = {"period": k["period"]["label"], "period_kpis": {x: k[x] for x in (
                 "total_invoices", "total_purchase_value", "gst_amount", "itc_eligible", "itc_at_risk", "itc_blocked",
                 "gstr2b_mismatches", "needs_review")},
             "all_time_kpis": {x: allk[x] for x in ("total_invoices", "total_purchase_value", "gst_amount", "itc_eligible", "itc_at_risk")},
             "issue_counts": counts,
             "important_issues": [{x: r[x] for x in ("severity", "title", "invoice_number", "vendor", "amount_at_stake")} for r in risks[:5]],
             "vendors_needing_attention": [{x: v[x] for x in ("vendor_name", "gst_errors", "gstr2b_mismatches", "itc_at_risk")} for v in vendors],
             "monthly_trend": series, "trend": trend}
    rule = (f"Business overview ({facts['period']}): {k['total_invoices']} invoices, purchases of {F.inr(k['total_purchase_value'])} "
            f"and {F.inr(k['gst_amount'])} GST. ITC: {F.inr(k['itc_eligible'])} claimable, {F.inr(k['itc_at_risk'])} at risk. "
            f"Issues: {counts['Critical']} critical, {counts['High']} high, {counts['Review']} to review."
            + (f" Purchases changed {trend['purchase_change_pct']}% from {trend['previous_month']} to {trend['latest_month']}." if trend else "")
            + (f" Vendor needing most attention: {vendors[0]['vendor_name']}." if vendors else ""))
    commentary = explain_facts("CFO business brief", facts, fallback=rule, max_tokens=700, question=(
        "Write a short CFO brief with these headings: Business overview, Important issues, ITC summary, Key trends, "
        "Areas requiring attention. 2-3 sentences each. Use only numbers from the facts."))
    return {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "facts": facts,
            "commentary": commentary}
