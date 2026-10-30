"""Vision-language-model OCR via OpenRouter (default: nvidia/nemotron-3.5-super-vl:free).

The page image is sent to the VLM, which transcribes it as text segments with approximate
bounding boxes (0-1000 normalised). Those are converted to the same ``OCRWord`` list every other
engine produces, so extraction/validation downstream is unchanged.

VLMs are not pixel-accurate, so geometry is treated as untrusted:
  * boxes are clamped and sanity-checked; if a segment has no usable box, a synthetic one is
    derived from reading order (line index -> y, character offset -> x) so the row/column
    heuristics in ``backend.extraction`` still see a sensible layout;
  * GSTIN-shaped tokens go through the same checksum-guarded repair as other OCR output;
  * any failure raises ``OCRUnavailable`` so ``run_ocr`` can fall back to the next engine
    (the free tier is rate limited, so this happens in practice).

Server-side only: the OpenRouter key never reaches the browser.
"""
from __future__ import annotations

import base64
import json
import logging
import re
import time
from typing import Any

import numpy as np

from backend.config import get_settings
from backend.schemas import OCRWord

logger = logging.getLogger(__name__)

MAX_SIDE = 1600          # longest edge sent to the model; boxes are normalised so scale doesn't matter
MAX_SEGMENTS = 3000

PROMPT = (
    "You are an OCR engine for Indian GST invoices. Transcribe ALL visible text in this image "
    "exactly as printed. Do not summarise, translate, correct, or invent anything. Keep numbers, "
    "GSTINs, dates, HSN/SAC codes, and currency symbols character-for-character.\n"
    "Return ONLY JSON, no commentary, in this shape:\n"
    '{"segments":[{"t":"<text>","b":[x0,y0,x1,y1]}, ...]}\n'
    "One segment per visual text run: a table cell, a label, or a short phrase on one line. "
    "Never merge separate table columns into one segment. "
    "b is the bounding box as integers 0-1000 (fraction of image width/height x 1000, origin top-left). "
    "List segments in reading order, top to bottom, then left to right."
)


def _unavailable(msg: str, exc: Exception | None = None):
    from backend.ocr.engine import OCRUnavailable
    err = OCRUnavailable(msg)
    if exc is not None:
        err.__cause__ = exc
    return err


def vlm_configured() -> bool:
    s = get_settings()
    return bool(s.vlm_ocr_enabled and s.openrouter_api_key and s.openrouter_ocr_model)


def vlm_engine_label() -> str:
    return f"{get_settings().openrouter_ocr_model} (OpenRouter VLM)"


# ----------------------------------------------------------------------------- request

def _encode(image_bgr: np.ndarray) -> str:
    import cv2
    h, w = image_bgr.shape[:2]
    s = min(1.0, MAX_SIDE / max(h, w))
    img = cv2.resize(image_bgr, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA) if s < 1 else image_bgr
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 88])
    if not ok:
        raise _unavailable("Could not encode invoice image for the vision model.")
    return "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode("ascii")


def _call_model(data_url: str) -> str:
    import httpx

    s = get_settings()
    body = {
        "model": s.openrouter_ocr_model,
        "temperature": 0,
        "max_tokens": s.vlm_ocr_max_tokens,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": PROMPT},
            {"type": "image_url", "image_url": {"url": data_url}},
        ]}],
    }
    headers = {"Authorization": f"Bearer {s.openrouter_api_key}", "Content-Type": "application/json"}
    attempts, last = max(1, s.vlm_ocr_max_retries), None
    deadline = time.monotonic() + s.vlm_ocr_timeout_s
    for attempt in range(attempts):
        remaining = deadline - time.monotonic()
        if remaining <= 2:
            break
        try:
            resp = httpx.post(f"{s.openrouter_base_url}/chat/completions", headers=headers, json=body, timeout=remaining)
            if resp.status_code in (429, 502, 503, 504):      # free tier: rate limited / provider busy
                last = RuntimeError(f"HTTP {resp.status_code}")
                time.sleep(min(2 ** attempt, 4))
                continue
            resp.raise_for_status()
            payload = resp.json()
            if payload.get("error"):
                raise RuntimeError(str(payload["error"].get("message", payload["error"]))[:200])
            msg = payload["choices"][0]["message"]
            text = (msg.get("content") or "").strip()
            if isinstance(msg.get("content"), list):          # some providers return content parts
                text = "".join(p.get("text", "") for p in msg["content"] if isinstance(p, dict)).strip()
            text = text or (msg.get("reasoning") or "").strip()
            if not text:
                raise ValueError("empty response")
            return text
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError, RuntimeError) as exc:
            last = exc
            logger.warning("VLM OCR attempt %d/%d failed: %s", attempt + 1, attempts, exc)
    raise _unavailable(f"Vision model OCR failed: {type(last).__name__ if last else 'timeout'}"
                       f"{': ' + str(last)[:120] if last else ''}", last)


