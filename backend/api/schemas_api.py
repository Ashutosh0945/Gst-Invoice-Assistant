"""Request/response models for the API (separate from the internal pipeline
schemas in app.schemas so API contracts can evolve independently)."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel


class InvoiceLineOut(BaseModel):
    id: UUID
    line_no: int
    description: str | None
    hsn_sac: str | None
    quantity: Decimal | None
    unit_price: Decimal | None
    taxable_value: Decimal | None
    gst_rate: Decimal | None
    cgst: Decimal | None
    sgst: Decimal | None
    igst: Decimal | None
    line_total: Decimal | None
    confidence: float

    model_config = {"from_attributes": True}


class FindingOut(BaseModel):
    id: UUID
    code: str
    category: str
    severity: str
    message: str
    field: str | None
    line_no: int | None

    model_config = {"from_attributes": True}


class ReconciliationOut(BaseModel):
    id: UUID
    invoice_line_no: int | None
    po_line_no: int | None
    status: str
    qty_invoiced: Decimal | None
    qty_po: Decimal | None
    price_invoiced: Decimal | None
    price_po: Decimal | None
    variance_pct: Decimal | None

    model_config = {"from_attributes": True}


class ItcAssessmentOut(BaseModel):
    status: str
    total_itc: Decimal
    eligible_itc: Decimal
    blocked_itc: Decimal
    review_itc: Decimal
    at_risk_itc: Decimal
    claim_deadline: date | None
    payment_due_by: date | None
    reasons: list | None

    model_config = {"from_attributes": True}


class InvoiceSummaryOut(BaseModel):
    id: UUID
    source_filename: str
    vendor_name_raw: str | None
    vendor_gstin_raw: str | None
    invoice_number: str | None
    invoice_date: date | None
    grand_total: Decimal | None
    status: str
    confidence_score: Decimal | None
    created_at: datetime
    einvoice_status: str | None = None
    gstr2b_status: str | None = None

    model_config = {"from_attributes": True}


class InvoiceDetailOut(InvoiceSummaryOut):
    po_number_raw: str | None
    llm_explanation: str | None
    reviewed_by: str | None
    reviewed_at: datetime | None
    review_notes: str | None
    items: list[InvoiceLineOut]
    findings: list[FindingOut]
    reconciliation: list[ReconciliationOut]
    buyer_gstin_raw: str | None = None
    subtotal: Decimal | None = None
    total_cgst: Decimal | None = None
    total_sgst: Decimal | None = None
    total_igst: Decimal | None = None
    irn: str | None = None
    einvoice_data: dict | None = None
    payment_date: date | None = None
    itc: ItcAssessmentOut | None = None


class PaymentIn(BaseModel):
    paid_on: date | None
    actor: str = "reviewer"


class QrVerifyIn(BaseModel):
    qr_text: str


class ReviewActionIn(BaseModel):
    reviewer: str
    notes: str | None = None


class CorrectionIn(BaseModel):
    reviewer: str
    header_fields: dict = {}
    line_corrections: list[dict] = []
    notes: str | None = None


class StatusSummaryOut(BaseModel):
    status: str
    invoice_count: int
    total_value: Decimal | None
    avg_confidence: Decimal | None


class DailyIntakeOut(BaseModel):
    day: str
    invoices_ingested: int
    auto_approved: int
    needs_review: int
    rejected: int


class GstByRateOut(BaseModel):
    gst_rate: Decimal | None
    invoice_count: int
    total_taxable_value: Decimal | None
    total_gst: Decimal | None


class HsnSummaryOut(BaseModel):
    hsn_sac: str | None
    line_count: int
    total_taxable_value: Decimal | None
    avg_gst_rate: Decimal | None


class VendorSpendOut(BaseModel):
    vendor_name: str | None
    gstin: str | None
    invoice_count: int
    total_spend: Decimal | None
    avg_confidence: Decimal | None


class FindingFrequencyOut(BaseModel):
    code: str
    category: str
    severity: str
    occurrence_count: int
    invoice_count: int


class ReconciliationSummaryOut(BaseModel):
    status: str
    line_count: int


class DuplicateFindingOut(BaseModel):
    invoice_id: str
    invoice_number: str | None
    source_filename: str
    code: str
    message: str
