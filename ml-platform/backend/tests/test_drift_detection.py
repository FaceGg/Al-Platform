"""补齐路线第一批 F4：漂移检测（B1-09，技术方案 §9C）。

验收口径：
- 特征级 PSI 的基线来自训练数据集版本（按血缘惰性计算），任一报告可追溯到所用基线；
- 特征直方图覆盖**全部**样本——包括超限降级后被丢弃明细的正常样本；
- 定时批检真实产出分级报告（样本不足 / 稳定 / 关注 / 严重）；严重级自动通知；
- 数据质量命中（缺失、恒值）进预警中心（传感器异常）；漂移是触发器，不自动处置。

本期未接入的信号（PCA 重构误差、分数级 PSI 并入报告、分片按版本分桶）在报告的
summary.not_wired 里如实写明——测试断言这个字段存在，防止以后被悄悄当成已做。
"""
import math
import unittest
import uuid
from datetime import datetime, timedelta

from app.config import settings
from app.database import Base, SessionLocal
from app.models.artifact import Artifact
from app.models.data_version import DatasetSample, DatasetVersion
from app.models.inference_result import InferenceResult, InferenceResultBucket
from app.models.model_library import ModelLibrary
from app.models.model_registry import InferenceDeployment, ModelVersion, RegisteredModel
from app.models.drift import DriftBaseline, DriftReport, DriftReportFeature, InferenceFeatureHistogram
from app.models.notifications import InAppNotification, NotificationOutbox
from app.models.project import Project
from app.models.quality_alerts import QualityAlert
from app.models.training import TrainingJob
from app.models.user import User
from app.services import drift_detection as drift
from app.services.inference_results import InferenceResultRecorder
from tests.quality_alert_fixtures import QualityAlertApiCase


class TestDriftPureFunctions(unittest.TestCase):
    def test_psi_matches_hand_computation(self):
        # 期望 [0.5, 0.5]，实际 [0.9, 0.1]：0.4·ln(1.8) + (−0.4)·ln(0.2)
        self.assertAlmostEqual(drift.psi([0.5, 0.5], [0.9, 0.1]), 0.4 * math.log(1.8) - 0.4 * math.log(0.2), places=9)
        self.assertAlmostEqual(drift.psi([3, 7], [30, 70]), 0.0, places=12, msg="同一分布（计数不同）PSI 为 0")
        self.assertEqual(drift.psi([0, 0], [1, 2]), 0.0, msg="基线全零时无法比较，返回 0 而不是除零")
        self.assertEqual(drift.psi([1, 0], [0, 0]), 0.0)
        with self.assertRaises(ValueError):
            drift.psi([1, 2], [1, 2, 3])

    def test_psi_is_symmetric_in_zero_bins_but_not_in_general(self):
        # 双方都为 0 的箱不贡献；只有一方为 0 的箱贡献一个有限值（epsilon 平滑）
        self.assertAlmostEqual(drift.psi([1, 0], [1, 0]), 0.0, places=12)
        self.assertGreater(drift.psi([1, 0], [0.5, 0.5]), 0.0)

    def test_quantile_edges_equal_frequency(self):
        edges = drift.quantile_edges(list(range(1, 101)), 10)
        # 第 k 个边界取第 round(k·99/10) 个次序统计量；Python 的 round 是银行家舍入，
        # round(59.4) = 59 → 第 60 个值，所以第六个内边界是 60 而不是 61
        self.assertEqual(edges, [1.0, 11.0, 21.0, 31.0, 41.0, 51.0, 60.0, 70.0, 80.0, 90.0, 100.0])
        # 等概率：每个箱里的样本数接近
        counts = [0] * (len(edges) - 1)
        for value in range(1, 101):
            counts[drift.bin_index(value, edges)] += 1
        self.assertEqual(counts, [10, 10, 10, 10, 10, 9, 10, 10, 10, 11])
        self.assertEqual(drift.quantile_edges([7, 7, 7], 10), [7.0, 7.0], msg="常量特征 → 退化基线")
        self.assertEqual(drift.quantile_edges([], 10), [])

    def test_bin_index(self):
        edges = [1, 11, 21, 31]
        self.assertEqual(drift.bin_index(10, edges), 0)
        self.assertEqual(drift.bin_index(11, edges), 1, "等于内边界的值归上一箱")
        self.assertEqual(drift.bin_index(31, edges), 2)
        self.assertEqual(drift.bin_index(999, edges), 2, "超出基线上界归末箱")
        self.assertEqual(drift.bin_index(-5, edges), 0)
        # 退化基线：等于常量 → 箱内；不等于 → 箱外（否则常量特征永远判不出漂移）
        self.assertEqual(drift.bin_index(7, [7, 7]), 0)
        self.assertEqual(drift.bin_index(8, [7, 7]), 2)


