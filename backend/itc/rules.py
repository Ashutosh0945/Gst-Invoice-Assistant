"""Section 17(5) blocked-credit rules, loaded from a CSV so an accountant can edit them.

Each rule matches an invoice line by HSN/SAC prefix ("code") or by a word in
the description ("keyword") and marks it BLOCKED (never claimable) or REVIEW
(depends on how it was used — a human must decide). The bundled list is an
illustrative starting point, not legal advice: have a CA review it for your
business before relying on it.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from backend.config import get_settings

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "data" / "itc" / "blocked_credits.csv"


@dataclass(frozen=True)
class BlockedRule:
    match_type: str   # "code" | "keyword"
    pattern: str
    action: str       # "BLOCKED" | "REVIEW"
    section: str
    category: str
    note: str


@lru_cache(maxsize=1)
def load_rules() -> tuple[BlockedRule, ...]:
    path = get_settings().itc_blocked_credits_path or DEFAULT_PATH
    with open(path, newline="", encoding="utf-8") as f:
        return tuple(
            BlockedRule(r["match_type"].strip(), r["pattern"].strip().lower(), r["action"].strip().upper(),
                        r["section"].strip(), r["category"].strip(), r["note"].strip())
            for r in csv.DictReader(f) if r.get("pattern")
        )


def match_rule(hsn_sac: str | None, description: str | None) -> BlockedRule | None:
    """Most specific code rule first (longest prefix), then keyword rules."""
    code = (hsn_sac or "").strip()
    desc = (description or "").lower()
    rules = load_rules()
    code_hits = [r for r in rules if r.match_type == "code" and code and code.startswith(r.pattern)]
    if code_hits:
        return max(code_hits, key=lambda r: len(r.pattern))
    for r in rules:
        if r.match_type == "keyword" and r.pattern in desc:
            return r
    return None
