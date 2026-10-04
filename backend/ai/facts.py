"""Deterministic facts for the AI features. Pure database reads -- no AI, no writes.

Every figure the dashboard, Copilot, CFO brief, risk centre and investigation show is
computed here from the same tables the rest of GST Desk uses, so AI wording can be
checked against it (see backend/llm/explain.py:unsupported_numbers).
"""
from __future__ import annotations

import calendar
import statistics
from collections import Counter, defaultdict
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from backend.db.models import Gstr2bRecord, Invoice, ItcAssessment, ReconciliationResult, ValidationFinding

ZERO = Decimal("0")
STANDARD_RATES = {Decimal(x) for x in ("0", "0.1", "0.25", "1", "1.5", "3", "5", "6", "7.5", "12", "18", "28", "40")}
TWO_B_MISMATCH = ("AMOUNT_MISMATCH", "MISSING_IN_BOOKS")


def money(v) -> float:
    return float(round(Decimal(str(v or 0)), 2))


def inr(v) -> str:
    n = float(v or 0)
    whole, frac = f"{abs(n):.2f}".split(".")
    head, tail = whole[:-3], whole[-3:]
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    body = ",".join(parts + [tail]) if parts else tail
    return f"{'-' if n < 0 else ''}₹{body}" + ("" if frac == "00" else f".{frac}")


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def tax_of(inv: Invoice) -> Decimal:
    return sum((x or ZERO) for x in (inv.total_cgst, inv.total_sgst, inv.total_igst, inv.total_cess))


# ----------------------------------------------------------------------------- periods
def resolve_period(key: str | None, today: date | None = None) -> dict:
    """'this_month' | 'last_month' | 'this_quarter' | 'this_fy' | 'last_90_days' | 'all' | 'YYYY-MM'."""
    today = today or date.today()
    key = (key or "all").strip().lower()
    if key == "this_month":
        start = today.replace(day=1)
        end = today.replace(day=calendar.monthrange(today.year, today.month)[1])
        label = start.strftime("%B %Y")
    elif key == "last_month":
        end = today.replace(day=1) - timedelta(days=1)
        start = end.replace(day=1)
        label = start.strftime("%B %Y")
    elif key == "this_quarter":
        q0 = (today.month - 1) // 3 * 3 + 1
        start = date(today.year, q0, 1)
        em = q0 + 2
        end = date(today.year, em, calendar.monthrange(today.year, em)[1])
        label = f"Quarter {start:%b}–{end:%b %Y}"
    elif key == "this_fy":
        y = today.year if today.month >= 4 else today.year - 1
        start, end = date(y, 4, 1), date(y + 1, 3, 31)
        label = f"FY {y}-{str(y + 1)[2:]}"
    elif key == "last_90_days":
        start, end = today - timedelta(days=90), today
        label = "Last 90 days"
    elif len(key) == 7 and key[4] == "-":
        y, m = int(key[:4]), int(key[5:])
        start = date(y, m, 1)
        end = date(y, m, calendar.monthrange(y, m)[1])
        label = start.strftime("%B %Y")
    else:
        return {"key": "all", "label": "All time", "start": None, "end": None}
    return {"key": key, "label": label, "start": start.isoformat(), "end": end.isoformat()}


def _in_period(d: date | None, period: dict) -> bool:
    if period.get("start") is None:
        return True
    return d is not None and period["start"] <= d.isoformat() <= period["end"]


def _invoices(db: Session, period: dict | None = None) -> list[Invoice]:
    rows = db.execute(select(Invoice).options(
        selectinload(Invoice.findings), selectinload(Invoice.itc), selectinload(Invoice.items),
        selectinload(Invoice.reconciliation))).scalars().all()
    if period:
        rows = [i for i in rows if _in_period(i.invoice_date, period)]
    return rows


