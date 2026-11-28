"""第三轮复审修复（2026-11-28，基于 wave1 5dc6baea 的核验结论）回归测试。

覆盖：
- recipe_change FMEA 形态经 **HTTP** 批准全链（wave1 曾把旧 U1 用例掏空成
  零断言——批准路径零覆盖；执行链 perform_approved 只在 API 层被调）
- 加严形态 HTTP 级：评估建单 → 批准 → 乘数写回 + **决策流水落库**（wave1
  E-1：加严分支曾漏回写 decision_log，「批准」这条流水永不落库）
- 归档计划 tightening-evaluation → 409（曾无 ApprovalError 映射直接 500）
- 同计划幂等去重（两次评估只一张待批单）
- NCR 复发判定排除误报/演示预警（E-2：曾一条误报即永久 NCR_CLOSE_BLOCKED）
- 盲测台账幂等记账（S2b #16：探测+正式双跑双重记账，默认 cap=2 必 failed）
- S4 端点跨项目 IDOR 回归（_version_or_404 曾不校验归属）
- 模型卡「预期用途/局限/运维指引」从 ModelCard 读（曾读不存在的属性恒未提供）
- 控制计划生效抽样量（乘数执行层消费方）
- 审计报告详情/导出端点；问数指标注册表 PlatformOption 接线
- 审计叙述 LLM 主路径（purpose=audit_report + actor 传参）
"""
import unittest
import uuid
from datetime import datetime, timedelta

from app.models.qms import QmsControlPlan, QmsNcrAction
from app.services.qms_core import QmsError, create_ncr, transition_ncr
from tests.quality_alert_fixtures import QualityAlertApiCase


class Wave2FixCase(QualityAlertApiCase):
    """共用夹具：TestClient + 直连同一内存库（quality_alert_fixtures）。"""

    def _plan(self, multiplier=1.0, points=None, status="active"):
        plan = QmsControlPlan(
            project_id=self.project.id,
            code=f"PL-{self.case_key}-{uuid.uuid4().hex[:4]}",
            version=1, status=status,
            quality_points=points if points is not None else [],
            tightening_multiplier=multiplier,
            decision_log=[], created_by_id=self.owner.id,
        )
        self.db.add(plan)
        self.db.commit()
        return plan

    def _make_version_with_deployment(self, project_id, metrics=None):
        """造「版本 + 本项目部署」对（IDOR 回归需要跨项目对照）。"""
        from app.models.model_library import ModelLibrary
        from app.models.model_registry import InferenceDeployment, ModelVersion

        library = ModelLibrary(name=f"lib-{uuid.uuid4().hex[:6]}",
                               owner_id=self.owner.id, status="completed")
        self.db.add(library)
        self.db.flush()
        version = ModelVersion(
            registered_model_id=uuid.uuid4(), version_number=1,
            source_kind="platform_joblib", source_artifact_id=uuid.uuid4(),
            onnx_artifact_id=uuid.uuid4(), source_model_library_id=library.id,
            approval_status="approved", metrics=metrics or {"f1": 0.9},
            feature_schema=["f1", "f2"], conversion_metadata={},
        )
        self.db.add(version)
        self.db.flush()
        deployment = InferenceDeployment(
            project_id=project_id, name=f"dep-{uuid.uuid4().hex[:6]}",
            model_version_id=version.id, created_by_id=self.owner.id,
        )
        self.db.add(deployment)
        self.db.commit()
        return version, deployment


