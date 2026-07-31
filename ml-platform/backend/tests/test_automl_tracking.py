import tempfile
import threading
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sklearn.dummy import DummyClassifier
from sklearn.linear_model import LogisticRegression
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.auth import create_access_token
from app.api.training import get_automl_dispatcher
from app.database import Base, get_db
from app.main import app
from app.models.experiment import Experiment
from app.models.model_library import ModelLibrary
from app.models.project import Project
from app.models.training import TrainingJob
from app.models.user import User
from app.services.automl_execution import (
    AutoMLCandidate,
    AutoMLDependencies,
    execute_automl_job,
)
from app.services.experiment_tracking import TrackedRun
from app.tasks.celery_app import celery_app
from app.tasks.training_tasks import LocalTrainingDispatcher


class FailingEstimator:
    def fit(self, _features, _target):
        raise ValueError("candidate failed")

    def get_params(self, deep=True):
        return {}

    def set_params(self, **_params):
        return self


class FakeArtifactService:
    def __init__(self, dataset_id, dataset_path):
        self.dataset = SimpleNamespace(id=dataset_id, storage_uri="file:///dataset.csv")
        self.dataset_path = Path(dataset_path)
        self.created = []

    def resolve(self, artifact_id, project_id, expected_type=None):
        if artifact_id != self.dataset.id or expected_type != "dataset":
            raise ValueError("Dataset not found")
        return self.dataset

    @contextmanager
    def materialize(self, artifact_id, project_id, expected_type=None):
        self.resolve(artifact_id, project_id, expected_type)
        yield self.dataset_path

    def create_from_file(self, project_id, source_path, name, artifact_type, metadata=None):
        artifact = SimpleNamespace(
            id=uuid.uuid4(),
            storage_uri=f"file:///models/{name}",
            file_size=Path(source_path).stat().st_size,
            metadata_=metadata or {},
        )
        self.created.append(artifact)
        return artifact

    @staticmethod
    def storage_reference(artifact):
        return artifact.storage_uri


class FakeTracking:
    def __init__(self):
        self.runs = {}
        self.children = []
        self.metrics = {}
        self.tags = {}
        self.terminated = []

    def start_run(self, experiment_id, *, run_name, tags, parent_run_id=None):
        run_id = f"run-{len(self.runs) + 1}"
        run = TrackedRun(
            run_id=run_id,
            experiment_id=str(experiment_id),
            run_name=run_name,
            status="RUNNING",
            start_time=1,
            end_time=None,
            artifact_uri=f"mlflow-artifacts:/{run_id}",
            params={},
            metrics={},
            tags=tags,
            parent_run_id=parent_run_id,
        )
        self.runs[run_id] = run
        if parent_run_id:
            self.children.append(run_id)
        return run


    def log_params(self, run_id, params):
        return None

    def log_metrics(self, run_id, metrics, *, step):
        self.metrics.setdefault(run_id, {}).update(metrics)

    def set_tags(self, run_id, tags):
        self.tags.setdefault(run_id, {}).update(tags)

    def end_run(self, run_id, status):
        self.terminated.append((run_id, status))

    @property
    def parent_run_count(self):
        return len(self.runs) - len(self.children)

    @property
    def child_run_count(self):
        return len(self.children)

    @property
    def failed_child_count(self):
        return sum(1 for run_id, status in self.terminated if run_id in self.children and status == "FAILED")

    @property
    def parent_tags(self):
        return self.tags.get("run-1", {})


class FakeDispatcher:
    def __init__(self):
        self.enqueued = []

    def enqueue(self, job_id):
        self.enqueued.append(str(job_id))
        return "automl-task-1"


