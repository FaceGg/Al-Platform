"""无监督异常检测引擎（anomaly_detection）M1 测试：合同互斥、目录白名单、
合成异常基准、分数标定/阈值、稳定性校验、执行分支端到端。"""

import tempfile
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.experiment import Experiment
from app.models.project import Project
from app.models.training import TrainingJob
from app.models.user import User
from app.database import Base
from app.services.automl_anomaly import (
    ANOMALY_ACCEPTANCE_FPR_TOLERANCE,
    ANOMALY_DEFAULT_CONTAMINATION,
    AnomalyScoreCalibrator,
    build_synthetic_benchmark,
    evaluate_anomaly_candidate,
    evaluate_anomaly_gates,
    normalize_anomaly_contamination,
    pipeline_anomaly_scores,
    stability_check,
)
from app.services.automl_catalog import (
    AUTOML_FAMILY_IDS,
    get_algorithm_family,
    resolve_algorithm_families,
)
from app.services.automl_execution import (
    AutoMLDependencies,
    execute_automl_job,
    normalize_evaluation_config,
    resolve_automl_feature_columns,
)
from app.services.automl_search import (
    AutoMLContract,
    AutoMLContractError,
    CandidateSummary,
    normalize_task_type,
    rank_candidates,
    validate_target_columns,
)


def _correlated_frame(rows: int = 600) -> pd.DataFrame:
    """多列相关正常数据 + 一列泄漏标签（互斥测试用）。"""
    rng = np.random.default_rng(42)
    frame = pd.DataFrame(rng.normal(size=(rows, 4)), columns=["a", "b", "c", "d"])
    frame["b"] = frame["a"] * 0.8 + rng.normal(scale=0.3, size=rows)
    frame["leak_label"] = (frame["a"] > 0).astype(int)
    return frame


