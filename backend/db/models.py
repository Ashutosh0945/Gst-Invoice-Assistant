"""Normalized schema.

vendors, purchase_orders / po_lines, invoices / invoice_lines, validation_findings,
reconciliation_results, processing_jobs, audit_logs. Money columns are NUMERIC, never FLOAT.
"""
from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean, Date, DateTime, Enum, ForeignKey, Index, Integer, Numeric,
    String, Text, UniqueConstraint, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.base import Base
from backend.db.types import GUID, JSONType


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(GUID(), primary_key=True, default=uuid.uuid4)


MONEY = Numeric(14, 2)
QTY = Numeric(14, 3)


class InvoiceStatus(str, enum.Enum):
    PROCESSING = "PROCESSING"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    AUTO_APPROVED = "AUTO_APPROVED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"


class JobStatus(str, enum.Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class ReconStatus(str, enum.Enum):
    MATCHED = "MATCHED"
    PARTIAL = "PARTIAL"
    MISMATCH = "MISMATCH"
    NO_PO = "NO_PO"
    PO_NOT_FOUND = "PO_NOT_FOUND"


class Severity(str, enum.Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class Vendor(Base):
    __tablename__ = "vendors"

    id: Mapped[uuid.UUID] = uuid_pk()
    gstin: Mapped[str | None] = mapped_column(String(15), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    normalized_name: Mapped[str] = mapped_column(String(255), index=True)
    state_code: Mapped[str | None] = mapped_column(String(2))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    purchase_orders: Mapped[list["PurchaseOrder"]] = relationship(back_populates="vendor")
    invoices: Mapped[list["Invoice"]] = relationship(back_populates="vendor")


class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"
    __table_args__ = (UniqueConstraint("po_number", "vendor_id", name="uq_po_vendor"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    po_number: Mapped[str] = mapped_column(String(64), index=True)
    vendor_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), ForeignKey("vendors.id"))
    po_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="OPEN")  # OPEN/CLOSED/CANCELLED
    total_amount: Mapped[Decimal | None] = mapped_column(MONEY)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    vendor: Mapped["Vendor | None"] = relationship(back_populates="purchase_orders")
    lines: Mapped[list["POLine"]] = relationship(back_populates="po", cascade="all, delete-orphan")


class POLine(Base):
    __tablename__ = "po_lines"

    id: Mapped[uuid.UUID] = uuid_pk()
    po_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("purchase_orders.id", ondelete="CASCADE"))
    line_no: Mapped[int] = mapped_column(Integer)
    description: Mapped[str | None] = mapped_column(Text)
    hsn_sac: Mapped[str | None] = mapped_column(String(8))
    quantity: Mapped[Decimal | None] = mapped_column(QTY)
    unit_price: Mapped[Decimal | None] = mapped_column(MONEY)
    quantity_invoiced: Mapped[Decimal] = mapped_column(QTY, default=0)  # running total, for partial matches

    po: Mapped["PurchaseOrder"] = relationship(back_populates="lines")


class Invoice(Base):
    __tablename__ = "invoices"
    __table_args__ = (
        Index("ix_invoice_dupe_key", "vendor_id", "invoice_number", "invoice_date"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    job_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), ForeignKey("processing_jobs.id"))
    vendor_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), ForeignKey("vendors.id"))
    po_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), ForeignKey("purchase_orders.id"))

    source_filename: Mapped[str] = mapped_column(String(500))
    document_hash: Mapped[str] = mapped_column(String(64), index=True)  # sha256 of raw bytes

    vendor_name_raw: Mapped[str | None] = mapped_column(String(255))
    vendor_gstin_raw: Mapped[str | None] = mapped_column(String(15))
    buyer_gstin_raw: Mapped[str | None] = mapped_column(String(15))
    invoice_number: Mapped[str | None] = mapped_column(String(64), index=True)
    invoice_date: Mapped[date | None] = mapped_column(Date)
    po_number_raw: Mapped[str | None] = mapped_column(String(64))
    place_of_supply: Mapped[str | None] = mapped_column(String(2))

    subtotal: Mapped[Decimal | None] = mapped_column(MONEY)
    total_cgst: Mapped[Decimal | None] = mapped_column(MONEY)
    total_sgst: Mapped[Decimal | None] = mapped_column(MONEY)
    total_igst: Mapped[Decimal | None] = mapped_column(MONEY)
    total_cess: Mapped[Decimal | None] = mapped_column(MONEY)
    round_off: Mapped[Decimal | None] = mapped_column(MONEY)
    grand_total: Mapped[Decimal | None] = mapped_column(MONEY)

    status: Mapped[str] = mapped_column(String(20), default=InvoiceStatus.PROCESSING.value, index=True)
    confidence_score: Mapped[float | None] = mapped_column(Numeric(5, 4))
    extraction_confidence: Mapped[dict | None] = mapped_column(JSONType)  # per-field confidences
    llm_explanation: Mapped[str | None] = mapped_column(Text)

    reviewed_by: Mapped[str | None] = mapped_column(String(255))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_notes: Mapped[str | None] = mapped_column(Text)

    # --- e-invoice (signed QR) ---
    irn: Mapped[str | None] = mapped_column(String(64), index=True)
    einvoice_status: Mapped[str | None] = mapped_column(String(24), index=True)  # see backend/einvoice/verify.py
    einvoice_data: Mapped[dict | None] = mapped_column(JSONType)                  # decoded QR payload

    # --- GSTR-2B / ITC ---
    gstr2b_status: Mapped[str | None] = mapped_column(String(24), index=True)     # IN_2B / MISSING_IN_2B / None
    gstr2b_record_id: Mapped[uuid.UUID | None] = mapped_column(GUID())  # soft link, avoids an FK cycle
    payment_date: Mapped[date | None] = mapped_column(Date)                       # Rule 37 (180-day payment)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    vendor: Mapped["Vendor | None"] = relationship(back_populates="invoices")
    items: Mapped[list["InvoiceLine"]] = relationship(back_populates="invoice", cascade="all, delete-orphan")
    findings: Mapped[list["ValidationFinding"]] = relationship(back_populates="invoice", cascade="all, delete-orphan")
    reconciliation: Mapped[list["ReconciliationResult"]] = relationship(back_populates="invoice", cascade="all, delete-orphan")
    audit_logs: Mapped[list["AuditLog"]] = relationship(back_populates="invoice", cascade="all, delete-orphan")
    itc: Mapped["ItcAssessment | None"] = relationship(back_populates="invoice", cascade="all, delete-orphan", uselist=False)


