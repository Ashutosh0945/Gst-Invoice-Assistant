"""v0.6: upload reliability, investigation, GSTR-2B queue, duplicates, anomaly ML, forecasting, action centre, Copilot evidence."""
from datetime import date, timedelta
from decimal import Decimal

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from backend.api.main import app
from backend.db.models import AnomalyScore, AuditLog, Document, DuplicateCandidate, Invoice
from backend.synthetic.generate import generate_invoice


def _up(c, seed, key=None, err=None, name=None):
    si = generate_invoice(seed=seed, n_items=2, inject_error=err)
    h = {"Idempotency-Key": key} if key else {}
    r = c.post("/api/v1/invoices", files={"file": (name or f"i{seed}.pdf", si.pdf_bytes, "application/pdf")}, headers=h)
    assert r.status_code in (200, 201), r.text
    return r.json()


# ------------------------------------------------------------------ 1. upload reliability
def test_unsupported_empty_and_corrupt_files(db):
    c = TestClient(app, raise_server_exceptions=False)
    assert c.post("/api/v1/invoices", files={"file": ("x.exe", b"MZ..", "application/octet-stream")}).status_code == 415
    assert c.post("/api/v1/invoices", files={"file": ("x.pdf", b"", "application/pdf")}).status_code == 422
    r = c.post("/api/v1/invoices", files={"file": ("bad.pdf", b"%PDF-1.4 garbage not a pdf", "application/pdf")})
    assert r.status_code >= 400 and "detail" in r.json()          # clear error, not a crash page


def test_idempotent_retry_and_original_document_kept(db):
    c = TestClient(app)
    a = _up(c, 11, key="sha256-abc")
    b = _up(c, 11, key="sha256-abc")                               # client retry after a dropped connection
    assert a["id"] == b["id"] and db.execute(select(func.count(Invoice.id))).scalar() == 1
    d = c.get(f"/api/v1/invoices/{a['id']}/document")
    assert d.status_code == 200 and d.content.startswith(b"%PDF")
    assert db.execute(select(Document).where(Document.kind == "original")).scalars().first().size_bytes == len(d.content)


# ------------------------------------------------------------------ 3. investigation workspace
def test_investigation_correct_revalidate_decide_audit(db):
    c = TestClient(app)
    inv = _up(c, 21, err="arithmetic")
    ws = c.get(f"/api/v1/invoices/{inv['id']}/workspace").json()
    errs = [f for f in ws["findings"] if f["severity"] == "ERROR"]
    assert errs and all(f["rule"] and f["recommended_action"] for f in errs)
    c.post(f"/api/v1/invoices/{inv['id']}/investigation", json={"actor": "Priya", "status": "under_review", "note": "Checking line 1"})
    rv = c.post(f"/api/v1/invoices/{inv['id']}/revalidate", json={"actor": "Priya"}).json()
    assert set(rv) == {"before", "after", "resolved", "new"}
    ws = c.post(f"/api/v1/invoices/{inv['id']}/investigation", json={"actor": "Priya", "decision": "rejected", "note": "Vendor to reissue"}).json()
    assert ws["investigation"]["status"] == "resolved" and ws["investigation"]["decision"] == "rejected"
    assert ws["notes"][0]["text"] == "Checking line 1"
    acts = {a["action"] for a in ws["audit"]}
    assert {"INVESTIGATION_UPDATED", "REVALIDATED"} <= acts


# ------------------------------------------------------------------ 10. duplicates
def test_near_duplicate_found_recurring_invoice_not_flagged():
    from backend.ml.duplicates import pair_signals, score_pair

    class I:  # minimal stand-in with the fields the scorer reads
        def __init__(self, no, total, d, h="x", items=()):
            self.invoice_number, self.grand_total, self.subtotal = no, Decimal(total), Decimal(total) / Decimal("1.18")
            self.total_cgst = self.total_sgst = Decimal(total) * Decimal("0.0763"); self.total_igst = None
            self.invoice_date, self.document_hash, self.vendor_gstin_raw = d, h, "27AAPFU0939F1ZV"
            self.items = [type("L", (), {"description": t})() for t in items]
    d = date(2026, 8, 1)
    near = score_pair(pair_signals(I("INV/2026/0045", 11800, d, "a", ["Toner"]), I("INV-2026-45", 11800, d, "b", ["Toner"])))
    recurring = score_pair(pair_signals(I("RENT/07", 50000, d, "a", ["Office rent"]), I("RENT/08", 50000, d + timedelta(days=31), "b", ["Office rent"])))
    different = score_pair(pair_signals(I("INV/1", 11800, d, "a"), I("INV/1", 11800, d, "a")))
    assert near[1] in ("likely", "exact") and recurring[1] is None and different[1] == "exact"


