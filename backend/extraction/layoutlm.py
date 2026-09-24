"""Optional LayoutLMv3 structured extractor.

Loaded only if settings.layoutlm_model_path is set AND transformers/torch are
installed. When either condition fails, extraction/pipeline.py falls back to
the regex baseline automatically — LayoutLMv3 is an accuracy upgrade, not a
hard dependency.

This module expects a token-classification model fine-tuned on invoice fields
with a BIO tag set, e.g.:
  O, B-VENDOR_NAME, B-VENDOR_GSTIN, B-INVOICE_NO, B-INVOICE_DATE, B-PO_NO,
  B-HSN, B-QTY, B-UNIT_PRICE, B-TAXABLE_VALUE, B-GST_RATE, B-LINE_TOTAL, ...
Training such a model (data labeling, fine-tuning, eval) is a separate
offline workflow — see ml/ for the dataset generator, training script and
benchmark.
"""
from __future__ import annotations

import logging
from functools import lru_cache

import numpy as np

from backend.config import get_settings
from backend.schemas import InvoiceData, LineItem, OCRWord

logger = logging.getLogger(__name__)


class LayoutLMUnavailable(RuntimeError):
    pass


@lru_cache(maxsize=1)
def _get_model():
    settings = get_settings()
    if not settings.layoutlm_model_path:
        raise LayoutLMUnavailable("LAYOUTLM_MODEL_PATH is not configured.")
    try:
        import torch
        from transformers import AutoProcessor, LayoutLMv3ForTokenClassification
    except ImportError as exc:
        raise LayoutLMUnavailable(
            "transformers/torch not installed. Install requirements-ml.txt to use LayoutLMv3."
        ) from exc

    processor = AutoProcessor.from_pretrained(settings.layoutlm_model_path, apply_ocr=False)
    model = LayoutLMv3ForTokenClassification.from_pretrained(settings.layoutlm_model_path)
    model.eval()
    return processor, model, torch


def _normalize_bbox(bbox: tuple[float, float, float, float], width: int, height: int) -> list[int]:
    x0, y0, x1, y1 = bbox
    return [
        max(0, min(1000, int(1000 * x0 / width))),
        max(0, min(1000, int(1000 * y0 / height))),
        max(0, min(1000, int(1000 * x1 / width))),
        max(0, min(1000, int(1000 * y1 / height))),
    ]


def extract_layoutlm(image_bgr: np.ndarray, words: list[OCRWord]) -> InvoiceData:
    """Runs the fine-tuned LayoutLMv3 token classifier and assembles InvoiceData
    from the predicted BIO tags (label set: backend/extraction/labels.py, the
    same one ml/generate_dataset.py trains on). Raises LayoutLMUnavailable if
    no model is configured, so the caller can fall back to the rules baseline.
    """
    from backend.extraction.assemble import assemble_invoice, group_entities

    processor, model, torch = _get_model()
    h, w = image_bgr.shape[:2]
    rgb = image_bgr[:, :, ::-1].copy()

    word_texts = [w_.text for w_ in words]
    boxes = [_normalize_bbox(w_.bbox, w, h) for w_ in words]
    encoding = processor(rgb, word_texts, boxes=boxes, return_tensors="pt", truncation=True,
                         padding="max_length", max_length=512)
    word_ids = encoding.word_ids(batch_index=0)
    with torch.no_grad():
        logits = model(**{k: v for k, v in encoding.items()}).logits[0]
    probs = torch.softmax(logits, dim=-1)
    conf, pred = probs.max(dim=-1)
    id2label = model.config.id2label

    # One prediction per word: the label of its first sub-token.
    seen: set[int] = set()
    word_preds = []
    for tok_idx, wid in enumerate(word_ids):
        if wid is None or wid in seen:
            continue
        seen.add(wid)
        x0, y0, x1, y1 = words[wid].bbox
        row_key = round(y0 / max(y1 - y0, 1.0))
        word_preds.append(((row_key, x0), (word_texts[wid], id2label[int(pred[tok_idx])],
                                           float(conf[tok_idx]), 0, y0, y1 - y0)))
    word_preds.sort(key=lambda p: p[0])   # reading order: row, then left to right
    inv = assemble_invoice(group_entities([p for _, p in word_preds]))
    if len(seen) < len(words):
        logger.info("LayoutLMv3 saw %d of %d words (512-token limit); later words were not labelled.",
                    len(seen), len(words))
    return inv
