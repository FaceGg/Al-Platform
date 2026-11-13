"""机群设备级标定与迁移测试（技术方案 §7，三期 M8/M9/M10）。

合同：
- recalibrate_device_version：只重标定不动检测器主体；机群形态判定
  （源阈值下新设备 fpr 超 1.5×contamination → unfit 不硬迁）；合成基准
  回测；迁移版本注册（同源 artifact + 分片阈值指针指向新 stats）
- add_fleet_shard_to_deployment：挂载为新 stable revision（现有分片全量
  复制+新分片）；重复挂载拒绝；部署 condition_column 缺省 device_id
- fleet_overview：部署面 per-device 概览（阈值/兼容性/回测）+ PSI 分片明细
"""

import json
import os
import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("LLM_MASTER_KEY", __import__(
    "cryptography.fernet", fromlist=["Fernet"]
).Fernet.generate_key().decode("ascii"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.database import Base  # noqa: E402
from app.models.artifact import Artifact  # noqa: E402
from app.models.demo_loop import DemoLoopConfig  # noqa: E402
from app.models.model_registry import (  # noqa: E402
    DeploymentRevision,
    DeploymentTarget,
    InferenceDeployment,
    ModelVersion,
    RegisteredModel,
)
from app.models.project import Project  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.anomaly_device_calibration import (  # noqa: E402
    DeviceCalibrationError,
    add_fleet_shard_to_deployment,
    fleet_overview,
    recalibrate_device_version,
)

Base.metadata.create_all(bind=create_engine("sqlite:///:memory:"))


def _normal_matrix(rows, n_features=4, seed=42):
    rng = np.random.RandomState(seed)
    return rng.randn(rows, n_features).astype(np.float32)


class TestRecalibrateDeviceVersion(unittest.TestCase):
    """M9 迁移流：重标定 + 机群形态判定 + 回测 + 版本注册。"""

    def setUp(self):
        import joblib
        from sklearn.ensemble import IsolationForest
        from sklearn.impute import SimpleImputer
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import StandardScaler

        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.db = self.Session()
        self.user = User(username="fleet-owner", password_hash="hash")
        self.db.add(self.user)
        self.db.flush()
        self.project = Project(name="Fleet", owner_id=self.user.id)
        self.db.add(self.project)
        self.db.flush()
        self.directory = tempfile.mkdtemp(prefix="fleet-calib-")
        self.n_features = 4

        # 机群基线模型：IF pipeline 在 N(0,1) 上训练（bundle 内嵌 score_stats，
        # 阈值来自真实分位标定——保证兼容场景的形态判定语义正确）
        from app.services.automl_anomaly import (
            AnomalyScoreCalibrator,
            pipeline_anomaly_scores,
        )

        fleet_matrix = _normal_matrix(1200, self.n_features)
        pipeline = Pipeline([
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
            ("detector", IsolationForest(n_estimators=50, random_state=42)),
        ]).fit(fleet_matrix)
        calibrator = AnomalyScoreCalibrator.fit(
            pipeline_anomaly_scores(pipeline, fleet_matrix), contamination=0.01,
        )
        bundle_path = Path(self.directory) / "fleet_bundle.joblib"
        joblib.dump({
            "model": pipeline,
            "feature_schema": [
                {"name": f"f{i}", "dtype": "float64"} for i in range(self.n_features)
            ],
            "target_schema": [],
            "score_stats": {
                "threshold_score": float(calibrator.threshold_score),
                "contamination": 0.01,
            },
        }, bundle_path)
        self.bundle_artifact = Artifact(
            project_id=self.project.id, name="fleet_bundle.joblib", type="model",
            storage_path=str(bundle_path), storage_uri="",
            file_size=bundle_path.stat().st_size, format="joblib",
            metadata_={"source": "automl", "sha256": "a" * 64},
        )
        self.db.add(self.bundle_artifact)
        self.db.flush()
        model = RegisteredModel(
            project_id=self.project.id, name="fleet-baseline",
            created_by_id=self.user.id,
        )
        self.db.add(model)
        self.db.flush()
        self.source_version = ModelVersion(
            registered_model_id=model.id, version_number=1,
            source_kind="onnx_artifact",
            source_model_library_id=None,
            source_artifact_id=self.bundle_artifact.id,
            onnx_artifact_id=self.bundle_artifact.id,
            framework="sklearn", algorithm="iforest",
            feature_schema=[
                {"name": f"f{i}", "dtype": "float64"} for i in range(self.n_features)
            ],
            output_schema={"task": "anomaly"},
            metrics={}, approval_status="approved",
            conversion_metadata={},
            created_by_id=self.user.id,
        )
        self.db.add(self.source_version)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _calibration_artifact(self, matrix):
        path = Path(self.directory) / f"calib-{uuid.uuid4().hex[:8]}.csv"
        pd.DataFrame(
            matrix, columns=[f"f{i}" for i in range(matrix.shape[1])],
        ).to_csv(path, index=False)
        artifact = Artifact(
            project_id=self.project.id, name=path.name, type="dataset",
            storage_path=str(path), storage_uri="",
            file_size=path.stat().st_size, format="csv", metadata_={},
        )
        self.db.add(artifact)
        self.db.commit()
        return artifact

    def test_recalibrate_compatible_device(self):
        """形态兼容设备：fpr 达标 → fleet_compatible=True，迁移版本带新阈值
        指针与回测。"""
        artifact = self._calibration_artifact(_normal_matrix(400, self.n_features, seed=7))
        result = recalibrate_device_version(
            self.db,
            source_version_id=self.source_version.id,
            calibration_artifact_id=artifact.id,
            condition_value="DEV-001",
            actor_id=str(self.user.id),
        )
        self.assertFalse(result["unfit_for_fleet"])
        self.assertTrue(result["fleet_fit"]["compatible"])
        self.assertGreaterEqual(result["backtest"]["synthetic_auc"], 0.0)
        self.assertEqual(result["calibration_rows"], 400)
        # 迁移版本：同源 artifact + 分片阈值指针指向新 stats
        version = self.db.query(ModelVersion).filter(
            ModelVersion.id == uuid.UUID(result["version_id"]),
        ).first()
        self.assertIsNotNone(version)
        self.assertEqual(
            version.source_artifact_id, self.source_version.source_artifact_id,
        )
        metadata = version.conversion_metadata or {}
        self.assertEqual(metadata.get("condition_value"), "DEV-001")
        self.assertTrue(metadata.get("device_recalibration"))
        self.assertEqual(
            metadata.get("anomaly_score_stats_artifact_id"),
            result["stats_artifact_id"],
        )
        # 模型名演进：fleet-baseline-device-DEV-001
        self.assertIn("device-DEV-001", result["registered_model_name"])

    def test_recalibrate_unfit_device_is_marked_not_rejected(self):
        """形态异于机群的设备（N(12,1)）：fpr 超 1.5×contamination → unfit
        标记；版本仍产出（不硬迁，挂载决策留给调用方）。"""
        artifact = self._calibration_artifact(
            (12.0 + _normal_matrix(400, self.n_features, seed=8)).astype(np.float32),
        )
        result = recalibrate_device_version(
            self.db,
            source_version_id=self.source_version.id,
            calibration_artifact_id=artifact.id,
            condition_value="DEV-ODD",
            actor_id=str(self.user.id),
        )
        self.assertTrue(result["unfit_for_fleet"])
        self.assertFalse(result["fleet_fit"]["compatible"])
        self.assertGreater(
            float(result["fleet_fit"]["fleet_fpr"]),
            float(result["fleet_fit"]["tolerance"]),
        )

    def test_rows_below_guard_rejected(self):
        artifact = self._calibration_artifact(_normal_matrix(100, self.n_features))
        with self.assertRaises(DeviceCalibrationError) as raised:
            recalibrate_device_version(
                self.db,
                source_version_id=self.source_version.id,
                calibration_artifact_id=artifact.id,
                condition_value="DEV-SMALL",
                actor_id=str(self.user.id),
            )
        self.assertEqual(raised.exception.code, "CALIBRATION_ROWS_INSUFFICIENT")

    def test_supervised_version_rejected(self):
        self.source_version.output_schema = {"task": "classification"}
        self.db.commit()
        artifact = self._calibration_artifact(_normal_matrix(300, self.n_features))
        with self.assertRaises(DeviceCalibrationError) as raised:
            recalibrate_device_version(
                self.db,
                source_version_id=self.source_version.id,
                calibration_artifact_id=artifact.id,
                condition_value="DEV-X",
                actor_id=str(self.user.id),
            )
        self.assertEqual(raised.exception.code, "RECALIBRATE_REQUIRES_ANOMALY_VERSION")


class TestFleetShardMountAndOverview(unittest.TestCase):
    """M9 挂载 + M10 机群监控聚合。"""

    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.db = self.Session()
        self.user = User(username="mount-owner", password_hash="hash")
        self.db.add(self.user)
        self.db.flush()
        self.project = Project(name="MountFleet", owner_id=self.user.id)
        self.db.add(self.project)
        self.db.flush()
        self.stats_path = Path(tempfile.mkdtemp(prefix="fleet-overview-")) / "stats.json"
        self.stats_path.write_text(json.dumps({
            "calibration": {"quantile_points": [0.0, 1.0]},
            "threshold_score": 0.42,
        }), encoding="utf-8")
        self.stats_artifact = Artifact(
            project_id=self.project.id, name="stats.json", type="report",
            storage_path=str(self.stats_path), storage_uri="",
            file_size=self.stats_path.stat().st_size, format="json", metadata_={},
        )
        self.db.add(self.stats_artifact)
        self.db.flush()
        self.artifact = Artifact(
            project_id=self.project.id, name="model.onnx", type="model",
            storage_path="", storage_uri="s3://models/model.onnx",
            file_size=12, format="onnx", metadata_={"sha256": "a" * 64},
        )
        self.db.add(self.artifact)
        self.db.flush()
        self.deployment = InferenceDeployment(
            project_id=self.project.id, name="fleet-deployment",
            model_version_id=None, condition_column="device_id",
            desired_state="running", observed_state="running",
            created_by_id=self.user.id,
        )
        self.versions = []
        model = RegisteredModel(
            project_id=self.project.id, name="fleet-models",
            created_by_id=self.user.id,
        )
        self.db.add(model)
        self.db.flush()
        for index in range(2):
            version = ModelVersion(
                registered_model_id=model.id, version_number=index + 1,
                source_kind="onnx_artifact",
                source_artifact_id=self.artifact.id,
                onnx_artifact_id=self.artifact.id,
                framework="onnx", algorithm="iforest",
                feature_schema=[], output_schema={"task": "anomaly"},
                metrics={}, approval_status="approved",
                conversion_metadata={
                    "anomaly_score_stats_artifact_id": str(self.stats_artifact.id),
                    "condition_value": f"DEV-{index:03d}",
                    "fleet_compatible": index == 0,
                },
                created_by_id=self.user.id,
            )
            self.db.add(version)
            self.versions.append(version)
        self.db.flush()
        self.deployment.model_version_id = self.versions[0].id
        self.db.add(self.deployment)
        self.db.flush()
        self.revision = DeploymentRevision(
            deployment_id=self.deployment.id, revision_number=1,
            strategy="immediate", status="stable", created_by_id=self.user.id,
        )
        self.db.add(self.revision)
        self.db.flush()
        self.db.add(DeploymentTarget(
            revision_id=self.revision.id, model_version_id=self.versions[0].id,
            weight_bps=10000, role="stable", condition_value="DEV-000",
        ))
        self.config = DemoLoopConfig(
            project_id=self.project.id, name="fleet-loop",
            deployment_id=self.deployment.id,
            psi_state={"per_shard": [
                {"condition_value": "DEV-000", "psi": 0.02, "level": "stable"},
            ]},
        )
        self.db.add(self.config)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_add_fleet_shard_copies_existing_targets(self):
        result = add_fleet_shard_to_deployment(
            self.db,
            deployment_id=self.deployment.id,
            version_id=self.versions[1].id,
            condition_value="DEV-001",
            actor_id=str(self.user.id),
        )
        self.assertEqual(result["revision_number"], 2)
        mounted = {
            item["condition_value"]: item for item in result["targets"]
        }
        self.assertEqual(set(mounted.keys()), {"DEV-000", "DEV-001"})
        self.assertEqual(mounted["DEV-000"]["weight_bps"], 10000)
        self.assertEqual(mounted["DEV-001"]["weight_bps"], 5000)
        # 旧 revision superseded、stable 轮换
        self.assertEqual(self.revision.status, "superseded")

    def test_duplicate_mount_rejected(self):
        add_fleet_shard_to_deployment(
            self.db,
            deployment_id=self.deployment.id,
            version_id=self.versions[1].id,
            condition_value="DEV-001",
            actor_id=str(self.user.id),
        )
        with self.assertRaises(DeviceCalibrationError) as raised:
            add_fleet_shard_to_deployment(
                self.db,
                deployment_id=self.deployment.id,
                version_id=self.versions[1].id,
                condition_value="DEV-001",
                actor_id=str(self.user.id),
            )
        self.assertEqual(raised.exception.code, "FLEET_SHARD_ALREADY_MOUNTED")

    def test_unapproved_version_rejected(self):
        self.versions[1].approval_status = "pending"
        self.db.commit()
        with self.assertRaises(DeviceCalibrationError) as raised:
            add_fleet_shard_to_deployment(
                self.db,
                deployment_id=self.deployment.id,
                version_id=self.versions[1].id,
                condition_value="DEV-001",
                actor_id=str(self.user.id),
            )
        self.assertEqual(raised.exception.code, "MODEL_NOT_APPROVED")

    def test_fleet_overview_aggregates_shards_and_psi(self):
        overview = fleet_overview(self.db, deployment_id=self.deployment.id)
        self.assertEqual(overview["condition_column"], "device_id")
        shards = overview["shards"]
        self.assertEqual(len(shards), 1)
        self.assertEqual(shards[0]["condition_value"], "DEV-000")
        self.assertEqual(shards[0]["threshold_score"], 0.42)
        self.assertEqual(overview["psi_per_shard"], [
            {"condition_value": "DEV-000", "psi": 0.02, "level": "stable"},
        ])

    def test_fleet_overview_includes_per_device_alert_rate(self):
        """M10 per-device fpr proxy：回流帧按工况分组，各分片按自身阈值统计
        报警率（与部署级 alert_comparison 同口径的分片化）。"""
        import pandas as pd

        reflow_path = Path(self.stats_path.parent) / "reflow.csv"
        pd.DataFrame([
            {"device_id": "DEV-000", "anomaly_score": 0.10},
            {"device_id": "DEV-000", "anomaly_score": 0.20},
            {"device_id": "DEV-000", "anomaly_score": 0.90},
            {"device_id": "DEV-999", "anomaly_score": 0.95},
        ]).to_csv(reflow_path, index=False)
        reflow_artifact = Artifact(
            project_id=self.project.id, name="reflow.csv", type="dataset",
            storage_path=str(reflow_path), storage_uri="",
            file_size=reflow_path.stat().st_size, format="csv", metadata_={},
        )
        self.db.add(reflow_artifact)
        self.db.flush()
        self.config.error_artifact_id = reflow_artifact.id
        self.db.commit()
        overview = fleet_overview(self.db, deployment_id=self.deployment.id)
        running = overview["shards"][0].get("running")
        self.assertIsNotNone(running)
        # DEV-000 阈值 0.42：3 行中 1 行报警 → 0.3333
        self.assertEqual(running["rows"], 3)
        self.assertEqual(running["alerts"], 1)
        self.assertEqual(running["alert_rate"], 0.3333)


class TestFleetApiSmoke(unittest.TestCase):
    """M9/M10 API 端点冒烟：重标定/挂分片/机群概览的认证与成功路径。"""

    def setUp(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from sqlalchemy.pool import StaticPool

        from app.api.auth import get_current_user
        from app.api.model_registry import build_model_registry_router
        from app.database import get_db

        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.db = self.Session()
        self.user = User(username="fleet-api", password_hash="hash")
        self.db.add(self.user)
        self.db.flush()
        self.project = Project(name="FleetApi", owner_id=self.user.id)
        self.db.add(self.project)
        self.db.commit()

        app = FastAPI()
        app.include_router(build_model_registry_router(
            registry_service=mock.Mock(),
            deployment_service=mock.Mock(),
            session_factory=self.Session,
        ))

        def override_db():
            yield self.db

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[get_current_user] = lambda: self.user
        self.client = TestClient(app)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_fleet_overview_endpoint(self):
        response = self.client.get(
            f"/api/inference-deployments/{uuid.uuid4()}/fleet-overview",
        )
        self.assertEqual(response.status_code, 404)

    def test_recalibrate_requires_known_version(self):
        response = self.client.post(
            f"/api/model-versions/{uuid.uuid4()}/recalibrate-device",
            json={"calibration_artifact_id": str(uuid.uuid4()),
                  "condition_value": "DEV-1"},
        )
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
