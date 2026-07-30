"""Production database and Alembic baseline tests."""

from pathlib import Path
from queue import Queue
from threading import Thread
from types import SimpleNamespace
from unittest import TestCase, mock
import tempfile

from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.main as main_module
from app.config import settings
from app.database import engine_options
from app.database_schema import (
    DatabaseSchemaError,
    require_current_schema,
    schema_status,
)
from app.main import initialize_database
from app.models.user import User


BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = Path(__file__).resolve().parents[3]
TEMP_ROOT = PROJECT_ROOT / "temp_test"
ALEMBIC_INI = BACKEND_ROOT / "alembic.ini"
BASELINE_REVISION = BACKEND_ROOT / "alembic" / "versions" / "20260715_01_baseline_schema.py"
HEAD_REVISION = "20260730_09"


class TestDatabaseEngineOptions(TestCase):
    def test_sqlite_engine_uses_thread_compatibility(self):
        self.assertEqual(
            engine_options("sqlite:///test.db"),
            {"connect_args": {"check_same_thread": False}},
        )

    def test_memory_sqlite_urls_use_static_pool(self):
        memory_urls = (
            "sqlite://",
            "sqlite:///:memory:",
            "sqlite:///file:shared?mode=memory&cache=shared&uri=true",
        )

        for database_url in memory_urls:
            with self.subTest(database_url=database_url):
                self.assertIs(engine_options(database_url)["poolclass"], StaticPool)

    def test_memory_sqlite_shares_data_across_threads(self):
        db_engine = create_engine("sqlite://", **engine_options("sqlite://"))
        query_result = Queue()
        try:
            with db_engine.begin() as connection:
                connection.execute(text("CREATE TABLE shared_data (value INTEGER NOT NULL)"))
                connection.execute(text("INSERT INTO shared_data (value) VALUES (42)"))

            def query_from_thread():
                try:
                    with db_engine.connect() as connection:
                        query_result.put(connection.scalar(text("SELECT value FROM shared_data")))
                except Exception as error:
                    query_result.put(error)

            worker = Thread(target=query_from_thread)
            worker.start()
            worker.join()

            result = query_result.get_nowait()
            if isinstance(result, Exception):
                raise result
            self.assertEqual(result, 42)
        finally:
            db_engine.dispose()

    def test_postgres_engine_uses_configured_pool_options(self):
        configured_settings = SimpleNamespace(
            database_pool_size=7,
            database_max_overflow=11,
            database_pool_timeout_seconds=19,
        )

        self.assertEqual(
            engine_options(
                "postgresql+psycopg://user:pass@db/app",
                settings_obj=configured_settings,
            ),
            {
                "pool_pre_ping": True,
                "pool_size": 7,
                "max_overflow": 11,
                "pool_timeout": 19,
            },
        )


class TestDatabaseSchemaStatus(TestCase):
    def test_current_head_is_ready(self):
        self.assertEqual(
            schema_status(HEAD_REVISION, HEAD_REVISION),
            {
                "ready": True,
                "current": HEAD_REVISION,
                "head": HEAD_REVISION,
            },
        )

    def test_outdated_revision_has_stable_error_code(self):
        self.assertEqual(
            schema_status("old", HEAD_REVISION),
            {
                "ready": False,
                "code": "DATABASE_SCHEMA_OUTDATED",
                "current": "old",
                "head": HEAD_REVISION,
            },
        )

    def test_require_current_schema_rejects_missing_revision(self):
        with self._temporary_database() as database_url:
            db_engine = create_engine(database_url)
            try:
                with self.assertRaises(DatabaseSchemaError) as raised:
                    require_current_schema(db_engine, ALEMBIC_INI)
            finally:
                db_engine.dispose()

        self.assertEqual(raised.exception.code, "DATABASE_SCHEMA_OUTDATED")

    def test_require_current_schema_rejects_outdated_revision(self):
        with self._temporary_database() as database_url:
            db_engine = create_engine(database_url)
            try:
                with db_engine.begin() as connection:
                    connection.execute(
                        text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
                    )
                    connection.execute(
                        text("INSERT INTO alembic_version (version_num) VALUES ('old')")
                    )
                with self.assertRaises(DatabaseSchemaError) as raised:
                    require_current_schema(db_engine, ALEMBIC_INI)
            finally:
                db_engine.dispose()

        self.assertEqual(raised.exception.code, "DATABASE_SCHEMA_OUTDATED")

    def _temporary_database(self):
        TEMP_ROOT.mkdir(parents=True, exist_ok=True)
        return _TemporaryDatabase()


