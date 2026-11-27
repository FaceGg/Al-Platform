"""盲测终验与不回退的打分基座测试（三批复审重构，2026-11-27）。

原实现：终验取 version.metrics（与浅验证集同源=没有盲测终验）、不回退比较
各版本自己的指标（非同批配对）——两条都是 S2b 对标竞品的核心卖点，复审判
failed。重构后对锁定盲测段用两版本分别真实打分（score_blind_split），同批
由「同一 frame」构造性保证。

本文件用真实工件（密封 joblib 模型包 + CSV 数据集工件）走完整打分链路。
"""
import hashlib
import io
import unittest
import uuid
from datetime import datetime

import joblib
import numpy as np
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.dataset_splitting import (
    DatasetSplit,
    DatasetSplitMember,
    ModelingRound,
)
from app.models.model_library import ModelLibrary
from app.models.model_registry import (
    DeploymentRevision,
    InferenceDeployment,
    ModelVersion,
    RegisteredModel,
)
from app.models.project import Project
from app.models.user import User
from app.services.model_artifact_sealing import model_seal_metadata
from app.services.release_governance import (
    GovernanceError,
    _blind_final_metrics,
    evaluate_no_regression,
    score_blind_split,
)


class _FixedPredictor:
    """恒定序列预测器：predict 返回预设标签序列（便于构造已知 F1）。"""

    def __init__(self, labels):
        self._labels = list(labels)

    def predict(self, matrix):
        return np.array(self._labels[: len(matrix)])


