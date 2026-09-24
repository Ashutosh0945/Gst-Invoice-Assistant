"""Deterministic validation. Pure functions: InvoiceData in, list[Finding] out.

No I/O, no ML, no LLM. Every financial judgement in the system is made here or in
reconciliation/, and every finding carries a stable rule code for analytics.
"""
from __future__ import annotations

import re
from datetime import date
from decimal import Decimal

from backend.config import Settings, get_settings
from backend.schemas import Finding, InvoiceData, LineItem, Severity
from backend.validation import hsn as hsnlib
from backend.validation.gst import (
    GST_LAUNCH, gstin_checksum, gstin_format_ok, gstin_state, slab_status, STATE_CODES,
)

ZERO = Decimal("0")
INVOICE_NO_RE = re.compile(r"^[A-Za-z0-9/\-]{1,16}$")  # CGST Rule 46: <=16 chars, alnum + '-' '/'


def _n(x: Decimal | None) -> Decimal:
    return x if x is not None else ZERO


def _tol(base: Decimal, s: Settings) -> Decimal:
    return max(s.line_tolerance, abs(base) * s.line_tolerance_rel)


def _fmt(x: Decimal | None) -> str | None:
    return None if x is None else f"{x:.2f}"


def supply_type(inv: InvoiceData, s: Settings) -> str | None:
    """'intra' (CGST+SGST) or 'inter' (IGST) from vendor state vs place of supply; None if unknown."""
    vendor_state = gstin_state(inv.vendor_gstin)
    pos = inv.place_of_supply or gstin_state(inv.buyer_gstin) or gstin_state(s.our_gstin)
    if not vendor_state or not pos:
        return None
    return "intra" if vendor_state == pos else "inter"


def line_tax(li: LineItem) -> Decimal:
    return _n(li.cgst) + _n(li.sgst) + _n(li.igst) + _n(li.cess)


class _Out:
    def __init__(self) -> None:
        self.items: list[Finding] = []

    def add(self, code: str, sev: Severity, msg: str, *, field: str | None = None,
            line: int | None = None, expected: str | None = None, actual: str | None = None) -> None:
        self.items.append(Finding(code=code, severity=sev, category="validation", message=msg,
                                  field=field, line_no=line, expected=expected, actual=actual))


# ------------------------------------------------------------------------------ checks
def _required(inv: InvoiceData, o: _Out) -> None:
    for fld, code in (("vendor_gstin", "V001"), ("invoice_number", "V002"),
                      ("invoice_date", "V003"), ("grand_total", "V004")):
        if getattr(inv, fld) in (None, ""):
            o.add(code, Severity.ERROR, f"Required field '{fld}' could not be extracted.", field=fld)
    if not inv.items:
        o.add("V005", Severity.ERROR, "No line items were extracted.", field="items")


def _gstin(inv: InvoiceData, s: Settings, o: _Out) -> None:
    for fld, code, sev in (("vendor_gstin", "V010", Severity.ERROR), ("buyer_gstin", "V014", Severity.WARNING)):
        g = getattr(inv, fld)
        if not g:
            continue
        g = g.strip().upper()
        if not gstin_format_ok(g):
            o.add(code, sev, f"{fld} '{g}' does not match the 15-character GSTIN structure.",
                  field=fld, actual=g)
        elif g[:2] not in STATE_CODES:
            o.add("V011", sev, f"{fld} '{g}' has unknown state code {g[:2]}.",
                  field=fld, actual=g)
        elif gstin_checksum(g[:14]) != g[14]:
            o.add("V012", sev, f"{fld} '{g}' fails the GSTIN checksum (likely OCR or typing error).",
                  field=fld, expected=g[:14] + gstin_checksum(g[:14]), actual=g)
    v, b = (inv.vendor_gstin or "").upper(), (inv.buyer_gstin or "").upper()
    if v and v == b:
        o.add("V013", Severity.ERROR, "Vendor GSTIN equals buyer GSTIN (self-invoice).", field="vendor_gstin", actual=v)
    if s.our_gstin and b and b != s.our_gstin.upper():
        o.add("V015", Severity.WARNING, "Buyer GSTIN differs from our registered GSTIN.",
              field="buyer_gstin", expected=s.our_gstin.upper(), actual=b)