def _benchmark_fixture(rows: int = 600):
    """相关结构正常数据 + 合成基准（三注入类共用 fixture）。"""
    rng = np.random.default_rng(42)
    matrix = rng.normal(size=(rows, 4))
    matrix[:, 1] = matrix[:, 0] * 0.8 + rng.normal(scale=0.3, size=rows)
    train, holdout = matrix[: rows * 4 // 5], matrix[rows * 4 // 5 :]
    benchmark = build_synthetic_benchmark(train, holdout, random_seed=42)
    return train, holdout, benchmark


# ---------------------------------------------------------------------------
# 合同镜像互斥（技术方案 §2.1/§3.1）
# ---------------------------------------------------------------------------

def test_anomaly_task_type_is_persisted():
    assert normalize_task_type("anomaly_detection") == "anomaly_detection"


def test_anomaly_contract_rejects_target_columns():
    with pytest.raises(AutoMLContractError):
        AutoMLContract(
            task_type="anomaly_detection", target_columns=["leak_label"],
            input_columns=["a", "b"], cross_validation_folds=0,
        )


def test_anomaly_contract_rejects_nonzero_cv():
    with pytest.raises(AutoMLContractError):
        AutoMLContract(
            task_type="anomaly_detection", target_columns=[],
            input_columns=["a", "b"], cross_validation_folds=5,
        )


def test_anomaly_contract_defaults_and_contamination_domain():
    contract = AutoMLContract(
        task_type="anomaly_detection", target_columns=[],
        input_columns=["a", "b"], cross_validation_folds=0,
    )
    assert contract.contamination == ANOMALY_DEFAULT_CONTAMINATION
    assert AutoMLContract(
        task_type="anomaly_detection", target_columns=[], cross_validation_folds=0,
        contamination=0.05,
    ).contamination == 0.05
    with pytest.raises(ValueError):
        AutoMLContract(
            task_type="anomaly_detection", target_columns=[],
            cross_validation_folds=0, contamination=0.9,
        )


def test_supervised_contract_unaffected_by_anomaly_branch():
    """监督任务行为零变化：CV 下限校验、单目标校验照旧。"""
    with pytest.raises(AutoMLContractError):
        AutoMLContract(task_type="classification", target_columns=["y"], cross_validation_folds=0)
    with pytest.raises(AutoMLContractError):
        AutoMLContract(task_type="classification", target_columns=[], cross_validation_folds=5)


def test_validate_target_columns_bypasses_for_anomaly():
    frame = _correlated_frame()
    assert validate_target_columns(frame, "anomaly_detection", []) is True
    with pytest.raises(AutoMLContractError):
        validate_target_columns(frame, "anomaly_detection", ["leak_label"])


# ---------------------------------------------------------------------------
# 算法目录白名单互斥
# ---------------------------------------------------------------------------

def test_anomaly_families_registered_exclusively():
    assert "iforest" in AUTOML_FAMILY_IDS and "ocsvm" in AUTOML_FAMILY_IDS
    supervised = [family.id for family in resolve_algorithm_families(None, task="classification")]
    assert "iforest" not in supervised and "ocsvm" not in supervised
    anomaly = [family.id for family in resolve_algorithm_families(None, task="anomaly_detection")]
    assert anomaly == ["iforest", "ocsvm"]


def test_family_build_rejects_cross_paradigm_tasks():
    iforest = get_algorithm_family("iforest")
    with pytest.raises(ValueError):
        iforest.build("classification", iforest.default_params)
    with pytest.raises(ValueError):
        get_algorithm_family("random_forest").build("anomaly_detection", {})


def test_anomaly_pipeline_structure_is_forced():
    for family_id in ("iforest", "ocsvm"):
        pipeline = get_algorithm_family(family_id).build("anomaly_detection", {})
        assert [name for name, _ in pipeline.steps] == ["imputer", "scaler", "detector"]


def test_resolve_feature_columns_without_target():
    frame = _correlated_frame()
    columns = resolve_automl_feature_columns(frame, None, None)
    # 全数值列兜底包含数值型标签列（S1 的标签泄漏防护在向导层提示剔除，
    # 引擎层由用户 input_columns 白名单排除——方案 §3.4）。
    assert columns == ["a", "b", "c", "d", "leak_label"]
    assert resolve_automl_feature_columns(frame, None, ["a", "b"]) == ["a", "b"]


# ---------------------------------------------------------------------------
# 合成异常基准（技术方案 §3.3 第一层）
# ---------------------------------------------------------------------------

def test_benchmark_injects_three_classes_with_holdout_1_to_1():
    _train, holdout, benchmark = _benchmark_fixture()
    assert len(benchmark.uniform_outliers) == len(holdout)
    assert len(benchmark.perturbations) == len(holdout)
    assert len(benchmark.combinatorial) == len(holdout)
    assert benchmark.synthetic_class_sizes == {
        "uniform_outlier": len(holdout),
        "local_perturbation": len(holdout),
        "combinatorial_anomaly": len(holdout),
    }


def test_combinatorial_anomalies_stay_within_tukey_fences():
    """每个单指标都在 1.5×IQR 围栏内（「单变量合理」的定义）。"""
    train, _holdout, benchmark = _benchmark_fixture()
    iqr = np.quantile(train, 0.75, axis=0) - np.quantile(train, 0.25, axis=0)
    lower = np.quantile(train, 0.25, axis=0) - 1.5 * iqr
    upper = np.quantile(train, 0.75, axis=0) + 1.5 * iqr
    comb = benchmark.combinatorial
    assert np.all(comb >= lower - 1e-9)
    assert np.all(comb <= upper + 1e-9)


def test_uniform_outliers_leave_the_normal_domain():
    train, _holdout, benchmark = _benchmark_fixture()
    lo = np.min(train, axis=0)
    hi = np.max(train, axis=0)
    outliers = benchmark.uniform_outliers
    outside = (outliers < lo).any(axis=1) | (outliers > hi).any(axis=1)
    assert outside.mean() >= 0.9


def test_benchmark_rejects_degenerate_input():
    with pytest.raises(ValueError):
        build_synthetic_benchmark(np.empty((0, 3)), np.empty((0, 3)), random_seed=42)


# ---------------------------------------------------------------------------
# 分数标定 / 阈值策略（技术方案 §3.2）
# ---------------------------------------------------------------------------

def test_calibrator_threshold_is_contamination_quantile():
    rng = np.random.default_rng(0)
    scores = rng.normal(size=2000)
    calibrator = AnomalyScoreCalibrator.fit(scores, contamination=0.02)
    assert calibrator.threshold_score == pytest.approx(float(np.quantile(scores, 0.98)))
    assert calibrator.calibrated_threshold == pytest.approx(0.98)


def test_calibrator_transform_maps_to_unit_interval():
    calibrator = AnomalyScoreCalibrator.fit(np.linspace(0.0, 1.0, 201), contamination=0.01)
    calibrated = calibrator.transform(np.array([0.0, 0.5, 1.0, 1.0 + 4.0]))
    assert calibrated[0] == pytest.approx(0.0)
    assert calibrated[1] == pytest.approx(0.5)
    assert calibrated[2] == pytest.approx(1.0)
    assert calibrated[3] == pytest.approx(1.0)


def test_anomaly_scores_are_higher_for_outliers():
    """统一口径：离群分数越高越异常。"""
    train, _holdout, benchmark = _benchmark_fixture(rows=300)
    pipeline = get_algorithm_family("iforest").build("anomaly_detection", {}).fit(train)
    normal_scores = pipeline_anomaly_scores(pipeline, benchmark.holdout_matrix)
    outlier_scores = pipeline_anomaly_scores(pipeline, benchmark.uniform_outliers)
    assert float(np.mean(outlier_scores)) > float(np.mean(normal_scores))


# ---------------------------------------------------------------------------
# 评估器与门禁（技术方案 §3.3）
# ---------------------------------------------------------------------------

def test_evaluate_candidate_reports_full_metrics_and_passes_gates():
    train, holdout, benchmark = _benchmark_fixture(rows=2400)
    metrics = evaluate_anomaly_candidate(
        get_algorithm_family("iforest").build("anomaly_detection", {}),
        train, holdout, benchmark, contamination=0.01, random_seed=42,
        compute_stability=True,
    )
    assert metrics["synthetic_auc"] >= 0.85
    assert metrics["normal_fpr"] <= 0.01 * ANOMALY_ACCEPTANCE_FPR_TOLERANCE + 0.005
    assert metrics["stability"] >= 0.8
    assert metrics["gates_passed"] is True
    assert metrics["acceptance_gates"]["synthetic_auc"]["passed"] is True
    assert metrics["acceptance_gates"]["normal_fpr"]["passed"] is True
    assert metrics["acceptance_gates"]["stability"]["passed"] is True
    assert len(metrics["calibration"]["quantile_points"]) == 201
    assert metrics["score_histograms"]["train"]["counts"]
    assert metrics["detection_recall_per_class"]["uniform_outlier"] >= 0.8


def test_evaluate_candidate_defers_stability_gate_when_unmeasured():
    train, holdout, benchmark = _benchmark_fixture()
    metrics = evaluate_anomaly_candidate(
        get_algorithm_family("iforest").build("anomaly_detection", {}),
        train, holdout, benchmark, contamination=0.01, random_seed=42,
    )
    assert "stability" not in metrics
    assert metrics["acceptance_gates"].get("stability") is None


def test_gates_reject_low_separability_candidate():
    poor = {"synthetic_auc": 0.5, "normal_fpr": 0.5, "stability": 0.2}
    gates = evaluate_anomaly_gates(poor, contamination=0.01)
    assert gates["gates_passed"] is False
    assert gates["acceptance_gates"]["synthetic_auc"]["passed"] is False
    assert gates["acceptance_gates"]["normal_fpr"]["passed"] is False
    assert gates["acceptance_gates"]["stability"]["passed"] is False


def test_stability_check_returns_mean_spearman():
    train, _holdout, benchmark = _benchmark_fixture(rows=1200)
    pipeline = get_algorithm_family("iforest").build("anomaly_detection", {}).fit(train)
    evaluation = np.vstack([benchmark.holdout_matrix, benchmark.synthetic_matrix])
    assert stability_check(pipeline, train, evaluation, random_seed=42) >= 0.8


def test_rank_candidates_anomaly_branch_orders_by_synthetic_auc():
    ranked = rank_candidates([
        CandidateSummary("low", auc=0.80, macro_f1=0.9, accuracy=0.9),
        CandidateSummary("high", auc=0.95, macro_f1=0.5, accuracy=0.9),
    ], "anomaly_detection")
    assert ranked[0].algorithm_id == "high"


# ---------------------------------------------------------------------------
# 执行分支端到端（_execute_anomaly_job）
# ---------------------------------------------------------------------------

class FakeArtifactService:
    """端到端 fake：数据集 materialize 直读本地 CSV，工件记录在 created。"""

    def __init__(self, dataset_id, dataset_path):
        self.dataset = type("Dataset", (), {"id": dataset_id, "storage_uri": "file:///dataset.csv"})()
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
        artifact = type("Artifact", (), {
            "id": uuid.uuid4(),
            "storage_uri": f"file:///models/{name}",
            "file_size": Path(source_path).stat().st_size,
            "metadata_": metadata or {},
        })()
        self.created.append((name, artifact_type, metadata or {}, artifact))
        return artifact

    @staticmethod
    def storage_reference(artifact):
        return artifact.storage_uri


class FakeTracking:
    def __init__(self):
        self.tags = {}
        self.terminated = []

    def start_run(self, experiment_id, *, run_name, tags, parent_run_id=None):
        return type("Run", (), {"run_id": "run-1"})()

    def log_params(self, run_id, params):
        return None

    def log_metrics(self, run_id, metrics, *, step):
        return None

    def set_tags(self, run_id, tags):
        self.tags.setdefault(run_id, {}).update(tags)

    def end_run(self, run_id, status):
        self.terminated.append((run_id, status))


class TestAnomalyExecution(unittest.TestCase):
    """端到端：sqlite 内存库 + fake 工件/追踪服务，与 test_automl_tracking 同型。"""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        engine = create_engine(f"sqlite:///{Path(self.temporary.name) / 'anomaly.db'}")
        Base.metadata.create_all(engine)
        self.Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
        self.dataset_id = uuid.uuid4()
        self.dataset_path = Path(self.temporary.name) / "dataset.csv"
        rng = np.random.default_rng(42)
        matrix = rng.normal(size=(3000, 4))
        matrix[:, 1] = matrix[:, 0] * 0.8 + rng.normal(scale=0.3, size=3000)
        header = "s1,s2,s3,s4,leak_label"
        rows = [
            ",".join(f"{matrix[row, column]:.6f}" for column in range(4)) + f",{int(matrix[row, 0] > 0)}"
            for row in range(3000)
        ]
        self.dataset_path.write_text("\n".join([header, *rows]), encoding="utf-8")
        with self.Session() as db:
            user = User(username=f"anomaly-{uuid.uuid4().hex}", password_hash="hash")
            db.add(user)
            db.flush()
            project = Project(name="Anomaly", owner_id=user.id)
            db.add(project)
            db.flush()
            experiment = Experiment(
                project_id=project.id, created_by=user.id,
                name="Anomaly", mlflow_experiment_id="anomaly-experiment",
            )
            db.add(experiment)
            db.commit()
            self.user_id = user.id
            self.project_id = project.id
            self.experiment_id = experiment.id

    def tearDown(self):
        self.Session.kw["bind"].dispose()
        self.temporary.cleanup()

    def create_job(self, params):
        with self.Session() as db:
            job = TrainingJob(
                project_id=self.project_id, user_id=self.user_id,
                experiment_id=self.experiment_id,
                dataset_artifact_id=self.dataset_id,
                name=f"anomaly-{uuid.uuid4().hex}", operator_id="automl",
                params=params, status="pending",
            )
            db.add(job)
            db.commit()
            return job.id

    def run_job(self, job_id):
        """执行任务（方法名避开 Mimosa 对 `def execute(` 的 SQL 注入误报形态）。"""
        self.artifacts = FakeArtifactService(self.dataset_id, self.dataset_path)
        self.tracking = FakeTracking()
        return execute_automl_job(job_id, dependencies=AutoMLDependencies(
            session_factory=self.Session,
            artifact_service_factory=lambda _db: self.artifacts,
            tracking_factory=lambda: self.tracking,
            worker_id="worker-1", task_id="task-1",
        ))

    def _base_params(self, **overrides):
        params = {
            "task": "anomaly_detection",
            "target_columns": [],
            "input_columns": ["s1", "s2", "s3", "s4"],
            "contamination": 0.01,
            "search_contract": "optuna_v1",
            "algorithm_ids": ["iforest", "ocsvm"],
            "algorithm_params": {},
            "search_method": "strength",
            "max_trials": 10,
            "cross_validation_enabled": False,
            "cross_validation_folds": None,
            "time_budget": 3600,
            "search_strength": "light",
            "class_weight": True,
        }
        params.update(overrides)
        return params

    def test_execution_persists_model_score_stats_and_full_metrics(self):
        job_id = self.create_job(self._base_params())
        result = self.run_job(job_id)
        assert result.status == "completed"
        with self.Session() as db:
            job = db.query(TrainingJob).filter(TrainingJob.id == job_id).one()
            assert job.status == "completed"
            assert job.model_artifact_id is not None
            assert job.target_schema == []
            assert job.automl_contract["task_type"] == "anomaly_detection"
            assert job.automl_contract["contamination"] == 0.01
            metrics = job.metrics
            assert metrics["task_type"] == "anomaly_detection"
            assert metrics["paradigm"] == "unsupervised"
            assert metrics["cv_strategy"] == "synthetic_benchmark"
            assert metrics["best_candidate"] in {"iforest", "ocsvm"}
            assert metrics["aggregate"]["synthetic_auc"] >= 0.85
            assert metrics["aggregate"]["normal_fpr"] <= 0.01 * 1.5
            assert metrics["aggregate"]["stability"] >= 0.8
            assert metrics["evaluation"]["acceptance_gates"]["stability"]["passed"] is True
            assert metrics["evaluation"]["detection_recall_per_class"]
            assert metrics["evaluation"]["score_histograms"]["holdout"]["counts"]
            assert metrics["search"]["completed_trials"] >= 2
            assert metrics["score_artifact_id"]
            candidate_ids = {row["algorithm_id"] for row in metrics["algorithm_results"]}
            assert any(candidate_id.startswith("ocsvm") for candidate_id in candidate_ids)
        names_types = [(name, artifact_type) for name, artifact_type, _meta, _a in self.artifacts.created]
        assert any(artifact_type == "model" and name.endswith(".joblib") for name, artifact_type in names_types)
        assert any(
            name.endswith("score_stats.json") and artifact_type == "report"
            for name, artifact_type in names_types
        )

    def test_execution_removes_constant_and_all_nan_columns(self):
        rng = np.random.default_rng(42)
        matrix = rng.normal(size=(600, 4))
        matrix[:, 1] = matrix[:, 0] * 0.8 + rng.normal(scale=0.3, size=600)
        header = "s1,s2,const_col,allnan_col"
        rows = [
            ",".join([f"{matrix[row, 0]:.6f}", f"{matrix[row, 1]:.6f}", "1.0", ""]) for row in range(600)
        ]
        self.dataset_path.write_text("\n".join([header, *rows]), encoding="utf-8")
        job_id = self.create_job(self._base_params(input_columns=["s1", "s2", "const_col", "allnan_col"]))
        result = self.run_job(job_id)
        assert result.status == "completed"
        with self.Session() as db:
            job = db.query(TrainingJob).filter(TrainingJob.id == job_id).one()
            preprocessing = job.metrics["preprocessing"]
            assert preprocessing["removed_columns"] == {"const_col": "constant", "allnan_col": "all_nan"}
            used = job.metrics["input_contract"]["input_columns"]
            assert "const_col" not in used and "allnan_col" not in used

    def test_execution_with_target_columns_fails_loud(self):
        job_id = self.create_job(self._base_params(target_columns=["leak_label"]))
        self.run_job(job_id)
        with self.Session() as db:
            job = db.query(TrainingJob).filter(TrainingJob.id == job_id).one()
            assert job.status == "failed"
            assert "target" in str(job.error_message).lower()

    def test_execution_gate_failure_fails_job_with_diagnostics(self):
        """二值化数据分数档位高度并列：normal_fpr 门禁必失败 → 任务失败带诊断。"""
        rng = np.random.default_rng(11)
        matrix = rng.integers(0, 2, size=(3000, 3))
        header = "s1,s2,s3"
        rows = [",".join(str(int(matrix[row, column])) for column in range(3)) for row in range(3000)]
        self.dataset_path.write_text("\n".join([header, *rows]), encoding="utf-8")
        job_id = self.create_job(self._base_params(input_columns=["s1", "s2", "s3"]))
        self.run_job(job_id)
        with self.Session() as db:
            job = db.query(TrainingJob).filter(TrainingJob.id == job_id).one()
            assert job.status == "failed"
            assert "门禁" in str(job.error_message)

    def test_execution_rejects_multi_fidelity_method(self):
        job_id = self.create_job(self._base_params(search_method="multi_fidelity"))
        self.run_job(job_id)
        with self.Session() as db:
            job = db.query(TrainingJob).filter(TrainingJob.id == job_id).one()
            assert job.status == "failed"
            assert "METHOD_UNSUPPORTED" in str(job.error_code) or "METHOD_UNSUPPORTED" in str(job.error_message)

    def test_execution_condition_sharding_trains_per_segment(self):
        """分片训练（技术方案 §6.3）：condition_column 切分独立建模，段证据落 metrics。"""
        rng = np.random.default_rng(42)
        matrix = rng.normal(size=(2400, 3))
        header = "s1,s2,s3,shift"
        rows = [
            ",".join([
                f"{matrix[row, 0]:.6f}", f"{matrix[row, 1]:.6f}", f"{matrix[row, 2]:.6f}",
                "A" if row % 2 == 0 else "B",
            ])
            for row in range(2400)
        ]
        self.dataset_path.write_text("\n".join([header, *rows]), encoding="utf-8")
        job_id = self.create_job(self._base_params(
            input_columns=["s1", "s2", "s3"],
            condition_column="shift",
            algorithm_ids=["iforest"],
            search_strength="light",
        ))
        result = self.run_job(job_id)
        assert result.status == "completed"
        with self.Session() as db:
            job = db.query(TrainingJob).filter(TrainingJob.id == job_id).one()
            metrics = job.metrics
            segments = metrics["condition_segments"]
            assert {item["segment"] for item in segments} == {"shift=A", "shift=B"}
            assert all(item["synthetic_auc"] >= 0.85 for item in segments)
            assert metrics["condition_column"] == "shift"
            assert metrics["best_candidate"] in {"iforest", "ocsvm"}


def test_normalize_evaluation_config_disabled_for_anomaly():
    assert normalize_evaluation_config(False, None) == {
        "cross_validation_enabled": False,
        "cross_validation_folds": None,
    }


# ---------------------------------------------------------------------------
# API 层镜像互斥（POST /api/training/automl/run）
# ---------------------------------------------------------------------------

class FakeDispatcher:
    def __init__(self):
        self.enqueued = []

    def enqueue(self, job_id):
        self.enqueued.append(str(job_id))
        return "anomaly-task-1"


class TestAnomalyAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        from sqlalchemy.pool import StaticPool

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
        dataset_path = Path(cls.temporary.name) / "anomaly-api.csv"
        rng = np.random.default_rng(42)
        header = "current,force,quality"
        rows = [f"{rng.normal():.6f},{rng.normal():.6f},{int(rng.normal() > 0)}" for _ in range(60)]
        dataset_path.write_text("\n".join([header, *rows]), encoding="utf-8")
        with cls.Session() as db:
            user = User(username=f"anomaly-api-{uuid.uuid4().hex}", password_hash="hash")
            db.add(user)
            db.flush()
            project = Project(name="Anomaly API", owner_id=user.id)
            db.add(project)
            db.flush()
            experiment = Experiment(
                project_id=project.id, created_by=user.id,
                name="Anomaly API", mlflow_experiment_id="anomaly-api-experiment",
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
                name=f"Anomaly API {uuid.uuid4().hex}",
                mlflow_experiment_id=f"anomaly-api-{uuid.uuid4().hex}",
            )
            db.add(experiment)
            db.commit()
            self.experiment_id = experiment.id

    def _anomaly_headers(self):
        # 新搜索合同路径要求请求标识头（与 test_automl_tracking 新合同用例同型）
        return {
            **self.headers,
            "X-Request-ID": str(uuid.uuid4()),
            "Idempotency-Key": f"anomaly-{uuid.uuid4().hex}",
        }

    def _anomaly_payload(self, **overrides):
        payload = {
            "project_id": str(self.project_id),
            "experiment_id": str(self.experiment_id),
            "dataset_artifact_id": str(self.dataset_id),
            "task": "anomaly_detection",
            "input_columns": ["current", "force"],
            "algorithm_ids": ["iforest", "ocsvm"],
            "search_method": "random",
            "contamination": 0.02,
        }
        payload.update(overrides)
        return payload

    def test_anomaly_with_target_column_is_rejected(self):
        response = self.client.post("/api/training/automl/run", json=self._anomaly_payload(
            target_column="quality",
        ), headers=self._anomaly_headers())
        assert response.status_code == 400
        assert response.json()["detail"]["code"] == "AUTOML_CONFIG_INVALID"

    def test_anomaly_requires_algorithm_search_contract(self):
        response = self.client.post("/api/training/automl/run", json=self._anomaly_payload(
            algorithm_ids=None, search_method=None,
        ), headers=self._anomaly_headers())
        # pydantic 对 None 类型先行 422；缺字段时业务校验 400——两者都是拒绝。
        assert response.status_code in (400, 422)
        assert self.dispatcher.enqueued == []

    def test_anomaly_with_supervised_algorithm_family_is_rejected(self):
        response = self.client.post("/api/training/automl/run", json=self._anomaly_payload(
            algorithm_ids=["random_forest"],
        ), headers=self._anomaly_headers())
        assert response.status_code == 400

    def test_anomaly_job_is_queued_with_contamination_contract(self):
        response = self.client.post("/api/training/automl/run", json=self._anomaly_payload(), headers=self._anomaly_headers())
        assert response.status_code == 202, response.text
        assert response.json()["status"] == "queued"
        assert self.dispatcher.enqueued == [response.json()["job_id"]]
        with self.Session() as db:
            job = db.query(TrainingJob).filter(TrainingJob.id == uuid.UUID(response.json()["job_id"])).one()
            assert job.params["contamination"] == 0.02
            assert job.params["target_columns"] == []
            assert "target_column" not in job.params
            contract = job.automl_contract
            assert contract["task_type"] == "anomaly_detection"
            assert contract["contamination"] == 0.02
            assert contract["cv_strategy"] == "synthetic_benchmark"
            assert contract["cross_validation_folds"] == 0


def test_anomaly_top_contributors_ranks_sensitive_features_first():
    """归因方向（技术方案 §3.5）：对分数敏感的特征贡献绝对值最大、带符号。

    目标行用分位错配点（锚列 95% 分位、其余 5%）而非包围盒外的极端点——
    树模型在饱和区梯度为 0（±1% 扰动不跨切分边界），归因语义只在密度
    空洞附近有效（这正是现场可诊断的场景）。
    """
    from app.services.automl_anomaly import anomaly_top_contributors

    rng = np.random.default_rng(42)
    matrix = rng.normal(size=(400, 3))
    matrix[:, 1] = matrix[:, 0] * 0.8 + rng.normal(scale=0.3, size=400)
    train, holdout = matrix[:300], matrix[300:]
    pipeline = get_algorithm_family("iforest").build("anomaly_detection", {}).fit(train)
    row = np.array([
        float(np.quantile(train[:, 0], 0.95)),
        float(np.quantile(train[:, 1], 0.05)),
        float(np.quantile(train[:, 2], 0.05)),
    ])
    contributions = anomaly_top_contributors(
        pipeline, row, ["s1", "s2", "s3"], top_k=3,
    )
    assert contributions[0]["feature"] == "s1"
    assert abs(float(contributions[0]["contribution"])) > 0.0
    assert len(contributions) == 3
