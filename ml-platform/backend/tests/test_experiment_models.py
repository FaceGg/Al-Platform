import unittest

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.database_migrations import ensure_schema_compatibility
from app.models.experiment import Experiment
from app.models.project import Project
from app.models.training import TrainingJob
from app.models.user import User


class TestExperimentModels(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.session = sessionmaker(bind=self.engine)()
        self.user = User(username="experiment-owner", password_hash="hash")
        self.session.add(self.user)
        self.session.flush()
        self.project = Project(name="Welding", owner_id=self.user.id)
        self.session.add(self.project)
        self.session.flush()

    def tearDown(self):
        self.session.close()
        self.engine.dispose()

    def test_experiment_relates_to_training_job_with_tracking_defaults(self):
        experiment = Experiment(
            project_id=self.project.id,
            created_by=self.user.id,
            name="Weld quality baseline",
            description="Baseline experiment",
            mlflow_experiment_id="42",
        )
        job = TrainingJob(
            project_id=self.project.id,
            user_id=self.user.id,
            experiment=experiment,
            name="incremental-classifier",
            status="pending",
            total_epochs=20,
            monitor_name="val_accuracy",
            monitor_mode="max",
        )
        self.session.add(job)
        self.session.commit()

        self.assertEqual(job.experiment, experiment)
        self.assertIn(job, experiment.training_jobs)
        self.assertEqual(job.attempt, 0)
        self.assertEqual(job.current_epoch, 0)
        self.assertTrue(job.restore_best)

    def test_experiment_name_is_unique_within_project_only(self):
        other_project = Project(name="Welding 2", owner_id=self.user.id)
        self.session.add(other_project)
        self.session.flush()
        self.session.add_all([
            Experiment(
                project_id=self.project.id,
                created_by=self.user.id,
                name="Baseline",
                mlflow_experiment_id="mlflow-1",
            ),
            Experiment(
                project_id=other_project.id,
                created_by=self.user.id,
                name="Baseline",
                mlflow_experiment_id="mlflow-2",
            ),
        ])
        self.session.commit()

        self.session.add(Experiment(
            project_id=self.project.id,
            created_by=self.user.id,
            name="Baseline",
            mlflow_experiment_id="mlflow-3",
        ))
        with self.assertRaises(IntegrityError):
            self.session.commit()

    def test_tracking_columns_and_indexes_are_present(self):
        inspector = inspect(self.engine)
        experiment_indexes = {
            item["name"]: item for item in inspector.get_indexes("experiments")
        }
        training_indexes = {
            item["name"]: item for item in inspector.get_indexes("training_jobs")
        }

        self.assertIn("ix_experiments_project_id", experiment_indexes)
        self.assertTrue(experiment_indexes["ix_experiments_mlflow_experiment_id"]["unique"])
        self.assertIn("ix_training_jobs_experiment_id", training_indexes)
        self.assertIn("ix_training_jobs_mlflow_run_id", training_indexes)
        self.assertIn("ix_training_jobs_task_id", training_indexes)
        self.assertIn("ix_training_jobs_heartbeat_at", training_indexes)


class TestExperimentSQLiteCompatibility(unittest.TestCase):
    def test_legacy_training_jobs_receive_nullable_tracking_columns_and_indexes(self):
        engine = create_engine("sqlite:///:memory:")
        try:
            with engine.begin() as connection:
                connection.execute(text(
                    "CREATE TABLE training_jobs ("
                    "id CHAR(32) PRIMARY KEY, project_id CHAR(32) NOT NULL, "
                    "user_id CHAR(32) NOT NULL, name VARCHAR(128) NOT NULL)"
                ))

            ensure_schema_compatibility(engine)

            inspector = inspect(engine)
            columns = {
                item["name"]: item for item in inspector.get_columns("training_jobs")
            }
            expected = {
                "experiment_id", "mlflow_run_id", "task_id", "worker_id",
                "heartbeat_at", "attempt", "resumed_from_job_id",
                "resumed_from_run_id", "resume_checkpoint_uri",
                "latest_checkpoint_uri", "best_checkpoint_uri", "current_epoch",
                "total_epochs", "monitor_name", "monitor_mode",
                "early_stopping_patience", "early_stopping_min_delta", "restore_best",
            }
            self.assertTrue(expected.issubset(columns))
            self.assertTrue(columns["experiment_id"]["nullable"])
            self.assertTrue(columns["mlflow_run_id"]["nullable"])
            indexes = {item["name"] for item in inspector.get_indexes("training_jobs")}
            self.assertTrue({
                "ix_training_jobs_experiment_id",
                "ix_training_jobs_mlflow_run_id",
                "ix_training_jobs_task_id",
                "ix_training_jobs_heartbeat_at",
            }.issubset(indexes))
        finally:
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
