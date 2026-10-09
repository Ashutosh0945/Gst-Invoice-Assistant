"""Remaining AI features, all built on deterministic facts:

  vendor_detail      (#5)  vendor intelligence profile
  recon_2b / recon_po (#7) exact field-by-field mismatch reasons
  monthly_report     (#8)  and  audit_report (#9)
  forecast           (#12) estimate of GST on purchases, with uncertainty
  what_if            (#13) simulations using the real ITC rules, never saved
  vendor_message     (#15) clarification draft from actual invoice facts
  feedback_metrics   (#14) human-correction dataset statistics

Nothing here writes to the database.
"""
from __future__ import annotations

import copy
import math
import statistics
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.ai import facts as F
from backend.db.models import FeedbackRecord, Gstr2bRecord, Invoice, ValidationFinding
from backend.llm.explain import explain_facts

ZERO = Decimal("0")
NOW = lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")  # noqa: E731


# ----------------------------------------------------------------------------- #5 vendor intelligence
def vendor_detail(db: Session, vendor_key: str, explain: bool = False) -> dict | None:
    vp = next((v for v in F.vendor_profiles(db) if v["vendor_key"] == vendor_key), None)
    if vp is None:
        return None
    invs = [i for i in F._invoices(db) if (i.vendor_gstin_raw or f"name:{(i.vendor_name_raw or 'Unknown vendor').strip()}") == vendor_key]
    monthly: dict[str, dict] = {}
    for i in invs:
        if i.invoice_date and i.status not in ("REJECTED", "FAILED"):
            m = monthly.setdefault(i.invoice_date.strftime("%Y-%m"), {"invoices": 0, "value": ZERO, "errors": 0})
            m["invoices"] += 1
            m["value"] += i.grand_total or ZERO
            m["errors"] += sum(1 for f in i.findings if f.severity == "ERROR" and f.category == "validation")
    trend = [{"month": k, "invoices": v["invoices"], "value": F.money(v["value"]), "errors": v["errors"]} for k, v in sorted(monthly.items())]
    rows = [{"invoice_id": str(i.id), "invoice_number": i.invoice_number, "invoice_date": i.invoice_date.isoformat() if i.invoice_date else None,
             "grand_total": F.money(i.grand_total), "status": i.status, "gstr2b_status": i.gstr2b_status,
             "errors": [f.code for f in i.findings if f.severity == "ERROR"]}
            for i in sorted(invs, key=lambda x: x.invoice_date or date.min, reverse=True)]
    out = {"profile": {k: v for k, v in vp.items() if k != "invoice_ids"}, "monthly_trend": trend, "invoices": rows}
    if explain:
        p = vp
        fb = (f"{p['vendor_name']}: {p['invoice_count']} invoices worth {F.inr(p['purchase_value'])} "
              f"(average {F.inr(p['average_invoice_value'])}). {p['gst_errors']} GST errors, {p['gstr2b_mismatches']} GSTR-2B "
              f"mismatches, {F.inr(p['itc_at_risk'])} ITC at risk."
              + (f" GSTR-2B filing rate {p['filing_rate_pct']}%." if p["filing_rate_pct"] is not None else ""))
        out["summary"] = explain_facts("vendor profile", {"profile": out["profile"], "monthly_trend": trend}, fallback=fb,
                                       question="Summarise this vendor's reliability for GST and what to watch out for.")
    return out


# ----------------------------------------------------------------------------- #7 reconciliation assistant
def _cmp(label, books, portal, same) -> dict:
    return {"field": label, "your_books": books, "gstr2b": portal, "match": same}