class TestRecipeChangeHttpApproval(Wave2FixCase):
    def test_fmea_sync_approve_via_http_applies_quality_points(self):
        """U1 重建（第三轮复审）：FMEA 高 RPN 同步 → 审批单 → 经 HTTP 四眼
        批准 → 质量点落地 + 决策流水。旧 U1 用例在执行器注册后被掏空成
        零断言，recipe_change 的 HTTP 批准路径自此零覆盖。"""
        base = f"/api/projects/{self.project.id}"
        self.act_as(self.owner)
        plan = self._plan()
        fmea_id = self.client.post(f"{base}/qms/fmeas", json={
            "name": f"F-{self.case_key}",
            "items": [{"failure_mode": "虚焊", "severity": 9,
                       "occurrence": 6, "detection": 5}],
        }).json()["id"]
        sync = self.client.post(
            f"{base}/qms/fmeas/{fmea_id}/sync-control-plan?plan_id={plan.id}")
        self.assertEqual(sync.status_code, 200, sync.text)
        from app.models.access import ProjectMember
        from app.models.approvals import ApprovalRequest
        from sqlalchemy import update

        approval = self.db.query(ApprovalRequest).filter(
            ApprovalRequest.type == "recipe_change",
            ApprovalRequest.status == "pending",
        ).order_by(ApprovalRequest.created_at.desc()).first()
        self.assertIsNotNone(approval)
        # 四眼：发起人是 owner，批准人须为持 approval.approve 的他人——
        # operator 升 editor
        self.db.execute(update(ProjectMember)
                        .where(ProjectMember.project_id == self.project.id,
                               ProjectMember.user_id == self.operator.id)
                        .values(role="editor"))
        self.db.commit()
        self.act_as(self.operator)
        decide = self.client.post(
            f"/api/projects/{self.project.id}/approvals/{approval.id}/approve",
            json={"note": "高 RPN 项纳入控制"},
        )
        self.assertEqual(decide.status_code, 200, decide.text)
        self.db.expire_all()
        fresh = self.db.get(QmsControlPlan, plan.id)
        names = [p.get("name") for p in (fresh.quality_points or [])]
        self.assertIn("虚焊", names, "批准后高 RPN 项应并入质量点")
        sources = [row.get("source") for row in (fresh.decision_log or [])]
        self.assertIn("fmea_approval", sources)

    def test_tightening_evaluate_approve_via_http_multiplier_and_log(self):
        """加严形态 HTTP 级：评估建单 → 批准 → 乘数写回 + 决策流水回写
        （wave1 E-1：加严分支曾 append 到局部变量未回写）。"""
        from app.services.qms_tools import evaluate_tightening

        base = f"/api/projects/{self.project.id}"
        self.act_as(self.owner)
        plan = self._plan()
        # 10 条 open 预警 → alerts 因子贡献 → 建议乘数 > 1.0 → 建单
        now = datetime.utcnow()
        for index in range(10):
            self.make_alert(title=f"加严-{self.case_key}-{index}",
                            merge_key=f"tighten-{self.case_key}-{index}",
                            created_at=now - timedelta(hours=2))
        decision = evaluate_tightening(self.db, plan=plan, actor_id=self.owner.id)
        self.db.commit()
        self.assertGreater(decision["suggested_multiplier"], 1.0)
        approval_id = decision.get("approval_id")
        self.assertIsNotNone(approval_id)
        # 四眼：发起 owner，批准换已升 editor 的 operator
        from app.models.access import ProjectMember
        from sqlalchemy import update

        self.db.execute(update(ProjectMember)
                        .where(ProjectMember.project_id == self.project.id,
                               ProjectMember.user_id == self.operator.id)
                        .values(role="editor"))
        self.db.commit()
        self.act_as(self.operator)
        decide = self.client.post(
            f"{base}/approvals/{approval_id}/approve",
            json={"note": "同意加严"},
        )
        self.assertEqual(decide.status_code, 200, decide.text)
        self.db.expire_all()
        fresh = self.db.get(QmsControlPlan, plan.id)
        self.assertEqual(fresh.tightening_multiplier, decision["suggested_multiplier"])
        sources = [row.get("source") for row in (fresh.decision_log or [])]
        self.assertIn("tightening_approval", sources,
                      "批准决策流水必须落库（E-1 回写）")

    def test_archived_plan_tightening_returns_409(self):
        """归档计划不再评估加严：409 QMS_PLAN_NOT_ACTIVE（曾 500）。"""
        self.act_as(self.owner)
        plan = self._plan(status="archived")
        response = self.client.post(
            f"/api/projects/{self.project.id}/qms/control-plans/{plan.id}/tightening-evaluation")
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()["detail"]["code"], "QMS_PLAN_NOT_ACTIVE")

    def test_tightening_idempotent_single_pending_approval(self):
        """同计划待批单去重：两次评估只一张 recipe_change 审批单。"""
        from app.models.approvals import ApprovalRequest
        from app.services.qms_tools import evaluate_tightening

        plan = self._plan()
        now = datetime.utcnow()
        for index in range(10):
            self.make_alert(title=f"幂等-{self.case_key}-{index}",
                            merge_key=f"idem-{self.case_key}-{index}",
                            created_at=now - timedelta(hours=2))
        first = evaluate_tightening(self.db, plan=plan, actor_id=self.owner.id)
        second = evaluate_tightening(self.db, plan=plan, actor_id=self.owner.id)
        self.db.commit()
        self.assertIsNotNone(first.get("approval_id"))
        self.assertIsNone(second.get("approval_id"),
                          "同计划已有待批单时第二次评估不得重复建单")
        # 类内用例共享内存库：按 payload.plan_id 过滤出本计划的待批单
        pending_for_plan = [
            row for row in self.db.query(ApprovalRequest).filter(
                ApprovalRequest.type == "recipe_change",
                ApprovalRequest.status == "pending",
                ApprovalRequest.project_id == self.project.id,
            ).all()
            if (row.payload or {}).get("plan_id") == str(plan.id)
        ]
        self.assertEqual(len(pending_for_plan), 1, "该计划只应有一张待批单")
        self.assertEqual(str(pending_for_plan[0].id), first["approval_id"])


