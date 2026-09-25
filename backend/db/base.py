from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker, Session
from sqlalchemy.pool import NullPool, StaticPool

from backend.config import get_settings


class Base(DeclarativeBase):
    pass


def make_engine():
    settings = get_settings()
    url = settings.database_url

    if url.startswith("sqlite") and ":memory:" in url:
        return create_engine(
            url, future=True,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

    if settings.serverless_db:
        return create_engine(url, future=True, poolclass=NullPool)

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
