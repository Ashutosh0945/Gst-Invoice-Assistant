from datetime import date
from decimal import Decimal as D

from backend.itc.eligibility import ItcInput, ItcLine, assess, claim_deadline

TODAY = date(2026, 9, 24)


def _inp(lines, **kw):
    base = dict(invoice_status="AUTO_APPROVED", invoice_date=date(2026, 8, 10), lines=lines, header_tax=D("0"),
                gstr2b_status="IN_2B", twob_itc_available=True, payment_date=date(2026, 8, 20))
    base.update(kw)
    return ItcInput(**base)


OFFICE = ItcLine(1, "Office chair", "9403", D("1116.00"))
CAR = ItcLine(2, "Company car", "8703", D("207000.00"))
CAB = ItcLine(3, "Rent-a-cab airport transfer", "996601", D("720.00"))
COACH = ItcLine(4, "Coach hire", "996425", D("1900.00"))
GIFT = ItcLine(5, "Diwali gift hampers", "2106", D("900.00"))


def _codes(d):
    return [r["code"] for r in d.reasons]


def test_plain_invoice_in_2b_is_eligible():
    d = assess(_inp([OFFICE]), today=TODAY, same_line_prefixes=[])
    assert d.status == "ELIGIBLE" and d.eligible_itc == D("1116.00")
    assert d.claim_deadline == date(2027, 11, 30)


def test_blocked_and_partial_credit():
    d = assess(_inp([CAR]), today=TODAY, same_line_prefixes=[])
    assert d.status == "BLOCKED" and d.blocked_itc == D("207000.00") and "I010" in _codes(d)
    d = assess(_inp([OFFICE, CAB]), today=TODAY, same_line_prefixes=[])
    assert d.status == "PARTIALLY_ELIGIBLE" and d.eligible_itc == D("1116.00") and d.blocked_itc == D("720.00")


def test_review_rules_by_code_and_keyword():
    d = assess(_inp([OFFICE, COACH, GIFT]), today=TODAY, same_line_prefixes=[])
    assert d.status == "NEEDS_REVIEW" and d.review_itc == D("2800.00") and _codes(d).count("I011") == 2


def test_own_line_of_business_unblocks_travel_services():
    d = assess(_inp([CAB, COACH]), today=TODAY, same_line_prefixes=["9966", "9964"])
    assert d.status == "ELIGIBLE" and d.eligible_itc == D("2620.00") and _codes(d).count("I012") == 2


def test_missing_in_2b_moves_credit_to_at_risk():
    d = assess(_inp([OFFICE], gstr2b_status="MISSING_IN_2B"), today=TODAY, same_line_prefixes=[])
    assert d.status == "NOT_IN_2B" and d.at_risk_itc == D("1116.00") and d.eligible_itc == 0


def test_portal_says_itc_not_available():
    d = assess(_inp([OFFICE], twob_itc_available=False, twob_reason="time limit"), today=TODAY,
               same_line_prefixes=[])
    assert d.status == "BLOCKED" and "I021" in _codes(d)


def test_no_2b_yet_is_provisional():
    d = assess(_inp([OFFICE], gstr2b_status=None), today=TODAY, same_line_prefixes=[])
    assert d.status == "AWAITING_2B" and d.eligible_itc == D("1116.00")


def test_rule_37_unpaid_after_180_days():
    d = assess(_inp([OFFICE], invoice_date=date(2026, 3, 1), payment_date=None), today=TODAY,
               same_line_prefixes=[])
    assert d.status == "REVERSAL_DUE" and d.at_risk_itc == D("1116.00") and "I030" in _codes(d)
    d = assess(_inp([OFFICE], invoice_date=date(2026, 8, 1), payment_date=None), today=TODAY,
               same_line_prefixes=[])
    assert d.status == "ELIGIBLE"


def test_section_16_4_deadline():
    assert claim_deadline(date(2026, 3, 31)) == date(2026, 11, 30)
    assert claim_deadline(date(2026, 4, 1)) == date(2027, 11, 30)
    d = assess(_inp([OFFICE], invoice_date=date(2024, 6, 1), gstr2b_status="MISSING_IN_2B",
                    payment_date=date(2024, 6, 5)), today=TODAY, same_line_prefixes=[])
    assert d.status == "LAPSED" and d.blocked_itc == D("1116.00")


def test_rejected_duplicate_and_zero_tax_are_not_applicable():
    assert assess(_inp([OFFICE], invoice_status="REJECTED"), today=TODAY, same_line_prefixes=[]).status \
        == "NOT_APPLICABLE"
    assert assess(_inp([OFFICE], possible_duplicate=True), today=TODAY, same_line_prefixes=[]).status \
        == "NOT_APPLICABLE"
    assert assess(_inp([ItcLine(1, "Rice", "1006", D("0"))]), today=TODAY, same_line_prefixes=[]).status \
        == "NOT_APPLICABLE"


def test_reverse_charge_is_flagged():
    d = assess(_inp([OFFICE], reverse_charge=True), today=TODAY, same_line_prefixes=[])
    assert "I040" in _codes(d)


def test_einvoice_mismatch_holds_credit_until_approved():
    d = assess(_inp([OFFICE], einvoice_problem=True), today=TODAY, same_line_prefixes=[])
    assert d.status == "NEEDS_REVIEW" and d.review_itc == D("1116.00") and "I060" in _codes(d)
    d = assess(_inp([OFFICE], einvoice_problem=True, invoice_status="APPROVED"), today=TODAY, same_line_prefixes=[])
    assert d.status == "ELIGIBLE"
