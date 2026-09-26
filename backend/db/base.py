from __future__ import annotations

import re
from urllib.parse import quote, unquote

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError
from sqlalchemy.orm import DeclarativeBase, sessionmaker, Session
from sqlalchemy.pool import NullPool, StaticPool

from backend.config import get_settings


class Base(DeclarativeBase):
    pass


class DatabaseConfigError(RuntimeError):
    """DATABASE_URL is missing or can't be understood. The message says what to fix."""


_PLACEHOLDERS = ("[YOUR-PASSWORD]", "[YOUR_PASSWORD]", "<PASSWORD>", "<password>", "YOUR-PASSWORD", "[password]")


def mask_url(url: str) -> str:
    """postgresql://user:secret@host/db -> postgresql://user:****@host/db (safe to show/log)."""
    m = re.match(r"^([a-z0-9+]+://[^:/@]+:)(.*)(@[^@]*)$", url)
    return f"{m.group(1)}****{m.group(3)}" if m else url[:40]


def clean_database_url(raw: str | None) -> str:
    """Accepts the connection string the way people actually paste it into Vercel and
    returns something SQLAlchemy understands, or raises DatabaseConfigError saying why not.

    Fixes silently: surrounding spaces/newlines, surrounding quotes, a pasted
    `DATABASE_URL=` prefix, Neon's `psql '...'` command, `postgres://` scheme,
    missing driver name, and special characters (@ # / ? etc.) in the password.
    """
    url = (raw or "").strip()
    for _ in range(3):
        url = re.sub(r"^(export\s+)?DATABASE_URL\s*=\s*", "", url).strip()
        url = re.sub(r"^psql\s+", "", url).strip()
        if len(url) >= 2 and url[0] == url[-1] and url[0] in "'\"`":
            url = url[1:-1].strip()
    if not url:
        raise DatabaseConfigError(
            "DATABASE_URL is empty. In Vercel -> Settings -> Environment Variables, add DATABASE_URL with your "
            "database connection string (it starts with postgresql://), then redeploy.")
    if url.startswith("sqlite"):
        return url
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg2://" + url[len("postgresql://"):]
    if not url.startswith("postgresql+"):
        raise DatabaseConfigError(
            f"DATABASE_URL doesn't look like a database address (it starts with '{url[:12]}...'). "
            "It must start with postgresql:// — copy only the connection string from Neon or Supabase.")
    if any(p in url for p in _PLACEHOLDERS):
        raise DatabaseConfigError(
            "DATABASE_URL still contains the placeholder [YOUR-PASSWORD]. Replace it with your real database "
            "password (Supabase -> Project Settings -> Database), then redeploy.")
    # Percent-encode the password if it contains characters that would break the address.
    scheme, rest = url.split("://", 1)
    at = rest.rfind("@")
    if at > 0:
        userinfo, hostpart = rest[:at], rest[at + 1:]
        user, sep, pw = userinfo.partition(":")
        if sep and quote(unquote(pw), safe="") != pw:
            url = f"{scheme}://{user}:{quote(unquote(pw), safe='')}@{hostpart}"
    try:
        make_url(url)
    except ArgumentError as exc:
        raise DatabaseConfigError(
            f"DATABASE_URL can't be read as a database address ({mask_url(url)}). Copy the connection string "
            "again from Neon/Supabase and paste only that — no quotes, no 'psql', no spaces.") from exc
    return url


def make_engine():
    try:
        return _make_engine()
    except DatabaseConfigError:
        raise
    except (ArgumentError, ValueError) as exc:
        raise DatabaseConfigError(
            f"DATABASE_URL couldn't be used ({type(exc).__name__}: {str(exc)[:120]}). Check the host, port and "
            "database name — copy the connection string again from Neon/Supabase.") from exc


def _make_engine():
    settings = get_settings()
    url = clean_database_url(settings.database_url)

    if url.startswith("sqlite") and ":memory:" in url:
        return create_engine(
            url, future=True,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

    if settings.serverless_db:
        # Vercel's Fluid compute reuses a function instance for many requests, so keep a
        # couple of connections open between them instead of reconnecting every time
        # (a new connection costs several network round trips). pre_ping replaces any
        # connection the database or its pooler has closed; recycle keeps them fresh.
        return create_engine(url, future=True, pool_size=2, max_overflow=3,
                             pool_pre_ping=True, pool_recycle=240, pool_timeout=10)

    return create_engine(url, pool_pre_ping=True, future=True)


# -------------------------------------------------------------------
# Lazy engine + session factory
# The engine is created on first use, not at import time.
# This prevents a cold-start crash on Vercel when DATABASE_URL has
# not been resolved yet (or is absent), which used to blow up the
# entire Python function before any request was served.
# -------------------------------------------------------------------
_engine = None
_SessionLocal = None


def _get_engine():
    global _engine, _SessionLocal
    if _engine is None:
        _engine = make_engine()
        _SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False, future=True)
    return _engine


def get_db():
    _get_engine()  # ensure initialised
    db: Session = _SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Keep these for code that does `from backend.db.base import engine`
# They are resolved lazily on first access via the module-level properties trick.
class _LazyEngine:
    """Proxy that forwards attribute access to the real engine, initialising it on first use."""
    def __getattr__(self, name):
        return getattr(_get_engine(), name)

    def __repr__(self):
        return repr(_get_engine())


engine = _LazyEngine()


class _LazySessionLocal:
    """Proxy for SessionLocal — forwards calls to the real sessionmaker, init on first use."""
    def __call__(self, *args, **kwargs):
        _get_engine()
        return _SessionLocal(*args, **kwargs)

    def __getattr__(self, name):
        _get_engine()
        return getattr(_SessionLocal, name)


SessionLocal = _LazySessionLocal()
