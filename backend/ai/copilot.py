"""AI GST Copilot and AI CFO Business Brief.

Flow for every question:  detect intent (rules)  ->  run a fixed, read-only query from
facts.py  ->  build a rule-written answer  ->  let OpenRouter re-word it from the same
facts  ->  fact-check every number (explain_facts). Data cards are always the raw facts,
so the user can see exactly where each number came from.
"""
from __future__ import annotations

import re
from decimal import Decimal
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
    ("review_queue", r"(?:which|what|list|show).*invoices?.*(?:manual review|need(?:s)? review|require(?:s)? review|to review)"),
    ("unresolved_by_vendor", r"vendors?.*(?:most|highest|top).*(?:unresolved|open).*(?:mismatch|discrepanc)|unresolved.*mismatch.*vendor"),
    ("tax_difference", r"(?:total )?tax difference|difference in (?:tax|gst)|how much tax.*(?:differ|mismatch)"),
    ("repeated_discrepancies", r"repeat(?:ed)?.*discrepanc|same (?:problem|issue|error).*again|recurring (?:issue|problem|discrepanc)"),
    ("prioritise", r"investigate first|what first|prioriti[sz]e|most important (?:issue|discrepanc)"),
    ("forecast", r"forecast|predict|next month|next quarter|projection"),
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


# ----------------------------------------------------------------------------- AI router (whitelisted)
ROUTABLE = {   # the ONLY things the AI router may choose; each maps to a fixed read-only query
    "summary": "overall GST / purchase / invoice summary or totals for a period",
    "itc_at_risk": "input tax credit (ITC) at risk, blocked or claimable",
    "vendor_errors": "which vendor has the most GST/validation errors",
    "vendors_attention": "risky vendors or vendors needing attention",
    "gstr2b_mismatches": "GSTR-2B mismatches or invoices missing from GSTR-2B",
    "anomalies": "unusual, suspicious or anomalous invoices",
    "risks": "what needs attention / open issues / priorities",
    "search": "find or list invoices matching conditions (amount, vendor, status, period)",
    "investigate": "explain or check one specific invoice by its number",
    "review_queue": "which invoices need manual review",
    "unresolved_by_vendor": "vendors with the most unresolved GSTR-2B mismatches",
    "tax_difference": "total tax difference in unresolved reconciliations",
    "repeated_discrepancies": "vendors with repeated discrepancies",
    "prioritise": "which discrepancies to investigate first",
    "forecast": "explain forecast / predicted purchases or GST",
    "unsupported": "anything else (weather, jokes, legal advice, changing data, etc.)",
}
PERIODS = {"this_month", "last_month", "this_quarter", "this_fy", "last_90_days", "all"}