class BlindScoringCase(unittest.TestCase):
    def setUp(self):
        import tempfile

        from app.models.access import ProjectMember
        from app.models.data_version import DatasetVersion
        from app.models.model_registry import DeploymentTarget
        from app.services.artifact_service import build_artifact_service

        self.engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine, expire_on_commit=False)()
        tag = uuid.uuid4().hex[:6]
        self.owner = User(username=f"bs-{tag}", password_hash="hash")
        self.db.add(self.owner)
        self.db.flush()
        self.project = Project(name=f"blind-{tag}", owner_id=self.owner.id)
        self.db.add(self.project)
        self.db.flush()
        self.artifacts = build_artifact_service(self.db)
        self._workdir = tempfile.TemporaryDirectory()

        # --- 数据集工件：4 行，target 列 [a, a, b, b]，特征列 feature_a ---
        import pandas as pd

        frame = pd.DataFrame({
            "feature_a": [1.0, 2.0, 3.0, 4.0],
            "target": ["a", "a", "b", "b"],
            "sample_key": [f"sk-{i}" for i in range(4)],
        })
        csv_path = self._workdir.name + "/blind.csv"
        frame.to_csv(csv_path, index=False)
        dataset_artifact = self.artifacts.create_from_file(
            self.project.id, csv_path, f"blind-{tag}.csv", "dataset",
        )
        latest = None
        self.dataset_version = DatasetVersion(
            project_id=self.project.id, operator_id=self.owner.id, version=1,
            status="ready", row_count=4, column_count=3,
            content_hash=uuid.uuid4().hex, schema_hash=uuid.uuid4().hex,
            normalized_artifact_id=dataset_artifact.id,
        )
        self.db.add(self.dataset_version)
        self.db.flush()

        # --- 划分（target_column 进 params）+ 全量 blind 成员 ---
        self.split = DatasetSplit(
            project_id=self.project.id, dataset_version_id=self.dataset_version.id,
            name="盲测", strategy="random_stratified",
            params={"target_column": "target", "test_size": 0.5, "seed": 42},
            split_fingerprint=uuid.uuid4().hex, created_by_id=self.owner.id,
        )
        self.db.add(self.split)
        self.db.flush()
        for index in range(4):
            self.db.add(DatasetSplitMember(
                split_id=self.split.id, row_index=index,
                sample_key=f"sk-{index}", role="blind",
            ))
        self.round_row = ModelingRound(
            project_id=self.project.id, dataset_version_id=self.dataset_version.id,
            split_id=self.split.id, status="locked", blind_eval_count=0,
            blind_eval_cap=6, blind_fingerprint=uuid.uuid4().hex,
            created_by_id=self.owner.id,
        )
        self.db.add(self.round_row)

        # --- 注册模型 / 库 / 两版本（打分链路读真实工件）---
        registered = RegisteredModel(project_id=self.project.id,
                                     name=f"blind-model-{tag}",
                                     created_by_id=self.owner.id)
        self.db.add(registered)
        self.db.flush()

        def _sealed_library(name, labels):
            bundle = _FixedPredictor(labels)
            path = self._workdir.name + f"/{name}.joblib"
            joblib.dump(bundle, path)
            payload = open(path, "rb").read()
            digest = hashlib.sha256(payload).hexdigest()
            artifact = self.artifacts.create_from_file(
                self.project.id, path, f"{name}.joblib", "model",
                metadata={**model_seal_metadata(digest), "served_sha256": digest},
            )
            library = ModelLibrary(name=name, owner_id=self.owner.id,
                                   status="completed",
                                   model_artifact_id=artifact.id)
            self.db.add(library)
            self.db.flush()
            return library

        champion_lib = _sealed_library(f"champ-{tag}", ["a", "a", "a", "b"])
        candidate_lib = _sealed_library(f"cand-{tag}", ["a", "a", "a", "b"])
        self.champion_version = ModelVersion(
            registered_model_id=registered.id, version_number=1,
            source_kind="platform_joblib", source_artifact_id=uuid.uuid4(),
            onnx_artifact_id=uuid.uuid4(),
            source_model_library_id=champion_lib.id,
            approval_status="approved", metrics={"f1": 0.9},
            feature_schema=["feature_a"],
        )
        self.candidate_version = ModelVersion(
            registered_model_id=registered.id, version_number=2,
            source_kind="platform_joblib", source_artifact_id=uuid.uuid4(),
            onnx_artifact_id=uuid.uuid4(),
            source_model_library_id=candidate_lib.id,
            approval_status="approved", metrics={"f1": 0.93},
            feature_schema=["feature_a"],
        )
        self.db.add_all([self.champion_version, self.candidate_version])
        self.db.flush()
        self.deployment = InferenceDeployment(
            project_id=self.project.id, name="盲测部署",
            model_version_id=self.champion_version.id,
            created_by_id=self.owner.id,
        )
        self.db.add(self.deployment)
        self.db.flush()
        revision = DeploymentRevision(
            deployment_id=self.deployment.id, revision_number=1,
            strategy="immediate", status="stable",
            created_by_id=self.owner.id,
        )
        self.db.add(revision)
        self.db.flush()
        from app.models.model_registry import DeploymentTarget

        self.db.add(DeploymentTarget(
            revision_id=revision.id, model_version_id=self.champion_version.id,
            weight_bps=10000, role="stable",
        ))
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        self._workdir.cleanup()

    # --- 终验：真实盲测打分 ---

    def test_blind_final_metrics_scored_from_real_blind_split(self):
        metrics = _blind_final_metrics(self.db, self.deployment,
                                       self.candidate_version, {})
        if metrics is None:
            from app.models.access import AuditEvent
            failed = self.db.query(AuditEvent).filter(
                AuditEvent.action == "blind_final_validation.failed").first()
            self.fail("blind scoring failed with: "
                      + (str(failed.changes) if failed else "no audit row"))
        self.assertIsNotNone(metrics)
        self.assertEqual(metrics["scored_from"], "blind_split")
        # candidate 预测 [a,a,a,b] vs 真值 [a,a,b,b]：
        # a 类 p=2/3, r=1 → f1=0.8；b 类 p=1, r=0.5 → f1=2/3 → macro=0.7333
        self.assertAlmostEqual(metrics["f1"], 0.7333, places=3)
        self.assertEqual(metrics["sample_count"], 4)
        self.assertTrue(metrics["samples_fingerprint"])

    def test_blind_final_metrics_without_target_column_fails_honestly(self):
        # split.params 缺 target_column → 诚实失败（None → 门禁 failed），不再拿浅验证集指标充数
        from app.models.dataset_splitting import DatasetSplit

        self.split.params = {}
        self.db.commit()
        metrics = _blind_final_metrics(self.db, self.deployment,
                                       self.candidate_version, {})
        self.assertIsNone(metrics)

    # --- 不回退：同批配对 ---

    def test_no_regression_paired_on_same_blind_samples(self):
        # champion/candidate 同预测 [a,a,a,b] → 同 macro F1 0.7333 → 平（容差 0 → passed）
        result = evaluate_no_regression(db=self.db, deployment=self.deployment,
                                        version=self.candidate_version)
        self.assertTrue(result["same_blind_samples"])
        self.assertEqual(result["sample_count"], 4)
        self.assertTrue(result["samples_fingerprint"])
        self.assertTrue(result["passed"])
        self.assertAlmostEqual(result["candidate"]["f1"], 0.7333, places=3)
        self.assertAlmostEqual(result["champion"]["f1"], 0.7333, places=3)

    def test_no_regression_flags_worse_candidate(self):
        # 换一个更差的候选（恒预测 b：macro F1 = 0.333 < champion 0.7333）→ failed。
        # 浅验证集口径会说候选更好（metrics f1 0.99 > 0.9）——盲测配对揭穿它
        import joblib

        from app.models.model_library import ModelLibrary
        from app.models.model_registry import ModelVersion

        tag = uuid.uuid4().hex[:6]
        worse_lib = ModelLibrary(name=f"worse-{tag}", owner_id=self.owner.id,
                                 status="completed")
        self.db.add(worse_lib)
        self.db.flush()
        bundle = _FixedPredictor(["b", "b", "b", "b"])
        path = self._workdir.name + f"/worse-{tag}.joblib"
        joblib.dump(bundle, path)
        payload = open(path, "rb").read()
        digest = hashlib.sha256(payload).hexdigest()
        artifact = self.artifacts.create_from_file(
            self.project.id, path, f"worse-{tag}.joblib", "model",
            metadata={**model_seal_metadata(digest), "served_sha256": digest},
        )
        worse_lib.model_artifact_id = artifact.id
        worse_version = ModelVersion(
            registered_model_id=self.champion_version.registered_model_id,
            version_number=3, source_kind="platform_joblib",
            source_artifact_id=uuid.uuid4(),
            onnx_artifact_id=uuid.uuid4(),
            source_model_library_id=worse_lib.id,
            approval_status="approved", metrics={"f1": 0.99},
            feature_schema=["feature_a"],
        )
        self.db.add(worse_version)
        self.db.commit()
        result = evaluate_no_regression(db=self.db, deployment=self.deployment,
                                        version=worse_version)
        self.assertFalse(result["passed"], result)
        # 浅验证集口径会说候选更好（0.99 > 0.9）——盲测配对揭穿它
        self.assertLess(result["candidate"]["f1"], result["champion"]["f1"])


if __name__ == "__main__":
    unittest.main()