class TestNcrRecurrenceFilters(Wave2FixCase):
    def _ncr_in_verification(self, code_suffix):
        now = datetime.utcnow()
        alert = self.make_alert(title=f"溯源-{code_suffix}",
                                merge_key=f"ncr-src-{code_suffix}",
                                created_at=now - timedelta(days=30))
        ncr = create_ncr(self.db, project_id=self.project.id,
                         code=f"NCR-{code_suffix}", title="复发过滤",
                         source_alert_id=alert.id, created_by_id=self.owner.id)
        for _ in range(3):
            transition_ncr(self.db, ncr_id=ncr.id, actor_id=self.owner.id)
        started = self.db.query(QmsNcrAction).filter(
            QmsNcrAction.ncr_id == ncr.id, QmsNcrAction.phase == "verification",
        ).order_by(QmsNcrAction.created_at.asc()).first()
        started.created_at = started.created_at - timedelta(days=22)
        self.db.commit()
        return ncr

    def test_false_positive_alert_does_not_block_close(self):
        """E-2：验证期内**已判定误报**的预警不算复发——曾让 NCR 永久
        NCR_CLOSE_BLOCKED 且生产无解锁手段。"""
        ncr = self._ncr_in_verification(f"fp-{self.case_key}")
        from app.models.quality_alerts import QualityAlert

        self.db.add(QualityAlert(
            project_id=self.project.id, scene_id=self.scene.id,
            station_id=self.station.id, source_type="model_risk",
            severity="warning", title=f"误报-{self.case_key}",
            evidence={}, merge_key=f"fp-alert-{self.case_key}",
            status="closed", resolution="false_positive",
            created_at=datetime.utcnow() - timedelta(days=5),
        ))
        self.db.commit()
        transition_ncr(self.db, ncr_id=ncr.id, actor_id=self.owner.id)
        self.db.commit()
        self.db.expire_all()
        self.assertEqual(self.db.get(type(ncr), ncr.id).stage, "closed")

    def test_real_alert_still_blocks_close(self):
        """对照：验证期内的真实（非误报）预警仍拦关闭——过滤不放松门禁。"""
        ncr = self._ncr_in_verification(f"real-{self.case_key}")
        from app.models.quality_alerts import QualityAlert

        self.db.add(QualityAlert(
            project_id=self.project.id, scene_id=self.scene.id,
            station_id=self.station.id, source_type="model_risk",
            severity="warning", title=f"真实-{self.case_key}",
            evidence={}, merge_key=f"real-alert-{self.case_key}",
            status="open", resolution=None,
            created_at=datetime.utcnow() - timedelta(days=5),
        ))
        self.db.commit()
        with self.assertRaises(QmsError) as caught:
            transition_ncr(self.db, ncr_id=ncr.id, actor_id=self.owner.id)
        self.assertEqual(caught.exception.code, "NCR_CLOSE_BLOCKED")

    def test_demo_alert_does_not_block_close(self):
        """演示预警不入真实复发判定（§6-9 隔离口径在门禁上的延续）。"""
        ncr = self._ncr_in_verification(f"demo-{self.case_key}")
        from app.models.quality_alerts import QualityAlert

        self.db.add(QualityAlert(
            project_id=self.project.id, scene_id=self.scene.id,
            station_id=self.station.id, source_type="model_risk",
            severity="warning", title=f"演示-{self.case_key}",
            evidence={}, merge_key=f"demo-alert-{self.case_key}",
            status="open", is_demo=True,
            created_at=datetime.utcnow() - timedelta(days=5),
        ))
        self.db.commit()
        transition_ncr(self.db, ncr_id=ncr.id, actor_id=self.owner.id)
        self.db.commit()
        self.db.expire_all()
        self.assertEqual(self.db.get(type(ncr), ncr.id).stage, "closed")


