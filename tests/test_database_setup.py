"""The API must prepare its own database (Vercel never runs scripts/init_db.py) and must
explain database problems in plain words instead of a bare 'Internal Server Error'."""
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.pool import StaticPool

from backend.db.base import Base
from backend.db.schema import ensure_schema


def _engine():
    return create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)


def test_creates_all_tables_on_an_empty_database():
    eng = _engine()
    ensure_schema(eng)
    assert set(Base.metadata.tables) <= set(inspect(eng).get_table_names())


def test_adds_columns_missing_from_an_older_database():
    eng = _engine()
    with eng.begin() as c:   # an "old" invoices table with only a few columns
        c.execute(text("CREATE TABLE invoices (id CHAR(32) PRIMARY KEY, source_filename VARCHAR(500))"))
    added = ensure_schema(eng)
    cols = {c["name"] for c in inspect(eng).get_columns("invoices")}
    assert "irn" in cols and "invoices.irn" in added
    assert ensure_schema(eng) == []          # second call is a no-op


def test_database_errors_are_explained(monkeypatch):
    from fastapi.testclient import TestClient
    from sqlalchemy.exc import OperationalError

    from backend.api.main import app

    @app.get("/api/v1/__boom")
    def boom():
        raise OperationalError("SELECT 1", {}, Exception("connection refused"))

    r = TestClient(app, raise_server_exceptions=False).get("/api/v1/__boom")
    assert r.status_code == 500 and "DATABASE_URL" in r.json()["detail"]


import pytest

from backend.db.base import DatabaseConfigError, clean_database_url

GOOD = "postgresql://neondb_owner:abc123@ep-cool-1.aws.neon.tech/neondb?sslmode=require"
EXPECTED = "postgresql+psycopg2://neondb_owner:abc123@ep-cool-1.aws.neon.tech/neondb?sslmode=require"


@pytest.mark.parametrize("pasted", [
    GOOD, f"psql '{GOOD}'", f'"{GOOD}"', f"'{GOOD}'", f"DATABASE_URL={GOOD}", f"  {GOOD}\n",
    GOOD.replace("postgresql://", "postgres://"),
])
def test_common_paste_mistakes_are_cleaned(pasted):
    assert clean_database_url(pasted) == EXPECTED


def test_special_characters_in_password_are_encoded():
    url = clean_database_url("postgresql://u:p@ss#1@db.host.com:5432/postgres")
    assert url == "postgresql+psycopg2://u:p%40ss%231@db.host.com:5432/postgres"


@pytest.mark.parametrize("bad, words", [
    ("", "empty"),
    ("postgresql://postgres:[YOUR-PASSWORD]@db.x.supabase.co:5432/postgres", "placeholder"),
    ("https://supabase.com/dashboard/project/abc", "postgresql://"),
])
def test_unusable_values_explain_themselves(bad, words):
    with pytest.raises(DatabaseConfigError, match=words):
        clean_database_url(bad)
