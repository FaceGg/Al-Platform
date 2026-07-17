"""Strict training submission, checkpoint, stop, and resume API tests."""

import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.auth import create_access_token
from app.database import Base, get_db
from app.main import app
from app.models.experiment import Experiment
from app.models.project import Project
from app.models.training import TrainingJob
from app.models.user import User
from app.services.experiment_tracking import TrackedArtifact
from app.services.iterative_training import IterativeTrainer, TrainingConfig


class FakeArtifactService:
    def __init__(self, dataset_id):
        self.dataset = SimpleNamespace(id=dataset_id, storage_uri="file:///dataset.csv")

    def resolve(self, artifact_id, project_id, expected_type=None):
        if artifact_id != self.dataset.id or expected_type != "dataset":
            raise ValueError("Dataset not found")
        return self.dataset

    @staticmethod
    def storage_reference(artifact):
        return artifact.storage_uri


class FakeTracking:
    def __init__(self):
        self.payloads = {}

    def list_artifacts(self, run_id, path=None):
        prefix = f"{path.rstrip('/')}/" if path else ""
        return tuple(
            TrackedArtifact(name, False, len(payload))
            for (stored_run, name), payload in self.payloads.items()
            if stored_run == run_id and name.startswith(prefix)
        )

    def download_artifact(self, run_id, path, destination):
        payload = self.payloads[(run_id, path)]
        target = Path(destination) / Path(path).name
        target.write_bytes(payload)
        return target


class FakeTrainingDispatcher:
    def __init__(self):
        self.enqueued = []
        self.cancelled = []

    def enqueue(self, job_id):
        self.enqueued.append(str(job_id))
        return f"task-{len(self.enqueued)}"

    def cancel(self, task_id):
        self.cancelled.append(task_id)


class TestTrainingAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        cls.Session = sessionmaker(bind=cls.engine, autocommit=False, autoflush=False)
        Base.metadata.create_all(cls.engine)
        cls.dataset_id = uuid.uuid4()
        with cls.Session() as db:
            owner = User(username="training-owner", password_hash="hash")
            other = User(username="training-other", password_hash="hash")
            db.add_all([owner, other])
            db.flush()
            cls.owner_id = owner.id
            cls.other_id = other.id
            project = Project(name="Training project", owner_id=owner.id)
            db.add(project)
            db.flush()
            cls.project_id = project.id
            experiment = Experiment(
                project_id=project.id,
                created_by=owner.id,
                name="Training experiment",
                mlflow_experiment_id="experiment-1",
            )
            db.add(experiment)
            db.commit()
            cls.experiment_id = experiment.id

        def override_db():
            db = cls.Session()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_db
        cls.artifacts = FakeArtifactService(cls.dataset_id)
        cls.tracking = FakeTracking()
        cls.dispatcher = FakeTrainingDispatcher()
        app.state.artifact_service_factory = lambda _db: cls.artifacts
        app.state.experiment_tracking = cls.tracking
        app.state.training_dispatcher = cls.dispatcher
        cls.client = TestClient(app)
        cls.owner_headers = cls._headers(cls.owner_id)
        cls.other_headers = cls._headers(cls.other_id)

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.pop(get_db, None)
        for name in (
            "artifact_service_factory",
            "experiment_tracking",
            "training_dispatcher",
        ):
            if hasattr(app.state, name):
                delattr(app.state, name)
        cls.engine.dispose()

    def setUp(self):
        self.dispatcher.enqueued.clear()
        self.dispatcher.cancelled.clear()
        self.tracking.payloads.clear()

    @staticmethod
    def _headers(user_id):
        token = create_access_token({"sub": str(user_id)})
        return {"Authorization": f"Bearer {token}"}

    def _create_source_job(self, status="running", checkpoint=True):
        with self.Session() as db:
            job = TrainingJob(
                project_id=self.project_id,
                user_id=self.owner_id,
                experiment_id=self.experiment_id,
                dataset_artifact_id=self.dataset_id,
                name=f"source-{uuid.uuid4().hex}",
                operator_id="incremental_sgd",
                params={"target_column": "quality", "task": "classification"},
                status=status,
                total_epochs=3,
                monitor_name="val_accuracy",
                monitor_mode="max",
                early_stopping_patience=2,
                early_stopping_min_delta=0.0,
                restore_best=True,
                mlflow_run_id=f"run-{uuid.uuid4().hex}",
                task_id="active-task",
            )
            db.add(job)
            db.commit()
            job_id = job.id
            run_id = job.mlflow_run_id
        if checkpoint:
            frame = pd.DataFrame({
                "current": list(range(20)),
                "force": [index % 3 for index in range(20)],
                "quality": [index % 2 for index in range(20)],
            })
            envelopes = []
            IterativeTrainer().fit(
                frame,
                target_column="quality",
                config=TrainingConfig(
                    task="classification",
                    total_epochs=1,
                    monitor="val_accuracy",
                    mode="max",
                    patience=2,
                ),
                checkpoint_callback=envelopes.append,
                dataset_artifact_id=str(self.dataset_id),
                source_job_id=str(job_id),
                source_run_id=run_id,
            )
            path = "checkpoints/latest.joblib"
            uri = f"mlflow-artifacts:/{run_id}/{path}"
            self.tracking.payloads[(run_id, path)] = envelopes[-1].payload
            with self.Session() as db:
                job = db.query(TrainingJob).filter(TrainingJob.id == job_id).one()
                job.latest_checkpoint_uri = uri
                db.commit()
        return job_id

    def test_start_training_requires_owned_experiment_and_queues_job(self):
        response = self.client.post("/api/training/run", json={
            "project_id": str(self.project_id),
            "experiment_id": str(self.experiment_id),
            "dataset_artifact_id": str(self.dataset_id),
            "name": "new-training",
            "target_column": "quality",
            "task": "classification",
            "total_epochs": 3,
        }, headers=self.owner_headers)

        self.assertEqual(response.status_code, 202, response.text)
        self.assertEqual(response.json()["status"], "queued")
        self.assertEqual(self.dispatcher.enqueued, [response.json()["job_id"]])
        with self.Session() as db:
            job = db.query(TrainingJob).filter(
                TrainingJob.id == uuid.UUID(response.json()["job_id"]),
            ).one()
            self.assertEqual(job.experiment_id, self.experiment_id)
            self.assertEqual(job.task_id, "task-1")

    def test_start_training_hides_other_users_experiment(self):
        response = self.client.post("/api/training/run", json={
            "project_id": str(self.project_id),
            "experiment_id": str(self.experiment_id),
            "dataset_artifact_id": str(self.dataset_id),
            "target_column": "quality",
        }, headers=self.other_headers)
        self.assertEqual(response.status_code, 404)

    def test_checkpoint_list_is_job_scoped_and_exact(self):
        job_id = self._create_source_job()
        response = self.client.get(
            f"/api/training/jobs/{job_id}/checkpoints",
            headers=self.owner_headers,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [item["path"] for item in response.json()["checkpoints"]],
            ["checkpoints/latest.joblib"],
        )
        hidden = self.client.get(
            f"/api/training/jobs/{job_id}/checkpoints",
            headers=self.other_headers,
        )
        self.assertEqual(hidden.status_code, 404)

    def test_stop_only_active_job_and_revokes_task(self):
        job_id = self._create_source_job(status="running", checkpoint=False)
        stopped = self.client.post(
            f"/api/training/jobs/{job_id}/stop",
            headers=self.owner_headers,
        )
        self.assertEqual(stopped.status_code, 200)
        self.assertEqual(stopped.json()["status"], "cancel_requested")
        self.assertEqual(self.dispatcher.cancelled, ["active-task"])

        again = self.client.post(
            f"/api/training/jobs/{job_id}/stop",
            headers=self.owner_headers,
        )
        self.assertEqual(again.status_code, 409)
        self.assertEqual(again.json()["detail"]["code"], "TRAINING_NOT_ACTIVE")

    def test_resume_validates_checkpoint_and_creates_lineage(self):
        source_id = self._create_source_job(status="cancelled")
        response = self.client.post(
            f"/api/training/jobs/{source_id}/resume",
            json={},
            headers=self.owner_headers,
        )

        self.assertEqual(response.status_code, 202, response.text)
        resumed_id = uuid.UUID(response.json()["job_id"])
        with self.Session() as db:
            resumed = db.query(TrainingJob).filter(TrainingJob.id == resumed_id).one()
            source = db.query(TrainingJob).filter(TrainingJob.id == source_id).one()
            self.assertEqual(resumed.resumed_from_job_id, source.id)
            self.assertEqual(resumed.resumed_from_run_id, source.mlflow_run_id)
            self.assertEqual(resumed.resume_checkpoint_uri, source.latest_checkpoint_uri)
            self.assertEqual(resumed.dataset_artifact_id, source.dataset_artifact_id)
            self.assertEqual(resumed.task_id, "task-1")

    def test_resume_rejects_incompatible_checkpoint(self):
        source_id = self._create_source_job(status="failed", checkpoint=False)
        run_id = None
        with self.Session() as db:
            source = db.query(TrainingJob).filter(TrainingJob.id == source_id).one()
            run_id = source.mlflow_run_id
            source.latest_checkpoint_uri = f"mlflow-artifacts:/{run_id}/checkpoints/latest.joblib"
            db.commit()
        self.tracking.payloads[(run_id, "checkpoints/latest.joblib")] = b"invalid"

        response = self.client.post(
            f"/api/training/jobs/{source_id}/resume",
            json={},
            headers=self.owner_headers,
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"]["code"], "CHECKPOINT_INCOMPATIBLE")


if __name__ == "__main__":
    unittest.main()
