"""Create all tables. For production use with Postgres, prefer Alembic
migrations; this script is for quick local/dev bootstrap and for tests."""
from __future__ import annotations

from backend.db.base import Base, make_engine
from backend.db import models  # noqa: F401  (import registers models on Base.metadata)


def main() -> None:
    engine = make_engine()
    Base.metadata.create_all(engine)
    print(f"Created tables: {', '.join(Base.metadata.tables.keys())}")


if __name__ == "__main__":
    main()
