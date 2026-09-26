"""Make sure the database has every table and column the code expects.

Runs automatically when the API starts (including each Vercel cold start), so a
fresh database -- or one created by an older version of the app -- is brought up
to date without anyone having to run a script by hand. It only ever ADDS
missing tables/columns; it never drops or changes existing data.
"""
from __future__ import annotations

import logging
import threading

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from backend.db import models  # noqa: F401  (registers every model on Base.metadata)
from backend.db.base import Base


def _real_engine(engine) -> Engine:
    """backend.db.base.engine is a lazy proxy; SQLAlchemy's inspector needs the real Engine."""
    if isinstance(engine, Engine):
        return engine
    from backend.db.base import _get_engine
    return _get_engine()

logger = logging.getLogger(__name__)
_lock = threading.Lock()
_done_for: set[int] = set()


def _already_complete(engine: Engine) -> bool:
    """On PostgreSQL, check every expected table and column in a single round trip.
    (The full inspection below costs ~25 queries, which is slow when the database is far away.)"""
    if engine.dialect.name != "postgresql":
        return False
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT table_name, column_name FROM information_schema.columns WHERE table_schema = current_schema()"
        )).all()
    have = {(t, c) for t, c in rows}
    return all((t.name, c.name) in have for t in Base.metadata.sorted_tables for c in t.columns)


def ensure_schema(engine: Engine) -> list[str]:
    """Creates missing tables and adds missing columns. Returns what it added."""
    engine = _real_engine(engine)
    with _lock:
        if id(engine) in _done_for:
            return []
        if _already_complete(engine):          # the usual case: ONE quick query, then done
            _done_for.add(id(engine))
            return []
        Base.metadata.create_all(engine)
        insp = inspect(engine)
        added: list[str] = []
        with engine.begin() as conn:
            for table in Base.metadata.sorted_tables:
                existing = {c["name"] for c in insp.get_columns(table.name)}
                for col in table.columns:
                    if col.name not in existing:
                        ddl_type = col.type.compile(dialect=engine.dialect)
                        conn.execute(text(f"ALTER TABLE {table.name} ADD COLUMN {col.name} {ddl_type}"))
                        added.append(f"{table.name}.{col.name}")
        if added:
            logger.info("Database upgraded, added columns: %s", ", ".join(added))
        _done_for.add(id(engine))
        return added