# ----------------------------------------------------------------------------- KPIs
def kpis(db: Session, period_key: str | None = None) -> dict:
    period = resolve_period(period_key)
    invs = _invoices(db, period)
    live = [i for i in invs if i.status not in ("REJECTED", "FAILED")]
    itc = [i.itc for i in live if i.itc]
    recs = db.execute(select(Gstr2bRecord)).scalars().all()
    recs = [r for r in recs if _in_period(r.invoice_date, period)]
    matched = sum(1 for r in recs if r.match_status in ("MATCHED", "FUZZY_MATCHED", "DATE_MISMATCH"))
    missing_in_2b = sum(1 for i in live if i.gstr2b_status == "MISSING_IN_2B")
    mismatches = sum(1 for r in recs if r.match_status in TWO_B_MISMATCH) + missing_in_2b
    status_counts = Counter(i.status for i in invs)
    return {
        "period": period,
        "total_invoices": len(invs),
        "total_purchase_value": money(sum((i.grand_total or ZERO) for i in live)),
        "gst_amount": money(sum((tax_of(i) for i in live), ZERO)),
        "itc_total": money(sum((a.total_itc or ZERO) for a in itc)),
        "itc_eligible": money(sum((a.eligible_itc or ZERO) for a in itc)),
        "itc_at_risk": money(sum(((a.at_risk_itc or ZERO) + (a.review_itc or ZERO)) for a in itc)),
        "itc_blocked": money(sum((a.blocked_itc or ZERO) for a in itc)),
        "gstr2b_matched": matched,
        "gstr2b_mismatches": mismatches,
        "invoices_missing_in_2b": missing_in_2b,
        "needs_review": status_counts.get("NEEDS_REVIEW", 0),
        "status_counts": dict(status_counts),
        "gstr2b_imported": bool(recs) or db.execute(select(Gstr2bRecord.id).limit(1)).first() is not None,
    }


def monthly_series(db: Session, months: int = 12) -> list[dict]:
    acc: dict[str, dict] = defaultdict(lambda: {"invoices": 0, "purchase_value": ZERO, "gst": ZERO, "itc_eligible": ZERO})
    for i in _invoices(db):
        if not i.invoice_date or i.status in ("REJECTED", "FAILED"):
            continue
        m = acc[i.invoice_date.strftime("%Y-%m")]
        m["invoices"] += 1
        m["purchase_value"] += i.grand_total or ZERO
        m["gst"] += tax_of(i)
        m["itc_eligible"] += (i.itc.eligible_itc if i.itc else ZERO) or ZERO
    out = [{"month": k, "invoices": v["invoices"], "purchase_value": money(v["purchase_value"]),
            "gst": money(v["gst"]), "itc_eligible": money(v["itc_eligible"])} for k, v in sorted(acc.items())]
    return out[-months:]


# ----------------------------------------------------------------------------- vendors
def vendor_profiles(db: Session, period_key: str | None = None) -> list[dict]:
    period = resolve_period(period_key)
    by: dict[str, list[Invoice]] = defaultdict(list)
    for i in _invoices(db, period):
        by[i.vendor_gstin_raw or f"name:{(i.vendor_name_raw or 'Unknown vendor').strip()}"].append(i)
    recs = db.execute(select(Gstr2bRecord)).scalars().all()
    rec_mm = Counter(r.supplier_gstin for r in recs if r.match_status in TWO_B_MISMATCH and _in_period(r.invoice_date, period))
    out = []
    for key, invs in by.items():
        live = [i for i in invs if i.status not in ("REJECTED", "FAILED")]
        errors = [f for i in invs for f in i.findings if f.severity == "ERROR" and f.category == "validation"]
        codes = Counter(f.code for f in errors)
        in2b = sum(1 for i in live if i.gstr2b_status == "IN_2B")
        miss = sum(1 for i in live if i.gstr2b_status == "MISSING_IN_2B")
        total = sum((i.grand_total or ZERO) for i in live)
        name = next((i.vendor_name_raw for i in invs if i.vendor_name_raw), None)
        out.append({
            "vendor_key": key, "vendor_gstin": None if key.startswith("name:") else key,
            "vendor_name": name or key.removeprefix("name:"),
            "invoice_count": len(invs), "purchase_value": money(total),
            "average_invoice_value": money(total / len(live)) if live else 0.0,
            "gst_errors": len(errors), "invoices_with_errors": sum(1 for i in invs if any(
                f.severity == "ERROR" and f.category == "validation" for f in i.findings)),
            "gstr2b_mismatches": miss + rec_mm.get(key, 0), "missing_in_2b": miss,
            "filing_rate_pct": round(100 * in2b / (in2b + miss), 1) if (in2b + miss) else None,
            "itc_at_risk": money(sum(((i.itc.at_risk_itc or ZERO) + (i.itc.review_itc or ZERO)) for i in live if i.itc)),
            "einvoice_problems": sum(1 for i in invs if i.einvoice_status in ("MISMATCH", "SIGNATURE_INVALID")),
            "repeated_issues": [{"code": c, "times": n} for c, n in codes.most_common() if n > 1],
            "invoice_ids": [str(i.id) for i in sorted(invs, key=lambda x: x.invoice_date or date.min, reverse=True)][:20],
        })
    for v in out:
        v["attention_score"] = (v["gst_errors"] * 2 + v["gstr2b_mismatches"] * 3 + v["einvoice_problems"] * 5
                                + (1 if v["itc_at_risk"] > 0 else 0) * 2)
    return sorted(out, key=lambda v: (-v["attention_score"], -v["purchase_value"]))


