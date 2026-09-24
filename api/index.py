"""Vercel entrypoint. Vercel's Python runtime auto-detects an ASGI `app`
object exported from a file under /api and serves it as serverless functions
-- one cold start per invocation (or a warm one if reused), so there is no
persistent process here. Nothing else about backend.api.main changes.
"""
from backend.api.main import app  # noqa: F401  (re-exported for Vercel's ASGI detection)
