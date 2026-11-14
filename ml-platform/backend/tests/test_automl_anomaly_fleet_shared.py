"""无监督异常检测：机群共享模式（fleet_mode="shared"）专项测试。

覆盖本轮四项修复：

- **B2**（技术方案 §7.1）联合段不得携带分组身份列——全局模型学的是「同型设备
  共有的正常联合分布」，不是「哪台设备」。
- **B20**（§6.3 护栏语义）联合段语料 = 该工况列下的全量数据（含被段行数护栏
  并入默认段/被丢弃的小段行）。
- **B18** 机群共享模式缺 condition_column 必须明确失败，不得静默退化成普通训练。
- **B3** 无监督进度单调：运行期分子与终态 progress.completed 同一计数口径。

端到端夹具沿用 ``tests/test_automl_anomaly.py`` 的形态（sqlite 临时库 + fake
工件/追踪服务）；本文件自带一份副本，避免与并行编辑中的测试文件相互耦合。
"""

import tempfile
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.models.experiment import Experiment
from app.models.project import Project
from app.models.training import TrainingJob
from app.models.user import User
from app.database import Base
from app.services import automl_execution as automl_execution_module
from app.services.automl_execution import (
    AutoMLDependencies,
    _detect_group_identity_columns,
    execute_automl_job,
)


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


class _RecordingSession(Session):
    """仅本测试用的 Session 子类：commit 后抓取运行期进度快照。"""


def _fleet_rows(device_plan, *, seed=42):
    """构造机群 CSV（s1,s2,s3 数值特征 + device_code + shift 工况列）。

    device_plan: [(device_code, shift, row_count), ...]
    """
    rng = np.random.default_rng(seed)
    header = "s1,s2,s3,device_code,shift"
    rows: list[str] = []
    for device_code, shift, count in device_plan:
        matrix = rng.normal(size=(count, 3))
        matrix[:, 1] = matrix[:, 0] * 0.8 + rng.normal(scale=0.3, size=count)
        for index in range(count):
            rows.append(",".join([
                f"{matrix[index, 0]:.6f}",
                f"{matrix[index, 1]:.6f}",
                f"{matrix[index, 2]:.6f}",
                str(device_code),
                shift,
            ]))
    return header, rows


