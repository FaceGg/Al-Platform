"""工况分片路由挂载与推理接线测试（技术方案 §6.3，二期 M7 主块二）。

合同：
- ConditionValueRouter 匹配语义：精确命中 / 通配（condition_value=None）回退 /
  weight 最高回退 + matched 标志（unknown_condition 审计依据）
- predict_condition_sharded：按记录工况分组路由各归其模、原序合并、逐记录
  condition_values 回显、unknown_condition 域事件幂等落库
- 闭环分片挂载：condition_bundles → N 版本 N targets（weight 按行数比例、
  幂等键/分片 stats 指针写入、deployment.condition_column 自动声明、重放不重复）
- retention per-shard：最差分片口径门禁
- 阈值解析：分片版本 conversion_metadata.anomaly_score_stats_artifact_id 优先
"""

import json
import os
import tempfile
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("LLM_MASTER_KEY", __import__(
    "cryptography.fernet", fromlist=["Fernet"]
).Fernet.generate_key().decode("ascii"))

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.database import Base  # noqa: E402
from app.models.artifact import Artifact  # noqa: E402
from app.models.model_registry import (  # noqa: E402
    DeploymentRevision,
    DeploymentTarget,
    InferenceDeployment,
    ModelVersion,
    RegisteredModel,
)
from app.models.notifications import NotificationOutbox as OutboxModel  # noqa: E402
from app.models.project import Project  # noqa: E402
from app.models.training import TrainingJob  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.closed_loop_actions import (  # noqa: E402
    _condition_shard_model_suffix,
    _retention_per_shard,
    complete_retrain_swap,
)
from app.services.inference_deployment import (  # noqa: E402
    InferenceDeploymentError,
    InferenceDeploymentService,
    anomaly_threshold_for_version,
)
from app.services.inference_rollout import (  # noqa: E402
    ConditionValueRouter,
    InferenceRolloutError,
)

Base.metadata.create_all(bind=create_engine("sqlite:///:memory:"))


def _target(revision_id, model_version_id, weight_bps, condition_value=None):
    return SimpleNamespace(
        revision_id=revision_id,
        model_version_id=model_version_id,
        weight_bps=weight_bps,
        condition_value=condition_value,
    )


class _ConstantModel:
    """模块级可 pickle 的最小检测器（joblib 工件用，局部类无法 pickle）。

    decision_function（正=正常）恒 -0.2 → anomaly_score 恒 +0.2（低于所有
    测试新阈值，命中 0）。"""

    def predict(self, values):
        return ["1"] * len(values)

    def decision_function(self, values):
        return [-0.2] * len(values)


class TestConditionValueRouter(unittest.TestCase):
    """Router 纯函数语义（§6.3 匹配规则 + unknown_condition matched 标志）。"""

    def setUp(self):
        self.router = ConditionValueRouter("station")
        self.targets = [
            _target("rev-1", "mv-a", 6000, "A"),
            _target("rev-1", "mv-b", 4000, "B"),
        ]

    def test_exact_match_wins(self):
        routed = self.router.select_for_record(None, {"station": "B"}, targets=self.targets)
        self.assertEqual(routed.model_version_id, "mv-b")
        self.assertTrue(routed.matched)
        self.assertEqual(routed.condition_value, "B")

    def test_unknown_value_falls_back_to_weight_highest(self):
        routed = self.router.select_for_record(None, {"station": "Z"}, targets=self.targets)
        self.assertEqual(routed.model_version_id, "mv-a")
        self.assertFalse(routed.matched)
        self.assertEqual(routed.condition_value, "A")

    def test_wildcard_target_beats_weight_fallback(self):
        targets = [
            _target("rev-1", "mv-a", 6000, "A"),
            _target("rev-1", "mv-default", 1000, None),
        ]
        routed = self.router.select_for_record(None, {"station": "Z"}, targets=targets)
        self.assertEqual(routed.model_version_id, "mv-default")
        self.assertFalse(routed.matched)
        self.assertIsNone(routed.condition_value)

    def test_empty_request_value_never_matches(self):
        routed = self.router.select_for_record(None, {"station": ""}, targets=self.targets)
        self.assertEqual(routed.model_version_id, "mv-a")
        self.assertFalse(routed.matched)

    def test_empty_targets_rejected(self):
        with self.assertRaises(InferenceRolloutError):
            self.router.select_for_record(None, {"station": "A"}, targets=[])

    def test_suffix_sanitized(self):
        self.assertEqual(_condition_shard_model_suffix("热处理/一线"), "热处理_一线")
        self.assertEqual(_condition_shard_model_suffix(None), "default")


