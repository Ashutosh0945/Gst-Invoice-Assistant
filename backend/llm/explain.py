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
import re
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


def chat(messages: list[dict], *, max_tokens: int = 600, temperature: float = 0.2,
         retries: int | None = None, timeout: float | None = None) -> str | None:
    """One OpenRouter chat call, shared by every AI feature. Returns the text, or None if
    the LLM is disabled/unavailable (callers then fall back to rule-written text).
    Server-side only: the API key never leaves the backend."""
    settings = get_settings()
    if not settings.llm_active:
        return None
    body = {"model": settings.openrouter_model, "messages": messages,
            "temperature": temperature, "max_tokens": max_tokens}
    headers = {"Authorization": f"Bearer {settings.openrouter_api_key}", "Content-Type": "application/json"}
    attempts = settings.llm_max_retries if retries is None else retries
    last_error: Exception | None = None
    for attempt in range(max(1, attempts)):
        try:
            resp = httpx.post(f"{settings.openrouter_base_url}/chat/completions", headers=headers, json=body,
                              timeout=timeout or settings.llm_timeout_s)
            resp.raise_for_status()
            message = resp.json()["choices"][0]["message"]
            # Some free/reasoning models (e.g. DeepSeek R1 routed via "openrouter/free") put
            # their output in "reasoning" and leave "content" as None -- fall back to that.
            content = (message.get("content") or message.get("reasoning") or "").strip()
            if not content:
                raise ValueError("LLM returned an empty response")
            return content
        except (httpx.HTTPError, KeyError, IndexError, AttributeError, TypeError, ValueError) as exc:
            last_error = exc
            logger.warning("LLM attempt %d/%d failed: %s", attempt + 1, attempts, exc)
            if attempt + 1 < attempts:
                time.sleep(min(2 ** attempt, 8))
    logger.error("LLM call failed after %d attempts: %s", attempts, last_error)
    return None


def explain_findings(inv: InvoiceData, findings: list[Finding]) -> str | None:
    """Returns an explanation string, or None if the LLM is disabled/unavailable."""
    settings = get_settings()
    if not settings.llm_active:
        return None
    if not findings:
        return "No discrepancies were detected; this invoice passed all automated checks."
    payload = _findings_payload(inv, findings)
    return chat([{"role": "system", "content": SYSTEM_PROMPT},
                 {"role": "user", "content": f"Findings JSON:\n{payload}"}], max_tokens=400)


# ---------------------------------------------------------------------------------------------
# Extension: explain ANY deterministic result (validation, ITC, GSTR-2B, PO reconciliation,
# investigations, briefs, Copilot answers) with a hard fact check on every number.
# ---------------------------------------------------------------------------------------------
FACTS_SYSTEM_PROMPT = """You are the AI assistant inside GST Desk, an Indian GST invoice system.
You explain results that the system's rule engine has ALREADY calculated. Strict rules:
- Use ONLY the facts in the FACTS JSON. Never invent invoices, vendors, amounts, dates or statistics.
- Do not do new arithmetic. Every number you write must appear in the FACTS JSON.
- If the facts don't contain what the user asked, say plainly that the data isn't available.
- Never say a calculation is wrong or suggest changing it; the rule engine is the source of truth.
- Anomalies are risk indicators, not proof of fraud. Forecasts/simulations are estimates.
- Write for a business owner: short, plain English, Indian number format (e.g. ₹1,24,500). No markdown tables."""

_NUM = re.compile(r"(?<![A-Za-z0-9/-])(\d{1,3}(?:,\d{2,3})+(?:\.\d+)?|\d+(?:\.\d+)?)")


def _numbers_in(value, out: set[str]) -> None:
    if isinstance(value, dict):
        for v in value.values():
            _numbers_in(v, out)
    elif isinstance(value, (list, tuple)):
        for v in value:
            _numbers_in(v, out)
    elif isinstance(value, bool) or value is None:
        return
    elif isinstance(value, (int, float)):
        out.add(_norm_num(str(value)))
    else:
        for m in _NUM.findall(str(value)):
            out.add(_norm_num(m))


def _norm_num(s: str) -> str:
    s = s.replace(",", "")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s or "0"


def unsupported_numbers(text: str, facts, question: str = "") -> list[str]:
    """Numbers in AI text that are not present in the facts (or the user's own question).
    Small counts (0-12) and years are allowed since they're unavoidable in prose."""
    allowed: set[str] = set()
    _numbers_in(facts, allowed)
    _numbers_in(question, allowed)
    bad = []
    for m in _NUM.findall(text):
        n = _norm_num(m)
        try:
            f = float(n)
        except ValueError:
            continue
        if (f <= 12 and f == int(f)) or (1900 <= f <= 2100 and f == int(f)) or n in allowed:
            continue
        bad.append(m)
    return bad


def explain_facts(topic: str, facts, *, question: str = "", history: list[dict] | None = None,
                  fallback: str = "", max_tokens: int = 500) -> dict:
    """AI wording over deterministic facts. Returns {"text", "source"} where source is
    "ai" (passed the fact check), or "rules" (AI unavailable / failed the fact check)."""
    msgs = [{"role": "system", "content": FACTS_SYSTEM_PROMPT}]
    for h in (history or [])[-6:]:
        if h.get("role") in ("user", "assistant") and h.get("content"):
            msgs.append({"role": h["role"], "content": str(h["content"])[:1500]})
    task = question or f"Explain the {topic} for the user."
    msgs.append({"role": "user", "content": f"TASK: {task}\n\nFACTS JSON ({topic}):\n"
                 f"{json.dumps(facts, default=str)[:12000]}"})
    text = chat(msgs, max_tokens=max_tokens, retries=1, timeout=get_settings().ai_timeout_s)
    if not text:
        return {"text": fallback, "source": "rules", "note": "AI wording unavailable; showing rule-based summary."}
    bad = unsupported_numbers(text, facts, question)
    if bad:
        logger.warning("AI text rejected by fact check (numbers not in data: %s)", bad[:5])
        return {"text": fallback, "source": "rules",
                "note": "AI wording was discarded because it contained numbers not found in your data."}
    return {"text": text, "source": "ai", "note": None}
