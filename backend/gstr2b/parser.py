"""Parse the GSTR-2B JSON downloaded from the GST portal.

Portal path: Returns Dashboard -> GSTR-2B -> Download (JSON). The file has
the shape  {"data": {"gstin", "rtnprd", "gendt", "docdata": {"b2b": [...]}}}
(some downloads omit the outer "data"). Each b2b entry is one supplier
(ctin = supplier GSTIN) with a list of invoices, each carrying item-wise
tax. Only the B2B section is reconciled here; credit/debit notes (cdnr) and
amendments (b2ba) are counted but not matched (see README, limitations).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

ZERO = Decimal("0")


@dataclass
class TwoBInvoice:
    supplier_gstin: str
    supplier_name: str | None
    invoice_number: str
    invoice_date: date | None
    invoice_value: Decimal | None
    taxable_value: Decimal
    igst: Decimal
    cgst: Decimal
    sgst: Decimal
    cess: Decimal
    place_of_supply: str | None
    reverse_charge: bool
    itc_available: bool
    itc_unavailable_reason: str | None
    supplier_filed_on: str | None
    irn: str | None

    @property
    def total_tax(self) -> Decimal:
        return self.igst + self.cgst + self.sgst + self.cess


@dataclass
class TwoBStatement:
    gstin: str | None
    return_period: str             # MMYYYY
    generated_on: str | None
    invoices: list[TwoBInvoice] = field(default_factory=list)
    skipped_sections: dict[str, int] = field(default_factory=dict)

    @property
    def period_start(self) -> date:
        return date(int(self.return_period[2:]), int(self.return_period[:2]), 1)

    @property
    def period_end(self) -> date:
        m, y = int(self.return_period[:2]), int(self.return_period[2:])
        nxt = date(y + (m // 12), m % 12 + 1, 1)
        return date.fromordinal(nxt.toordinal() - 1)


class Gstr2bFormatError(ValueError):
    pass


# Reason codes the portal uses when itcavl = "N".
ITC_UNAVAILABLE_REASONS = {
    "P": "Place of supply is in the same state as supplier but IGST charged (or vice versa)",
    "C": "Invoice date is beyond the time limit under Section 16(4)",
    "D": "Supplier's registration was cancelled / ITC restricted",
}


def _dec(v) -> Decimal:
    if v in (None, ""):
        return ZERO
    try:
        return Decimal(str(v)).quantize(Decimal("0.01"))
    except InvalidOperation:
        return ZERO


def _date(v: str | None) -> date | None:
    if not v:
        return None
    for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(v.strip(), fmt).date()
        except ValueError:
            continue
    return None


def parse_gstr2b(raw: bytes | str | dict) -> TwoBStatement:
    if isinstance(raw, (bytes, str)):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise Gstr2bFormatError(f"File is not valid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise Gstr2bFormatError("Expected a JSON object at the top level.")
    body = raw.get("data", raw)
    period = str(body.get("rtnprd") or "").strip()
    if len(period) != 6 or not period.isdigit():
        raise Gstr2bFormatError("Missing or invalid return period 'rtnprd' (expected MMYYYY, e.g. 032026).")
    docdata = body.get("docdata") or {}
    if "b2b" not in docdata:
        raise Gstr2bFormatError("No 'docdata.b2b' section found — is this a GSTR-2B JSON download?")

    stmt = TwoBStatement(gstin=body.get("gstin"), return_period=period, generated_on=body.get("gendt"))
    for supplier in docdata.get("b2b") or []:
        ctin = (supplier.get("ctin") or "").strip().upper()
        for inv in supplier.get("inv") or []:
            items = inv.get("items") or []
            stmt.invoices.append(TwoBInvoice(
                supplier_gstin=ctin,
                supplier_name=supplier.get("trdnm"),
                invoice_number=str(inv.get("inum") or "").strip(),
                invoice_date=_date(inv.get("dt")),
                invoice_value=_dec(inv.get("val")) if inv.get("val") is not None else None,
                taxable_value=sum((_dec(i.get("txval")) for i in items), ZERO),
                igst=sum((_dec(i.get("igst")) for i in items), ZERO),
                cgst=sum((_dec(i.get("cgst")) for i in items), ZERO),
                sgst=sum((_dec(i.get("sgst")) for i in items), ZERO),
                cess=sum((_dec(i.get("cess")) for i in items), ZERO),
                place_of_supply=inv.get("pos"),
                reverse_charge=str(inv.get("rev", "N")).upper() == "Y",
                itc_available=str(inv.get("itcavl", "Y")).upper() != "N",
                itc_unavailable_reason=ITC_UNAVAILABLE_REASONS.get(inv.get("rsn") or "", inv.get("rsn") or None),
                supplier_filed_on=supplier.get("supfildt"),
                irn=inv.get("irn"),
            ))
    for section, entries in docdata.items():
        if section != "b2b" and isinstance(entries, list):
            stmt.skipped_sections[section] = len(entries)
    return stmt
