"""Free OCR: browser (Tesseract.js) words sent with the upload, OCR.space fallback, safe GSTIN repair."""
import json

import cv2
import numpy as np
import pymupdf
import pytest
from fastapi.testclient import TestClient

from backend.api.main import app
from backend.ocr.client_ocr import fix_gstin
from backend.synthetic.generate import generate_invoice


def _photo_and_browser_words(seed=11, dpi=150):
    """Render an invoice to an image and build the word list a browser OCR would return for it
    (taken from the PDF text layer, scaled to image pixels) -- deterministic stand-in for Tesseract.js."""
    si = generate_invoice(seed=seed, n_items=2)
    page = pymupdf.open(stream=si.pdf_bytes, filetype="pdf")[0]
    pix = page.get_pixmap(dpi=dpi)
    img = np.frombuffer(pix.samples, np.uint8).reshape(pix.h, pix.w, pix.n)[:, :, :3][:, :, ::-1].copy()
    k = dpi / 72
    words = [{"text": w[4], "bbox": [w[0] * k, w[1] * k, w[2] * k, w[3] * k], "conf": 93} for w in page.get_text("words")]
    return si, cv2.imencode(".png", img)[1].tobytes(), json.dumps({"engine": "tesseract.js 5.1.1", "width": pix.w, "height": pix.h, "words": words})


def test_photo_is_read_with_browser_ocr_when_server_has_none(db):
    from backend.db.models import AuditLog
    si, png, client_ocr = _photo_and_browser_words()
    c = TestClient(app)
    none = c.post("/api/v1/invoices", files={"file": ("a.png", png, "image/png")}).json()
    assert not none.get("invoice_number")                                     # today's behaviour: nothing read
    r = c.post("/api/v1/invoices", files={"file": ("b.png", png, "image/png")}, data={"client_ocr": client_ocr})
    assert r.status_code == 201
    inv = r.json()
    assert inv["invoice_number"] == si.ground_truth.invoice_number and inv["vendor_gstin_raw"] == si.ground_truth.vendor_gstin
    log = [a for a in db.query(AuditLog).filter(AuditLog.invoice_id == inv["id"]) if a.action == "OCR_ENGINE"]
    assert log and log[0].details["engine"] == "Tesseract.js (browser)" and log[0].details["browser_words"] > 20


def test_invalid_browser_ocr_is_rejected(db):
    _, png, _ = _photo_and_browser_words()
    c = TestClient(app)
    bad = [json.dumps({"width": 10, "height": 10, "words": [{"text": "x", "bbox": [5, 5, 1, 1], "conf": 50}]}),   # inverted box
           json.dumps({"width": 10, "height": 10, "words": [{"text": "x", "bbox": [0, 0, 1, 1], "conf": 500}]}),  # bad confidence
           json.dumps({"width": 10, "height": 10, "words": [{"text": "x", "bbox": [0, 0, 1, 1], "conf": 5}] * 6001}),
           "not json"]
    for b in bad:
        assert c.post("/api/v1/invoices", files={"file": ("x.png", png, "image/png")}, data={"client_ocr": b}).status_code in (413, 422)


def test_server_engine_takes_priority_over_browser_words(monkeypatch):
    from backend.ocr import engine as E
    from backend.ocr.client_ocr import CLIENT_OCR, OCR_USED, ClientOCR
    from backend.schemas import OCRWord
    monkeypatch.setattr(E, "_run_server_ocr", lambda img: [OCRWord(text="SERVER", bbox=(0, 0, 1, 1), conf=0.99)])
    CLIENT_OCR.set(ClientOCR(width=10, height=10, words=[{"text": "BROWSER", "bbox": (0, 0, 1, 1), "conf": 90}]))
    assert E.run_ocr(np.zeros((10, 10, 3), np.uint8))[0].text == "SERVER" and OCR_USED.get() != "Tesseract.js (browser)"
    CLIENT_OCR.set(None)


def test_ocr_space_parsing_and_fallback(monkeypatch):
    import httpx
    from backend.config import reset_settings_cache
    from backend.ocr import engine as E
    from backend.ocr.client_ocr import CLIENT_OCR, OCR_USED, ClientOCR
    monkeypatch.setenv("OCR_SPACE_API_KEY", "free-test-key"); reset_settings_cache()
    payload = {"IsErroredOnProcessing": False, "ParsedResults": [{"TextOverlay": {"Lines": [{"Words": [
        {"WordText": "GSTIN:", "Left": 10, "Top": 20, "Width": 40, "Height": 10},
        {"WordText": "27AAPFUO939FlZV", "Left": 60, "Top": 20, "Width": 120, "Height": 10}]}]}}]}
    monkeypatch.setattr(httpx, "post", lambda *a, **k: httpx.Response(200, json=payload, request=httpx.Request("POST", "https://x")))
    words = E.run_ocr(np.full((200, 300, 3), 255, np.uint8))
    assert [w.text for w in words] == ["GSTIN:", "27AAPFU0939F1ZV"] and OCR_USED.get() == "OCR.space"   # repaired GSTIN
    def down(*a, **k):
        raise httpx.ConnectError("offline")
    monkeypatch.setattr(httpx, "post", down)
    CLIENT_OCR.set(ClientOCR(width=300, height=200, words=[{"text": "BROWSER", "bbox": (0, 0, 9, 9), "conf": 80}]))
    assert E.run_ocr(np.full((200, 300, 3), 255, np.uint8))[0].text == "BROWSER" and OCR_USED.get() == "Tesseract.js (browser)"
    CLIENT_OCR.set(None); monkeypatch.delenv("OCR_SPACE_API_KEY"); reset_settings_cache()


@pytest.mark.parametrize("ocr_text, expected", [
    ("27AAPFUO939FlZV", "27AAPFU0939F1ZV"),      # clear look-alikes fixed by position + checksum
    ("27AAPFU0939F1ZV", "27AAPFU0939F1ZV"),      # already valid: unchanged
    ("19WWWBC4757A1Z1", "19WWWBC4757A1Z1"),      # two different fixes are valid -> ambiguous -> left for human review
])
def test_gstin_repair_is_safe(ocr_text, expected):
    assert fix_gstin(ocr_text) == expected
