"""Access control and data scoping for the business console API.

Who may call it:
  * a signed-in user whose role is "staff" (the console website's login), or
  * a server holding API_KEY in the X-API-Key header (the console website's
    server-side page rendering, scripts, integrations).
Nobody else — there is no anonymous access, even when API_KEY is unset.

What it can see: only the business register (invoices with owner_id IS NULL).
Personal-app users' bills are excluded from *every* console query by a
session-level rule (with_loader_criteria), so a new query can't leak them by
accident.
"""
from __future__ import annotations

import hmac

from fastapi import Cookie, Depends, Header, HTTPException, status
from sqlalchemy import event
from sqlalchemy.orm import Session, with_loader_criteria

from backend.config import get_settings
from backend.db.base import SessionLocal
from backend.db.models import Invoice, User


def get_console_db():
    db = SessionLocal()
    db.info["console_scope"] = True
    try:
        yield db
    finally:
        db.close()


@event.listens_for(Session, "do_orm_execute")
def _console_scope(state) -> None:
    if not state.session.info.get("console_scope"):
        return
    if state.is_column_load or state.is_relationship_load:
        return
    if state.is_select or state.is_update or state.is_delete:
        state.statement = state.statement.options(
            with_loader_criteria(Invoice, Invoice.owner_id.is_(None), include_aliases=True))


def console_principal(x_api_key: str | None = Header(default=None), session: str | None = Cookie(default=None),
                      db: Session = Depends(get_console_db)) -> dict:
    from backend.personal.auth import read_session

    key = get_settings().api_key
    if key and x_api_key and hmac.compare_digest(x_api_key, key):
        return {"kind": "api_key", "name": "server"}
    uid = read_session(session)
    user = db.get(User, uid) if uid else None
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Please sign in to the console.")
    if user.role != "staff":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This account doesn't have console access.")
    return {"kind": "staff", "id": str(user.id), "name": user.name, "email": user.email}


# Backwards-compatible name used by the console routers.
require_api_key = console_principal
