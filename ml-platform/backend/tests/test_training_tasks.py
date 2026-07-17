import tempfile
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.experiment import Experiment
from app.models.model_library import ModelLibrary
from app.models.project import Project
from app.models.training import TrainingJob
from app.models.user import User
from app.services.experiment_tracking import TrackedRun, TrackingUnavailable
from app.services.training_execution import execute_training_job
from app.tasks.celery_app import celery_app


class FakeArtifactService:
    def __init__(self, dataset_path, dataset_id):
        self.dataset = SimpleNamespace(
            id=dataset_id,
            storage_uri="file:///datasets/weld.csv",
            storage_path=str(dataset_path),
        )
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
            storage_path=str(source_path),
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
        self.params = {}
        self.metrics = []
        self.artifacts = []
        self.payloads = {}
        self.tags = {}
        self.terminated = []
        self.fail_start = False
        self.on_metric = None

    def start_run(self, experiment_id, *, run_name, tags, parent_run_id=None):
        if self.fail_start:
            raise TrackingUnavailable("offline")
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
        return run

    def log_params(self, run_id, params):
        self.params[run_id] = dict(params)

    def log_metrics(self, run_id, metrics, *, step):
        self.metrics.append((run_id, step, dict(metrics)))
        if self.on_metric is not None:
            self.on_metric(step)

    def log_artifact(self, run_id, local_path, artifact_path=None):
        self.artifacts.append((
            run_id,
            artifact_path,
            Path(local_path).name,
            Path(local_path).read_bytes(),
        ))
        relative = f"{artifact_path.rstrip('/')}/{Path(local_path).name}"
        self.payloads[(run_id, relative)] = Path(local_path).read_bytes()

    def download_artifact(self, run_id, path, destination):
        target = Path(destination) / Path(path).name
        target.write_bytes(self.payloads[(run_id, path)])
        return target

    def set_tags(self, run_id, tags):
        self.tags.setdefault(run_id, {}).update(tags)

    def end_run(self, run_id, status):
        self.terminated.append((run_id, status))

    def metric_steps(self, name):
        return [step for _run_id, step, values in self.metrics if name in values]


