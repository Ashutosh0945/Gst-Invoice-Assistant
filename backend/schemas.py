"""Pydantic contracts shared by every pipeline stage.

Money is always Decimal. The LLM never sees or produces objects of these types.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class OCRWord(BaseModel):
    text: str
    bbox: tuple[float, float, float, float]  # x0, y0, x1, y1 in page-image pixels
    conf: float = 1.0                         # 0..1 (native PDF text => 1.0)


class PageData(BaseModel):
    page: int
    width: int
    height: int
    source: Literal["native", "ocr"]
    words: list[OCRWord]
    deskew_angle: float = 0.0


class LineItem(BaseModel):
    line_no: int
    description: str | None = None
    hsn_sac: str | None = None
    quantity: Decimal | None = None
    unit: str | None = None
    unit_price: Decimal | None = None
    discount: Decimal | None = None
    taxable_value: Decimal | None = None
    gst_rate: Decimal | None = None
    cgst: Decimal | None = None
    sgst: Decimal | None = None
    igst: Decimal | None = None
    cess: Decimal | None = None
    line_total: Decimal | None = None
    confidence: float = 1.0


class InvoiceData(BaseModel):
    vendor_name: str | None = None
    vendor_gstin: str | None = None
    buyer_name: str | None = None
    buyer_gstin: str | None = None
    invoice_number: str | None = None
    invoice_date: date | None = None
    po_number: str | None = None
    place_of_supply: str | None = None  # 2-digit GST state code
    items: list[LineItem] = Field(default_factory=list)
    subtotal: Decimal | None = None      # total taxable value
    total_cgst: Decimal | None = None
    total_sgst: Decimal | None = None
    total_igst: Decimal | None = None
    total_cess: Decimal | None = None
    round_off: Decimal | None = None
    grand_total: Decimal | None = None
    field_confidence: dict[str, float] = Field(default_factory=dict)


class Severity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class Finding(BaseModel):
    code: str
    severity: Severity
    category: Literal["validation", "duplicate", "reconciliation", "einvoice", "gstr2b", "itc"]
    message: str
    field: str | None = None
    line_no: int | None = None
    expected: str | None = None
    actual: str | None = None


class InvoiceStatus(str, Enum):
    PROCESSING = "PROCESSING"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    AUTO_APPROVED = "AUTO_APPROVED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"


class JobStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class ReconStatus(str, Enum):
    MATCHED = "MATCHED"
    PARTIAL = "PARTIAL"
    MISMATCH = "MISMATCH"
    NO_PO = "NO_PO"
    PO_NOT_FOUND = "PO_NOT_FOUND"
