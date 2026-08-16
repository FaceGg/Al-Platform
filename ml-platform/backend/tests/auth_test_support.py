"""Test-only authenticated-user bootstrap helpers."""

from app.api.auth import pwd_context
from app.database import SessionLocal
from app.models.user import User


def ensure_admin(username: str = "admin", password: str = "admin123") -> None:
    """Create an isolated administrator without exercising public registration."""
    db = SessionLocal()
    try:
        if db.query(User).filter(User.username == username).first() is None:
            db.add(
                User(
                    username=username,
                    password_hash=pwd_context.hash(password),
                    role="admin",
                ),
            )
            db.commit()
    finally:
        db.close()
