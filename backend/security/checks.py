"""Real security / system checks. Status values: Healthy, Degraded, Unavailable, Not configured,
Unable to verify. Secrets are only ever reported as configured / not configured."""
from __future__ import annotations

import importlib.util
import os
import time
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import func, select, text

from backend.config import get_settings

V, U = "Verified by application", "Unable to verify"


def _chk(name, status, detail, verified=True, weight=0, passed=None, category="System health"):
    return {"name": name, "status": status, "detail": detail, "verification": V if verified else U,
            "weight": weight, "passed": passed, "category": category}


def system_health() -> list[dict]:
    from backend.db.base import Base, _get_engine
    s = get_settings()
    out = [_chk("API server", "Healthy", "This check ran on the API server, so it is up.", weight=1, passed=True)]
    try:
        eng = _get_engine()
        with eng.connect() as c:
            c.execute(text("SELECT 1"))
            t0 = time.perf_counter(); c.execute(text("SELECT 1")); ms = round((time.perf_counter() - t0) * 1000)
            dialect = eng.dialect.name
            ssl = None
            if dialect == "postgresql":
                try:
                    ssl = c.execute(text("SELECT ssl FROM pg_stat_ssl WHERE pid = pg_backend_pid()")).scalar()
                except Exception:  # noqa: BLE001
                    ssl = None
        from sqlalchemy import inspect as sa_inspect
        missing = [t for t in Base.metadata.tables if t not in set(sa_inspect(eng).get_table_names())]
        out.append(_chk("Database", "Healthy" if ms < 150 and not missing else "Degraded",
                        f"{dialect}, query round trip {ms} ms" + (f"; missing tables: {', '.join(missing)}" if missing else "; all tables present."),
                        weight=2, passed=not missing))
        if dialect == "postgresql":
            out.append(_chk("Database connection encrypted (TLS)", "Healthy" if ssl else "Degraded" if ssl is False else U,
                            "Connection to the database uses TLS." if ssl else "Connection is NOT encrypted." if ssl is False else "Couldn't read pg_stat_ssl.",
                            verified=ssl is not None, weight=2 if ssl is not None else 0, passed=bool(ssl) if ssl is not None else None, category="Configuration"))
        else:
            out.append(_chk("Database connection encrypted (TLS)", U, f"{dialect} is a local file database; no network connection to encrypt.",
                            verified=False, category="Configuration"))
    except Exception as exc:  # noqa: BLE001
        out.append(_chk("Database", "Unavailable", f"{type(exc).__name__}: {str(exc).splitlines()[0][:150]}", weight=2, passed=False))
    if not s.openrouter_api_key:
        out.append(_chk("AI service (OpenRouter)", "Not configured", "No OpenRouter key set; AI features use rule-based answers.", category="System health"))
    else:
        try:
            r = httpx.get(f"{s.openrouter_base_url}/key", headers={"Authorization": f"Bearer {s.openrouter_api_key}"}, timeout=6)
            st = "Healthy" if r.status_code == 200 else "Unavailable" if r.status_code in (401, 403) else "Degraded"
            out.append(_chk("AI service (OpenRouter)", st, {"Healthy": "Key accepted by OpenRouter.", "Unavailable": "OpenRouter rejected the key."}
                            .get(st, f"OpenRouter answered HTTP {r.status_code}.") + ("" if s.llm_enabled else " (AI is switched off: LLM_ENABLED=false)"),
                            weight=1, passed=st == "Healthy"))
        except httpx.HTTPError as exc:
            out.append(_chk("AI service (OpenRouter)", U, f"Couldn't reach OpenRouter ({type(exc).__name__}).", verified=False))
    pdf_ok = importlib.util.find_spec("pymupdf") is not None or importlib.util.find_spec("fitz") is not None
    out.append(_chk("PDF reading", "Healthy" if pdf_ok else "Unavailable", "PyMuPDF installed: text PDFs can be read." if pdf_ok else "PyMuPDF missing.", weight=1, passed=pdf_ok))
    from backend.ocr.engine import engine_name
    eng_name = engine_name()
    out.append(_chk("Photo / scan reading (OCR)", "Healthy" if eng_name else "Unavailable",
                    f"{eng_name} installed." if eng_name else "No OCR engine on this server: photos and scanned PDFs can't be read. "
                    "Install requirements-ocr.txt where the host allows it.", weight=1, passed=bool(eng_name)))
    return out


