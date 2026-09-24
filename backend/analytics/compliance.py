"""Compliance analytics (ITC, GSTR-2B, e-invoice, vendor risk) as JSON-ready dicts. Pandas-free."""
from __future__ import annotations

import json
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.db.models import Gstr2bImport, Gstr2bRecord, Invoice, ItcAssessment, ValidationFinding

ZERO = Decimal("0")
BENCHMARK_PATH = Path(__file__).resolve().parents[2] / "data" / "benchmarks" / "results.json"


def _d(v) -> Decimal:
    return Decimal(str(v)) if v is not None else ZERO


def itc_summary(db: Session) -> dict:
    rows = db.execute(select(
        ItcAssessment.status, func.count(ItcAssessment.id),
        func.sum(ItcAssessment.total_itc), func.sum(ItcAssessment.eligible_itc),
        func.sum(ItcAssessment.blocked_itc), func.sum(ItcAssessment.review_itc),
        func.sum(ItcAssessment.at_risk_itc),
    ).group_by(ItcAssessment.status)).all()
    by_status = [{"status": s, "invoice_count": c, "total_itc": _d(t), "eligible_itc": _d(e),
                  "blocked_itc": _d(b), "review_itc": _d(r), "at_risk_itc": _d(a)}
                 for s, c, t, e, b, r, a in rows]
    tot = lambda k: sum((r[k] for r in by_status), ZERO)  # noqa: E731
    return {
        "total_itc": tot("total_itc"), "eligible_itc": tot("eligible_itc"), "blocked_itc": tot("blocked_itc"),
        "review_itc": tot("review_itc"), "at_risk_itc": tot("at_risk_itc"),
        "credit_at_risk": tot("at_risk_itc") + tot("review_itc"),
        "by_status": sorted(by_status, key=lambda r: -r["total_itc"]),
    }


def itc_by_month(db: Session) -> list[dict]:
    rows = db.execute(select(Invoice.invoice_date, ItcAssessment.eligible_itc, ItcAssessment.blocked_itc,
                             ItcAssessment.review_itc, ItcAssessment.at_risk_itc)
                      .join(ItcAssessment, ItcAssessment.invoice_id == Invoice.id)
                      .where(Invoice.invoice_date.is_not(None))).all()
    acc: dict[str, dict] = defaultdict(lambda: {"eligible": ZERO, "blocked": ZERO, "review": ZERO, "at_risk": ZERO})
    for d, e, b, r, a in rows:
        m = acc[d.strftime("%Y-%m")]
        m["eligible"] += _d(e); m["blocked"] += _d(b); m["review"] += _d(r); m["at_risk"] += _d(a)
    return [{"month": k, **v} for k, v in sorted(acc.items())][-12:]


def itc_assessments(db: Session, status: str | None = None, limit: int = 200) -> list[dict]:
    q = (select(Invoice, ItcAssessment).join(ItcAssessment, ItcAssessment.invoice_id == Invoice.id)
         .order_by(ItcAssessment.at_risk_itc.desc(), ItcAssessment.total_itc.desc()).limit(limit))
    if status:
        q = q.where(ItcAssessment.status == status)
    out = []
    for inv, a in db.execute(q).all():
        out.append({
            "invoice_id": str(inv.id), "invoice_number": inv.invoice_number, "vendor_name": inv.vendor_name_raw,
            "vendor_gstin": inv.vendor_gstin_raw, "invoice_date": inv.invoice_date, "grand_total": inv.grand_total,
            "gstr2b_status": inv.gstr2b_status, "payment_date": inv.payment_date,
            "status": a.status, "total_itc": a.total_itc, "eligible_itc": a.eligible_itc,
            "blocked_itc": a.blocked_itc, "review_itc": a.review_itc, "at_risk_itc": a.at_risk_itc,
            "claim_deadline": a.claim_deadline, "payment_due_by": a.payment_due_by, "reasons": a.reasons or [],
        })
    return out


