"""Email + password accounts with signed, stateless session cookies.

Passwords: PBKDF2-HMAC-SHA256 with a per-user salt (Python standard library,
no extra dependency). Sessions: "<user_id>.<expiry>.<hmac>" signed with
SESSION_SECRET, sent as an HttpOnly cookie so page scripts can't read it.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import time
import uuid

from fastapi import Cookie, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from backend.config import get_settings
from backend.db.base import get_db
from backend.db.models import User

COOKIE = "session"
ITERATIONS = 240_000


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITERATIONS)
    return f"pbkdf2${ITERATIONS}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, iters, salt, digest = stored.split("$")
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), base64.b64decode(salt), int(iters))
        return hmac.compare_digest(base64.b64encode(dk).decode(), digest)
    except (ValueError, TypeError):
        return False


def _sign(payload: str) -> str:
    key = get_settings().session_secret.encode()
    return hmac.new(key, payload.encode(), hashlib.sha256).hexdigest()


def make_session(user_id: uuid.UUID) -> str:
    exp = int(time.time()) + get_settings().session_days * 86400
    payload = f"{user_id}.{exp}"
    return f"{payload}.{_sign(payload)}"


def read_session(token: str | None) -> uuid.UUID | None:
    if not token or token.count(".") != 2:
        return None
    uid, exp, sig = token.split(".")
    if not hmac.compare_digest(sig, _sign(f"{uid}.{exp}")):
        return None
    if int(exp) < time.time():
        return None
    try:
        return uuid.UUID(uid)
    except ValueError:
        return None


def set_session_cookie(response: Response, user_id: uuid.UUID) -> None:
    s = get_settings()
    response.set_cookie(COOKIE, make_session(user_id), httponly=True, samesite="lax", secure=s.cookie_secure,
                        max_age=s.session_days * 86400, path="/")


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE, path="/")


def current_user(session: str | None = Cookie(default=None), db: Session = Depends(get_db)) -> User:
    uid = read_session(session)
    user = db.get(User, uid) if uid else None
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Please sign in.")
    return user