def recon_2b(db: Session, record_id) -> dict | None:
    r = db.get(Gstr2bRecord, record_id)
    if r is None:
        return None
    inv = db.get(Invoice, r.matched_invoice_id) if r.matched_invoice_id else None
    tax_2b = (r.igst or 0) + (r.cgst or 0) + (r.sgst or 0) + (r.cess or 0)
    rows = []
    if inv:
        tax_b = F.tax_of(inv)
        rows = [
            _cmp("Supplier GSTIN", inv.vendor_gstin_raw, r.supplier_gstin, (inv.vendor_gstin_raw or "").upper() == r.supplier_gstin.upper()),
            _cmp("Invoice number", inv.invoice_number, r.invoice_number, (inv.invoice_number or "") == r.invoice_number),
            _cmp("Invoice date", inv.invoice_date.isoformat() if inv.invoice_date else None,
                 r.invoice_date.isoformat() if r.invoice_date else None, inv.invoice_date == r.invoice_date),
            _cmp("Taxable value", F.money(inv.subtotal), F.money(r.taxable_value),
                 abs((inv.subtotal or ZERO) - (r.taxable_value or ZERO)) <= Decimal("1")),
            _cmp("Total tax", F.money(tax_b), F.money(tax_2b), abs(tax_b - tax_2b) <= Decimal("1")),
        ]
    reasons = {"MATCHED": "Everything matches.",
               "FUZZY_MATCHED": "Matched, but the invoice number is written differently in GSTR-2B.",
               "DATE_MISMATCH": "Matched, but the invoice date differs.",
               "AMOUNT_MISMATCH": "The amounts the vendor reported differ from your books.",
               "MISSING_IN_BOOKS": "The vendor reported this invoice, but it isn't in your books.",
               "GSTIN_MISMATCH": "The same invoice exists in your books under a different supplier GSTIN.",
               "REVIEW_REQUIRED": "More than one invoice in your books fits this line equally well; choose the right one.",
               "POTENTIAL_DUPLICATE": "This supplier invoice appears more than once in the GSTR-2B statement."}
    diffs = [x for x in rows if x["match"] is False]
    facts = {"match_status": r.match_status, "system_reason": reasons.get(r.match_status, r.match_status),
             "matcher_notes": r.match_notes, "differences": diffs, "itc_available_per_portal": r.itc_available,
             "portal_reason": r.itc_unavailable_reason, "supplier": r.supplier_name, "invoice_number": r.invoice_number}
    fb = facts["system_reason"] + (" Differences: " + "; ".join(f"{d['field']}: books {d['your_books']}, GSTR-2B {d['gstr2b']}" for d in diffs) + "." if diffs else "")
    return {"record": {"id": str(r.id), "supplier_name": r.supplier_name, "supplier_gstin": r.supplier_gstin,
                       "invoice_number": r.invoice_number, "match_status": r.match_status, "matched_invoice_id": str(inv.id) if inv else None},
            "comparison": rows, "reason": facts["system_reason"],
            "explanation": explain_facts("GSTR-2B reconciliation result", facts, fallback=fb,
                                         question="Explain exactly why this GSTR-2B record does or doesn't match, and what to do.")}


def recon_po(db: Session, invoice_id) -> dict | None:
    inv = db.get(Invoice, invoice_id)
    if inv is None:
        return None
    lines = {li.line_no: li for li in inv.items}
    rows = []
    for r in inv.reconciliation:
        li = lines.get(r.invoice_line_no)
        rows.append({"invoice_line": r.invoice_line_no, "description": li.description if li else None, "status": r.status,
                     "qty_invoice": None if r.qty_invoiced is None else float(r.qty_invoiced),
                     "qty_po": None if r.qty_po is None else float(r.qty_po),
                     "price_invoice": None if r.price_invoiced is None else float(r.price_invoiced),
                     "price_po": None if r.price_po is None else float(r.price_po),
                     "variance_amount": None if r.variance_amount is None else float(r.variance_amount),
                     "notes": r.notes})
    bad = [x for x in rows if x["status"] not in ("MATCHED", "NO_PO")]
    fb = ("No purchase order is referenced." if all(x["status"] == "NO_PO" for x in rows) else
          "Every line matches the purchase order." if not bad else
          " ".join(f"Line {x['invoice_line']}: {x['status'].replace('_', ' ').lower()} (invoice qty {x['qty_invoice']}, PO qty {x['qty_po']}, "
                   f"invoice price {x['price_invoice']}, PO price {x['price_po']})." for x in bad))
    return {"invoice_id": str(inv.id), "po_number": inv.po_number_raw, "lines": rows,
            "explanation": explain_facts("purchase order reconciliation", {"po_number": inv.po_number_raw, "lines": rows}, fallback=fb,
                                         question="Explain exactly which lines differ from the purchase order and why.")}


