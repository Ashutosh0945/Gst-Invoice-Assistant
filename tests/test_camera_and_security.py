"""Camera capture optimization + Security & Compliance Center."""
import json
from pathlib import Path

import cv2
import numpy as np
import pymupdf
import pytest
from fastapi.testclient import TestClient

from backend.api.main import app
from backend.capture.optimize import optimize
from backend.synthetic.generator import generate


@pytest.fixture(scope="module")
def doc(tmp_path_factory):
    p = tmp_path_factory.mktemp("cap") / "inv.pdf"
    generate(p, seed=33)
    pix = pymupdf.open(str(p))[0].get_pixmap(dpi=150)
    return np.frombuffer(pix.samples, np.uint8).reshape(pix.h, pix.w, pix.n)[:, :, :3][:, :, ::-1].copy()


def _on_desk(doc, H=1600, W=2100):
    rng = np.random.default_rng(1)
    bg = np.clip(np.full((H, W, 3), (60, 95, 140), np.float32) + rng.normal(0, 10, (H, W, 1)), 0, 255).astype(np.uint8)
    h, w = doc.shape[:2]
    dst = np.float32([[420, 260], [1660, 300], [1720, 1360], [380, 1320]])
    M = cv2.getPerspectiveTransform(np.float32([[0, 0], [w, 0], [w, h], [0, h]]), dst)
    paper = cv2.warpPerspective(doc, M, (W, H)); mask = cv2.warpPerspective(np.full((h, w), 255, np.uint8), M, (W, H))
    return np.where(mask[..., None] > 0, paper, bg)


def test_desk_photo_is_detected_cropped_and_straightened(doc):
    photo = _on_desk(doc)
    before = photo.copy()
    r = optimize(photo)
    m = r.quality["metrics"]
    assert m["document_found"] and 40 < m["document_coverage_pct"] < 90 and m["perspective_deg"] > 2
    assert np.array_equal(photo, before)                    # original never modified
    landscape = lambda im: im.shape[1] > im.shape[0]  # noqa: E731
    assert landscape(r.ocr_ready) == landscape(doc)         # same orientation as the real invoice
    assert r.quality["verdict"] in ("good", "fair")


def test_rotated_photo_is_turned_upright(doc):
    r = optimize(cv2.rotate(_on_desk(doc), cv2.ROTATE_90_COUNTERCLOCKWISE))
    assert r.quality["metrics"]["rotated_deg"] == 90
    assert (r.ocr_ready.shape[1] > r.ocr_ready.shape[0]) == (doc.shape[1] > doc.shape[0])   # back to the invoice's real orientation


def test_blurry_dark_and_tiny_photos_are_flagged(doc):
    codes = lambda img: {w["code"] for w in optimize(img).quality["warnings"]}  # noqa: E731
    assert "blurry" in codes(cv2.GaussianBlur(_on_desk(doc), (0, 0), 4))
    assert "low_light" in codes((_on_desk(doc).astype(np.float32) * 0.25).astype(np.uint8))
    tiny = optimize(cv2.resize(_on_desk(doc), (500, 380)))
    assert tiny.quality["verdict"] == "poor" and "low_resolution" in {w["code"] for w in tiny.quality["warnings"]}


def test_clean_scan_gets_no_false_warnings(doc):
    r = optimize(doc)
    assert r.quality["warnings"] == [] and r.quality["verdict"] == "good"


def test_upload_with_optimize_passes_ocr_ready_image_and_logs_it(db, doc, tmp_path):
    c = TestClient(app)
    ok, jpg = cv2.imencode(".jpg", _on_desk(doc))
    a = c.post("/api/v1/capture/analyze", files={"file": ("p.jpg", jpg.tobytes(), "image/jpeg")}).json()
    assert a["enhanced"].startswith("data:image/jpeg;base64,") and a["quality"]["verdict"] in ("good", "fair")
    assert c.post("/api/v1/capture/analyze", files={"file": ("x.jpg", b"not an image", "image/jpeg")}).status_code == 422
    r = c.post("/api/v1/invoices?optimize=true", files={"file": ("p.jpg", jpg.tobytes(), "image/jpeg")})
    assert r.status_code == 201
    from backend.db.models import AuditLog
    logs = [x.action for x in db.query(AuditLog).filter(AuditLog.invoice_id == r.json()["id"])]
    assert "CAPTURE_OPTIMIZED" in logs
    r2 = c.post("/api/v1/invoices", files={"file": ("p2.jpg", cv2.imencode(".jpg", doc)[1].tobytes(), "image/jpeg")})
    assert "CAPTURE_OPTIMIZED" not in [x.action for x in db.query(AuditLog).filter(AuditLog.invoice_id == r2.json()["id"])]


