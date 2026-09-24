"""Load invoice PDFs/images, split into page images, compute a document hash for
duplicate detection, and classify each page as 'native text' vs 'needs OCR'.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import pymupdf as fitz  # PyMuPDF
import numpy as np

from backend.config import get_settings
from backend.schemas import OCRWord, PageData

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".tiff", ".bmp", ".webp"}


@dataclass
class LoadedPage:
    page_index: int
    image: np.ndarray            # BGR, uint8, ready for OpenCV
    native_words: list[OCRWord]  # empty if this page has no embedded text layer
    width: int
    height: int


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_document(path: str | Path) -> tuple[str, list[LoadedPage]]:
    """Returns (document_hash, pages). Works for PDFs and single images."""
    path = Path(path)
    raw = path.read_bytes()
    doc_hash = sha256_bytes(raw)

    if path.suffix.lower() in IMAGE_SUFFIXES:
        import cv2

        img = cv2.imread(str(path))
        if img is None:
            raise ValueError(f"Could not decode image: {path}")
        h, w = img.shape[:2]
        return doc_hash, [LoadedPage(0, img, [], w, h)]

    settings = get_settings()
    pages: list[LoadedPage] = []
    with fitz.open(stream=raw, filetype="pdf") as pdf:
        for i, page in enumerate(pdf):
            zoom = settings.render_dpi / 72.0
            mat = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=mat, colorspace=fitz.csRGB)
            arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
            bgr = arr[:, :, ::-1].copy() if pix.n == 3 else arr.copy()

            words = []
            for w0, y0, x1, y1, text, *_ in page.get_text("words"):
                if not text.strip():
                    continue
                words.append(OCRWord(
                    text=text,
                    bbox=(w0 * zoom, y0 * zoom, x1 * zoom, y1 * zoom),
                    conf=1.0,
                ))
            pages.append(LoadedPage(i, bgr, words, pix.width, pix.height))
    return doc_hash, pages


def is_native_text_page(page: LoadedPage, min_words: int) -> bool:
    return len(page.native_words) >= min_words