class TestTrainingExecution(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.engine = create_engine(f"sqlite:///{Path(self.temporary.name) / 'training.db'}")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        self.dataset_id = uuid.uuid4()
        self.dataset_path = Path(self.temporary.name) / "weld.csv"
        rows = ["current,force,quality"] + [
            f"{7 + index % 6},{2 + index % 5},{int((index % 6) + (index % 5) > 4)}"
            for index in range(120)
        ]
        self.dataset_path.write_text("\n".join(rows), encoding="utf-8")
        with self.Session() as db:
            user = User(username=f"trainer-{uuid.uuid4().hex}", password_hash="hash")
            db.add(user)
            db.flush()
            project = Project(name="Training", owner_id=user.id)
            db.add(project)
            db.flush()
            experiment = Experiment(
                project_id=project.id,
                created_by=user.id,
                name="Baseline",
                mlflow_experiment_id="experiment-1",
            )
            db.add(experiment)
            db.flush()
            job = TrainingJob(
                project_id=project.id,
                user_id=user.id,
                experiment_id=experiment.id,
                dataset_artifact_id=self.dataset_id,
                name="incremental-classifier",
                operator_id="incremental_sgd",
                params={"target_column": "quality", "task": "classification"},
                status="pending",
                total_epochs=3,
                monitor_name="val_accuracy",
                monitor_mode="max",
                early_stopping_patience=10,
                early_stopping_min_delta=0.0,
                restore_best=True,
            )
            db.add(job)
            db.commit()
            self.job_id = job.id
        self.artifacts = FakeArtifactService(self.dataset_path, self.dataset_id)
        self.tracking = FakeTracking()

    def tearDown(self):
        self.engine.dispose()
        self.temporary.cleanup()

    def execute(self):
        return execute_training_job(
            self.job_id,
            session_factory=self.Session,
            artifact_service_factory=lambda _db: self.artifacts,
            tracking_factory=lambda: self.tracking,
            worker_id="worker-1",
            task_id="task-1",
            checkpoint_interval=2,
        )

    def test_claimed_job_tracks_metrics_checkpoints_and_final_lineage(self):
        outcome = self.execute()
        with self.Session() as db:
            job = db.query(TrainingJob).filter(TrainingJob.id == self.job_id).one()
            model = db.query(ModelLibrary).filter(
                ModelLibrary.training_job_id == self.job_id,
            ).one()
            self.assertEqual(outcome.status, "completed")
            self.assertEqual(job.status, "completed")
            self.assertEqual(job.mlflow_run_id, "run-1")
            self.assertEqual(job.current_epoch, 3)
            self.assertIsNotNone(job.heartbeat_at)
            self.assertTrue(job.latest_checkpoint_uri.startswith("mlflow-artifacts:/"))
            self.assertTrue(job.best_checkpoint_uri.startswith("mlflow-artifacts:/"))
            self.assertIsNotNone(job.model_artifact_id)
            self.assertEqual(model.model_artifact_id, job.model_artifact_id)
            self.assertEqual(model.dataset_artifact_id, self.dataset_id)
        steps = self.tracking.metric_steps("val_accuracy")
        self.assertEqual(steps, sorted(steps))
        self.assertEqual(steps, [1, 2, 3])
        self.assertEqual(self.tracking.params["run-1"]["total_epochs"], 3)
        self.assertEqual(self.tracking.params["run-1"]["monitor"], "val_accuracy")
        names = {item[2] for item in self.tracking.artifacts}
        self.assertTrue({"latest.joblib", "best.joblib"}.issubset(names))
        self.assertEqual(self.tracking.terminated, [("run-1", "FINISHED")])

    def test_duplicate_delivery_is_skipped(self):
        first = self.execute()
        second = execute_training_job(
            self.job_id,
            session_factory=self.Session,
            artifact_service_factory=lambda _db: self.artifacts,
            tracking_factory=lambda: self.tracking,
            worker_id="worker-2",
            task_id="task-2",
        )

        self.assertEqual(first.status, "completed")
        self.assertEqual(second.status, "skipped")
        self.assertEqual(len(self.tracking.runs), 1)

    def test_resumed_job_continues_from_checkpoint_epoch(self):
        self.assertEqual(self.execute().status, "completed")
        with self.Session() as db:
            source = db.query(TrainingJob).filter(TrainingJob.id == self.job_id).one()
            resumed = TrainingJob(
                project_id=source.project_id,
                user_id=source.user_id,
                experiment_id=source.experiment_id,
                dataset_artifact_id=source.dataset_artifact_id,
                name="resumed-classifier",
                operator_id=source.operator_id,
                params=dict(source.params),
                status="pending",
                total_epochs=5,
                monitor_name=source.monitor_name,
                monitor_mode=source.monitor_mode,
                early_stopping_patience=source.early_stopping_patience,
                early_stopping_min_delta=source.early_stopping_min_delta,
                restore_best=source.restore_best,
                resumed_from_job_id=source.id,
                resumed_from_run_id=source.mlflow_run_id,
                resume_checkpoint_uri=source.latest_checkpoint_uri,
            )
            db.add(resumed)
            db.commit()
            resumed_id = resumed.id

        outcome = execute_training_job(
            resumed_id,
            session_factory=self.Session,
            artifact_service_factory=lambda _db: self.artifacts,
            tracking_factory=lambda: self.tracking,
            worker_id="worker-2",
            task_id="task-2",
            checkpoint_interval=2,
        )

        self.assertEqual(outcome.status, "completed")
        self.assertEqual(
            [step for run_id, step, _values in self.tracking.metrics if run_id == "run-2"],
            [4, 5],
        )

    def test_tracking_failure_maps_job_to_failed(self):
        self.tracking.fail_start = True
        outcome = self.execute()

        with self.Session() as db:
            job = db.query(TrainingJob).filter(TrainingJob.id == self.job_id).one()
            self.assertEqual(outcome.status, "failed")
            self.assertEqual(job.status, "failed")
            self.assertEqual(job.error_code, "TRACKING_UNAVAILABLE")
            self.assertIn("TrackingUnavailable", job.error_details["exception_type"])

    def test_cancel_request_stops_after_epoch_and_keeps_latest_checkpoint(self):
        def request_cancel(_step):
            with self.Session() as db:
                job = db.query(TrainingJob).filter(TrainingJob.id == self.job_id).one()
                job.status = "cancel_requested"
                db.commit()

        self.tracking.on_metric = request_cancel
        outcome = self.execute()

        with self.Session() as db:
            job = db.query(TrainingJob).filter(TrainingJob.id == self.job_id).one()
            self.assertEqual(outcome.status, "cancelled")
            self.assertEqual(job.status, "cancelled")
            self.assertEqual(job.current_epoch, 1)
            self.assertIsNotNone(job.latest_checkpoint_uri)
            self.assertIsNone(job.model_artifact_id)
        self.assertEqual(self.tracking.terminated, [("run-1", "KILLED")])

    def test_celery_task_is_registered_with_durable_delivery_settings(self):
        self.assertIn("ml_platform.execute_training", celery_app.tasks)
        self.assertTrue(celery_app.conf.task_acks_late)
        self.assertTrue(celery_app.conf.task_reject_on_worker_lost)


if __name__ == "__main__":
    unittest.main()
