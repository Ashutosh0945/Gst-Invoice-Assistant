"""Create all tables (and add any columns newer versions introduced).

The API now does this by itself when it starts, so this script is optional --
handy to set up a database before the first deploy, or locally.
"""
from __future__ import annotations

from backend.db.base import Base, make_engine
from backend.db.schema import ensure_schema


def main() -> None:
    engine = make_engine()
    added = ensure_schema(engine)
    print(f"Tables ready: {', '.join(Base.metadata.tables.keys())}")
    if added:
        print(f"Added new columns: {', '.join(added)}")


if __name__ == "__main__":
    main()
