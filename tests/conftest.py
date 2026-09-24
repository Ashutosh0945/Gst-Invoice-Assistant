import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("LLM_ENABLED", "false")

import pytest

from backend.db.base import Base, SessionLocal, engine
from backend.db import models  # noqa: F401


@pytest.fixture()
def db():
    # Reuse the module-level engine/SessionLocal (already bound at import
    # time to DATABASE_URL) rather than constructing a second engine --
    # for sqlite ":memory:" a second engine would open an unrelated,
    # separately-empty database even with the same URL.
    Base.metadata.create_all(engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)