# ----------------------------------------------------------------------------- parsing

def _parse_segments(raw: str) -> list[dict[str, Any]]:
    """Pull the JSON out of the reply (tolerates code fences / leading chatter); fall back to plain lines."""
    txt = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.I)
    for opener, closer in (("{", "}"), ("[", "]")):
        i, j = txt.find(opener), txt.rfind(closer)
        if i != -1 and j > i:
            try:
                data = json.loads(txt[i:j + 1])
            except ValueError:
                continue
            segs = data.get("segments") if isinstance(data, dict) else data
            if isinstance(segs, list):
                return [x for x in segs if isinstance(x, dict)]
    # model ignored the JSON instruction: treat each non-empty line as a segment with no box
    return [{"t": ln.strip()} for ln in raw.splitlines() if ln.strip() and not ln.strip().startswith("```")]


def _valid_box(b: Any) -> tuple[float, float, float, float] | None:
    try:
        x0, y0, x1, y1 = (float(v) for v in b)
    except (TypeError, ValueError):
        return None
    x0, x1 = sorted((max(0.0, min(1000.0, x0)), max(0.0, min(1000.0, x1))))
    y0, y1 = sorted((max(0.0, min(1000.0, y0)), max(0.0, min(1000.0, y1))))
    if x1 - x0 < 2 or y1 - y0 < 2:
        return None
    return x0, y0, x1, y1


def segments_to_words(segments: list[dict[str, Any]], width: int, height: int) -> list[OCRWord]:
    """Segments -> word boxes in image pixels. Each segment's box is shared out across its words by
    character length. If fewer than half the segments carry a usable box, ignore model geometry
    entirely and lay everything out from reading order (consistent beats half-right)."""
    segs = [(str(s.get("t") or s.get("text") or "").strip(), _valid_box(s.get("b") or s.get("bbox")))
            for s in segments[:MAX_SEGMENTS]]
    segs = [(t, b) for t, b in segs if t]
    if not segs:
        return []
    use_model_boxes = sum(1 for _, b in segs if b) * 2 >= len(segs)

    line_h = height / max(len(segs), 1)
    words: list[OCRWord] = []
    for idx, (text, box) in enumerate(segs):
        if use_model_boxes and box:
            x0, y0, x1, y1 = box[0] / 1000 * width, box[1] / 1000 * height, box[2] / 1000 * width, box[3] / 1000 * height
        else:  # synthetic: one band per segment in reading order, full width
            y0, y1 = idx * line_h, idx * line_h + line_h * 0.8
            x0, x1 = 0.05 * width, 0.05 * width + min(0.9, 0.012 * len(text)) * width
        toks = text.split()
        total = sum(len(t) for t in toks) + max(len(toks) - 1, 0)
        cur = x0
        for t in toks:
            w = (x1 - x0) * len(t) / total if total else 0
            words.append(OCRWord(text=t, bbox=(cur, y0, cur + w, y1), conf=0.9))
            cur += w + (x1 - x0) / total   # one character of space between words
    return words


# ----------------------------------------------------------------------------- public

def run_vlm_ocr(image_bgr: np.ndarray) -> list[OCRWord]:
    """OCR one page image with the OpenRouter vision model. Raises OCRUnavailable on any failure."""
    if not vlm_configured():
        raise _unavailable("Vision-model OCR is not configured (needs OPENROUTER_API_KEY).")
    from backend.ocr.client_ocr import repair_gstin_tokens

    h, w = image_bgr.shape[:2]
    raw = _call_model(_encode(image_bgr))
    words = repair_gstin_tokens(segments_to_words(_parse_segments(raw), w, h))
    if not words:
        raise _unavailable("Vision model returned no text.")
    return words