def test_duplicate_candidate_review_never_deletes(db):
    c = TestClient(app)
    a = _up(c, 31)
    si = generate_invoice(seed=31, n_items=2)
    pdf2 = si.pdf_bytes + b"\n%% re-saved copy"                    # same content, different file hash
    b = c.post("/api/v1/invoices", files={"file": ("copy.pdf", pdf2, "application/pdf")}).json()
    cands = c.get("/api/v1/duplicates/candidates").json()
    assert cands and {cands[0]["a"]["id"], cands[0]["b"]["id"]} == {a["id"], b["id"]} and "not a probability" in cands[0]["score_label"]
    c.post(f"/api/v1/duplicates/candidates/{cands[0]['id']}/decision", json={"actor": "Priya", "decision": "confirmed"})
    assert db.execute(select(func.count(Invoice.id))).scalar() == 2      # nothing deleted or merged
    assert db.get(DuplicateCandidate, __import__("uuid").UUID(cands[0]["id"])).status == "confirmed"


# ------------------------------------------------------------------ 9. anomaly ML
def test_anomaly_needs_enough_data(db):
    c = TestClient(app)
    for s in range(3):
        _up(c, 40 + s)
    r = c.post("/api/v1/ml/anomaly/train").json()
    assert r["status"] == "insufficient_data" and "20" in r["message"]


def test_anomaly_flags_injected_outlier_reproducibly_and_never_blocks_upload(db, monkeypatch):
    c = TestClient(app)
    ids = [_up(c, 100 + s)["id"] for s in range(30)]
    target = db.get(Invoice, __import__("uuid").UUID(ids[7]))
    target.grand_total = (target.grand_total or Decimal(1000)) * 60          # an implausible amount
    db.commit()
    r = c.post("/api/v1/ml/anomaly/train").json()
    assert r["status"] == "trained" and r["scored"] >= 25
    top = c.get("/api/v1/ml/anomaly/scores?limit=3").json()
    assert ids[7] in [t["invoice_id"] for t in top] and all("not" not in str(t["priority"]) for t in top)
    s1 = {a.invoice_id: float(a.score) for a in db.execute(select(AnomalyScore)).scalars()}
    from backend.ml.anomaly import score_invoices, active_model
    score_invoices(db, list(db.execute(select(Invoice)).scalars()), active_model(db)); db.commit()
    s2 = {a.invoice_id: float(a.score) for a in db.execute(select(AnomalyScore)).scalars()}
    assert s1 == s2                                                       # same model + same data -> same scores
    import backend.ml.iforest as IF
    monkeypatch.setattr(IF, "score", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("model broken")))
    assert c.post("/api/v1/invoices", files={"file": ("z.pdf", generate_invoice(seed=999).pdf_bytes, "application/pdf")}).status_code == 201


# ------------------------------------------------------------------ 11. forecasting
def test_forecast_insufficient_history_and_honest_selection():
    from backend.ml.forecasting import forecast_series
    short = forecast_series([f"2026-0{m}" for m in range(1, 6)], np.array([1.0, 2, 3, 4, 5]))
    assert short["status"] == "insufficient_history" and short["history"]
    months = [f"2025-{m:02d}" for m in range(1, 13)]
    trend = forecast_series(months, np.array([100.0 + 10 * k for k in range(12)]))
    assert trend["status"] == "ok" and trend["model"] != "naive (last month)" and trend["forecast"][0]["forecast"] > 200
    flat = forecast_series(months, np.array([100.0] * 12))
    assert flat["model"] == "naive (last month)" and "naive" in flat["selection"]          # nothing beats naive -> naive
    assert all(f["low"] <= f["forecast"] <= f["high"] for f in trend["forecast"])


