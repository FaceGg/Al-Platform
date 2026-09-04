"""Task 1 contracts for the generic annotation boundary."""

import sys
import unittest
import uuid
import hashlib
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, ".")

from app.api.auth import get_current_user
from app.database import Base, get_db
from app.main import app
from app.models.project import Project
from app.models.user import User
from app.models.platform_models import GenericAnnotationTask
from app.services.annotation_tasks import migrate_legacy_quality_run
from app.models.spot_weld_quality import SpotWeldQualityRun
from app.models.spot_weld_quality import SpotWeldQualitySample, SpotWeldLabelRevision, SpotWeldLabelSnapshot


class GenericizationContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        cls.Session = sessionmaker(bind=cls.engine, expire_on_commit=False)
        Base.metadata.create_all(cls.engine)
        cls.db = cls.Session()
        cls.owner = User(username="generic-owner", password_hash="hash", role="engineer")
        cls.db.add(cls.owner)
        cls.db.flush()
        cls.project = Project(name="Generic project", owner_id=cls.owner.id)
        cls.db.add(cls.project)
        cls.db.commit()
        app.dependency_overrides[get_db] = lambda: cls.db
        app.dependency_overrides[get_current_user] = lambda: cls.owner
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.clear()
        cls.db.close()
        cls.engine.dispose()

    def test_generic_annotation_create_does_not_require_industry_columns(self):
        response = self.client.post(
            "/api/annotation-tasks",
            headers={"X-Request-ID": str(uuid.uuid4()), "Idempotency-Key": "generic-1"},
            json={
                "project_id": str(self.project.id),
                "dataset_version_id": str(uuid.uuid4()),
                "mode": "manual",
                "label_schema_id": str(uuid.uuid4()),
                "sample_scope": {"kind": "all"},
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        self.assertNotIn("industry_field", response.json())

    def test_generic_annotation_idempotency_returns_same_task(self):
        payload = {
            "project_id": str(self.project.id),
            "dataset_version_id": str(uuid.uuid4()),
            "mode": "manual",
            "label_schema_id": str(uuid.uuid4()),
            "sample_scope": {"kind": "all"},
        }
        headers = {"X-Request-ID": str(uuid.uuid4()), "Idempotency-Key": "same-key"}
        first = self.client.post("/api/annotation-tasks", json=payload, headers=headers)
        second = self.client.post("/api/annotation-tasks", json=payload, headers=headers)
        self.assertEqual(first.status_code, 201, first.text)
        self.assertEqual(second.status_code, 201, second.text)
        self.assertEqual(first.json()["id"], second.json()["id"])

    def test_generic_annotation_idempotency_key_is_scoped_to_the_owner(self):
        payload = {
            "project_id": str(self.project.id),
            "dataset_version_id": str(uuid.uuid4()),
            "mode": "manual",
            "label_schema_id": str(uuid.uuid4()),
            "sample_scope": {"kind": "all"},
        }
        headers = {"X-Request-ID": str(uuid.uuid4()), "Idempotency-Key": "shared-owner-key"}
        first = self.client.post("/api/annotation-tasks", json=payload, headers=headers)
        self.assertEqual(first.status_code, 201, first.text)

        other = User(username="generic-idempotency-other", password_hash="hash", role="engineer")
        self.db.add(other)
        self.db.flush()
        other_project = Project(name="Other generic project", owner_id=other.id)
        self.db.add(other_project)
        self.db.commit()
        app.dependency_overrides[get_current_user] = lambda: other
        second = self.client.post(
            "/api/annotation-tasks",
            json={**payload, "project_id": str(other_project.id)},
            headers={"X-Request-ID": str(uuid.uuid4()), "Idempotency-Key": "shared-owner-key"},
        )
        self.assertEqual(second.status_code, 201, second.text)
        self.assertNotEqual(first.json()["id"], second.json()["id"])
        app.dependency_overrides[get_current_user] = lambda: self.owner

    def test_generic_annotation_requires_explicit_correlation_headers(self):
        payload = {
            "project_id": str(self.project.id),
            "dataset_version_id": str(uuid.uuid4()),
            "mode": "manual",
            "label_schema_id": str(uuid.uuid4()),
            "sample_scope": {"kind": "all"},
        }
        missing_request = self.client.post(
            "/api/annotation-tasks", json=payload,
            headers={"Idempotency-Key": "header-test-1"},
        )
        self.assertEqual(missing_request.status_code, 400)
        missing_idempotency = self.client.post(
            "/api/annotation-tasks", json=payload,
            headers={"X-Request-ID": str(uuid.uuid4())},
        )
        self.assertEqual(missing_idempotency.status_code, 400)

    def test_legacy_spot_weld_write_is_closed(self):
        response = self.client.post(
            f"/api/projects/{self.project.id}/spot-weld/runs", json={},
            headers={"X-Request-ID": str(uuid.uuid4()), "Idempotency-Key": "legacy-410"},
        )
        self.assertEqual(response.status_code, 410, response.text)
        self.assertEqual(response.json()["detail"]["code"], "GENERIC_API_REQUIRED")
        self.assertIn("request_id", response.json()["detail"])
        self.assertIn("message", response.json()["detail"])

    def test_list_is_owner_isolated(self):
        other = User(username="generic-other", password_hash="hash", role="engineer")
        self.db.add(other)
        self.db.commit()
        task = self.db.query(GenericAnnotationTask).filter_by(owner_id=self.owner.id).first()
        if task is None:
            task = GenericAnnotationTask(
                project_id=self.project.id,
                dataset_version_id=uuid.uuid4(),
                label_schema_id=uuid.uuid4(),
                owner_id=self.owner.id,
                mode="manual",
                sample_scope={"kind": "all"},
            )
            self.db.add(task)
            self.db.commit()
        app.dependency_overrides[get_current_user] = lambda: other
        response = self.client.get("/api/annotation-tasks", headers={"X-Request-ID": str(uuid.uuid4())})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total"], 0)
        app.dependency_overrides[get_current_user] = lambda: self.owner

    def test_legacy_quality_run_migrates_to_generic_task(self):
        run = SpotWeldQualityRun(
            project_id=self.project.id,
            dataset_artifact_id=uuid.uuid4(),
            created_by_id=self.owner.id,
            status="completed",
            field_mapping={"target_column": "label"},
            automl_results=[{"algorithm": "legacy"}],
        )
        self.db.add(run)
        self.db.commit()
        sample = SpotWeldQualitySample(
            run_id=run.id, source_row_index=0, display_id="row-0",
            table_values={"x": 1}, current_label="ok",
        )
        self.db.add(sample)
        self.db.flush()
        revision = SpotWeldLabelRevision(
            project_id=self.project.id, run_id=run.id, sample_id=sample.id,
            author_id=self.owner.id, label="ok", action="submitted",
            review_comment="reviewed", parent_revision_id=None,
        )
        snapshot = SpotWeldLabelSnapshot(
            project_id=self.project.id, run_id=run.id, created_by_id=self.owner.id,
            name="approved", labels=["ok"], label_counts={"ok": 1},
        )
        self.db.add_all([revision, snapshot])
        self.db.commit()
        task = migrate_legacy_quality_run(self.db, run.id)
        self.assertIn(task.mode, {"manual", "automatic"})
        self.assertEqual(task.source_legacy_id, str(run.id))
        self.assertEqual(task.label_snapshot["samples"][0]["id"], str(sample.id))
        self.assertEqual(task.label_snapshot["revisions"][0]["review_comment"], "reviewed")
        self.assertEqual(task.label_snapshot["snapshots"][0]["run_id"], str(run.id))
        checksum = task.label_snapshot["checksum"]
        self.assertEqual(checksum, hashlib.sha256(
            task.label_snapshot["canonical_json"].encode("utf-8")
        ).hexdigest())

    def test_legacy_migration_authorization_and_missing_run(self):
        other = User(username="generic-third", password_hash="hash", role="engineer")
        self.db.add(other)
        run = SpotWeldQualityRun(
            project_id=self.project.id, dataset_artifact_id=uuid.uuid4(),
            created_by_id=self.owner.id, status="completed",
        )
        self.db.add(run)
        self.db.commit()
        app.dependency_overrides[get_current_user] = lambda: other
        denied = self.client.post(
            f"/api/annotation-tasks/{run.id}/migrate",
            headers={"X-Request-ID": str(uuid.uuid4()), "Idempotency-Key": "migration-denied"},
        )
        self.assertEqual(denied.status_code, 404)
        self.assertIsNone(self.db.query(GenericAnnotationTask).filter(
            GenericAnnotationTask.source_legacy_id == str(run.id)
        ).first())
        app.dependency_overrides[get_current_user] = lambda: self.owner
        missing = self.client.post(
            f"/api/annotation-tasks/{uuid.uuid4()}/migrate",
            headers={"X-Request-ID": str(uuid.uuid4()), "Idempotency-Key": "migration-missing"},
        )
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(missing.json()["detail"]["code"], "LEGACY_QUALITY_RUN_NOT_FOUND")

    def test_generic_task_migration_revision_is_present(self):
        migration = Path(__file__).parents[1] / "alembic" / "versions" / "20260903_15_generic_annotation_tasks.py"
        self.assertTrue(migration.exists())
        contents = migration.read_text(encoding="utf-8")
        self.assertIn('revision = "20260903_15"', contents)
        self.assertIn('down_revision = "20260902_15"', contents)
        self.assertIn("uq_generic_annotation_task_source_legacy_id", contents)

    def test_partial_existing_generic_table_is_upgraded_idempotently(self):
        from importlib.util import module_from_spec, spec_from_file_location
        from alembic.migration import MigrationContext
        from alembic.operations import Operations
        from sqlalchemy import inspect, text

        migration_path = Path(__file__).parents[1] / "alembic" / "versions" / "20260903_15_generic_annotation_tasks.py"
        spec = spec_from_file_location("generic_migration", migration_path)
        module = module_from_spec(spec)
        spec.loader.exec_module(module)
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE projects (id CHAR(32) PRIMARY KEY)"))
            connection.execute(text("CREATE TABLE users (id CHAR(32) PRIMARY KEY)"))
            connection.execute(text("CREATE TABLE generic_annotation_tasks (id CHAR(32) PRIMARY KEY, project_id CHAR(32) NOT NULL, owner_id CHAR(32) NOT NULL, mode VARCHAR(16) NOT NULL, status VARCHAR(24) NOT NULL, sample_scope JSON NOT NULL, label_snapshot JSON NOT NULL, created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL)"))
            ctx = MigrationContext.configure(connection)
            module.op = Operations(ctx)
            module.upgrade()
            module.upgrade()
            columns = {column["name"] for column in inspect(connection).get_columns("generic_annotation_tasks")}
            self.assertTrue({"dataset_version_id", "label_schema_id", "source_legacy_id", "idempotency_key"}.issubset(columns))
            unique_names = {item["name"] for item in inspect(connection).get_unique_constraints("generic_annotation_tasks")}
            self.assertIn("uq_generic_annotation_task_source_legacy_id", unique_names)

    def test_downgrade_does_not_drop_preexisting_generic_table(self):
        from importlib.util import module_from_spec, spec_from_file_location
        from alembic.migration import MigrationContext
        from alembic.operations import Operations
        from sqlalchemy import text

        migration_path = Path(__file__).parents[1] / "alembic" / "versions" / "20260903_15_generic_annotation_tasks.py"
        spec = spec_from_file_location("generic_migration_downgrade", migration_path)
        module = module_from_spec(spec)
        spec.loader.exec_module(module)
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE generic_annotation_tasks (id CHAR(32) PRIMARY KEY, project_id CHAR(32) NOT NULL, owner_id CHAR(32) NOT NULL, mode VARCHAR(16) NOT NULL, status VARCHAR(24) NOT NULL, sample_scope JSON NOT NULL, label_snapshot JSON NOT NULL, created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL)"))
            connection.execute(text("INSERT INTO generic_annotation_tasks (id, project_id, owner_id, mode, status, sample_scope, label_snapshot, created_at, updated_at) VALUES ('task-1', 'project-1', 'owner-1', 'manual', 'pending', '{}', '{}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"))
            ctx = MigrationContext.configure(connection)
            module.op = Operations(ctx)
            module.upgrade()
            with self.assertRaises(RuntimeError):
                module.downgrade()
            row = connection.execute(text("SELECT id FROM generic_annotation_tasks WHERE id='task-1'")).first()
            self.assertIsNotNone(row)

    def test_downgrade_refuses_table_drop_after_module_reload(self):
        from importlib.util import module_from_spec, spec_from_file_location
        from alembic.migration import MigrationContext
        from alembic.operations import Operations
        from sqlalchemy import inspect, text

        migration_path = Path(__file__).parents[1] / "alembic" / "versions" / "20260903_15_generic_annotation_tasks.py"
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE projects (id CHAR(32) PRIMARY KEY)"))
            connection.execute(text("CREATE TABLE users (id CHAR(32) PRIMARY KEY)"))
            upgrade_spec = spec_from_file_location("generic_migration_fresh_upgrade", migration_path)
            upgrade_module = module_from_spec(upgrade_spec)
            upgrade_spec.loader.exec_module(upgrade_module)
            upgrade_module.op = Operations(MigrationContext.configure(connection))
            upgrade_module.upgrade()

            downgrade_spec = spec_from_file_location("generic_migration_fresh_downgrade", migration_path)
            downgrade_module = module_from_spec(downgrade_spec)
            downgrade_spec.loader.exec_module(downgrade_module)
            downgrade_module.op = Operations(MigrationContext.configure(connection))
            with self.assertRaises(RuntimeError):
                downgrade_module.downgrade()

            self.assertIn("generic_annotation_tasks", inspect(connection).get_table_names())

    def test_generic_payload_subcontracts_reject_unbounded_or_malformed_json(self):
        headers = {"X-Request-ID": str(uuid.uuid4()), "Idempotency-Key": "bounded-payload"}
        base = {
            "project_id": str(self.project.id),
            "dataset_version_id": str(uuid.uuid4()),
            "label_schema_id": str(uuid.uuid4()),
            "mode": "manual",
        }
        malformed_scope = self.client.post(
            "/api/annotation-tasks", headers=headers,
            json={**base, "sample_scope": {"kind": "unknown"}},
        )
        self.assertEqual(malformed_scope.status_code, 422, malformed_scope.text)
        oversized_snapshot = self.client.post(
            "/api/annotation-tasks",
            headers={**headers, "Idempotency-Key": "oversized-payload"},
            json={**base, "sample_scope": {"kind": "all"}, "label_snapshot": {"payload": "x" * 70000}},
        )
        self.assertEqual(oversized_snapshot.status_code, 422, oversized_snapshot.text)

    def test_production_source_forbidden_reference_gate_is_enforced(self):
        from app.services.genericization_gate import scan_production_sources

        violations = scan_production_sources(Path(__file__).parents[1])
        self.assertEqual(violations, [], violations)

    def test_source_gate_requires_markers_for_legacy_bridge_files(self):
        from app.services.genericization_gate import scan_production_sources

        with tempfile.TemporaryDirectory() as temporary_directory:
            app_root = Path(temporary_directory) / "app"
            legacy_adapter = app_root / "services" / "spot_weld_features.py"
            legacy_adapter.parent.mkdir(parents=True)
            legacy_adapter.write_text("class SpotWeldFeatureEngineering: pass\n", encoding="utf-8")

            violations = scan_production_sources(Path(temporary_directory))

        self.assertEqual(
            violations,
            ["services/spot_weld_features.py: missing LEGACY_ADAPTER_ONLY marker"],
        )

    def test_source_gate_rejects_new_business_dependency_on_legacy_features(self):
        from app.services.genericization_gate import scan_production_sources

        with tempfile.TemporaryDirectory() as temporary_directory:
            app_root = Path(temporary_directory) / "app" / "services"
            app_root.mkdir(parents=True)
            (app_root / "new_annotation_flow.py").write_text(
                "from app.services.spot_weld_features import build_feature_frame\n",
                encoding="utf-8",
            )

            violations = scan_production_sources(Path(temporary_directory))

        self.assertEqual(
            violations,
            ["services/new_annotation_flow.py: forbidden reference spot_weld"],
        )

    def test_source_gate_rejects_a_root_without_production_sources(self):
        from app.services.genericization_gate import scan_production_sources

        with tempfile.TemporaryDirectory() as temporary_directory:
            with self.assertRaisesRegex(ValueError, "app directory"):
                scan_production_sources(Path(temporary_directory))

    def test_model_uniqueness_matches_migration_without_duplicate_unique_indexes(self):
        model_source = (Path(__file__).parents[1] / "app" / "models" / "platform_models.py").read_text(encoding="utf-8")
        migration_root = Path(__file__).parents[1] / "alembic" / "versions"
        migration_source = "\n".join(
            path.read_text(encoding="utf-8")
            for path in migration_root.glob("202609*_generic*task*.py")
        )
        self.assertNotIn("source_legacy_id = Column(String(64), nullable=True, unique=True, index=True)", model_source)
        self.assertNotIn("idempotency_key = Column(String(128), nullable=True, unique=True, index=True)", model_source)
        self.assertIn('sa.UniqueConstraint("source_legacy_id", name="uq_generic_annotation_task_source_legacy_id")', migration_source)
        unique_constraints = {
            constraint.name: tuple(constraint.columns.keys())
            for constraint in GenericAnnotationTask.__table__.constraints
            if isinstance(constraint, __import__("sqlalchemy").UniqueConstraint)
        }
        self.assertEqual(
            unique_constraints["uq_generic_annotation_task_owner_idempotency"],
            ("owner_id", "idempotency_key"),
        )
        self.assertIn("uq_generic_annotation_task_owner_idempotency", migration_source)


if __name__ == "__main__":
    unittest.main()
