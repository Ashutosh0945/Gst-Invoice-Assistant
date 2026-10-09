"""AI intent router: only whitelisted intents, validated params, safe fallbacks."""
from fastapi.testclient import TestClient

from backend.ai import copilot
from backend.api.main import app


def test_rules_still_win_without_calling_the_ai(monkeypatch):
    called = []
    monkeypatch.setattr("backend.llm.explain.chat", lambda *a, **k: called.append(1) or None)
    assert copilot.detect("How much ITC is at risk?", None)[0] == "itc_at_risk" and not called


def test_ai_routes_unrecognised_questions_to_a_whitelisted_intent(monkeypatch):
    monkeypatch.setattr("backend.llm.explain.chat", lambda *a, **k: '{"intent": "itc_at_risk", "period": "last_month", "invoice_ref": null}')
    intent, params = copilot.detect("are we going to lose any tax credit money?", None)
    assert intent == "itc_at_risk" and params["period"] == "last_month" and params["_routed_by"] == "ai"


def test_ai_cannot_invent_intents_or_bad_params(monkeypatch):
    for reply in ['{"intent": "drop_table"}', '{"intent": "delete_invoices", "period": "all"}', "not json", None,
                  '{"intent": "investigate", "invoice_ref": "x; DROP TABLE invoices"}']:
        monkeypatch.setattr("backend.llm.explain.chat", lambda *a, r=reply, **k: r)
        assert copilot.detect("zxqv blorp", None)[0] == "help"
    monkeypatch.setattr("backend.llm.explain.chat", lambda *a, **k: '{"intent": "summary", "period": "since 1900"}')
    intent, params = copilot.detect("zxqv blorp", None)
    assert intent == "summary" and "period" not in params                 # invalid period dropped
    monkeypatch.setattr("backend.llm.explain.chat", lambda *a, **k: '{"intent": "unsupported"}')
    assert copilot.detect("what's the weather?", None)[0] == "help"


def test_end_to_end_answer_reports_routing(db, monkeypatch):
    monkeypatch.setattr("backend.ai.copilot._ai_route", lambda t: ("summary", {"period": "all"}))
    r = TestClient(app).post("/api/v1/ai/copilot", json={"message": "zxqv blorp tax"}).json()
    assert r["intent"] == "summary" and r["routed_by"] == "ai" and r["context"]["period"] == "all"