class TestAutoMLTracking(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.engine = create_engine(f"sqlite:///{Path(self.temporary.name) / 'automl.db'}")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        self.dataset_id = uuid.uuid4()
        self.dataset_path = Path(self.temporary.name) / "dataset.csv"
        rows = ["current,force,quality"] + [
            f"{index % 8},{index % 5},{int((index % 8) + (index % 5) > 5)}"
            for index in range(150)
        ]
        self.dataset_path.write_text("\n".join(rows), encoding="utf-8")
        with self.Session() as db:
            user = User(username=f"automl-{uuid.uuid4().hex}", password_hash="hash")
            db.add(user)
            db.flush()
            project = Project(name="AutoML", owner_id=user.id)
            db.add(project)
            db.flush()
            experiment = Experiment(
                project_id=project.id,
                created_by=user.id,
                name="AutoML",
                mlflow_experiment_id="automl-experiment",
            )
            db.add(experiment)
            db.commit()
            self.user_id = user.id
            self.project_id = project.id
            self.experiment_id = experiment.id
        self.artifacts = FakeArtifactService(self.dataset_id, self.dataset_path)
        self.tracking = FakeTracking()

    def tearDown(self):
        self.engine.dispose()
        self.temporary.cleanup()

    def create_job(self, *, params=None):
        with self.Session() as db:
            job = TrainingJob(
                project_id=self.project_id,
                user_id=self.user_id,
                experiment_id=self.experiment_id,
                dataset_artifact_id=self.dataset_id,
                name=f"automl-{uuid.uuid4().hex}",
                operator_id="automl",
                params=params or {"target_column": "quality", "task": "classification"},
                status="pending",
            )
            db.add(job)
            db.commit()
            return job.id

    def execute(self, job_id, candidates=None):
        return execute_automl_job(
            job_id,
            candidates=candidates,
            dependencies=AutoMLDependencies(
                session_factory=self.Session,
                artifact_service_factory=lambda _db: self.artifacts,
                tracking_factory=lambda: self.tracking,
                worker_id="worker-1",
                task_id="task-1",
            ),
        )

    def test_partial_failure_tracks_children_and_final_lineage(self):
        job_id = self.create_job()
        candidates = [
            AutoMLCandidate("logistic", lambda: LogisticRegression(max_iter=500), {}),
            AutoMLCandidate("failing", FailingEstimator, {}),
        ]
        result = self.execute(job_id, candidates)

        self.assertEqual(result.status, "completed")
        self.assertEqual(self.tracking.parent_run_count, 1)
        self.assertEqual(self.tracking.child_run_count, 2)
        self.assertEqual(self.tracking.failed_child_count, 1)
        self.assertEqual(self.tracking.parent_tags["platform.best_child_run_id"], "run-2")
        with self.Session() as db:
            job = db.query(TrainingJob).filter(TrainingJob.id == job_id).one()
            model = db.query(ModelLibrary).filter(ModelLibrary.training_job_id == job_id).one()
            self.assertEqual(job.status, "completed")
            self.assertEqual(model.model_artifact_id, job.model_artifact_id)
            self.assertEqual(model.dataset_artifact_id, self.dataset_id)
            self.assertEqual(job.metrics["best_model"]["name"], "logistic")
            self.assertEqual(
                [result["name"] for result in job.metrics["all_results"]],
                ["logistic"],
            )

    def test_all_failed_marks_parent_and_job_failed(self):
        job_id = self.create_job()
        result = self.execute(job_id, [
            AutoMLCandidate("failure-a", FailingEstimator, {}),
            AutoMLCandidate("failure-b", FailingEstimator, {}),
        ])

        self.assertEqual(result.status, "failed")
        with self.Session() as db:
            job = db.query(TrainingJob).filter(TrainingJob.id == job_id).one()
            self.assertEqual(job.error_code, "AUTOML_ALL_CANDIDATES_FAILED")
        self.assertIn(("run-1", "FAILED"), self.tracking.terminated)

    def test_tied_scores_select_first_candidate_deterministically(self):
        job_id = self.create_job()
        result = self.execute(job_id, [
            AutoMLCandidate("first", lambda: DummyClassifier(strategy="most_frequent"), {}),
            AutoMLCandidate("second", lambda: DummyClassifier(strategy="most_frequent"), {}),
        ])
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.best_candidate, "first")
        self.assertEqual(self.tracking.parent_tags["platform.best_child_run_id"], "run-2")

    def test_persisted_candidate_subset_is_used_when_no_override_is_supplied(self):
        job_id = self.create_job(params={
            "target_column": "quality",
            "task": "classification",
            "candidate_ids": ["logistic_regression"],
        })

        result = self.execute(job_id)

        self.assertEqual(result.status, "completed")
        with self.Session() as db:
            job = db.query(TrainingJob).filter(TrainingJob.id == job_id).one()
            self.assertEqual(
                [item["name"] for item in job.metrics["all_results"]],
                ["logistic_regression"],
            )

    def test_celery_automl_task_is_registered(self):
        self.assertIn("ml_platform.execute_automl", celery_app.tasks)


class TestAutoMLAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(cls.engine)
        cls.Session = sessionmaker(bind=cls.engine)
        cls.dataset_id = uuid.uuid4()
        with cls.Session() as db:
            user = User(username="automl-api", password_hash="hash")
            db.add(user)
            db.flush()
            project = Project(name="AutoML API", owner_id=user.id)
            db.add(project)
            db.flush()
            experiment = Experiment(
                project_id=project.id,
                created_by=user.id,
                name="AutoML API",
                mlflow_experiment_id="automl-api-experiment",
            )
            db.add(experiment)
            db.commit()
            cls.user_id = user.id
            cls.project_id = project.id
            cls.experiment_id = experiment.id

        def override_db():
            db = cls.Session()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_db
        cls.artifacts = FakeArtifactService(cls.dataset_id, Path(__file__))
        cls.dispatcher = FakeDispatcher()
        app.state.artifact_service_factory = lambda _db: cls.artifacts
        app.state.automl_dispatcher = cls.dispatcher
        cls.client = TestClient(app)
        token = create_access_token({"sub": str(cls.user_id)})
        cls.headers = {"Authorization": f"Bearer {token}"}

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.pop(get_db, None)
        for name in ("artifact_service_factory", "automl_dispatcher"):
            if hasattr(app.state, name):
                delattr(app.state, name)
        cls.engine.dispose()

    def setUp(self):
        self.dispatcher.enqueued.clear()
        app.state.automl_dispatcher = self.dispatcher

    def test_dataset_path_is_rejected(self):
        response = self.client.post("/api/training/automl/run", json={
            "project_id": str(self.project_id),
            "experiment_id": str(self.experiment_id),
            "dataset_path": "/tmp/untrusted.csv",
            "target_column": "quality",
        }, headers=self.headers)
        self.assertEqual(response.status_code, 422)

    def test_artifact_automl_job_is_queued(self):
        response = self.client.post("/api/training/automl/run", json={
            "project_id": str(self.project_id),
            "experiment_id": str(self.experiment_id),
            "dataset_artifact_id": str(self.dataset_id),
            "target_column": "quality",
            "task": "classification",
        }, headers=self.headers)
        self.assertEqual(response.status_code, 202, response.text)
        self.assertEqual(response.json()["status"], "queued")
        self.assertEqual(self.dispatcher.enqueued, [response.json()["job_id"]])

    def test_unknown_candidate_id_is_rejected_before_queueing(self):
        response = self.client.post("/api/training/automl/run", json={
            "project_id": str(self.project_id),
            "experiment_id": str(self.experiment_id),
            "dataset_artifact_id": str(self.dataset_id),
            "target_column": "quality",
            "task": "classification",
            "candidate_ids": ["does_not_exist"],
        }, headers=self.headers)

        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(response.json()["detail"]["code"], "AUTOML_CONFIG_INVALID")
        self.assertEqual(self.dispatcher.enqueued, [])

    def test_duplicate_candidate_ids_are_rejected_before_queueing(self):
        response = self.client.post("/api/training/automl/run", json={
            "project_id": str(self.project_id),
            "experiment_id": str(self.experiment_id),
            "dataset_artifact_id": str(self.dataset_id),
            "target_column": "quality",
            "task": "classification",
            "candidate_ids": ["random_forest", "random_forest"],
        }, headers=self.headers)

        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(response.json()["detail"]["code"], "AUTOML_CONFIG_INVALID")
        self.assertEqual(self.dispatcher.enqueued, [])

    def test_candidate_ids_are_persisted_in_request_order(self):
        response = self.client.post("/api/training/automl/run", json={
            "project_id": str(self.project_id),
            "experiment_id": str(self.experiment_id),
            "dataset_artifact_id": str(self.dataset_id),
            "target_column": "quality",
            "task": "classification",
            "candidate_ids": ["logistic_regression", "random_forest"],
        }, headers=self.headers)

        self.assertEqual(response.status_code, 202, response.text)
        with self.Session() as db:
            job = db.query(TrainingJob).filter(
                TrainingJob.id == uuid.UUID(response.json()["job_id"])
            ).one()
            self.assertEqual(
                job.params["candidate_ids"],
                ["logistic_regression", "random_forest"],
            )

    def test_deferred_local_dispatch_starts_after_queue_commit(self):
        class DeferredDispatcher(FakeDispatcher):
            def __init__(self):
                super().__init__()
                self.observed_status = None

            def start(self, task_id):
                with TestAutoMLAPI.Session() as db:
                    job = db.query(TrainingJob).filter(
                        TrainingJob.id == uuid.UUID(self.enqueued[0]),
                    ).one()
                    self.observed_status = (job.status, job.task_id, task_id)

        dispatcher = DeferredDispatcher()
        app.state.automl_dispatcher = dispatcher
        try:
            response = self.client.post("/api/training/automl/run", json={
                "project_id": str(self.project_id),
                "experiment_id": str(self.experiment_id),
                "dataset_artifact_id": str(self.dataset_id),
                "target_column": "quality",
            }, headers=self.headers)
        finally:
            app.state.automl_dispatcher = self.dispatcher

        self.assertEqual(response.status_code, 202, response.text)
        self.assertEqual(
            dispatcher.observed_status,
            ("queued", "automl-task-1", "automl-task-1"),
        )

    def test_automl_budget_is_accepted_and_persisted(self):
        response = self.client.post("/api/training/automl/run", json={
            "project_id": str(self.project_id),
            "experiment_id": str(self.experiment_id),
            "dataset_artifact_id": str(self.dataset_id),
            "target_column": "quality",
            "time_budget": 60,
        }, headers=self.headers)

        self.assertEqual(response.status_code, 202, response.text)
        with self.Session() as db:
            job = db.query(TrainingJob).filter(
                TrainingJob.id == uuid.UUID(response.json()["job_id"])
            ).one()
            self.assertEqual(job.params["time_budget"], 60)


class TestAutoMLDispatcherSelection(unittest.TestCase):
    def test_local_task_backend_uses_local_dispatcher(self):
        request = SimpleNamespace(
            app=SimpleNamespace(
                state=SimpleNamespace(
                    settings=SimpleNamespace(task_backend="local"),
                ),
            ),
        )

        dispatcher = get_automl_dispatcher(request)

        self.assertEqual(type(dispatcher).__name__, "LocalTrainingDispatcher")

    def test_missing_app_settings_uses_default_local_dispatcher(self):
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))

        dispatcher = get_automl_dispatcher(request)

        self.assertEqual(type(dispatcher).__name__, "LocalTrainingDispatcher")


class TestLocalTrainingDispatcher(unittest.TestCase):
    def test_execution_waits_until_task_id_is_persisted(self):
        started = threading.Event()
        executed = []

        def execute(job_id, task_id):
            executed.append((job_id, task_id))
            started.set()

        dispatcher = LocalTrainingDispatcher(execute)
        task_id = dispatcher.enqueue("job-1")

        self.assertFalse(started.wait(0.1))
        dispatcher.start(task_id)
        self.assertTrue(started.wait(1))
        self.assertEqual(executed, [("job-1", task_id)])


if __name__ == "__main__":
    unittest.main()