# ----------------------------------------------------------------------------- #8 / #9 reports
def _report_facts(db: Session, period_key: str) -> dict:
    period = F.resolve_period(period_key)
    invs = F._invoices(db, period)
    k = F.kpis(db, period_key)
    by_rate: dict[str, dict] = {}
    for i in invs:
        if i.status in ("REJECTED", "FAILED"):
            continue
        for li in i.items:
            key = f"{li.gst_rate:g}%" if li.gst_rate is not None else "unknown"
            b = by_rate.setdefault(key, {"taxable": ZERO, "gst": ZERO, "lines": 0})
            b["taxable"] += li.taxable_value or ZERO
            b["gst"] += sum((x or ZERO) for x in (li.cgst, li.sgst, li.igst, li.cess))
            b["lines"] += 1
    errs = [(i, f) for i in invs for f in i.findings if f.severity == "ERROR"]
    recs = [r for r in db.execute(select(Gstr2bRecord)).scalars() if F._in_period(r.invoice_date, period)]
    risks = [x for x in F.risk_items(db) if not x["invoice_id"] or x["invoice_id"] in {str(i.id) for i in invs}]
    an = [x for x in F.anomalies(db)["items"] if x["invoice_id"] in {str(i.id) for i in invs}]
    conf = [float(i.confidence_score) for i in invs if i.confidence_score is not None]
    return {
        "period": period,
        "processing": {"invoices": len(invs), "status_counts": k["status_counts"],
                       "average_confidence_pct": round(100 * statistics.mean(conf), 1) if conf else None},
        "gst": {"purchase_value": k["total_purchase_value"], "gst_amount": k["gst_amount"],
                "by_rate": [{"rate": r, "taxable": F.money(v["taxable"]), "gst": F.money(v["gst"]), "lines": v["lines"]}
                            for r, v in sorted(by_rate.items())]},
        "itc": {x: k[x] for x in ("itc_total", "itc_eligible", "itc_at_risk", "itc_blocked")},
        "gstr2b": {"imported": k["gstr2b_imported"], "records": len(recs),
                   "by_status": dict(Counter(r.match_status for r in recs)), "missing_in_2b": k["invoices_missing_in_2b"]},
        "validation": {"error_findings": len(errs), "by_code": dict(Counter(f.code for _, f in errs).most_common(10))},
        "vendors": [{x: v[x] for x in ("vendor_name", "invoice_count", "purchase_value", "gst_errors", "gstr2b_mismatches", "itc_at_risk")}
                    for v in F.vendor_profiles(db, period_key) if v["attention_score"] > 0][:8],
        "anomalies": an[:15],
        "review_items": [{x: r[x] for x in ("severity", "category", "title", "invoice_number", "invoice_id", "vendor", "amount_at_stake")} for r in risks],
        "trend": F.monthly_series(db, 6),
        "detailed_findings": [{"invoice_id": str(i.id), "invoice_number": i.invoice_number, "vendor": i.vendor_name_raw,
                               "code": f.code, "category": f.category, "message": f.message} for i, f in errs],
    }


