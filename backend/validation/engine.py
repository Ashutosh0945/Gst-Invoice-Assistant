"""Deterministic rule engine: GST arithmetic, tax-type consistency, HSN/SAC
checks, and general data-quality validation. Nothing here calls the LLM —
this module is the source of truth for every number in the system.
"""
from __future__ import annotations

from decimal import Decimal

from backend.config import get_settings
from backend.schemas import Finding, InvoiceData, LineItem, Severity
from backend.validation.gstin import checksum_valid, is_well_formed, state_code
from backend.validation.hsn_reference import is_valid_format, lookup

TWOPLACES = Decimal("0.01")


def _close(a: Decimal | None, b: Decimal | None, abs_tol: Decimal, rel_tol: Decimal) -> bool:
    if a is None or b is None:
        return False
    diff = abs(a - b)
    tol = max(abs_tol, rel_tol * abs(b))
    return diff <= tol


def _line_findings(line: LineItem, settings) -> list[Finding]:
    findings: list[Finding] = []

    # --- HSN/SAC presence & validity ---
    if not line.hsn_sac:
        findings.append(Finding(
            code="HSN_MISSING", severity=Severity.WARNING, category="validation",
            message="Line item has no HSN/SAC code.", line_no=line.line_no, field="hsn_sac",
        ))
    elif not is_valid_format(line.hsn_sac):
        findings.append(Finding(
            code="HSN_INVALID_FORMAT", severity=Severity.ERROR, category="validation",
            message=f"HSN/SAC '{line.hsn_sac}' is not a valid 2/4/6/8-digit code.",
            line_no=line.line_no, field="hsn_sac", actual=line.hsn_sac,
        ))
    else:
        ref = lookup(line.hsn_sac)
        if ref is None:
            findings.append(Finding(
                code="HSN_NOT_IN_REFERENCE", severity=Severity.WARNING, category="validation",
                message=f"HSN/SAC '{line.hsn_sac}' was not found in the reference table (unverified).",
                line_no=line.line_no, field="hsn_sac", actual=line.hsn_sac,
            ))
        elif len(ref.get("gst_rates") or []) > 1 and line.gst_rate is not None:
            allowed = [Decimal(str(r)) for r in ref["gst_rates"]]
            if line.gst_rate not in allowed:
                findings.append(Finding(
                    code="HSN_RATE_MISMATCH", severity=Severity.WARNING, category="validation",
                    message=(f"Invoice GST rate {line.gst_rate}% is not one of the rates "
                             f"({', '.join(f'{r:g}%' for r in allowed)}) that apply to SAC {line.hsn_sac}."),
                    line_no=line.line_no, field="gst_rate",
                    expected="|".join(f"{r:g}" for r in allowed), actual=str(line.gst_rate),
                ))
        elif ref.get("gst_rate") is not None and line.gst_rate is not None:
            if Decimal(str(ref["gst_rate"])) != line.gst_rate:
                findings.append(Finding(
                    code="HSN_RATE_MISMATCH", severity=Severity.WARNING, category="validation",
                    message=(f"Invoice GST rate {line.gst_rate}% differs from the reference rate "
                             f"{ref['gst_rate']}% typically associated with HSN {line.hsn_sac}."),
                    line_no=line.line_no, field="gst_rate",
                    expected=str(ref["gst_rate"]), actual=str(line.gst_rate),
                ))

    # --- quantity * unit_price - discount == taxable_value ---
    if line.quantity is not None and line.unit_price is not None:
        expected_taxable = (line.quantity * line.unit_price) - (line.discount or Decimal("0"))
        expected_taxable = expected_taxable.quantize(TWOPLACES)
        if line.taxable_value is not None and not _close(
            line.taxable_value, expected_taxable, settings.line_tolerance, settings.line_tolerance_rel
        ):
            findings.append(Finding(
                code="LINE_ARITHMETIC_MISMATCH", severity=Severity.ERROR, category="validation",
                message=(f"Line {line.line_no}: qty x unit_price - discount = {expected_taxable}, "
                         f"but invoice states taxable_value = {line.taxable_value}."),
                line_no=line.line_no, field="taxable_value",
                expected=str(expected_taxable), actual=str(line.taxable_value),
            ))

    # --- GST tax amount consistency: taxable_value * gst_rate/100 == cgst+sgst+igst+cess ---
    if line.taxable_value is not None and line.gst_rate is not None:
        expected_tax = (line.taxable_value * line.gst_rate / Decimal("100")).quantize(TWOPLACES)
        stated_tax = sum(x for x in (line.cgst, line.sgst, line.igst) if x is not None) or None
        if stated_tax is not None and not _close(
            stated_tax, expected_tax, settings.line_tolerance, settings.line_tolerance_rel
        ):
            findings.append(Finding(
                code="LINE_GST_MISMATCH", severity=Severity.ERROR, category="validation",
                message=(f"Line {line.line_no}: expected GST of {expected_tax} at {line.gst_rate}%, "
                         f"but CGST+SGST+IGST sums to {stated_tax}."),
                line_no=line.line_no, field="gst_rate",
                expected=str(expected_tax), actual=str(stated_tax),
            ))

    # --- CGST/SGST must be equal (intra-state) and IGST must be zero, or vice versa ---
    has_intra = (line.cgst or 0) or (line.sgst or 0)
    has_inter = line.igst or 0
    if has_intra and has_inter:
        findings.append(Finding(
            code="TAX_TYPE_CONFLICT", severity=Severity.ERROR, category="validation",
            message=f"Line {line.line_no} has both CGST/SGST and IGST populated; a line must be one or the other.",
            line_no=line.line_no, field="igst",
        ))
    if line.cgst is not None and line.sgst is not None and line.cgst != line.sgst:
        findings.append(Finding(
            code="CGST_SGST_MISMATCH", severity=Severity.WARNING, category="validation",
            message=f"Line {line.line_no}: CGST ({line.cgst}) should equal SGST ({line.sgst}) for intra-state supply.",
            line_no=line.line_no, field="cgst",
        ))

    # --- line_total == taxable_value + taxes ---
    # Not every invoice prints a per-line CGST/SGST/IGST split (many print it
    # only at the header level). When the line has none of those fields, fall
    # back to the tax amount implied by taxable_value * gst_rate rather than
    # silently treating the missing split as zero tax.
    if line.taxable_value is not None and line.line_total is not None:
        explicit_tax_fields = [x for x in (line.cgst, line.sgst, line.igst, line.cess) if x is not None]
        if explicit_tax_fields:
            tax_sum = sum(explicit_tax_fields)
        elif line.gst_rate is not None:
            tax_sum = (line.taxable_value * line.gst_rate / Decimal("100")).quantize(TWOPLACES)
        else:
            tax_sum = None
        expected_total = (line.taxable_value + tax_sum).quantize(TWOPLACES) if tax_sum is not None else None
        if expected_total is not None and not _close(line.line_total, expected_total, settings.line_tolerance, settings.line_tolerance_rel):
            findings.append(Finding(
                code="LINE_TOTAL_MISMATCH", severity=Severity.ERROR, category="validation",
                message=f"Line {line.line_no}: taxable_value + taxes = {expected_total}, but line_total = {line.line_total}.",
                line_no=line.line_no, field="line_total",
                expected=str(expected_total), actual=str(line.line_total),
            ))

    return findings


