"""字段角色排除挂钩（补齐路线第一批 P1，D5）测试。

覆盖（技术方案 §11.1 test_automl_excluded_columns.py 行）：
- resolve_automl_feature_columns 差集语义：显式白名单与默认数值列两路径；
- 默认行为零变化：excluded_columns=None/[] 与原调用完全等价；
- 目标列不可排除、排除列必须在数据集中、差集后为空显式报错；
- API 契约：excluded_columns 进 TrainingJob.params；非法值 400。
"""
import tempfile
import unittest
import uuid
from pathlib import Path

import numpy as np
import pandas as pd
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.experiment import Experiment
from app.models.project import Project
from app.models.training import TrainingJob
from app.models.user import User
from app.services.automl_execution import resolve_automl_feature_columns


def _frame() -> pd.DataFrame:
    rng = np.random.default_rng(7)
    return pd.DataFrame({
        "torque": rng.normal(size=40),
        "current": rng.normal(size=40),
        "vin": [f"VIN{i:03d}" for i in range(40)],  # 非数值列
        "quality": [int(value) for value in rng.normal(size=40) > 0],
    })


class TestResolveExcludedColumns(unittest.TestCase):
    def test_none_keeps_default_behavior(self):
        frame = _frame()
        # 默认数值列路径：None 与不传完全等价
        baseline = resolve_automl_feature_columns(frame, "quality", None)
        self.assertEqual(
            baseline,
            resolve_automl_feature_columns(frame, "quality", None, excluded_columns=None),
        )
        # 显式白名单路径：None 与不传完全等价
        explicit = resolve_automl_feature_columns(
            frame, "quality", ["torque", "current"],
        )
        self.assertEqual(
            explicit,
            resolve_automl_feature_columns(
                frame, "quality", ["torque", "current"], excluded_columns=None,
            ),
        )
        # 空列表同样零变化
        self.assertEqual(
            resolve_automl_feature_columns(frame, "quality", None, excluded_columns=[]),
            baseline,
        )

    def test_explicit_list_difference_semantics(self):
        frame = _frame()
        result = resolve_automl_feature_columns(
            frame, "quality", ["torque", "current"],
            excluded_columns=["current"],
        )
        self.assertEqual(result, ["torque"])

    def test_default_numeric_path_excludes_columns(self):
        frame = _frame()
        baseline = resolve_automl_feature_columns(frame, "quality", None)
        self.assertIn("current", baseline)
        result = resolve_automl_feature_columns(
            frame, "quality", None, excluded_columns=["current"],
        )
        self.assertNotIn("current", result)
        self.assertIn("torque", result)

    def test_target_column_cannot_be_excluded(self):
        frame = _frame()
        with self.assertRaises(ValueError) as ctx:
            resolve_automl_feature_columns(
                frame, "quality", ["torque"], excluded_columns=["quality"],
            )
        self.assertIn("cannot be excluded", str(ctx.exception))

    def test_excluded_column_must_exist(self):
        frame = _frame()
        with self.assertRaises(ValueError) as ctx:
            resolve_automl_feature_columns(
                frame, "quality", ["torque"], excluded_columns=["ghost"],
            )
        self.assertIn("excluded columns are missing", str(ctx.exception))

    def test_exhausted_candidates_raise(self):
        frame = _frame()
        with self.assertRaises(ValueError) as ctx:
            resolve_automl_feature_columns(
                frame, "quality", ["torque"], excluded_columns=["torque"],
            )
        self.assertIn("after exclusions", str(ctx.exception))
        # 默认路径同样：唯一数值特征被排除后为空
        tiny = pd.DataFrame({"only": [1.0, 2.0], "quality": [0, 1]})
        with self.assertRaises(ValueError):
            resolve_automl_feature_columns(
                tiny, "quality", None, excluded_columns=["only"],
            )

    def test_multioutput_target_protection(self):
        frame = _frame().assign(quality2=[int(v) for v in np.random.default_rng(3).normal(size=40) > 0])
        with self.assertRaises(ValueError):
            resolve_automl_feature_columns(
                frame, "quality", ["torque", "current"],
                target_columns=["quality", "quality2"],
                excluded_columns=["quality2"],
            )