def monthly_report(db: Session, period_key: str) -> dict:
    f = _report_facts(db, period_key)
    fb = (f"For {f['period']['label'].lower() if f['period']['key'] == 'all' else f['period']['label']}, {f['processing']['invoices']} invoices were processed with purchases of "
          f"{F.inr(f['gst']['purchase_value'])} and {F.inr(f['gst']['gst_amount'])} GST. Claimable ITC: {F.inr(f['itc']['itc_eligible'])}; "
          f"at risk: {F.inr(f['itc']['itc_at_risk'])}. {len(f['review_items'])} items need review.")
    summary = explain_facts("monthly GST report", {k: v for k, v in f.items() if k != "detailed_findings"}, fallback=fb,
                            question="Write a short monthly GST report summary for the business owner.", max_tokens=600)
    return {"kind": "monthly", "generated_at": NOW(), "facts": f, "summary": summary}


def audit_report(db: Session, period_key: str) -> dict:
    f = _report_facts(db, period_key)
    crit = sum(1 for r in f["review_items"] if r["severity"] == "Critical")
    fb = (f"Audit of {f['period']['label']}: {f['processing']['invoices']} invoices reviewed, {f['validation']['error_findings']} GST "
          f"validation errors, {crit} critical issues, {len(f['anomalies'])} anomaly indicators. ITC at risk: {F.inr(f['itc']['itc_at_risk'])}.")
    summary = explain_facts("GST audit report", {k: v for k, v in f.items() if k != "detailed_findings"}, fallback=fb,
                            question="Write the executive summary of a GST audit report: what was reviewed, key findings, "
                                     "and the most important issues. Factual and neutral.", max_tokens=600)
    return {"kind": "audit", "generated_at": NOW(), "facts": f, "executive_summary": summary,
            "sections": ["Executive Summary", "Invoice Processing", "GST Validation", "GSTR-2B Reconciliation", "ITC Review",
                         "Vendor Findings", "Anomaly Findings", "Important Issues", "Detailed Findings"]}


# ----------------------------------------------------------------------------- #12 forecast
def forecast(db: Session, months_ahead: int = 3) -> dict:
    """Linear trend over monthly GST on purchases, with an ~80% range from past residuals.
    GST Desk only records PURCHASE invoices, so this forecasts input GST (and ITC), not output liability."""
    series = F.monthly_series(db, 24)
    base = {"label": "Estimate only — not a statutory calculation.", "what": "GST on purchase invoices (input tax) per month",
            "history": series, "forecast": [], "method": "Least-squares linear trend over monthly totals"}
    if len(series) < 3:
        return {**base, "status": "insufficient_history", "message": f"At least 3 months of invoices are needed; you have {len(series)}."}
    ys = [m["gst"] for m in series]
    n = len(ys)
    xs = list(range(n))
    mx, my = statistics.mean(xs), statistics.mean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx if sxx else 0.0
    icpt = my - slope * mx
    resid = [y - (icpt + slope * x) for x, y in zip(xs, ys)]
    sd = statistics.stdev(resid) if n > 2 else 0.0
    last = datetime.strptime(series[-1]["month"] + "-01", "%Y-%m-%d").date()
    out = []
    for h in range(1, months_ahead + 1):
        y, m = last.year + (last.month - 1 + h) // 12, (last.month - 1 + h) % 12 + 1
        x = n - 1 + h
        est = max(0.0, icpt + slope * x)
        width = 1.28 * sd * math.sqrt(1 + 1 / n + ((x - mx) ** 2) / sxx) if sxx else 0.0
        out.append({"month": f"{y}-{m:02d}", "estimate": round(est, 2), "low": round(max(0.0, est - width), 2), "high": round(est + width, 2)})
    conf = "low" if n < 6 or (my and sd / my > 0.5) else "medium" if n < 12 else "reasonable"
    return {**base, "status": "ok", "forecast": out, "confidence": conf, "months_used": n,
            "trend_per_month": round(slope, 2),
            "message": f"Based on {n} months. Confidence: {conf}. The range is an ~80% band from past variation."}