class TestDatabaseInitialization(TestCase):
    @mock.patch("app.main.require_current_schema")
    @mock.patch("app.main.ensure_schema_compatibility")
    @mock.patch("app.main.Base.metadata.create_all")
    def test_local_initialization_creates_and_updates_schema(
        self,
        create_all,
        ensure_compatibility,
        require_schema,
    ):
        db_engine = object()

        initialize_database(SimpleNamespace(app_mode="local"), db_engine)

        create_all.assert_called_once_with(bind=db_engine)
        ensure_compatibility.assert_called_once_with(db_engine)
        require_schema.assert_not_called()

    @mock.patch("app.main.require_current_schema")
    @mock.patch("app.main.ensure_schema_compatibility")
    @mock.patch("app.main.Base.metadata.create_all")
    def test_production_initialization_only_checks_revision(
        self,
        create_all,
        ensure_compatibility,
        require_schema,
    ):
        db_engine = object()

        initialize_database(SimpleNamespace(app_mode="production"), db_engine)

        require_schema.assert_called_once_with(db_engine)
        create_all.assert_not_called()
        ensure_compatibility.assert_not_called()


class TestDatabaseLifespan(TestCase):
    def test_default_admin_seed_tolerates_concurrent_unique_insert(self):
        existing_user = SimpleNamespace(username="admin")

        class Query:
            def __init__(self):
                self.calls = 0
            def filter(self, *_args):
                return self
            def first(self):
                self.calls += 1
                return None if self.calls == 1 else existing_user

        class Session:
            def __init__(self):
                self.query_result = Query()
                self.rollback_called = False
            def query(self, _model):
                return self.query_result
            def add(self, _value):
                return None
            def commit(self):
                raise IntegrityError("insert", {}, RuntimeError("duplicate"))
            def rollback(self):
                self.rollback_called = True
            def close(self):
                return None

        db = Session()
        main_module.ensure_default_admin(lambda: db)
        self.assertTrue(db.rollback_called)

    def test_lifespan_uses_injected_database_dependencies(self):
        TEMP_ROOT.mkdir(parents=True, exist_ok=True)
        with _TemporaryDatabase() as database_url:
            db_engine = create_engine(database_url, **engine_options(database_url))
            session_factory = sessionmaker(
                autocommit=False,
                autoflush=False,
                bind=db_engine,
            )
            test_app = FastAPI(lifespan=main_module.lifespan)
            main_module.configure_runtime_dependencies(
                test_app,
                app_settings=SimpleNamespace(app_mode="local"),
                db_engine=db_engine,
                session_factory=session_factory,
            )

            with (
                mock.patch.object(main_module, "SessionLocal") as global_session_factory,
                mock.patch.object(main_module, "engine") as global_engine,
                mock.patch.object(db_engine, "dispose", wraps=db_engine.dispose) as dispose,
            ):
                with TestClient(test_app):
                    with session_factory() as db:
                        admin = db.query(User).filter(User.username == "admin").one()
                        self.assertEqual(admin.role, "admin")

                global_session_factory.assert_not_called()
                global_engine.dispose.assert_not_called()
                dispose.assert_called_once_with()


