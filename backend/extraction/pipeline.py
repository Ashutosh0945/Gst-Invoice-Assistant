"""Extraction orchestration: pick native text vs OCR per page, then pick
LayoutLMv3 vs the regex baseline, merging multi-page invoices into one
InvoiceData. This is the ONLY module callers need from backend.extraction.
"""
from __future__ import annotations

import logging

from backend.config import get_settings
from backend.ingestion.loader import LoadedPage, is_native_text_page
from backend.ingestion.preprocess import preprocess_for_ocr
from backend.schemas import InvoiceData, OCRWord, PageData
from decimal import Decimal
from backend.extraction.rules_baseline import extract_baseline
from backend.extraction.layoutlm import LayoutLMUnavailable, extract_layoutlm
from backend.ocr.engine import OCRUnavailable, run_ocr

logger = logging.getLogger(__name__)


def get_page_words(page: LoadedPage) -> tuple[list[OCRWord], str]:
    """Returns (words, source) where source is 'native' or 'ocr'."""
    settings = get_settings()
    if is_native_text_page(page, settings.native_text_min_words):
        return page.native_words, "native"

    deskewed, _angle = preprocess_for_ocr(page.image)
    try:
        words = run_ocr(deskewed)
        return words, "ocr"
    except OCRUnavailable:
        logger.warning("OCR unavailable and page has no embedded text; extraction will be sparse.")
        return page.native_words, "native"


def extract_invoice(pages: list[LoadedPage]) -> tuple[InvoiceData, list[str]]:
    """Extracts one InvoiceData from all pages of a document.

    Returns (invoice_data, page_sources) so callers/audit logs can record
    which pages were OCR'd vs native, and which extractor produced the data.
    """
    all_words: list[OCRWord] = []
    sources: list[str] = []
    first_page_image = pages[0].image if pages else None

    for page in pages:
        words, source = get_page_words(page)
        all_words.extend(words)
        sources.append(source)

    settings = get_settings()
    if settings.layoutlm_model_path and first_page_image is not None:
        try:
            data = extract_layoutlm(first_page_image, all_words)
            return data, sources
        except LayoutLMUnavailable as exc:
            logger.info("LayoutLMv3 unavailable (%s); using regex baseline extractor.", exc)

    page_data = [PageData(page=p.page_index, width=p.width, height=p.height, source="native", words=w)
                 for p, w in zip(pages, _words_per_page(pages, all_words))]
    return extract_rules_ensemble(all_words, page_data), sources


def _words_per_page(pages: list[LoadedPage], all_words: list[OCRWord]) -> list[list[OCRWord]]:
    """Splits the flat word list back per page (words were appended page by page)."""
    out, i = [], 0
    for p in pages:
        n = len(p.native_words) if p.native_words else 0
        out.append(all_words[i:i + n] if n else [])
        i += n
    if i < len(all_words) and out:          # OCR pages: counts differ, keep remainder on the last page
        out[-1] = out[-1] + all_words[i:]
    return out


_REQUIRED = ("vendor_gstin", "invoice_number", "invoice_date", "subtotal", "grand_total")
_TOL = Decimal("1.00")


def _consistency_score(inv: InvoiceData) -> float:
    """How complete and internally consistent an extraction is. Used only to choose
    between rule-based extractors -- never to change any extracted value."""
    score = sum(1.0 for f in _REQUIRED if getattr(inv, f) is not None)
    if inv.items:
        score += 1.0
        tv = [li.taxable_value for li in inv.items if li.taxable_value is not None]
        if inv.subtotal is not None and tv and abs(sum(tv) - inv.subtotal) <= _TOL:
            score += 2.0
    if inv.subtotal is not None and inv.grand_total is not None:
        taxes = sum((x or 0) for x in (inv.total_cgst, inv.total_sgst, inv.total_igst, inv.total_cess))
        if abs(inv.subtotal + taxes + (inv.round_off or 0) - inv.grand_total) <= _TOL:
            score += 1.0
    return score


def extract_rules_ensemble(words: list[OCRWord], pages: list[PageData]) -> InvoiceData:
    """Runs both rule-based extractors (regex line parser and column-aware layout
    heuristic) and keeps whichever result is more complete and self-consistent.
    Each is strong on different layouts (see ml/benchmark.py), so together they
    cover more invoices than either alone."""
    from backend.extraction.heuristic import extract as heuristic_extract

    candidates = [extract_baseline(words)]
    try:
        candidates.append(heuristic_extract(pages))
    except Exception as exc:  # noqa: BLE001 - a heuristic crash must not lose the baseline result
        logger.warning("Layout heuristic extractor failed: %s", exc)
    best = max(candidates, key=_consistency_score)   # ties keep the regex baseline (first)
    if _consistency_score(best) >= _FULLY_CONSISTENT:
        # Every total cross-checks against the line items, which is independent evidence
        # that the amounts were read correctly; raise their confidence accordingly.
        for f in ("subtotal", "total_cgst", "total_sgst", "total_igst", "grand_total", "items"):
            if f == "items" or getattr(best, f) is not None:
                best.field_confidence[f] = max(best.field_confidence.get(f, 0.0), 0.98)
    return best


_FULLY_CONSISTENT = len(_REQUIRED) + 4
