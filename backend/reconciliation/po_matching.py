"""Purchase-order reconciliation. Pure logic over POData; DB loading lives in services/checks.py."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal
from difflib import SequenceMatcher

from backend.config import Settings, get_settings
from backend.schemas import Finding, InvoiceData, LineItem, ReconStatus, Severity
from backend.validation.hsn import clean_code


@dataclass
class POLine:
    id: int
    line_no: int
    description: str | None
    hsn_sac: str | None
    quantity: Decimal
    unit_price: Decimal
    gst_rate: Decimal | None = None
    previously_invoiced: Decimal = Decimal("0")   # from other live invoices

    @property
    def remaining(self) -> Decimal:
        return self.quantity - self.previously_invoiced


@dataclass
class POData:
    id: int
    po_number: str
    vendor_gstin: str | None
    lines: list[POLine]


@dataclass
class ReconResult:
    status: ReconStatus
    findings: list[Finding] = field(default_factory=list)
    line_matches: dict[int, int] = field(default_factory=dict)   # invoice line_no -> po_item id
    matched_lines: int = 0
    unmatched_lines: int = 0
    po_id: int | None = None


def _tok(s: str | None) -> str:
    return re.sub(r"[^a-z0-9 ]", " ", (s or "").lower()).strip()


def desc_similarity(a: str | None, b: str | None) -> float:
    x, y = _tok(a), _tok(b)
    if not x or not y:
        return 0.0
    if x in y or y in x:
        return max(0.9, SequenceMatcher(None, x, y).ratio())
    tx, ty = set(x.split()), set(y.split())
    jacc = len(tx & ty) / len(tx | ty)
    return max(SequenceMatcher(None, x, y).ratio(), jacc)


def _score(li: LineItem, pl: POLine) -> float:
    d = desc_similarity(li.description, pl.description)
    h1, h2 = clean_code(li.hsn_sac), clean_code(pl.hsn_sac)
    if h1 and h2:
        hs = 1.0 if h1 == h2 else (0.6 if h1[:4] == h2[:4] else 0.0)
        return 0.5 * hs + 0.5 * d
    return d


def match_lines(items: list[LineItem], po_lines: list[POLine], threshold: float = 0.6) -> dict[int, POLine]:
    """Greedy global best-first assignment (each PO line used at most once)."""
    cands = sorted(((_score(li, pl), li.line_no, pl.id) for li in items for pl in po_lines), reverse=True)
    by_id = {pl.id: pl for pl in po_lines}
    out: dict[int, POLine] = {}
    used: set[int] = set()
    for sc, ln, pid in cands:
        if sc < threshold:
            break
        if ln in out or pid in used:
            continue
        out[ln] = by_id[pid]
        used.add(pid)
    return out


def reconcile(inv: InvoiceData, po: POData | None, settings: Settings | None = None) -> ReconResult:
    s = settings or get_settings()
    F: list[Finding] = []

    def add(code: str, sev: Severity, msg: str, line: int | None = None, expected: str | None = None,
            actual: str | None = None, fld: str | None = None) -> None:
        F.append(Finding(code=code, severity=sev, category="reconciliation", message=msg, line_no=line,
                         expected=expected, actual=actual, field=fld))

    if not inv.po_number:
        add("R001", Severity.WARNING, "Invoice does not reference a purchase order.", fld="po_number")
        return ReconResult(ReconStatus.NO_PO, F)
    if po is None:
        add("R002", Severity.ERROR, f"Purchase order '{inv.po_number}' was not found.", fld="po_number",
            actual=inv.po_number)
        return ReconResult(ReconStatus.PO_NOT_FOUND, F)

    if po.vendor_gstin and inv.vendor_gstin and po.vendor_gstin.upper() != inv.vendor_gstin.upper():
        add("R003", Severity.ERROR, "Invoice vendor differs from the vendor on the purchase order.",
            expected=po.vendor_gstin, actual=inv.vendor_gstin, fld="vendor_gstin")

    matches = match_lines(inv.items, po.lines)
    partial = False
    for li in inv.items:
        n = li.line_no
        pl = matches.get(n)
        if pl is None:
            add("R010", Severity.ERROR, f"Line {n}: item is not on purchase order {po.po_number}.", line=n,
                actual=(li.description or li.hsn_sac or "")[:60])
            continue
        if li.quantity is not None:
            if li.quantity > pl.remaining + s.po_qty_epsilon:
                add("R020", Severity.ERROR,
                    f"Line {n}: invoiced quantity exceeds the remaining PO quantity.", line=n,
                    expected=f"{pl.remaining:g}", actual=f"{li.quantity:g}", fld="quantity")
            elif li.quantity < pl.remaining - s.po_qty_epsilon:
                partial = True
                add("R021", Severity.INFO, f"Line {n}: partial delivery ({li.quantity:g} of {pl.remaining:g} remaining).",
                    line=n, expected=f"{pl.remaining:g}", actual=f"{li.quantity:g}", fld="quantity")
        if li.unit_price is not None and pl.unit_price:
            diff_pct = abs(li.unit_price - pl.unit_price) / pl.unit_price * 100
            if diff_pct > s.po_price_tolerance_pct:
                add("R030", Severity.ERROR, f"Line {n}: unit price differs from the PO price by {diff_pct:.1f}%.",
                    line=n, expected=f"{pl.unit_price:.2f}", actual=f"{li.unit_price:.2f}", fld="unit_price")
        if li.gst_rate is not None and pl.gst_rate is not None and li.gst_rate != pl.gst_rate:
            add("R031", Severity.WARNING, f"Line {n}: GST rate differs from the PO rate.", line=n,
                expected=str(pl.gst_rate), actual=str(li.gst_rate), fld="gst_rate")
    billed = {pl.id for pl in matches.values()}
    for pl in po.lines:
        if pl.id not in billed and pl.remaining > s.po_qty_epsilon:
            partial = True
            add("R040", Severity.INFO, f"PO line {pl.line_no} is not billed on this invoice (remaining {pl.remaining:g}).",
                expected=f"{pl.remaining:g}")

    has_err = any(f.severity == Severity.ERROR for f in F)
    status = ReconStatus.MISMATCH if has_err else (ReconStatus.PARTIAL if partial else ReconStatus.MATCHED)
    return ReconResult(status, F, {ln: pl.id for ln, pl in matches.items()}, len(matches),
                       len(inv.items) - len(matches), po.id)