class TestAlembicBaseline(TestCase):
    def test_baseline_is_static_and_does_not_use_metadata_ddl(self):
        self.assertTrue(BASELINE_REVISION.is_file())
        source = BASELINE_REVISION.read_text(encoding="utf-8")
        self.assertNotIn("create_all", source)
        self.assertNotIn("drop_all", source)
        self.assertIn("revision = \"20260715_01\"", source)

    def test_upgrade_head_twice_creates_complete_schema(self):
        TEMP_ROOT.mkdir(parents=True, exist_ok=True)
        with _TemporaryDatabase() as database_url:
            config = Config(str(ALEMBIC_INI))
            original_database_url = settings.database_url
            settings.database_url = database_url
            try:
                command.upgrade(config, "head")
                command.upgrade(config, "head")
                command.check(config)
            finally:
                settings.database_url = original_database_url

            db_engine = create_engine(database_url)
            try:
                inspector = inspect(db_engine)
                business_tables = set(inspector.get_table_names()) - {"alembic_version"}
                self.assertEqual(len(business_tables), 43)
                self.assertTrue(
                    {
                        "users",
                        "projects",
                        "workflows",
                        "workflow_versions",
                        "artifacts",
                        "experiments",
                        "training_jobs",
                        "pipeline_schedules",
                        "pipeline_schedule_runs",
                        "project_members",
                        "spot_weld_quality_runs",
                        "spot_weld_quality_samples",
                        "spot_weld_quality_rule_sets",
                        "spot_weld_label_revisions",
                        "spot_weld_label_snapshots",
                        "audit_events",
                        "registered_models",
                        "model_versions",
                        "inference_deployments",
                    }.issubset(business_tables)
                )
                self.assertIn(
                    "ix_users_username",
                    {item["name"] for item in inspector.get_indexes("users")},
                )
                self.assertIn(
                    "ix_graph_entities_name",
                    {item["name"] for item in inspector.get_indexes("graph_entities")},
                )
                self.assertIn(
                    "storage_uri",
                    {item["name"] for item in inspector.get_columns("artifacts")},
                )
                self.assertIn(
                    "ix_artifacts_storage_uri",
                    {item["name"] for item in inspector.get_indexes("artifacts")},
                )
                self.assertIn(
                    "timeout_seconds",
                    {item["name"] for item in inspector.get_columns("workflow_runs")},
                )
                self.assertIn(
                    "next_attempt_at",
                    {
                        item["name"]
                        for item in inspector.get_columns("pipeline_schedule_runs")
                    },
                )
                self.assertIn(
                    "ix_pipeline_schedule_runs_retry",
                    {
                        item["name"]
                        for item in inspector.get_indexes("pipeline_schedule_runs")
                    },
                )
                self.assertIn(
                    "ix_project_members_user_project",
                    {item["name"] for item in inspector.get_indexes("project_members")},
                )
                self.assertIn(
                    "ix_audit_events_project_created",
                    {item["name"] for item in inspector.get_indexes("audit_events")},
                )
                model_library_foreign_keys = {
                    tuple(item["constrained_columns"]): item["referred_table"]
                    for item in inspector.get_foreign_keys("model_library")
                }
                self.assertEqual(
                    model_library_foreign_keys[("training_job_id",)],
                    "training_jobs",
                )
                experiment_uniques = {
                    tuple(item["column_names"])
                    for item in inspector.get_unique_constraints("experiments")
                }
                self.assertIn(("project_id", "name"), experiment_uniques)
                training_columns = {
                    item["name"] for item in inspector.get_columns("training_jobs")
                }
                self.assertTrue({
                    "experiment_id",
                    "mlflow_run_id",
                    "task_id",
                    "heartbeat_at",
                    "latest_checkpoint_uri",
                    "current_epoch",
                    "total_epochs",
                }.issubset(training_columns))
                with db_engine.connect() as connection:
                    revision = connection.scalar(
                        text("SELECT version_num FROM alembic_version")
                    )
                self.assertEqual(revision, HEAD_REVISION)
            finally:
                db_engine.dispose()

    def test_experiment_tracking_revision_has_complete_downgrade(self):
        TEMP_ROOT.mkdir(parents=True, exist_ok=True)
        with _TemporaryDatabase() as database_url:
            config = Config(str(ALEMBIC_INI))
            original_database_url = settings.database_url
            settings.database_url = database_url
            try:
                command.upgrade(config, "head")
                command.downgrade(config, "20260715_03")
            finally:
                settings.database_url = original_database_url

            db_engine = create_engine(database_url)
            try:
                inspector = inspect(db_engine)
                self.assertNotIn("experiments", inspector.get_table_names())
                self.assertNotIn("project_members", inspector.get_table_names())
                self.assertNotIn("audit_events", inspector.get_table_names())
                training_columns = {
                    item["name"] for item in inspector.get_columns("training_jobs")
                }
                self.assertNotIn("experiment_id", training_columns)
                with db_engine.connect() as connection:
                    revision = connection.scalar(
                        text("SELECT version_num FROM alembic_version")
                    )
                self.assertEqual(revision, "20260715_03")
            finally:
                db_engine.dispose()

    def test_model_registry_revision_has_complete_downgrade(self):
        TEMP_ROOT.mkdir(parents=True, exist_ok=True)
        with _TemporaryDatabase() as database_url:
            config = Config(str(ALEMBIC_INI))
            original_database_url = settings.database_url
            settings.database_url = database_url
            try:
                command.upgrade(config, "head")
                command.downgrade(config, "20260718_07")
            finally:
                settings.database_url = original_database_url

            db_engine = create_engine(database_url)
            try:
                inspector = inspect(db_engine)
                tables = set(inspector.get_table_names())
                self.assertNotIn("registered_models", tables)
                self.assertNotIn("model_versions", tables)
                self.assertNotIn("inference_deployments", tables)
                self.assertIn("audit_events", tables)
                with db_engine.connect() as connection:
                    revision = connection.scalar(
                        text("SELECT version_num FROM alembic_version")
                    )
                self.assertEqual(revision, "20260718_07")
            finally:
                db_engine.dispose()


class _TemporaryDatabase:
    def __init__(self):
        self._directory = None

    def __enter__(self):
        self._directory = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        database_path = Path(self._directory.name) / "database.db"
        return f"sqlite:///{database_path.as_posix()}"

    def __exit__(self, exc_type, exc_value, traceback):
        self._directory.cleanup()
