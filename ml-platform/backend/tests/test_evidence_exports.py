"""补齐路线第一批 F2b：闭环证据总览与证据链导出（B1-12 / E21，技术方案 §9.9/§9.10）。

验收口径：
- 任一生产模型版本可一屏看出 12 环节状态并下钻到源记录；
- 上线检查五项（模型文件 / 校验和 / 数据版本 / 评估完整性 / 生产版本唯一）结果留档
  并进入证据包；留档时重算模型文件校验和；
- 异机解包校验 SHA-256 全部通过（测试里重新解包并逐个复算，模拟异机校验）；
- 包内证据可回溯到库内记录。

平台当前不产出证据的环节（切分、主动选样、现场验证）如实标为 not_supported，
不冒充完成——这是本模块与「把没做的说成做了」之间的界线。
"""
import hashlib
import io
import json
import tempfile
import unittest
import uuid
import zipfile
from datetime import datetime
from pathlib import Path

from app.config import settings
from app.models.access import AuditEvent
from app.models.artifact import Artifact
from app.models.inference_result import InferenceResult
from app.models.labeling import AnnotationSampleCurrent, AnnotationStrategyArtifact
from app.models.model_library import ModelLibrary
from app.models.model_registry import InferenceDeployment, ModelVersion, RegisteredModel
from app.models.platform_models import GenericAnnotationTask
from app.models.quality_alerts import ModelEvidenceCheck
from app.models.training import TrainingJob
from app.models.user import User
from app.services import evidence_chain as chain
from app.services.artifact_service import build_artifact_service
from app.services.label_schema import create_label_schema
from tests.quality_alert_fixtures import QualityAlertApiCase

MODEL_BYTES = b"fake-model-bytes-for-evidence-" + uuid.uuid4().bytes