# ------------------------------------------------------------------------------------------- security
SECRETS = {"OPENROUTER_API_KEY": "sk-or-v1-SUPERSECRET-123456", "API_KEY": "console-SECRET-key-987"}


@pytest.fixture()
def secured(monkeypatch):
    from backend.config import reset_settings_cache
    for k, v in SECRETS.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("LLM_ENABLED", "false")
    reset_settings_cache()
    import httpx

    monkeypatch.setattr(httpx, "get", lambda *a, **k: (_ for _ in ()).throw(httpx.ConnectError("offline in tests")))
    yield
    reset_settings_cache()


def test_security_overview_never_leaks_secrets(db, secured):
    c = TestClient(app, headers={"X-API-Key": SECRETS["API_KEY"]})
    body = c.get("/api/v1/security/overview").text
    for v in SECRETS.values():
        assert v not in body
    o = json.loads(body)
    cfg = {x["setting"]: x["status"] for x in o["configuration"]}
    assert cfg["OPENROUTER_API_KEY"] == "Configured" and cfg["API_KEY (API access protection)"] == "Configured"
    assert o["rls"]["verification"] == "Unable to verify"            # SQLite: honestly unverifiable
    assert o["score"]["score"] is not None and "certification" in o["score"]["note"]
    assert "Row-level security" in o["score"]["not_counted"]          # unverifiable checks don't affect the score
    assert any(h["name"] == "AI service (OpenRouter)" and h["status"] == "Unable to verify" for h in o["health"])


def test_failed_access_is_recorded_and_alerts(db, secured):
    bad = TestClient(app, headers={"X-API-Key": "wrong"})
    for _ in range(5):
        assert bad.get("/api/v1/invoices").status_code == 401
    assert TestClient(app).get("/api/v1/security/overview").status_code == 401     # the Security Center itself is protected
    good = TestClient(app, headers={"X-API-Key": SECRETS["API_KEY"]})
    ev = good.get("/api/v1/security/events?kind=auth&outcome=denied").json()
    assert len(ev) >= 6 and all(e["actor"] in ("Invalid API key", "Anonymous (no login)") for e in ev)
    assert all("wrong" not in json.dumps(e) for e in ev)                           # attempted key never stored
    alerts = good.get("/api/v1/security/overview").json()["alerts"]
    assert any(a["title"] == "Repeated failed access attempts" for a in alerts)


def test_data_access_trail(db):
    c = TestClient(app)
    from backend.synthetic.generate import generate_invoice
    inv = c.post("/api/v1/invoices", files={"file": ("a.pdf", generate_invoice(seed=71).pdf_bytes, "application/pdf")}).json()
    c.get(f"/api/v1/invoices/{inv['id']}")
    c.post("/api/v1/ai/reports/monthly?period=all")
    ev = c.get("/api/v1/security/events?kind=access").json()
    acts = {e["action"] for e in ev}
    assert {"invoice.uploaded", "invoice.viewed", "report.generated"} <= acts
    viewed = next(e for e in ev if e["action"] == "invoice.viewed")
    assert viewed["resource_id"] == inv["id"] and "{id}" in viewed["path"] and viewed["actor"] == "Anonymous (no login)"
    o = c.get("/api/v1/security/overview").json()
    assert any(a["title"] == "API is open" for a in o["alerts"])                    # honest: no key, no login


def test_audit_failure_never_breaks_requests(db, monkeypatch):
    import backend.db.base as B
    monkeypatch.setattr(B, "SessionLocal", lambda: (_ for _ in ()).throw(RuntimeError("audit db down")))
    assert TestClient(app).post("/api/v1/ai/reports/monthly?period=all").status_code == 200


def test_ip_masking():
    from backend.security.audit import mask_ip
    assert mask_ip("103.21.244.17") == "103.21.x.x" and mask_ip("2405:201:abcd::1").startswith("2405:201")