# ----------------------------------------------------------------------------- anomalies
def _robust_z(x: float, xs: list[float]) -> float | None:
    if len(xs) < 4:
        return None
    med = statistics.median(xs)
    mad = statistics.median([abs(v - med) for v in xs]) or (statistics.pstdev(xs) / 1.4826 if len(set(xs)) > 1 else 0)
    if not mad:
        return None
    return abs(x - med) / (1.4826 * mad)


def anomalies(db: Session) -> dict:
    """Risk indicators, NOT confirmed fraud. Each needs enough history to be judged."""
    invs = [i for i in _invoices(db) if i.status not in ("REJECTED", "FAILED")]
    by_vendor: dict[str, list[Invoice]] = defaultdict(list)
    for i in invs:
        by_vendor[i.vendor_gstin_raw or (i.vendor_name_raw or "?")].append(i)
    items: list[dict] = []
    insufficient = 0

    def add(inv: Invoice, kind: str, score: int, reason: str):
        items.append({"invoice_id": str(inv.id), "invoice_number": inv.invoice_number, "vendor": inv.vendor_name_raw,
                      "amount": money(inv.grand_total), "kind": kind, "score": score, "reason": reason})

    for vk, vinvs in by_vendor.items():
        amounts = [float(i.grand_total) for i in vinvs if i.grand_total]
        if len(amounts) < 5:
            insufficient += 1
        for i in vinvs:
            if not i.grand_total:
                continue
            others = [float(o.grand_total) for o in vinvs if o is not i and o.grand_total]
            z = _robust_z(float(i.grand_total), others)
            if z is not None and z >= 3.5:
                add(i, "unusual_amount", min(95, int(40 + z * 8)),
                    f"Amount {inr(i.grand_total)} is far from this vendor's usual invoice value "
                    f"(median {inr(statistics.median(others))} over {len(others)} other invoices).")
        # price deviation for the same item from the same vendor
        item_prices: dict[str, list[tuple[Invoice, float]]] = defaultdict(list)
        for i in vinvs:
            for li in i.items:
                if li.description and li.unit_price:
                    item_prices[li.description.strip().lower()].append((i, float(li.unit_price)))
        for desc, rows in item_prices.items():
            if len(rows) < 3:
                continue
            for inv, price in rows:
                others = [p for x, p in rows if x is not inv]
                med = statistics.median(others)
                if med and abs(price - med) / med >= 0.3:
                    add(inv, "price_deviation", 55, f"'{desc}' billed at {inr(price)} per unit vs this vendor's usual "
                        f"{inr(med)} ({round(100 * (price - med) / med)}% difference).")
        # abnormal frequency: several invoices from one vendor on one day
        for d, n in Counter(i.invoice_date for i in vinvs if i.invoice_date).items():
            if n >= 3:
                for i in [x for x in vinvs if x.invoice_date == d]:
                    add(i, "abnormal_frequency", 45, f"{n} invoices from this vendor dated {d:%d %b %Y}.")
    for i in invs:
        for li in i.items:
            if li.gst_rate is not None and Decimal(li.gst_rate) not in STANDARD_RATES:
                add(i, "unusual_gst_rate", 60, f"Line {li.line_no} uses a {li.gst_rate}% GST rate, which is not a standard slab.")
        if any(f.code == "HSN_RATE_MISMATCH" for f in i.findings):
            add(i, "unusual_gst_rate", 50, "GST rate differs from the usual rate for the item's HSN/SAC code.")
        if any(f.category == "duplicate" for f in i.findings):
            add(i, "duplicate_like", 70, "Looks like an invoice already recorded (same vendor/number/amount or file).")
        if i.grand_total and i.grand_total >= 50000 and i.grand_total % 10000 == 0:
            add(i, "round_amount", 25, f"Exact round amount {inr(i.grand_total)}; worth a second look.")
    items.sort(key=lambda x: -x["score"])
    return {"items": items, "vendors_with_insufficient_history": insufficient,
            "note": "These are risk indicators for review, not confirmed fraud. Vendors with fewer than 5 invoices "
                    "have too little history for amount checks."}


