"""Pytest collection policy for the generic platform test suite."""

import os

# Multi-module test runs share one TestClient IP and easily exceed the
# production login IP limit (5 / 15 min). Raise it for the whole test process.
os.environ.setdefault("LOGIN_IP_RATE_LIMIT_CAPACITY", "100")

# python_script operator tests execute against the current interpreter instead
# of bootstrapping a real venv (which would download packages from PyPI).
os.environ.setdefault("PYTHON_SCRIPT_VENV_DIR", "")

# 直跑 pytest 的密封兜底：本 conftest 自身会 import app.database 固化引擎 URL，
# 若不在此时兜底，各测试模块文件头的密封兜底（如 test_demo_loop）全部来不及
# 生效——用例会静默写入共享开发库，残留行再引发计数漂移与
# experiments.mlflow_experiment_id 唯一键冲突（test_demo_loop 6 败的根因）。
# run_suite/CI 在进程外用硬赋值注入 DATABASE_URL，此 setdefault 不影响其路径。
if not os.environ.get("DATABASE_URL"):
    import atexit
    import uuid as _uuid
    from pathlib import Path as _Path

    _SEALED_DIR = _Path("temp_test")
    _SEALED_DIR.mkdir(exist_ok=True)
    _SEALED_DB = _SEALED_DIR / f"pytest-{os.getpid()}-{_uuid.uuid4().hex[:8]}.db"
    os.environ["DATABASE_URL"] = "sqlite:///" + _SEALED_DB.as_posix()

    def _cleanup_sealed_db():
        # Windows 语义：sqlite 文件被 engine 连接持有时 unlink 报 WinError 32，
        # 先 dispose 再删；仍失败则静默留下（temp_test 不入库）。
        try:
            import app.database as _sealed_database

            _sealed_database.engine.dispose()
        except Exception:
            pass
        try:
            _SEALED_DB.unlink(missing_ok=True)
        except OSError:
            pass

    atexit.register(_cleanup_sealed_db)

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
