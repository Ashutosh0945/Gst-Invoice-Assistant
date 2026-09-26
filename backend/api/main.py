from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import OperationalError, ProgrammingError, SQLAlchemyError

from backend.db.base import DatabaseConfigError

from backend.api.routes import router
from backend.api.routes_compliance import router as compliance_router
from backend.logging_conf import setup_logging

setup_logging()
logger = logging.getLogger("backend.api")

# Shown by /health so you can confirm which version is live after a deploy.
APP_VERSION = "0.2.2 (database-url-fix)"


def _prepare_database() -> None:
    """Create any missing tables/columns. Never blocks startup: if the database is
    unreachable, requests will explain that clearly instead (see the handler below)."""
    from backend.db.base import engine
    from backend.db.schema import ensure_schema

    try:
        ensure_schema(engine)
    except Exception:  # noqa: BLE001
        logger.exception("Could not prepare the database schema at startup")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    _prepare_database()
    yield


app = FastAPI(
    title="GST Invoice Processing & Accounting Assistant",
    version="0.2.1",
    description="AI + data-engineering pipeline for Indian GST invoice automation.",
    lifespan=lifespan,
)


@app.middleware("http")
async def _ensure_schema_first(request: Request, call_next):
    # Serverless hosts don't always run the startup hook before the first request;
    # this makes sure the schema check has happened (it's a no-op after the first time).
    if request.url.path.startswith("/api/"):
        _prepare_database()
    return await call_next(request)


@app.exception_handler(DatabaseConfigError)
async def _database_config_error(request: Request, exc: DatabaseConfigError):
    logger.error("Database configuration problem: %s", exc)
    return JSONResponse(status_code=500, content={"detail": str(exc)})


@app.exception_handler(SQLAlchemyError)
async def _database_error(request: Request, exc: SQLAlchemyError):
    logger.exception("Database error on %s %s", request.method, request.url.path)
    if isinstance(exc, OperationalError):
        msg = ("Couldn't connect to the database. Check that DATABASE_URL is set correctly in your "
               "Vercel project settings (Settings -> Environment Variables), then redeploy.")
    elif isinstance(exc, ProgrammingError):
        msg = ("The database isn't set up the way this version of the app expects "
               f"({str(getattr(exc, 'orig', exc)).splitlines()[0][:160]}). Redeploy so the app can update it, "
               "or run scripts/init_db.py against this database.")
    else:
        msg = (f"A database error stopped this request ({type(exc).__name__}). "
               "Open /api/v1/health/database on this site for details.")
    return JSONResponse(status_code=500, content={"detail": msg})


@app.exception_handler(Exception)
async def _unexpected_error(request: Request, exc: Exception):
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={
        "detail": f"Processing failed: {type(exc).__name__}: {str(exc)[:200]}. See the server logs for details."})

# Same-origin in production (Next.js and this API share one Vercel deployment,
# proxied via vercel.json rewrites). Permissive CORS here only helps local
# dev if the frontend ever calls the API on a different port directly.
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

app.include_router(router, prefix="/api/v1")
app.include_router(compliance_router, prefix="/api/v1")


@app.get("/health")
@app.get("/api/v1/health")
def health():
    import os
    return {"status": "ok", "version": APP_VERSION,
            "deployed_commit": (os.environ.get("VERCEL_GIT_COMMIT_SHA") or "local")[:7],
            "database_url_set": bool((os.environ.get("DATABASE_URL") or "").strip())}


@app.get("/api/v1/health/database")
def health_database():
    """Open this in a browser to check the deployment's database in one glance,
    including how far away it is from where the API runs."""
    import os
    import time

    from backend.db.base import Base, _get_engine

    try:
        engine = _get_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            t0 = time.perf_counter()
            conn.execute(text("SELECT 1"))
            round_trip_ms = round((time.perf_counter() - t0) * 1000)
        from sqlalchemy import inspect as sa_inspect

        present = set(sa_inspect(engine).get_table_names())
        missing = [t for t in Base.metadata.tables if t not in present]
        host = engine.url.host or ""
        return {"database": "connected", "dialect": engine.dialect.name,
                "tables_missing": missing, "ready": not missing,
                "round_trip_ms": round_trip_ms,
                "database_region": _region_from_host(host),
                "api_region": os.environ.get("VERCEL_REGION", "local"),
                "advice": _latency_advice(round_trip_ms, host)}
    except DatabaseConfigError as exc:
        return JSONResponse(status_code=503, content={"database": "not configured", "error": str(exc)})
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=503, content={
            "database": "unreachable", "error": f"{type(exc).__name__}: {str(exc).splitlines()[0][:200]}",
            "hint": "Check DATABASE_URL in your Vercel environment variables."})


_REGIONS = {"ap-south-1": ("Mumbai", "bom1"), "ap-southeast-1": ("Singapore", "sin1"),
            "us-east-1": ("N. Virginia, USA", "iad1"), "us-east-2": ("Ohio, USA", "cle1"),
            "us-west-1": ("N. California, USA", "sfo1"), "us-west-2": ("Oregon, USA", "pdx1"),
            "eu-central-1": ("Frankfurt", "fra1"), "eu-west-1": ("Ireland", "dub1"),
            "eu-west-2": ("London", "lhr1"), "ap-northeast-1": ("Tokyo", "hnd1"),
            "ap-southeast-2": ("Sydney", "syd1"), "sa-east-1": ("Sao Paulo", "gru1")}


def _region_from_host(host: str) -> str:
    for code, (city, _v) in _REGIONS.items():
        if code in host:
            return f"{code} ({city})"
    return "unknown (not shown in the database address)"


def _latency_advice(ms: int, host: str) -> str:
    import os

    here = os.environ.get("VERCEL_REGION")
    for code, (city, vercel) in _REGIONS.items():
        if code in host and here and here != vercel:
            return (f"Your database is in {city} but the API runs in {here}. Every query crosses that distance. "
                    f"In Vercel -> Settings -> Functions -> Function Region, choose {vercel}, then redeploy.")
    if ms > 60:
        return (f"Each database query takes about {ms} ms. Run the API in the Vercel region closest to your "
                "database (Settings -> Functions -> Function Region).")
    return "Database response time looks good."