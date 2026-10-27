"""Read-only Alembic schema revision checks."""

from functools import lru_cache
from pathlib import Path

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy.engine import Engine


DATABASE_SCHEMA_OUTDATED = "DATABASE_SCHEMA_OUTDATED"


class DatabaseSchemaError(RuntimeError):
    """Raised when the database revision is not the Alembic head."""

    def __init__(self, code: str = DATABASE_SCHEMA_OUTDATED):
        self.code = code
        super().__init__(code)


def schema_status(current: str | None, head: str | None) -> dict:
    """Describe whether a database revision matches the migration head."""
    status = {
        "ready": current is not None and current == head,
        "current": current,
        "head": head,
    }
    if not status["ready"]:
        status["code"] = DATABASE_SCHEMA_OUTDATED
    return status


def require_current_schema(engine: Engine, config_path: str | Path | None = None) -> dict:
    """Require the configured database to already be at Alembic head."""
    with engine.connect() as connection:
        current = MigrationContext.configure(connection).get_current_revision()
    status = schema_status(
        current,
        _script_head(str(config_path or _default_config_path())),
    )
    if not status["ready"]:
        raise DatabaseSchemaError(code=DATABASE_SCHEMA_OUTDATED)
    return status


@lru_cache(maxsize=8)
def _script_head(config_path: str) -> str | None:
    """Resolve the script head once per process per config path.

    Building a ScriptDirectory rescans every file under the versions
    directory, and readiness probes call this repeatedly. A new head only
    ships with a new deployment (new process), so in-process caching is
    safe; DB revisions are still read fresh on every call.
    """
    return ScriptDirectory.from_config(Config(config_path)).get_current_head()


def _default_config_path() -> Path:
    return Path(__file__).resolve().parents[1] / "alembic.ini"