class TestDriftDetection(QualityAlertApiCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        drift.reset_baseline_cache()
        tag = uuid.uuid4().hex[:6]
        dataset_artifact = Artifact(
            project_id=cls.project.id, name="drift-dataset.csv", type="dataset",
            storage_path="", created_at=datetime.utcnow(),
        )
        cls.db.add(dataset_artifact)
        cls.db.flush()
        # force 均匀分布在 1–200；current 是训练时的常量特征
        cls.dataset_version = QualityAlertApiCase.make_dataset_version(
            cls,
            [{"vin": f"dr-{index}", "force": float(index + 1), "current": 3.0, "quality": index % 2}
             for index in range(200)],
            original_artifact_id=dataset_artifact.id,
        )
        model_artifact = Artifact(
            project_id=cls.project.id, name="drift-model.joblib", type="model",
            storage_path="", created_at=datetime.utcnow(),
        )
        cls.db.add(model_artifact)
        cls.db.flush()
        cls.registered = RegisteredModel(
            project_id=cls.project.id, name=f"drift-model-{tag}", created_by_id=cls.owner.id,
        )
        cls.db.add(cls.registered)
        cls.db.flush()
        cls.job = TrainingJob(
            project_id=cls.project.id, user_id=cls.owner.id, operator_id=str(cls.owner.id),
            name=f"drift-job-{tag}", status="completed",
            dataset_artifact_id=dataset_artifact.id,
        )
        cls.db.add(cls.job)
        cls.db.flush()
        cls.library = ModelLibrary(
            name=f"drift-lib-{tag}", project_id=cls.project.id, owner_id=cls.owner.id,
            status="completed", framework="sklearn", model_artifact_id=model_artifact.id,
            format="joblib", training_job_id=cls.job.id,
            dataset_artifact_id=dataset_artifact.id,
        )
        cls.db.add(cls.library)
        cls.db.flush()
        cls.version = ModelVersion(
            registered_model_id=cls.registered.id, version_number=1,
            source_kind="platform_joblib", source_artifact_id=model_artifact.id,
            onnx_artifact_id=model_artifact.id, created_by_id=cls.owner.id,
            source_model_library_id=cls.library.id,
            feature_schema=[{"name": "force", "dtype": "float64"}, {"name": "current", "dtype": "float64"}],
        )
        cls.db.add(cls.version)
        cls.external_version = ModelVersion(
            registered_model_id=cls.registered.id, version_number=2,
            source_kind="onnx_artifact", source_artifact_id=model_artifact.id,
            onnx_artifact_id=model_artifact.id, created_by_id=cls.owner.id,
            feature_schema=[{"name": "force", "dtype": "float64"}],
        )
        cls.db.add(cls.external_version)
        cls.db.flush()
        cls.deployment = InferenceDeployment(
            project_id=cls.project.id, name=f"drift-deploy-{tag}",
            model_version_id=cls.version.id, created_by_id=cls.owner.id,
            desired_state="running", created_at=datetime.utcnow(),
        )
        cls.db.add(cls.deployment)
        cls.db.commit()

    def setUp(self):
        super().setUp()
        drift.reset_baseline_cache()
        for model in (InferenceFeatureHistogram, DriftReport, QualityAlert,
                      InAppNotification, NotificationOutbox):
            self.db.query(model).filter(model.project_id == self.project.id).delete(
                synchronize_session="fetch",
            )
        # 基线表按模型版本归属（没有项目列）：清掉本类两个模型版本的基线，让每条用例重算
        self.db.query(DriftBaseline).filter(
            DriftBaseline.model_version_id.in_([self.version.id, self.external_version.id]),
        ).delete(synchronize_session="fetch")
        # 用例里临时建的运行态部署会漂到后面的用例里（被定时扫描扫到）：只保留类级的两个
        for stale in self.db.query(InferenceDeployment).filter(
            InferenceDeployment.project_id == self.project.id,
            InferenceDeployment.id.notin_([self.deployment.id]),
        ).all():
            self.db.query(DriftReport).filter(DriftReport.deployment_id == stale.id).delete(
                synchronize_session="fetch",
            )
            self.db.delete(stale)
        self.db.query(DriftReportFeature).delete(synchronize_session="fetch")
        self.db.commit()
        self.addCleanup(setattr, settings, "drift_min_samples", settings.drift_min_samples)
        settings.drift_min_samples = 20

    def _histogram(self, feature, counts, *, missing=0, hours_ago=1, model_version=None):
        total = sum(counts) + missing
        self.db.add(InferenceFeatureHistogram(
            bucket_start=(datetime.utcnow() - timedelta(hours=hours_ago)).replace(
                minute=0, second=0, microsecond=0,
            ),
            project_id=self.project.id, model_version_id=(model_version or self.version).id,
            feature_name=feature, bin_counts=list(counts), missing_count=missing, total_count=total,
        ))
        self.db.commit()

    def test_baseline_is_computed_from_the_training_dataset_by_lineage(self):
        baselines = drift.ensure_baselines(self.db, self.version.id)
        self.assertIsNotNone(baselines)
        self.assertEqual(set(baselines), {"force", "current"})
        force = baselines["force"]
        self.assertEqual(len(force["probs"]), 10)
        self.assertAlmostEqual(sum(force["probs"]), 1.0, places=9)
        self.assertTrue(all(abs(share - 0.1) < 0.02 for share in force["probs"]), force["probs"])
        self.assertEqual(force["sample_count"], 200)
        # 基线落库：任一报告可追溯到所用基线
        rows = self.db.query(DriftBaseline).filter(DriftBaseline.model_version_id == self.version.id).all()
        self.assertEqual({row.feature_name for row in rows}, {"force", "current"})
        self.assertEqual({row.source for row in rows}, {"training_dataset"})
        self.assertTrue(all(row.dataset_version_id == self.dataset_version.id for row in rows))

    def test_model_without_training_lineage_has_no_baseline(self):
        self.assertIsNone(drift.ensure_baselines(self.db, self.external_version.id))
        self.assertEqual(
            self.db.query(DriftBaseline).filter(DriftBaseline.model_version_id == self.external_version.id).count(),
            0,
        )

    def test_histogram_accumulation_counts_every_sample(self):
        drift.ensure_baselines(self.db, self.version.id)
        records = [{"force": float(index + 1), "current": 3.0} for index in range(20)]
        records[5]["force"] = None  # 缺失
        scopes = [(None, None, None, "online")] * len(records)
        written = drift.record_feature_histograms(
            self.db, project_id=self.project.id, model_version_id=self.version.id,
            scopes=scopes, records=records,
        )
        self.assertEqual(written, 2)
        # 再累计一批：同一小时桶内累加，而不是覆盖或另起一行
        second_written = drift.record_feature_histograms(
            self.db, project_id=self.project.id, model_version_id=self.version.id,
            scopes=scopes[:10] + [(None, None, None, "demo")] * 5, records=records[:15],
        )
        self.assertEqual(second_written, 2)
        # 先提交再让对象失效：expire_all 会丢弃尚未刷入的改动（真实落库路径都会提交）
        self.db.commit()
        self.db.expire_all()
        rows = {row.feature_name: row for row in self.db.query(InferenceFeatureHistogram).all()}
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows["force"].total_count, 30, "演示通道的 5 条不计")
        self.assertEqual(rows["force"].missing_count, 2)
        self.assertEqual(sum(rows["force"].bin_counts) + rows["force"].missing_count, 30)
        self.assertEqual(rows["current"].total_count, 30)

    def test_scan_without_samples_reports_insufficient(self):
        report = drift.scan_deployment(self.db, self.deployment, notify=False)
        self.db.commit()
        self.assertEqual(report.level, "insufficient")
        self.assertEqual(report.sample_count, 0)
        self.assertIn("少于最小样本", " ".join(report.summary["notes"]))
        self.assertIn("pca_reconstruction_error", report.summary["not_wired"])

    def test_scan_without_baseline_says_so(self):
        external = InferenceDeployment(
            project_id=self.project.id, name=f"drift-ext-{uuid.uuid4().hex[:6]}",
            model_version_id=self.external_version.id, created_by_id=self.owner.id,
            desired_state="running", created_at=datetime.utcnow(),
        )
        self.db.add(external)
        self.db.commit()
        report = drift.scan_deployment(self.db, external, notify=False)
        self.assertEqual(report.level, "insufficient")
        self.assertIn("没有训练分布基线", " ".join(report.summary["notes"]))

    def test_stable_distribution_produces_no_signals(self):
        drift.ensure_baselines(self.db, self.version.id)
        self._histogram("force", [5] * 10)
        self._histogram("current", [50])
        report = drift.scan_deployment(self.db, self.deployment, notify=False)
        self.db.commit()
        self.assertEqual(report.level, "stable")
        self.assertEqual(self.db.query(DriftReportFeature).count(), 0)
        self.assertEqual(self.db.query(QualityAlert).filter(QualityAlert.project_id == self.project.id).count(), 0)

    def test_shifted_distribution_is_graded_and_notified(self):
        drift.ensure_baselines(self.db, self.version.id)
        self._histogram("force", [0, 0, 0, 0, 0, 0, 0, 0, 0, 200])
        report = drift.scan_deployment(self.db, self.deployment, notify=True)
        self.db.commit()
        self.assertEqual(report.level, "severe")
        self.assertEqual(report.sample_count, 200)
        signals = self.db.query(DriftReportFeature).filter(DriftReportFeature.report_id == report.id).all()
        by_kind = {item.signal_kind: item for item in signals}
        self.assertEqual(by_kind["feature_psi"].feature_name, "force")
        self.assertGreaterEqual(by_kind["feature_psi"].value, 0.25)
        self.assertEqual(by_kind["feature_psi"].level, "severe")
        self.assertIsNotNone(by_kind["feature_psi"].detail.get("baseline_id"), "特征明细可追溯到所用基线")
        self.assertEqual(len(by_kind["feature_psi"].detail["observed_shares"]), 10)
        # 整体平移到最高箱时，取值也都集中在训练分布的同一个分箱内——数据质量信号
        # 如实同时出现（措辞是「集中在单一分箱」，不说「恒值」）
        self.assertIn("dq_constant", by_kind)
        # 严重级：域事件入 outbox + 站内信项目负责人；不自动处置（没有模型或部署被改动）
        outbox = self.db.query(NotificationOutbox).filter(NotificationOutbox.event_type == "drift.severe").all()
        self.assertEqual(len(outbox), 1)
        self.assertEqual(outbox[0].payload.get("report_id"), str(report.id))
        self.assertEqual(outbox[0].payload.get("drifted_feature_count"), 1)
        self.assertTrue(self.db.query(InAppNotification).filter(
            InAppNotification.event_type == "drift.severe", InAppNotification.recipient_user_id == self.owner.id,
        ).first() is not None)
        self.db.expire_all()
        deployment = self.db.get(InferenceDeployment, self.deployment.id)
        self.assertEqual((deployment.desired_state, deployment.model_version_id), ("running", self.version.id))

    def test_watch_level_does_not_notify(self):
        drift.ensure_baselines(self.db, self.version.id)
        # 轻度偏移：占比 0.08×9 + 0.28，PSI ≈ 0.2255——落在关注档（0.10）与严重档（0.25）之间
        self._histogram("force", [16] * 9 + [56])
        report = drift.scan_deployment(self.db, self.deployment, notify=True)
        self.db.commit()
        self.assertEqual(report.level, "watch")
        self.assertEqual(self.db.query(NotificationOutbox).filter(NotificationOutbox.event_type == "drift.severe").count(), 0)

    def test_data_quality_hits_become_sensor_anomaly_alerts(self):
        drift.ensure_baselines(self.db, self.version.id)
        self._histogram("force", [10] * 10, missing=190)  # 缺失率 95%
        self._histogram("current", [200])                  # 退化基线：训练时就是常量，不算恒值异常
        report = drift.scan_deployment(self.db, self.deployment, notify=True)
        self.db.commit()
        kinds = sorted(item.signal_kind for item in self.db.query(DriftReportFeature).all())
        self.assertEqual(kinds, ["dq_missing"])
        alerts = self.db.query(QualityAlert).filter(
            QualityAlert.project_id == self.project.id, QualityAlert.source_type == "sensor_anomaly",
        ).all()
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].evidence["signal"], "dq_missing")
        self.assertEqual(alerts[0].evidence["report_id"], str(report.id))
        self.assertEqual(alerts[0].merge_key, "drift:dq_missing:force")

    def test_constant_feature_is_flagged_unless_it_was_constant_in_training(self):
        drift.ensure_baselines(self.db, self.version.id)
        self._histogram("force", [200, 0, 0, 0, 0, 0, 0, 0, 0, 0])
        report = drift.scan_deployment(self.db, self.deployment, notify=True)
        self.db.commit()
        self.assertIn("dq_constant", [item.signal_kind for item in self.db.query(DriftReportFeature).all()])
        self.assertTrue(report.level in ("watch", "severe"))

    def test_run_drift_scan_covers_only_running_deployments(self):
        stopped = InferenceDeployment(
            project_id=self.project.id, name=f"drift-stopped-{uuid.uuid4().hex[:6]}",
            model_version_id=self.version.id, created_by_id=self.owner.id,
            desired_state="stopped", created_at=datetime.utcnow(),
        )
        self.db.add(stopped)
        self.db.commit()
        summary = drift.run_drift_scan(session_factory=self.Session)
        self.assertEqual((summary["scanned"], summary["errors"]), (1, 0))
        self.assertEqual(summary["levels"], {"insufficient": 1})
        self.assertEqual(self.db.query(DriftReport).filter(DriftReport.deployment_id == stopped.id).count(), 0)

    def test_drift_endpoints(self):
        base = f"/api/projects/{self.project.id}/drift"
        running_external = InferenceDeployment(
            project_id=self.project.id, name=f"drift-ext-run-{uuid.uuid4().hex[:6]}",
            model_version_id=self.external_version.id, created_by_id=self.owner.id,
            desired_state="running", created_at=datetime.utcnow(),
        )
        self.db.add(running_external)
        self.db.commit()

        deployments = self.client.get(f"{base}/deployments").json()
        by_name = {item["name"]: item for item in deployments["items"]}
        self.assertTrue(by_name[self.deployment.name]["has_baseline"])
        self.assertFalse(
            by_name[running_external.name]["has_baseline"],
            "没有训练数据血缘的部署做不了特征级检测：如实标出",
        )
        self.assertEqual(deployments["scan_interval_seconds"], 300)

        scanned = self.client.post(f"{base}/scan")
        self.assertEqual(scanned.status_code, 200, scanned.text)
        self.assertEqual(scanned.json()["scanned"], 2)
        listing = self.client.get(f"{base}/reports").json()
        self.assertEqual(listing["total"], 2)
        report = next(item for item in listing["items"] if item["deployment_id"] == str(self.deployment.id))
        self.assertEqual(report["level"], "insufficient")
        detail = self.client.get(f"{base}/reports/{report['id']}").json()
        self.assertEqual(detail["features"], [])
        self.assertIn("pca_reconstruction_error", detail["not_wired"])

        proposed = self.client.post(f"{base}/reports/{report['id']}/propose-retrain")
        self.assertEqual(proposed.status_code, 200, proposed.text)
        self.assertIsNotNone(proposed.json()["proposal_at"])
        self.assertEqual(
            self.client.post(f"{base}/reports/{report['id']}/propose-retrain").status_code, 409,
        )
        self.db.expire_all()
        self.assertTrue(self.db.query(InAppNotification).filter(
            InAppNotification.event_type == "drift.retrain_proposal",
        ).first() is not None)
        self.assertEqual(self.client.get(f"{base}/reports/{uuid.uuid4()}").status_code, 404)

        other = next(item for item in listing["items"] if item["deployment_id"] == str(running_external.id))
        self.act_as(self.operator)
        self.assertEqual(
            self.client.post(f"{base}/reports/{other['id']}/propose-retrain").status_code, 403,
        )
        self.assertEqual(self.client.post(f"{base}/scan").status_code, 403)
        self.act_as(self.viewer)
        self.assertEqual(self.client.get(f"{base}/reports").status_code, 200)


