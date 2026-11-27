"""第三批 T1 闭环内聚件（B3-04/03/07/09/10）：NCR 三周期门禁、8D 顺序+D6 门禁、
案例自动开案与状态重推、追溯、知识检索。

验收口径（技术方案 §5 T1）：三周期未满关闭被拒；从预警转入自动带证据链；
跳步/D6 门禁被拒；预警→自动开案→关联全链。
"""
import unittest
import uuid

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.project import Project
from app.models.qms import (
    QmsCase,
    QmsCaseLink,
    QmsD8Report,
    QmsNcrCapa,
)
from app.models.quality_alerts import QualityAlert
from app.models.user import User
from app.services.qms_core import (
    QmsError,
    advance_d8,
    close_d8,
    create_d8,
    create_ncr,
    link_case_object,
    open_case,
    reject_ncr,
    repush_case_status,
    search_knowledge,
    transition_ncr,
)


class T1Case(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                                    poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine, expire_on_commit=False)()
        self.user = User(username=f"t1-{uuid.uuid4().hex[:6]}", password_hash="hash")
        self.db.add(self.user)
        self.db.flush()
        self.project = Project(name="T1", owner_id=self.user.id)
        self.db.add(self.project)
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def _ncr(self, code="NCR-001"):
        return create_ncr(self.db, project_id=self.project.id, code=code,
                          title="测试不合格", created_by_id=self.user.id)


class TestNcr(T1Case):
    def test_five_stage_order_and_reject(self):
        ncr = self._ncr()
        for expected in ("analysis", "action", "verification"):
            transition_ncr(self.db, ncr_id=ncr.id, actor_id=self.user.id)
            self.assertEqual(ncr.stage, expected)
        with self.assertRaises(QmsError) as caught:
            reject_ncr(self.db, ncr_id=ncr.id, actor_id=self.user.id, reason="太晚")
        self.assertEqual(caught.exception.code, "NCR_REJECT_STAGE_INVALID")
        db = self.db
        fresh = create_ncr(db, project_id=self.project.id, code="NCR-R",
                           title="驳回样例", created_by_id=self.user.id)
        with self.assertRaises(QmsError) as caught:
            reject_ncr(db, ncr_id=fresh.id, actor_id=self.user.id, reason="  ")
        self.assertEqual(caught.exception.code, "NCR_REJECT_REASON_REQUIRED")
        rejected = reject_ncr(db, ncr_id=fresh.id, actor_id=self.user.id, reason="误报不成立")
        self.assertEqual(rejected.stage, "rejected")

    def test_three_cycle_close_gate(self):
        """〔三批复审重构〕时间窗语义：验证期须满 21 天方可关闭。

        旧语义（调用计数 +1）在 HTTP 路径上被 project_action 的回滚撤销——
        经 HTTP 永远关不掉（运行验证坐实）；新判定只读时间与预警，被拦请求
        回滚无害，且「点三次」无法绕过时间要求。
        """
        from datetime import timedelta

        ncr = self._ncr()
        for _ in range(3):
            transition_ncr(self.db, ncr_id=ncr.id, actor_id=self.user.id)
        self.assertEqual(ncr.stage, "verification")
        # 刚进入 verification（0 天）：关闭被拒
        with self.assertRaises(QmsError) as caught:
            transition_ncr(self.db, ncr_id=ncr.id, actor_id=self.user.id)
        self.assertEqual(caught.exception.code, "NCR_CLOSE_BLOCKED")
        self.assertEqual(ncr.stage, "verification")
        # 反复点击不能「攒次数」：仍 BLOCKED
        for _ in range(3):
            with self.assertRaises(QmsError):
                transition_ncr(self.db, ncr_id=ncr.id, actor_id=self.user.id)
        self.assertEqual(ncr.stage, "verification")
        # 把验证起点回拨 22 天（≥3×7 天）且验证期内无新预警 → 关闭成功
        from app.models.qms import QmsNcrAction

        started = self.db.query(QmsNcrAction).filter(
            QmsNcrAction.ncr_id == ncr.id, QmsNcrAction.phase == "verification",
        ).order_by(QmsNcrAction.created_at.asc()).first()
        started.created_at = started.created_at - timedelta(days=22)
        self.db.commit()
        transition_ncr(self.db, ncr_id=ncr.id, actor_id=self.user.id)
        self.db.commit()
        self.db.expire_all()
        fresh = self.db.get(type(ncr), ncr.id)
        self.assertEqual(fresh.stage, "closed")
        self.assertEqual(fresh.verification_cycles, 3)

    def test_recurrence_during_verification_blocks_close(self):
        """验证期内（起点之后）出现新预警 → 判复发、关闭被拒。

        旧实现的窗口是「近 7 天」——进入 verification **之前**的旧预警也会
        被判复发；新语义以验证期起点为窗口起点。
        """
        from datetime import timedelta

        from app.models.qms import QmsNcrAction

        ncr = create_ncr(self.db, project_id=self.project.id, code="NCR-REC",
                         title="复发样例", created_by_id=self.user.id)
        for _ in range(3):
            transition_ncr(self.db, ncr_id=ncr.id, actor_id=self.user.id)
        # 验证起点回拨 22 天；在起点之后 1 天种一条新预警（同项目视为复发）
        started = self.db.query(QmsNcrAction).filter(
            QmsNcrAction.ncr_id == ncr.id, QmsNcrAction.phase == "verification",
        ).order_by(QmsNcrAction.created_at.asc()).first()
        started.created_at = started.created_at - timedelta(days=22)
        from datetime import datetime

        self.db.add(QualityAlert(
            project_id=self.project.id, source_type="model_risk",
            severity="warning", title="验证期复发", evidence={}, merge_key="rec-x",
            created_at=datetime.utcnow() - timedelta(days=21),
        ))
        self.db.commit()
        with self.assertRaises(QmsError) as caught:
            transition_ncr(self.db, ncr_id=ncr.id, actor_id=self.user.id)
        self.assertEqual(caught.exception.code, "NCR_CLOSE_BLOCKED")
        self.assertEqual(ncr.stage, "verification")
        # 对照：起点之前的预警不判复发（旧实现会）——清掉验证期预警后关闭成功
        self.db.query(QualityAlert).filter(
            QualityAlert.title == "验证期复发").delete()
        self.db.commit()
        transition_ncr(self.db, ncr_id=ncr.id, actor_id=self.user.id)
        self.db.commit()
        self.db.expire_all()
        fresh = self.db.get(type(ncr), ncr.id)
        self.assertEqual(fresh.stage, "closed")


