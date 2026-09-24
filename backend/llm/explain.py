"""LLM explanation layer (OpenRouter + NVIDIA Nemotron Ultra).

STRICT BOUNDARY: this module only ever *describes* findings that the
deterministic engine already produced. It never computes a GST amount,
never edits InvoiceData, and its output is stored as free text
(Invoice.llm_explanation) alongside — never instead of — the structured
findings. If the call fails or is disabled, the pipeline proceeds with the
structured findings alone: the LLM is a UX layer, not a dependency.
"""
from __future__ import annotations

import json
import logging
import time

import httpx

from backend.config import get_settings
from backend.schemas import Finding, InvoiceData

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are a GST invoice-audit assistant. You will be given structured, "
    "already-computed validation findings for one invoice. Write a short, "
    "plain-language summary (max ~150 words) for a human reviewer: what looks "
    "wrong, roughly how serious it is, and what to check first. "
    "Do not invent numbers, GST rates, or facts not present in the findings. "
    "Do not perform any arithmetic. If there are no findings, say the invoice "
    "passed automated checks."
)


def _findings_payload(inv: InvoiceData, findings: list[Finding]) -> str:
    return json.dumps({
        "invoice_number": inv.invoice_number,
        "vendor_gstin": inv.vendor_gstin,
        "grand_total": str(inv.grand_total) if inv.grand_total is not None else None,
        "findings": [f.model_dump(mode="json") for f in findings],
    }, default=str)


def explain_findings(inv: InvoiceData, findings: list[Finding]) -> str | None:
    """Returns an explanation string, or None if the LLM is disabled/unavailable."""
    settings = get_settings()
    if not settings.llm_active:
        return None
    if not findings:
        return "No discrepancies were detected; this invoice passed all automated checks."

    payload = _findings_payload(inv, findings)
    body = {
        "model": settings.openrouter_model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Findings JSON:\n{payload}"},
        ],
        "temperature": 0.2,
        "max_tokens": 400,
    }
    headers = {
        "Authorization": f"Bearer {settings.openrouter_api_key}",
        "Content-Type": "application/json",
    }

    last_error: Exception | None = None
    for attempt in range(settings.llm_max_retries):
        try:
            resp = httpx.post(
                f"{settings.openrouter_base_url}/chat/completions",
                headers=headers, json=body, timeout=settings.llm_timeout_s,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"].strip()
        except (httpx.HTTPError, KeyError, IndexError) as exc:
            last_error = exc
            logger.warning("LLM explanation attempt %d/%d failed: %s", attempt + 1, settings.llm_max_retries, exc)
            time.sleep(min(2 ** attempt, 8))

    logger.error("LLM explanation failed after %d attempts: %s", settings.llm_max_retries, last_error)
    return None