class TestBlindLedgerIdempotent(Wave2FixCase):
    def test_same_fingerprint_and_purpose_records_once(self):
        """S2b #16：同轮次+同样本指纹+同用途重复记账返回既有行、不耗 cap——
        探测评估与端点正式评估双跑曾双重记账，默认 cap=2 必 blind_eval_cap_reached。"""
        from app.models.dataset_splitting import BlindTestUsage, ModelingRound

        round_row = ModelingRound(
            project_id=self.project.id, dataset_version_id=uuid.uuid4(),
            split_id=uuid.uuid4(), status="locked", blind_eval_cap=2,
            blind_eval_count=0,
        )
        self.db.add(round_row)
        self.db.commit()
        from app.services.modeling_rounds import record_blind_evaluation

        fingerprint = f"fp-{uuid.uuid4().hex}"
        first = record_blind_evaluation(
            self.db, round_id=round_row.id, purpose="no_regression_check",
            used_by_id=None, sample_count=100, samples_fingerprint=fingerprint)
        second = record_blind_evaluation(
            self.db, round_id=round_row.id, purpose="no_regression_check",
            used_by_id=None, sample_count=100, samples_fingerprint=fingerprint)
        self.db.commit()
        self.assertEqual(first.id, second.id, "重复评估应返回既有台账行")
        self.db.expire_all()
        fresh = self.db.get(ModelingRound, round_row.id)
        self.assertEqual(fresh.blind_eval_count, 1, "重复评估不消耗 cap")
        rows = self.db.query(BlindTestUsage).filter(
            BlindTestUsage.round_id == round_row.id).all()
        self.assertEqual(len(rows), 1)
        # 不同用途仍各自记账（cap 语义不受影响）
        record_blind_evaluation(
            self.db, round_id=round_row.id, purpose="release_final_validation",
            used_by_id=None, sample_count=100, samples_fingerprint=fingerprint)
        self.db.expire_all()
        self.assertEqual(self.db.get(ModelingRound, round_row.id).blind_eval_count, 2)


class TestS4CrossProjectIsolation(Wave2FixCase):
    def _other_project_setup(self):
        from app.models.project import Project

        other = Project(name=f"其他项目-{self.case_key}", owner_id=self.owner.id)
        self.db.add(other)
        self.db.commit()
        version, deployment = self._make_version_with_deployment(other.id)
        return other, version, deployment

    def test_trust_score_rejects_version_outside_project(self):
        """S4 IDOR 回归：对项目有权限 ≠ 可读任意版本——未部署于本项目的
        版本一律 404（曾可跨项目打可信度，落行还记路径 pid）。"""
        self.act_as(self.owner)
        other, version, _deployment = self._other_project_setup()
        response = self.client.get(
            f"/api/projects/{self.project.id}/model-versions/{version.id}/trust-score")
        self.assertEqual(response.status_code, 404, response.text)
        self.assertEqual(response.json()["detail"]["code"], "MODEL_VERSION_NOT_FOUND")
        # 本项目部署的版本正常
        mine_version, _mine_dep = self._make_version_with_deployment(self.project.id)
        ok = self.client.get(
            f"/api/projects/{self.project.id}/model-versions/{mine_version.id}/trust-score")
        self.assertEqual(ok.status_code, 200, ok.text)

    def test_cbpe_rejects_deployment_of_other_project(self):
        """CBPE 曾忽略路径 version_id、不校验 deployment 归属——跨项目部署
        可被估 CBPE。现显式传入他项目部署 → 404。"""
        self.act_as(self.owner)
        other, version, deployment = self._other_project_setup()
        response = self.client.get(
            f"/api/projects/{self.project.id}/model-versions/{version.id}/cbpe-estimate",
            params={"deployment_id": str(deployment.id)})
        self.assertEqual(response.status_code, 404, response.text)

    def test_model_card_refresh_rejects_version_outside_project(self):
        """refresh 曾可把他项目模型卡打回 pending（跨项目写）。"""
        self.act_as(self.owner)
        other, version, _deployment = self._other_project_setup()
        response = self.client.post(
            f"/api/projects/{self.project.id}/model-versions/{version.id}/model-card/refresh")
        self.assertEqual(response.status_code, 404, response.text)


