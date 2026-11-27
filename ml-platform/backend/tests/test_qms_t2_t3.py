"""第三批 T2+T3（B3-08/06/01/02/05）：报告同源幂等、控制计划双生效+diff+乘数
决策流水、%GRR 手算向量、RPN 服务端计算、IQC 约束+SCAR 唯一。

验收口径（技术方案 §5 T2/T3）。
"""
import unittest
import uuid
from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.project import Project
from app.models.qms import (
    QmsControlPlan,
    QmsFmea,
    QmsIqcRecord,
    QmsQualityReport,
    QmsScar,
    QmsSupplier,
)
from app.models.user import User
from app.services.qms_tools import (
    QmsToolsError,
    compute_grr,
    create_or_replace_plan,
    disable_supplier,
    evaluate_tightening,
    generate_report,
    normalize_fmea_items,
    plan_version_diff,
    record_iqc,
    scheduled_due_reports,
    sync_fmea_to_control_plan,
)


class T23Case(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                                    poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine, expire_on_commit=False)()
        self.user = User(username=f"t23-{uuid.uuid4().hex[:6]}", password_hash="hash")
        self.db.add(self.user)
        self.db.flush()
        self.project = Project(name="T23", owner_id=self.user.id)
        self.db.add(self.project)
        self.db.commit()

    def tearDown(self):
        self.db.close()


class TestReports(T23Case):
    def test_report_is_idempotent_per_scope(self):
        first = generate_report(self.db, project_id=self.project.id,
                                period="daily", period_key="20261126")
        second = generate_report(self.db, project_id=self.project.id,
                                 period="daily", period_key="20261126")
        self.assertEqual(first.id, second.id, "同窗口幂等（唯一键语义）")

    def test_report_content_has_same_source_numbers(self):
        from app.models.quality_alerts import QualityAlert

        for index in range(3):
            self.db.add(QualityAlert(
                project_id=self.project.id, source_type="model_risk",
                severity="warning", title=f"r{index}", evidence={}, merge_key="x",
            ))
        self.db.commit()
        # 周期窗口取数：键必须取当前 UTC 日期（夹具 created_at=now，落进当日窗口）
        today_key = datetime.utcnow().strftime("%Y%m%d")
        report = generate_report(self.db, project_id=self.project.id,
                                 period="daily", period_key=today_key)
        self.assertEqual(report.content["alert_total"], 3, "同库同源")
        self.assertEqual(report.content["window"][0], f"{today_key[:4]}-{today_key[4:6]}-{today_key[6:]}T00:00:00")
        self.assertIn("同源", report.content["footnote"])

    def test_report_period_key_invalid_rejected(self):
        with self.assertRaises(QmsToolsError) as caught:
            generate_report(self.db, project_id=self.project.id,
                            period="daily", period_key="not-a-key")
        self.assertEqual(caught.exception.code, "REPORT_PERIOD_KEY_INVALID")
        with self.assertRaises(QmsToolsError):
            generate_report(self.db, project_id=self.project.id,
                            period="weekly", period_key="2026-W47")


class TestReportScheduler(T23Case):
    def test_scheduler_generates_due_periods_idempotent(self):
        from app.models.quality_alerts import QualityAlert

        empty_project = Project(name="T23-EMPTY", owner_id=self.user.id)
        self.db.add(empty_project)
        self.db.add(QualityAlert(
            project_id=self.project.id, source_type="model_risk",
            severity="warning", title="sched", evidence={}, merge_key="sched-x",
        ))
        self.db.commit()
        reference = datetime(2026, 11, 27, 8, 30, 0)
        first = scheduled_due_reports(self.db, now=reference)
        # 无质量活动的项目不出空报告；三类周期键为上一已完结周期
        self.assertEqual(first["projects"], 1)
        self.assertEqual(first["periods"]["daily"], "20261126")
        self.assertEqual(first["periods"]["weekly"], "2026W47")
        self.assertEqual(first["periods"]["monthly"], "202610")
        self.assertEqual(first["created"], 3)
        rows = self.db.query(QmsQualityReport).filter(
            QmsQualityReport.generated_by == "scheduler"
        ).all()
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(r.project_id == self.project.id for r in rows))
        # 重复巡检：唯一键幂等，不重复出报告
        second = scheduled_due_reports(self.db, now=reference)
        self.assertEqual(second["created"], 0)


class TestControlPlan(T23Case):
    def test_dual_active_rejected_and_versioning(self):
        plan1 = create_or_replace_plan(self.db, project_id=self.project.id,
                                       code="CP-1", quality_points=[{"name": "点A"}])
        with self.assertRaises(QmsToolsError) as caught:
            create_or_replace_plan(self.db, project_id=self.project.id,
                                   code="CP-2", quality_points=[])
        self.assertEqual(caught.exception.code, "QMS_PLAN_DUAL_ACTIVE")
        plan1.status = "archived"
        plan2 = create_or_replace_plan(self.db, project_id=self.project.id,
                                       code="CP-2",
                                       quality_points=[{"name": "点A", "sample": 5}])
        self.assertEqual(plan2.version, 2)

    def test_tightening_decision_log_is_replayable(self):
        plan = create_or_replace_plan(self.db, project_id=self.project.id,
                                      code="CP-3", quality_points=[])
        decision = evaluate_tightening(self.db, plan=plan)
        self.assertGreaterEqual(decision["suggested_multiplier"], 1.0)
        replay = sum(
            item["contribution"] for item in decision["factors"].values()
        ) + 1.0
        self.assertAlmostEqual(decision["suggested_multiplier"],
                               round(min(replay, 3.0), 2), msg="决策流水可复算")

    def test_version_diff_lists_changes(self):
        plan1 = create_or_replace_plan(self.db, project_id=self.project.id,
                                       code="CP-4",
                                       quality_points=[{"name": "点A", "sample": 3}])
        plan1.status = "archived"
        plan2 = create_or_replace_plan(self.db, project_id=self.project.id,
                                       code="CP-4",
                                       quality_points=[{"name": "点A", "sample": 8}])
        diff = plan_version_diff(self.db, plan_id=plan2.id)
        self.assertEqual(diff["from_version"], 1)
        self.assertEqual(len(diff["quality_point_changes"]), 1)
        self.assertEqual(diff["quality_point_changes"][0]["after"]["sample"], 8)


