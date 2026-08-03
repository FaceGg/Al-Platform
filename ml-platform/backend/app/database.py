"""Minimal SQLAlchemy engine, session, and declarative base."""

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings


SQLITE_BUSY_TIMEOUT_MS = 30_000


def _is_memory_sqlite_url(database_url: str) -> bool:
    parsed_url = make_url(database_url)
    database = parsed_url.database or ""
    return (
        database in {"", ":memory:"}
        or database.startswith("file::memory:")
        or parsed_url.query.get("mode") == "memory"
    )


def engine_options(database_url: str, settings_obj=settings) -> dict:
    """Return dialect-appropriate SQLAlchemy engine options."""
    parsed_url = make_url(database_url)
    if parsed_url.get_backend_name() == "sqlite":
        options = {"connect_args": {"check_same_thread": False}}
        if _is_memory_sqlite_url(database_url):
            options["poolclass"] = StaticPool
        return options
    return {
        "pool_pre_ping": True,
        "pool_size": settings_obj.database_pool_size,
        "max_overflow": settings_obj.database_max_overflow,
        "pool_timeout": settings_obj.database_pool_timeout_seconds,
    }


def configure_sqlite_engine(db_engine: Engine) -> None:
    """Apply local SQLite settings that tolerate long read/write annotation runs."""
    if db_engine.dialect.name != "sqlite":
        return
    use_wal = not _is_memory_sqlite_url(str(db_engine.url))

    @event.listens_for(db_engine, "connect")
    def _configure_sqlite_connection(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        try:
            if use_wal:
                cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
        finally:
            cursor.close()


engine = create_engine(
    settings.database_url,
    echo=False,
    **engine_options(settings.database_url),
)
configure_sqlite_engine(engine)
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