# ----------------------------------------------------------------------------- #13 what-if
def what_if(db: Session, scenario: str, *, pct: float = 0, invoice_id=None) -> dict:
    """Runs the real ITC rules on a COPY of the inputs. Nothing is saved."""
    from backend.config import get_settings
    from backend.itc.eligibility import assess
    from backend.itc.service import build_input

    s = get_settings()
    note = "Simulated values — nothing in your records was changed."
    if scenario == "purchases_change":
        k = F.kpis(db, "all")
        f = 1 + pct / 100
        rows = [("Purchase value", k["total_purchase_value"], round(k["total_purchase_value"] * f, 2)),
                ("GST paid on purchases", k["gst_amount"], round(k["gst_amount"] * f, 2)),
                ("ITC claimable", k["itc_eligible"], round(k["itc_eligible"] * f, 2)),
                ("ITC blocked by law", k["itc_blocked"], round(k["itc_blocked"] * f, 2))]
        return {"scenario": f"Purchases change by {pct:+g}%", "note": note,
                "assumption": "Every invoice scales by the same percentage; the mix of goods, rates and vendors stays the same.",
                "rows": [{"metric": m, "current": a, "simulated": b, "change": round(b - a, 2)} for m, a, b in rows]}
    inv = db.get(Invoice, invoice_id) if invoice_id else None
    if inv is None:
        raise ValueError("Choose an invoice for this scenario.")
    current = assess(build_input(db, inv), today=date.today(), same_line_prefixes=s.same_line_prefixes, payment_days=s.itc_payment_days)
    sim_in = copy.deepcopy(build_input(db, inv))
    today = date.today()
    if scenario == "not_in_2b":
        sim_in.gstr2b_status, sim_in.twob_itc_available = "MISSING_IN_2B", None
        title = f"Invoice {inv.invoice_number} is NOT in GSTR-2B"
    elif scenario == "unpaid_180":
        sim_in.payment_date = None
        today = (inv.invoice_date or date.today()) + timedelta(days=s.itc_payment_days + 1)
        title = f"Vendor for {inv.invoice_number} still unpaid after {s.itc_payment_days} days"
    else:
        raise ValueError("Unknown scenario.")
    sim = assess(sim_in, today=today, same_line_prefixes=s.same_line_prefixes, payment_days=s.itc_payment_days)
    rows = [{"metric": m, "current": float(getattr(current, a)), "simulated": float(getattr(sim, a)),
             "change": float(getattr(sim, a) - getattr(current, a))}
            for m, a in (("ITC claimable", "eligible_itc"), ("ITC at risk", "at_risk_itc"), ("ITC blocked", "blocked_itc"), ("Needs decision", "review_itc"))]
    return {"scenario": title, "note": note, "assumption": "Uses the same ITC rules as the live system on a copy of this invoice's data.",
            "status": {"current": current.status, "simulated": sim.status},
            "simulated_reasons": [r["message"] for r in sim.reasons if r["severity"] in ("ERROR", "WARNING")], "rows": rows}