class _ShardRuntime:
    """按 runtime_key（含分片版本 id）返回差异化解分数：A 分片
    probabilities=+0.9（正常向）、B 分片 =-0.5（异常向）——路由各归其模的
    断言锚点。key_map 由测试注入（版本 id → 概率列表）。"""

    def __init__(self, key_map=None):
        self.calls = []
        self.key_map = dict(key_map or {})

    def predict(self, runtime_key, records):
        self.calls.append((str(runtime_key), len(records)))
        probabilities = [0.9]
        for fragment, values in self.key_map.items():
            if fragment in str(runtime_key):
                probabilities = values
                break
        predictions = ["-1" if value < 0 else "1" for value in probabilities]
        return {
            "predictions": predictions * len(records),
            "probabilities": probabilities * len(records),
        }

    def load(self, deployment_id, specification):
        return {"already_loaded": False}

    def unload(self, deployment_id):
        return {"already_absent": False}

    def list(self):
        return {"items": []}


class TestConditionShardedPredict(unittest.TestCase):
    """predict_condition_sharded：分组路由各归其模 + unknown 事件 + 灰度互斥。"""

    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.db = self.Session()
        self.user = User(username="shard-owner", password_hash="hash")
        self.db.add(self.user)
        self.db.flush()
        self.project = Project(name="Shard", owner_id=self.user.id)
        self.db.add(self.project)
        self.db.flush()
        self.artifact = Artifact(
            project_id=self.project.id, name="model.onnx", type="model",
            storage_path="", storage_uri="s3://models/model.onnx",
            file_size=12, format="onnx", metadata_={"sha256": "a" * 64},
        )
        self.db.add(self.artifact)
        self.db.flush()
        self.versions = {}
        for suffix in ("a", "b"):
            model = RegisteredModel(
                project_id=self.project.id, name=f"shard-{suffix}",
                created_by_id=self.user.id,
            )
            self.db.add(model)
            self.db.flush()
            version = ModelVersion(
                registered_model_id=model.id, version_number=1,
                source_kind="onnx_artifact", source_artifact_id=self.artifact.id,
                onnx_artifact_id=self.artifact.id, framework="onnx", algorithm="",
                feature_schema=[{"name": "current", "dtype": "float64"}],
                output_schema={"task": "anomaly"},
                metrics={}, conversion_metadata={},
                approval_status="approved", created_by_id=self.user.id,
            )
            self.db.add(version)
            self.db.flush()
            self.versions[suffix] = version
        self.deployment = InferenceDeployment(
            project_id=self.project.id, name="sharded",
            model_version_id=self.versions["a"].id, condition_column="station",
            desired_state="running", observed_state="running",
            created_by_id=self.user.id,
        )
        self.db.add(self.deployment)
        self.db.flush()
        self.revision = DeploymentRevision(
            deployment_id=self.deployment.id, revision_number=1,
            strategy="immediate", status="stable", created_by_id=self.user.id,
        )
        self.db.add(self.revision)
        self.db.flush()
        self.db.add(DeploymentTarget(
            revision_id=self.revision.id, model_version_id=self.versions["a"].id,
            weight_bps=6000, role="stable", condition_value="A",
        ))
        self.db.add(DeploymentTarget(
            revision_id=self.revision.id, model_version_id=self.versions["b"].id,
            weight_bps=4000, role="stable", condition_value="B",
        ))
        self.db.commit()
        self.runtime = _ShardRuntime(key_map={
            str(self.versions["a"].id): [0.9],
            str(self.versions["b"].id): [-0.5],
        })
        self.service = InferenceDeploymentService(self.runtime, self.Session)
        self._threshold_patch = mock.patch.object(
            __import__("app.services.inference_deployment", fromlist=["anomaly_threshold_for_version"]),
            "anomaly_threshold_for_version",
            side_effect=lambda db, version: 0.2 if version.id == self.versions["a"].id else 0.3,
        )
        self._threshold_patch.start()
        self.addCleanup(self._threshold_patch.stop)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _mv_id(self, suffix):
        return str(self.versions[suffix].id)

    def test_records_route_each_to_their_own_shard(self):
        records = [
            {"station": "A", "current": 1.0},
            {"station": "B", "current": 2.0},
            {"station": "A", "current": 3.0},
        ]
        result = self.service.predict(self.db, self.deployment.id, records)
        # 分组调用：A 两条一批（mv-a）、B 一条一批（mv-b）
        keys = [key for key, _count in self.runtime.calls]
        counts = {key: count for key, count in self.runtime.calls}
        self.assertEqual(sum(count for _key, count in self.runtime.calls), 3)
        self.assertTrue(any(self._mv_id("a") in key and counts[key] == 2 for key in keys))
        self.assertTrue(any(self._mv_id("b") in key and counts[key] == 1 for key in keys))
        # 原序合并 + 各分片分数（A→-0.9，B→+0.5）
        self.assertEqual(result["condition_values"], ["A", "B", "A"])
        self.assertEqual(
            [round(value, 2) for value in result["anomaly_score"]],
            [-0.9, 0.5, -0.9],
        )
        # 各分片阈值独立判定（A 阈 0.2：-0.9 非异常；B 阈 0.3：0.5 异常）
        self.assertEqual(result["is_anomaly"], [False, True, False])

    def test_unknown_condition_falls_back_and_audits_once(self):
        records = [{"station": "Z", "current": 1.0}, {"station": "Z", "current": 2.0}]
        result = self.service.predict(self.db, self.deployment.id, records)
        # 无通配 target：回退 weight 最高（mv-a），matched=False → 审计事件
        self.assertEqual(result["condition_values"], [None, None])
        self.assertEqual(
            [round(value, 2) for value in result["anomaly_score"]],
            [-0.9, -0.9],
        )
        events = self.db.query(OutboxModel).filter(
            OutboxModel.event_type == "inference.unknown_condition",
        ).all()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].payload["unknown_values"], ["Z"])
        self.assertEqual(events[0].severity, "warning")
        # 同一 unknown 集合幂等：第二次请求不新增事件
        self.service.predict(self.db, self.deployment.id, records)
        events = self.db.query(OutboxModel).filter(
            OutboxModel.event_type == "inference.unknown_condition",
        ).all()
        self.assertEqual(len(events), 1)

    def test_routing_key_is_ignored_in_condition_mode(self):
        """工况模式与灰度互斥：routing_key 传入也走工况路由（调用仍成功）。"""
        records = [{"station": "B", "current": 1.0}]
        result = self.service.predict(
            self.db, self.deployment.id, records, routing_key="bucket-key",
        )
        self.assertEqual(result["condition_values"], ["B"])
        self.assertEqual(round(result["anomaly_score"][0], 2), 0.5)

    def test_missing_stable_revision_fails_closed(self):
        self.revision.status = "superseded"
        self.db.commit()
        with self.assertRaises(InferenceDeploymentError) as raised:
            self.service.predict(
                self.db, self.deployment.id, [{"station": "A", "current": 1.0}],
            )
        self.assertEqual(raised.exception.code, "STABLE_REVISION_NOT_FOUND")

    def test_single_row_keeps_top_contributors(self):
        self.runtime.probabilities_override = True
        with mock.patch.object(
            InferenceDeploymentService, "_anomaly_enrich",
            autospec=True,
            side_effect=lambda service_self, runtime_key, records, result, version,
                            threshold_score, enable_attribution=True: {
                "predictions": result["predictions"],
                "probabilities": result["probabilities"],
                "anomaly_score": [-float(value) for value in result["probabilities"]],
                "is_anomaly": [False],
                **({"top_contributors": [{"feature": "current", "contribution": 0.1}]}
                   if enable_attribution else {}),
            },
        ):
            result = self.service.predict(
                self.db, self.deployment.id, [{"station": "A", "current": 1.0}],
            )
        self.assertIn("top_contributors", result)


