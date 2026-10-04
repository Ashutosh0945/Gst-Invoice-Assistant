"""Reports, forecast, what-if, reconciliation assistant, vendor intelligence, vendor message,
feedback loop. Same guarantees: numbers from data, nothing written, honest labels."""
import json
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from backend.api.main import app
from backend.db.models import FeedbackRecord, Invoice, ValidationFinding
from backend.synthetic.generate import generate_invoice


def _seed(c, n=5):
    ids = []
    for s in range(n):
        si = generate_invoice(seed=500 + s, n_items=2, inject_error="arithmetic" if s == 0 else None)
        ids.append(c.post("/api/v1/invoices", files={"file": (f"b{s}.pdf", si.pdf_bytes, "application/pdf")}).json()["id"])
    return ids


def test_reports_are_traceable_and_match_the_data(db):
    c = TestClient(app)
    _seed(c)
    for kind in ("monthly", "audit"):
        r = c.post(f"/api/v1/ai/reports/{kind}?period=all").json()
        f = r["facts"]
        assert f["processing"]["invoices"] == db.execute(select(func.count(Invoice.id))).scalar()
        errors = db.execute(select(func.count(ValidationFinding.id)).where(ValidationFinding.severity == "ERROR")).scalar()
        assert len(f["detailed_findings"]) == errors >= 1
        for d in f["detailed_findings"]:                       # every finding points at a real invoice
            assert c.get(f"/api/v1/invoices/{d['invoice_id']}").status_code == 200
    assert c.post("/api/v1/ai/reports/audit?period=all").json()["sections"][0] == "Executive Summary"


def test_forecast_needs_history_and_is_labelled_an_estimate(db):
    c = TestClient(app)
    _seed(c, 2)
    f = c.get("/api/v1/ai/forecast").json()
    assert f["status"] == "insufficient_history" and "Estimate" in f["label"] and f["forecast"] == []


def test_forecast_math(monkeypatch):
    from backend.ai import insights as I
    monkeypatch.setattr(I.F, "monthly_series", lambda db, n: [{"month": f"2026-0{m}", "gst": 1000.0 * m, "invoices": 1,
                                                              "purchase_value": 0, "itc_eligible": 0} for m in range(1, 7)])
    f = I.forecast(None, 2)
    assert f["status"] == "ok" and [x["estimate"] for x in f["forecast"]] == [7000.0, 8000.0]   # perfect linear trend
    assert f["forecast"][0]["low"] <= f["forecast"][0]["estimate"] <= f["forecast"][0]["high"]


def test_what_if_never_saves_and_uses_real_rules(db):
    c = TestClient(app)
    ids = _seed(c, 2)
    before = [(i.id, i.gstr2b_status, i.itc.status, i.itc.eligible_itc) for i in db.execute(select(Invoice)).scalars()]
    r = c.post("/api/v1/ai/whatif", json={"scenario": "purchases_change", "pct": 20}).json()
    gst = r["rows"][1]
    assert Decimal(str(gst["simulated"])) == (Decimal(str(gst["current"])) * Decimal("1.2")).quantize(Decimal("0.01"))
    w = c.post("/api/v1/ai/whatif", json={"scenario": "not_in_2b", "invoice_id": ids[1]}).json()
    assert w["status"]["simulated"] in ("NOT_IN_2B", "BLOCKED", "NOT_APPLICABLE") and "nothing" in w["note"].lower()
    u = c.post("/api/v1/ai/whatif", json={"scenario": "unpaid_180", "invoice_id": ids[1]}).json()
    assert u["status"]["simulated"] in ("REVERSAL_DUE", "BLOCKED", "NOT_APPLICABLE", "LAPSED")
    db.expire_all()
    assert before == [(i.id, i.gstr2b_status, i.itc.status, i.itc.eligible_itc) for i in db.execute(select(Invoice)).scalars()]
    assert c.post("/api/v1/ai/whatif", json={"scenario": "drop_table"}).status_code == 422


def test_vendor_message_uses_only_invoice_facts(db, monkeypatch):
    from backend.llm import explain as E
    c = TestClient(app)
    ids = _seed(c, 1)
    inv = c.get(f"/api/v1/invoices/{ids[0]}").json()
    m = c.post("/api/v1/ai/vendor-message", json={"invoice_id": ids[0]}).json()
    assert inv["invoice_number"] in m["subject"] and inv["invoice_number"] in m["body"] and "Review" in m["reminder"]
    monkeypatch.setattr(E, "chat", lambda *a, **k: "Dear vendor, please refund ₹4,44,444 for invoice 999.")
    bad = c.post("/api/v1/ai/vendor-message", json={"invoice_id": ids[0]}).json()
    assert "4,44,444" not in bad["body"] and bad["source"] == "rules"


def test_vendor_profile_links_to_invoices(db):
    c = TestClient(app)
    _seed(c, 3)
    v = c.get("/api/v1/ai/vendors").json()[0]
    p = c.get(f"/api/v1/ai/vendors/{v['vendor_key']}/profile?explain=true").json()
    assert p["profile"]["invoice_count"] == len(p["invoices"]) and p["summary"]["text"]
    assert c.get(f"/api/v1/invoices/{p['invoices'][0]['invoice_id']}").status_code == 200
    assert c.get("/api/v1/ai/vendors/NOPE/profile").status_code == 404


def test_po_reconciliation_assistant(db):
    c = TestClient(app)
    ids = _seed(c, 1)
    r = c.get(f"/api/v1/ai/reconcile/po/{ids[0]}").json()
    assert r["lines"] and r["explanation"]["text"]


def test_feedback_loop_records_prediction_and_correction(db):
    c = TestClient(app)
    ids = _seed(c, 1)
    inv = c.get(f"/api/v1/invoices/{ids[0]}").json()
    r = c.post(f"/api/v1/invoices/{ids[0]}/correct", json={"reviewer": "Priya",
               "header_fields": {"invoice_number": "FIXED-001", "vendor_name_raw": inv["vendor_name_raw"]}})
    assert r.status_code == 200
    recs = db.execute(select(FeedbackRecord)).scalars().all()
    by = {x.field: x for x in recs}
    assert by["invoice_number"].predicted_value == inv["invoice_number"] and by["invoice_number"].corrected_value == "FIXED-001"
    assert by["invoice_number"].was_correct is False and by["vendor_name_raw"].was_correct is True
    m = c.get("/api/v1/ai/feedback/metrics").json()
    assert m["total_feedback"] == 2 and m["enough_data"] is False and m["fields"] == []     # no metrics without enough data
    lines = c.get("/api/v1/ai/feedback/export").text.strip().splitlines()
    assert len(lines) == 2 and json.loads(lines[0])["field"]
