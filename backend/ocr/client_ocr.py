"""OCR results computed in the user's browser (Tesseract.js) and sent with the upload.

Used only when the server itself has no OCR engine (e.g. on Vercel). The words are untrusted input,
so they are validated and size-limited here, and only ever used as text for extraction -- exactly
like OCR output from any other engine. Coordinates are scaled from the image the browser read to the
image the server processes.
"""
from __future__ import annotations

import contextvars
import re

from pydantic import BaseModel, Field, field_validator

from backend.schemas import OCRWord

MAX_WORDS = 6000


class ClientWord(BaseModel):
    text: str = Field(min_length=1, max_length=80)
    bbox: tuple[float, float, float, float]
    conf: float = Field(ge=0, le=100)

    @field_validator("bbox")
    @classmethod
    def _ordered(cls, b):
        x0, y0, x1, y1 = b
        if x1 < x0 or y1 < y0 or min(b) < -5:
            raise ValueError("invalid bounding box")
        return b


class ClientOCR(BaseModel):
    engine: str = Field(default="tesseract.js", max_length=60)
    width: int = Field(gt=0, le=20000)
    height: int = Field(gt=0, le=20000)
    words: list[ClientWord] = Field(max_length=MAX_WORDS)


CLIENT_OCR: contextvars.ContextVar[ClientOCR | None] = contextvars.ContextVar("client_ocr", default=None)
OCR_USED: contextvars.ContextVar[str | None] = contextvars.ContextVar("ocr_used", default=None)


_GSTIN_LIKE = re.compile(r"^[0-9OoIlSZB]{2}[0-9A-Za-z]{13}$")


_DIGIT = {"O": "0", "o": "0", "D": "0", "Q": "0", "I": "1", "l": "1", "i": "1", "S": "5", "s": "5", "B": "8", "Z": "2", "G": "6"}
_LETTER = {"0": "O", "1": "I", "5": "S", "8": "B", "2": "Z", "6": "G"}
_SWAP = {"0": "O", "O": "0", "1": "I", "I": "1", "5": "S", "S": "5", "8": "B", "B": "8", "2": "Z", "Z": "2", "6": "G", "G": "6"}


def fix_gstin(t: str) -> str:
    """GSTIN = 2 digits, 5 letters, 4 digits, 1 letter, 1 alphanumeric, 'Z', 1 checksum character.
    Step 1: fix look-alikes where the position fixes the type (digits vs letters) -- unambiguous.
    Step 2: if the checksum still fails, try every single look-alike swap in the alphanumeric positions;
    accept a swap ONLY if exactly one candidate is valid. Several valid candidates = ambiguous: leave it,
    so validation flags it for a human instead of silently storing a wrong-but-valid GSTIN."""
    from backend.validation.gst import gstin_checksum

    t = t.upper() if not any(ch in t for ch in "lois") else "".join(_DIGIT.get(ch, ch) if ch in "lois" else ch for ch in t).upper()
    if len(t) != 15:
        return t
    c = list(t)
    for k in (0, 1, 7, 8, 9, 10):
        c[k] = _DIGIT.get(c[k], c[k])
    for k in (2, 3, 4, 5, 6, 11):
        c[k] = _LETTER.get(c[k], c[k])
    if c[13] == "2":
        c[13] = "Z"
    base = "".join(c)
    valid = lambda g: gstin_checksum(g[:14]) == g[14]  # noqa: E731
    if valid(base):
        return base
    cands = {base[:k] + _SWAP[base[k]] + base[k + 1:] for k in (12, 14) if base[k] in _SWAP}
    good = [g for g in cands if valid(g)]
    return good[0] if len(good) == 1 else t


def repair_gstin_tokens(words: list[OCRWord]) -> list[OCRWord]:
    """Apply fix_gstin to GSTIN-shaped tokens; only valid, unambiguous results replace the OCR text."""
    from backend.validation.gst import gstin_checksum

    out = []
    for w in words:
        t = w.text.strip().strip(".,:;")
        if _GSTIN_LIKE.match(t):
            fixed = fix_gstin(t)
            if fixed != t and len(fixed) == 15 and gstin_checksum(fixed[:14]) == fixed[14]:
                w = OCRWord(text=w.text.replace(t, fixed), bbox=w.bbox, conf=w.conf)
        out.append(w)
    return out


def words_for_image(image_w: int, image_h: int) -> list[OCRWord] | None:
    c = CLIENT_OCR.get()
    if c is None:
        return None
    sx, sy = image_w / c.width, image_h / c.height
    return repair_gstin_tokens([OCRWord(text=w.text, bbox=(w.bbox[0] * sx, w.bbox[1] * sy, w.bbox[2] * sx, w.bbox[3] * sy),
                                        conf=round(w.conf / 100, 4)) for w in c.words if w.text.strip()])