class _FakeArtifactService:
    """resolve/materialize 直指本地文件（storage_path legacy 模式同款语义）。"""

    def __init__(self, paths):
        self.paths = paths

    def resolve(self, artifact_id, project_id, expected_type=None):
        return SimpleNamespace(id=artifact_id)

    @contextmanager
    def materialize(self, artifact_id, project_id, expected_type=None):
        yield Path(self.paths[str(artifact_id)])


class TestSwapConditionShardMount(unittest.TestCase):
    """闭环分片挂载：condition_bundles → N 版本 N targets + 幂等重放。"""

    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.db = self.Session()
        self.user = User(username="swap-owner", password_hash="hash")
        self.db.add(self.user)
        self.db.flush()
        self.project = Project(name="SwapShard", owner_id=self.user.id)
        self.db.add(self.project)
        self.db.flush()

        self.stats_ids = {}
        self.stats_artifacts = {}
        for suffix in ("a", "b"):
            stats_artifact = Artifact(
                project_id=self.project.id, name=f"stats-{suffix}.json", type="report",
                storage_path="", storage_uri="",
                file_size=10, format="json", metadata_={},
            )
            self.db.add(stats_artifact)
            self.db.flush()
            self.stats_ids[suffix] = str(stats_artifact.id)
            self.stats_artifacts[suffix] = stats_artifact

        self.job = TrainingJob(
            project_id=self.project.id, user_id=self.user.id,
            name="anomaly-shard-job",
            dataset_artifact_id=None, status="completed",
            metrics={
                "task_type": "anomaly_detection",
                "best_candidate": "iforest",
                "condition_column": "station",
                "algorithm_results": [{
                    "candidate_id": "iforest", "algorithm_id": "iforest",
                    "name": "IForest", "metrics": {"synthetic_auc": 0.93},
                    "model_artifact_id": "deadbeef", "status": "completed",
                }],
                "condition_bundles": [
                    {"condition_value": "A", "model_artifact_id": str(uuid.uuid4()),
                     "stats_artifact_id": self.stats_ids["a"],
                     "synthetic_auc": 0.95, "rows": 600},
                    {"condition_value": "B", "model_artifact_id": str(uuid.uuid4()),
                     "stats_artifact_id": self.stats_ids["b"],
                     "synthetic_auc": 0.93, "rows": 400},
                ],
            },
        )
        self.db.add(self.job)
        self.db.flush()

        old_model = RegisteredModel(
            project_id=self.project.id, name="old-champion", created_by_id=self.user.id,
        )
        self.db.add(old_model)
        self.db.flush()
        self.old_version = ModelVersion(
            registered_model_id=old_model.id, version_number=1,
            source_kind="onnx_artifact",
            source_artifact_id=self.stats_artifacts["a"].id,
            onnx_artifact_id=self.stats_artifacts["a"].id,
            framework="sklearn", algorithm="iforest",
            feature_schema=[], output_schema={"task": "anomaly"},
            approval_status="approved", created_by_id=self.user.id,
        )
        self.db.add(self.old_version)
        self.db.flush()
        self.deployment = InferenceDeployment(
            project_id=self.project.id, name="sharded-swap",
            model_version_id=self.old_version.id,
            desired_state="running", observed_state="running",
            created_by_id=self.user.id,
        )
        self.db.add(self.deployment)
        self.db.flush()
        self.old_revision = DeploymentRevision(
            deployment_id=self.deployment.id, revision_number=1,
            strategy="immediate", status="stable", created_by_id=self.user.id,
        )
        self.db.add(self.old_revision)
        self.db.flush()
        self.db.add(DeploymentTarget(
            revision_id=self.old_revision.id, model_version_id=self.old_version.id,
            weight_bps=10000, role="stable",
        ))
        self.db.commit()

        def _fake_register_platform_version(self_registry, db, *, model_id,
                                            source_model_library_id=None, actor_id=None,
                                            commit=True, source_model_artifact_id=None):
            version = ModelVersion(
                registered_model_id=model_id,
                version_number=1,
                source_kind="onnx_artifact",
                source_artifact_id=self.stats_artifacts["a"].id,
                onnx_artifact_id=self.stats_artifacts["a"].id,
                framework="sklearn", algorithm="iforest",
                feature_schema=[], output_schema={"task": "anomaly"},
                metrics={}, conversion_metadata={},
                approval_status="pending", created_by_id=actor_id,
            )
            db.add(version)
            db.flush()
            return version

        self._registry_patch = mock.patch.object(
            __import__("app.services.model_registry", fromlist=["ModelRegistryService"]).ModelRegistryService,
            "register_platform_version",
            _fake_register_platform_version,
        )
        self._registry_patch.start()
        self.addCleanup(self._registry_patch.stop)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _swap(self):
        return complete_retrain_swap(
            self.db, deployment_id=self.deployment.id, job=self.job,
            actor_id=str(self.user.id), model_name="champion",
        )

    def _stable(self):
        return self.db.query(DeploymentRevision).filter(
            DeploymentRevision.deployment_id == self.deployment.id,
            DeploymentRevision.status == "stable",
        ).order_by(DeploymentRevision.revision_number.desc()).first()

    def test_mounts_n_versions_n_targets(self):
        version = self._swap()
        self.assertIsNotNone(version)
        # 命名合同：base（model_name-jobid8）+ 工况后缀；job id 八位在 base 里
        job_tag = str(self.job.id)[:8]
        models = self.db.query(RegisteredModel).filter(
            RegisteredModel.name.like(f"champion-{job_tag}-%"),
        ).all()
        self.assertEqual(len(models), 2)
        self.assertIn(f"champion-{job_tag}-A", {model.name for model in models})
        self.assertIn(f"champion-{job_tag}-B", {model.name for model in models})
        shards = self.db.query(ModelVersion).filter(
            ModelVersion.registration_task_id == self.job.id,
        ).all()
        self.assertEqual(len(shards), 2)
        by_suffix = {
            model.name.rsplit("-", 1)[1]: version
            for model, version in (
                (self.db.query(RegisteredModel).filter(
                    RegisteredModel.id == shard.registered_model_id,
                ).first(), shard) for shard in shards
            )
        }
        # 幂等键 + 分片 stats 指针写入 conversion_metadata
        for suffix, condition_value in (("A", "A"), ("B", "B")):
            shard = by_suffix[suffix]
            self.assertEqual(
                shard.registration_idempotency_key,
                f"closed-loop-{self.job.id}-cond-{suffix}",
            )
            metadata = shard.conversion_metadata or {}
            self.assertEqual(
                metadata.get("anomaly_score_stats_artifact_id"),
                self.stats_ids[suffix.lower()],
            )
            self.assertEqual(metadata.get("condition_value"), condition_value)
            self.assertEqual(shard.approval_status, "approved")
            self.assertEqual(shard.lifecycle_state, "enabled")
        # 部署主版本 = 训练量最大分片（A rows 600）+ condition_column 自动声明
        self.assertEqual(self.deployment.model_version_id, by_suffix["A"].id)
        self.assertEqual(self.deployment.condition_column, "station")
        # 新 revision：旧 superseded、2 targets 权重按行数比例
        self.assertEqual(self.old_revision.status, "superseded")
        stable = self._stable()
        self.assertIsNot(stable.id, self.old_revision.id)
        targets = sorted(stable.targets, key=lambda item: item.condition_value)
        self.assertEqual(len(targets), 2)
        self.assertEqual(
            [(item.condition_value, item.weight_bps) for item in targets],
            [("A", 6000), ("B", 4000)],
        )

    def test_replay_is_idempotent(self):
        first = self._swap()
        stable_id = self._stable().id
        version_count = self.db.query(ModelVersion).filter(
            ModelVersion.registration_task_id == self.job.id,
        ).count()
        second = self._swap()
        self.assertIsNotNone(second)
        self.assertEqual(second.id, first.id)
        self.assertEqual(self._stable().id, stable_id)
        self.assertEqual(
            self.db.query(ModelVersion).filter(
                ModelVersion.registration_task_id == self.job.id,
            ).count(),
            version_count,
        )

    def test_non_sharded_job_keeps_single_target_swap(self):
        """无 condition_bundles 的 anomaly 任务走原单版本路径（回归锁）。"""
        self.job.metrics = {
            "task_type": "anomaly_detection",
            "best_candidate": "iforest",
            "algorithm_results": [{
                "candidate_id": "iforest", "algorithm_id": "iforest",
                "name": "IForest", "metrics": {"synthetic_auc": 0.93},
                "model_artifact_id": "deadbeef", "status": "completed",
            }],
        }
        self.db.commit()
        patcher = mock.patch.object(
            __import__("app.services.model_registry", fromlist=["ModelRegistryService"]).ModelRegistryService,
            "register_automl_candidate",
            return_value=(self.old_version, False),
        )
        with patcher:
            self._swap()
        stable = self._stable()
        targets = list(stable.targets or ())
        self.assertEqual(len(targets), 1)
        self.assertIsNone(targets[0].condition_value)
        self.assertEqual(targets[0].weight_bps, 10000)