def gstr2b_imports(db: Session) -> list[dict]:
    imports = db.execute(select(Gstr2bImport).order_by(Gstr2bImport.return_period.desc())).scalars().all()
    out = []
    for imp in imports:
        counts = dict(db.execute(select(Gstr2bRecord.match_status, func.count(Gstr2bRecord.id))
                                 .where(Gstr2bRecord.import_id == imp.id)
                                 .group_by(Gstr2bRecord.match_status)).all())
        m, y = int(imp.return_period[:2]), int(imp.return_period[2:])
        missing = db.execute(select(func.count(Invoice.id)).where(
            Invoice.gstr2b_status == "MISSING_IN_2B",
            func.extract("month", Invoice.invoice_date) == m, func.extract("year", Invoice.invoice_date) == y,
        )).scalar() or 0
        tax = db.execute(select(func.sum(Gstr2bRecord.igst + Gstr2bRecord.cgst + Gstr2bRecord.sgst + Gstr2bRecord.cess))
                         .where(Gstr2bRecord.import_id == imp.id)).scalar()
        out.append({"id": str(imp.id), "return_period": imp.return_period, "gstin": imp.gstin,
                    "source_filename": imp.source_filename, "generated_on": imp.generated_on,
                    "record_count": imp.record_count, "imported_at": imp.imported_at,
                    "total_tax": _d(tax), "status_counts": counts, "missing_in_2b": missing})
    return out


def gstr2b_records(db: Session, import_id, status: str | None = None) -> list[dict]:
    q = select(Gstr2bRecord).where(Gstr2bRecord.import_id == import_id).order_by(
        Gstr2bRecord.match_status, Gstr2bRecord.supplier_name)
    if status:
        q = q.where(Gstr2bRecord.match_status == status)
    return [{
        "id": str(r.id), "supplier_gstin": r.supplier_gstin, "supplier_name": r.supplier_name,
        "invoice_number": r.invoice_number, "invoice_date": r.invoice_date, "taxable_value": r.taxable_value,
        "total_tax": _d(r.igst) + _d(r.cgst) + _d(r.sgst) + _d(r.cess), "itc_available": r.itc_available,
        "itc_unavailable_reason": r.itc_unavailable_reason, "reverse_charge": r.reverse_charge,
        "match_status": r.match_status, "match_score": r.match_score, "match_notes": r.match_notes,
        "matched_invoice_id": str(r.matched_invoice_id) if r.matched_invoice_id else None,
    } for r in db.execute(q).scalars().all()]


def missing_in_2b(db: Session) -> list[dict]:
    q = (select(Invoice, ItcAssessment).outerjoin(ItcAssessment, ItcAssessment.invoice_id == Invoice.id)
         .where(Invoice.gstr2b_status == "MISSING_IN_2B").order_by(Invoice.invoice_date))
    return [{"invoice_id": str(i.id), "invoice_number": i.invoice_number, "vendor_name": i.vendor_name_raw,
             "vendor_gstin": i.vendor_gstin_raw, "invoice_date": i.invoice_date, "grand_total": i.grand_total,
             "at_risk_itc": a.at_risk_itc if a else None} for i, a in db.execute(q).all()]


def einvoice_summary(db: Session) -> dict:
    counts = dict(db.execute(select(Invoice.einvoice_status, func.count(Invoice.id))
                             .group_by(Invoice.einvoice_status)).all())
    flagged = db.execute(select(Invoice).where(Invoice.einvoice_status.in_(
        ["MISMATCH", "SIGNATURE_INVALID", "MALFORMED"])).order_by(Invoice.created_at.desc()).limit(50)).scalars().all()
    recent = db.execute(select(Invoice).where(Invoice.irn.is_not(None))
                        .order_by(Invoice.created_at.desc()).limit(50)).scalars().all()
    row = lambda i: {"invoice_id": str(i.id), "invoice_number": i.invoice_number,  # noqa: E731
                     "vendor_name": i.vendor_name_raw, "grand_total": i.grand_total, "irn": i.irn,
                     "einvoice_status": i.einvoice_status,
                     "comparisons": (i.einvoice_data or {}).get("comparisons", [])}
    return {"counts": {k or "NOT_SCANNED": v for k, v in counts.items()},
            "flagged": [row(i) for i in flagged], "recent": [row(i) for i in recent]}