def _header_findings(inv: InvoiceData, settings) -> list[Finding]:
    findings: list[Finding] = []

    for label, gstin in (("vendor_gstin", inv.vendor_gstin), ("buyer_gstin", inv.buyer_gstin)):
        if not gstin:
            findings.append(Finding(
                code=f"{label.upper()}_MISSING", severity=Severity.WARNING, category="validation",
                message=f"{label.replace('_', ' ').title()} was not found on the invoice.", field=label,
            ))
        elif not is_well_formed(gstin):
            findings.append(Finding(
                code=f"{label.upper()}_MALFORMED", severity=Severity.ERROR, category="validation",
                message=f"{label.replace('_', ' ').title()} '{gstin}' does not match the GSTIN pattern.",
                field=label, actual=gstin,
            ))
        elif not checksum_valid(gstin):
            findings.append(Finding(
                code=f"{label.upper()}_CHECKSUM_INVALID", severity=Severity.ERROR, category="validation",
                message=f"{label.replace('_', ' ').title()} '{gstin}' fails the GSTIN checksum.",
                field=label, actual=gstin,
            ))

    if not inv.invoice_number:
        findings.append(Finding(
            code="INVOICE_NUMBER_MISSING", severity=Severity.ERROR, category="validation",
            message="Invoice number could not be extracted.", field="invoice_number",
        ))
    if not inv.invoice_date:
        findings.append(Finding(
            code="INVOICE_DATE_MISSING", severity=Severity.ERROR, category="validation",
            message="Invoice date could not be extracted.", field="invoice_date",
        ))

    # Cross-check header totals against the sum of line items. A tax-type
    # check only runs when at least one line actually reports that field --
    # many invoices show CGST/SGST/IGST only at the header level, with line
    # items carrying just taxable_value and gst_rate.
    if inv.items:
        sum_taxable = sum((li.taxable_value for li in inv.items if li.taxable_value is not None), Decimal("0"))
        checks = [("subtotal", inv.subtotal, sum_taxable, True)]
        for label, attr in (("total_cgst", "cgst"), ("total_sgst", "sgst"), ("total_igst", "igst")):
            values = [getattr(li, attr) for li in inv.items if getattr(li, attr) is not None]
            if values:
                checks.append((label, getattr(inv, label), sum(values, Decimal("0")), True))

        for label, header_val, summed, _enabled in checks:
            if header_val is not None and not _close(header_val, summed, settings.amount_tolerance, settings.line_tolerance_rel):
                findings.append(Finding(
                    code="HEADER_LINE_SUM_MISMATCH", severity=Severity.ERROR, category="validation",
                    message=f"Header {label} ({header_val}) does not match the sum of line items ({summed}).",
                    field=label, expected=str(summed), actual=str(header_val),
                ))

    # Grand total = subtotal + taxes + cess + round_off
    if inv.subtotal is not None and inv.grand_total is not None:
        tax_sum = sum((x for x in (inv.total_cgst, inv.total_sgst, inv.total_igst, inv.total_cess) if x is not None), Decimal("0"))
        expected_grand = inv.subtotal + tax_sum + (inv.round_off or Decimal("0"))
        if not _close(inv.grand_total, expected_grand, settings.amount_tolerance, settings.line_tolerance_rel):
            findings.append(Finding(
                code="GRAND_TOTAL_MISMATCH", severity=Severity.ERROR, category="validation",
                message=f"Grand total ({inv.grand_total}) does not equal subtotal + taxes + round-off ({expected_grand}).",
                field="grand_total", expected=str(expected_grand), actual=str(inv.grand_total),
            ))

    # Place-of-supply vs vendor/buyer state should agree with which tax type was charged.
    v_state = state_code(inv.vendor_gstin)
    b_state = state_code(inv.buyer_gstin)
    if v_state and b_state:
        same_state = v_state == b_state
        charged_igst = any((li.igst or 0) > 0 for li in inv.items)
        charged_intra = any((li.cgst or 0) > 0 or (li.sgst or 0) > 0 for li in inv.items)
        if same_state and charged_igst:
            findings.append(Finding(
                code="TAX_TYPE_WRONG_FOR_SAME_STATE", severity=Severity.ERROR, category="validation",
                message=f"Vendor and buyer are both in state {v_state}, but IGST was charged instead of CGST+SGST.",
                field="igst",
            ))
        if not same_state and charged_intra:
            findings.append(Finding(
                code="TAX_TYPE_WRONG_FOR_INTERSTATE", severity=Severity.ERROR, category="validation",
                message=f"Vendor (state {v_state}) and buyer (state {b_state}) differ, but CGST/SGST was charged instead of IGST.",
                field="cgst",
            ))

    return findings


def validate_invoice(inv: InvoiceData) -> list[Finding]:
    settings = get_settings()
    findings = _header_findings(inv, settings)
    for line in inv.items:
        findings.extend(_line_findings(line, settings))
    return findings
