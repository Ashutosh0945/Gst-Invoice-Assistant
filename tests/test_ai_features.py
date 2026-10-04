"""AI layer: numbers must equal independent database calculations; AI text with invented
numbers must be rejected; AI must never write to the database; empty data is handled."""
import hashlib
import json
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from backend.api.main import app
from backend.db.models import Gstr2bRecord, Invoice, ItcAssessment
from backend.synthetic.generate import generate_invoice

KEY = {"X-API-Key": "test-console-key"}


def _client():
    return TestClient(app, headers=KEY)


def _seed(c, n=6):
    ids = []
    for seed in range(n):
        si = generate_invoice(seed=300 + seed, n_items=2, inject_error="arithmetic" if seed == 0 else None)
        r = c.post("/api/v1/invoices", files={"file": (f"i{seed}.pdf", si.pdf_bytes, "application/pdf")})
        assert r.status_code == 201, r.text
        ids.append(r.json()["id"])
    return ids


def _db_fingerprint(db):
    rows = db.execute(select(Invoice.id, Invoice.status, Invoice.grand_total, Invoice.gstr2b_status)).all()
    itc = db.execute(select(ItcAssessment.invoice_id, ItcAssessment.status, ItcAssessment.eligible_itc)).all()
    return hashlib.sha256(json.dumps(sorted(map(str, rows + itc))).encode()).hexdigest()


def test_empty_database_is_handled(db):
    c = _client()
    k = c.get("/api/v1/ai/kpis").json()
    assert k["total_invoices"] == 0 and k["total_purchase_value"] == 0
    ans = c.post("/api/v1/ai/copilot", json={"message": "Give me this month's GST summary"}).json()
    assert "no invoices" in ans["answer"].lower()
    assert c.get("/api/v1/ai/risks").json()["items"] == []
    assert c.post("/api/v1/ai/brief").status_code == 200


def test_kpis_match_independent_database_totals(db):
    c = _client()
    _seed(c)
    k = c.get("/api/v1/ai/kpis").json()
    live = db.execute(select(Invoice).where(Invoice.status.notin_(["REJECTED", "FAILED"]))).scalars().all()
    assert k["total_invoices"] == db.execute(select(func.count(Invoice.id))).scalar()
    assert Decimal(str(k["total_purchase_value"])) == sum((i.grand_total or 0) for i in live)
    gst = sum(sum((x or 0) for x in (i.total_cgst, i.total_sgst, i.total_igst, i.total_cess)) for i in live)
    assert Decimal(str(k["gst_amount"])) == gst
    assert Decimal(str(k["itc_eligible"])) == sum(a.eligible_itc for a in db.execute(select(ItcAssessment)).scalars()
                                                  if a.invoice.status not in ("REJECTED", "FAILED"))


def test_cfo_brief_numbers_come_from_backend(db):
    c = _client()
    _seed(c)
    b = c.post("/api/v1/ai/brief?period=all").json()
    k = c.get("/api/v1/ai/kpis").json()
    for key in ("total_invoices", "total_purchase_value", "gst_amount", "itc_eligible", "itc_at_risk"):
        assert b["facts"]["period_kpis"][key] == k[key]
    assert b["commentary"]["source"] == "rules"          # LLM disabled in tests -> rule text, clearly labelled


def test_ai_text_with_invented_numbers_is_rejected(db, monkeypatch):
    from backend.llm import explain as E

    c = _client()
    _seed(c)
    k = c.get("/api/v1/ai/kpis").json()
    monkeypatch.setattr(E, "chat", lambda *a, **kw: f"You have {k['total_invoices']} invoices.")
    ok = c.post("/api/v1/ai/copilot", json={"message": "Give me the GST summary overall"}).json()
    assert ok["answer_source"] == "ai"
    monkeypatch.setattr(E, "chat", lambda *a, **kw: "You spent ₹98,76,543 on 4321 invoices.")
    bad = c.post("/api/v1/ai/copilot", json={"message": "Give me the GST summary overall"}).json()
    assert bad["answer_source"] == "rules" and "98,76,543" not in bad["answer"] and "discarded" in bad["note"]
    monkeypatch.setattr(E, "chat", lambda *a, **kw: None)          # OpenRouter down / no key
    down = c.post("/api/v1/ai/copilot", json={"message": "How much ITC is at risk?"}).json()
    assert down["answer_source"] == "rules" and "₹" in down["answer"]


