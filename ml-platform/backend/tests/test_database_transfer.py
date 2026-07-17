"""Tests for the idempotent database transfer utility."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest import TestCase
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    MetaData,
    String,
    Table,
    Column,
    create_engine,
    insert,
    select,
    text,
)
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import dialect as postgresql_dialect

from tools.migrate_database import TableTransferResult, _raw_rows, copy_database, redact_url
from app.database import Base
from app.models.model_library import ModelLibrary
from app.models.project import Project
from app.models.training import TrainingJob
from app.models.user import User


PROJECT_ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = PROJECT_ROOT / "ml-platform" / "backend"
TEMP_ROOT = PROJECT_ROOT / "temp_test"


class _RecordingConnection:
    def __init__(self, dialect):
        self.dialect = dialect
        self.statements = []

    def exec_driver_sql(self, statement):
        self.statements.append(statement)
        return [("row-1",)]


def build_schema(metadata: MetaData) -> dict[str, Table]:
    users = Table(
        "users",
        metadata,
        Column("id", String(36), primary_key=True),
        Column("payload", JSON, nullable=True),
        Column("created_at", DateTime, nullable=True),
    )
    model_library = Table(
        "model_library",
        metadata,
        Column("id", String(36), primary_key=True),
        Column("training_job_id", String(36), ForeignKey("training_jobs.id"), nullable=True),
        Column("user_id", String(36), ForeignKey("users.id"), nullable=False),
    )
    training_jobs = Table(
        "training_jobs",
        metadata,
        Column("id", String(36), primary_key=True),
        Column("model_library_id", String(36), ForeignKey("model_library.id"), nullable=True),
        Column("user_id", String(36), ForeignKey("users.id"), nullable=False),
    )
    Table("alembic_version", metadata, Column("version_num", String(32), primary_key=True))
    return {table.name: table for table in (users, model_library, training_jobs)}


class TestRawRows(TestCase):
    def test_schema_qualified_table_and_columns_are_quoted(self):
        metadata = MetaData()
        table = Table("records", metadata, Column("id", String(20), primary_key=True), schema="tenant")
        connection = _RecordingConnection(postgresql_dialect())
        self.assertEqual(_raw_rows(connection, table), [{"id": "row-1"}])
        self.assertEqual(connection.statements, ['SELECT "id" FROM "tenant"."records"'])


class TestDatabaseTransfer(TestCase):
    def setUp(self):
        TEMP_ROOT.mkdir(parents=True, exist_ok=True)
        self.directory = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        self.source_engine = create_engine(f"sqlite:///{Path(self.directory.name) / 'source.db'}")
        self.target_engine = create_engine(f"sqlite:///{Path(self.directory.name) / 'target.db'}")
        self.source_metadata = MetaData()
        self.target_metadata = MetaData()
        self.source_tables = build_schema(self.source_metadata)
        self.target_tables = build_schema(self.target_metadata)
        self.source_metadata.create_all(self.source_engine)
        self.target_metadata.create_all(self.target_engine)

    def tearDown(self):
        self.source_engine.dispose()
        self.target_engine.dispose()
        self.directory.cleanup()

    def test_preserves_uuid_datetime_json_and_null_values(self):
        user_id = uuid4()
        created_at = datetime(2026, 7, 16, 8, 30, tzinfo=timezone.utc)
        with self.source_engine.begin() as connection:
            connection.execute(
                insert(self.source_tables["users"]).values(
                    id=str(user_id), payload={"labels": ["a", 3]}, created_at=created_at
                )
            )
        results = copy_database(self.source_engine, self.target_engine)
        with self.target_engine.connect() as connection:
            row = connection.execute(select(self.target_tables["users"])).one()
        self.assertEqual(UUID(row.id), user_id)
        self.assertEqual(row.payload, {"labels": ["a", 3]})
        self.assertEqual(row.created_at, created_at.replace(tzinfo=None))
        self.assertEqual(results["users"].inserted_count, 1)

    def test_is_idempotent_and_skips_alembic_version(self):
        with self.source_engine.begin() as connection:
            connection.execute(insert(self.source_tables["users"]).values(id="u1"))
            connection.execute(text("INSERT INTO alembic_version VALUES ('source-revision')"))
        with self.target_engine.begin() as connection:
            connection.execute(text("INSERT INTO alembic_version VALUES ('target-revision')"))
        first = copy_database(self.source_engine, self.target_engine)
        second = copy_database(self.source_engine, self.target_engine)
        self.assertEqual(first["users"].inserted_count, 1)
        self.assertEqual(second["users"].inserted_count, 0)
        self.assertNotIn("alembic_version", first)
        with self.target_engine.connect() as connection:
            self.assertEqual(
                connection.scalar(text("SELECT version_num FROM alembic_version")),
                "target-revision",
            )

    def test_target_conflict_is_reported_without_overwrite(self):
        with self.source_engine.begin() as connection:
            connection.execute(insert(self.source_tables["users"]).values(id="u1", payload={"source": True}))
        with self.target_engine.begin() as connection:
            connection.execute(insert(self.target_tables["users"]).values(id="u1", payload={"target": True}))
        results = copy_database(self.source_engine, self.target_engine)
        self.assertEqual(results["users"].mismatched_ids, ("u1",))
        with self.target_engine.connect() as connection:
            self.assertEqual(connection.scalar(select(self.target_tables["users"].c.payload)), {"target": True})

    def test_nullable_foreign_key_cycle_is_inserted_and_repaired(self):
        with self.source_engine.begin() as connection:
            connection.execute(insert(self.source_tables["users"]).values(id="u1"))
            connection.execute(insert(self.source_tables["model_library"]).values(id="m1", user_id="u1"))
            connection.execute(insert(self.source_tables["training_jobs"]).values(id="j1", user_id="u1", model_library_id="m1"))
            connection.execute(self.source_tables["model_library"].update().values(training_job_id="j1"))
        results = copy_database(self.source_engine, self.target_engine)
        self.assertEqual(results["model_library"].mismatched_ids, ())
        with self.target_engine.connect() as connection:
            self.assertEqual(connection.scalar(select(self.target_tables["model_library"].c.training_job_id)), "j1")
            self.assertEqual(connection.scalar(select(self.target_tables["training_jobs"].c.model_library_id)), "m1")


class TestRealOrmUuidTransfer(TestCase):
    def test_real_orm_uuid_sqlite_transfer_and_cross_representation_match(self):
        TEMP_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            source_engine = create_engine(f"sqlite:///{Path(directory) / 'orm-source.db'}")
            target_engine = create_engine(f"sqlite:///{Path(directory) / 'orm-target.db'}")
            Base.metadata.create_all(source_engine)
            Base.metadata.create_all(target_engine)
            user_id = uuid4()
            with sessionmaker(bind=source_engine)() as session:
                session.add(User(id=user_id, username="orm-user", password_hash="hash"))
                session.commit()
            results = copy_database(source_engine, target_engine)
            with sessionmaker(bind=target_engine)() as session:
                copied = session.query(User).filter_by(id=user_id).one()
            self.assertEqual(copied.id, user_id)
            self.assertEqual(results["users"].mismatched_ids, ())
            source_engine.dispose()
            target_engine.dispose()

    def test_real_orm_bidirectional_uuid_cycle_repair_is_idempotent(self):
        TEMP_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            source_engine = create_engine(f"sqlite:///{Path(directory) / 'cycle-source.db'}")
            target_engine = create_engine(f"sqlite:///{Path(directory) / 'cycle-target.db'}")
            Base.metadata.create_all(source_engine)
            Base.metadata.create_all(target_engine)
            user_id, project_id = uuid4(), uuid4()
            model_id, training_id = uuid4(), uuid4()
            created_at = datetime(2026, 7, 16, 12, 34, 56)
            with sessionmaker(bind=source_engine)() as session:
                session.add(User(id=user_id, username="cycle-user", password_hash="hash"))
                session.add(Project(id=project_id, name="cycle-project", owner_id=user_id))
                session.add(
                    ModelLibrary(
                        id=model_id,
                        name="cycle-model",
                        owner_id=user_id,
                        project_id=project_id,
                        metrics={"accuracy": 0.98, "labels": ["ok", "ng"]},
                        params={"epochs": 12, "nested": {"enabled": True}},
                        tags=["production", "welding"],
                        algorithm_id=None,
                        created_at=created_at,
                    )
                )
                session.add(TrainingJob(id=training_id, name="cycle-job", project_id=project_id, user_id=user_id))
                session.commit()
                session.query(ModelLibrary).filter_by(id=model_id).update({"training_job_id": training_id})
                session.query(TrainingJob).filter_by(id=training_id).update({"model_library_id": model_id})
                session.commit()
                source_model = session.query(ModelLibrary).filter_by(id=model_id).one()
                source_updated_at = source_model.updated_at
            first = copy_database(source_engine, target_engine)
            second = copy_database(source_engine, target_engine)
            with sessionmaker(bind=target_engine)() as session:
                copied_model = session.query(ModelLibrary).filter_by(id=model_id).one()
                copied_job = session.query(TrainingJob).filter_by(id=training_id).one()
            self.assertEqual(copied_model.training_job_id, training_id)
            self.assertEqual(copied_job.model_library_id, model_id)
            self.assertEqual(copied_model.metrics, {"accuracy": 0.98, "labels": ["ok", "ng"]})
            self.assertEqual(copied_model.params, {"epochs": 12, "nested": {"enabled": True}})
            self.assertEqual(copied_model.tags, ["production", "welding"])
            self.assertIsNone(copied_model.algorithm_id)
            self.assertEqual(copied_model.created_at, created_at)
            self.assertEqual(copied_model.updated_at, source_updated_at)
            self.assertEqual(first["model_library"].mismatched_ids, ())
            self.assertEqual(first["training_jobs"].mismatched_ids, ())
            self.assertEqual(second["model_library"].inserted_count, 0)
            self.assertEqual(second["training_jobs"].inserted_count, 0)
            self.assertEqual(second["model_library"].mismatched_ids, ())
            self.assertEqual(second["training_jobs"].mismatched_ids, ())
            source_engine.dispose()
            target_engine.dispose()


class TestMigrationCLI(TestCase):
    def test_same_normalized_url_is_rejected(self):
        safe_url = redact_url("sqlite:///db.sqlite?token=secret#fragment")
        self.assertNotIn("token=secret", safe_url)
        self.assertNotIn("#fragment", safe_url)
        command = [sys.executable, "tools/migrate_database.py", "--source-url", "sqlite:///same.db?x=1", "--target-url", "sqlite:///same.db?x=1"]
        result = subprocess.run(command, cwd=BACKEND_ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertNotIn("x=1", result.stdout + result.stderr)

    def test_cli_redacts_url_and_returns_failure_for_mismatch(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            source = Path(directory) / "source.db"
            target = Path(directory) / "target.db"
            metadata = MetaData()
            table = Table("items", metadata, Column("id", String(20), primary_key=True), Column("value", String(20)))
            source_setup_engine = create_engine(f"sqlite:///{source}")
            target_setup_engine = create_engine(f"sqlite:///{target}")
            metadata.create_all(source_setup_engine)
            metadata.create_all(target_setup_engine)
            with source_setup_engine.begin() as connection:
                connection.execute(insert(table).values(id="x", value="source"))
            with target_setup_engine.begin() as connection:
                connection.execute(insert(table).values(id="x", value="target"))
            source_setup_engine.dispose()
            target_setup_engine.dispose()
            result = subprocess.run(
                [sys.executable, "tools/migrate_database.py", "--source-url", f"sqlite:///{source}?password=secret#x", "--target-url", f"sqlite:///{target}"],
                cwd=BACKEND_ROOT,
                capture_output=True,
                text=True,
            )
        self.assertEqual(result.returncode, 1)
        self.assertIn("mismatched=1", result.stdout)
        self.assertNotIn("password=secret", result.stdout)
        self.assertNotIn("#x", result.stdout)


if __name__ == "__main__":
    import unittest

    unittest.main()
