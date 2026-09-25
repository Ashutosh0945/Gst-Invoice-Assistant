"""Create a console (staff) account, or give an existing account console access.

    PYTHONPATH=. python scripts/create_staff.py priya@yourfirm.in "Priya Sharma"
    (you'll be asked for a password; for an existing account the password is left unchanged)

Online: run it on your computer with DATABASE_URL set to the Neon connection string.
"""
from __future__ import annotations

import getpass
import sys

from sqlalchemy import select

from backend.db import models  # noqa: F401
from backend.db.base import Base, SessionLocal, engine
from backend.db.models import User
from backend.personal.auth import hash_password


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    email = sys.argv[1].strip().lower()
    name = sys.argv[2] if len(sys.argv) > 2 else email.split("@")[0]
    Base.metadata.create_all(engine)
    db = SessionLocal()
    user = db.execute(select(User).where(User.email == email)).scalars().first()
    if user:
        user.role = "staff"
        db.commit()
        print(f"{email} now has console access (password unchanged).")
        return
    pw = getpass.getpass("Password for the new staff account (8+ characters): ")
    if len(pw) < 8:
        print("Password too short.")
        sys.exit(1)
    db.add(User(email=email, name=name, password_hash=hash_password(pw), profile_type="business", role="staff"))
    db.commit()
    print(f"Created staff account {email}.")


if __name__ == "__main__":
    main()
