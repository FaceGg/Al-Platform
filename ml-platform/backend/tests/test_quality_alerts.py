"""补齐路线第一批 F2a：预警处置链路（B1-01/B1-02，技术方案 §9.10）。

覆盖：确认防呆（责任人必填）、五阶段流转图与连续轨迹、处置单快照三要素
及其不可变性、误报回流复核任务（含创建失败不丢处置）、聚合桶回写、
同因合并、预警规则校验（触发下限独立于分级阈值）、CSV 导出与演示隔离。
"""
import base64
import struct
import unittest
import uuid
from datetime import datetime, timedelta
from unittest import mock

from app.models.access import AuditEvent
from app.models.data_version import DatasetSample, DatasetVersion
from app.models.inference_result import InferenceResultBucket
from app.models.platform_models import AnnotationTaskScopeSample, GenericAnnotationTask
from app.models.project import Project
from app.models.quality_alerts import QualityAlert, QualityAlertEvent
from app.models.quality_domain import QualityScene, QualitySpecLimit
from app.models.user import User
from app.services import quality_alerts as service
from tests.quality_alert_fixtures import QualityAlertApiCase


def _encoded_waveform(values):
    return base64.b64encode(struct.pack(f">{len(values)}h", *[int(v) for v in values])).decode("ascii")