class InvoiceLine(Base):
    __tablename__ = "invoice_lines"

    id: Mapped[uuid.UUID] = uuid_pk()
    invoice_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("invoices.id", ondelete="CASCADE"))
    line_no: Mapped[int] = mapped_column(Integer)
    description: Mapped[str | None] = mapped_column(Text)
    hsn_sac: Mapped[str | None] = mapped_column(String(8), index=True)
    quantity: Mapped[Decimal | None] = mapped_column(QTY)
    unit: Mapped[str | None] = mapped_column(String(20))
    unit_price: Mapped[Decimal | None] = mapped_column(MONEY)
    discount: Mapped[Decimal | None] = mapped_column(MONEY)
    taxable_value: Mapped[Decimal | None] = mapped_column(MONEY)
    gst_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    cgst: Mapped[Decimal | None] = mapped_column(MONEY)
    sgst: Mapped[Decimal | None] = mapped_column(MONEY)
    igst: Mapped[Decimal | None] = mapped_column(MONEY)
    cess: Mapped[Decimal | None] = mapped_column(MONEY)
    line_total: Mapped[Decimal | None] = mapped_column(MONEY)
    confidence: Mapped[float] = mapped_column(Numeric(5, 4), default=1.0)

    invoice: Mapped["Invoice"] = relationship(back_populates="items")


class ValidationFinding(Base):
    __tablename__ = "validation_findings"

    id: Mapped[uuid.UUID] = uuid_pk()
    invoice_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("invoices.id", ondelete="CASCADE"))
    code: Mapped[str] = mapped_column(String(64))
    category: Mapped[str] = mapped_column(String(20))  # validation/duplicate/reconciliation
    severity: Mapped[str] = mapped_column(String(10))
    message: Mapped[str] = mapped_column(Text)
    field: Mapped[str | None] = mapped_column(String(64))
    line_no: Mapped[int | None] = mapped_column(Integer)
    expected: Mapped[str | None] = mapped_column(String(255))
    actual: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    invoice: Mapped["Invoice"] = relationship(back_populates="findings")


class ReconciliationResult(Base):
    __tablename__ = "reconciliation_results"

    id: Mapped[uuid.UUID] = uuid_pk()
    invoice_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("invoices.id", ondelete="CASCADE"))
    po_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), ForeignKey("purchase_orders.id"))
    invoice_line_no: Mapped[int | None] = mapped_column(Integer)
    po_line_no: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20))
    qty_invoiced: Mapped[Decimal | None] = mapped_column(QTY)
    qty_po: Mapped[Decimal | None] = mapped_column(QTY)
    price_invoiced: Mapped[Decimal | None] = mapped_column(MONEY)
    price_po: Mapped[Decimal | None] = mapped_column(MONEY)
    variance_amount: Mapped[Decimal | None] = mapped_column(MONEY)
    variance_pct: Mapped[Decimal | None] = mapped_column(Numeric(7, 3))
    notes: Mapped[str | None] = mapped_column(Text)

    invoice: Mapped["Invoice"] = relationship(back_populates="reconciliation")