def _ai_route(text: str) -> tuple[str, dict] | None:
    """Asks OpenRouter to map a free-form question onto ONE whitelisted intent. The reply is validated:
    unknown intents, periods or malformed JSON are rejected. The AI never writes or runs a query."""
    import json

    from backend.llm.explain import chat

    menu = "\n".join(f"- {k}: {v}" for k, v in ROUTABLE.items())
    out = chat([{"role": "system", "content": "You route questions for a GST invoice app. Choose exactly one intent from this list:\n"
                 f"{menu}\nReply ONLY with JSON: {{\"intent\": ..., \"period\": one of {sorted(PERIODS)} or null, "
                 "\"invoice_ref\": invoice number or null}}"},
                {"role": "user", "content": text[:500]}], max_tokens=120, retries=1)
    if not out:
        return None
    try:
        raw = json.loads(out[out.find("{"): out.rfind("}") + 1])
    except ValueError:
        return None
    intent = raw.get("intent")
    if intent not in ROUTABLE or intent == "unsupported":
        return ("help", {}) if intent == "unsupported" else None
    params: dict = {}
    if raw.get("period") in PERIODS:
        params["period"] = raw["period"]
    ref = raw.get("invoice_ref")
    if intent == "investigate":
        if not (isinstance(ref, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9/\-]{2,40}", ref)):
            return None
        params["invoice_ref"] = ref
    return intent, params


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
    routed = _ai_route(text)                 # only when the rules didn't recognise the question
    if routed:
        intent, params = routed
        params["_routed_by"] = "ai"
        return intent, params
    return "help", {}


def _table(title, columns, rows, link=None):
    return {"type": "table", "title": title, "columns": columns, "rows": rows, "link": link}


def answer(db: Session, message: str, history: list[dict] | None = None, context: dict | None = None) -> dict:
    intent, params = detect(message, context)
    routed_by = "ai" if params.pop("_routed_by", None) else "rules"
    period_key = (_period_from(message) or params.pop("period", None) or (context or {}).get("period")) if intent != "help" else None
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
    elif intent in ("review_queue", "unresolved_by_vendor", "tax_difference", "repeated_discrepancies", "prioritise", "forecast"):
        rule_text, facts, cards, followups = _v6_intent(db, intent)
    else:
        rule_text = ("I can answer questions about your GST data, for example: " + "; ".join(SUGGESTIONS[:4]) + ".")

    if intent == "help" or not facts:
        reply = {"text": rule_text, "source": "rules", "note": None}
    else:
        reply = explain_facts(intent.replace("_", " "), facts, question=message, history=history, fallback=rule_text)
    evidence = build_evidence(intent, period_key, facts, cards, reply["source"])
    return {"answer": reply["text"], "answer_source": reply["source"], "note": reply.get("note"),
            "intent": intent, "routed_by": routed_by, "context": {"intent": intent, "params": params, "period": period_key},
            "facts": facts, "cards": cards, "followups": followups or SUGGESTIONS[:3], "evidence": evidence}


# ----------------------------------------------------------------------------- evidence panel (Improvement 5)
SOURCES = {
    "summary": ["invoices", "itc_assessments", "gstr2b_records"], "itc_at_risk": ["itc_assessments", "invoices", "gstr2b_records"],
    "vendor_errors": ["invoices", "validation_findings"], "vendors_attention": ["invoices", "validation_findings", "gstr2b_records", "itc_assessments"],
    "gstr2b_mismatches": ["gstr2b_records", "invoices"], "anomalies": ["invoices", "anomaly_scores"], "risks": ["invoices", "validation_findings", "gstr2b_records", "itc_assessments"],
    "search": ["invoices"], "investigate": ["invoices", "validation_findings", "gstr2b_records", "itc_assessments", "audit_logs"],
    "review_queue": ["invoices"], "unresolved_by_vendor": ["gstr2b_records"], "tax_difference": ["gstr2b_records", "invoices"],
    "repeated_discrepancies": ["validation_findings", "gstr2b_records", "invoices"], "prioritise": ["invoices", "gstr2b_records", "itc_assessments"],
    "forecast": ["invoices (monthly aggregates)", "forecast_runs"]}
DEFINITIONS = {
    "itc_at_risk": "ITC at risk = at-risk + needs-decision amounts from the ITC rules (not confirmed lost or eligible).",
    "gstr2b_mismatches": "A mismatch is any GSTR-2B line that isn't an exact match, or an invoice missing from GSTR-2B.",
    "tax_difference": "Sum of |GSTR-2B tax − register tax| over unresolved amount-mismatched pairs (each pair counted once).",
    "forecast": "Forecasts are statistical estimates of purchase GST, not tax liability; see model, holdout error and range.",
    "anomalies": "Anomaly = statistical signal for review; not proof of fraud or non-compliance.",
    "unresolved_by_vendor": "Unresolved = GSTR-2B line that isn't an exact match and isn't marked resolved."}


def build_evidence(intent: str, period_key: str | None, facts: dict, cards: list, source: str) -> dict:
    links = []
    for c in cards:
        for href, row in zip(c.get("row_links") or [], c.get("rows") or []):
            links.append({"label": str(row[0]), "href": href})
        if c.get("type") == "link":
            links.append({"label": c["title"], "href": c["href"]})
    kinds = []
    if facts:
        kinds.append("verified database facts")
        kinds.append("deterministic calculations")
    if intent in ("anomalies",):
        kinds.append("ML / statistical signals")
    if intent == "forecast" and facts.get("status") == "ok":
        kinds.append("ML forecast (estimate)")
    if source == "ai":
        kinds.append("AI explanation (wording only, numbers fact-checked)")
    if not facts or facts.get("status") == "insufficient_history" or facts.get("count") == 0:
        kinds.append("insufficient data")
    from backend.ai import facts as F
    return {"period": F.resolve_period(period_key)["label"] if period_key else "All time / not period-specific",
            "filters": {k: v for k, v in (facts.get("understood_as") and {"search": facts["understood_as"]} or {}).items()},
            "data_sources": SOURCES.get(intent, []), "definition": DEFINITIONS.get(intent),
            "records": links[:20], "response_categories": kinds,
            "provenance": "Numbers come from read-only database queries in backend/ai/facts.py and the ML modules; "
                          "the language model only words the answer and every number it writes is checked against these facts.",
            "limitations": "Credit/debit notes and amendments in GSTR-2B are not reconciled; forecasts and anomaly scores are estimates."}


def _v6_intent(db: Session, intent: str):
    from sqlalchemy import select

    from backend.db.models import Gstr2bRecord, Invoice
    if intent == "review_queue":
        rows = db.execute(select(Invoice).where(Invoice.status == "NEEDS_REVIEW").order_by(Invoice.confidence_score)).scalars().all()
        facts = {"count": len(rows), "invoices": [{"invoice_number": i.invoice_number, "vendor": i.vendor_name_raw,
                 "confidence_pct": round(float(i.confidence_score or 0) * 100), "errors": [f.code for f in i.findings if f.severity == "ERROR"][:4]} for i in rows[:15]]}
        text = f"{len(rows)} invoices need manual review." if rows else "No invoices need manual review right now."
        card = _table("Invoices needing review", ["Invoice", "Vendor", "Confidence", "Errors"],
                      [[x["invoice_number"], x["vendor"], f"{x['confidence_pct']}%", ", ".join(x["errors"]) or "—"] for x in facts["invoices"]], "/review")
        card["row_links"] = [f"/invoices/{i.id}/investigate" for i in rows[:15]]
        return text, facts, [card], ["Which discrepancies should I investigate first?"]
    recs = db.execute(select(Gstr2bRecord)).scalars().all()
    open_recs = [r for r in recs if r.match_status != "MATCHED" and (r.resolution_status or "open") != "resolved"]
    if intent == "unresolved_by_vendor":
        by: dict[str, list] = {}
        for r in open_recs:
            by.setdefault(r.supplier_name or r.supplier_gstin, []).append(r)
        top = sorted(by.items(), key=lambda kv: -len(kv[1]))[:5]
        facts = {"count": len(open_recs), "vendors": [{"vendor": v, "unresolved": len(rs), "kinds": sorted({r.match_status for r in rs})} for v, rs in top]}
        text = (f"{top[0][0]} has the most unresolved GSTR-2B mismatches: {len(top[0][1])}." if top else
                "There are no unresolved GSTR-2B mismatches." if recs else "No GSTR-2B has been imported, so there's nothing to reconcile.")
        card = _table("Unresolved GSTR-2B mismatches by vendor", ["Vendor", "Unresolved", "Kinds"],
                      [[x["vendor"], x["unresolved"], ", ".join(x["kinds"])] for x in facts["vendors"]], "/gstr2b")
        return text, facts, [card], ["What is the total tax difference in unresolved reconciliations?"]
    if intent == "tax_difference":
        diff, n, items = Decimal(0), 0, []
        for r in open_recs:
            if r.match_status == "AMOUNT_MISMATCH" and r.matched_invoice_id:
                inv = db.get(Invoice, r.matched_invoice_id)
                t2b = (r.igst or 0) + (r.cgst or 0) + (r.sgst or 0) + (r.cess or 0)
                tb = sum((x or 0) for x in (inv.total_cgst, inv.total_sgst, inv.total_igst, inv.total_cess))
                d = abs(t2b - tb)
                diff += d; n += 1
                items.append({"invoice_number": inv.invoice_number, "vendor": r.supplier_name, "difference": float(d), "invoice_id": str(inv.id)})
        facts = {"tax_difference": float(diff), "pairs": n, "items": items[:15]}
        text = f"The total tax difference across {n} unresolved amount mismatches is {F.inr(diff)}." if n else "There are no unresolved amount mismatches."
        card = _table("Unresolved tax differences", ["Invoice", "Vendor", "Difference"], [[x["invoice_number"], x["vendor"], F.inr(x["difference"])] for x in items[:15]], "/gstr2b")
        card["row_links"] = [f"/invoices/{x['invoice_id']}/investigate" for x in items[:15]]
        return text, facts, [card], ["Which vendors have the most unresolved GST mismatches?"]
    if intent == "repeated_discrepancies":
        vp = [v for v in F.vendor_profiles(db) if v["repeated_issues"] or v["gstr2b_mismatches"] >= 2]
        facts = {"count": len(vp), "vendors": [{"vendor": v["vendor_name"], "repeated_issues": v["repeated_issues"], "gstr2b_mismatches": v["gstr2b_mismatches"]} for v in vp[:8]]}
        text = (f"{len(vp)} vendors have repeated discrepancies; {vp[0]['vendor_name']} is first." if vp else "No vendor has repeated discrepancies.")
        card = _table("Vendors with repeated discrepancies", ["Vendor", "Repeated validation issues", "GSTR-2B mismatches"],
                      [[x["vendor"], ", ".join(f"{i['code']}×{i['times']}" for i in x["repeated_issues"]) or "—", x["gstr2b_mismatches"]] for x in facts["vendors"]], "/vendors")
        return text, facts, [card], ["Which vendors need attention?"]
    if intent == "prioritise":
        from backend.services.workspace import action_center
        acts = action_center(db)["priority_actions"][:8]
        facts = {"count": len(acts), "ranking_rule": "severity weight + 10·log10(1 + amount at stake)",
                 "top": [{"title": a["title"], "invoice": a["invoice_number"] or a["vendor"], "priority_score": a["priority_score"]} for a in acts]}
        text = (f"Start with: {acts[0]['title']} ({acts[0]['invoice_number'] or acts[0]['vendor']})." if acts else "Nothing needs investigation right now.")
        card = _table("Investigate in this order", ["Priority", "Issue", "Invoice / vendor"], [[a["priority_score"], a["title"], a["invoice_number"] or a["vendor"]] for a in acts], "/risk")
        card["row_links"] = [f"/invoices/{a['invoice_id']}/investigate" if a.get("invoice_id") else "/risk" for a in acts]
        return text, facts, [card], ["Explain why the first one was flagged"]
    # forecast: explain stored/derived results; the LLM never creates forecast values
    from backend.ml.forecasting import forecast_series, monthly
    invs = db.execute(select(Invoice).where(Invoice.status.notin_(["REJECTED", "FAILED"]))).scalars().all()
    months, y, filled = monthly([(i.invoice_date, float(sum((x or 0) for x in (i.total_cgst, i.total_sgst, i.total_igst, i.total_cess)))) for i in invs if i.invoice_date])
    fc = forecast_series(months, y, filled=filled)
    facts = {"status": fc["status"], "model": fc.get("model"), "forecast": fc.get("forecast"), "selection": fc.get("selection"),
             "message": fc.get("message"), "label": fc["label"],
             "holdout_mae": fc["evaluation"][fc["model"]]["MAE"] if fc["status"] == "ok" else None}
    text = (f"Using {fc['model']}, GST on purchases next month is estimated at {F.inr(fc['forecast'][0]['forecast'])} "
            f"(range {F.inr(fc['forecast'][0]['low'])}–{F.inr(fc['forecast'][0]['high'])}). {fc['selection']} This is an estimate, not tax liability."
            if fc["status"] == "ok" else fc["message"])
    return text, facts, [{"type": "link", "title": "Open forecasts in Analytics", "href": "/forecast"}], ["Give me this month's GST summary"]


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