# ------------------------------------------------------------------ 4. GSTR-2B queue + metrics
def test_gstr2b_queue_metrics_and_resolution(db):
    import json
    c = TestClient(app)
    inv = _up(c, 400)
    d = date.fromisoformat(inv["invoice_date"])
    period = f"{d.month:02d}{d.year}"
    line = lambda no, txval, tax: {"inum": no, "dt": d.strftime("%d-%m-%Y"), "val": float(txval) + 2 * tax, "pos": "27", "rev": "N",  # noqa: E731
                                   "itcavl": "Y", "items": [{"txval": float(txval), "rt": 18, "cgst": tax, "sgst": tax}]}
    sub = float(inv["subtotal"])
    book_tax = sum(float(inv[k] or 0) for k in ("total_cgst", "total_sgst", "total_igst"))
    half = round((book_tax + 50) / 2, 2)                                                         # 2B tax deliberately off by 50
    payload = {"data": {"rtnprd": period, "gstin": inv["buyer_gstin_raw"] or "27AAAAA0000A1Z5", "docdata": {"b2b": [
        {"ctin": inv["vendor_gstin_raw"], "trdnm": "Vendor", "inv": [line(inv["invoice_number"], sub, half), line("ZZ/999", 500, 45)]}]}}}
    r = c.post("/api/v1/gstr2b/import", files={"file": ("2b.json", json.dumps(payload).encode(), "application/json")})
    assert r.status_code in (200, 201), r.text
    q = c.get("/api/v1/gstr2b/queue").json()
    cats = {x["category"] for x in q}
    assert {"Tax mismatch", "Missing from purchase records"} <= cats
    m = c.get("/api/v1/gstr2b/metrics").json()
    assert m["total_imported_records"] == 2 and m["matched_records"] == 0 and abs(m["tax_difference"] - 50.0) < 0.05
    rec = next(x for x in q if x["category"] == "Missing from purchase records")
    p = c.patch(f"/api/v1/gstr2b/records/{rec['id']}", json={"actor": "Priya", "resolution_status": "resolved", "note": "Not our invoice"})
    assert p.json()["resolution_status"] == "resolved" and c.get("/api/v1/gstr2b/metrics").json()["resolved_issues"] == 1
    r2 = c.post("/api/v1/gstr2b/import", files={"file": ("2b.json", json.dumps(payload).encode(), "application/json")})
    assert c.get("/api/v1/gstr2b/metrics").json()["total_imported_records"] == 2       # re-import doesn't duplicate


def test_action_center_matches_database(db):
    c = TestClient(app)
    for s in range(4):
        _up(c, 200 + s, err="arithmetic" if s == 0 else None)
    ac = c.get("/api/v1/ai/action-center").json()
    assert ac["overview"]["total_invoices"] == db.execute(select(func.count(Invoice.id))).scalar()
    assert ac["overview"]["needs_review"] == db.execute(select(func.count(Invoice.id)).where(Invoice.status == "NEEDS_REVIEW")).scalar()
    assert ac["priority_actions"] == sorted(ac["priority_actions"], key=lambda a: -a["priority_score"])
    assert "priority_score" in ac["definitions"] and ac["overview"]["gstr2b_match_rate"] is None   # no 2B imported -> no fake rate


# ------------------------------------------------------------------ 5. Copilot evidence
def test_copilot_answers_carry_evidence_and_admit_missing_data(db):
    c = TestClient(app)
    _up(c, 300, err="arithmetic")
    r = c.post("/api/v1/ai/copilot", json={"message": "Which invoices require manual review?"}).json()
    assert r["intent"] == "review_queue" and r["evidence"]["data_sources"] == ["invoices"] and r["evidence"]["records"]
    assert "verified database facts" in r["evidence"]["response_categories"]
    t = c.post("/api/v1/ai/copilot", json={"message": "What is the total tax difference in unresolved reconciliations?"}).json()
    assert t["intent"] == "tax_difference" and "no unresolved" in t["answer"].lower()
    f = c.post("/api/v1/ai/copilot", json={"message": "forecast next month GST"}).json()
    assert f["intent"] == "forecast" and "insufficient data" in f["evidence"]["response_categories"]