class TestModelCardSectionsReadFromCard(Wave2FixCase):
    def test_intended_use_reflects_card_content(self):
        """预期用途/局限/运维指引在 ModelCard 上——曾从 version 读不存在
        属性，永远「未提供」（代理口径 #35）。"""
        from app.services.model_cards import ModelCardService
        from app.services.model_trust import build_card_sections

        version, _deployment = self._make_version_with_deployment(self.project.id)
        card = ModelCardService().ensure_for_version(self.db, version)
        card.intended_use = "产线焊点质量分级（在线推理）"
        card.limitations = "仅适用单点焊场景，多工位泛化未验证"
        card.operational_guidance = "每周复核漂移看板"
        self.db.commit()
        sections = build_card_sections(self.db, version=version)
        self.assertEqual(sections["预期用途"], "产线焊点质量分级（在线推理）")
        self.assertEqual(sections["局限"], "仅适用单点焊场景，多工位泛化未验证")
        self.assertEqual(sections["运维指引"], "每周复核漂移看板")


class TestEffectiveSample(Wave2FixCase):
    def test_effective_sample_multiplied_by_tightening(self):
        """乘数执行层消费方：控制计划视图输出生效抽样量 = 基础抽样量 × 乘数
        （乘数曾只存得进、看得见，无执行消费方）。"""
        self.act_as(self.owner)
        plan = self._plan(multiplier=1.5, points=[
            {"name": "外观", "sample": 10},
            {"name": "尺寸", "sample": None},
        ])
        rows = self.client.get(
            f"/api/projects/{self.project.id}/qms/control-plans").json()["items"]
        row = next(r for r in rows if r["id"] == str(plan.id))
        by_name = {p["name"]: p for p in row["quality_points"]}
        self.assertEqual(by_name["外观"]["effective_sample"], 15.0)
        self.assertIsNone(by_name["尺寸"]["effective_sample"])


class TestAuditReportEndpoints(Wave2FixCase):
    def test_detail_and_export_md(self):
        """详情/导出端点补齐（此前只有 POST+list，历史报告无法单取/导出）。"""
        self.act_as(self.owner)
        created = self.client.post(
            f"/api/projects/{self.project.id}/audit-reports",
            json={"template_key": "quality", "params": {}})
        self.assertEqual(created.status_code, 200, created.text)
        report_id = created.json()["id"]
        detail = self.client.get(
            f"/api/projects/{self.project.id}/audit-reports/{report_id}")
        self.assertEqual(detail.status_code, 200, detail.text)
        self.assertEqual(detail.json()["id"], report_id)
        exported = self.client.get(
            f"/api/projects/{self.project.id}/audit-reports/{report_id}/export.md")
        self.assertEqual(exported.status_code, 200, exported.text)
        self.assertIn("text/markdown", exported.headers["content-type"])
        self.assertIn("attachment", exported.headers["content-disposition"])
        missing = self.client.get(
            f"/api/projects/{self.project.id}/audit-reports/{uuid.uuid4()}")
        self.assertEqual(missing.status_code, 404)

    def test_narrative_uses_gateway_with_purpose_and_actor(self):
        """LLM 主路径（曾恒回退文案）：网关被 mock 时叙述取 LLM 内容，
        且 purpose=audit_report 与 actor 真被传入。"""
        from unittest.mock import patch

        from app.services import audit_qa as audit_qa_module

        captured = {}

        def _fake_chat(db, *, config, messages, temperature=None, max_tokens=None,
                       purpose="chat", actor=None, **kwargs):
            captured["purpose"] = purpose
            captured["actor"] = actor
            return ("本报告质量证据充分。[E1] 为预警记录。", {"tokens": 1}, None)

        import app.services.llm_gateway as gateway_module

        # _narrative 内部延迟 import 网关——mock 网关模块的源头函数
        with patch.object(gateway_module, "chat_completion", _fake_chat), \
                patch.object(gateway_module, "resolve_profile",
                             lambda db, purpose=None: object()):
            report = audit_qa_module.build_report(
                self.db, project_id=self.project.id,
                template_key="quality", created_by_id=self.owner.id)
        self.assertEqual(captured["purpose"], "audit_report")
        self.assertEqual(captured["actor"], self.owner.id,
                         "叙述调用必须传 actor（口径 5 同族修复）")
        self.assertIn("本报告质量证据充分", report.content_markdown,
                      "LLM 内容应进入叙述而非回退文案")