class TestAlertLifecycle(QualityAlertApiCase):
    def _url(self, alert_id, suffix=""):
        return f"/api/projects/{self.project.id}/quality-alerts/{alert_id}{suffix}"

    def _dispose(self, alert_id, **extra):
        return self.client.post(self._url(alert_id, "/disposition"), json=extra)

    def test_ack_requires_assignee(self):
        alert = self.make_alert()
        # 请求体缺责任人 → 契约层拒绝
        self.assertEqual(self.client.post(self._url(alert.id, "/ack"), json={}).status_code, 422)
        missing = self.client.post(
            self._url(alert.id, "/ack"), json={"assignee_id": str(uuid.uuid4())},
        )
        self.assertEqual(missing.status_code, 422)
        self.assertEqual(missing.json()["detail"]["code"], "ASSIGNEE_NOT_FOUND")
        # 责任人为空时绕开确认直接流转 → 同样被拒（验收：责任人为空时确认按钮置灰）
        blocked = self.transition(alert.id, "acknowledged")
        self.assertEqual(blocked.status_code, 422)
        self.assertEqual(blocked.json()["detail"]["code"], "ALERT_ASSIGNEE_REQUIRED")
        self.assertEqual(self.detail(alert.id)["status"], "open")
        self.assertIsNone(self.detail(alert.id)["assigned_to"])

    def test_full_lifecycle_records_continuous_status_trail(self):
        alert = self.make_alert()
        self.assertEqual(self.ack(alert.id).status_code, 200)
        self.assertEqual(self.transition(alert.id, "processing").status_code, 200)
        review = self.client.post(self._url(alert.id, "/request-review"))
        self.assertEqual(review.status_code, 200)
        response = self._dispose(
            alert.id, resolution="confirmed_issue", type="参数调整",
            cause="电极磨损", action="更换电极", downtime=True,
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "closed")
        self.assertEqual(body["resolution"], "confirmed_issue")
        self.assertIsNotNone(body["first_ack_at"])
        self.assertIsNotNone(body["closed_at"])

        events = self.events(alert.id)
        self.assertEqual(
            [event["action"] for event in events],
            ["created", "acknowledged", "status_changed", "review_requested",
             "status_changed", "disposition_submitted"],
        )
        # 轨迹首尾相接：每条流转的「从状态」等于上一条的「到状态」
        moves = [
            (event["from_status"], event["to_status"])
            for event in events if event["from_status"]
        ]
        self.assertEqual(moves, [
            ("open", "acknowledged"), ("acknowledged", "processing"),
            ("processing", "review_pending"), ("review_pending", "closed"),
        ])
        self.assertEqual(events[-1]["form_snapshot"]["cause"], "电极磨损")
        self.assertTrue(events[-1]["form_snapshot"]["downtime"])

        audited = {
            row.action for row in self.db.query(AuditEvent).filter(
                AuditEvent.project_id == self.project.id,
                AuditEvent.result == "success",
            ).all()
        }
        self.assertTrue({
            "quality.alert.ack", "quality.alert.transition",
            "quality.alert.request_review", "quality.alert.disposition",
        } <= audited)

    def test_invalid_transitions_rejected(self):
        alert = self.make_alert()
        for target in ("processing", "review_pending", "closed"):
            with self.subTest(target=target):
                response = self.transition(alert.id, target)
                self.assertEqual(response.status_code, 422)
                self.assertEqual(response.json()["detail"]["code"], "ALERT_TRANSITION_INVALID")
        self.assertEqual(self.ack(alert.id).status_code, 200)
        self.assertEqual(self.transition(alert.id, "open").status_code, 422)
        # 关闭必须带结论
        unresolved = self.transition(alert.id, "closed")
        self.assertEqual(unresolved.status_code, 422)
        self.assertEqual(unresolved.json()["detail"]["code"], "ALERT_RESOLUTION_REQUIRED")
        self.assertEqual(self.transition(alert.id, "processing").status_code, 200)
        self.assertEqual(self.transition(alert.id, "closed", resolution="other").status_code, 200)
        # closed 是终态
        self.assertEqual(self.transition(alert.id, "processing").status_code, 422)

    def test_only_alert_handlers_can_act(self):
        alert = self.make_alert()
        self.act_as(self.viewer)
        denied = self.ack(alert.id)
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(denied.json()["detail"]["code"], "PROJECT_PERMISSION_DENIED")
        # 只读成员仍可查看
        self.assertEqual(self.client.get(self._url(alert.id)).status_code, 200)
        # operator（班组长）可以处置——处置是运营动作，不需要配置类权限
        self.act_as(self.operator)
        self.assertEqual(self.ack(alert.id).status_code, 200)

    def test_confirmed_issue_writes_back_bucket_once_per_alert(self):
        occurred_at = datetime(2026, 11, 26, 9, 20, 0)
        bucket = InferenceResultBucket(
            bucket_start=occurred_at.replace(minute=0, second=0, microsecond=0),
            project_id=self.project.id, scene_id=self.scene.id,
            station_id=self.station.id, total=10, ok_count=8, anomaly_count=2,
        )
        self.db.add(bucket)
        self.db.commit()
        bucket_id = bucket.id
        for _ in range(2):
            alert = self.make_alert(evidence={
                "kind": "param_exceed", "field": "force", "recorded_value": 14.0,
                "occurred_at": occurred_at.isoformat(),
            })
            self.assertEqual(self.ack(alert.id).status_code, 200)
            response = self._dispose(alert.id, resolution="confirmed_issue")
            self.assertTrue(response.json()["outcome"]["bucket_confirmed"])
        self.db.expire_all()
        self.assertEqual(self.db.get(InferenceResultBucket, bucket_id).ng_confirmed_count, 2)

        # 证据里没有发生时间（如演示预警）→ 不回写，也不凭空造桶
        orphan = self.make_alert()
        self.ack(orphan.id)
        response = self._dispose(orphan.id, resolution="confirmed_issue")
        self.assertFalse(response.json()["outcome"]["bucket_confirmed"])
        self.assertEqual(self.db.query(InferenceResultBucket).count(), 1)


