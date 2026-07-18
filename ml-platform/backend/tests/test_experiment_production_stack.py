import os
import tempfile
import time
import unittest
import uuid
from pathlib import Path

import httpx

import app.main  # noqa: F401 (load the complete production model graph)
from app.config import settings
from app.database import SessionLocal, engine
from app.models.experiment import Experiment
from app.models.project import Project
from app.models.training import TrainingJob
from app.models.user import User
from app.services.artifact_service import build_artifact_service
from app.services.readiness_service import ReadinessService
from app.services.training_execution import build_training_tracking
from app.storage.minio import MinioStorage
from app.tasks.celery_app import celery_app
from app.tasks.training_tasks import execute_training_task
from app.tensorboard_gateway.tokens import SessionSigner


@unittest.skipUnless(
    os.getenv("RUN_EXPERIMENT_INTEGRATION") == "1",
    "RUN_EXPERIMENT_INTEGRATION is not enabled",
)
class TestExperimentProductionStack(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.storage = MinioStorage.from_settings(settings)
        cls.tracking = build_training_tracking()
        unique = uuid.uuid4().hex
        cls.experiment_name = f"production-experiment-{unique}"
        cls.mlflow_experiment_id = cls.tracking.ensure_experiment(cls.experiment_name)

        with tempfile.TemporaryDirectory() as directory, SessionLocal() as db:
            dataset_path = Path(directory) / "weld.csv"
            rows = ["current,force,quality"] + [
                f"{7 + index % 6},{2 + index % 5},{int((index % 6) + (index % 5) > 4)}"
                for index in range(120)
            ]
            dataset_path.write_text("\n".join(rows), encoding="utf-8")
            user = User(
                username=f"experiment-integration-{unique}",
                password_hash="integration-only-hash",
            )
            db.add(user)
            db.flush()
            project = Project(name=f"Experiment integration {unique}", owner_id=user.id)
            db.add(project)
            db.flush()
            experiment = Experiment(
                project_id=project.id,
                created_by=user.id,
                name=cls.experiment_name,
                mlflow_experiment_id=cls.mlflow_experiment_id,
            )
            db.add(experiment)
            db.flush()
            dataset = build_artifact_service(db).create_dataset(
                project.id,
                dataset_path,
                "weld-production.csv",
            )
            job = TrainingJob(
                project_id=project.id,
                user_id=user.id,
                experiment_id=experiment.id,
                dataset_artifact_id=dataset.id,
                name="production-incremental-classifier",
                operator_id="incremental_sgd",
                params={"target_column": "quality", "task": "classification"},
                status="pending",
                total_epochs=3,
                monitor_name="val_accuracy",
                monitor_mode="max",
                early_stopping_patience=10,
                restore_best=True,
            )
            db.add(job)
            db.commit()
            cls.job_id = job.id
            cls.project_id = project.id

    def test_real_training_resume_comparison_and_tensorboard_session(self):
        first = execute_training_task.delay(str(self.job_id)).get(timeout=120)
        self.assertEqual(first["status"], "completed", first)

        with SessionLocal() as db:
            source = db.query(TrainingJob).filter(TrainingJob.id == self.job_id).one()
            source_run_id = source.mlflow_run_id
            self.assertIsNotNone(source_run_id)
            self.assertIsNotNone(source.latest_checkpoint_uri)
            resumed = TrainingJob(
                project_id=source.project_id,
                user_id=source.user_id,
                experiment_id=source.experiment_id,
                dataset_artifact_id=source.dataset_artifact_id,
                name="production-resumed-classifier",
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
                resumed_from_run_id=source_run_id,
                resume_checkpoint_uri=source.latest_checkpoint_uri,
            )
            db.add(resumed)
            db.commit()
            resumed_id = resumed.id

        artifacts = self.tracking.list_artifacts(source_run_id, "checkpoints")
        self.assertIn("checkpoints/latest.joblib", {item.path for item in artifacts})
        with tempfile.TemporaryDirectory() as directory:
            downloaded = self.tracking.download_artifact(
                source_run_id,
                "checkpoints/latest.joblib",
                directory,
            )
            self.assertGreater(Path(downloaded).stat().st_size, 0)

        second = execute_training_task.delay(str(resumed_id)).get(timeout=120)
        self.assertEqual(second["status"], "completed", second)
        with SessionLocal() as db:
            resumed = db.query(TrainingJob).filter(TrainingJob.id == resumed_id).one()
            resumed_run_id = resumed.mlflow_run_id

        compared = self.tracking.compare_runs([source_run_id, resumed_run_id])
        self.assertEqual([run.run_id for run in compared], [source_run_id, resumed_run_id])
        resumed_history = self.tracking.get_metric_history(resumed_run_id, "val_accuracy")
        self.assertEqual([point.step for point in resumed_history], [4, 5])

        secret = settings.resolved_tensorboard_session_secret.get_secret_value()
        token = SessionSigner(secret).issue(
            session_id=f"integration-{uuid.uuid4().hex}",
            run_id=resumed_run_id,
            relative_logdir=f"{self.project_id}/{resumed_run_id}",
            expires_at=int(time.time()) + settings.tensorboard_session_ttl_seconds,
        )
        gateway = settings.tensorboard_gateway_url.rstrip("/")
        response = httpx.post(
            f"{gateway}/internal/sessions",
            json={"token": token},
            timeout=15.0,
        )
        response.raise_for_status()
        self.assertEqual(response.json()["run_id"], resumed_run_id)

        readiness = ReadinessService(
            engine,
            settings,
            redis_client=None,
            celery_app=celery_app,
            storage=self.storage,
        )
        readiness._redis = lambda: {"ready": True, "code": "OK"}
        result = readiness.check_all()
        self.assertTrue(result["mlflow"]["ready"], result)
        self.assertTrue(result["tensorboard"]["ready"], result)


if __name__ == "__main__":
    unittest.main()
