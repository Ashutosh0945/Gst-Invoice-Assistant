"""Records security-relevant requests to access_events. Called from an HTTP middleware; it must never
break or slow down the request it observes, so every failure here is swallowed and logged."""
from __future__ import annotations

import hmac
import logging
import re
import time

from backend.config import get_settings

logger = logging.getLogger(__name__)
UUID = r"[0-9a-fA-F-]{32,36}"
RULES = [  # (method, path regex, action)
    ("GET", rf"^/api/v1/invoices/({UUID})$", "invoice.viewed"),
    ("POST", r"^/api/v1/invoices$", "invoice.uploaded"),
    ("POST", rf"^/api/v1/invoices/({UUID})/(approve|reject|correct|payment)$", "invoice.modified"),
    ("DELETE", rf"^/api/v1/invoices/({UUID})$", "invoice.deleted"),
    ("GET", r"^/api/v1/ai/feedback/export$", "data.downloaded"),
    ("POST", r"^/api/v1/gstr2b/import$", "gstr2b.imported"),
    ("DELETE", rf"^/api/v1/gstr2b/imports/({UUID})$", "gstr2b.deleted"),
    ("GET", r"^/api/v1/gstr2b/", "gstr2b.accessed"),
    ("POST", r"^/api/v1/ai/reports/(monthly|audit)$", "report.generated"),
    ("POST", r"^/api/v1/itc/reassess$", "itc.recalculated"),
]
_recent_ok: dict[str, float] = {}


def mask_ip(ip: str | None) -> str | None:
    if not ip:
        return None
    ip = ip.split(",")[0].strip()
    if "." in ip:
        p = ip.split(".")
        return f"{p[0]}.{p[1]}.x.x" if len(p) == 4 else "masked"
    return ":".join(ip.split(":")[:2]) + ":…" if ":" in ip else "masked"


def classify(method: str, path: str, status: int, api_key_header: str | None) -> tuple[str, str, str, str | None] | None:
    """Returns (kind, action, outcome, resource_id) or None if the request isn't security-relevant."""
    if not path.startswith("/api/"):
        return None
    if status in (401, 403):
        return "auth", "auth.failed", "denied", None
    for m, pat, action in RULES:
        if method == m and (mm := re.match(pat, path)):
            rid = mm.group(1) if mm.groups() and re.fullmatch(UUID, mm.group(1) or "") else None
            return "access", action, "success" if status < 400 else "failure", rid
    return None


def record(request, status: int) -> None:
    try:
        key = request.headers.get("x-api-key")
        settings = get_settings()
        valid_key = bool(key and settings.api_key and hmac.compare_digest(key, settings.api_key))
        ip = mask_ip(request.headers.get("x-forwarded-for") or (request.client.host if request.client else None))
        path = request.url.path
        c = classify(request.method, path, status, key)
        if c is None and valid_key:                     # successful API-key authentication, once per IP per 10 min
            if time.time() - _recent_ok.get(ip or "?", 0) < 600:
                return
            _recent_ok[ip or "?"] = time.time()
            c = ("auth", "auth.success", "success", None)
        if c is None:
            return
        kind, action, outcome, rid = c
        from backend.db.base import SessionLocal
        from backend.db.models import AccessEvent
        db = SessionLocal()
        try:
            db.add(AccessEvent(kind=kind, action=action, outcome=outcome,
                               actor="API key" if valid_key else ("Invalid API key" if key else "Anonymous (no login)"),
                               ip_masked=ip, method=request.method, path=re.sub(UUID, "{id}", path)[:200], resource_id=rid,
                               status_code=status, user_agent=(request.headers.get("user-agent") or "")[:120] or None))
            db.commit()
        finally:
            db.close()
    except Exception:  # noqa: BLE001 - auditing must never break the request
        logger.exception("Could not record access event")
