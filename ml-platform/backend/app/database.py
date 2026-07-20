"""Minimal SQLAlchemy engine, session, and declarative base."""

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings


def engine_options(database_url: str, settings_obj=settings) -> dict:
    """Return dialect-appropriate SQLAlchemy engine options."""
    parsed_url = make_url(database_url)
    if parsed_url.get_backend_name() == "sqlite":
        options = {"connect_args": {"check_same_thread": False}}
        database = parsed_url.database or ""
        is_memory_database = (
            database in {"", ":memory:"}
            or database.startswith("file::memory:")
            or parsed_url.query.get("mode") == "memory"
        )
        if is_memory_database:
            options["poolclass"] = StaticPool
        return options
    return {
        "pool_pre_ping": True,
        "pool_size": settings_obj.database_pool_size,
        "max_overflow": settings_obj.database_max_overflow,
        "pool_timeout": settings_obj.database_pool_timeout_seconds,
    }


engine = create_engine(
    settings.database_url,
    echo=False,
    **engine_options(settings.database_url),
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""
    pass


def get_db():
    """Yield a database session, ensuring it is closed after use."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