class TestFalsePositiveReviewTask(QualityAlertApiCase):
    def _url(self, alert_id, suffix=""):
        return f"/api/projects/{self.project.id}/quality-alerts/{alert_id}{suffix}"

    def _dispose(self, alert_id, **extra):
        return self.client.post(self._url(alert_id, "/disposition"), json=extra)

    def test_false_positive_creates_assignable_review_task(self):
        version = self.make_dataset_version([{"vin": "VIN-001", "force": 12.5, "quality": 0}])
        alert = self.make_alert(sample_key="VIN-001")
        self.assertEqual(self.ack(alert.id).status_code, 200)
        response = self._dispose(alert.id, resolution="false_positive", cause="模型误判")
        self.assertEqual(response.status_code, 200)
        task_id = response.json()["outcome"]["review_task_id"]
        self.assertIsNotNone(task_id, "误报结论应生成复核任务（验收：误报结论自动进回流队列）")

        self.db.expire_all()
        task = self.db.get(GenericAnnotationTask, uuid.UUID(task_id))
        self.assertEqual(task.status, "awaiting_annotation")
        self.assertEqual(task.project_id, self.project.id)
        self.assertEqual(task.dataset_version_id, version.id)
        self.assertEqual(task.idempotency_key, f"quality-alert-review-{alert.id}")
        scope = self.db.query(AnnotationTaskScopeSample).filter(
            AnnotationTaskScopeSample.task_id == task.id,
        ).all()
        self.assertEqual([row.sample_id for row in scope], ["VIN-001"])
        self.assertIn(
            "review_task_created",
            [event["action"] for event in self.events(alert.id)],
        )

    def test_unknown_sample_still_closes_alert_without_task(self):
        alert = self.make_alert(sample_key="VIN-NOT-EXIST")
        self.ack(alert.id)
        response = self._dispose(alert.id, resolution="false_positive")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "closed")
        self.assertIsNone(response.json()["outcome"]["review_task_id"])
        self.assertEqual(self._tasks_for(alert), [])

    def _tasks_for(self, alert):
        """本条预警对应的复核任务（同类用例共用一个库，只看自己的）。"""
        self.db.expire_all()
        return self.db.query(GenericAnnotationTask).filter(
            GenericAnnotationTask.idempotency_key == f"quality-alert-review-{alert.id}",
        ).all()

    def test_review_task_failure_does_not_lose_disposition(self):
        self.make_dataset_version([{"vin": "VIN-002", "force": 1.0}])
        alert = self.make_alert(sample_key="VIN-002")
        self.ack(alert.id)
        with mock.patch.object(
            service, "create_review_task_for_alert", side_effect=RuntimeError("boom"),
        ):
            response = self._dispose(alert.id, resolution="false_positive")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "closed")
        self.assertIsNone(response.json()["outcome"]["review_task_id"])
        self.assertEqual(self._tasks_for(alert), [])
        notes = [
            event["note"] for event in self.events(alert.id)
            if event["action"] == "comment"
        ]
        self.assertTrue(any("创建失败" in note for note in notes), notes)
        # 处置结论确实已落库（不是只在响应里）
        self.assertEqual(self.detail(alert.id)["resolution"], "false_positive")


