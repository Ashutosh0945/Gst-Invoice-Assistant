"""HSN/SAC structural checks and (optional) reference-master lookup.

The bundled CSV (data/hsn/hsn_seed.csv) is a SMALL DEMO SEED. For real use, point
HSN_REFERENCE_PATH at a CSV export of the official GST portal HSN/SAC master
(columns: code,description[,gst_rate]).  Rate-consistency checks only run when gst_rate is present.
"""
from __future__ import annotations

import csv
import re
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

_SEED = Path(__file__).resolve().parents[2] / "data" / "hsn" / "hsn_seed.csv"
HSN_LENGTHS = (2, 4, 6, 8)


def clean_code(raw: str | None) -> str | None:
    if not raw:
        return None
    c = re.sub(r"[\s.\-]", "", str(raw))
    return c or None


def is_sac(code: str) -> bool:
    return len(code) == 6 and code.startswith("99")


def structure_problem(code: str | None) -> str | None:
    """Return a human-readable structural problem, or None if the code looks well-formed."""
    if not code:
        return "missing"
    if not code.isdigit():
        return "contains non-digit characters"
    if code.startswith("99"):
        return None if len(code) == 6 else "SAC codes must be 6 digits"
    if len(code) not in (4, 6, 8):
        return f"HSN must be 4, 6 or 8 digits (got {len(code)})"
    chapter = int(code[:2])
    if chapter == 0 or chapter > 97 or chapter == 77:
        return f"chapter {code[:2]} does not exist in the HS nomenclature"
    return None


class HSNReference:
    def __init__(self, rows: dict[str, tuple[str, Decimal | None]] | None = None):
        self.rows = rows or {}

    @classmethod
    def from_csv(cls, path: Path) -> "HSNReference":
        rows: dict[str, tuple[str, Decimal | None]] = {}
        with open(path, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                code = clean_code(r.get("code"))
                if not code:
                    continue
                rate = r.get("gst_rate")
                rows[code] = (r.get("description", ""), Decimal(rate) if rate else None)
        return cls(rows)

    def lookup(self, code: str) -> tuple[str, str, Decimal | None] | None:
        """Exact match, else longest known prefix. Returns (matched_code, description, rate)."""
        for n in range(len(code), 1, -1):
            hit = self.rows.get(code[:n])
            if hit:
                return code[:n], hit[0], hit[1]
        return None

    def __len__(self) -> int:
        return len(self.rows)


@lru_cache
def load_reference(path: str | None = None) -> HSNReference:
    p = Path(path) if path else _SEED
    return HSNReference.from_csv(p) if p.exists() else HSNReference()
