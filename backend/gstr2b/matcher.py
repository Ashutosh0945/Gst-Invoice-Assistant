"""Match GSTR-2B invoices to the purchase register. Pure functions, no I/O.

A pair is only ever considered when the supplier GSTIN is identical. Within
one supplier, candidates are scored on invoice-number similarity, and then
checked on amounts and date. Assignment is greedy one-to-one, best score
first, so one register invoice can never satisfy two 2B lines.

Outcomes for each 2B line:
  MATCHED          same number (after normalisation), amounts within tolerance, same date
  FUZZY_MATCHED    number differs slightly (e.g. "INV-045" vs "INV/45") but amounts agree
  DATE_MISMATCH    matched, amounts agree, dates differ
  AMOUNT_MISMATCH  matched on number, but taxable value or tax differ beyond tolerance
  MISSING_IN_BOOKS the supplier reported it; you have no such invoice
And for each register invoice in the return period with no partner:
  MISSING_IN_2B    you recorded it; the supplier has not reported it -> ITC at risk
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from difflib import SequenceMatcher

from backend.gstr2b.parser import TwoBInvoice


@dataclass
class BookInvoice:
    id: object
    vendor_gstin: str | None
    invoice_number: str | None
    invoice_date: date | None
    taxable_value: Decimal | None
    total_tax: Decimal | None


@dataclass
class MatchResult:
    twob_index: int
    book_id: object | None
    status: str
    score: float | None
    notes: str | None


def normalize_invoice_number(s: str | None) -> str:
    """Upper-case, drop separators, and strip leading zeros from each digit run.
    'inv/0045' -> 'INV45', 'INV-45' -> 'INV45'."""
    s = re.sub(r"[^A-Z0-9]", "", (s or "").upper())
    return re.sub(r"0+(\d)", r"\1", s)


def _osa_distance(a: str, b: str) -> int:
    """Edit distance where swapping two adjacent characters counts as one edit
    (the most common typing mistake in invoice numbers)."""
    d = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i in range(len(a) + 1):
        d[i][0] = i
    for j in range(len(b) + 1):
        d[0][j] = j
    for i in range(1, len(a) + 1):
        for j in range(1, len(b) + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + cost)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                d[i][j] = min(d[i][j], d[i - 2][j - 2] + 1)
    return d[-1][-1]


def number_similarity(a: str | None, b: str | None) -> float:
    na, nb = normalize_invoice_number(a), normalize_invoice_number(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    edit = 1 - _osa_distance(na, nb) / max(len(na), len(nb))
    return max(edit, SequenceMatcher(None, na, nb).ratio())


def _inr(v: Decimal | None) -> str:
    """Indian digit grouping: 1234567.5 -> '₹12,34,567.50'."""
    if v is None:
        return "—"
    whole, frac = f"{abs(v):.2f}".split(".")
    head, tail = whole[:-3], whole[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    body = ",".join(groups + [tail]) if groups else tail
    return f"{'-' if v < 0 else ''}₹{body}.{frac}"


def _close(a: Decimal | None, b: Decimal | None, tol: Decimal) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return abs(a - b) <= max(tol, abs(b) * Decimal("0.001"))


def reconcile(twob: list[TwoBInvoice], books: list[BookInvoice], *, period_start: date, period_end: date,
              amount_tolerance: Decimal, fuzzy_threshold: float) -> tuple[list[MatchResult], list[object]]:
    """Returns (one MatchResult per 2B invoice, ids of in-period register invoices missing from 2B)."""
    by_gstin: dict[str, list[BookInvoice]] = {}
    for b in books:
        if b.vendor_gstin:
            by_gstin.setdefault(b.vendor_gstin.upper(), []).append(b)

    def amounts_ok(t: TwoBInvoice, b: BookInvoice) -> bool:
        return _close(t.taxable_value, b.taxable_value, amount_tolerance) and \
            _close(t.total_tax, b.total_tax, amount_tolerance)

    # Same number -> always a candidate (even if amounts differ: that is an AMOUNT_MISMATCH).
    # Similar number -> a candidate only when the amounts agree, so two different
    # invoices with look-alike numbers are never paired.
    candidates: list[tuple[float, int, BookInvoice]] = []
    for i, t in enumerate(twob):
        for b in by_gstin.get(t.supplier_gstin.upper(), []):
            score = number_similarity(t.invoice_number, b.invoice_number)
            if score == 1.0 or (score >= fuzzy_threshold and amounts_ok(t, b)):
                candidates.append((score, i, b))
    candidates.sort(key=lambda c: (-c[0], c[1]))

    used_books: set = set()
    results: dict[int, MatchResult] = {}
    for score, i, b in candidates:
        if i in results or b.id in used_books:
            continue
        t = twob[i]
        used_books.add(b.id)
        notes: list[str] = []
        if not amounts_ok(t, b):
            status = "AMOUNT_MISMATCH"
            notes.append(f"GSTR-2B shows {_inr(t.taxable_value)} + {_inr(t.total_tax)} tax; "
                         f"your books show {_inr(b.taxable_value)} + {_inr(b.total_tax)} tax")
        elif score < 1.0:
            status = "FUZZY_MATCHED"
            notes.append(f"Invoice number is {t.invoice_number} in GSTR-2B but {b.invoice_number} in your books")
        elif t.invoice_date and b.invoice_date and t.invoice_date != b.invoice_date:
            status = "DATE_MISMATCH"
            notes.append(f"GSTR-2B date {t.invoice_date:%d %b %Y}; your books {b.invoice_date:%d %b %Y}")
        else:
            status = "MATCHED"
        results[i] = MatchResult(i, b.id, status, round(score, 4), "; ".join(notes) or None)

    out = [results.get(i) or MatchResult(i, None, "MISSING_IN_BOOKS", None,
                                         "Supplier reported this invoice but it is not in your register")
           for i in range(len(twob))]
    missing_in_2b = [b.id for b in books
                     if b.id not in used_books and b.invoice_date and period_start <= b.invoice_date <= period_end]
    return out, missing_in_2b
