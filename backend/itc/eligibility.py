"""Decide how much input tax credit an invoice can claim, and why. Pure function.

Rules applied (CGST Act, 2017 and CGST Rules):
  * Section 17(5)  - blocked credits, per line (see rules.py / blocked_credits.csv).
                     A blocked line becomes claimable when its HSN/SAC is in your own
                     line of business (ITC_SAME_LINE_PREFIXES), mirroring the Act's
                     "same category of outward supply" exceptions.
  * Section 16(2)(aa) - credit only if the invoice appears in your GSTR-2B.
  * GSTR-2B itcavl = N - the portal itself says the credit is not available.
  * Rule 37        - reverse the credit if the vendor is not paid within 180 days.
  * Section 16(4)  - claim by 30 November after the end of the financial year.
  * Reverse charge - tax must be paid by you before it can be claimed (flagged, not blocked).

Status precedence (worst first):
  NOT_APPLICABLE > LAPSED > BLOCKED > NOT_IN_2B > REVERSAL_DUE > NEEDS_REVIEW
  > PARTIALLY_ELIGIBLE > AWAITING_2B > ELIGIBLE
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from backend.itc.rules import match_rule

ZERO = Decimal("0.00")


@dataclass
class ItcLine:
    line_no: int
    description: str | None
    hsn_sac: str | None
    tax: Decimal


@dataclass
class ItcInput:
    invoice_status: str
    invoice_date: date | None
    lines: list[ItcLine]
    header_tax: Decimal                      # used when no line-level tax was extracted
    gstr2b_status: str | None                # IN_2B / MISSING_IN_2B / None (no 2B imported yet)
    twob_itc_available: bool | None = None
    twob_reason: str | None = None
    reverse_charge: bool = False
    payment_date: date | None = None
    possible_duplicate: bool = False          # an unresolved DUPLICATE_* error on the invoice
    einvoice_problem: bool = False            # signed QR disagrees with the printout, or is forged


@dataclass
class ItcDecision:
    status: str
    total_itc: Decimal = ZERO
    eligible_itc: Decimal = ZERO
    blocked_itc: Decimal = ZERO
    review_itc: Decimal = ZERO
    at_risk_itc: Decimal = ZERO
    claim_deadline: date | None = None
    payment_due_by: date | None = None
    reasons: list[dict] = field(default_factory=list)


def claim_deadline(invoice_date: date) -> date:
    """Section 16(4): 30 November following the end of the financial year (April-March)."""
    fy_end_year = invoice_date.year + 1 if invoice_date.month >= 4 else invoice_date.year
    return date(fy_end_year, 11, 30)


def assess(inp: ItcInput, *, today: date, same_line_prefixes: list[str], payment_days: int = 180) -> ItcDecision:
    reasons: list[dict] = []

    def why(code: str, severity: str, message: str, line_no: int | None = None) -> None:
        reasons.append({"code": code, "severity": severity, "message": message, "line_no": line_no})

    if inp.invoice_status in ("REJECTED", "FAILED"):
        why("I000", "INFO", "Invoice was rejected, so no credit is claimed on it.")
        return ItcDecision("NOT_APPLICABLE", reasons=reasons)

    if inp.possible_duplicate and inp.invoice_status != "APPROVED":
        why("I002", "WARNING", "Possible duplicate of another invoice; excluded from credit until a reviewer "
            "approves it.")
        return ItcDecision("NOT_APPLICABLE", reasons=reasons)

    lines = [l for l in inp.lines if l.tax and l.tax > 0]
    total = sum((l.tax for l in lines), ZERO) if lines else (inp.header_tax or ZERO)
    if total <= 0:
        why("I001", "INFO", "No GST was charged on this invoice, so there is no credit to claim.")
        return ItcDecision("NOT_APPLICABLE", reasons=reasons)

    blocked = review = ZERO
    for l in lines:
        rule = match_rule(l.hsn_sac, l.description)
        if rule is None:
            continue
        own_line = bool(l.hsn_sac) and any(l.hsn_sac.startswith(p) for p in same_line_prefixes)
        if own_line:
            why("I012", "INFO", f"Line {l.line_no}: {rule.category} is normally restricted under Section "
                f"{rule.section}, but it is in your own line of business, so it is claimable.", l.line_no)
            continue
        if rule.action == "BLOCKED":
            blocked += l.tax
            why("I010", "ERROR", f"Line {l.line_no}: {rule.category} — blocked under Section {rule.section}. "
                f"{rule.note}", l.line_no)
        else:
            review += l.tax
            why("I011", "WARNING", f"Line {l.line_no}: {rule.category} — may be blocked under Section "
                f"{rule.section}. {rule.note}", l.line_no)

    d = ItcDecision("ELIGIBLE", total_itc=total, blocked_itc=blocked, review_itc=review)
    claimable = total - blocked - review
    d.eligible_itc = claimable

    if inp.invoice_date:
        d.claim_deadline = claim_deadline(inp.invoice_date)
        d.payment_due_by = inp.invoice_date + timedelta(days=payment_days)

    status = "ELIGIBLE"
    if blocked == total:
        status = "BLOCKED"
    elif review > 0:
        status = "NEEDS_REVIEW"
    elif blocked > 0:
        status = "PARTIALLY_ELIGIBLE"

    # GSTR-2B presence (Section 16(2)(aa)).
    if inp.gstr2b_status == "IN_2B":
        if inp.twob_itc_available is False:
            why("I021", "ERROR", "GSTR-2B marks this invoice's credit as not available"
                + (f": {inp.twob_reason}." if inp.twob_reason else "."))
            d.blocked_itc, d.eligible_itc, d.review_itc = total, ZERO, ZERO
            status = "BLOCKED"
    elif inp.gstr2b_status == "MISSING_IN_2B":
        d.at_risk_itc, d.eligible_itc = claimable + review, ZERO
        why("I020", "ERROR", "The vendor has not reported this invoice in GSTR-1, so it is missing from your "
            "GSTR-2B. You cannot claim the credit until they do — follow up with the vendor.")
        if status not in ("BLOCKED",):
            status = "NOT_IN_2B"
    else:
        why("I022", "INFO", "No GSTR-2B has been imported for this period yet; credit is provisional.")
        if status == "ELIGIBLE":
            status = "AWAITING_2B"

    if inp.einvoice_problem and inp.invoice_status != "APPROVED" and status not in ("BLOCKED",):
        why("I060", "ERROR", "The printed invoice does not match its government-signed e-invoice QR code. "
            "Hold the credit until the vendor sends a corrected invoice.")
        d.review_itc += d.eligible_itc
        d.eligible_itc = ZERO
        status = "NEEDS_REVIEW"

    if inp.reverse_charge:
        why("I040", "WARNING", "Reverse charge applies: you must pay this tax to the government yourself "
            "before claiming it as credit.")

    # Rule 37 — 180-day payment.
    if d.payment_due_by and inp.payment_date is None and today > d.payment_due_by and status not in ("BLOCKED",):
        why("I030", "ERROR", f"Vendor not paid within {payment_days} days (due {d.payment_due_by}). "
            "Credit already claimed must be reversed with interest until payment is made.")
        d.at_risk_itc += d.eligible_itc
        d.eligible_itc = ZERO
        status = "REVERSAL_DUE"
    elif inp.payment_date and d.payment_due_by and inp.payment_date > d.payment_due_by:
        why("I031", "INFO", f"Vendor was paid after the {payment_days}-day limit; credit can be re-claimed "
            "now that payment is made.")

    # Section 16(4) — time limit.
    if d.claim_deadline and today > d.claim_deadline and inp.gstr2b_status != "IN_2B" and status != "BLOCKED":
        why("I050", "ERROR", f"The claim deadline under Section 16(4) passed on {d.claim_deadline}.")
        d.blocked_itc += d.eligible_itc + d.at_risk_itc
        d.eligible_itc = d.at_risk_itc = ZERO
        status = "LAPSED"

    d.status = status
    d.reasons = reasons
    return d
