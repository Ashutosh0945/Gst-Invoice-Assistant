from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.routes import router
from backend.api.routes_compliance import router as compliance_router
from backend.api.routes_app import router as app_router
from backend.config import get_settings
from backend.logging_conf import setup_logging

setup_logging()

app = FastAPI(
    title="GST Invoice Processing & Accounting Assistant",
    version="0.2.0",
    description="AI + data-engineering pipeline for Indian GST invoice automation.",
)

# Same-origin in production (Next.js and this API share one Vercel deployment,
# proxied via vercel.json rewrites). Permissive CORS here only helps local
# dev if the frontend ever calls the API on a different port directly.
_s = get_settings()
if _s.cookie_secure and _s.session_secret == "change-me-in-production":
    raise RuntimeError("SESSION_SECRET is still the default. Set a long random value before going live "
                       "(python -c \"import secrets; print(secrets.token_urlsafe(48))\").")

_origins = [o.strip() for o in get_settings().cors_origins.split(",") if o.strip()]
if _origins:   # only needed if the web app is served from a different domain than the API
    app.add_middleware(CORSMiddleware, allow_origins=_origins, allow_credentials=True,
                       allow_methods=["*"], allow_headers=["*"])

app.include_router(app_router, prefix="/api/v1")          # the personal app (signed-in users)

# The business console API (invoice register, GSTR-2B, ITC, analytics). Every route needs a
# staff login or the server API_KEY, and only ever sees business invoices (backend/api/deps.py).
if get_settings().console_enabled:
    app.include_router(router, prefix="/api/v1")
    app.include_router(compliance_router, prefix="/api/v1")


@app.get("/health")
def health():
    return {"status": "ok"}
