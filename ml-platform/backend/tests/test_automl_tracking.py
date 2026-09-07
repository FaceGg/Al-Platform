import tempfile
import threading
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from fastapi.testclient import TestClient
from sklearn.base import BaseEstimator, ClassifierMixin, RegressorMixin
from sklearn.dummy import DummyClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import KFold as SklearnKFold
from sklearn.model_selection import StratifiedKFold as SklearnStratifiedKFold
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
    _build_multioutput_trial_specs,
    _aggregate_fold_classification_metrics,
    _rank_multioutput_trials,
    execute_automl_job,
)
from app.services.experiment_tracking import TrackedRun
from app.services.automl_search import FamilySearchResult, run_family_search
from app.tasks.celery_app import celery_app
from app.tasks.training_tasks import LocalTrainingDispatcher


class FailingEstimator:
    def fit(self, _features, _target):
        raise ValueError("candidate failed")

    def get_params(self, deep=True):
        return {}

    def set_params(self, **_params):
        return self


class FeatureCapturingClassifier(ClassifierMixin, BaseEstimator):
    seen_columns: list[tuple[str, ...]] = []

    def fit(self, features, target):
        type(self).seen_columns.append(tuple(features.columns))
        self.classes_ = np.unique(target)
        self.prediction_ = int(np.asarray(target)[0])
        return self

    def predict(self, features):
        return np.full(len(features), self.prediction_)


class FeatureCapturingRegressor(RegressorMixin, BaseEstimator):
    seen_columns: list[tuple[str, ...]] = []

    def fit(self, features, target):
        type(self).seen_columns.append(tuple(features.columns))
        self.prediction_ = float(np.mean(target))
        return self

    def predict(self, features):
        return np.full(len(features), self.prediction_, dtype=float)


