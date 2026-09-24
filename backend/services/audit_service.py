from __future__ import annotations

from sqlalchemy.orm import Session

from backend.db.models import AuditLog


def log_action(db: Session, invoice_id, actor: str, action: str, details: dict | None = None) -> None:
    db.add(AuditLog(invoice_id=invoice_id, actor=actor, action=action, details=details or {}))