class TestAlertMerge(QualityAlertApiCase):
    """同因合并（E20）：验收口径——同因事件重放只增加组内计数，不产生重复预警条目。"""

    def _key(self, name="d1"):
        return f"model_risk:deployment={self.case_key}-{name}"

    def _create(self, merge_key=None, severity="warning", minutes_ago=0,
                source_type="model_risk"):
        return service.create_alert(
            self.db, project_id=self.project.id,
            merge_key=merge_key or self._key(),
            source_type=source_type, title="测试预警", severity=severity,
            scene_id=self.scene.id, station_id=self.station.id,
            now=datetime.utcnow() - timedelta(minutes=minutes_ago),
        )

    def _alerts_with_key(self, merge_key):
        self.db.expire_all()
        return self.db.query(QualityAlert).filter(
            QualityAlert.project_id == self.project.id,
            QualityAlert.merge_key == merge_key,
        ).all()

    def test_same_cause_within_window_merges_into_one_alert(self):
        key = self._key()
        first, created = self._create(key)
        self.assertTrue(created)
        for _ in range(3):
            merged, created = self._create(key)
            self.assertFalse(created)
            self.assertEqual(merged.id, first.id)
        self.db.commit()
        self.assertEqual(len(self._alerts_with_key(key)), 1)
        alert = self.db.get(QualityAlert, first.id)
        self.assertEqual(alert.occurrence_count, 4)
        occurred = self.db.query(QualityAlertEvent).filter(
            QualityAlertEvent.alert_id == alert.id,
            QualityAlertEvent.action == "occurred",
        ).count()
        self.assertEqual(occurred, 3)

    def test_merge_window_expiry_creates_new_alert(self):
        key = self._key()
        self._create(key, minutes_ago=45)
        _, created = self._create(key)
        self.assertTrue(created, "合并窗口（默认 30 分钟）之外的重复事件是新预警")
        self.db.commit()
        self.assertEqual(len(self._alerts_with_key(key)), 2)

    def test_different_fields_are_not_merged(self):
        force, _ = self._create(f"param_exceed:field=force", source_type="param_exceed")
        current, created = self._create(
            f"param_exceed:field=current", source_type="param_exceed",
        )
        self.assertTrue(created)
        self.assertNotEqual(force.id, current.id)

    def test_severity_only_escalates(self):
        first, _ = self._create(self._key("hot"), severity="critical")
        merged, _ = self._create(self._key("hot"), severity="warning")
        self.assertEqual(merged.severity, "critical")
        low_key = self._key("warm")
        low, _ = self._create(low_key, severity="warning")
        escalated, _ = self._create(low_key, severity="high")
        self.assertEqual(escalated.id, low.id)
        self.assertEqual(escalated.severity, "high")

    def test_closed_alert_does_not_absorb_new_occurrences(self):
        key = self._key()
        first, _ = self._create(key)
        first.assigned_to_id = self.assignee.id
        service.transition_alert(self.db, first, "acknowledged", actor_id=self.owner.id)
        service.transition_alert(
            self.db, first, "closed", resolution="other", actor_id=self.owner.id,
        )
        _, created = self._create(key)
        self.assertTrue(created)