class TestEvidenceChain(QualityAlertApiCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # 默认本地存储指到临时目录：建工件、重算校验和、下载都走它
        cls._storage_dir = tempfile.TemporaryDirectory()
        cls._original_storage_dir = settings.artifact_storage_dir
        settings.artifact_storage_dir = cls._storage_dir.name
        cls._workdir = tempfile.TemporaryDirectory()

        model_path = Path(cls._workdir.name) / "model.joblib"
        model_path.write_bytes(MODEL_BYTES)
        cls.model_artifact = build_artifact_service(cls.db).create_from_file(
            cls.project.id, model_path, "evidence-model.joblib", "model",
        )
        dataset_artifact = Artifact(
            project_id=cls.project.id, name="dataset.csv", type="dataset",
            storage_path="", created_at=datetime.utcnow(),
        )
        cls.db.add(dataset_artifact)
        cls.db.flush()
        # 类方法里经类访问实例方法不会自动绑定：显式把 cls 当 self 传入
        cls.dataset_version = QualityAlertApiCase.make_dataset_version(
            cls,
            [{"vin": f"ev-{index}", "force": 5.0 + index * 0.1, "quality": index % 2}
             for index in range(25)],
            original_artifact_id=dataset_artifact.id,
        )
        cls.db.flush()

        cls.registered = RegisteredModel(
            project_id=cls.project.id, name=f"evidence-model-{uuid.uuid4().hex[:6]}",
            created_by_id=cls.owner.id,
        )
        cls.db.add(cls.registered)
        cls.db.flush()
        cls.job = TrainingJob(
            project_id=cls.project.id, user_id=cls.owner.id,
            # operator_id 列是不做 UUID 转换的方言类型，SQLite 下须传字符串
            operator_id=str(cls.owner.id),
            name=f"evidence-job-{uuid.uuid4().hex[:6]}",
            status="completed", metrics={"accuracy": 0.91},
            dataset_artifact_id=dataset_artifact.id,
        )
        cls.db.add(cls.job)
        cls.db.flush()
        cls.library = ModelLibrary(
            name=f"evidence-lib-{uuid.uuid4().hex[:6]}", project_id=cls.project.id,
            owner_id=cls.owner.id, status="completed", framework="sklearn",
            model_artifact_id=cls.model_artifact.id, file_size=len(MODEL_BYTES),
            format="joblib", training_job_id=cls.job.id,
            dataset_artifact_id=dataset_artifact.id,
        )
        cls.db.add(cls.library)
        cls.db.flush()
        cls.version = ModelVersion(
            registered_model_id=cls.registered.id, version_number=1,
            source_kind="platform_joblib", source_artifact_id=cls.model_artifact.id,
            onnx_artifact_id=cls.model_artifact.id, approval_status="approved",
            source_model_library_id=cls.library.id, created_by_id=cls.owner.id,
            algorithm="logistic_regression", framework="sklearn",
            metrics={"accuracy": 0.93, "f1": 0.9},
        )
        cls.db.add(cls.version)
        cls.db.flush()

        schema = create_label_schema(
            cls.db, project_id=cls.project.id, name=f"evidence-label-{uuid.uuid4().hex[:6]}",
            columns=[{"machine_key": "quality", "display_name": "质量",
                      "value_type": "int", "required": True}],
            commit=False,
        )
        cls.task = GenericAnnotationTask(
            project_id=cls.project.id, dataset_version_id=cls.dataset_version.id,
            label_schema_id=schema.id, owner_id=cls.owner.id, name="证据标注任务",
            status="awaiting_annotation", created_at=datetime.utcnow(),
        )
        cls.db.add(cls.task)
        cls.db.flush()
        cls.db.add(AnnotationStrategyArtifact(
            task_id=cls.task.id, task_revision=0, config_hash=uuid.uuid4().hex,
            strategy="cluster_rule", artifact={"clusters": 3}, created_by=cls.owner.id,
        ))
        cls.db.add(AnnotationSampleCurrent(
            task_id=cls.task.id, sample_id="ev-0", schema_id=schema.id, values={"quality": 1},
        ))
        cls.db.add(InferenceDeployment(
            project_id=cls.project.id, name=f"evidence-deploy-{uuid.uuid4().hex[:6]}",
            model_version_id=cls.version.id, created_by_id=cls.owner.id,
            desired_state="running", created_at=datetime.utcnow(),
        ))
        cls.db.add(InferenceResult(
            request_id=f"ev-flagged-{uuid.uuid4().hex[:6]}", project_id=cls.project.id,
            model_version_id=cls.version.id, alert_triggered=True,
            occurred_at=datetime.utcnow(), expires_at=datetime(2099, 1, 1),
        ))
        cls.db.commit()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        settings.artifact_storage_dir = cls._original_storage_dir
        cls._storage_dir.cleanup()
        cls._workdir.cleanup()

    def _overview_url(self, version=None):
        return f"/api/projects/{self.project.id}/model-versions/{(version or self.version).id}/evidence-overview"

    def _export(self, scope, target_id):
        return self.client.post(
            f"/api/projects/{self.project.id}/evidence-exports",
            json={"scope": scope, "target_id": str(target_id)},
        )

    def _download_zip(self, artifact_id) -> tuple[dict, dict[str, bytes]]:
        response = self.client.get(
            f"/api/projects/{self.project.id}/evidence-exports/{artifact_id}/download",
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers["content-type"], "application/zip")
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            return (
                {name: archive.read(name) for name in archive.namelist()},
                response.headers,
            )

    def _verify_manifest(self, files: dict[str, bytes]) -> list[str]:
        """模拟异机解包：逐条复算 MANIFEST.SHA256。返回清单里的相对路径。"""
        manifest = files["MANIFEST.SHA256"].decode("utf-8")
        listed = []
        for line in manifest.splitlines():
            digest, name = line.split("  ", 1)
            self.assertEqual(hashlib.sha256(files[name]).hexdigest(), digest, name)
            listed.append(name)
        self.assertEqual(sorted(listed), sorted(name for name in files if name != "MANIFEST.SHA256"))
        return listed

    def test_overview_reports_all_twelve_stages_with_evidence_refs(self):
        response = self.client.get(self._overview_url())
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        stages = {stage["key"]: stage for stage in body["stages"]}
        self.assertEqual(len(stages), 12)
        self.assertEqual([stage["key"] for stage in body["stages"]], [item[0] for item in chain.STAGES])
        expected = {
            "ingest": "complete", "split": "not_supported", "clustering": "complete",
            "annotation": "complete", "active_sampling": "not_supported", "training": "complete",
            "evaluation": "complete", "release": "complete", "production": "complete",
            "field_validation": "not_supported", "feedback": "complete", "iteration": "pending",
        }
        self.assertEqual({key: stage["status"] for key, stage in stages.items()}, expected)
        # 可下钻：依据引用指向库内记录
        self.assertEqual(stages["ingest"]["evidence"][0]["ref_id"], str(self.dataset_version.id))
        self.assertEqual(stages["training"]["evidence"][0]["ref_id"], str(self.job.id))
        self.assertEqual(stages["annotation"]["evidence"][0]["ref_id"], str(self.task.id))
        self.assertIn("1 个标注任务", stages["annotation"]["note"])
        # 平台尚不产出的环节写明随哪一批接入，不冒充完成
        self.assertIn("第二批", stages["split"]["note"])
        self.assertIn("第四批", stages["field_validation"]["note"])
        self.assertEqual(body["summary"]["not_supported"], 3)
        self.assertFalse(body["checksum_verified"], "总览不重算文件哈希")

    def test_launch_checks_cover_five_items(self):
        checks = {check["key"]: check for check in self.client.get(self._overview_url()).json()["checks"]}
        self.assertEqual(
            sorted(checks), sorted(["model_file", "checksum", "data_version", "evaluation", "production_unique"]),
        )
        self.assertTrue(all(check["status"] == "pass" for check in checks.values()), checks)
        self.assertEqual(checks["checksum"]["value"], self.model_artifact.metadata_["sha256"])
        self.assertTrue(all(check["title"] for check in checks.values()))

    def test_external_model_without_platform_lineage_is_labelled_honestly(self):
        external = ModelVersion(
            registered_model_id=self.registered.id, version_number=2,
            source_kind="onnx_artifact", source_artifact_id=self.model_artifact.id,
            onnx_artifact_id=self.model_artifact.id, created_by_id=self.owner.id,
        )
        self.db.add(external)
        self.db.commit()
        stages = {
            stage["key"]: stage["status"]
            for stage in self.client.get(self._overview_url(external)).json()["stages"]
        }
        self.assertEqual(stages["training"], "not_applicable")
        self.assertEqual(stages["ingest"], "missing")
        self.assertEqual(stages["annotation"], "missing")
        self.assertEqual(stages["release"], "pending")
        self.assertEqual(stages["production"], "pending")

    def test_production_unique_fails_when_two_versions_run_side_by_side(self):
        rival = ModelVersion(
            registered_model_id=self.registered.id, version_number=3,
            source_kind="platform_joblib", source_artifact_id=self.model_artifact.id,
            onnx_artifact_id=self.model_artifact.id, created_by_id=self.owner.id,
            source_model_library_id=self.library.id,
        )
        self.db.add(rival)
        self.db.flush()
        self.db.add(InferenceDeployment(
            project_id=self.project.id, name=f"evidence-rival-{uuid.uuid4().hex[:6]}",
            model_version_id=rival.id, created_by_id=self.owner.id,
            desired_state="running", created_at=datetime.utcnow(),
        ))
        self.db.commit()
        checks = {
            check["key"]: check
            for check in self.client.get(self._overview_url(rival)).json()["checks"]
        }
        self.assertEqual(checks["production_unique"]["status"], "fail")
        self.assertIn("2 个版本同时在生产", checks["production_unique"]["detail"])

    def test_archive_recomputes_the_model_checksum_and_keeps_a_snapshot(self):
        response = self.client.post(self._overview_url().replace("evidence-overview", "evidence-checks"))
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertTrue(body["checksum_verified"])
        checksum = next(check for check in body["checks"] if check["key"] == "checksum")
        self.assertEqual(checksum["status"], "pass")
        self.assertIn("重新计算", checksum["detail"])
        self.db.expire_all()
        record = self.db.get(ModelEvidenceCheck, uuid.UUID(body["archived_check_id"]))
        self.assertIsNotNone(record)
        self.assertEqual(len(record.summary["stages"]), 12)
        overview = self.client.get(self._overview_url()).json()
        self.assertEqual(overview["archived_check"]["id"], body["archived_check_id"])

        # 文件被改动后重新留档：重算值与登记值不一致，必须报失败
        # （存储里的文件名用源文件名 model.joblib，不是工件名）
        stored = next(Path(self._storage_dir.name).rglob("model.joblib"))
        stored.write_bytes(MODEL_BYTES + b"tampered")
        body = self.client.post(self._overview_url().replace("evidence-overview", "evidence-checks")).json()
        checksum = next(check for check in body["checks"] if check["key"] == "checksum")
        self.assertEqual(checksum["status"], "fail")
        self.assertIn("不一致", checksum["detail"])
        stored.write_bytes(MODEL_BYTES)

    def test_archive_needs_manage_permission_but_overview_is_readable(self):
        self.act_as(self.operator)
        self.assertEqual(
            self.client.post(self._overview_url().replace("evidence-overview", "evidence-checks")).status_code,
            403,
        )
        self.act_as(self.viewer)
        self.assertEqual(self.client.get(self._overview_url()).status_code, 200)

    def test_alert_export_builds_a_zip_with_verifiable_manifest(self):
        alert = self.make_alert(
            evidence={"kind": "model_risk", "score": 0.97, "model_version_id": str(self.version.id),
                      "occurred_at": "2026-11-26T09:00:00"},
            merge_key=f"evidence-{self.case_key}",
        )
        self.assertEqual(self.ack(alert.id).status_code, 200)  # 留下一条审计事件
        self.db.expire_all()
        flagged = self.db.query(InferenceResult).filter(
            InferenceResult.model_version_id == self.version.id,
        ).first()
        flagged.alert_id = alert.id
        self.db.commit()

        created = self._export("alert", alert.id)
        self.assertEqual(created.status_code, 200, created.text)
        body = created.json()
        self.assertTrue(body["artifact_id"])
        self.assertTrue(body["include_audit"], "项目负责人持有 audit.read，审计日志随包")

        files, headers = self._download_zip(body["artifact_id"])
        listed = self._verify_manifest(files)
        for expected in ("alert/alert.json", "alert/criteria.json", "alert/inference_results.json",
                         "model/model_version.json", "model/stages.json", "model/launch_checks.json",
                         "model/model_artifact.json", "audit/audit_events.json"):
            self.assertIn(expected, listed)
        self.assertIn("model_file/evidence-model.joblib", listed)
        self.assertEqual(files["model_file/evidence-model.joblib"], MODEL_BYTES, "模型文件本体随包")
        self.assertIn("attachment", headers["content-disposition"])

        # 包内证据可回溯到库内记录
        payload = json.loads(files["alert/alert.json"])
        self.assertEqual(payload["alert"]["id"], str(alert.id))
        self.assertIn("acknowledged", [event["action"] for event in payload["events"]])
        model_payload = json.loads(files["model/model_version.json"])
        self.assertEqual(model_payload["version"]["id"], str(self.version.id))
        audit_payload = json.loads(files["audit/audit_events.json"])
        self.assertEqual(
            sorted({row["resource_id"] for row in audit_payload["items"]}),
            sorted({str(alert.id)}),
        )

    def test_audit_log_is_not_exported_without_audit_read(self):
        alert = self.make_alert(merge_key=f"evidence-op-{self.case_key}")
        self.ack(alert.id)
        self.act_as(self.operator)
        created = self._export("alert", alert.id).json()
        self.assertFalse(created["include_audit"])
        files, _ = self._download_zip(created["artifact_id"])
        self._verify_manifest(files)
        self.assertNotIn("audit/audit_events.json", files)
        self.assertIn("alert/alert.json", files)

    def test_model_version_export_and_scope_guards(self):
        created = self._export("model_version", self.version.id)
        self.assertEqual(created.status_code, 200, created.text)
        files, _ = self._download_zip(created.json()["artifact_id"])
        listed = self._verify_manifest(files)
        for expected in ("model/stages.json", "model/launch_checks.json", "training/training_job.json",
                         "data/dataset_version.json", "production/deployments.json",
                         "production/alerts.json"):
            self.assertIn(expected, listed)

        # 别的项目里的 id、非法 scope、不存在的预警都被拒，且不产生半截工件
        before = self.db.query(Artifact).filter(Artifact.type == "evidence_export").count()
        self.assertEqual(self._export("model_version", uuid.uuid4()).status_code, 404)
        self.assertEqual(self._export("alert", uuid.uuid4()).status_code, 404)
        invalid = self.client.post(
            f"/api/projects/{self.project.id}/evidence-exports",
            json={"scope": "dataset", "target_id": str(self.version.id)},
        )
        self.assertEqual(invalid.status_code, 422)
        self.assertEqual(self.db.query(Artifact).filter(Artifact.type == "evidence_export").count(), before)

    def test_download_is_scoped_to_the_project(self):
        created = self._export("model_version", self.version.id).json()
        self.act_as(self.viewer)
        self.assertEqual(
            self.client.get(
                f"/api/projects/{self.project.id}/evidence-exports/{created['artifact_id']}/download",
            ).status_code, 200,
            "只读成员可以取回证据包",
        )
        stranger = User(username=f"ev-stranger-{uuid.uuid4().hex[:6]}", password_hash="hash")
        self.db.add(stranger)
        self.db.commit()
        self.act_as(stranger)
        self.assertEqual(
            self.client.get(
                f"/api/projects/{self.project.id}/evidence-exports/{created['artifact_id']}/download",
            ).status_code, 404,
        )


if __name__ == "__main__":
    unittest.main()
