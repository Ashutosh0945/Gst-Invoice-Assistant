from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.routes import router
from backend.api.routes_compliance import router as compliance_router
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
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

app.include_router(router, prefix="/api/v1")
app.include_router(compliance_router, prefix="/api/v1")


@app.get("/health")
def health():
    return {"status": "ok"}
