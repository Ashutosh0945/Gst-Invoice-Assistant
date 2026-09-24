from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import NullPool, StaticPool

from backend.config import get_settings


class Base(DeclarativeBase):
    pass


def make_engine():
    settings = get_settings()
    url = settings.database_url

    if url.startswith("sqlite") and ":memory:" in url:
        # A single shared connection so every session sees the same in-memory
        # database -- SQLite's default behavior opens a fresh, empty DB per
        # connection otherwise (only relevant for tests; Postgres in prod
        # doesn't need this).
        return create_engine(
            url, future=True,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

    if settings.serverless_db:
        # On Vercel (or any serverless host) each invocation is a short-lived
        # process, and Supabase's pooled connection string already runs
        # PgBouncer in front of Postgres -- so SQLAlchemy should hand back
        # connections immediately rather than keeping its own idle pool
        # around between invocations (which would fight with PgBouncer and
        # can exhaust its pool under concurrent cold starts).
        return create_engine(url, future=True, poolclass=NullPool)

    return create_engine(url, pool_pre_ping=True, future=True)


engine = make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