class _OverCapCounter:
    """恒返回超限值：触发「只存异常 + 抽样」降级，正常样本不落明细。"""

    def incr(self, _key):
        return 200_001

    def expire(self, _key, _ttl):
        return True


class _FakeStorage:
    def put_snapshot(self, source, project_id, date_key, filename):
        from types import SimpleNamespace

        return SimpleNamespace(uri=f"file:///fake/inference-snapshots/{date_key}/{filename}")


class TestHistogramsCoverPersistPath(unittest.TestCase):
    """经真实落库路径：直方图覆盖全部样本，包括超限降级后被丢弃明细的正常样本。"""

    @classmethod
    def setUpClass(cls):
        from app.database import engine

        drift.reset_baseline_cache()
        Base.metadata.create_all(bind=engine)
        tag = uuid.uuid4().hex[:8]
        with SessionLocal() as db:
            user = User(username=f"drift-persist-{tag}", password_hash="hash")
            db.add(user)
            db.flush()
            project = Project(name=f"Drift persist {tag}", owner_id=user.id)
            db.add(project)
            db.flush()
            dataset_artifact = Artifact(
                project_id=project.id, name="persist-dataset.csv", type="dataset",
                storage_path="", created_at=datetime.utcnow(),
            )
            db.add(dataset_artifact)
            db.flush()
            version_number = int(db.query(DatasetVersion.version).filter(
                DatasetVersion.project_id == project.id,
            ).count()) + 1
            dataset_version = DatasetVersion(
                project_id=project.id, operator_id=user.id, version=version_number,
                status="ready", row_count=200, column_count=2,
                content_hash=uuid.uuid4().hex, schema_hash=uuid.uuid4().hex,
                original_artifact_id=dataset_artifact.id,
            )
            db.add(dataset_version)
            db.flush()
            for index in range(200):
                db.add(DatasetSample(
                    dataset_version_id=dataset_version.id, sample_id=f"p-{index}", row_index=index,
                    values={"force": float(index + 1)},
                ))
            model_artifact = Artifact(
                project_id=project.id, name="persist-model.joblib", type="model",
                storage_path="", created_at=datetime.utcnow(),
            )
            db.add(model_artifact)
            db.flush()
            registered = RegisteredModel(project_id=project.id, name=f"persist-model-{tag}", created_by_id=user.id)
            db.add(registered)
            db.flush()
            library = ModelLibrary(
                name=f"persist-lib-{tag}", project_id=project.id, owner_id=user.id,
                status="completed", model_artifact_id=model_artifact.id, format="joblib",
                dataset_artifact_id=dataset_artifact.id,
            )
            db.add(library)
            db.flush()
            cls.version_id = uuid.uuid4()
            db.add(ModelVersion(
                id=cls.version_id, registered_model_id=registered.id, version_number=1,
                source_kind="platform_joblib", source_artifact_id=model_artifact.id,
                onnx_artifact_id=model_artifact.id, created_by_id=user.id,
                source_model_library_id=library.id,
                feature_schema=[{"name": "force", "dtype": "float64"}],
            ))
            db.commit()
            cls.project_id = project.id

    @classmethod
    def tearDownClass(cls):
        drift.reset_baseline_cache()
        with SessionLocal() as db:
            db.query(InferenceFeatureHistogram).filter(
                InferenceFeatureHistogram.project_id == cls.project_id,
            ).delete(synchronize_session="fetch")
            db.query(DriftBaseline).filter(DriftBaseline.model_version_id == cls.version_id).delete(
                synchronize_session="fetch",
            )
            db.query(InferenceResult).filter(InferenceResult.project_id == cls.project_id).delete(
                synchronize_session="fetch",
            )
            db.query(InferenceResultBucket).filter(InferenceResultBucket.project_id == cls.project_id).delete(
                synchronize_session="fetch",
            )
            db.commit()

    def _histogram_total(self):
        with SessionLocal() as db:
            return sum(int(row.total_count) for row in db.query(InferenceFeatureHistogram).filter(
                InferenceFeatureHistogram.model_version_id == self.version_id,
            ).all())

    def test_histograms_cover_all_samples_even_when_detail_rows_are_dropped(self):
        records = [{"force": float((index % 50) + 1)} for index in range(60)]
        request_id = f"drift-persist-{uuid.uuid4().hex[:6]}"
        InferenceResultRecorder(storage=_FakeStorage(), counter=_OverCapCounter(), sample_rate=0.0).record_prediction(
            request_id=request_id, project_id=self.project_id, model_version_id=self.version_id,
            result={"predictions": ["OK"] * 60}, records=records,
            occurred_at=datetime.utcnow(),
        )
        with SessionLocal() as db:
            detailed = db.query(InferenceResult).filter(InferenceResult.request_id == request_id).count()
        # 超限降级：60 条正常样本一条明细都不落
        self.assertEqual(detailed, 0)
        # 但直方图仍然覆盖了全部 60 条样本
        self.assertEqual(self._histogram_total(), 60)


if __name__ == "__main__":
    unittest.main()