class TestRetentionPerShard(unittest.TestCase):
    """分片 retention：最差分片口径门禁。"""

    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.db = self.Session()
        self.paths = {}
        self.service = _FakeArtifactService(self.paths)
        patcher = mock.patch(
            "app.services.closed_loop_actions.build_artifact_service",
            return_value=self.service,
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _bundle_payload(self, key, threshold):
        import joblib

        path = Path(tempfile.mkdtemp(prefix="shard-retention-")) / f"{key}.joblib"
        joblib.dump(
            {"model": _ConstantModel(), "feature_schema": [{"name": "f1"}],
             "score_stats": {"threshold_score": threshold}},
            path,
        )
        artifact_id = str(uuid.uuid4())
        self.paths[artifact_id] = str(path)
        return artifact_id

    def test_worst_shard_gate(self):
        import pandas as pd

        confirmed = pd.DataFrame([
            {"station": "A", "anomaly_score": 0.9},
            {"station": "A", "anomaly_score": 0.8},
            {"station": "B", "anomaly_score": 0.9},
        ])
        job = SimpleNamespace(
            project_id=str(uuid.uuid4()),
            metrics={
                "condition_column": "station",
                "condition_bundles": [
                    {"condition_value": "A", "model_artifact_id": self._bundle_payload("a", 0.5)},
                    {"condition_value": "B", "model_artifact_id": self._bundle_payload("b", 1.5)},
                ],
            },
        )
        report = _retention_per_shard(self.db, job=job, confirmed=confirmed, old_threshold=0.3)
        # A 分片：新阈值 0.5 下命中率 0 < 旧 1.0；B 分片：新阈值 1.5 下 0 < 1.0。
        # 返回最差分片口径（此处两者同差，取排序首者）。
        self.assertIsNotNone(report)
        self.assertLess(report["new_hit_rate"], report["old_hit_rate"])
        self.assertEqual(len(report["shards"]), 2)
        self.assertIn("condition_value", report["shards"][0])

    def test_no_condition_column_falls_back(self):
        import pandas as pd

        confirmed = pd.DataFrame([{"anomaly_score": 0.9}])
        job = SimpleNamespace(metrics={
            "condition_bundles": [
                {"condition_value": "A", "model_artifact_id": str(uuid.uuid4())},
            ],
        })
        self.assertIsNone(
            _retention_per_shard(self.db, job=job, confirmed=confirmed, old_threshold=0.3),
        )


class TestThresholdShardStats(unittest.TestCase):
    """分片版本阈值解析：conversion_metadata.anomaly_score_stats_artifact_id 优先。"""

    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.db = self.Session()
        self.user = User(username="threshold-owner", password_hash="hash")
        self.db.add(self.user)
        self.db.flush()
        self.project = Project(name="Threshold", owner_id=self.user.id)
        self.db.add(self.project)
        self.db.flush()
        self.directory = tempfile.mkdtemp(prefix="shard-threshold-")
        self.stats_path = Path(self.directory) / "stats.json"
        self.stats_path.write_text(
            json.dumps({"threshold_score": 0.37}), encoding="utf-8",
        )
        self.stats_artifact = Artifact(
            project_id=self.project.id, name="stats.json", type="report",
            storage_path=str(self.stats_path), storage_uri="",
            file_size=20, format="json", metadata_={},
        )
        self.db.add(self.stats_artifact)
        self.db.flush()
        model = RegisteredModel(
            project_id=self.project.id, name="shard-model", created_by_id=self.user.id,
        )
        self.db.add(model)
        self.db.flush()
        self.version = ModelVersion(
            registered_model_id=model.id, version_number=1,
            source_kind="onnx_artifact",
            source_artifact_id=self.stats_artifact.id,
            onnx_artifact_id=self.stats_artifact.id,
            framework="sklearn", algorithm="iforest",
            feature_schema=[], output_schema={"task": "anomaly"},
            metrics={}, approval_status="approved", created_by_id=self.user.id,
            conversion_metadata={
                "anomaly_score_stats_artifact_id": str(self.stats_artifact.id),
            },
        )
        self.db.add(self.version)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_shard_stats_take_precedence(self):
        """分片指针存在时直接读它——不依赖 job 链（source_model_library_id 为空）。"""
        from app.services.inference_deployment import _ANOMALY_THRESHOLD_CACHE

        _ANOMALY_THRESHOLD_CACHE.pop(str(self.version.id), None)
        threshold = anomaly_threshold_for_version(self.db, self.version)
        self.assertEqual(threshold, 0.37)

    def test_plain_version_still_uses_job_chain(self):
        from app.services.inference_deployment import _ANOMALY_THRESHOLD_CACHE

        self.version.conversion_metadata = {}
        self.db.commit()
        _ANOMALY_THRESHOLD_CACHE.pop(str(self.version.id), None)
        # 无 library 链 → None（回退 label 端口），分片分支不误吞普通版本
        self.assertIsNone(anomaly_threshold_for_version(self.db, self.version))


class TestShardedPsiDrift(unittest.TestCase):
    """PSI per-shard（§6.3/§6.4 M7 分片化补全）：每分片各自基线+流内按工况
    分列+最差分片汇总；重拟合触发携带 condition_column。"""

    def setUp(self):
        import pandas as pd

        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.db = self.Session()
        self.user = User(username="psi-owner", password_hash="hash")
        self.db.add(self.user)
        self.db.flush()
        self.project = Project(name="PsiShard", owner_id=self.user.id)
        self.db.add(self.project)
        self.db.flush()
        self.directory = tempfile.mkdtemp(prefix="shard-psi-")
        self.artifact = Artifact(
            project_id=self.project.id, name="model.onnx", type="model",
            storage_path="", storage_uri="s3://models/model.onnx",
            file_size=12, format="onnx", metadata_={"sha256": "a" * 64},
        )
        self.db.add(self.artifact)
        self.db.flush()
        # 两个分片版本：各自 stats artifact（分位表不同）；先建版本再建部署
        # （inference_deployments.model_version_id NOT NULL）
        self.baselines = {
            "A": [round(0.001 * index, 4) for index in range(201)],
            "B": [round(1.0 + 0.001 * index, 4) for index in range(201)],
        }
        self.stats_ids = {}
        self.versions = {}
        for suffix in ("a", "b"):
            stats_path = Path(self.directory) / f"stats_{suffix}.json"
            stats_path.write_text(json.dumps({
                "calibration": {"quantile_points": self.baselines[suffix.upper()]},
                "threshold_score": 0.5,
                "contamination": 0.01,
            }), encoding="utf-8")
            stats_artifact = Artifact(
                project_id=self.project.id, name=f"stats-{suffix}.json", type="report",
                storage_path=str(stats_path), storage_uri="",
                file_size=stats_path.stat().st_size, format="json", metadata_={},
            )
            self.db.add(stats_artifact)
            self.db.flush()
            self.stats_ids[suffix] = str(stats_artifact.id)
            model = RegisteredModel(
                project_id=self.project.id, name=f"psi-shard-{suffix}",
                created_by_id=self.user.id,
            )
            self.db.add(model)
            self.db.flush()
            version = ModelVersion(
                registered_model_id=model.id, version_number=1,
                source_kind="onnx_artifact",
                source_artifact_id=self.artifact.id,
                onnx_artifact_id=self.artifact.id,
                framework="onnx", algorithm="iforest",
                feature_schema=[], output_schema={"task": "anomaly"},
                metrics={}, approval_status="approved",
                created_by_id=self.user.id,
                conversion_metadata={
                    "anomaly_score_stats_artifact_id": str(stats_artifact.id),
                },
            )
            self.db.add(version)
            self.db.flush()
            self.versions[suffix] = version
        self.deployment = InferenceDeployment(
            project_id=self.project.id, name="psi-sharded",
            model_version_id=self.versions["a"].id, condition_column="station",
            desired_state="running", observed_state="running",
            created_by_id=self.user.id,
        )
        self.db.add(self.deployment)
        self.db.flush()
        self.revision = DeploymentRevision(
            deployment_id=self.deployment.id, revision_number=1,
            strategy="immediate", status="stable", created_by_id=self.user.id,
        )
        self.db.add(self.revision)
        self.db.flush()
        self.db.add(DeploymentTarget(
            revision_id=self.revision.id, model_version_id=self.versions["a"].id,
            weight_bps=6000, role="stable", condition_value="A",
        ))
        self.db.add(DeploymentTarget(
            revision_id=self.revision.id, model_version_id=self.versions["b"].id,
            weight_bps=4000, role="stable", condition_value="B",
        ))
        # 回流帧：A 分片贴基线（稳定），B 分片漂移到远离 B 基线的分布。
        # prediction 列是回流写入侧真实列名（§3.3 第三层「阈值法报警数」口径
        # 读取该列）——早期实现读 "predicted" 致计数恒 0，此处按真实 schema 造数。
        reflow_rows = (
            [{"station": "A", "anomaly_score": 0.0005 * index,
              "prediction": "-1" if index < 50 else "0"} for index in range(100)]
            + [{"station": "B", "anomaly_score": 50.0 + index,
                "prediction": "0"} for index in range(100)]
        )
        reflow_path = Path(self.directory) / "reflow.csv"
        pd.DataFrame(reflow_rows).to_csv(reflow_path, index=False)
        self.reflow_artifact = Artifact(
            project_id=self.project.id, name="reflow.csv", type="dataset",
            storage_path=str(reflow_path), storage_uri="",
            file_size=reflow_path.stat().st_size, format="csv", metadata_={},
        )
        self.db.add(self.reflow_artifact)
        self.db.flush()
        from app.models.demo_loop import DemoLoopConfig

        self.config = DemoLoopConfig(
            project_id=self.project.id, name="psi-loop",
            deployment_id=self.deployment.id,
            error_artifact_id=self.reflow_artifact.id,
            psi_enabled=True, psi_threshold=0.25,
            total_count=200,
        )
        self.db.add(self.config)
        self.db.commit()
        from app.services.demo_loop import DemoLoopService

        self.service = DemoLoopService(self.db)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_baseline_points_are_per_shard(self):
        points = self.service._psi_baseline_points(self.config)
        self.assertIsInstance(points, dict)
        self.assertEqual(sorted(points.keys()), ["A", "B"])
        self.assertEqual(points["A"], self.baselines["A"])
        self.assertEqual(points["B"], self.baselines["B"])

    def test_evaluate_psi_reports_worst_shard(self):
        drift = self.service._evaluate_psi_drift(self.config)
        self.assertIsNotNone(drift)
        self.assertEqual(drift["level"], "alert")
        # 最差分片 = B（流内分数 50+ 对 B 基线 1.0-1.2 完全漂移）
        self.assertGreater(float(drift["psi"]), 0.25)
        per_shard = drift.get("per_shard") or []
        self.assertEqual(len(per_shard), 2)
        by_value = {item["condition_value"]: item for item in per_shard}
        self.assertGreater(float(by_value["B"]["psi"]), float(by_value["A"]["psi"]))
        # per_shard 明细进 psi_state
        self.assertIn("per_shard", self.config.psi_state or {})

    def test_retrain_trigger_carries_condition_column(self):
        """分片部署重拟合触发必须携带工况列（否则引擎退化单段训练）。"""
        from app.services import demo_loop as demo_loop_module

        self.config.retrain_enabled = True
        self.config.retrain_threshold_rows = 1
        self.config.error_count = 5
        self.db.commit()
        captured = {}

        def _fake_trigger(db, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(id=uuid.uuid4(), params={"max_trials": 3})

        with mock.patch(
            "app.services.closed_loop_actions.resolve_retrain_dataset_ids",
            return_value=[str(uuid.uuid4())],
        ), mock.patch.object(
            demo_loop_module, "trigger_retrain_job", side_effect=_fake_trigger,
        ):
            self.service._trigger_retrain(self.config, str(self.user.id))
        self.assertEqual(captured.get("condition_column"), "station")
        self.assertEqual(captured.get("task_type"), "anomaly_detection")

    def test_alert_comparison_counts_model_alerts(self):
        """运行期报警对比（§3.3 第三层）：同一批回流行上阈值法 vs 模型口径。

        回归锁：阈值法口径读回流真实列名 ``prediction``（写入侧 schema）。
        历史实现读 ``predicted`` → 列不存在 → threshold_alerts 恒 0，
        对比曲线失真且无任何报错（2026-11-13 审计 P0-1）。
        """
        comparison = self.service._alert_comparison(self.config)
        self.assertIsNotNone(comparison)
        self.assertEqual(comparison["rows"], 200)
        # 阈值法口径：prediction 列命中 ==-1 的行（A 分片前 50 行）
        self.assertEqual(comparison["threshold_alerts"], 50)
        self.assertEqual(comparison["threshold_alert_rate"], 0.25)
        # 模型口径：A 分片分数 0~0.05（<0.5 阈值不报警）、B 分片 50+（全报警）
        self.assertEqual(comparison["model_alerts"], 100)
        self.assertEqual(comparison["model_alert_rate"], 0.5)


class TestCrossConditionInjection(unittest.TestCase):
    """验收③语义级交叉注入（技术方案 §6.4）：两工况正常包络本质不同时，
    同一样本在错误分片模型下分数显著不同——错用工况模型会把邻工况正常
    误报、把靠近其包络的异常漏检。路由各归其模是检出质量的前提。

    M7 前置批次的 stub 级测试只验证「路由把请求送到正确分片」；本类用
    真实训练的两个 AE 分片模型验证「分片模型的包络确实各不相同」。
    """

    def test_cross_condition_scores_diverge(self):
        try:
            import torch  # noqa: F401
        except ImportError:
            self.skipTest("torch not installed (AE 采纳后接线待用户决策)")
        import numpy as np

        from app.services.automl_anomaly_ae import TorchAutoencoder

        rng = np.random.RandomState(11)
        # 工况 A 正常包络 N(0,1)；工况 B 正常包络 N(10,1)——分布中心差 10σ
        normal_a = rng.randn(1500, 4).astype(np.float32)
        normal_b = (10.0 + rng.randn(1500, 4)).astype(np.float32)
        ae_a = TorchAutoencoder(hidden_units=32, hidden_layers=2, epochs=40)
        ae_b = TorchAutoencoder(hidden_units=32, hidden_layers=2, epochs=40)
        ae_a.fit(normal_a)
        ae_b.fit(normal_b)

        def anomaly_score(model, matrix):
            return -np.asarray(model.decision_function(matrix))

        # ① A 正常样本：在 A 模型下低分（正常）；在 B 模型下显著高分（误报）
        probe_a = normal_a[:200]
        score_on_a = anomaly_score(ae_a, probe_a)
        score_on_b = anomaly_score(ae_b, probe_a)
        self.assertLess(float(score_on_a.mean()), float(score_on_b.mean()))
        self.assertGreater(float(score_on_b.mean()), 2.0 * max(float(score_on_a.mean()), 1e-6))
        # ② A 异常（向 +8 偏移，靠近 B 包络）：A 模型检出；B 模型漏检
        anomaly_a = (normal_a[:200] + 8.0).astype(np.float32)
        self.assertGreater(
            float(anomaly_score(ae_a, anomaly_a).mean()),
            float(anomaly_score(ae_b, anomaly_a).mean()),
        )
        # ③ B 正常样本在 A 模型下同理误报（对称性）
        probe_b = normal_b[:200]
        self.assertLess(
            float(anomaly_score(ae_b, probe_b).mean()),
            float(anomaly_score(ae_a, probe_b).mean()),
        )


class TestAutoencoderAttribution(unittest.TestCase):
    """AE 专属归因（技术方案 §3.5，三期补全）：逐特征重构误差分解——
    ONNX 第三端口 per_feature_error 直接给贡献度，零额外推理；IF/OC-SVM
    仍走中心差分。"""

    def test_ae_decomposition_attribution(self):
        from app.services.inference_deployment import anomaly_predict_enrichment

        class _Runtime:
            def predict(self, key, records):
                return {"predictions": ["1"], "probabilities": [-0.5]}

        # AE 版本（conversion_metadata.converter=="torch"）：result 带
        # per_feature_error（runtime 单行透传第三端口）→ 分解归因
        feature_schema = [{"name": f"f{i}", "dtype": "float64"} for i in range(4)]
        result = {
            "predictions": ["1"],
            "probabilities": [-0.5],
            "per_feature_error": [[0.9, 0.02, 0.5, 0.03]],
        }
        enriched = anomaly_predict_enrichment(
            _Runtime(), "key", [{"f0": 1.0}], result,
            feature_schema=feature_schema,
            output_schema={"task": "anomaly"},
            threshold_score=0.2,
            conversion_metadata={"converter": "torch"},
        )
        contributors = enriched.get("top_contributors") or []
        self.assertEqual(
            [item["feature"] for item in contributors], ["f0", "f2", "f3"],
        )
        self.assertEqual(enriched.get("attribution"), "ae_reconstruction_decomposition")

    def test_non_ae_keeps_central_difference(self):
        from app.services.inference_deployment import anomaly_predict_enrichment

        class _Runtime:
            def __init__(self):
                self.predict_calls = 0

            def predict(self, key, records):
                self.predict_calls += 1
                return {"predictions": ["1"], "probabilities": [-0.5]}

        feature_schema = [{"name": "f0", "dtype": "float64"}, {"name": "f1", "dtype": "float64"}]
        runtime = _Runtime()
        result = {"predictions": ["1"], "probabilities": [-0.5]}
        enriched = anomaly_predict_enrichment(
            runtime, "key", [{"f0": 1.0, "f1": 2.0}], result,
            feature_schema=feature_schema,
            output_schema={"task": "anomaly"},
            threshold_score=0.2,
            conversion_metadata={"converter": "skl2onnx"},
        )
        # 非 AE：仍走中心差分（runtime 被多次调用，每特征 ±1% 两次）
        self.assertNotEqual(enriched.get("attribution"), "ae_reconstruction_decomposition")
        self.assertGreater(runtime.predict_calls, 1)


if __name__ == "__main__":
    unittest.main()