# ----------------------------------------------------------------------------- risk centre
def risk_items(db: Session) -> list[dict]:
    """'What needs your attention?' -- every item comes from an actual system finding."""
    out: list[dict] = []

    def add(sev, cat, title, reason, inv: Invoice | None = None, amount=None, action="", vendor=None, key=None):
        out.append({"key": key or f"{cat}:{inv.id if inv else title}", "severity": sev, "category": cat,
                    "title": title, "reason": reason, "invoice_id": str(inv.id) if inv else None,
                    "invoice_number": inv.invoice_number if inv else None,
                    "vendor": vendor or (inv.vendor_name_raw if inv else None),
                    "amount_at_stake": money(amount) if amount is not None else None, "next_action": action})

    for i in _invoices(db):
        if i.status == "REJECTED":
            continue
        open_ = i.status == "NEEDS_REVIEW"
        if i.einvoice_status == "SIGNATURE_INVALID":
            add("Critical", "E-invoice", "Forged e-invoice QR signature", "The QR code was not signed by the government portal.",
                i, i.grand_total, "Contact the vendor before paying; do not claim ITC on this invoice.")
        elif i.einvoice_status == "MISMATCH":
            add("Critical", "E-invoice", "Invoice doesn't match its e-invoice QR",
                "Printed details differ from the government-signed QR code.", i, i.grand_total,
                "Ask the vendor for the original invoice.")
        a = i.itc
        if a and a.status == "REVERSAL_DUE":
            add("Critical", "ITC", "ITC reversal due (unpaid > 180 days)", "Vendor not paid within 180 days (Rule 37).",
                i, a.at_risk_itc, "Pay the vendor, or reverse the credit in your next return.")
        if a and a.status == "LAPSED":
            add("Critical", "ITC", "ITC claim deadline passed", "Section 16(4) time limit has passed.", i, a.blocked_itc,
                "Confirm with your CA; this credit can no longer be claimed.")
        if open_ and any(f.category == "duplicate" and f.severity == "ERROR" for f in i.findings):
            add("Critical", "Duplicate", "Possible duplicate invoice", next(f.message for f in i.findings if f.category == "duplicate"),
                i, i.grand_total, "Check it isn't paid or claimed twice, then approve or reject.")
        if i.gstr2b_status == "MISSING_IN_2B":
            add("High", "GSTR-2B", "Missing from GSTR-2B", "The vendor hasn't reported this invoice to the government.",
                i, a.at_risk_itc if a else None, "Ask the vendor to file their GSTR-1.")
        errs = [f for f in i.findings if f.severity == "ERROR" and f.category == "validation"]
        if open_ and errs:
            add("High", "Validation", f"{len(errs)} GST validation error{'s' if len(errs) > 1 else ''}",
                "; ".join(f.message for f in errs[:2]), i, i.grand_total, "Review and correct, or reject the invoice.")
        if any(r.status in ("MISMATCH", "PO_NOT_FOUND") for r in i.reconciliation):
            add("High", "PO", "Invoice doesn't match its purchase order",
                "Quantity or price differs from the PO.", i, None, "Compare with the PO and confirm with purchasing.")
        if a and a.status == "NEEDS_REVIEW" and (a.review_itc or 0) > 0:
            add("Review", "ITC", "ITC needs a decision", next((r["message"] for r in (a.reasons or []) if r.get("severity") == "WARNING"),
                "Some lines may be blocked credit."), i, a.review_itc, "Decide whether the expense qualifies for ITC.")
    for r in db.execute(select(Gstr2bRecord).where(Gstr2bRecord.match_status.in_(TWO_B_MISMATCH))).scalars():
        tax = (r.igst or 0) + (r.cgst or 0) + (r.sgst or 0) + (r.cess or 0)
        if r.match_status == "AMOUNT_MISMATCH":
            add("High", "GSTR-2B", "GSTR-2B amount mismatch", r.match_notes or "Amounts differ from your books.", None, tax,
                "Check the invoice amount with the vendor.", vendor=r.supplier_name, key=f"2b:{r.id}")
        else:
            add("Review", "GSTR-2B", f"In GSTR-2B but not in your books: {r.invoice_number}",
                "The vendor reported an invoice you haven't recorded.", None, tax,
                "Find and upload the invoice, or confirm it isn't yours.", vendor=r.supplier_name, key=f"2b:{r.id}")
    seen = {x["invoice_id"] for x in out if x["invoice_id"]}
    for an in anomalies(db)["items"]:
        if an["score"] >= 50 and an["invoice_id"] not in seen:
            seen.add(an["invoice_id"])
            out.append({"key": f"anomaly:{an['invoice_id']}:{an['kind']}", "severity": "Review", "category": "Anomaly",
                        "title": "Unusual invoice (risk indicator)", "reason": an["reason"], "invoice_id": an["invoice_id"],
                        "invoice_number": an["invoice_number"], "vendor": an["vendor"], "amount_at_stake": an["amount"],
                        "next_action": "Take a second look; this is not confirmed fraud."})
    order = {"Critical": 0, "High": 1, "Review": 2}
    return sorted(out, key=lambda x: (order[x["severity"]], -(x["amount_at_stake"] or 0)))


