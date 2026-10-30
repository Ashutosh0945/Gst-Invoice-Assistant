"""Vision-language-model OCR (OpenRouter, nvidia/nemotron-3.5-super-vl:free): parsing, geometry, fallback."""
from __future__ import annotations

import numpy as np
import pytest

from backend.config import get_settings, reset_settings_cache
from backend.ocr import engine, vlm


@pytest.fixture(autouse=True)
def _cfg(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("VLM_OCR_ENABLED", "true")
    monkeypatch.delenv("GOOGLE_VISION_API_KEY", raising=False)
    monkeypatch.delenv("OCR_SPACE_API_KEY", raising=False)
    reset_settings_cache()
    yield
    reset_settings_cache()


def test_default_model():
    assert get_settings().openrouter_ocr_model == "nvidia/nemotron-3.5-super-vl:free"


def test_parse_json_with_fences_and_chatter():
    raw = 'Sure!\n```json\n{"segments":[{"t":"Invoice No: INV-1","b":[10,10,300,40]}]}\n```'
    assert vlm._parse_segments(raw)[0]["t"] == "Invoice No: INV-1"


def test_parse_plain_text_fallback():
    assert [s["t"] for s in vlm._parse_segments("Line one\nLine two")] == ["Line one", "Line two"]


def test_boxes_scaled_to_pixels():
    words = vlm.segments_to_words([{"t": "Total 1180.00", "b": [500, 900, 900, 950]}], 2000, 1000)
    assert [w.text for w in words] == ["Total", "1180.00"]
    assert words[0].bbox[0] == pytest.approx(1000) and words[-1].bbox[2] == pytest.approx(1800)
    assert all(w.bbox[1] == pytest.approx(900) and w.bbox[3] == pytest.approx(950) for w in words)


def test_missing_boxes_use_reading_order_layout():
    words = vlm.segments_to_words([{"t": "ACME LTD"}, {"t": "Invoice 7"}, {"t": "Total 10"}], 1000, 1000)
    ys = [w.bbox[1] for w in words]
    assert ys == sorted(ys) and len(set(ys)) == 3          # one distinct band per line, top to bottom


def test_bad_boxes_are_rejected():
    assert vlm._valid_box([5, 5, 5, 5]) is None and vlm._valid_box("x") is None
    assert vlm._valid_box([-50, 0, 2000, 100]) == (0.0, 0.0, 1000.0, 100.0)


def test_run_vlm_ocr_end_to_end(monkeypatch):
    reply = '{"segments":[{"t":"GSTIN 27AAPFU0939F1ZV","b":[50,50,600,80]},{"t":"Total 1,180.00","b":[600,900,950,940]}]}'
    monkeypatch.setattr(vlm, "_call_model", lambda url: reply)
    words = vlm.run_vlm_ocr(np.full((400, 300, 3), 255, np.uint8))
    assert "27AAPFU0939F1ZV" in [w.text for w in words]


def test_run_ocr_prefers_vlm_then_falls_back(monkeypatch):
    from backend.ocr.client_ocr import OCR_USED
    monkeypatch.setattr(engine, "_run_server_ocr", lambda img: (_ for _ in ()).throw(engine.OCRUnavailable("none")))
    img = np.full((100, 100, 3), 255, np.uint8)
    monkeypatch.setattr(vlm, "_call_model", lambda url: '{"segments":[{"t":"hello","b":[10,10,200,50]}]}')
    assert [w.text for w in engine.run_ocr(img)] == ["hello"]
    assert OCR_USED.get().startswith("nvidia/nemotron-3.5-super-vl:free")

    def boom(url):
        raise engine.OCRUnavailable("rate limited")
    monkeypatch.setattr(vlm, "_call_model", boom)
    with pytest.raises(engine.OCRUnavailable):               # no browser words, no other engine
        engine.run_ocr(img)


def test_browser_ocr_still_needed_when_only_vlm(monkeypatch):
    monkeypatch.setattr("importlib.util.find_spec", lambda name: None)
    assert engine.engine_name().endswith("(OpenRouter VLM)")
    assert engine.browser_ocr_needed() is True


def test_disabled_flag(monkeypatch):
    monkeypatch.setenv("VLM_OCR_ENABLED", "false")
    reset_settings_cache()
    assert vlm.vlm_configured() is False