def _identity(inv: InvoiceData, o: _Out, today: date) -> None:
    if inv.invoice_number and not INVOICE_NO_RE.match(inv.invoice_number):
        o.add("V020", Severity.WARNING,
              "Invoice number violates CGST Rule 46 format (max 16 chars; letters, digits, '-' and '/').",
              field="invoice_number", actual=inv.invoice_number)
    if inv.invoice_date:
        if inv.invoice_date > today:
            o.add("V021", Severity.ERROR, "Invoice date is in the future.", field="invoice_date",
                  actual=inv.invoice_date.isoformat())
        elif inv.invoice_date < GST_LAUNCH:
            o.add("V022", Severity.ERROR, "Invoice date precedes the GST launch (2017-07-01).",
                  field="invoice_date", actual=inv.invoice_date.isoformat())


def _lines(inv: InvoiceData, s: Settings, o: _Out) -> None:
    st = supply_type(inv, s)
    for li in inv.items:
        n = li.line_no
        # arithmetic: qty * price - discount = taxable
        if li.quantity is not None and li.unit_price is not None and li.taxable_value is not None:
            exp = li.quantity * li.unit_price - _n(li.discount)
            if abs(exp - li.taxable_value) > _tol(exp, s):
                o.add("V030", Severity.ERROR, f"Line {n}: quantity x rate (less discount) does not equal taxable value.",
                      field="taxable_value", line=n, expected=_fmt(exp), actual=_fmt(li.taxable_value))
        # rate slab
        rate = li.gst_rate
        if rate is None and li.taxable_value and li.taxable_value > 0 and line_tax(li) > 0:
            rate = (line_tax(li) / li.taxable_value * 100).quantize(Decimal("0.01"))
            o.add("V031", Severity.WARNING, f"Line {n}: GST rate not shown; implied rate is {rate}%.",
                  field="gst_rate", line=n, actual=str(rate))
        if rate is not None:
            status = slab_status(rate, inv.invoice_date)
            if status == "invalid":
                o.add("V032", Severity.ERROR, f"Line {n}: GST rate {rate}% is not a valid GST slab.",
                      field="gst_rate", line=n, actual=str(rate))
            elif status == "legacy_after_cutover":
                o.add("V033", Severity.WARNING,
                      f"Line {n}: rate {rate}% was retired on 2025-09-22 but the invoice is dated later.",
                      field="gst_rate", line=n, actual=str(rate))
        # tax amount = taxable * rate
        if rate is not None and li.taxable_value is not None and (li.cgst is not None or li.sgst is not None
                                                                    or li.igst is not None):
            exp_tax = li.taxable_value * rate / 100
            if abs(exp_tax - line_tax(li)) > _tol(exp_tax, s):
                o.add("V034", Severity.ERROR, f"Line {n}: tax amount does not equal taxable value x rate.",
                      field="tax", line=n, expected=_fmt(exp_tax), actual=_fmt(line_tax(li)))
        if li.cgst is not None and li.sgst is not None and abs(li.cgst - li.sgst) > s.line_tolerance:
            o.add("V035", Severity.ERROR, f"Line {n}: CGST and SGST must be equal.", field="cgst", line=n,
                  expected=_fmt(li.cgst), actual=_fmt(li.sgst))
        # intra vs inter-state tax type (UTGST for UTs is captured in the SGST column)
        if st == "intra" and _n(li.igst) > 0:
            o.add("V036", Severity.ERROR, f"Line {n}: IGST charged on an intra-state supply (expect CGST+SGST).",
                  field="igst", line=n, actual=_fmt(li.igst))
        if st == "inter" and (_n(li.cgst) > 0 or _n(li.sgst) > 0):
            o.add("V037", Severity.ERROR, f"Line {n}: CGST/SGST charged on an inter-state supply (expect IGST).",
                  field="cgst", line=n, actual=_fmt(_n(li.cgst) + _n(li.sgst)))
        if li.taxable_value is not None and li.line_total is not None:
            exp_total = li.taxable_value + line_tax(li)
            if abs(exp_total - li.line_total) > _tol(exp_total, s):
                o.add("V038", Severity.ERROR, f"Line {n}: line total does not equal taxable value plus tax.",
                      field="line_total", line=n, expected=_fmt(exp_total), actual=_fmt(li.line_total))
    if st is None and inv.items:
        o.add("V039", Severity.INFO, "Supply type (intra/inter-state) could not be determined; tax-type check skipped.")


