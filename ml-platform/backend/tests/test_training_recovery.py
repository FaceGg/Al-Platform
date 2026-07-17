import unittest
import uuid
from datetime import timedelta
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.experiment import Experiment
from app.models.project import Project
from app.models.training import TrainingJob
from app.models.user import User
from app.services.readiness_service import ReadinessService
from app.tasks.training_recovery import reconcile_stale_training_jobs, utcnow


class TestTrainingRecovery(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()
        user = User(username=f"recovery-{uuid.uuid4().hex}", password_hash="hash")
        self.db.add(user)
        self.db.flush()
        project = Project(name="Recovery", owner_id=user.id)
        self.db.add(project)
        self.db.flush()
        experiment = Experiment(
            project_id=project.id,
            created_by=user.id,
            name="Recovery",
            mlflow_experiment_id=f"exp-{uuid.uuid4().hex}",
        )
        self.db.add(experiment)
        self.db.flush()
        self.ids = (project.id, user.id, experiment.id)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _job(self, status, checkpoint=None, task_id="lost-task"):
        project_id, user_id, experiment_id = self.ids
        job = TrainingJob(
            project_id=project_id,
            user_id=user_id,
            experiment_id=experiment_id,
            dataset_artifact_id=uuid.uuid4(),
            name=f"job-{uuid.uuid4().hex}",
            status=status,
            task_id=task_id,
            worker_id="lost-worker",
            heartbeat_at=utcnow() - timedelta(minutes=10),
            latest_checkpoint_uri=checkpoint,
        )
        self.db.add(job)
        self.db.commit()
        return job

    def test_stale_job_with_checkpoint_is_requeued_with_attempt(self):
        stale = self._job("running", "mlflow-artifacts:/latest")

        recovered = reconcile_stale_training_jobs(
            self.db,
            active_task_ids=set(),
            stale_after=timedelta(minutes=5),
        )

        self.assertEqual(recovered.requeued, 1)
        self.assertEqual(stale.status, "pending")
        self.assertEqual(stale.attempt, 1)
        self.assertIsNone(stale.task_id)
        self.assertIsNone(stale.worker_id)

    def test_stale_job_without_checkpoint_fails(self):
        stale = self._job("running")
        recovered = reconcile_stale_training_jobs(
            self.db,
            active_task_ids=set(),
            stale_after=timedelta(minutes=5),
        )
        self.assertEqual(recovered.failed, 1)
        self.assertEqual(stale.status, "failed")
        self.assertEqual(stale.error_code, "TRAINING_WORKER_LOST")

    def test_stale_cancel_request_becomes_cancelled(self):
        stale = self._job("cancel_requested", "mlflow-artifacts:/latest")
        recovered = reconcile_stale_training_jobs(
            self.db,
            active_task_ids=set(),
            stale_after=timedelta(minutes=5),
        )
        self.assertEqual(recovered.cancelled, 1)
        self.assertEqual(stale.status, "cancelled")

    def test_active_or_fresh_jobs_are_unchanged(self):
        active = self._job("running", "mlflow-artifacts:/latest", task_id="active-task")
        fresh = self._job("running", "mlflow-artifacts:/latest", task_id="fresh-task")
        fresh.heartbeat_at = utcnow()
        self.db.commit()

        recovered = reconcile_stale_training_jobs(
            self.db,
            active_task_ids={"active-task"},
            stale_after=timedelta(minutes=5),
        )
        self.assertEqual(recovered.total, 0)
        self.assertEqual(active.status, "running")
        self.assertEqual(fresh.status, "running")

    def test_readiness_requires_registered_training_task(self):
        inspect = SimpleNamespace(ping=lambda: {"worker": {"ok": "pong"}})
        missing = ReadinessService(
            engine=self.engine,
            settings=SimpleNamespace(task_backend="celery", artifact_storage_backend="local"),
            celery_app=SimpleNamespace(
                tasks={},
                control=SimpleNamespace(inspect=lambda: inspect),
            ),
        )
        registered = ReadinessService(
            engine=self.engine,
            settings=SimpleNamespace(task_backend="celery", artifact_storage_backend="local"),
            celery_app=SimpleNamespace(
                tasks={"ml_platform.execute_training": object()},
                control=SimpleNamespace(inspect=lambda: inspect),
            ),
        )

        self.assertEqual(missing._celery()["code"], "CELERY_UNAVAILABLE")
        self.assertEqual(registered._celery(), {"ready": True, "code": "OK"})


if __name__ == "__main__":
    unittest.main()