class TestMetricRegistryOption(Wave2FixCase):
    def test_option_registry_extends_ask_metrics(self):
        """PlatformOption qa.metric_registry 接线（曾无入口，自定义指标
        永不生效）：注册自定义指标后问数可答。"""
        from app.models.platform_option import set_option

        self.act_as(self.owner)
        set_option(self.db, "qa.metric_registry", {
            "高危预警数": {
                "sql": ("SELECT COUNT(*) AS value FROM quality_alerts "
                        "WHERE project_id = :project_id AND severity = 'critical'"),
                "params": [],
                "footnote": "severity = critical（自定义注册表）",
            },
        })
        self.db.commit()
        alert = self.make_alert(title=f"高危-{self.case_key}",
                                merge_key=f"metric-{self.case_key}")
        alert.severity = "critical"
        self.db.commit()
        answer = self.client.post(
            f"/api/projects/{self.project.id}/ask-metrics",
            json={"question": "高危预警数是多少"})
        self.assertEqual(answer.status_code, 200, answer.text)
        self.assertEqual(answer.json().get("status"), "answered",
                         "自定义指标经 option 注册表应可答")
        listing = self.client.get(
            f"/api/projects/{self.project.id}/metric-registry").json()
        names = {row["name"] for row in listing["items"]}
        self.assertIn("高危预警数", names)


class TestSampleUsageOverride(Wave2FixCase):
    def test_explicit_sample_usage_overrides_default(self):
        """sample_usage 显式传入覆盖缺省登记（wave1 只测了缺省分支）。"""
        import pandas as pd

        from app.services.dataset_splitting import create_split

        frame = pd.DataFrame({
            "value": [1.0, 2.0, 3.0, 4.0],
            "target": [0, 1, 0, 1],
        })
        split = create_split(
            self.db, project_id=self.project.id,
            dataset_version_id=uuid.uuid4(), name="显式用途",
            strategy="random_stratified",
            params={"target_column": "target", "test_size": 0.5, "seed": 42,
                    "sample_usage": {"development": "training",
                                     "blind": "external_eval"}},
            frame=frame,
        )
        self.assertEqual(split.params["sample_usage"]["blind"], "external_eval")
        self.assertEqual(split.params["sample_usage"]["development"], "training")


class TestBlindLabelSubjectBinding(Wave2FixCase):
    def test_blind_label_subject_bound_to_login_user(self):
        """S3 #28 修复：subject 不再来自请求体——一律绑登录用户。曾为自由
        字符串：一人可用不同 subject 替全部标注位提交，且与仲裁人的 UUID
        身份空间不一致。"""
        from app.models.label_quality import AnnotationBlindLabel

        base = f"/api/projects/{self.project.id}"
        self.act_as(self.owner)
        samples = [f"s-{self.case_key}-{index}" for index in range(3)]
        opened = self.client.post(f"{base}/consistency-rounds", json={
            "annotator_subject_ids": [str(self.owner.id), str(self.operator.id)],
            "sample_ids": samples,
        })
        self.assertEqual(opened.status_code, 200, opened.text)
        round_id = opened.json()["id"]
        # 请求体带 subject_id → 422（契约禁字段：身份只能来自登录态）
        with_subject = self.client.put(
            f"{base}/consistency-rounds/{round_id}/labels",
            json={"subject_id": str(self.operator.id),
                  "sample_id": samples[0], "values": {"q": "ok"}})
        self.assertEqual(with_subject.status_code, 422, with_subject.text)
        # 提交 → 落库 subject = 登录用户 id
        ok = self.client.put(
            f"{base}/consistency-rounds/{round_id}/labels",
            json={"sample_id": samples[0], "values": {"q": "ok"}})
        self.assertEqual(ok.status_code, 200, ok.text)
        row = self.db.query(AnnotationBlindLabel).filter(
            AnnotationBlindLabel.round_id == uuid.UUID(round_id),
            AnnotationBlindLabel.sample_id == samples[0],
        ).first()
        self.assertIsNotNone(row)
        self.assertEqual(row.subject_id, str(self.owner.id))
        # 同用户同样本重复提交 → 400 BLIND_LABEL_ALREADY_SUBMITTED
        again = self.client.put(
            f"{base}/consistency-rounds/{round_id}/labels",
            json={"sample_id": samples[0], "values": {"q": "ok2"}})
        self.assertEqual(again.status_code, 400, again.text)
        # 名单内 operator 同样本一票（并行盲标通道）
        self.act_as(self.operator)
        other = self.client.put(
            f"{base}/consistency-rounds/{round_id}/labels",
            json={"sample_id": samples[0], "values": {"q": "ng"}})
        self.assertEqual(other.status_code, 200, other.text)
        # 名单外但有 quality.label 权限的用户 → 400 SUBJECT_NOT_IN_ROUND
        # （viewer 升 operator 角色：持有标签权限，未注册进本回合名单）
        from app.models.access import ProjectMember
        from sqlalchemy import update

        self.db.execute(update(ProjectMember)
                        .where(ProjectMember.project_id == self.project.id,
                               ProjectMember.user_id == self.viewer.id)
                        .values(role="operator"))
        self.db.commit()
        self.act_as(self.viewer)
        outsider = self.client.put(
            f"{base}/consistency-rounds/{round_id}/labels",
            json={"sample_id": samples[0], "values": {"q": "ok"}})
        self.assertEqual(outsider.status_code, 400, outsider.text)
        self.assertEqual(outsider.json()["detail"]["code"],
                         "BLIND_LABEL_SUBJECT_NOT_IN_ROUND")