def _totals(inv: InvoiceData, s: Settings, o: _Out) -> None:
    def sum_of(attr: str) -> Decimal:
        return sum((_n(getattr(li, attr)) for li in inv.items), ZERO)

    pairs = (("subtotal", "taxable_value", "V040"), ("total_cgst", "cgst", "V041"),
             ("total_sgst", "sgst", "V042"), ("total_igst", "igst", "V043"), ("total_cess", "cess", "V044"))
    for tot_attr, line_attr, code in pairs:
        tot = getattr(inv, tot_attr)
        if tot is not None and inv.items and any(getattr(li, line_attr) is not None for li in inv.items):
            ssum = sum_of(line_attr)
            if abs(ssum - tot) > s.amount_tolerance:
                o.add(code, Severity.ERROR, f"Sum of line {line_attr} does not equal invoice {tot_attr}.",
                      field=tot_attr, expected=_fmt(ssum), actual=_fmt(tot))
    if inv.grand_total is not None:
        if inv.grand_total <= 0:
            o.add("V046", Severity.ERROR, "Grand total is zero or negative.", field="grand_total",
                  actual=_fmt(inv.grand_total))
            return
        base = inv.subtotal if inv.subtotal is not None else sum_of("taxable_value")
        cg = inv.total_cgst if inv.total_cgst is not None else sum_of("cgst")
        sg = inv.total_sgst if inv.total_sgst is not None else sum_of("sgst")
        ig = inv.total_igst if inv.total_igst is not None else sum_of("igst")
        ce = inv.total_cess if inv.total_cess is not None else sum_of("cess")
        exp = base + cg + sg + ig + ce + _n(inv.round_off)
        if base > 0 and abs(exp - inv.grand_total) > s.amount_tolerance:
            o.add("V045", Severity.ERROR, "Grand total does not equal taxable value + taxes + round-off.",
                  field="grand_total", expected=_fmt(exp), actual=_fmt(inv.grand_total))


def _hsn(inv: InvoiceData, s: Settings, o: _Out, ref: hsnlib.HSNReference) -> None:
    for li in inv.items:
        code = hsnlib.clean_code(li.hsn_sac)
        problem = hsnlib.structure_problem(code)
        if problem == "missing":
            o.add("V050", Severity.WARNING, f"Line {li.line_no}: HSN/SAC is missing.", field="hsn_sac", line=li.line_no)
            continue
        if problem:
            o.add("V051", Severity.ERROR, f"Line {li.line_no}: HSN/SAC '{code}' is malformed ({problem}).",
                  field="hsn_sac", line=li.line_no, actual=code)
            continue
        if len(ref):
            hit = ref.lookup(code)
            if hit is None:
                o.add("V052", Severity.WARNING, f"Line {li.line_no}: HSN/SAC '{code}' not found in the reference master.",
                      field="hsn_sac", line=li.line_no, actual=code)
            elif hit[2] is not None and li.gst_rate is not None and hit[2] != li.gst_rate:
                o.add("V053", Severity.WARNING,
                      f"Line {li.line_no}: rate {li.gst_rate}% differs from the reference rate for HSN/SAC {hit[0]}.",
                      field="gst_rate", line=li.line_no, expected=str(hit[2]), actual=str(li.gst_rate))
        if hsnlib.is_sac(code) and li.quantity is not None and li.unit and li.unit.upper() in {"KG", "KGS", "MTR", "PCS", "NOS"}:
            o.add("V054", Severity.INFO, f"Line {li.line_no}: SAC code with a goods-type unit '{li.unit}'.",
                  field="hsn_sac", line=li.line_no, actual=code)


def validate(inv: InvoiceData, settings: Settings | None = None, hsn_ref: hsnlib.HSNReference | None = None,
             today: date | None = None) -> list[Finding]:
    s = settings or get_settings()
    ref = hsn_ref if hsn_ref is not None else hsnlib.load_reference(str(s.hsn_reference_path) if s.hsn_reference_path else None)
    o = _Out()
    _required(inv, o)
    _gstin(inv, s, o)
    _identity(inv, o, today or date.today())
    _lines(inv, s, o)
    _totals(inv, s, o)
    _hsn(inv, s, o, ref)
    return o.items
