import unittest
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.auth import create_access_token
from app.database import Base, get_db
from app.main import app
from app.models.experiment import Experiment
from app.models.project import Project
from app.models.access import AuditEvent, ProjectMember
from app.models.user import User
from app.services.experiment_tracking import (
    TrackedMetric,
    TrackedRun,
    TrackingUnavailable,
)


class FakeExperimentTracking:
    def __init__(self):
        self.experiment_names = {}
        self.runs = {}
        self.histories = {}
        self.fail_ensure = False

    def ensure_experiment(self, name):
        if self.fail_ensure:
            raise TrackingUnavailable("offline")
        return self.experiment_names.setdefault(name, str(len(self.experiment_names) + 1))

    def add_run(
        self,
        experiment_id,
        *,
        params=None,
        metrics=None,
        histories=None,
        status="FINISHED",
    ):
        run_id = f"run-{len(self.runs) + 1}"
        run = TrackedRun(
            run_id=run_id,
            experiment_id=str(experiment_id),
            run_name=run_id,
            status=status,
            start_time=100 + len(self.runs),
            end_time=200 + len(self.runs),
            artifact_uri=f"s3://artifacts/{run_id}",
            params=params or {},
            metrics=metrics or {},
            tags={},
            parent_run_id=None,
        )
        self.runs[run_id] = run
        for key, values in (histories or {}).items():
            self.histories[(run_id, key)] = tuple(
                TrackedMetric(key=key, value=value, timestamp=1000 + step, step=step)
                for step, value in enumerate(values, start=1)
            )
        return run

    def search_runs(self, experiment_ids, *, filter_string="", max_results=1000):
        selected = {str(item) for item in experiment_ids}
        return tuple(
            run for run in self.runs.values()
            if run.experiment_id in selected
        )[:max_results]

    def compare_runs(self, run_ids):
        return tuple(self.runs[run_id] for run_id in run_ids)

    def get_metric_history(self, run_id, key):
        return self.histories.get((run_id, key), ())


class TestExperimentAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        cls.Session = sessionmaker(bind=cls.engine, autocommit=False, autoflush=False)
        Base.metadata.create_all(cls.engine)

        with cls.Session() as db:
            cls.owner = User(username="experiment-owner", password_hash="hash")
            cls.editor = User(username="experiment-editor", password_hash="hash")
            cls.operator = User(username="experiment-operator", password_hash="hash")
            cls.viewer = User(username="experiment-viewer", password_hash="hash")
            cls.other = User(username="experiment-other", password_hash="hash")
            db.add_all([cls.owner, cls.editor, cls.operator, cls.viewer, cls.other])
            db.flush()
            cls.owner_id = cls.owner.id
            cls.editor_id = cls.editor.id
            cls.operator_id = cls.operator.id
            cls.viewer_id = cls.viewer.id
            cls.other_id = cls.other.id
            project = Project(name="Weld project", owner_id=cls.owner_id)
            db.add(project)
            db.flush()
            db.add_all([
                ProjectMember(
                    project_id=project.id,
                    user_id=user.id,
                    role=role,
                    created_by=cls.owner_id,
                )
                for role, user in (
                    ("editor", cls.editor),
                    ("operator", cls.operator),
                    ("viewer", cls.viewer),
                )
            ])
            db.commit()
            cls.project_id = project.id

        def override_db():
            db = cls.Session()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_db
        cls.override_db = override_db
        cls.tracking = FakeExperimentTracking()
        app.state.experiment_tracking = cls.tracking
        cls.client = TestClient(app)
        cls.owner_headers = cls._headers(cls.owner_id)
        cls.editor_headers = cls._headers(cls.editor_id)
        cls.operator_headers = cls._headers(cls.operator_id)
        cls.viewer_headers = cls._headers(cls.viewer_id)
        cls.other_headers = cls._headers(cls.other_id)

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.pop(get_db, None)
        if hasattr(app.state, "experiment_tracking"):
            del app.state.experiment_tracking
        cls.engine.dispose()

    def setUp(self):
        self.tracking.fail_ensure = False

    @staticmethod
    def _headers(user_id):
        token = create_access_token({"sub": str(user_id)})
        return {"Authorization": f"Bearer {token}"}

    def _create_experiment(self, name=None):
        response = self.client.post(
            "/api/experiments",
            json={
                "project_id": str(self.project_id),
                "name": name or f"Weld baseline {uuid.uuid4().hex}",
                "description": "Compare incremental models",
            },
            headers=self.owner_headers,
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def test_create_list_detail_and_owner_isolation(self):
        created = self._create_experiment()
        self.assertTrue(created["mlflow_experiment_id"])

        listed = self.client.get(
            "/api/experiments",
            params={"project_id": str(self.project_id)},
            headers=self.owner_headers,
        )
        self.assertEqual(listed.status_code, 200)
        self.assertIn(created["id"], {item["id"] for item in listed.json()["items"]})

        detail = self.client.get(
            f"/api/experiments/{created['id']}",
            headers=self.owner_headers,
        )
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["run_count"], 0)
        hidden = self.client.get(
            f"/api/experiments/{created['id']}",
            headers=self.other_headers,
        )
        self.assertEqual(hidden.status_code, 404)

    def test_duplicate_name_is_rejected_before_creating_tracking_state(self):
        name = f"Duplicate {uuid.uuid4().hex}"
        self._create_experiment(name)
        tracking_count = len(self.tracking.experiment_names)

        duplicate = self.client.post(
            "/api/experiments",
            json={"project_id": str(self.project_id), "name": name},
            headers=self.owner_headers,
        )
        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(duplicate.json()["detail"]["code"], "EXPERIMENT_NAME_CONFLICT")
        self.assertEqual(len(self.tracking.experiment_names), tracking_count)

    def test_project_roles_create_read_and_audit_experiments(self):
        created = self.client.post(
            "/api/experiments",
            json={
                "project_id": str(self.project_id),
                "name": f"Editor experiment {uuid.uuid4().hex}",
            },
            headers=self.editor_headers,
        )
        self.assertEqual(created.status_code, 201, created.text)

        listed = self.client.get(
            "/api/experiments",
            params={"project_id": str(self.project_id)},
            headers=self.viewer_headers,
        )
        detail = self.client.get(
            f"/api/experiments/{created.json()['id']}", headers=self.viewer_headers,
        )
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertEqual(detail.status_code, 200, detail.text)

        denied = self.client.post(
            "/api/experiments",
            json={
                "project_id": str(self.project_id),
                "name": f"Operator denied {uuid.uuid4().hex}",
            },
            headers=self.operator_headers,
        )
        self.assertEqual(denied.status_code, 403, denied.text)
        with self.Session() as db:
            actions = {
                (event.action, event.result)
                for event in db.query(AuditEvent).filter(AuditEvent.project_id == self.project_id)
            }
        self.assertIn(("experiment.create", "success"), actions)
        self.assertIn(("experiment.create", "denied"), actions)

    def test_tracking_failure_rolls_back_platform_record(self):
        self.tracking.fail_ensure = True
        name = f"Offline {uuid.uuid4().hex}"

        response = self.client.post(
            "/api/experiments",
            json={"project_id": str(self.project_id), "name": name},
            headers=self.owner_headers,
        )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["detail"]["code"], "TRACKING_UNAVAILABLE")
        with self.Session() as db:
            self.assertIsNone(db.query(Experiment).filter(Experiment.name == name).first())

    def test_unauthorized_detail_is_hidden_before_tracking_configuration(self):
        created = self._create_experiment()
        tracking = app.state.experiment_tracking
        del app.state.experiment_tracking
        try:
            response = self.client.get(
                f"/api/experiments/{created['id']}",
                headers=self.other_headers,
            )
        finally:
            app.state.experiment_tracking = tracking
        self.assertEqual(response.status_code, 404)

    def test_database_failure_after_tracking_creation_is_structured(self):
        name = f"Database failure {uuid.uuid4().hex}"
        tracking_count = len(self.tracking.experiment_names)

        def failing_db():
            db = self.Session()
            original_add = db.add
            original_commit = db.commit
            fail_commit = False

            def add(instance, *args, **kwargs):
                nonlocal fail_commit
                original_add(instance, *args, **kwargs)
                if isinstance(instance, Experiment):
                    fail_commit = True

            def commit():
                if fail_commit:
                    raise SQLAlchemyError("database unavailable")
                original_commit()

            db.add = add
            db.commit = commit
            try:
                yield db
            finally:
                db.rollback()
                db.close()

        app.dependency_overrides[get_db] = failing_db
        try:
            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.post(
                    "/api/experiments",
                    json={"project_id": str(self.project_id), "name": name},
                    headers=self.owner_headers,
                )
        finally:
            app.dependency_overrides[get_db] = type(self).override_db

        self.assertEqual(response.status_code, 500)
        self.assertIn("EXPERIMENT_PERSISTENCE_FAILED", response.text)
        self.assertEqual(len(self.tracking.experiment_names), tracking_count + 1)
        with self.Session() as db:
            self.assertIsNone(db.query(Experiment).filter(Experiment.name == name).first())

    def test_run_listing_is_paginated_and_scoped_to_experiment(self):
        created = self._create_experiment()
        experiment_id = created["mlflow_experiment_id"]
        runs = [self.tracking.add_run(experiment_id) for _ in range(3)]
        other = self._create_experiment()
        self.tracking.add_run(other["mlflow_experiment_id"])

        response = self.client.get(
            f"/api/experiments/{created['id']}/runs",
            params={"offset": 1, "limit": 2},
            headers=self.owner_headers,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total"], 3)
        self.assertEqual(
            [item["run_id"] for item in response.json()["items"]],
            [runs[1].run_id, runs[2].run_id],
        )

    def test_compare_returns_deterministic_missing_aware_matrix(self):
        created = self._create_experiment()
        experiment_id = created["mlflow_experiment_id"]
        first = self.tracking.add_run(
            experiment_id,
            params={"epochs": "10", "solver": "sgd"},
            metrics={"accuracy": 0.91},
            histories={"accuracy": [0.7, 0.91]},
        )
        second = self.tracking.add_run(
            experiment_id,
            params={"epochs": "20"},
            metrics={"loss": 0.2},
            histories={"loss": [0.4, 0.2]},
            status="FAILED",
        )

        response = self.client.post(
            f"/api/experiments/{created['id']}/compare",
            json={"run_ids": [second.run_id, first.run_id]},
            headers=self.owner_headers,
        )
        self.assertEqual(response.status_code, 200, response.text)
        matrix = response.json()
        self.assertEqual(matrix["run_ids"], [second.run_id, first.run_id])
        self.assertEqual(matrix["param_names"], ["epochs", "solver"])
        self.assertEqual(matrix["metric_names"], ["accuracy", "loss"])
        self.assertIsNone(matrix["runs"][0]["params"]["solver"])
        self.assertEqual(matrix["runs"][0]["missing"]["params"], ["solver"])
        self.assertEqual(matrix["runs"][1]["missing"]["metrics"], ["loss"])
        self.assertEqual(matrix["runs"][1]["metric_history"]["accuracy"][-1]["step"], 2)

    def test_compare_requires_two_to_ten_runs(self):
        created = self._create_experiment()
        run = self.tracking.add_run(created["mlflow_experiment_id"])
        too_few = self.client.post(
            f"/api/experiments/{created['id']}/compare",
            json={"run_ids": [run.run_id]},
            headers=self.owner_headers,
        )
        too_many = self.client.post(
            f"/api/experiments/{created['id']}/compare",
            json={"run_ids": [f"run-{index}" for index in range(11)]},
            headers=self.owner_headers,
        )
        self.assertEqual(too_few.status_code, 422)
        self.assertEqual(too_many.status_code, 422)


if __name__ == "__main__":
    unittest.main()
