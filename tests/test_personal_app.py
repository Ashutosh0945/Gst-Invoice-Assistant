from datetime import date

from fastapi.testclient import TestClient

from backend.api.main import app
from backend.personal.tax import TaxInputs, compare_regimes, compute_regime, gst_registration_check
from backend.synthetic.generate import generate_invoice


def _client(email="a@example.com", profile="freelancer", **extra):
    c = TestClient(app)
    r = c.post("/api/v1/app/auth/signup", json={"name": "Asha", "email": email, "password": "secret-pass-1",
                                                 "profile_type": profile, "state_code": "27", **extra})
    assert r.status_code == 201, r.text
    return c


# ---------------------------------------------------------------- tax rules (FY 2025-26)
def test_new_regime_rebate_and_marginal_relief():
    # 12,00,000 taxable after standard deduction -> fully rebated
    assert compute_regime("new", TaxInputs(salary_income=1275000)).total_tax == 0
    # 12,10,000 taxable: slab tax 61,500 but capped at income above 12L (10,000) + cess
    r = compute_regime("new", TaxInputs(salary_income=1285000))
    assert r.marginal_relief == 51500 and r.total_tax == 10400


def test_old_regime_caps_deductions():
    r = compute_regime("old", TaxInputs(salary_income=1050000, sec_80c=200000))
    assert [d["allowed"] for d in r.deductions] == [150000]
    assert r.taxable_income == 850000 and r.total_tax == round((12500 + 70000) * 1.04)


def test_compare_picks_cheaper_regime():
    out = compare_regimes(TaxInputs(salary_income=1800000, sec_80c=150000, sec_80d_self=25000))
    assert out["better"] == "new" and out["saving"] == out["old"]["total_tax"] - out["new"]["total_tax"]


def test_gst_registration_thresholds():
    assert gst_registration_check(1800000, "services", "27")["required"] is False
    assert gst_registration_check(1800000, "services", "14")["required"] is True      # Manipur: 10L
    assert gst_registration_check(3500000, "goods", "27")["required"] is False
    assert gst_registration_check(500000, "goods", "27", interstate_goods=True)["required"] is True


# ---------------------------------------------------------------- API
def test_signup_login_and_isolation(db):
    a = _client("a@example.com")
    assert a.get("/api/v1/app/me").json()["name"] == "Asha"
    assert TestClient(app).get("/api/v1/app/me").status_code == 401
    r = a.post("/api/v1/app/invoices", json={"client_name": "Acme", "items": [{"description": "Design", "rate": 10000}]})
    inv_id = r.json()["id"]
    b = _client("b@example.com")
    assert b.get(f"/api/v1/app/invoices/{inv_id}").status_code == 404      # can't see another user's data
    assert b.get("/api/v1/app/invoices").json() == []
    bad = TestClient(app).post("/api/v1/app/auth/login", json={"email": "a@example.com", "password": "wrong-pass"})
    assert bad.status_code == 401


def test_bill_upload_insights_and_warranty(db, tmp_path):
    c = _client("bills@example.com", profile="business")
    si = generate_invoice(seed=5, n_items=2)
    r = c.post("/api/v1/app/bills", files={"file": ("bill.pdf", si.pdf_bytes, "application/pdf")})
    assert r.status_code == 201, r.text
    bill = r.json()
    assert bill["insights"]["headline"] and bill["total"]
    r = c.patch(f"/api/v1/app/bills/{bill['id']}", json={"warranty_until": "2027-01-31", "category": "electronics"})
    assert r.json()["warranty_until"] == "2027-01-31" and r.json()["category"] == "electronics"
    assert len(c.get("/api/v1/app/bills").json()) == 1
    assert c.delete(f"/api/v1/app/bills/{bill['id']}").status_code == 204


def test_invoice_gst_split_pdf_and_paid(db):
    c = _client("inv@example.com", gstin="27AAPFU0939F1ZV")
    r = c.post("/api/v1/app/invoices", json={"client_name": "Karnataka Co", "place_of_supply": "29",
                                             "items": [{"description": "App build", "rate": 50000, "gst_rate": 18}]})
    inv = r.json()
    assert inv["igst"] == "9000.00" and inv["total"] == "59000.00" and inv["number"].endswith("/001")
    pdf = c.get(f"/api/v1/app/invoices/{inv['id']}/pdf")
    assert pdf.headers["content-type"] == "application/pdf" and pdf.content[:4] == b"%PDF"
    assert c.post(f"/api/v1/app/invoices/{inv['id']}/paid", json={}).json()["status"] == "PAID"


def test_unregistered_seller_charges_no_gst(db):
    c = _client("small@example.com")
    inv = c.post("/api/v1/app/invoices", json={"client_name": "X", "items": [{"description": "Work", "rate": 1000, "gst_rate": 18}]}).json()
    assert inv["total"] == "1000.00"


def test_assistant_offline_answers_with_tools(db):
    c = _client("chat@example.com")
    c.post("/api/v1/app/invoices", json={"client_name": "Slow Payer", "items": [{"description": "Work", "rate": 20000}]})
    r = c.post("/api/v1/app/assistant", json={"message": "Who hasn't paid me?"}).json()
    assert r["meta"]["mode"] == "offline" and r["meta"]["tools"][0]["tool"] == "unpaid_invoices"
    assert "₹20,000" in r["content"]
    r = c.post("/api/v1/app/assistant", json={"message": "Old or new regime if my salary is 15 lakh?"}).json()
    assert r["meta"]["tools"][0]["tool"] == "compare_tax_regimes" and "new regime" in r["content"]
    r = c.post("/api/v1/app/assistant", json={"message": "Do I need GST registration for 25 lakh of services?"}).json()
    assert r["content"].startswith("Yes")
    assert len(c.get("/api/v1/app/assistant/history").json()["messages"]) == 6


def test_home_and_deadlines(db):
    c = _client("home@example.com", profile="business", gstin="27AAPFU0939F1ZV")
    h = c.get("/api/v1/app/home").json()
    assert h["me"]["profile_type"] == "business" and h["suggestions"]
    assert all(d["date"] >= date.today().isoformat() for d in h["deadlines"])
