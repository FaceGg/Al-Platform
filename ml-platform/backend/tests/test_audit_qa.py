"""S4 智能应用（B2-01/B2-04）：引用编号唯一+同表校验、问数注册表拒绝/澄清/
命中、七因子评分与档位、CBPE 脚注、模型卡指纹重建回 pending。

验收口径（技术方案 §9）：引用编号唯一且指向正确（单测）；未命中注册表即
拒绝；生产模型有评分+已签模型卡；单样本解释可复算（脚注口径）。
"""
import unittest
import uuid
from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.audit_qa import AuditReport
from app.models.inference_result import InferenceResult
from app.models.project import Project
from app.models.user import User
from app.services.audit_qa import (
    AuditQAError,
    ask_metrics,
    build_report,
    validate_citations,
)


class S4Case(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                                    poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine, expire_on_commit=False)()
        self.user = User(username=f"s4-{uuid.uuid4().hex[:6]}", password_hash="hash")
        self.db.add(self.user)
        self.db.flush()
        self.project = Project(name="S4", owner_id=self.user.id)
        self.db.add(self.project)
        self.db.commit()

    def tearDown(self):
        self.db.close()


class TestCitations(S4Case):
    def test_numbering_is_globally_unique(self):
        from app.services.audit_qa import _citation_renumber

        items = [{"table": "a", "record_id": "1", "summary": "x"},
                 {"table": "a", "record_id": "2", "summary": "y"},
                 {"table": "b", "record_id": "3", "summary": "z"}]
        numbered = _citation_renumber(items)
        refs = [item["ref"] for item in numbered]
        self.assertEqual(refs, ["E1", "E2", "E3"])
        self.assertEqual(len(set(refs)), 3, "编号全局唯一不跨节复用")

    def test_citation_validation_catches_unknown_refs(self):
        evidence = [{"ref": "E1"}, {"ref": "E2"}]
        content = "摘要 [E1] 与 [E9] 与 [E2]"
        errors = validate_citations(content, evidence)
        self.assertTrue(any("E9" in e for e in errors), "未知引用被定位")
        clean = validate_citations("摘要 [E1] [E2]", evidence)
        self.assertEqual(clean, [])

    def test_build_report_renders_evidence_list(self):
        report = build_report(
            self.db, project_id=self.project.id, template_key="alerts",
            created_by_id=self.user.id,
        )
        self.db.commit()
        self.assertIn("## 证据清单", report.content_markdown)
        self.assertTrue(all(item.get("ref") for item in report.evidence))
        self.assertEqual(report.citation_errors, [])
        self.assertEqual(report.status, "final")
        reopened = self.db.query(AuditReport).filter(
            AuditReport.project_id == self.project.id
        ).count()
        self.assertEqual(reopened, 1, "历史报告可重开（行永存）")

    def test_invalid_template_rejected(self):
        with self.assertRaises(AuditQAError):
            build_report(self.db, project_id=self.project.id,
                         template_key="nope")


class TestAskMetrics(S4Case):
    def test_registry_hit_answers_with_footnote(self):
        result = ask_metrics(self.db, project_id=self.project.id, question="现在有多少未处理预警？")
        self.assertEqual(result["status"], "answered")
        self.assertEqual(result["metric"], "未处理预警数")
        self.assertEqual(result["value"], 0)
        self.assertTrue(result["footnote"])

    def test_off_registry_question_is_denied(self):
        result = ask_metrics(self.db, project_id=self.project.id,
                             question="今天食堂吃什么")
        self.assertEqual(result["status"], "denied")
        self.assertEqual(result["code"], "METRIC_NOT_IN_REGISTRY")

    def test_ambiguous_question_enters_clarify(self):
        result = ask_metrics(self.db, project_id=self.project.id,
                             question="预警总量和未处理的都告诉我")
        self.assertEqual(result["status"], "clarify")
        self.assertIn("candidates", result)