# ----------------------------------------------------------------------------- #15 vendor message
def vendor_message(db: Session, invoice_id, issue: str | None = None) -> dict | None:
    inv = db.get(Invoice, invoice_id)
    if inv is None:
        return None
    rec = db.get(Gstr2bRecord, inv.gstr2b_record_id) if inv.gstr2b_record_id else None
    errs = [f.message for f in inv.findings if f.severity == "ERROR" and f.category in ("validation", "einvoice")]
    points = []
    if inv.gstr2b_status == "MISSING_IN_2B":
        points.append("This invoice does not appear in our GSTR-2B. Please confirm it has been reported in your GSTR-1.")
    if rec and rec.match_status == "AMOUNT_MISMATCH":
        points.append(f"The amounts reported in GSTR-2B differ from the invoice we received ({rec.match_notes}).")
    if inv.einvoice_status in ("MISMATCH", "SIGNATURE_INVALID"):
        points.append("The details printed on the invoice do not match its e-invoice QR code. Please share the original e-invoice.")
    points += [f"{m}" for m in errs[:3] if not any(m in p for p in points)]
    if issue:
        points.insert(0, issue.strip()[:300])
    if not points:
        points.append("Please confirm the details of this invoice.")
    facts = {"vendor": inv.vendor_name_raw, "vendor_gstin": inv.vendor_gstin_raw, "invoice_number": inv.invoice_number,
             "invoice_date": inv.invoice_date.strftime("%d %b %Y") if inv.invoice_date else None,
             "grand_total": F.inr(inv.grand_total), "points": points}
    subject = f"Clarification needed: invoice {inv.invoice_number or ''} dated {facts['invoice_date'] or ''}".strip()
    body = (f"Dear {inv.vendor_name_raw or 'Sir/Madam'},\n\nWe are reviewing your invoice {inv.invoice_number or ''} dated "
            f"{facts['invoice_date'] or '—'} for {facts['grand_total']} (GSTIN {inv.vendor_gstin_raw or '—'}).\n\n"
            + "\n".join(f"• {p}" for p in points)
            + "\n\nCould you please look into this and reply at the earliest, so we can complete our GST records?\n\nRegards,\n")
    polished = explain_facts("vendor clarification email", facts, fallback=body, max_tokens=500,
                             question="Rewrite this as a polite, professional email to the vendor. Keep every invoice detail exactly "
                                      "as given; do not add any new facts. Start with 'Dear'. End with 'Regards,'.\n\nDRAFT:\n" + body)
    return {"subject": subject, "body": polished["text"], "source": polished["source"], "note": polished.get("note"),
            "facts": facts, "reminder": "Review and edit before sending. GST Desk never sends messages by itself."}


# ----------------------------------------------------------------------------- #14 feedback loop
MIN_FEEDBACK = 20


def feedback_metrics(db: Session) -> dict:
    recs = db.execute(select(FeedbackRecord).order_by(FeedbackRecord.created_at)).scalars().all()
    by_field: dict[str, list] = {}
    for r in recs:
        by_field.setdefault(r.field, []).append(r)
    fields = [{"field": k, "reviewed": len(v), "corrected": sum(not r.was_correct for r in v),
               "accuracy_pct": round(100 * sum(r.was_correct for r in v) / len(v), 1)} for k, v in sorted(by_field.items())]
    enough = len(recs) >= MIN_FEEDBACK
    trend = []
    if enough:
        months: dict[str, list] = {}
        for r in recs:
            months.setdefault(r.created_at.strftime("%Y-%m") if r.created_at else "unknown", []).append(r.was_correct)
        trend = [{"month": m, "reviewed": len(v), "accuracy_pct": round(100 * sum(v) / len(v), 1)} for m, v in sorted(months.items())]
    return {"total_feedback": len(recs), "minimum_for_metrics": MIN_FEEDBACK, "enough_data": enough,
            "fields": fields if enough else [], "trend": trend,
            "message": None if enough else f"Improvement metrics appear after {MIN_FEEDBACK} reviewed fields; you have {len(recs)}.",
            "policy": "Corrections are stored as a training/evaluation dataset only. A new extraction model is never switched on "
                      "automatically: it must first beat the current one on the benchmark (python -m ml.benchmark)."}


def feedback_export(db: Session) -> list[dict]:
    return [{"invoice_id": str(r.invoice_id) if r.invoice_id else None, "scope": r.scope, "field": r.field, "line_no": r.line_no,
             "predicted": r.predicted_value, "corrected": r.corrected_value, "was_correct": r.was_correct,
             "predicted_confidence": float(r.predicted_confidence) if r.predicted_confidence is not None else None,
             "created_at": r.created_at.isoformat() if r.created_at else None}
            for r in db.execute(select(FeedbackRecord).order_by(FeedbackRecord.created_at)).scalars()]