def test_ai_never_writes_to_the_database(db):
    c = _client()
    ids = _seed(c)
    before = _db_fingerprint(db)
    for q in ["Give me this month's GST summary", "How much ITC is at risk?", "Which vendors need attention?",
              "Show invoices above 1,000", "What needs my attention?", "Any unusual invoices?"]:
        assert c.post("/api/v1/ai/copilot", json={"message": q}).status_code == 200
    c.post("/api/v1/ai/brief"), c.get("/api/v1/ai/risks"), c.get(f"/api/v1/ai/investigate/{ids[0]}?explain=true")
    db.expire_all()
    assert _db_fingerprint(db) == before


@pytest.mark.parametrize("text, expect", [
    ("Show invoices above 50,000 from vendors with GSTR-2B mismatches", {"min_amount": 50000.0, "vendor_has_2b_mismatch": True}),
    ("Find invoices from ABC Technologies above 1 lakh", {"vendor": "abc technologies", "min_amount": 100000.0}),
    ("invoices between 10k and 2 lakh that need review", {"min_amount": 10000.0, "max_amount": 200000.0, "status": "NEEDS_REVIEW"}),
    ("invoices with errors last month", {"has_errors": True, "period": "last_month"}),
])
def test_smart_search_parses_to_whitelisted_filters(text, expect):
    from backend.ai.search import parse_rules

    got = parse_rules(text, []).model_dump(exclude_defaults=True)
    assert got == expect


def test_smart_search_rejects_unsafe_ai_filters(monkeypatch):
    from backend.ai import search as S
    from backend.llm import explain as E

    monkeypatch.setattr(E, "chat", lambda *a, **kw: '{"vendor": "x\\"; DROP TABLE invoices;--", "sql": "DELETE FROM invoices"}')
    assert S._llm_filters("anything") is None          # unknown key 'sql' -> whole filter rejected


def test_smart_search_results_are_correct(db):
    c = _client()
    _seed(c)
    res = c.post("/api/v1/ai/search", json={"query": "show invoices above 1,000"}).json()
    expect = db.execute(select(func.count(Invoice.id)).where(Invoice.grand_total >= 1000)).scalar()
    assert res["count"] == expect and all(r["grand_total"] >= 1000 for r in res["results"])


def test_investigation_covers_every_stage_and_findings(db):
    c = _client()
    ids = _seed(c, 2)
    inv = c.get(f"/api/v1/ai/investigate/{ids[0]}?explain=true").json()
    assert [s["stage"] for s in inv["stages"]] == ["Document & OCR", "Extraction", "GST validation", "Purchase order",
        "Duplicate check", "E-invoice QR", "GSTR-2B", "Input tax credit", "Vendor history", "Anomaly detection"]
    val = next(s for s in inv["stages"] if s["stage"] == "GST validation")
    assert val["status"] == "fail" and any(e["severity"] == "ERROR" for e in val["evidence"])
    assert inv["explanation"]["source"] == "rules"
    assert c.get("/api/v1/ai/investigate/00000000-0000-0000-0000-000000000000").status_code == 404


def test_risk_center_items_trace_to_real_records(db):
    c = _client()
    _seed(c)
    items = c.get("/api/v1/ai/risks").json()["items"]
    assert items and any(x["category"] == "Validation" for x in items)
    for x in items:
        if x["invoice_id"]:
            assert c.get(f"/api/v1/invoices/{x['invoice_id']}").status_code == 200


def test_copilot_follow_up_keeps_topic(db):
    c = _client()
    _seed(c)
    first = c.post("/api/v1/ai/copilot", json={"message": "How much ITC is at risk?"}).json()
    nxt = c.post("/api/v1/ai/copilot", json={"message": "what about last month?", "context": first["context"]}).json()
    assert nxt["intent"] == "itc_at_risk" and nxt["context"]["period"] == "last_month"