class TestMsa(T23Case):
    def test_grr_grade_boundaries(self):
        good = compute_grr({"tolerance": 10.0, "readings": [
            [[10.0, 10.05], [20.0, 20.05]],
            [[10.02, 10.07], [20.02, 20.07]],
        ]})
        self.assertEqual(good["grade"], "acceptable")
        self.assertLess(good["grr_percent"], 10)
        bad = compute_grr({"tolerance": 1.0, "readings": [
            [[10.0, 12.0], [20.0, 22.0]],
            [[10.5, 12.5], [20.5, 22.5]],
        ]})
        self.assertEqual(bad["grade"], "unacceptable")
        self.assertGreater(bad["grr_percent"], 30)

    def test_ndc_formula(self):
        result = compute_grr({"tolerance": 10.0, "readings": [
            [[10.0, 10.1], [20.0, 20.1]],
            [[10.03, 10.13], [20.03, 20.13]],
        ]})
        self.assertIsInstance(result["ndc"], int)
        self.assertGreater(result["ndc"], 0)


class TestFmea(T23Case):
    def test_rpn_computed_server_side_with_clamp(self):
        items = normalize_fmea_items([
            {"failure_mode": "a", "severity": 99, "occurrence": 2, "detection": 3},
            {"failure_mode": "b", "severity": 0, "occurrence": -2, "detection": 5},
        ])
        self.assertEqual(items[0]["severity"], 10)
        self.assertEqual(items[0]["rpn"], 10 * 2 * 3)
        self.assertEqual(items[1]["severity"], 1)
        self.assertEqual(items[1]["occurrence"], 1)

    def test_sync_creates_recipe_change_approval(self):
        from app.services.approvals import decide_approval
        from app.services.qms_core import create_ncr

        plan = create_or_replace_plan(self.db, project_id=self.project.id,
                                      code="CP-5", quality_points=[])
        fmea = QmsFmea(project_id=self.project.id, name="FMEA-1",
                       items=normalize_fmea_items([
                           {"failure_mode": "高风险", "severity": 9,
                            "occurrence": 6, "detection": 5},
                       ]))
        self.db.add(fmea)
        self.db.commit()
        result = sync_fmea_to_control_plan(self.db, fmea_id=fmea.id,
                                           plan_id=plan.id, actor_id=self.user.id)
        self.assertEqual(result["high_rpn_items"], 1)
        # recipe_change 审批单已进 S1 队列（保留类型，批准诚实降级）
        from app.models.approvals import ApprovalRequest

        approvals = self.db.query(ApprovalRequest).filter(
            ApprovalRequest.type == "recipe_change"
        ).all()
        self.assertEqual(len(approvals), 1)


class TestIqc(T23Case):
    def _supplier(self):
        supplier = QmsSupplier(project_id=self.project.id, code="SUP-1",
                               name="供应商A")
        self.db.add(supplier)
        self.db.commit()
        return supplier

    def test_count_constraint_three_branches(self):
        supplier = self._supplier()
        ok = record_iqc(self.db, project_id=self.project.id,
                        supplier_id=supplier.id, arrival_count=100,
                        inspected_count=50, defect_count=5)
        self.assertIsNotNone(ok.id)
        with self.assertRaises(QmsToolsError) as caught:
            record_iqc(self.db, project_id=self.project.id,
                       supplier_id=supplier.id, arrival_count=10,
                       inspected_count=20, defect_count=1)
        self.assertEqual(caught.exception.code, "IQC_COUNT_CONSTRAINT")
        with self.assertRaises(QmsToolsError):
            record_iqc(self.db, project_id=self.project.id,
                       supplier_id=supplier.id, arrival_count=10,
                       inspected_count=10, defect_count=11)

    def test_one_iqc_one_scar_uniqueness(self):
        supplier = self._supplier()
        record = record_iqc(self.db, project_id=self.project.id,
                            supplier_id=supplier.id, arrival_count=10,
                            inspected_count=10, defect_count=2)
        self.db.commit()
        self.assertIsNotNone(record.scar_id)
        scars = self.db.query(QmsScar).filter(
            QmsScar.iqc_record_id == record.id
        ).count()
        self.assertEqual(scars, 1, "一检验一 SCAR")
        record2 = record_iqc(self.db, project_id=self.project.id,
                             supplier_id=supplier.id, arrival_count=10,
                             inspected_count=10, defect_count=3)
        self.assertNotEqual(record2.id, record.id)
        self.assertIsNotNone(record2.scar_id, "新检验不合格 → 新 SCAR")

    def test_disabled_supplier_rejects_new_records(self):
        supplier = self._supplier()
        disable_supplier(self.db, supplier_id=supplier.id)
        with self.assertRaises(QmsToolsError) as caught:
            record_iqc(self.db, project_id=self.project.id,
                       supplier_id=supplier.id, arrival_count=10,
                       inspected_count=10, defect_count=0)
        self.assertEqual(caught.exception.code, "SUPPLIER_DISABLED")


if __name__ == "__main__":
    unittest.main()