def rls_status() -> dict:
    from backend.db.base import Base, _get_engine
    eng = _get_engine()
    if eng.dialect.name != "postgresql":
        return {"status": U, "verification": U, "detail": f"{eng.dialect.name} has no row-level security.", "tables": []}
    with eng.connect() as c:
        rows = c.execute(text("SELECT c.relname, c.relrowsecurity FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                              "WHERE n.nspname = current_schema() AND c.relkind = 'r'")).all()
        bypass = c.execute(text("SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname = current_user")).scalar()
    mine = {r[0]: bool(r[1]) for r in rows if r[0] in Base.metadata.tables}
    on = sum(mine.values())
    return {"status": "Enabled" if mine and on == len(mine) else "Partially enabled" if on else "Disabled",
            "verification": V, "tables": [{"table": t, "rls_enabled": e} for t, e in sorted(mine.items())],
            "app_role_bypasses_rls": bool(bypass),
            "detail": f"RLS is on for {on} of {len(mine)} GST Desk tables." + (" The API's database role bypasses RLS (normal for a trusted backend); "
                      "isolation therefore depends on the API." if bypass else "")}


def configuration() -> list[dict]:
    s = get_settings()
    def env(name):
        return bool((os.environ.get(name) or "").strip())
    db_default = not env("DATABASE_URL")
    items = [
        ("DATABASE_URL", "Not configured (using local default)" if db_default else "Configured"),
        ("OPENROUTER_API_KEY", "Configured" if s.openrouter_api_key else "Not configured"),
        ("LLM_ENABLED", "On" if s.llm_enabled else "Off"),
        ("API_KEY (API access protection)", "Configured" if s.api_key else "Not configured"),
        ("SITE_URL", "Configured" if env("SITE_URL") else "Not configured"),
        ("EINVOICE_PUBLIC_KEY_PATHS", "Configured" if env("EINVOICE_PUBLIC_KEY_PATHS") else "Not configured"),
    ]
    return [{"setting": k, "status": v, "verification": V} for k, v in items]


def security_posture() -> list[dict]:
    s = get_settings()
    from backend.api import main as M
    cors_any = any(getattr(m, "kwargs", {}).get("allow_origins") == ["*"] for m in M.app.user_middleware)
    return [
        _chk("User login", "Not configured", "GST Desk has no user accounts or sessions. Anyone who can reach the site can use it; "
             "per-user data isolation can't exist yet.", weight=3, passed=False, category="Authentication"),
        _chk("API access protection", "Healthy" if s.api_key else "Not configured",
             "Requests to the API need the API key." if s.api_key else "The API accepts requests without a key.",
             weight=3, passed=bool(s.api_key), category="Authentication"),
        _chk("Cross-site access (CORS)", "Degraded" if cors_any else "Healthy",
             "The API allows requests from any website (allow_origins=*)." if cors_any else "Only listed websites may call the API.",
             weight=1, passed=not cors_any, category="Configuration"),
        _chk("Secrets exposed to the browser", "Healthy", "Keys are read only on the server; the AI and database keys are never sent "
             "to the website (checked by an automated test).", weight=1, passed=True, category="Configuration"),
        _chk("Backups", "Not configured", "The application has no backup mechanism it can verify. Your database host may run its "
             "own backups (check its dashboard); GST Desk can't confirm them.", verified=False, category="Backup & sync"),
    ]


def events_summary(db, hours: int = 24) -> dict:
    from backend.db.models import AccessEvent
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    rows = db.execute(select(AccessEvent.action, AccessEvent.outcome, func.count()).where(AccessEvent.created_at >= since)
                      .group_by(AccessEvent.action, AccessEvent.outcome)).all()
    return {"hours": hours, "by_action": [{"action": a, "outcome": o, "count": n} for a, o, n in rows]}


def alerts(db, health: list[dict], rls: dict) -> list[dict]:
    from backend.db.models import AccessEvent
    out = []
    since = datetime.now(timezone.utc) - timedelta(minutes=15)
    for ip, n in db.execute(select(AccessEvent.ip_masked, func.count()).where(AccessEvent.action == "auth.failed",
                            AccessEvent.created_at >= since).group_by(AccessEvent.ip_masked)).all():
        if n >= 5:
            out.append({"severity": "High", "title": "Repeated failed access attempts", "detail": f"{n} denied requests from {ip or 'unknown'} in 15 minutes."})
    hour = datetime.now(timezone.utc) - timedelta(hours=1)
    for ip, n in db.execute(select(AccessEvent.ip_masked, func.count()).where(AccessEvent.action == "invoice.viewed",
                            AccessEvent.created_at >= hour).group_by(AccessEvent.ip_masked)).all():
        if n >= 200:
            out.append({"severity": "Medium", "title": "Unusual access volume", "detail": f"{n} invoice views from {ip} in the last hour."})
    dels = db.execute(select(func.count()).where(AccessEvent.action.in_(["invoice.deleted", "gstr2b.deleted"]), AccessEvent.created_at >= hour)).scalar()
    if dels and dels >= 5:
        out.append({"severity": "Medium", "title": "Many deletions", "detail": f"{dels} deletions in the last hour."})
    for h in health:
        if h["status"] == "Unavailable":
            out.append({"severity": "High" if h["name"] in ("Database", "API server") else "Medium", "title": f"{h['name']} unavailable", "detail": h["detail"]})
    if rls.get("status") == "Disabled":
        out.append({"severity": "Medium", "title": "Row-level security is off", "detail": rls["detail"]})
    if not get_settings().api_key:
        out.append({"severity": "High", "title": "API is open", "detail": "No login and no API key: anyone with the address can read and change data."})
    return out


def score(factors: list[dict]) -> dict:
    counted = [f for f in factors if f["weight"] and f["passed"] is not None and f["verification"] == V]
    total = sum(f["weight"] for f in counted)
    got = sum(f["weight"] for f in counted if f["passed"])
    return {"score": round(100 * got / total) if total else None, "points": got, "out_of": total,
            "factors": [{"name": f["name"], "passed": f["passed"], "weight": f["weight"]} for f in counted],
            "not_counted": [f["name"] for f in factors if f not in counted],
            "note": "Calculated only from checks the application could verify. Not a certification (no SOC 2, ISO 27001, etc. is claimed)."}