class TestD8(T1Case):
    def test_step_order_and_d6_gate(self):
        d8 = create_d8(self.db, project_id=self.project.id, code="8D-001",
                       title="测试 8D", created_by_id=self.user.id)
        # 跳到结案：步序门禁
        with self.assertRaises(QmsError) as caught:
            close_d8(self.db, d8_id=d8.id, actor_id=self.user.id)
        self.assertEqual(caught.exception.code, "D8_STEP_ORDER_ENFORCED")
        for _ in range(9):
            advance_d8(self.db, d8_id=d8.id, actor_id=self.user.id)
        self.assertEqual(d8.current_step, 9)
        # D6 未通过 → 结案被拒
        with self.assertRaises(QmsError) as caught:
            close_d8(self.db, d8_id=d8.id, actor_id=self.user.id)
        self.assertEqual(caught.exception.code, "D6_GATE_NOT_PASSED")
        # D6 通过后可结案：重走 D6 登记步（步序回到 8 → 推进到 9 → 关闭）
        d8.current_step = 8
        advance_d8(self.db, d8_id=d8.id, actor_id=self.user.id, d6_passed=True)
        close_d8(self.db, d8_id=d8.id, actor_id=self.user.id)
        self.assertIsNotNone(d8.closed_at)

    def test_draft_fallback_when_gateway_down(self):
        d8 = create_d8(self.db, project_id=self.project.id, code="8D-002",
                       title="草稿样例", created_by_id=self.user.id)
        result = __import__("app.services.qms_core", fromlist=["draft_d8_with_llm"]).draft_d8_with_llm(
            self.db, d8_id=d8.id, context="点焊飞溅",
        )
        self.assertEqual(result["drafted"], True)


class TestCases(T1Case):
    def test_auto_open_from_alert_and_repush(self):
        alert = QualityAlert(
            project_id=self.project.id, source_type="model_risk",
            severity="critical", title="严重预警", evidence={}, merge_key="x",
        )
        self.db.add(alert)
        self.db.commit()
        case = open_case(self.db, project_id=self.project.id, code="CASE-001",
                         title="自动开案", severity="critical",
                         source_alert_id=alert.id, created_by_id=self.user.id)
        links = self.db.query(QmsCaseLink).filter_by(case_id=case.id).all()
        self.assertEqual(len(links), 1, "预警自动关联")
        ncr = create_ncr(self.db, project_id=self.project.id, code="NCR-C1",
                         title="案例 NCR", created_by_id=self.user.id)
        link_case_object(self.db, case_id=case.id, object_type="ncr_capa",
                         object_id=str(ncr.id))
        repush_case_status(self.db, case_id=case.id)
        self.assertEqual(case.status, "monitoring", "NCR 未关闭 → monitoring")
        ncr.stage = "closed"
        repush_case_status(self.db, case_id=case.id)
        self.assertEqual(case.status, "closed", "NCR 关闭 → 案例关闭候选")


class TestKnowledgeTrace(T1Case):
    def test_knowledge_filter_and_symptom_search(self):
        from app.models.qms import QmsKnowledgeEntry

        self.db.add(QmsKnowledgeEntry(
            project_id=self.project.id, defect_code="D-100",
            symptom="飞溅严重伴电极粘连", root_cause="电极压力不足",
        ))
        self.db.add(QmsKnowledgeEntry(
            project_id=self.project.id, defect_code="D-200",
            symptom="虚焊强度低", root_cause="电流偏低",
        ))
        self.db.commit()
        rows = search_knowledge(self.db, project_id=self.project.id,
                                keyword="飞溅")
        self.assertEqual(len(rows), 1)
        results = __import__("app.services.qms_core", fromlist=["search_by_symptom"]).search_by_symptom(
            self.db, project_id=self.project.id, symptom="飞溅 粘连",
        )
        self.assertEqual(results[0]["entry"].defect_code, "D-100")

    def test_trace_sample_aggregates_objects(self):
        result = __import__("app.services.qms_core", fromlist=["trace_sample"]).trace_sample(
            self.db, project_id=self.project.id, sample_key="sk-none",
        )
        self.assertEqual(result["sample_key"], "sk-none")
        self.assertEqual(result["inference_results"], [])


if __name__ == "__main__":
    unittest.main()