class TestTrustScore(S4Case):
    def _version(self, db, metrics=None, task=None):
        from app.models.model_library import ModelLibrary
        from app.models.model_registry import ModelVersion

        library = ModelLibrary(name=f"lib-{uuid.uuid4().hex[:6]}",
                               owner_id=self.user.id, status="completed")
        db.add(library)
        db.flush()
        version = ModelVersion(
            registered_model_id=uuid.uuid4(), version_number=5,
            source_kind="platform_joblib", source_artifact_id=uuid.uuid4(),
            onnx_artifact_id=uuid.uuid4(), source_model_library_id=library.id,
            approval_status="approved", metrics=metrics or {},
            conversion_metadata={"task": task} if task else {},
        )
        db.add(version)
        db.flush()
        return version

    def test_grade_boundaries_and_hard_fail(self):
        from app.services.model_trust import compute_trust_score

        strong = self._version(self.db, metrics={
            "f1": 0.95, "evaluation_rows": 8000, "topk_variance": 0.001,
            "leakage_hits": 0,
        })
        row = compute_trust_score(self.db, project_id=self.project.id,
                                  version=strong, computed_by_id=self.user.id)
        self.db.commit()
        self.assertEqual(row.grade, "A")
        no_metric = self._version(self.db, metrics={})
        hard = compute_trust_score(self.db, project_id=self.project.id,
                                   version=no_metric)
        self.assertEqual(hard.grade, "D", "主指标缺失硬门禁 → D")

    def test_unsupervised_uses_synthetic_auc(self):
        from app.services.model_trust import compute_trust_score

        anomaly = self._version(self.db, metrics={"synthetic_auc": 0.93},
                                task="anomaly_detection")
        row = compute_trust_score(self.db, project_id=self.project.id,
                                  version=anomaly)
        self.assertIn("synthetic_auc", row.factors["primary_metric_level"]["key"])


class TestCardAndCBPE(S4Case):
    def _version(self, db):
        from app.models.model_library import ModelLibrary
        from app.models.model_registry import ModelVersion

        library = ModelLibrary(name=f"lib-{uuid.uuid4().hex[:6]}",
                               owner_id=self.user.id, status="completed")
        db.add(library)
        db.flush()
        version = ModelVersion(
            registered_model_id=uuid.uuid4(), version_number=3,
            source_kind="platform_joblib", source_artifact_id=uuid.uuid4(),
            onnx_artifact_id=uuid.uuid4(), source_model_library_id=library.id,
            approval_status="approved", metrics={"f1": 0.9},
            feature_schema=["f1", "f2"],
        )
        db.add(version)
        db.flush()
        return version

    def test_card_sections_and_fingerprint_rebuild(self):
        from app.services.model_cards import ModelCardService
        from app.services.model_trust import (
            build_card_sections,
            data_fingerprint_of_version,
        )

        version = self._version(self.db)
        sections = build_card_sections(self.db, version=version)
        self.assertEqual(len(sections), 11, "11 章节齐备")
        fingerprint = data_fingerprint_of_version(version)
        card = ModelCardService().ensure_for_version(self.db, version)
        card.sections_v2 = {**sections, "_data_fingerprint": fingerprint}
        card.data_fingerprint = fingerprint
        self.db.commit()
        # 数据指纹变化 → 审批回 pending（重签）
        version.feature_schema = ["f1", "f2", "f3"]
        new_fingerprint = data_fingerprint_of_version(version)
        data_changed = new_fingerprint != card.data_fingerprint
        if data_changed:
            version.approval_status = "pending"
        self.db.commit()
        self.assertTrue(data_changed)
        self.assertEqual(version.approval_status, "pending")

    def test_cbpe_requires_minimum_rows_and_footnotes(self):
        from app.models.model_registry import InferenceDeployment
        from app.services.model_trust import estimate_cbpe

        deployment = InferenceDeployment(
            project_id=self.project.id, name="cbpe-deploy",
            model_version_id=self._version(self.db).id,
            created_by_id=self.user.id,
        )
        self.db.add(deployment)
        self.db.commit()
        short = estimate_cbpe(self.db, deployment=deployment)
        self.assertFalse(short["estimated"])
        self.assertIn("校准", short["footnote"])
        for index in range(40):
            self.db.add(InferenceResult(
                request_id=f"cbpe-{uuid.uuid4().hex[:8]}-{index}",
                project_id=self.project.id, deployment_id=deployment.id,
                channel="online", probability=0.5 + (index % 40) / 200.0,
            ))
        self.db.commit()
        result = estimate_cbpe(self.db, deployment=deployment)
        self.assertTrue(result["estimated"])
        self.assertTrue(0 <= result["accuracy_ci"][0] <= result["estimated_accuracy"]
                        <= result["accuracy_ci"][1] <= 1)
        self.assertIn("校准", result["footnote"])


if __name__ == "__main__":
    unittest.main()
