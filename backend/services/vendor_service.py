from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.models import Vendor
from backend.validation.gstin import state_code


def get_or_create_vendor(db: Session, gstin: str | None, name: str | None) -> Vendor | None:
    if not gstin and not name:
        return None
    vendor = None
    if gstin:
        vendor = db.execute(select(Vendor).where(Vendor.gstin == gstin)).scalars().first()
    if vendor is None and name:
        norm = name.strip().lower()
        vendor = db.execute(select(Vendor).where(Vendor.normalized_name == norm)).scalars().first()
    if vendor is not None:
        return vendor

    vendor = Vendor(
        gstin=gstin,
        name=name or "Unknown vendor",
        normalized_name=(name or "unknown vendor").strip().lower(),
        state_code=state_code(gstin),
    )
    db.add(vendor)
    db.flush()
    return vendor