class TestAnomalyFleetShared(unittest.TestCase):
    """机群共享模式端到端（sqlite 临时库 + fake 工件/追踪服务）。"""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        engine = create_engine(f"sqlite:///{Path(self.temporary.name) / 'fleet.db'}")
        Base.metadata.create_all(engine)
        # expire_on_commit=False：commit 后对象仍可读，after_commit 里能抓到进度快照
        self.Session = sessionmaker(
            bind=engine, autocommit=False, autoflush=False,
            expire_on_commit=False, class_=_RecordingSession,
        )
        self.dataset_id = uuid.uuid4()
        self.dataset_path = Path(self.temporary.name) / "dataset.csv"
        self.progress_snapshots: list[dict] = []
        self._watched_job_id = None
        self._capture_progress_snapshots()
        header, rows = _fleet_rows([(101, "day", 500), (102, "night", 500)])
        self.dataset_path.write_text("\n".join([header, *rows]), encoding="utf-8")
        with self.Session() as db:
            user = User(username=f"fleet-{uuid.uuid4().hex}", password_hash="hash")
            db.add(user)
            db.flush()
            project = Project(name="Fleet", owner_id=user.id)
            db.add(project)
            db.flush()
            experiment = Experiment(
                project_id=project.id, created_by=user.id,
                name="Fleet", mlflow_experiment_id="fleet-experiment",
            )
            db.add(experiment)
            db.commit()
            self.user_id = user.id
            self.project_id = project.id
            self.experiment_id = experiment.id

    def tearDown(self):
        event.remove(_RecordingSession, "after_commit", self._after_commit)
        self.Session.kw["bind"].dispose()
        self.temporary.cleanup()

    def _capture_progress_snapshots(self):
        def _after_commit(session):
            if self._watched_job_id is None:
                return
            for obj in list(session.identity_map.values()):
                if isinstance(obj, TrainingJob) and obj.id == self._watched_job_id:
                    progress = (obj.metrics or {}).get("progress")
                    if isinstance(progress, dict):
                        self.progress_snapshots.append(dict(progress))
                    break

        self._after_commit = _after_commit
        event.listen(_RecordingSession, "after_commit", _after_commit)

    def write_dataset(self, device_plan, *, seed=42):
        header, rows = _fleet_rows(device_plan, seed=seed)
        self.dataset_path.write_text("\n".join([header, *rows]), encoding="utf-8")

    def create_job(self, params):
        with self.Session() as db:
            job = TrainingJob(
                project_id=self.project_id, user_id=self.user_id,
                experiment_id=self.experiment_id,
                dataset_artifact_id=self.dataset_id,
                name=f"fleet-{uuid.uuid4().hex}", operator_id="automl",
                params=params, status="pending",
            )
            db.add(job)
            db.commit()
            return job.id

    def run_job(self, job_id):
        """执行任务（方法名避开 Mimosa 对 `def execute(` 的 SQL 注入误报形态）。"""
        self.artifacts = FakeArtifactService(self.dataset_id, self.dataset_path)
        self.tracking = FakeTracking()
        self._watched_job_id = job_id
        return execute_automl_job(job_id, dependencies=AutoMLDependencies(
            session_factory=self.Session,
            artifact_service_factory=lambda _db: self.artifacts,
            tracking_factory=lambda: self.tracking,
            worker_id="worker-1", task_id="task-1",
        ))

    def job_metrics(self, job_id):
        with self.Session() as db:
            job = db.query(TrainingJob).filter(TrainingJob.id == job_id).one()
            return job.metrics, job.status, job.error_message

    def _base_params(self, **overrides):
        params = {
            "task": "anomaly_detection",
            "target_columns": [],
            "input_columns": ["s1", "s2", "s3", "device_code"],
            "contamination": 0.01,
            "search_contract": "optuna_v1",
            "algorithm_ids": ["iforest"],
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

    # -- (a) B2：联合段剔除分组身份列 -------------------------------------

    def test_shared_joint_segment_excludes_device_identity_column(self):
        """工况列选了 shift（非设备列）时，设备列不得留在联合段特征里。"""
        # 3 台设备各 600 行，每台设备跨 day/night 两个工况段 → 设备列与工况轴交叉
        self.write_dataset([
            (101, "day", 200), (101, "night", 200),
            (102, "day", 200), (102, "night", 200),
            (103, "day", 200), (103, "night", 200),
        ])
        job_id = self.create_job(self._base_params(
            condition_column="shift", fleet_mode="shared",
        ))
        result = self.run_job(job_id)
        assert result.status == "completed"
        metrics, status, error_message = self.job_metrics(job_id)
        assert status == "completed", error_message
        bundles = metrics["condition_bundles"]
        global_bundle = next(item for item in bundles if item["fleet_global"])
        segment_bundles = [item for item in bundles if not item["fleet_global"]]
        # 联合段（全局兜底）剔除设备身份列，且留痕可见
        assert "device_code" not in global_bundle["feature_columns"]
        assert global_bundle["removed_columns"]["device_code"] == "group_identity"
        assert metrics["fleet_global_note"]["removed_columns"] == {"device_code": "group_identity"}
        # 普通高方差数值特征不被误伤
        assert {"s1", "s2", "s3"}.issubset(set(global_bundle["feature_columns"]))
        # 各工况段保持原样（身份列在段内无害，§7.1 的全局顾虑只针对共享模型）
        assert len(segment_bundles) == 2
        for bundle in segment_bundles:
            assert "device_code" in bundle["feature_columns"]
            assert "group_identity" not in bundle["removed_columns"].values()

    def test_shared_joint_segment_keeps_ordinary_numeric_features(self):
        """反例检验：高方差数值特征不是身份列，联合段必须保留。"""
        frame = pd.DataFrame({
            "device_code": [101] * 400 + [102] * 400,
            "shift": ["day"] * 200 + ["night"] * 200 + ["day"] * 200 + ["night"] * 200,
            "sensor": np.random.default_rng(7).normal(size=800),
        })
        segments = [
            ("shift=day", frame.loc[frame["shift"] == "day"]),
            ("shift=night", frame.loc[frame["shift"] == "night"]),
        ]
        detected = _detect_group_identity_columns(
            segments, ["device_code", "sensor"], joint_frame=frame,
        )
        assert "sensor" not in detected
        # 段内恒定且跨段不同 → 判定为身份列（R1）
        assert "device_code" in detected

    # -- (b) B20：联合段语料含护栏丢弃的小段行 ----------------------------

    def test_shared_joint_segment_corpus_includes_below_guard_rows(self):
        """段行数护栏只管「不训练很多个独立模型」，不得把数据排除出共享模型。"""
        # weekend 段仅 50 行（<200 护栏）→ 该段被并入默认段后丢弃
        self.write_dataset([
            (101, "day", 500),
            (102, "night", 500),
            (103, "weekend", 50),
        ])
        job_id = self.create_job(self._base_params(
            condition_column="shift", fleet_mode="shared",
        ))
        result = self.run_job(job_id)
        assert result.status == "completed"
        metrics, status, error_message = self.job_metrics(job_id)
        assert status == "completed", error_message
        # 小段行确实被护栏丢弃（留痕）
        assert metrics["condition_merged_note"]["dropped"] is True
        assert metrics["condition_merged_note"]["rows"] == 50
        # 联合段语料 = 全量 1050 行（含那 50 行），而不是只含 1000 行的建模段
        global_bundle = next(
            item for item in metrics["condition_bundles"] if item["fleet_global"]
        )
        assert global_bundle["rows"] == 1050
        assert metrics["fleet_global_note"]["rows"] == 1050

    # -- (c) B18：机群共享模式缺分组列必须明确失败 ------------------------

    def test_shared_mode_without_condition_column_fails_loudly(self):
        """fleet_mode="shared" 但没有 condition_column → 明确失败，不静默降级。"""
        job_id = self.create_job(self._base_params(fleet_mode="shared"))
        result = self.run_job(job_id)
        assert result.status == "failed"
        metrics, status, error_message = self.job_metrics(job_id)
        assert status == "failed"
        assert "AUTOML_ANOMALY_FLEET_SHARED_REQUIRES_CONDITION_COLUMN" in str(error_message)
        # 失败任务不得产出「看起来成功」的机群基线
        assert "best_candidate" not in metrics
        assert "condition_bundles" not in metrics

    # -- (d) B3：进度单调 + 终态口径 == 运行期分子 ------------------------

    def test_progress_is_monotonic_and_terminal_matches_running_counter(self):
        """trial 失败时进度条不得从 100% 回退（§B3）。"""
        self.write_dataset([(101, "day", 800)])
        job_id = self.create_job(self._base_params(
            algorithm_ids=["iforest", "ocsvm"],
            input_columns=["s1", "s2", "s3"],
        ))
        real_builder = automl_execution_module._build_anomaly_estimator

        def failing_builder(family, family_params):
            if getattr(family, "id", "") == "ocsvm":
                raise RuntimeError("forced failure for progress monotonicity check")
            return real_builder(family, family_params)

        with patch.object(
            automl_execution_module, "_build_anomaly_estimator", failing_builder,
        ):
            result = self.run_job(job_id)
        assert result.status == "completed"
        metrics, status, error_message = self.job_metrics(job_id)
        assert status == "completed", error_message
        # 强制失败确实发生：attempted > completed
        trials = metrics["search"]["trials"]
        assert any(trial.get("status") == "failed" for trial in trials)
        progress = metrics["progress"]
        assert progress["attempted"] > progress["completed"]
        # 运行期分子单调不回退
        observed = [
            snapshot["completed"] for snapshot in self.progress_snapshots
            if "completed" in snapshot
        ]
        assert len(observed) >= 2, self.progress_snapshots
        assert observed == sorted(observed), observed
        # 终态 completed == 运行期分子（同一计数口径）
        assert observed[-1] == progress["completed"]
        assert progress["completed"] == metrics["search"]["completed_trials"]

    # -- (e) 普通（非共享）路径行为不变 ------------------------------------

    def test_plain_path_without_condition_column_is_unchanged(self):
        """无工况列的普通路径：单段、特征集不变、无身份列剔除。"""
        job_id = self.create_job(self._base_params())
        result = self.run_job(job_id)
        assert result.status == "completed"
        metrics, status, error_message = self.job_metrics(job_id)
        assert status == "completed", error_message
        assert metrics["condition_column"] is None
        assert metrics["input_contract"]["input_columns"] == ["s1", "s2", "s3", "device_code"]
        assert metrics["preprocessing"]["removed_columns"] == {}
        assert not metrics["condition_bundles"]
        assert "fleet_global_note" not in metrics
        assert metrics["progress"]["completed"] == metrics["search"]["completed_trials"]

    def test_plain_sharded_path_keeps_all_features_per_segment(self):
        """有工况列但非共享模式：各段特征集与改动前一致（不剔除任何列）。"""
        self.write_dataset([
            (101, "day", 600),
            (102, "night", 600),
        ])
        job_id = self.create_job(self._base_params(condition_column="shift"))
        result = self.run_job(job_id)
        assert result.status == "completed"
        metrics, status, error_message = self.job_metrics(job_id)
        assert status == "completed", error_message
        bundles = metrics["condition_bundles"]
        assert {item["condition_value"] for item in bundles} == {"day", "night"}
        for bundle in bundles:
            assert bundle["feature_columns"] == ["s1", "s2", "s3", "device_code"]
            assert bundle["removed_columns"] == {}
            assert bundle["fleet_global"] is False
        assert "fleet_global_note" not in metrics


if __name__ == "__main__":
    unittest.main()