class ProcessingJob(Base):
    __tablename__ = "processing_jobs"

    id: Mapped[uuid.UUID] = uuid_pk()
    source_filename: Mapped[str] = mapped_column(String(500))
    stage: Mapped[str] = mapped_column(String(50), default="INGESTED")
    status: Mapped[str] = mapped_column(String(20), default=JobStatus.PENDING.value, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = uuid_pk()
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), ForeignKey("invoices.id", ondelete="CASCADE"))
    actor: Mapped[str] = mapped_column(String(255))          # "system" or reviewer name/id
    action: Mapped[str] = mapped_column(String(64))          # e.g. INGESTED, EXTRACTED, VALIDATED, APPROVED, REJECTED, CORRECTED
    details: Mapped[dict | None] = mapped_column(JSONType)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    invoice: Mapped["Invoice | None"] = relationship(back_populates="audit_logs")


class Gstr2bImport(Base):
    """One uploaded GSTR-2B statement (one return period). Re-importing a period replaces it."""
    __tablename__ = "gstr2b_imports"

    id: Mapped[uuid.UUID] = uuid_pk()
    return_period: Mapped[str] = mapped_column(String(6), index=True)   # MMYYYY, as on the portal
    gstin: Mapped[str | None] = mapped_column(String(15))
    source_filename: Mapped[str] = mapped_column(String(500))
    generated_on: Mapped[str | None] = mapped_column(String(32))
    record_count: Mapped[int] = mapped_column(Integer, default=0)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    records: Mapped[list["Gstr2bRecord"]] = relationship(back_populates="import_", cascade="all, delete-orphan")


class Gstr2bRecord(Base):
    """One supplier invoice as the government sees it (GSTR-2B B2B section)."""
    __tablename__ = "gstr2b_records"

    id: Mapped[uuid.UUID] = uuid_pk()
    import_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("gstr2b_imports.id", ondelete="CASCADE"))
    supplier_gstin: Mapped[str] = mapped_column(String(15), index=True)
    supplier_name: Mapped[str | None] = mapped_column(String(255))
    invoice_number: Mapped[str] = mapped_column(String(64))
    invoice_date: Mapped[date | None] = mapped_column(Date)
    invoice_value: Mapped[Decimal | None] = mapped_column(MONEY)
    taxable_value: Mapped[Decimal | None] = mapped_column(MONEY)
    igst: Mapped[Decimal | None] = mapped_column(MONEY)
    cgst: Mapped[Decimal | None] = mapped_column(MONEY)
    sgst: Mapped[Decimal | None] = mapped_column(MONEY)
    cess: Mapped[Decimal | None] = mapped_column(MONEY)
    place_of_supply: Mapped[str | None] = mapped_column(String(2))
    reverse_charge: Mapped[bool] = mapped_column(Boolean, default=False)
    itc_available: Mapped[bool] = mapped_column(Boolean, default=True)
    itc_unavailable_reason: Mapped[str | None] = mapped_column(String(255))
    supplier_filed_on: Mapped[str | None] = mapped_column(String(16))
    irn: Mapped[str | None] = mapped_column(String(64))

    match_status: Mapped[str] = mapped_column(String(24), index=True, default="MISSING_IN_BOOKS")
    matched_invoice_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), ForeignKey("invoices.id", ondelete="SET NULL"))
    match_score: Mapped[float | None] = mapped_column(Numeric(5, 4))
    match_notes: Mapped[str | None] = mapped_column(Text)

    import_: Mapped["Gstr2bImport"] = relationship(back_populates="records")


class ItcAssessment(Base):
    """Input-tax-credit decision for one invoice. Recomputed whenever its inputs change."""
    __tablename__ = "itc_assessments"

    id: Mapped[uuid.UUID] = uuid_pk()
    invoice_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("invoices.id", ondelete="CASCADE"), unique=True)
    status: Mapped[str] = mapped_column(String(24), index=True)
    total_itc: Mapped[Decimal] = mapped_column(MONEY, default=0)
    eligible_itc: Mapped[Decimal] = mapped_column(MONEY, default=0)
    blocked_itc: Mapped[Decimal] = mapped_column(MONEY, default=0)
    review_itc: Mapped[Decimal] = mapped_column(MONEY, default=0)
    at_risk_itc: Mapped[Decimal] = mapped_column(MONEY, default=0)
    claim_deadline: Mapped[date | None] = mapped_column(Date)
    payment_due_by: Mapped[date | None] = mapped_column(Date)
    reasons: Mapped[list | None] = mapped_column(JSONType)
    assessed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    invoice: Mapped["Invoice"] = relationship(back_populates="itc")
