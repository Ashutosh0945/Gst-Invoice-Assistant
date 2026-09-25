"""The console must never be open to the public, and must never show personal-app data."""
from fastapi.testclient import TestClient

from backend.api.main import app
from backend.synthetic.generate import generate_invoice

KEY = {"X-API-Key": "test-console-key"}


def _personal_user_with_bill(email: str) -> TestClient:
    c = TestClient(app)
    c.post("/api/v1/app/auth/signup", json={"name": "P", "email": email, "password": "password-123"})
    r = c.post("/api/v1/app/bills", files={"file": ("b.pdf", generate_invoice(seed=77).pdf_bytes, "application/pdf")})
    assert r.status_code == 201
    return c


def test_console_rejects_anonymous_and_wrong_key(db):
    assert TestClient(app).get("/api/v1/invoices").status_code == 401
    assert TestClient(app, headers={"X-API-Key": "nope"}).get("/api/v1/invoices").status_code == 401
    assert TestClient(app).get("/api/v1/compliance/overview").status_code == 401


def test_personal_user_is_not_staff(db):
    c = _personal_user_with_bill("p1@example.com")
    assert c.get("/api/v1/invoices").status_code == 403
    assert c.get("/api/v1/console/me").status_code == 403


def test_console_never_sees_personal_bills(db):
    c = _personal_user_with_bill("p2@example.com")
    bill_invoice_count = len(c.get("/api/v1/app/bills").json())
    assert bill_invoice_count == 1
    staff = TestClient(app, headers=KEY)
    assert staff.get("/api/v1/invoices").json() == []
    assert staff.get("/api/v1/analytics/status-summary").json() == []
    assert staff.get("/api/v1/itc/assessments").json() == []
    assert staff.get("/api/v1/analytics/vendor-risk").json() == []


def test_staff_login_opens_console(db):
    from backend.db.base import SessionLocal
    from backend.db.models import User
    from backend.personal.auth import hash_password

    s = SessionLocal()
    s.add(User(email="acc@firm.in", name="Acc", password_hash=hash_password("password-123"), role="staff"))
    s.commit()
    c = TestClient(app)
    assert c.post("/api/v1/app/auth/login", json={"email": "acc@firm.in", "password": "password-123"}).status_code == 200
    assert c.get("/api/v1/console/me").json()["kind"] == "staff"
    assert c.get("/api/v1/invoices").status_code == 200