def vendor_risk(db: Session, limit: int = 50) -> list[dict]:
    invs = db.execute(select(Invoice).where(Invoice.vendor_gstin_raw.is_not(None))).scalars().all()
    errs = dict(db.execute(select(ValidationFinding.invoice_id, func.count(ValidationFinding.id))
                           .where(ValidationFinding.severity == "ERROR")
                           .group_by(ValidationFinding.invoice_id)).all())
    amt_mm = dict(db.execute(select(Gstr2bRecord.supplier_gstin, func.count(Gstr2bRecord.id))
                             .where(Gstr2bRecord.match_status == "AMOUNT_MISMATCH")
                             .group_by(Gstr2bRecord.supplier_gstin)).all())
    at_risk = dict(db.execute(select(Invoice.vendor_gstin_raw, func.sum(ItcAssessment.at_risk_itc))
                              .join(ItcAssessment, ItcAssessment.invoice_id == Invoice.id)
                              .group_by(Invoice.vendor_gstin_raw)).all())
    by_v: dict[str, list[Invoice]] = defaultdict(list)
    for i in invs:
        by_v[i.vendor_gstin_raw].append(i)

    out = []
    for gstin, rows in by_v.items():
        n = len(rows)
        in2b = sum(1 for r in rows if r.gstr2b_status == "IN_2B")
        miss = sum(1 for r in rows if r.gstr2b_status == "MISSING_IN_2B")
        checked = in2b + miss
        filing_rate = in2b / checked if checked else None
        err_count = sum(errs.get(r.id, 0) for r in rows)
        bad_einv = sum(1 for r in rows if r.einvoice_status in ("MISMATCH", "SIGNATURE_INVALID"))
        mm = amt_mm.get(gstin, 0)
        score = 100 * min(1.0, (
            0.60 * ((1 - filing_rate) if filing_rate is not None else 0)   # not filing = credit you can't claim
            + 0.15 * min(1.0, err_count / max(n, 1) / 2)
            + 0.25 * (1.0 if bad_einv else 0.0)                           # any QR problem is a fraud signal
            + 0.10 * min(1.0, mm / max(checked, 1))
        ))
        level = "High" if score >= 40 else "Medium" if score >= 20 else "Low"
        reasons = []
        if miss:
            reasons.append(f"{miss} of {checked} invoices not reported in GSTR-2B")
        if mm:
            reasons.append(f"{mm} amount mismatch{'es' if mm > 1 else ''} with GSTR-2B")
        if bad_einv:
            reasons.append(f"{bad_einv} e-invoice QR problem{'s' if bad_einv > 1 else ''}")
        if err_count:
            reasons.append(f"{err_count} validation error{'s' if err_count > 1 else ''}")
        out.append({
            "vendor_gstin": gstin, "vendor_name": next((r.vendor_name_raw for r in rows if r.vendor_name_raw), None),
            "invoice_count": n, "total_spend": sum((_d(r.grand_total) for r in rows), ZERO),
            "filing_rate": filing_rate, "missing_in_2b": miss, "amount_mismatches": mm,
            "einvoice_issues": bad_einv, "error_findings": err_count,
            "at_risk_itc": _d(at_risk.get(gstin)), "risk_score": round(score, 1), "risk_level": level,
            "reasons": reasons,
        })
    out.sort(key=lambda r: (-r["risk_score"], -r["total_spend"]))
    return out[:limit]


def benchmark_results() -> dict | None:
    if not BENCHMARK_PATH.exists():
        return None
    return json.loads(BENCHMARK_PATH.read_text())
