"""Create all tables, and add any columns that newer versions of the app introduced.

Safe to run on every start (the Render container does): existing tables and data are
left alone; only missing tables and missing columns are added.
"""
from __future__ import annotations

from sqlalchemy import inspect, text

from backend.db import models  # noqa: F401  (import registers models on Base.metadata)
from backend.db.base import Base, make_engine


def main() -> None:
    engine = make_engine()
    Base.metadata.create_all(engine)
    insp = inspect(engine)
    added = []
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            existing = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in existing:
                    continue
                ddl_type = col.type.compile(dialect=engine.dialect)
                conn.execute(text(f'ALTER TABLE {table.name} ADD COLUMN {col.name} {ddl_type}'))
                added.append(f"{table.name}.{col.name}")
    print(f"Tables ready: {', '.join(Base.metadata.tables.keys())}")
    if added:
        print(f"Added new columns: {', '.join(added)}")


if __name__ == "__main__":
    main()