class TestExcludedColumnsAPI(unittest.TestCase):
    """API 契约：excluded_columns 进 params；非法值 400。"""

    @classmethod
    def setUpClass(cls):
        from app.api.auth import create_access_token
        from app.api.training import get_automl_dispatcher
        from app.database import get_db
        from app.main import app

        cls.engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
        )
        Base.metadata.create_all(cls.engine)
        cls.Session = sessionmaker(bind=cls.engine)
        cls.dataset_id = uuid.uuid4()
        cls.temporary = tempfile.TemporaryDirectory()
        dataset_path = Path(cls.temporary.name) / "excluded-api.csv"
        rng = np.random.default_rng(42)
        rows = [
            f"{rng.normal():.6f},{rng.normal():.6f},VIN{i:03d},{int(rng.normal() > 0)}"
            for i in range(60)
        ]
        dataset_path.write_text(
            "\n".join(["current,force,vin,quality", *rows]), encoding="utf-8",
        )
        with cls.Session() as db:
            user = User(username=f"excluded-api-{uuid.uuid4().hex}", password_hash="hash")
            db.add(user)
            db.flush()
            project = Project(name="Excluded API", owner_id=user.id)
            db.add(project)
            db.flush()
            experiment = Experiment(
                project_id=project.id, created_by=user.id,
                name="Excluded API", mlflow_experiment_id="excluded-api-experiment",
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

        from tests.test_automl_anomaly import FakeArtifactService, FakeDispatcher

        app.dependency_overrides[get_db] = override_db
        cls.artifacts = FakeArtifactService(cls.dataset_id, dataset_path)
        cls.dispatcher = FakeDispatcher()
        app.state.artifact_service_factory = lambda _db: cls.artifacts
        app.state.automl_dispatcher = cls.dispatcher
        cls.client = TestClient(app)
        cls.headers = {"Authorization": f"Bearer {create_access_token({'sub': str(cls.user_id)})}"}

    @classmethod
    def tearDownClass(cls):
        from app.database import get_db
        from app.main import app

        app.dependency_overrides.pop(get_db, None)
        for name in ("artifact_service_factory", "automl_dispatcher"):
            if hasattr(app.state, name):
                delattr(app.state, name)
        cls.temporary.cleanup()
        cls.engine.dispose()

    def setUp(self):
        self.dispatcher.enqueued.clear()
        with self.Session() as db:
            experiment = Experiment(
                project_id=self.project_id, created_by=self.user_id,
                name=f"Excluded API {uuid.uuid4().hex}",
                mlflow_experiment_id=f"excluded-api-{uuid.uuid4().hex}",
            )
            db.add(experiment)
            db.commit()
            self.experiment_id = experiment.id

    def _headers(self):
        return {
            **self.headers,
            "X-Request-ID": str(uuid.uuid4()),
            "Idempotency-Key": f"excluded-{uuid.uuid4().hex}",
        }

    def _payload(self, **overrides):
        payload = {
            "project_id": str(self.project_id),
            "experiment_id": str(self.experiment_id),
            "dataset_artifact_id": str(self.dataset_id),
            "task": "classification",
            "target_column": "quality",
            "input_columns": ["current", "force"],
            "algorithm_ids": ["random_forest", "hist_gradient_boosting"],
            "search_method": "random",
        }
        payload.update(overrides)
        return payload

    def test_excluded_columns_reach_job_params(self):
        from app.models.training import TrainingJob

        response = self.client.post(
            "/api/training/automl/run",
            json=self._payload(excluded_columns=["force"]),
            headers=self._headers(),
        )
        self.assertEqual(response.status_code, 202, response.text)
        self.assertEqual(response.json()["status"], "queued")
        with self.Session() as db:
            job = db.query(TrainingJob).filter(
                TrainingJob.id == uuid.UUID(response.json()["job_id"]),
            ).one()
            self.assertEqual(job.params["excluded_columns"], ["force"])
            self.assertEqual(job.params["input_columns"], ["current", "force"])

    def test_no_excluded_columns_defaults_to_none(self):
        from app.models.training import TrainingJob

        response = self.client.post(
            "/api/training/automl/run",
            json=self._payload(),
            headers=self._headers(),
        )
        self.assertEqual(response.status_code, 202, response.text)
        with self.Session() as db:
            job = db.query(TrainingJob).filter(
                TrainingJob.id == uuid.UUID(response.json()["job_id"]),
            ).one()
            self.assertIsNone(job.params.get("excluded_columns"))

    def test_unknown_excluded_column_rejected(self):
        response = self.client.post(
            "/api/training/automl/run",
            json=self._payload(excluded_columns=["ghost"]),
            headers=self._headers(),
        )
        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(response.json()["detail"]["code"], "AUTOML_CONFIG_INVALID")
        self.assertEqual(self.dispatcher.enqueued, [])

    def test_target_excluded_rejected(self):
        response = self.client.post(
            "/api/training/automl/run",
            json=self._payload(excluded_columns=["quality"]),
            headers=self._headers(),
        )
        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(self.dispatcher.enqueued, [])

    def test_exhausting_all_inputs_rejected(self):
        response = self.client.post(
            "/api/training/automl/run",
            json=self._payload(excluded_columns=["current", "force"]),
            headers=self._headers(),
        )
        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(self.dispatcher.enqueued, [])


class TestExcludedColumnsEngine(unittest.TestCase):
    """引擎级全链：带排除列的真训练任务，模型输入契约确实不含被排除列。

    F1 验收口径③「新场景 → 字段角色 → 训练特征排除全链生效」的直接证据——
    上面的 API 测试只证明参数进了任务，这里证明引擎真跑后的输入契约。
    """

    def setUp(self):
        from tests.test_automl_tracking import FakeArtifactService, FakeTracking

        self.temporary = tempfile.TemporaryDirectory()
        self.engine = create_engine(f"sqlite:///{Path(self.temporary.name) / 'excluded.db'}")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        self.dataset_id = uuid.uuid4()
        dataset_path = Path(self.temporary.name) / "dataset.csv"
        # vin_id 是数值型的样本序号（字段角色 sample_key 的典型形态）：与标签
        # 完全无关，但不排除就会进模型输入
        rows = ["current,force,vin_id,quality"] + [
            f"{index % 8},{index % 5},{index},{int((index % 8) + (index % 5) > 5)}"
            for index in range(150)
        ]
        dataset_path.write_text("\n".join(rows), encoding="utf-8")
        with self.Session() as db:
            user = User(username=f"excluded-engine-{uuid.uuid4().hex[:8]}", password_hash="hash")
            db.add(user)
            db.flush()
            project = Project(name="Excluded engine", owner_id=user.id)
            db.add(project)
            db.flush()
            experiment = Experiment(
                project_id=project.id, created_by=user.id, name="Excluded engine",
                mlflow_experiment_id=f"excluded-engine-{uuid.uuid4().hex[:8]}",
            )
            db.add(experiment)
            db.commit()
            self.user_id, self.project_id, self.experiment_id = user.id, project.id, experiment.id
        self.artifacts = FakeArtifactService(self.dataset_id, dataset_path)
        self.tracking = FakeTracking()

    def tearDown(self):
        self.engine.dispose()
        self.temporary.cleanup()

    def _run(self, **extra_params):
        from app.services.automl_execution import AutoMLDependencies, execute_automl_job

        params = {
            "search_contract": "optuna_v1",
            "target_column": "quality",
            "task": "classification",
            "algorithm_ids": ["gbdt"],
            "search_method": "random",
            "max_trials": 5,
            "time_budget": 60,
            "cross_validation_enabled": False,
            "cross_validation_folds": None,
        }
        params.update(extra_params)
        with self.Session() as db:
            job = TrainingJob(
                project_id=self.project_id, user_id=self.user_id,
                experiment_id=self.experiment_id, dataset_artifact_id=self.dataset_id,
                name=f"excluded-engine-{uuid.uuid4().hex[:8]}", operator_id="automl",
                params=params, status="pending",
            )
            db.add(job)
            db.commit()
            job_id = job.id
        result = execute_automl_job(job_id, dependencies=AutoMLDependencies(
            session_factory=self.Session,
            artifact_service_factory=lambda _db: self.artifacts,
            tracking_factory=lambda: self.tracking,
            worker_id="worker-1", task_id="task-1",
        ))
        self.assertEqual(result.status, "completed", result.status)
        with self.Session() as db:
            job = db.get(TrainingJob, job_id)
            return list(job.metrics["input_contract"]["input_columns"])

    def test_excluded_column_is_absent_from_the_trained_input_contract(self):
        inputs = self._run(
            input_columns=["current", "force", "vin_id"],
            excluded_columns=["vin_id"],
        )
        self.assertEqual(inputs, ["current", "force"])

    def test_exclusion_is_equivalent_to_never_selecting_the_column(self):
        # 「选中后排除」与「从不选」产出同一份输入契约（默认行为零变化的等价性）
        explicit = self._run(input_columns=["current", "force"])
        via_exclusion = self._run(
            input_columns=["current", "force", "vin_id"],
            excluded_columns=["vin_id"],
        )
        self.assertEqual(via_exclusion, explicit)

    def test_without_exclusions_every_selected_column_is_used(self):
        inputs = self._run(input_columns=["current", "force", "vin_id"])
        self.assertEqual(inputs, ["current", "force", "vin_id"])
