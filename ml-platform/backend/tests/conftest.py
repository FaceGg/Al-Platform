"""Pytest collection policy for the generic platform test suite."""

import os

# Multi-module test runs share one TestClient IP and easily exceed the
# production login IP limit (5 / 15 min). Raise it for the whole test process.
os.environ.setdefault("LOGIN_IP_RATE_LIMIT_CAPACITY", "100")

import pytest
from sqlalchemy import event

from tests.week_manifest import DEPRECATED_TEST_MODULES


def _enforce_sqlite_foreign_keys() -> None:
    """Match production referential integrity in the SQLite test path.

    SQLite ignores foreign keys unless the pragma is set, so a missing
    detach/cleanup step before a delete passes locally and only fails on
    PostgreSQL. Set ``SQLITE_FOREIGN_KEYS=0`` to opt out while triaging.
    """
    if os.environ.get("SQLITE_FOREIGN_KEYS") == "0":
        return
    from app.database import engine

    if engine.dialect.name != "sqlite":
        return

    @event.listens_for(engine, "connect")
    def _set_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()


_enforce_sqlite_foreign_keys()


def pytest_collection_modifyitems(config, items):
    """Keep historical industry tests out of the default active suite."""
    if os.environ.get("INCLUDE_DEPRECATED_TESTS") == "1":
        return

    skip_deprecated = pytest.mark.skip(
        reason=(
            "historical point-weld compatibility test; "
            "set INCLUDE_DEPRECATED_TESTS=1 to run explicitly"
        )
    )
    for item in items:
        module_name = item.module.__name__.rsplit(".", 1)[-1]
        if module_name in DEPRECATED_TEST_MODULES:
            item.add_marker(skip_deprecated)
