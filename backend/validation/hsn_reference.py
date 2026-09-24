"""HSN/SAC reference lookup. Loaded from a CSV (bundled seed by default, or a
path the operator provides) with columns: hsn_sac, description, gst_rate.
"""
from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path

from backend.config import get_settings

SEED_PATH = Path(__file__).resolve().parents[2] / "data" / "hsn" / "hsn_seed.csv"


@lru_cache(maxsize=1)
def load_hsn_table() -> dict[str, dict]:
    settings = get_settings()
    path = settings.hsn_reference_path or SEED_PATH
    table: dict[str, dict] = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            code = row["hsn_sac"].strip()
            raw_rate = (row.get("gst_rate") or "").strip()
            rates = [float(r) for r in raw_rate.split("|") if r.strip()]
            table[code] = {
                "description": row["description"],
                # A single slab, or None when the rate depends on conditions ("5|18").
                "gst_rate": rates[0] if len(rates) == 1 else None,
                "gst_rates": rates,
            }
    return table


def lookup(hsn_sac: str | None) -> dict | None:
    if not hsn_sac:
        return None
    table = load_hsn_table()
    code = hsn_sac.strip()
    if code in table:
        return table[code]
    # HSN codes are hierarchical (2/4/6/8 digit); try progressively shorter prefixes.
    for length in (6, 4, 2):
        if len(code) >= length and code[:length] in table:
            return table[code[:length]]
    return None


def is_valid_format(hsn_sac: str | None) -> bool:
    if not hsn_sac:
        return False
    return hsn_sac.isdigit() and len(hsn_sac) in (2, 4, 6, 8)
