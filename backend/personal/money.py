"""Indian-style money formatting for plain-language messages."""
from __future__ import annotations


def inr(v, decimals: bool = False) -> str:
    """1234567 -> '₹12,34,567' (Indian digit grouping)."""
    if v is None:
        return "—"
    n = float(v)
    neg = n < 0
    whole, frac = f"{abs(n):.2f}".split(".")
    head, tail = whole[:-3], whole[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    body = ",".join(groups + [tail]) if groups else tail
    return f"{'-' if neg else ''}₹{body}" + (f".{frac}" if decimals else "")