# ----------------------------------------------------------------------------- investigation
def investigate(db: Session, invoice_id) -> dict | None:
    inv = db.get(Invoice, invoice_id)
    if inv is None:
        return None
    stages = []

    def stage(name, status, summary, evidence=None):
        stages.append({"stage": name, "status": status, "summary": summary, "evidence": evidence or []})

    conf = inv.extraction_confidence or {}
    low = [k for k, v in conf.items() if isinstance(v, (int, float)) and v < 0.7]
    stage("Document & OCR", "pass" if inv.items else "warn",
          f"Read from {inv.source_filename}." + (" No line items could be read." if not inv.items else ""),
          [{"field": k, "confidence": round(float(v), 2)} for k, v in conf.items() if isinstance(v, (int, float))])
    missing = [f for f, v in (("Vendor GSTIN", inv.vendor_gstin_raw), ("Invoice number", inv.invoice_number),
                              ("Invoice date", inv.invoice_date), ("Grand total", inv.grand_total)) if not v]
    stage("Extraction", "fail" if len(missing) >= 2 else "warn" if missing or low else "pass",
          ("Missing: " + ", ".join(missing) + ". " if missing else "All key fields found. ")
          + (f"Low confidence on: {', '.join(low)}." if low else ""),
          [{"field": "Overall confidence", "value": f"{round(float(inv.confidence_score or 0) * 100)}%"}])
    val = [f for f in inv.findings if f.category == "validation" and f.severity != "INFO"]
    stage("GST validation", "fail" if any(f.severity == "ERROR" for f in val) else "warn" if val else "pass",
          _plural(sum(f.severity == 'ERROR' for f in val), "error") + ", " + _plural(sum(f.severity == 'WARNING' for f in val), "warning") + ".",
          [{"code": f.code, "severity": f.severity, "message": f.message, "field": f.field,
            "expected": f.expected, "actual": f.actual} for f in val])
    recon = inv.reconciliation
    po_bad = [r for r in recon if r.status not in ("MATCHED", "NO_PO")]
    stage("Purchase order", "na" if all(r.status == "NO_PO" for r in recon) else "fail" if po_bad else "pass",
          "No PO referenced." if all(r.status == "NO_PO" for r in recon) else f"{len(po_bad)} line(s) differ from the PO." if po_bad else "Matches the PO.",
          [{"invoice_line": r.invoice_line_no, "status": r.status, "qty_invoiced": str(r.qty_invoiced), "qty_po": str(r.qty_po),
            "price_invoiced": str(r.price_invoiced), "price_po": str(r.price_po)} for r in po_bad])
    dup = [f for f in inv.findings if f.category == "duplicate"]
    stage("Duplicate check", "fail" if any(f.severity == "ERROR" for f in dup) else "warn" if dup else "pass",
          dup[0].message if dup else "No duplicates found.", [{"code": f.code, "message": f.message} for f in dup])
    ed = inv.einvoice_data or {}
    stage("E-invoice QR", {"VERIFIED": "pass", "UNVERIFIED": "pass", "NO_QR": "na"}.get(inv.einvoice_status or "NO_QR", "fail"),
          {"VERIFIED": "Signed QR verified; matches the printout.", "UNVERIFIED": "QR read and matches; signature not checked.",
           "NO_QR": "No e-invoice QR on this document.", "MISMATCH": "Printout differs from the signed QR.",
           "SIGNATURE_INVALID": "QR signature is not from the government portal.", "MALFORMED": "QR unreadable."}.get(
              inv.einvoice_status or "NO_QR", inv.einvoice_status),
          [c for c in ed.get("comparisons", []) if c.get("match") is False])
    rec = db.get(Gstr2bRecord, inv.gstr2b_record_id) if inv.gstr2b_record_id else None
    stage("GSTR-2B", {"IN_2B": "pass" if not rec or rec.match_status == "MATCHED" else "warn",
                      "MISSING_IN_2B": "fail"}.get(inv.gstr2b_status or "", "na"),
          {"IN_2B": "Found in GSTR-2B." + (f" {rec.match_notes}" if rec and rec.match_notes else ""),
           "MISSING_IN_2B": "Not reported by the vendor in GSTR-2B."}.get(inv.gstr2b_status or "", "No GSTR-2B imported for this period yet."),
          [{"match_status": rec.match_status, "notes": rec.match_notes}] if rec else [])
    a = inv.itc
    stage("Input tax credit", "na" if not a or a.status == "NOT_APPLICABLE" else
          "pass" if a.status in ("ELIGIBLE", "AWAITING_2B") else "warn" if a.status in ("NEEDS_REVIEW", "PARTIALLY_ELIGIBLE") else "fail",
          f"Status {a.status.replace('_', ' ').lower()}: claimable {inr(a.eligible_itc)}, at risk {inr(a.at_risk_itc)}, "
          f"blocked {inr(a.blocked_itc)}." if a else "Not assessed.",
          [{"code": r["code"], "severity": r["severity"], "message": r["message"]} for r in (a.reasons or [])] if a else [])
    vkey = inv.vendor_gstin_raw or f"name:{(inv.vendor_name_raw or 'Unknown vendor').strip()}"
    vp = next((v for v in vendor_profiles(db) if v["vendor_key"] == vkey), None)
    stage("Vendor history", "warn" if vp and vp["attention_score"] >= 5 else "pass" if vp else "na",
          f"{vp['invoice_count']} invoices from this vendor, {vp['gst_errors']} GST errors, "
          f"{vp['gstr2b_mismatches']} GSTR-2B mismatches." if vp else "No history.",
          [{k: vp[k] for k in ("invoice_count", "purchase_value", "average_invoice_value", "gst_errors",
                               "gstr2b_mismatches", "filing_rate_pct")}] if vp else [])
    an = [x for x in anomalies(db)["items"] if x["invoice_id"] == str(inv.id)]
    stage("Anomaly detection", "warn" if an else "pass",
          f"{len(an)} risk indicator(s)." if an else "Nothing unusual compared with history.",
          [{"kind": x["kind"], "score": x["score"], "reason": x["reason"]} for x in an])
    return {"invoice": {"id": str(inv.id), "invoice_number": inv.invoice_number, "vendor": inv.vendor_name_raw,
                        "vendor_gstin": inv.vendor_gstin_raw, "invoice_date": inv.invoice_date.isoformat() if inv.invoice_date else None,
                        "grand_total": money(inv.grand_total), "gst": money(tax_of(inv)), "status": inv.status},
            "stages": stages,
            "verdict": "fail" if any(s["status"] == "fail" for s in stages) else "warn" if any(s["status"] == "warn" for s in stages) else "pass"}