class TestDispositionSnapshot(QualityAlertApiCase):
    """处置单快照三要素（E07）：验收口径——不随后续 SOP、基线、模型的变更而改写。"""

    def _sop(self, code="SOP-A"):
        return self.client.post(
            f"/api/projects/{self.project.id}/quality-sops",
            json={
                "code": code, "title": "电极更换",
                "content": {"spec_exceed": ["停机", "更换电极"]},
                "scene_id": str(self.scene.id),
            },
        )

    def _freeze(self, base):
        version = self.make_dataset_version([
            {"vin": f"b-{base}-{index}", "force": base + (index % 4) * 0.5}
            for index in range(30)
        ])
        response = self.client.post(
            f"/api/projects/{self.project.id}/quality-scenes/{self.scene.id}/spc-baselines",
            json={"dataset_version_id": str(version.id), "field": "force"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_snapshot_is_frozen_against_later_changes(self):
        self.assertEqual(self._sop().json()["version"], 1)
        self.assertEqual(self._freeze(10.0)["version"], 1)
        alert = self.make_alert(
            source_type="param_exceed",
            evidence={"kind": "param_exceed", "field": "force", "recorded_value": 14.0},
            merge_key="param_exceed:field=force",
        )
        self.assertEqual(self.ack(alert.id).status_code, 200)
        response = self.client.post(
            f"/api/projects/{self.project.id}/quality-alerts/{alert.id}/disposition",
            json={"resolution": "confirmed_issue"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        snapshot = self.events(alert.id)[-1]["snapshot"]
        self.assertEqual(snapshot["sops"][0]["version"], 1)
        self.assertEqual(snapshot["sops"][0]["code"], "SOP-A")
        self.assertEqual(snapshot["spc_baseline"]["version"], 1)
        self.assertIsNone(snapshot["model_version"], "参数超限预警无模型版本，快照如实留空")

        # 之后 SOP 出新版本、基线重新冻结
        self.assertEqual(self._sop().json()["version"], 2)
        self.assertEqual(self._freeze(20.0)["version"], 2)
        self.assertEqual(self.events(alert.id)[-1]["snapshot"], snapshot)

        # 判据链的「当前复算」读现行基线（D20：展示读现行，留档读快照）
        criteria = self.client.get(
            f"/api/projects/{self.project.id}/quality-alerts/{alert.id}/criteria",
        ).json()["criteria"]
        self.assertEqual(criteria[1]["detail"]["baseline"]["version"], 2)

    def test_snapshot_records_the_model_version_cited_by_the_alert(self):
        """快照三要素里的模型版本：取自预警证据；库里查不到时如实留引用 id。"""
        version_id = str(uuid.uuid4())
        alert = self.make_alert(
            merge_key=f"model-version-{self.case_key}",
            evidence={"kind": "model_risk", "score": 0.97, "model_version_id": version_id},
        )
        self.assertEqual(self.ack(alert.id).status_code, 200)
        response = self.client.post(
            f"/api/projects/{self.project.id}/quality-alerts/{alert.id}/disposition",
            json={"resolution": "confirmed_issue"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        snapshot = self.events(alert.id)[-1]["snapshot"]
        self.assertEqual(snapshot["model_version"], {"id": version_id})
        self.assertTrue(snapshot["frozen_at"])


class TestAlertSettings(QualityAlertApiCase):
    def _settings_url(self):
        return f"/api/projects/{self.project.id}/quality-scenes/{self.scene.id}/alert-settings"

    def test_settings_are_validated_against_platform_defaults(self):
        # 只把「高」档改到低于默认触发下限 → 拒绝
        rejected = self.client.put(self._settings_url(), json={"high_threshold": 0.5})
        self.assertEqual(rejected.status_code, 422)
        self.assertEqual(rejected.json()["detail"]["code"], "ALERT_THRESHOLD_ORDER_INVALID")
        accepted = self.client.put(
            self._settings_url(), json={"trigger_threshold": 0.5, "high_threshold": 0.6},
        )
        self.assertEqual(accepted.status_code, 200, accepted.text)
        body = accepted.json()
        # 只存显式配置的键；未配置的键跟随平台默认
        self.assertEqual(
            body["alert_settings"],
            {"trigger_threshold": 0.5, "high_threshold": 0.6},
        )
        self.assertEqual(body["resolved"]["critical_threshold"], 0.95)

    def test_trigger_threshold_is_independent_of_severity_thresholds(self):
        """对标反面教材：调整分级阈值不改变触发判定；风险分口径留在证据里。"""
        response = self.client.put(self._settings_url(), json={
            "trigger_threshold": 0.6, "high_threshold": 0.97, "critical_threshold": 0.99,
        })
        self.assertEqual(response.status_code, 200, response.text)
        self.db.expire_all()
        settings = service.resolve_alert_settings(self.db.get(QualityScene, self.scene.id))
        self.assertEqual(settings["trigger_threshold"], 0.6)
        # 0.8 已触发（≥0.6），但在这一套分级阈值下只是 warning
        self.assertEqual(service.severity_for_score(0.8, settings), "warning")
        self.assertEqual(service.severity_for_score(0.98, settings), "high")
        self.assertEqual(service.severity_for_score(0.995, settings), "critical")


class TestAlertListing(QualityAlertApiCase):
    def _list(self, **params):
        return self.client.get(
            f"/api/projects/{self.project.id}/quality-alerts", params=params,
        )

    def _export(self, **params):
        return self.client.get(
            f"/api/projects/{self.project.id}/quality-alerts/export.csv", params=params,
        )

    def test_demo_alerts_hidden_by_default(self):
        real = self.make_alert()
        demo = self.make_alert(is_demo=True, merge_key=f"demo:{self.case_key}")
        own = {str(real.id), str(demo.id)}

        def visible(response):
            return {item["id"] for item in response.json()["items"]} & own

        # 默认视图看不到演示预警（诚实设计⑥）
        self.assertEqual(visible(self._list()), {str(real.id)})
        # 显式开关可见，且带演示标记
        shown = self._list(include_demo="true").json()["items"]
        self.assertEqual({item["id"] for item in shown} & own, own)
        self.assertTrue(next(item for item in shown if item["id"] == str(demo.id))["is_demo"])

    def test_csv_export_excludes_demo_and_needs_handle_permission(self):
        real = self.make_alert()
        demo = self.make_alert(is_demo=True, merge_key=f"demo:{self.case_key}")

        def exported_ids(response):
            lines = response.text.strip("\ufeff\r\n").split("\r\n")[1:]
            return {line.split(",")[0] for line in lines}

        exported = self._export()
        self.assertEqual(exported.status_code, 200)
        self.assertTrue(exported.headers["content-type"].startswith("text/csv"))
        # BOM 开头（Excel 直开不乱码）；表头 + 本用例的非演示预警
        self.assertTrue(exported.text.startswith("\ufeff"))
        self.assertEqual(
            exported_ids(exported) & {str(real.id), str(demo.id)}, {str(real.id)},
        )
        with_demo = self._export(include_demo="true")
        self.assertEqual(
            exported_ids(with_demo) & {str(real.id), str(demo.id)},
            {str(real.id), str(demo.id)},
        )
        self.act_as(self.viewer)
        self.assertEqual(self._export().status_code, 403)


class TestWaveformOverlay(QualityAlertApiCase):
    """曲线叠加（D23）：带波形样本可叠加目标窗口；无波形时给出显式空态。"""

    def test_waveform_is_decoded_with_spec_window(self):
        self.scene.field_roles = {"sample_key": "vin", "waveform": "cvei"}
        self.db.commit()
        points = [100, -200, 300, 450, 120]
        self.make_dataset_version([{"vin": "VIN-W", "cvei": _encoded_waveform(points), "force": 3.0}])
        self.db.add(QualitySpecLimit(
            scene_id=self.scene.id, field="cvei", statistic="mean",
            usl=200.0, lsl=50.0, target=120.0, unit="A",
        ))
        self.db.commit()
        alert = self.make_alert(sample_key="VIN-W")
        response = self.client.get(
            f"/api/projects/{self.project.id}/quality-alerts/{alert.id}/waveform",
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["points"], [100.0, -200.0, 300.0, 450.0, 120.0])
        self.assertEqual(body["specs"][0]["statistic"], "mean")
        self.assertEqual(body["specs"][0]["usl"], 200.0)

        missing = self.make_alert(sample_key="VIN-NO-WAVE")
        body = self.client.get(
            f"/api/projects/{self.project.id}/quality-alerts/{missing.id}/waveform",
        ).json()
        self.assertEqual(body["status"], "no_waveform")
        self.assertTrue(body["reason"])

    def test_waveform_lookup_stays_inside_the_project(self):
        """样本键不是全局唯一的：别的项目里的同名样本不能被读出来。"""
        other_owner = User(username=f"other-{uuid.uuid4().hex[:6]}", password_hash="hash")
        self.db.add(other_owner)
        self.db.flush()
        other_project = Project(name="Other project", owner_id=other_owner.id)
        self.db.add(other_project)
        self.db.flush()
        self.db.add(DatasetVersion(
            project_id=other_project.id, operator_id=other_owner.id, version=1,
            status="ready", row_count=1, column_count=1,
            content_hash=uuid.uuid4().hex, schema_hash=uuid.uuid4().hex,
        ))
        self.db.flush()
        other_version = self.db.query(DatasetVersion).filter(
            DatasetVersion.project_id == other_project.id,
        ).one()
        self.db.add(DatasetSample(
            dataset_version_id=other_version.id, sample_id="VIN-SHARED",
            row_index=0, values={"vin": "VIN-SHARED", "cvei": _encoded_waveform([1, 2, 3])},
        ))
        self.scene.field_roles = {"sample_key": "vin", "waveform": "cvei"}
        self.db.commit()
        alert = self.make_alert(sample_key="VIN-SHARED")
        body = self.client.get(
            f"/api/projects/{self.project.id}/quality-alerts/{alert.id}/waveform",
        ).json()
        self.assertEqual(body["status"], "no_waveform")

    def test_decoder_rejects_malformed_input(self):
        self.assertIsNone(service.decode_waveform_column("not base64!!"))
        self.assertIsNone(service.decode_waveform_column(""))
        self.assertIsNone(service.decode_waveform_column(None))
        # 奇数字节不是 int16 序列
        self.assertIsNone(service.decode_waveform_column(base64.b64encode(b"\x01").decode()))