class TestReportSameSource(Wave2FixCase):
    def test_report_ng_rate_same_source_as_trend_and_demo_filtered(self):
        """口径 9：报告与趋势页共用 production_by_day+alert_series——NG 率=
        确认 NG÷产量；alert_total 走 scoped_alerts（演示预警不入统计）；
        top_defects 从窗口确认异常聚合 Top5（曾恒 []）。"""
        from app.models.quality_alerts import QualityAlert
        from app.services.qms_tools import _monthly_key, generate_report
        from datetime import datetime as _dt

        now = _dt.utcnow()
        period_key = _monthly_key(now)
        # 月报窗口=上个自然月：夹具日期必须落窗口内（created_at 与 closed_at
        # 双落——confirmed_ng 按关闭日归档）
        in_window = now.date().replace(day=1) - timedelta(days=15)
        created_at = _dt(in_window.year, in_window.month, in_window.day, 10, 0, 0)
        closed_at = created_at + timedelta(days=1)
        # 窗口内：2 条真实确认异常（其中 1 条合并计数 3）+1 条演示确认异常
        for title, occurrence, is_demo in (
            (f"虚焊-{self.case_key}", 3, False),
            (f"虚焊-{self.case_key}", 1, False),
            (f"飞溅-{self.case_key}", 1, False),
            (f"演示缺陷-{self.case_key}", 9, True),
        ):
            self.db.add(QualityAlert(
                project_id=self.project.id, source_type="model_risk",
                severity="warning", title=title, evidence={},
                merge_key=f"report-{self.case_key}-{title[:8]}-{is_demo}",
                status="closed", resolution="confirmed_issue", is_demo=is_demo,
                occurrence_count=occurrence,
                created_at=now - timedelta(days=3),
                closed_at=now - timedelta(days=2),
            ))
        self.db.commit()
        report = generate_report(self.db, project_id=self.project.id,
                                 period="monthly", period_key=period_key,
                                 created_by_id=self.owner.id)
        content = report.content
        self.assertEqual(content["top_defects"][0]["defect"],
                         f"虚焊-{self.case_key}")
        self.assertEqual(content["top_defects"][0]["count"], 4, "合并计数应累加")
        self.assertTrue(all("演示缺陷" not in item["defect"]
                            for item in content["top_defects"]),
                        "演示预警不得进 Top 缺陷")
        self.assertNotIn(9, [item["count"] for item in content["top_defects"]],
                         "演示计数（9）不得混入")
        # 同源：报告 NG 率应等于 trend_view totals 的 ng_rate（同一对聚合函数）
        from app.services.quality_aggregates import MonitorScope, trend_view

        window = content["window"]
        trend = trend_view(self.db, self.project.id, MonitorScope(),
                           since=_dt.fromisoformat(window[0]),
                           until=_dt.fromisoformat(window[1]))
        self.assertEqual(content["confirmed_ng"], trend["totals"]["confirmed_ng"])
        self.assertEqual(content["produced_total"], trend["totals"]["total"])
        self.assertEqual(content["ng_rate"], trend["totals"]["ng_rate"])


if __name__ == "__main__":
    unittest.main()

