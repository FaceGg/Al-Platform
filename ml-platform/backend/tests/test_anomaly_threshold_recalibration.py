"""M6 半监督档 1 机制测试（技术方案 §6.2）：标签阈值重标定 + 门槛 + 形态报表
+ 派生导出（§2.3.3）。机制先行模式——confirmed≥50 标签到位即可用，门槛
fail-closed 保证未解锁时不可误触发。"""

import os
import tempfile
import unittest
import uuid
from pathlib import Path

os.environ.setdefault("LLM_MASTER_KEY", __import__(
    "cryptography.fernet", fromlist=["Fernet"]
).Fernet.generate_key().decode("ascii"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.database import Base  # noqa: E402
from app.models.artifact import Artifact  # noqa: E402
from app.models.model_registry import ModelVersion, RegisteredModel  # noqa: E402
from app.models.project import Project  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.anomaly_threshold_recalibration import (  # noqa: E402
    ThresholdRecalibrationError,
    confirmed_morphology_clusters,
    export_labeled_reflow_dataset,
    false_alarm_morphology_report,
    label_recalibrate_version,
    meets_m6_gate,
    optimal_threshold_from_labels,
)

Base.metadata.create_all(bind=create_engine("sqlite:///:memory:"))


class TestOptimalThreshold(unittest.TestCase):
    """加权损失核心（漏报罚 2×误报）。"""

    def test_separable_distributions_threshold_between(self):
        confirmed = np.array([5.0, 6.0, 7.0, 8.0, 9.0])  # 真故障：高分
        false_alarm = np.array([0.0, 0.5, 1.0, 1.5, 2.0])  # 误报：低分
        result = optimal_threshold_from_labels(confirmed, false_alarm)
        # 两组完全分离：最优阈值在 2.0~5.0 之间（loss=0）
        self.assertGreaterEqual(result["threshold"], 2.0)
        self.assertLessEqual(result["threshold"], 5.0)
        self.assertEqual(result["loss"], 0.0)
        self.assertEqual(result["fnr"], 0.0)
        self.assertEqual(result["fpr"], 0.0)

    def test_overlapping_distributions_balances_weights(self):
        # 重叠分布：漏报罚 2 倍 → 阈值应压低（多报警少漏报）
        confirmed = np.array([2.0, 2.5, 3.0, 3.5, 4.0])
        false_alarm = np.array([2.4, 2.8, 3.2, 3.6, 4.0])
        result = optimal_threshold_from_labels(confirmed, false_alarm)
        self.assertIsNotNone(result["threshold"])
        # 任意档位下 loss 有限且非负
        self.assertGreaterEqual(result["loss"], 0.0)

    def test_empty_inputs_report_counts(self):
        result = optimal_threshold_from_labels(np.array([]), np.array([1.0]))
        self.assertIsNone(result["threshold"])
        self.assertEqual(result["confirmed_count"], 0)
        self.assertEqual(result["false_alarm_count"], 1)

    def test_gate_requires_fifty_confirmed_and_two_morphologies(self):
        self.assertFalse(meets_m6_gate(49, 2)["unlocked"])
        self.assertFalse(meets_m6_gate(50, 1)["unlocked"])
        self.assertTrue(meets_m6_gate(50, 2)["unlocked"])


class TestMorphology(unittest.TestCase):
    def test_morphology_clusters_two_groups(self):
        rng = np.random.RandomState(3)
        group_a = rng.randn(30, 5)
        group_b = 10.0 + rng.randn(30, 5)
        report = confirmed_morphology_clusters(np.vstack([group_a, group_b]))
        self.assertGreaterEqual(report["cluster_count"], 2)

    def test_false_alarm_report_lists_dense_features(self):
        rng = np.random.RandomState(4)
        matrix = rng.randn(40, 3)
        matrix[:, 1] += 20.0  # f1 为误报密集特征
        report = false_alarm_morphology_report(matrix, ["f0", "f1", "f2"])
        self.assertTrue(report["clusters"])
        dense = {item["feature"] for cluster in report["clusters"] for item in cluster["dense_features"]}
        self.assertIn("f1", dense)


class TestLabelRecalibrateVersion(unittest.TestCase):
    """端到端：门槛 fail-closed + 达标时注册重标定版本。"""

    def setUp(self):
        import joblib
        from sklearn.ensemble import IsolationForest
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import StandardScaler

        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.db = self.Session()
        self.user = User(username="m6-owner", password_hash="hash")
        self.db.add(self.user)
        self.db.flush()
        self.project = Project(name="M6", owner_id=self.user.id)
        self.db.add(self.project)
        self.db.flush()
        self.directory = tempfile.mkdtemp(prefix="m6-recal-")
        self.n_features = 4
        rng = np.random.RandomState(42)
        fleet = rng.randn(800, self.n_features).astype(np.float32)
        pipeline = Pipeline([
            ("imputer", StandardScaler()),
            ("detector", __import__("sklearn.ensemble", fromlist=["IsolationForest"]).IsolationForest(
                n_estimators=30, random_state=0)),
        ]).fit(fleet)
        bundle_path = Path(self.directory) / "bundle.joblib"
        joblib.dump({
            "model": pipeline,
            "feature_schema": [{"name": f"f{i}", "dtype": "float64"} for i in range(self.n_features)],
            "target_schema": [],
            "score_stats": {"threshold_score": 0.1, "contamination": 0.01},
        }, bundle_path)
        self.bundle_artifact = Artifact(
            project_id=self.project.id, name="bundle.joblib", type="model",
            storage_path=str(bundle_path), storage_uri="",
            file_size=bundle_path.stat().st_size, format="joblib",
            metadata_={"source": "automl", "sha256": "a" * 64},
        )
        self.db.add(self.bundle_artifact)
        self.db.flush()
        model = RegisteredModel(
            project_id=self.project.id, name="m6-baseline",
            created_by_id=self.user.id,
        )
        self.db.add(model)
        self.db.flush()
        self.source_version = ModelVersion(
            registered_model_id=model.id, version_number=1,
            source_kind="onnx_artifact", source_model_library_id=None,
            source_artifact_id=self.bundle_artifact.id,
            onnx_artifact_id=self.bundle_artifact.id,
            framework="sklearn", algorithm="iforest",
            feature_schema=[{"name": f"f{i}", "dtype": "float64"} for i in range(self.n_features)],
            output_schema={"task": "anomaly"},
            metrics={}, approval_status="approved", conversion_metadata={},
            created_by_id=self.user.id,
        )
        self.db.add(self.source_version)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _labeled_artifact(self, confirmed: int, false_alarm: int, seed: int = 1):
        rng = np.random.RandomState(seed)
        rows = []
        for i in range(confirmed):
            rows.append({f"f{j}": 8.0 + rng.randn() for j in range(self.n_features)} | {"feedback": "confirmed_fault", "anomaly_score": 5.0})
        for i in range(false_alarm):
            rows.append({f"f{j}": rng.randn() for j in range(self.n_features)} | {"feedback": "false_alarm", "anomaly_score": -1.0})
        path = Path(self.directory) / f"labeled-{uuid.uuid4().hex[:8]}.csv"
        pd.DataFrame(rows).to_csv(path, index=False)
        artifact = Artifact(
            project_id=self.project.id, name=path.name, type="dataset",
            storage_path=str(path), storage_uri="",
            file_size=path.stat().st_size, format="csv", metadata_={},
        )
        self.db.add(artifact)
        self.db.commit()
        return artifact

    def test_gate_below_fifty_confirmed_fails_closed(self):
        artifact = self._labeled_artifact(confirmed=30, false_alarm=20)
        with self.assertRaises(ThresholdRecalibrationError) as raised:
            label_recalibrate_version(
                self.db,
                source_version_id=self.source_version.id,
                labeled_artifact_id=artifact.id,
                actor_id=str(self.user.id),
            )
        self.assertEqual(raised.exception.code, "M6_GATE_NOT_UNLOCKED")

    def test_unlocked_recalibration_registers_version(self):
        artifact = self._labeled_artifact(confirmed=60, false_alarm=30, seed=5)
        result = label_recalibrate_version(
            self.db,
            source_version_id=self.source_version.id,
            labeled_artifact_id=artifact.id,
            actor_id=str(self.user.id),
        )
        self.assertTrue(result["gate"]["unlocked"])
        self.assertEqual(result["confirmed_count"], 60)
        self.assertIsNotNone(result["new_threshold"])
        version = self.db.query(ModelVersion).filter(
            ModelVersion.id == uuid.UUID(result["version_id"]),
        ).first()
        self.assertIsNotNone(version)
        metadata = version.conversion_metadata or {}
        self.assertTrue(metadata.get("m6_recalibration"))
        self.assertEqual(
            metadata.get("anomaly_score_stats_artifact_id"),
            result["stats_artifact_id"],
        )
        self.assertIn("false_alarm_report", version.metrics.get("label_recalibration", {}))

    def test_derived_supervised_dataset_export(self):
        artifact = self._labeled_artifact(confirmed=55, false_alarm=25, seed=9)
        result = export_labeled_reflow_dataset(
            self.db,
            source_version_id=self.source_version.id,
            labeled_artifact_id=artifact.id,
            actor_id=str(self.user.id),
            dataset_name="derived-supervised",
        )
        self.assertEqual(result["positives"], 55)
        self.assertEqual(result["negatives"], 25)
        # 数据集 artifact 已建（metadata 带正负样本计数）
        from app.models.artifact import Artifact as _A

        dataset = self.db.query(_A).filter(
            _A.id == uuid.UUID(result["dataset_artifact_id"]),
        ).first()
        self.assertIsNotNone(dataset)
        self.assertEqual((dataset.metadata_ or {}).get("positives"), 55)

    def test_export_without_labeled_rows_fails(self):
        rows = [{f"f{j}": 1.0 for j in range(4)} | {"feedback": ""} for _ in range(10)]
        path = Path(self.directory) / "unlabeled.csv"
        pd.DataFrame(rows).to_csv(path, index=False)
        artifact = Artifact(
            project_id=self.project.id, name="unlabeled.csv", type="dataset",
            storage_path=str(path), storage_uri="",
            file_size=path.stat().st_size, format="csv", metadata_={},
        )
        self.db.add(artifact)
        self.db.commit()
        with self.assertRaises(ThresholdRecalibrationError) as raised:
            export_labeled_reflow_dataset(
                self.db,
                source_version_id=self.source_version.id,
                labeled_artifact_id=artifact.id,
                actor_id=str(self.user.id),
            )
        self.assertEqual(raised.exception.code, "NO_LABELED_ROWS")


if __name__ == "__main__":
    unittest.main()