class FailOnThirdFitClassifier(ClassifierMixin, BaseEstimator):
    fit_calls = 0

    def fit(self, features, target):
        type(self).fit_calls += 1
        if type(self).fit_calls >= 3:
            raise ValueError("final fit failed")
        self.classes_ = np.unique(target)
        return self

    def predict(self, features):
        return np.full(len(features), self.classes_[0])

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
            self.assertEqual(job.status, "completed")
            self.assertIsNotNone(job.model_artifact_id)
            self.assertEqual(
                db.query(ModelLibrary).filter(ModelLibrary.training_job_id == job_id).count(),
                0,
            )
            self.assertEqual(job.metrics["best_model"]["name"], "logistic")
            self.assertEqual(
                [result["name"] for result in job.metrics["all_results"]],
                ["logistic"],
            )

    def test_multioutput_execution_persists_candidate_artifact_and_reports(self):
        self.dataset_path.write_text(
            "x1,x2,label_a,label_b\n" + "\n".join(
                f"{index % 7},{index % 5},{int(index % 2 == 0)},{int(index % 3 == 0)}"
                for index in range(60)
            ),
            encoding="utf-8",
        )
        job_id = self.create_job(params={
            "target_column": "label_a",
            "target_columns": ["label_a", "label_b"],
            "task": "multioutput_classification",
            "input_columns": ["x1", "x2"],
            "cross_validation_enabled": True,
            "cross_validation_folds": 2,
        })

        result = self.execute(job_id)

        self.assertEqual(result.status, "completed")
        with self.Session() as db:
            job = db.query(TrainingJob).filter(TrainingJob.id == job_id).one()
            self.assertIsNotNone(job.model_artifact_id)
            self.assertEqual(job.metrics["best_candidate"], "multioutput_random_forest")
            self.assertEqual(
                next(row for row in job.metrics["algorithm_results"] if row["algorithm_id"] == job.metrics["best_candidate"])["model_artifact_id"],
                str(job.model_artifact_id),
            )
            self.assertEqual(
                set(job.metrics["per_target"]),
                {"label_a", "label_b"},
            )
            self.assertEqual(
                set(job.metrics["predictions"]),
                {"label_a", "label_b"},
            )
            self.assertIn("preprocessing", job.metrics)
            self.assertEqual(job.metrics["input_contract"]["target_columns"], ["label_a", "label_b"])

    def test_multioutput_persists_one_artifact_for_each_completed_family(self):
        self.dataset_path.write_text(
            "x1,x2,label_a,label_b\n" + "\n".join(
                f"{index % 7},{index % 5},{int(index % 2 == 0)},{int(index % 3 == 0)}"
                for index in range(60)
            ),
            encoding="utf-8",
        )
        job_id = self.create_job(params={
            "target_columns": ["label_a", "label_b"],
            "task": "multioutput_classification",
            "input_columns": ["x1", "x2"],
            "cross_validation_folds": 2,
            "algorithm_ids": ["random_forest", "extra_trees"],
            "search_method": "grid",
            "max_trials": 2,
        })

        result = self.execute(job_id)

        self.assertEqual(result.status, "completed")
        with self.Session() as db:
            job = db.get(TrainingJob, job_id)
            rows = [row for row in job.metrics["algorithm_results"] if row["status"] == "completed"]
            self.assertEqual({row["algorithm_id"] for row in rows}, {"random_forest", "extra_trees"})
            self.assertEqual(len({row["model_artifact_id"] for row in rows}), 2)
            self.assertEqual(
                {row["model_artifact_id"] for row in rows},
                {str(artifact.id) for artifact in self.artifacts.created},
            )
            self.assertEqual(
                {row["algorithm_id"] for row in job.metrics["all_results"]},
                {row["algorithm_id"] for row in rows},
            )
            self.assertIn(str(job.model_artifact_id), {row["model_artifact_id"] for row in rows})

    def test_multioutput_controls_change_worker_configuration_and_auc_tier(self):
        self.dataset_path.write_text(
            "x1,x2,label_a,label_b\n" + "\n".join(
                f"{index % 7},{index % 5},{int(index % 2 == 0)},{int(index % 3 == 0)}"
                for index in range(60)
            ),
            encoding="utf-8",
        )
        job_id = self.create_job(params={
            "target_column": "label_a",
            "target_columns": ["label_a", "label_b"],
            "task": "multioutput_classification",
            "input_columns": ["x1", "x2"],
            "cross_validation_folds": 2,
            "search_strength": "maximum",
            "time_budget": 1800,
            "class_weight": True,
        })

        self.execute(job_id)

        with self.Session() as db:
            job = db.get(TrainingJob, job_id)
            self.assertEqual(job.metrics["search"]["n_estimators"], 320)
            self.assertEqual(job.metrics["search"]["time_budget"], 1800)
            self.assertTrue(job.metrics["search"]["class_weight"])
            self.assertIn(job.metrics["auc_tier"], {"complete", "incomplete"})

    def test_fold_auc_aggregates_all_binary_and_multiclass_scores(self):
        binary = _aggregate_fold_classification_metrics(
            np.array([0, 1, 0, 1]),
            np.array([0, 1, 0, 1]),
            [(np.array([0, 1]), np.array([0.1, 0.9])), (np.array([2, 3]), np.array([0.2, 0.8]))],
        )
        multiclass = _aggregate_fold_classification_metrics(
            np.array([0, 1, 2, 0, 1, 2]),
            np.array([0, 1, 2, 0, 1, 2]),
            [
                (np.array([0, 1, 2]), np.eye(3)),
                (np.array([3, 4, 5]), np.eye(3)),
            ],
        )
        self.assertEqual(binary["auc"], 1.0)
        self.assertEqual(multiclass["auc"], 1.0)
        self.assertIsNone(_aggregate_fold_classification_metrics(
            np.array([0, 1]), np.array([0, 1]), [(np.array([0, 1]), None)],
        )["auc"])

    def test_multioutput_worker_honors_cancellation_polling(self):
        self.dataset_path.write_text(
            "x1,x2,label_a,label_b\n" + "\n".join(
                f"{index % 7},{index % 5},{index % 2},{index % 3 == 0}" for index in range(60)
            ), encoding="utf-8",
        )
        job_id = self.create_job(params={
            "target_columns": ["label_a", "label_b"], "task": "multioutput_classification",
            "input_columns": ["x1", "x2"], "cross_validation_folds": 2,
        })
        result = execute_automl_job(job_id, dependencies=AutoMLDependencies(
            session_factory=self.Session, artifact_service_factory=lambda _db: self.artifacts,
            tracking_factory=lambda: self.tracking, worker_id="worker-1", task_id="task-1",
            cancellation_requested=lambda _job_id: True,
        ))
        self.assertEqual(result.status, "cancelled")
        with self.Session() as db:
            self.assertEqual(db.get(TrainingJob, job_id).status, "cancelled")

    def test_single_output_worker_honors_cancellation_polling(self):
        job_id = self.create_job(params={
            "target_column": "quality",
            "task": "classification",
            "input_columns": ["current", "force"],
            "cross_validation_enabled": False,
            "cross_validation_folds": None,
        })
        result = execute_automl_job(job_id, dependencies=AutoMLDependencies(
            session_factory=self.Session,
            artifact_service_factory=lambda _db: self.artifacts,
            tracking_factory=lambda: self.tracking,
            worker_id="worker-1",
            task_id="task-1",
            cancellation_requested=lambda _job_id: True,
        ))
        self.assertEqual(result.status, "cancelled")
        with self.Session() as db:
            self.assertEqual(db.get(TrainingJob, job_id).status, "cancelled")

    def test_single_output_cancellation_after_candidate_search_does_not_complete_final_fit(self):
        job_id = self.create_job(params={
            "target_column": "quality",
            "task": "classification",
            "input_columns": ["current", "force"],
            "cross_validation_enabled": False,
            "cross_validation_folds": None,
        })
        cancellation_states = iter((False, False, True))
        result = execute_automl_job(job_id, candidates=[
            AutoMLCandidate("capturing", FeatureCapturingClassifier, {}),
        ], dependencies=AutoMLDependencies(
            session_factory=self.Session,
            artifact_service_factory=lambda _db: self.artifacts,
            tracking_factory=lambda: self.tracking,
            worker_id="worker-1",
            task_id="task-1",
            cancellation_requested=lambda _job_id: next(cancellation_states),
        ))

        self.assertEqual(result.status, "cancelled")
        with self.Session() as db:
            job = db.get(TrainingJob, job_id)
            self.assertEqual(job.status, "cancelled")
            self.assertIsNone(job.model_artifact_id)

    def test_multioutput_worker_stops_when_time_budget_is_exhausted(self):
        self.dataset_path.write_text(
            "x1,x2,target_a,target_b\n" + "\n".join(
                f"{index},{index % 7},{index * 1.5},{index % 7 * 2}" for index in range(60)
            ), encoding="utf-8",
        )
        job_id = self.create_job(params={
            "target_columns": ["target_a", "target_b"], "task": "multioutput_regression",
            "input_columns": ["x1", "x2"], "cross_validation_folds": 2, "time_budget": 60,
        })
        ticks = iter((0.0, 61.0))
        result = execute_automl_job(job_id, dependencies=AutoMLDependencies(
            session_factory=self.Session, artifact_service_factory=lambda _db: self.artifacts,
            tracking_factory=lambda: self.tracking, worker_id="worker-1", task_id="task-1",
            monotonic=lambda: next(ticks),
        ))
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.error_code, "AUTOML_TIME_BUDGET_EXCEEDED")

    def test_multioutput_regression_persists_cross_validated_predictions(self):
        self.dataset_path.write_text(
            "x1,x2,target_a,target_b\n" + "\n".join(
                f"{index},{index % 7},{index * 1.5 + 3},{(index % 7) * 2.0 - 1}"
                for index in range(60)
            ),
            encoding="utf-8",
        )
        job_id = self.create_job(params={
            "target_column": "target_a",
            "target_columns": ["target_a", "target_b"],
            "task": "multioutput_regression",
            "input_columns": ["x1", "x2"],
            "cross_validation_folds": 3,
        })

        self.execute(job_id)

        with self.Session() as db:
            job = db.get(TrainingJob, job_id)
            self.assertEqual(job.metrics["prediction_source"], "cross_validation")
            self.assertEqual(len(job.metrics["predictions"]["target_a"]), 60)

    def test_multioutput_regression_persists_full_metrics_and_feature_importance(self):
        self.dataset_path.write_text(
            "x1,x2,target_a,target_b\n" + "\n".join(
                f"{index},{index % 7},{index * 1.5 + 3},{(index % 7) * 2.0 - 1}"
                for index in range(60)
            ),
            encoding="utf-8",
        )
        job_id = self.create_job(params={
            "target_column": "target_a",
            "target_columns": ["target_a", "target_b"],
            "task": "multioutput_regression",
            "input_columns": ["x1", "x2"],
            "cross_validation_folds": 3,
        })

        self.execute(job_id)

        with self.Session() as db:
            metrics = db.get(TrainingJob, job_id).metrics
            for report in metrics["per_target"].values():
                self.assertEqual(set(report), {"r2", "rmse", "mae"})
                self.assertTrue(all(np.isfinite(float(report[key])) for key in ("r2", "rmse", "mae")))
            self.assertEqual(set(metrics["aggregate"]), {"r2", "rmse", "mae"})
            self.assertEqual(set(metrics["feature_importance"]), {"x1", "x2"})
            report = metrics["feature_importance_report"]
            self.assertEqual(set(report["per_target"]), {"target_a", "target_b"})
            self.assertEqual(report["source"], "model_native")

    def test_multioutput_worker_ranks_regression_candidates_by_full_metric_contract(self):
        trials = [
            {
                "algorithm_id": "higher_runtime",
                "status": "completed",
                "aggregate": {"r2": 0.90, "rmse": 0.80, "mae": 0.50},
                "training_time_seconds": 20.0,
            },
            {
                "algorithm_id": "lower_rmse",
                "status": "completed",
                "aggregate": {"r2": 0.90, "rmse": 0.70, "mae": 0.90},
                "training_time_seconds": 10.0,
            },
            {
                "algorithm_id": "faster_tie",
                "status": "completed",
                "aggregate": {"r2": 0.90, "rmse": 0.80, "mae": 0.50},
                "training_time_seconds": 5.0,
            },
        ]

        ranked = _rank_multioutput_trials(trials, "multioutput_regression")

        self.assertEqual(
            [trial["algorithm_id"] for trial in ranked],
            ["lower_rmse", "faster_tie", "higher_runtime"],
        )

    def test_multioutput_worker_preserves_idempotency_fingerprint_and_family_selection(self):
        self.dataset_path.write_text(
            "x1,x2,target_a,target_b\n" + "\n".join(
                f"{index},{index % 7},{index * 1.5},{index % 7 * 2}" for index in range(60)
            ), encoding="utf-8",
        )
        job_id = self.create_job(params={
            "target_columns": ["target_a", "target_b"], "task": "multioutput_regression",
            "input_columns": ["x1", "x2"], "cross_validation_folds": 2,
            "algorithm_ids": ["extra_trees"], "search_method": "grid", "max_trials": 5,
        })
        with self.Session() as db:
            job = db.get(TrainingJob, job_id)
            job.automl_contract = {"idempotency_fingerprint": "keep-me"}
            db.commit()
        result = self.execute(job_id)
        self.assertEqual(result.status, "completed")
        with self.Session() as db:
            job = db.get(TrainingJob, job_id)
            self.assertEqual(job.automl_contract["idempotency_fingerprint"], "keep-me")
            self.assertEqual(job.metrics["best_algorithm"], "extra_trees")
            self.assertTrue(job.preprocessing["fold_local"])

    def test_multioutput_candidate_runtime_failure_isolated_from_later_candidates(self):
        self.dataset_path.write_text(
            "x1,x2,label_a,label_b\n" + "\n".join(
                f"{index % 7},{index % 5},{int(index % 2 == 0)},{int(index % 3 == 0)}"
                for index in range(60)
            ),
            encoding="utf-8",
        )
        job_id = self.create_job(params={
            "target_columns": ["label_a", "label_b"],
            "task": "multioutput_classification",
            "input_columns": ["x1", "x2"],
            "cross_validation_folds": 2,
            "algorithm_ids": ["runtime_failure", "random_forest"],
            "search_method": "grid",
            "max_trials": 2,
        })
        from app.services.automl_catalog import resolve_algorithm_families

        failing_family = SimpleNamespace(
            id="runtime_failure",
            display_name="Runtime failure",
            default_params={},
            grid={},
            search_space={},
            resource_parameter="n_estimators",
            min_resource=1,
            max_resource=1,
            build=lambda _task, _params: FailingEstimator(),
        )
        valid_family = resolve_algorithm_families(["random_forest"])[0]
        with patch(
            "app.services.automl_execution.resolve_algorithm_families",
            return_value=(failing_family, valid_family),
        ):
            result = self.execute(job_id)

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.best_candidate, "random_forest")
        with self.Session() as db:
            rows = db.get(TrainingJob, job_id).metrics["algorithm_results"]
            failed = next(row for row in rows if row["algorithm_id"] == "runtime_failure")
            completed = next(row for row in rows if row["algorithm_id"] == "random_forest")
            self.assertEqual(failed["status"], "failed")
            self.assertEqual(failed["error_code"], "AUTOML_CANDIDATE_FAILED")
            self.assertTrue(failed["error_type"])
            self.assertEqual(completed["status"], "completed")
            self.assertTrue(completed["model_artifact_id"])

    def test_multioutput_candidate_final_artifact_failure_does_not_discard_other_candidates(self):
        FailOnThirdFitClassifier.fit_calls = 0
        self.dataset_path.write_text(
            "x1,x2,label_a,label_b\n" + "\n".join(
                f"{index % 7},{index % 5},{int(index % 2 == 0)},{int(index % 3 == 0)}"
                for index in range(60)
            ),
            encoding="utf-8",
        )
        job_id = self.create_job(params={
            "target_columns": ["label_a", "label_b"],
            "task": "multioutput_classification",
            "input_columns": ["x1", "x2"],
            "cross_validation_folds": 2,
            "algorithm_ids": ["final_fit_failure", "random_forest"],
            "search_method": "grid",
            "max_trials": 2,
        })
        from app.services.automl_catalog import resolve_algorithm_families

        failing_family = SimpleNamespace(
            id="final_fit_failure",
            display_name="Final fit failure",
            default_params={},
            grid={},
            search_space={},
            resource_parameter="n_estimators",
            min_resource=1,
            max_resource=1,
            build=lambda _task, _params: FailOnThirdFitClassifier(),
        )
        valid_family = resolve_algorithm_families(["random_forest"])[0]
        with patch(
            "app.services.automl_execution.resolve_algorithm_families",
            return_value=(failing_family, valid_family),
        ):
            result = self.execute(job_id)

        self.assertEqual(result.status, "completed")
        with self.Session() as db:
            rows = db.get(TrainingJob, job_id).metrics["algorithm_results"]
            failed = next(row for row in rows if row["algorithm_id"] == "final_fit_failure")
            completed = next(row for row in rows if row["algorithm_id"] == "random_forest")
            self.assertEqual(failed["status"], "failed")
            self.assertEqual(failed["error_code"], "AUTOML_CANDIDATE_FAILED")
            self.assertEqual(completed["status"], "completed")
            self.assertTrue(completed["model_artifact_id"])

    def test_time_budget_preserves_completed_trials(self):
        self.dataset_path.write_text(
            "x1,x2,target_a,target_b\n" + "\n".join(
                f"{index},{index % 7},{index * 1.5},{index % 7 * 2}" for index in range(60)
            ), encoding="utf-8",
        )
        job_id = self.create_job(params={
            "target_columns": ["target_a", "target_b"], "task": "multioutput_regression",
            "input_columns": ["x1", "x2"], "cross_validation_folds": 2,
            "algorithm_ids": ["random_forest"], "search_method": "grid", "max_trials": 5, "time_budget": 60,
        })
        ticks = iter([0.0, 1.0, 2.0, 3.0, 4.0, 61.0])
        result = execute_automl_job(job_id, dependencies=AutoMLDependencies(
            session_factory=self.Session, artifact_service_factory=lambda _db: self.artifacts,
            tracking_factory=lambda: self.tracking, worker_id="worker-1", task_id="task-1",
            monotonic=lambda: next(ticks),
        ))
        self.assertEqual(result.status, "completed")
        self.assertIsNone(result.error_code)
        with self.Session() as db:
            search = db.get(TrainingJob, job_id).metrics["search"]
            self.assertGreaterEqual(search["completed_trials"], 1)
            self.assertTrue(search["budget_exhausted"])

    def test_timeout_persists_best_so_far_artifact_and_completed_status(self):
        self.dataset_path.write_text(
            "x1,x2,target_a,target_b\n" + "\n".join(
                f"{index},{index % 7},{index * 1.5},{index % 7 * 2}" for index in range(60)
            ), encoding="utf-8",
        )
        job_id = self.create_job(params={
            "target_columns": ["target_a", "target_b"], "task": "multioutput_regression",
            "input_columns": ["x1", "x2"], "cross_validation_folds": 2,
            "algorithm_ids": ["random_forest"], "search_method": "grid", "max_trials": 5, "time_budget": 60,
        })
        ticks = iter([0.0] + [1.0] * 8 + [61.0])
        result = execute_automl_job(job_id, dependencies=AutoMLDependencies(
            session_factory=self.Session, artifact_service_factory=lambda _db: self.artifacts,
            tracking_factory=lambda: self.tracking, worker_id="worker-1", task_id="task-1",
            monotonic=lambda: next(ticks),
        ))
        self.assertEqual(result.status, "completed")
        with self.Session() as db:
            job = db.get(TrainingJob, job_id)
            self.assertEqual(job.status, "completed")
            self.assertIsNotNone(job.model_artifact_id)
            self.assertTrue(job.metrics["search"]["budget_exhausted"])
            self.assertGreaterEqual(job.metrics["search"]["completed_trials"], 1)

    def test_search_strength_changes_family_resource_parameter(self):
        self.dataset_path.write_text(
            "x1,x2,target_a,target_b\n" + "\n".join(
                f"{index},{index % 7},{index * 1.5},{index % 7 * 2}" for index in range(60)
            ), encoding="utf-8",
        )
        values = {}
        for strength in ("light", "maximum"):
            job_id = self.create_job(params={
                "target_columns": ["target_a", "target_b"], "task": "multioutput_regression",
                "input_columns": ["x1", "x2"], "cross_validation_folds": 2,
                "algorithm_ids": ["random_forest"], "search_method": "grid", "max_trials": 5,
                "search_strength": strength, "time_budget": 60,
            })
            self.execute(job_id)
            with self.Session() as db:
                values[strength] = db.get(TrainingJob, job_id).metrics["search"]["selected_params"]["n_estimators"]
        self.assertLess(values["light"], values["maximum"])

    def test_grid_trial_specs_use_cartesian_parameter_combinations(self):
        from app.services.automl_catalog import resolve_algorithm_families
        family = resolve_algorithm_families(["random_forest"])[0]
        specs = _build_multioutput_trial_specs((family,), method="grid", max_trials=200, search_strength="balanced")
        expected = 1
        for values in family.grid.values():
            expected *= len(values)
        self.assertEqual(len(specs), expected)
        self.assertEqual(len({tuple(sorted(params.items())) for _family, params in specs}), expected)

    def test_grid_trial_specs_give_each_requested_family_a_trial(self):
        from app.services.automl_catalog import resolve_algorithm_families
        specs = _build_multioutput_trial_specs(
            resolve_algorithm_families(["random_forest", "extra_trees"]),
            method="grid", max_trials=2, search_strength="balanced",
        )
        self.assertEqual({family.id for family, _params in specs}, {"random_forest", "extra_trees"})

    def test_non_grid_search_methods_generate_distinct_observable_trials(self):
        from app.services.automl_catalog import resolve_algorithm_families

        family = resolve_algorithm_families(["random_forest"])[0]
        for method in ("random", "bayesian", "evolutionary", "multi_fidelity"):
            specs = _build_multioutput_trial_specs(
                (family,), method=method, max_trials=4, search_strength="balanced",
            )
            params = [tuple(sorted(values.items())) for _family, values in specs]
            self.assertGreater(len(set(params)), 1, method)
            if method == "multi_fidelity":
                self.assertGreater(len({values[family.resource_parameter] for _family, values in specs}), 1)

    def test_multioutput_bayesian_search_uses_optuna_family_search(self):
        self.dataset_path.write_text(
            "x1,x2,target_a,target_b\n" + "\n".join(
                f"{index},{index % 7},{index * 1.5},{index % 7 * 2}" for index in range(60)
            ),
            encoding="utf-8",
        )
        job_id = self.create_job(params={
            "target_columns": ["target_a", "target_b"],
            "task": "multioutput_regression",
            "input_columns": ["x1", "x2"],
            "cross_validation_folds": 2,
            "algorithm_ids": ["random_forest"],
            "search_method": "bayesian",
            "search_strength": "light",
            "max_trials": 2,
            "time_budget": 60,
        })
        observed_methods = []

        def observed_family_search(**kwargs):
            observed_methods.append(kwargs["config"].method)
            return run_family_search(**kwargs)

        result = execute_automl_job(job_id, dependencies=AutoMLDependencies(
            session_factory=self.Session,
            artifact_service_factory=lambda _db: self.artifacts,
            tracking_factory=lambda: self.tracking,
            worker_id="worker-1",
            task_id="task-1",
            family_search=observed_family_search,
        ))

        self.assertEqual(result.status, "completed")
        self.assertEqual(observed_methods, ["bayesian"])
        with self.Session() as db:
            search = db.get(TrainingJob, job_id).metrics["search"]
            self.assertEqual(search["method"], "bayesian")
            self.assertEqual(search["completed_trials"], 2)
            self.assertTrue(all(row["status"] == "complete" for row in search["trials"]))

    def test_multioutput_trial_budget_rejects_fewer_trials_than_families(self):
        from app.services.automl_catalog import resolve_algorithm_families

        with self.assertRaises(ValueError):
            _build_multioutput_trial_specs(
                resolve_algorithm_families(["random_forest", "extra_trees"]),
                method="grid", max_trials=1, search_strength="balanced",
            )

    def test_optuna_timeout_persists_best_so_far(self):
        job_id = self.create_job(params={
            "search_contract": "optuna_v1", "target_column": "quality",
            "input_columns": ["current", "force"], "task": "classification",
            "algorithm_ids": ["gbdt", "random_forest"], "search_method": "random",
            "max_trials": 5, "time_budget": 60,
            "cross_validation_enabled": False, "cross_validation_folds": None,
        })
        def family_search(**kwargs):
            kwargs["progress_callback"](SimpleNamespace(trial_number=0))
            return FamilySearchResult(
                algorithm_id=kwargs["family"].id,
                display_name=kwargs["family"].display_name,
                catalog_index=kwargs["catalog_index"], status="completed",
                best_score=0.8, best_params=dict(kwargs["family"].default_params),
                best_estimator=DummyClassifier(strategy="most_frequent").fit([[0], [1]], [0, 1]),
                completed_trials=1, training_time_seconds=1.0,
            )
        ticks = iter([0.0, 1.0, 61.0, 61.0])
        result = execute_automl_job(job_id, dependencies=AutoMLDependencies(
            session_factory=self.Session, artifact_service_factory=lambda _db: self.artifacts,
            tracking_factory=lambda: self.tracking, worker_id="worker-1", task_id="task-1",
            family_search=family_search, monotonic=lambda: next(ticks),
        ))
        self.assertEqual(result.status, "completed")
        with self.Session() as db:
            job = db.get(TrainingJob, job_id)
            self.assertIsNotNone(job.model_artifact_id)
            self.assertTrue(job.metrics["search"]["budget_exhausted"])

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

    def test_tied_metrics_select_the_faster_candidate(self):
        job_id = self.create_job()
        result = self.execute(job_id, [
            AutoMLCandidate("first", lambda: DummyClassifier(strategy="most_frequent"), {}),
            AutoMLCandidate("second", lambda: DummyClassifier(strategy="most_frequent"), {}),
        ])
        self.assertEqual(result.status, "completed")
        with self.Session() as db:
            job = db.query(TrainingJob).filter(TrainingJob.id == job_id).one()
            completed = job.metrics["all_results"]
            expected = min(completed, key=lambda item: item["training_time_seconds"])["name"]
        self.assertEqual(result.best_candidate, expected)

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

    def test_optuna_job_searches_each_family_and_persists_results(self):
        job_id = self.create_job(params={
            "search_contract": "optuna_v1",
            "target_column": "quality",
            "input_columns": ["current", "force"],
            "task": "classification",
            "algorithm_ids": ["gbdt", "random_forest"],
            "search_method": "random",
            "max_trials": 5,
            "time_budget": 60,
            "cross_validation_enabled": False,
            "cross_validation_folds": None,
        })

        result = self.execute(job_id)

        self.assertEqual(result.status, "completed")
        with self.Session() as db:
            job = db.query(TrainingJob).filter(TrainingJob.id == job_id).one()
            models = db.query(ModelLibrary).filter(ModelLibrary.training_job_id == job_id).all()
            self.assertEqual(job.metrics["search"]["method"], "random")
            self.assertEqual(
                [item["algorithm_id"] for item in job.metrics["algorithm_results"]],
                ["gbdt", "random_forest"],
            )
            self.assertIn(job.metrics["best_model"]["algorithm_id"], {"gbdt", "random_forest"})
            self.assertEqual(len(models), 0)
            self.assertEqual(
                {item["algorithm_id"] for item in job.metrics["all_results"]},
                {item["algorithm_id"] for item in job.metrics["algorithm_results"] if item["status"] == "completed"},
            )
            self.assertIsNone(job.model_library_id)
            self.assertTrue(all(item.get("model_artifact_id") for item in job.metrics["all_results"]))

    def test_optuna_persists_complete_single_output_training_contract(self):
        job_id = self.create_job(params={
            "search_contract": "optuna_v1",
            "target_column": "quality",
            "input_columns": ["current", "force"],
            "task": "classification",
            "algorithm_ids": ["random_forest"],
            "search_method": "random",
            "max_trials": 1,
            "time_budget": 60,
            "cross_validation_enabled": False,
            "cross_validation_folds": None,
        })

        result = self.execute(job_id)
        self.assertEqual(result.status, "completed")
        with self.Session() as db:
            job = db.get(TrainingJob, job_id)
            self.assertEqual(job.metrics["input_contract"]["task_type"], "classification")
            self.assertEqual(job.metrics["input_contract"]["target_columns"], ["quality"])
            self.assertEqual(job.metrics["input_contract"]["input_columns"], ["current", "force"])
            self.assertIn("preprocessing", job.metrics)
            self.assertIn("feature_importance_report", job.metrics)
            self.assertEqual([item["name"] for item in job.feature_schema], ["current", "force"])
            self.assertEqual(job.target_schema["name"], "quality")
            self.assertEqual(job.automl_contract["task_type"], "classification")
            self.assertEqual(job.automl_contract["target_columns"], ["quality"])
            self.assertEqual(job.automl_contract["input_columns"], ["current", "force"])

    def test_selected_input_columns_are_the_only_columns_used_for_automl(self):
        FeatureCapturingClassifier.seen_columns.clear()
        job_id = self.create_job(params={
            "target_column": "quality",
            "task": "classification",
            "input_columns": ["force"],
        })

        result = self.execute(job_id, [
            AutoMLCandidate("capturing", FeatureCapturingClassifier, {}),
        ])

        self.assertEqual(result.status, "completed")
        self.assertTrue(FeatureCapturingClassifier.seen_columns)
        self.assertEqual(set(FeatureCapturingClassifier.seen_columns), {("force",)})

    def test_disabled_cross_validation_uses_deterministic_holdout(self):
        FeatureCapturingClassifier.seen_columns.clear()
        job_id = self.create_job(params={
            "target_column": "quality",
            "task": "classification",
            "cross_validation_enabled": False,
            "cross_validation_folds": None,
        })

        with patch(
            "app.services.automl_execution.StratifiedKFold",
            wraps=SklearnStratifiedKFold,
        ) as stratified_kfold:
            result = self.execute(job_id, [
                AutoMLCandidate("capturing", FeatureCapturingClassifier, {}),
            ])

        self.assertEqual(result.status, "completed")
        stratified_kfold.assert_not_called()
        self.assertEqual(len(FeatureCapturingClassifier.seen_columns), 3)
        with self.Session() as db:
            job = db.query(TrainingJob).filter(TrainingJob.id == job_id).one()
            self.assertEqual(job.metrics["evaluation"], {
                "cross_validation_enabled": False,
                "cross_validation_folds": None,
            })

    def test_enabled_cross_validation_honors_requested_classification_folds(self):
        for folds in (3, 4, 5):
            with self.subTest(folds=folds):
                FeatureCapturingClassifier.seen_columns.clear()
                job_id = self.create_job(params={
                    "target_column": "quality",
                    "task": "classification",
                    "cross_validation_enabled": True,
                    "cross_validation_folds": folds,
                })

                with patch(
                    "app.services.automl_execution.StratifiedKFold",
                    wraps=SklearnStratifiedKFold,
                ) as stratified_kfold:
                    result = self.execute(job_id, [
                        AutoMLCandidate("capturing", FeatureCapturingClassifier, {}),
                    ])

                self.assertEqual(result.status, "completed")
                stratified_kfold.assert_called_once_with(
                    n_splits=folds,
                    shuffle=True,
                    random_state=42,
                )
                self.assertGreaterEqual(
                    len(FeatureCapturingClassifier.seen_columns),
                    folds + 1,
                )
                self.assertEqual(
                    set(FeatureCapturingClassifier.seen_columns),
                    {("current", "force")},
                )

    def test_enabled_cross_validation_uses_kfold_for_regression(self):
        FeatureCapturingRegressor.seen_columns.clear()
        job_id = self.create_job(params={
            "target_column": "quality",
            "task": "regression",
            "cross_validation_enabled": True,
            "cross_validation_folds": 4,
        })

        with patch(
            "app.services.automl_execution.KFold",
            wraps=SklearnKFold,
        ) as kfold:
            result = self.execute(job_id, [
                AutoMLCandidate("capturing", FeatureCapturingRegressor, {}),
            ])

        self.assertEqual(result.status, "completed")
        kfold.assert_called_once_with(n_splits=4, shuffle=True, random_state=42)
        self.assertEqual(len(FeatureCapturingRegressor.seen_columns), 5)

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
        cls.temporary = tempfile.TemporaryDirectory()
        dataset_path = Path(cls.temporary.name) / "automl-api.csv"
        dataset_path.write_text(
            "current,force,quality,material\n"
            "1,10,0,steel\n"
            "2,11,1,steel\n"
            "3,12,0,alloy\n"
            "4,13,1,alloy\n",
            encoding="utf-8",
        )
        cls.artifacts = FakeArtifactService(cls.dataset_id, dataset_path)
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
        cls.temporary.cleanup()
        cls.engine.dispose()

    def setUp(self):
        self.dispatcher.enqueued.clear()
        app.state.automl_dispatcher = self.dispatcher
        with self.Session() as db:
            experiment = Experiment(
                project_id=self.project_id,
                created_by=self.user_id,
                name=f"AutoML API {uuid.uuid4().hex}",
                mlflow_experiment_id=f"automl-api-{uuid.uuid4().hex}",
            )
            db.add(experiment)
            db.commit()
            self.experiment_id = experiment.id

    def _run_automl(self):
        return self.client.post("/api/training/automl/run", json={
            "project_id": str(self.project_id),
            "experiment_id": str(self.experiment_id),
            "dataset_artifact_id": str(self.dataset_id),
            "target_column": "quality",
            "task": "classification",
        }, headers=self.headers)

    def test_dataset_path_is_rejected(self):
        response = self.client.post("/api/training/automl/run", json={
            "project_id": str(self.project_id),
            "experiment_id": str(self.experiment_id),
            "dataset_path": "/tmp/untrusted.csv",
            "target_column": "quality",
        }, headers=self.headers)
        self.assertEqual(response.status_code, 422)

    def test_artifact_automl_job_is_queued(self):
        response = self._run_automl()
        self.assertEqual(response.status_code, 202, response.text)
        self.assertEqual(response.json()["status"], "queued")
        self.assertEqual(self.dispatcher.enqueued, [response.json()["job_id"]])

    def test_experiment_can_only_create_one_automl_job(self):
        first = self._run_automl()
        second = self._run_automl()

        self.assertEqual(first.status_code, 202, first.text)
        self.assertEqual(second.status_code, 409, second.text)
        self.assertEqual(
            second.json()["detail"]["code"],
            "EXPERIMENT_ALREADY_HAS_AUTOML_JOB",
        )

    def test_idempotency_key_replays_original_automl_job(self):
        headers = {**self.headers, "Idempotency-Key": f"automl-{uuid.uuid4().hex}"}
        payload = {
            "project_id": str(self.project_id),
            "experiment_id": str(self.experiment_id),
            "dataset_artifact_id": str(self.dataset_id),
            "target_column": "quality",
            "task": "classification",
        }
        first = self.client.post("/api/training/automl/run", json=payload, headers=headers)
        second = self.client.post("/api/training/automl/run", json=payload, headers=headers)
        self.assertEqual(first.status_code, 202, first.text)
        self.assertEqual(second.status_code, 202, second.text)
        self.assertEqual(second.json()["job_id"], first.json()["job_id"])
        self.assertEqual(self.dispatcher.enqueued, [first.json()["job_id"]])

    def test_idempotency_key_rejects_different_request(self):
        headers = {**self.headers, "Idempotency-Key": f"automl-{uuid.uuid4().hex}"}
        first = self.client.post("/api/training/automl/run", json={
            "project_id": str(self.project_id), "experiment_id": str(self.experiment_id),
            "dataset_artifact_id": str(self.dataset_id), "target_column": "quality",
        }, headers=headers)
        second = self.client.post("/api/training/automl/run", json={
            "project_id": str(self.project_id), "experiment_id": str(self.experiment_id),
            "dataset_artifact_id": str(self.dataset_id), "target_column": "quality", "name": "different",
        }, headers=headers)
        self.assertEqual(first.status_code, 202, first.text)
        self.assertEqual(second.status_code, 409, second.text)
        self.assertEqual(second.json()["detail"]["code"], "AUTOML_IDEMPOTENCY_CONFLICT")

    def test_completed_job_replays_after_worker_contract_update(self):
        headers = {**self.headers, "Idempotency-Key": f"automl-{uuid.uuid4().hex}"}
        payload = {"project_id": str(self.project_id), "experiment_id": str(self.experiment_id), "dataset_artifact_id": str(self.dataset_id), "target_column": "quality"}
        first = self.client.post("/api/training/automl/run", json=payload, headers=headers)
        with self.Session() as db:
            job = db.get(TrainingJob, uuid.UUID(first.json()["job_id"]))
            job.status = "completed"
            job.automl_contract = {**job.automl_contract, "input_columns": ["current", "force"]}
            db.commit()
        replay = self.client.post("/api/training/automl/run", json=payload, headers=headers)
        self.assertEqual(replay.status_code, 202, replay.text)
        self.assertEqual(replay.json()["job_id"], first.json()["job_id"])

    def test_deleting_terminal_automl_job_does_not_release_experiment(self):
        created = self._run_automl()
        self.assertEqual(created.status_code, 202, created.text)
        job_id = uuid.UUID(created.json()["job_id"])
        with self.Session() as db:
            job = db.get(TrainingJob, job_id)
            job.status = "completed"
            db.commit()

        deleted = self.client.post(
            "/api/training/batch-delete",
            json={"ids": [str(job_id)]},
            headers=self.headers,
        )
        retried = self._run_automl()

        self.assertEqual(deleted.status_code, 200, deleted.text)
        self.assertEqual(deleted.json()["deleted"], 1)
        self.assertEqual(retried.status_code, 409, retried.text)
        self.assertEqual(
            retried.json()["detail"]["code"],
            "EXPERIMENT_ALREADY_HAS_AUTOML_JOB",
        )

    def test_automl_delete_removes_training_job_and_experiment(self):
        created = self._run_automl()
        self.assertEqual(created.status_code, 202, created.text)
        job_id = uuid.UUID(created.json()["job_id"])
        experiment_id = self.experiment_id
        with self.Session() as db:
            job = db.get(TrainingJob, job_id)
            job.status = "completed"
            db.commit()

        deleted = self.client.delete(
            f"/api/training/automl/jobs/{job_id}",
            headers=self.headers,
        )

        self.assertEqual(deleted.status_code, 200, deleted.text)
        self.assertEqual(deleted.json(), {
            "deleted": 1,
            "experiment_deleted": True,
        })
        with self.Session() as db:
            self.assertIsNone(db.get(TrainingJob, job_id))
            self.assertIsNone(db.get(Experiment, experiment_id))

    def test_ordinary_training_job_does_not_occupy_experiment(self):
        with self.Session() as db:
            db.add(TrainingJob(
                project_id=self.project_id,
                user_id=self.user_id,
                experiment_id=self.experiment_id,
                name="ordinary-training",
                operator_id="random_forest",
                status="completed",
            ))
            db.commit()

        response = self._run_automl()

        self.assertEqual(response.status_code, 202, response.text)

    def test_automl_job_list_includes_experiment_name(self):
        created = self._run_automl()
        self.assertEqual(created.status_code, 202, created.text)

        response = self.client.get(
            "/api/training/automl/jobs",
            params={"project_id": str(self.project_id)},
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 200, response.text)
        item = next(row for row in response.json() if row["id"] == created.json()["job_id"])
        self.assertTrue(item["experiment_name"].startswith("AutoML API "))
        self.assertEqual(item["project_name"], "AutoML API")

    def test_experiment_list_reports_automl_binding(self):
        created = self._run_automl()
        self.assertEqual(created.status_code, 202, created.text)

        response = self.client.get(
            "/api/experiments",
            params={"project_id": str(self.project_id)},
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 200, response.text)
        item = next(
            row for row in response.json()["items"]
            if row["id"] == str(self.experiment_id)
        )
        self.assertIs(item["automl_used"], True)
        self.assertEqual(item["automl_job_id"], created.json()["job_id"])

    def test_target_column_and_target_columns_are_mutually_exclusive(self):
        response = self.client.post("/api/training/automl/run", json={
            "project_id": str(self.project_id),
            "experiment_id": str(self.experiment_id),
            "dataset_artifact_id": str(self.dataset_id),
            "target_column": "quality",
            "target_columns": ["quality"],
            "task": "classification",
        }, headers=self.headers)

        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(response.json()["detail"]["code"], "AUTOML_CONFIG_INVALID")
        self.assertEqual(self.dispatcher.enqueued, [])

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

    def test_four_candidate_ids_are_validated_by_the_automl_resolver(self):
        response = self.client.post("/api/training/automl/run", json={
            "project_id": str(self.project_id),
            "experiment_id": str(self.experiment_id),
            "dataset_artifact_id": str(self.dataset_id),
            "target_column": "quality",
            "task": "classification",
            "candidate_ids": [
                "random_forest",
                "gradient_boosting",
                "logistic_regression",
                "does_not_exist",
            ],
        }, headers=self.headers)

        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(response.json()["detail"]["code"], "AUTOML_CONFIG_INVALID")
        self.assertEqual(self.dispatcher.enqueued, [])

    def test_ten_algorithm_candidates_are_accepted(self):
        candidate_ids = [
            "LGB_v1", "LGB_v2", "XGB_v1", "XGB_v2", "CAT_v1",
            "CAT_v2", "GBDT_v1", "RF_v1", "ET_v1", "HGB_v1",
        ]
        response = self.client.post("/api/training/automl/run", json={
            "project_id": str(self.project_id),
            "experiment_id": str(self.experiment_id),
            "dataset_artifact_id": str(self.dataset_id),
            "target_column": "quality",
            "task": "classification",
            "candidate_ids": candidate_ids,
        }, headers=self.headers)

        self.assertEqual(response.status_code, 202, response.text)
        with self.Session() as db:
            job = db.query(TrainingJob).filter(
                TrainingJob.id == uuid.UUID(response.json()["job_id"])
            ).one()
            self.assertEqual(job.params["candidate_ids"], candidate_ids)

    def test_new_search_request_persists_resolved_family_contract(self):
        response = self.client.post("/api/training/automl/run", json={
            "project_id": str(self.project_id),
            "experiment_id": str(self.experiment_id),
            "dataset_artifact_id": str(self.dataset_id),
            "target_column": "quality",
            "task": "classification",
            "algorithm_ids": ["gbdt", "random_forest"],
            "search_method": "bayesian",
            "max_trials": 20,
            "time_budget": 3600,
        }, headers={
            **self.headers,
            "X-Request-ID": str(uuid.uuid4()),
            "Idempotency-Key": f"automl-new-{uuid.uuid4().hex}",
        })

        self.assertEqual(response.status_code, 202, response.text)
        with self.Session() as db:
            job = db.query(TrainingJob).filter(
                TrainingJob.id == uuid.UUID(response.json()["job_id"])
            ).one()
            self.assertEqual(job.params["search_contract"], "optuna_v1")
            self.assertEqual(job.params["algorithm_ids"], ["gbdt", "random_forest"])
            self.assertEqual(job.params["search_method"], "bayesian")
            self.assertEqual(job.params["max_trials"], 20)
            self.assertEqual(job.params["time_budget"], 3600)

    def test_new_search_rejects_trial_budget_smaller_than_selected_family_count(self):
        response = self.client.post("/api/training/automl/run", json={
            "project_id": str(self.project_id),
            "experiment_id": str(self.experiment_id),
            "dataset_artifact_id": str(self.dataset_id),
            "target_column": "quality",
            "task": "classification",
            "algorithm_ids": ["gbdt", "random_forest", "extra_trees", "hist_gradient_boosting", "lightgbm", "xgboost"],
            "search_method": "bayesian",
            "max_trials": 5,
            "time_budget": 3600,
        }, headers={
            **self.headers,
            "X-Request-ID": str(uuid.uuid4()),
            "Idempotency-Key": f"automl-budget-families-{uuid.uuid4().hex}",
        })

        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(response.json()["detail"]["code"], "AUTOML_SEARCH_CONFIG_INVALID")
        self.assertEqual(self.dispatcher.enqueued, [])

    def test_new_search_request_requires_request_id_and_idempotency_key(self):
        payload = {
            "project_id": str(self.project_id),
            "experiment_id": str(self.experiment_id),
            "dataset_artifact_id": str(self.dataset_id),
            "target_column": "quality",
            "task": "classification",
            "algorithm_ids": ["gbdt"],
            "search_method": "bayesian",
            "max_trials": 20,
            "time_budget": 3600,
        }
        missing_request_id = self.client.post(
            "/api/training/automl/run",
            json=payload,
            headers={**self.headers, "Idempotency-Key": "automl-request-context"},
        )
        self.assertEqual(missing_request_id.status_code, 400, missing_request_id.text)
        self.assertEqual(missing_request_id.json()["detail"]["code"], "REQUEST_ID_REQUIRED")

        missing_idempotency_key = self.client.post(
            "/api/training/automl/run",
            json=payload,
            headers={**self.headers, "X-Request-ID": str(uuid.uuid4())},
        )
        self.assertEqual(missing_idempotency_key.status_code, 400, missing_idempotency_key.text)
        self.assertEqual(missing_idempotency_key.json()["detail"]["code"], "IDEMPOTENCY_KEY_REQUIRED")

    def test_new_and_legacy_algorithm_fields_are_mutually_exclusive(self):
        response = self.client.post("/api/training/automl/run", json={
            "project_id": str(self.project_id),
            "experiment_id": str(self.experiment_id),
            "dataset_artifact_id": str(self.dataset_id),
            "target_column": "quality",
            "task": "classification",
            "algorithm_ids": ["gbdt"],
            "candidate_ids": ["GBDT_v1"],
            "search_method": "grid",
            "max_trials": 5,
            "time_budget": 60,
        }, headers={
            **self.headers,
            "X-Request-ID": str(uuid.uuid4()),
            "Idempotency-Key": f"automl-mutual-{uuid.uuid4().hex}",
        })

        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(response.json()["detail"]["code"], "AUTOML_SEARCH_CONFIG_INVALID")
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

    def test_input_columns_are_accepted_and_persisted(self):
        response = self.client.post("/api/training/automl/run", json={
            "project_id": str(self.project_id),
            "experiment_id": str(self.experiment_id),
            "dataset_artifact_id": str(self.dataset_id),
            "target_column": "quality",
            "input_columns": ["current", "force"],
        }, headers=self.headers)

        self.assertEqual(response.status_code, 202, response.text)
        with self.Session() as db:
            job = db.query(TrainingJob).filter(
                TrainingJob.id == uuid.UUID(response.json()["job_id"])
            ).one()
            self.assertEqual(job.params["input_columns"], ["current", "force"])

    def test_invalid_input_columns_are_rejected_before_job_creation_or_queueing(self):
        invalid_column_sets = (
            [],
            ["current", "current"],
            ["quality"],
            ["unknown"],
            ["material"],
        )
        with self.Session() as db:
            initial_job_count = db.query(TrainingJob).count()

        for input_columns in invalid_column_sets:
            with self.subTest(input_columns=input_columns):
                response = self.client.post("/api/training/automl/run", json={
                    "project_id": str(self.project_id),
                    "experiment_id": str(self.experiment_id),
                    "dataset_artifact_id": str(self.dataset_id),
                    "target_column": "quality",
                    "input_columns": input_columns,
                }, headers=self.headers)

                self.assertEqual(response.status_code, 400, response.text)
                self.assertEqual(response.json()["detail"]["code"], "AUTOML_CONFIG_INVALID")

        self.assertEqual(self.dispatcher.enqueued, [])
        with self.Session() as db:
            self.assertEqual(db.query(TrainingJob).count(), initial_job_count)

    def test_cross_validation_configuration_is_accepted_and_persisted(self):
        response = self.client.post("/api/training/automl/run", json={
            "project_id": str(self.project_id),
            "experiment_id": str(self.experiment_id),
            "dataset_artifact_id": str(self.dataset_id),
            "target_column": "quality",
            "cross_validation_enabled": True,
            "cross_validation_folds": 4,
        }, headers=self.headers)

        self.assertEqual(response.status_code, 202, response.text)
        with self.Session() as db:
            job = db.query(TrainingJob).filter(
                TrainingJob.id == uuid.UUID(response.json()["job_id"])
            ).one()
            self.assertEqual(job.params["cross_validation_enabled"], True)
            self.assertEqual(job.params["cross_validation_folds"], 4)

    def test_invalid_enabled_cross_validation_folds_return_stable_business_error(self):
        for folds in (None, 6):
            with self.subTest(folds=folds):
                response = self.client.post("/api/training/automl/run", json={
                    "project_id": str(self.project_id),
                    "experiment_id": str(self.experiment_id),
                    "dataset_artifact_id": str(self.dataset_id),
                    "target_column": "quality",
                    "cross_validation_enabled": True,
                    "cross_validation_folds": folds,
                }, headers=self.headers)

                self.assertEqual(response.status_code, 400, response.text)
                self.assertEqual(response.json()["detail"]["code"], "AUTOML_CONFIG_INVALID")
                self.assertEqual(self.dispatcher.enqueued, [])


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
