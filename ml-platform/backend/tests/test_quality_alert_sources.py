"""补齐路线第一批 F2a：三类预警来源接入（B1-01〔规划〕，技术方案 §9.2/§9.10）。

验收口径：先行三类（模型风险 / 参数超限 / 设备异常）各有端到端用例；
后行三类接入时预警中心不改表（表结构层面已含六类来源枚举）。

- 模型风险与参数超限走**真实的推理落库路径**（InferenceResultRecorder →
  SessionLocal 密封库），验证预警与明细在同一事务里产生、明细行被回写；
- 设备异常与 SLA 走巡检任务体；
- SLA「送达」用真实站内信适配器走完 outbox → 订阅 → 站内信全链。
"""
import base64
import unittest
import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest import mock
from pydantic import SecretStr

from app.config import Settings
from app.database import Base, SessionLocal
from app.models.compute import EdgeDevice
from app.models.inference_result import InferenceResult, InferenceResultBucket
from app.models.notifications import (
    InAppNotification,
    NotificationEndpoint,
    NotificationOutbox,
    NotificationSubscription,
)
from app.models.project import Project
from app.models.quality_alerts import QualityAlert, QualityAlertEvent
from app.models.quality_domain import QualityScene, QualitySpecLimit, QualityStation
from app.models.user import User
from app.services import quality_alerts as service
from app.services.inference_results import ContextRow, InferenceResultRecorder
from app.services.notification_channels import NotificationChannelRouter
from app.services.notification_crypto import encrypt_config
from app.tasks.notification_tasks import execute_notification_delivery
from tests.quality_alert_fixtures import QualityAlertApiCase

_MASTER_KEY = base64.urlsafe_b64encode(b"f2-sla-notify-key-32-bytes-long!!"[:32]).decode("ascii")


class _FakeStorage:
    def put_snapshot(self, source, project_id, date_key, filename):
        return SimpleNamespace(uri=f"file:///fake/inference-snapshots/{date_key}/{filename}")


class TestInferenceAlertSources(unittest.TestCase):
    """模型风险 / 参数超限：经真实落库路径产生（密封测试库）。"""

    @classmethod
    def setUpClass(cls):
        from app.database import engine

        Base.metadata.create_all(bind=engine)
        tag = uuid.uuid4().hex[:8]
        with SessionLocal() as db:
            user = User(username=f"f2-src-{tag}", password_hash="hash")
            db.add(user)
            db.flush()
            project = Project(name=f"F2 alert sources {tag}", owner_id=user.id)
            db.add(project)
            db.flush()
            scene = QualityScene(project_id=project.id, code="SRC", name="来源场景")
            db.add(scene)
            db.flush()
            station = QualityStation(scene_id=scene.id, code="SRC-ST", name="来源工位")
            db.add(station)
            db.flush()
            db.add_all([
                QualitySpecLimit(scene_id=scene.id, field="force", statistic="value",
                                 usl=8.0, lsl=2.0, unit="kN"),
                QualitySpecLimit(scene_id=scene.id, field="current", statistic="value",
                                 usl=20.0, unit="kA"),
            ])
            db.commit()
            cls.project_id, cls.scene_id, cls.station_id = project.id, scene.id, station.id

    @classmethod
    def tearDownClass(cls):
        cls._cleanup()

    def setUp(self):
        self._cleanup()

    @classmethod
    def _cleanup(cls):
        with SessionLocal() as db:
            alert_ids = [
                row.id for row in db.query(QualityAlert.id).filter(
                    QualityAlert.project_id == cls.project_id,
                )
            ]
            if alert_ids:
                db.query(QualityAlertEvent).filter(
                    QualityAlertEvent.alert_id.in_(alert_ids),
                ).delete(synchronize_session="fetch")
                db.query(InferenceResult).filter(
                    InferenceResult.alert_id.in_(alert_ids),
                ).update({"alert_id": None}, synchronize_session=False)
                db.query(QualityAlert).filter(
                    QualityAlert.id.in_(alert_ids),
                ).delete(synchronize_session="fetch")
            db.query(InferenceResult).filter(
                InferenceResult.project_id == cls.project_id,
            ).delete(synchronize_session="fetch")
            db.query(InferenceResultBucket).filter(
                InferenceResultBucket.project_id == cls.project_id,
            ).delete(synchronize_session="fetch")
            db.commit()

    def _record(self, request_id, result, records, *, channel="online"):
        context = [
            ContextRow(sample_key=f"VIN-{index}", scene_id=self.scene_id,
                       station_id=self.station_id)
            for index in range(len(records))
        ]
        InferenceResultRecorder(storage=_FakeStorage(), counter=None, sample_rate=0.0).record_prediction(
            request_id=request_id,
            project_id=self.project_id,
            context_rows=context,
            result=result,
            records=records,
            occurred_at=datetime(2026, 11, 26, 10, 0, 0),
            channel=channel,
        )

    def _alerts(self, source_type):
        with SessionLocal() as db:
            return db.query(QualityAlert).filter(
                QualityAlert.project_id == self.project_id,
                QualityAlert.source_type == source_type,
            ).all()

    def test_model_risk_threshold_merges_and_flags_rows(self):
        self._record(
            f"req-f2-{uuid.uuid4().hex[:6]}",
            {"predictions": ["NG", "NG", "NG"], "probabilities": [0.5, 0.9, 0.99]},
            [{"force": 3.0}, {"force": 3.1}, {"force": 3.2}],
        )
        alerts = self._alerts("model_risk")
        self.assertEqual(len(alerts), 1, "同一次请求内越过阈值的多行并成一条预警")
        alert = alerts[0]
        self.assertEqual(alert.occurrence_count, 2)
        self.assertEqual(alert.severity, "critical", "组内出现过 0.99，整组按最严重显示")
        self.assertEqual(alert.evidence["rule"], "threshold")
        self.assertIsNotNone(alert.sla_due_at)
        self.assertEqual(alert.scene_id, self.scene_id)
        self.assertEqual(alert.station_id, self.station_id)
        with SessionLocal() as db:
            rows = db.query(InferenceResult).filter(
                InferenceResult.project_id == self.project_id,
            ).order_by(InferenceResult.sample_key).all()
            # 未越阈值的行不被标记
            self.assertEqual([row.alert_triggered for row in rows], [None, True, True])
            self.assertEqual(
                {row.alert_id for row in rows if row.alert_id}, {alert.id},
            )
            # 明细与聚合桶照常落库
            self.assertEqual(len(rows), 3)
            bucket = db.query(InferenceResultBucket).filter(
                InferenceResultBucket.project_id == self.project_id,
            ).one()
            self.assertEqual(bucket.total, 3)

    def test_unsupervised_flag_triggers_below_the_score_threshold(self):
        """无监督模型的异常分数量纲因族而异：模型判异即触发，不只靠固定阈值。

        第二行分数 0.6 低于触发阈值 0.70，但模型判异——只比较分数会漏掉它。
        """
        self._record(
            f"req-f2-{uuid.uuid4().hex[:6]}",
            {"anomaly_score": [0.02, 0.6], "is_anomaly": [False, True],
             "thresholds": [0.55, 0.55]},
            [{"force": 3.0}, {"force": 9.0}],
        )
        alerts = self._alerts("model_risk")
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].evidence["rule"], "is_anomaly")
        self.assertEqual(alerts[0].evidence["score"], 0.6)
        self.assertEqual(alerts[0].evidence["score_kind"], "anomaly_score")
        self.assertEqual(alerts[0].occurrence_count, 1)

    def test_both_rules_recorded_when_score_also_crosses_threshold(self):
        self._record(
            f"req-f2-{uuid.uuid4().hex[:6]}",
            {"anomaly_score": [7.5], "is_anomaly": [True], "thresholds": [6.0]},
            [{"force": 9.0}],
        )
        alerts = self._alerts("model_risk")
        self.assertEqual(alerts[0].evidence["rule"], "threshold+is_anomaly")
        # 分数不在 [0,1]，不套用比例型分级阈值
        self.assertEqual(alerts[0].severity, "high")

    def test_param_exceed_keeps_fields_apart_and_snapshots_spec(self):
        self._record(
            f"req-f2-{uuid.uuid4().hex[:6]}",
            {"predictions": ["OK", "OK"]},
            [{"force": 12.0, "current": 5.0}, {"force": 3.0, "current": 25.0}],
        )
        alerts = self._alerts("param_exceed")
        self.assertEqual(
            {alert.evidence["field"] for alert in alerts}, {"force", "current"},
            "两个不同参数超限是两条预警，不得并成一条",
        )
        force = next(alert for alert in alerts if alert.evidence["field"] == "force")
        self.assertEqual(force.evidence["recorded_value"], 12.0)
        self.assertEqual(force.evidence["spec"]["usl"], 8.0)
        self.assertEqual(force.evidence["spec"]["unit"], "kN")
        self.assertEqual(force.evidence["kind"], "param_exceed")
        self.assertEqual(force.sample_key, "VIN-0")
        with SessionLocal() as db:
            rows = db.query(InferenceResult).filter(
                InferenceResult.project_id == self.project_id,
                InferenceResult.alert_triggered.is_(True),
            ).all()
            self.assertEqual(len(rows), 2)
            by_alert = {alert.id: alert.evidence["field"] for alert in alerts}
            self.assertEqual(
                sorted(by_alert[row.alert_id] for row in rows), ["current", "force"],
            )

    def test_within_spec_records_raise_no_alert(self):
        self._record(
            f"req-f2-{uuid.uuid4().hex[:6]}",
            {"predictions": ["OK"], "probabilities": [0.1]},
            [{"force": 5.0, "current": 10.0}],
        )
        self.assertEqual(self._alerts("model_risk"), [])
        self.assertEqual(self._alerts("param_exceed"), [])

    def test_demo_channel_is_not_evaluated(self):
        self._record(
            f"demo-{uuid.uuid4().hex[:6]}",
            {"predictions": ["NG"], "probabilities": [0.99]},
            [{"force": 99.0}],
            channel="demo",
        )
        self.assertEqual(self._alerts("model_risk"), [])
        self.assertEqual(self._alerts("param_exceed"), [])

    def test_alert_evaluation_failure_does_not_break_persistence(self):
        """预警评估出错：明细与聚合桶照常落库，且不留半截预警标记。"""
        request_id = f"req-f2-{uuid.uuid4().hex[:6]}"
        with mock.patch(
            "app.services.quality_alerts.evaluate_inference_alerts",
            side_effect=RuntimeError("alert engine down"),
        ):
            self._record(
                request_id, {"probabilities": [0.99, 0.5]}, [{"force": 99.0}, {"force": 3.0}],
            )
        self.assertEqual(self._alerts("model_risk"), [])
        self.assertEqual(self._alerts("param_exceed"), [])
        with SessionLocal() as db:
            rows = db.query(InferenceResult).filter(
                InferenceResult.request_id == request_id,
            ).all()
            self.assertEqual(len(rows), 2)
            self.assertEqual({row.alert_triggered for row in rows}, {None})
            bucket = db.query(InferenceResultBucket).filter(
                InferenceResultBucket.project_id == self.project_id,
            ).one()
            self.assertEqual(bucket.total, 2)


class TestDeviceWatch(QualityAlertApiCase):
    """设备异常（先行来源之三）：心跳过期产生预警，恢复只记一次且不自动关闭。"""

    def _station_with_device(self, last_heartbeat):
        device = EdgeDevice(
            name=f"edge-{self.case_key}", owner_id=self.owner.id,
            last_heartbeat=last_heartbeat,
        )
        self.db.add(device)
        self.db.flush()
        station = QualityStation(
            scene_id=self.scene.id, code=f"ST-{self.case_key}", name="离线工位",
            edge_device_id=device.id,
        )
        self.db.add(station)
        self.db.commit()
        return device, station

    def _alerts(self, station):
        self.db.expire_all()
        return self.db.query(QualityAlert).filter(
            QualityAlert.station_id == station.id,
            QualityAlert.source_type == "device_anomaly",
        ).all()

    def test_stale_heartbeat_then_recovery_then_stale_again(self):
        stale = datetime.utcnow() - timedelta(minutes=30)
        device, station = self._station_with_device(stale)
        first = service.watch_devices(self.db)
        self.db.commit()
        self.assertEqual(first["created"], 1)
        # 巡检每 5 分钟一轮：持续离线不刷屏，只增组内计数
        second = service.watch_devices(self.db)
        self.db.commit()
        self.assertEqual(second["created"], 0)
        alerts = self._alerts(station)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].occurrence_count, 2)
        self.assertEqual(alerts[0].evidence["device_name"], device.name)

        device.last_heartbeat = datetime.utcnow()
        self.db.commit()
        self.assertEqual(service.watch_devices(self.db)["recovered"], 1)
        self.db.commit()
        # 恢复只记一次轨迹；预警不自动关闭，但停止接受合并
        self.assertEqual(service.watch_devices(self.db)["recovered"], 0)
        self.db.commit()
        alert = self._alerts(station)[0]
        self.assertEqual(alert.status, "open")
        self.assertFalse(alert.merge_open)
        recovered = self.db.query(QualityAlertEvent).filter(
            QualityAlertEvent.alert_id == alert.id,
            QualityAlertEvent.action == "device_recovered",
        ).count()
        self.assertEqual(recovered, 1)

        # 恢复后再次离线是新的「因」：产生新预警，不并进已恢复的那条
        device.last_heartbeat = datetime.utcnow() - timedelta(minutes=30)
        self.db.commit()
        self.assertEqual(service.watch_devices(self.db)["created"], 1)
        self.db.commit()
        self.assertEqual(len(self._alerts(station)), 2)

    def test_never_seen_heartbeat_counts_as_offline(self):
        _, station = self._station_with_device(None)
        result = service.watch_devices(self.db)
        self.db.commit()
        self.assertEqual(result["created"], 1)
        self.assertEqual(self._alerts(station)[0].evidence["last_heartbeat"], None)

    def test_disabled_station_is_not_watched(self):
        _, station = self._station_with_device(datetime.utcnow() - timedelta(hours=2))
        station.enabled = False
        self.db.commit()
        result = service.watch_devices(self.db)
        self.db.commit()
        self.assertEqual(result["created"], 0)
        self.assertEqual(self._alerts(station), [])


class TestSlaWatch(QualityAlertApiCase):
    """SLA 两档通知（D21）：临期与超时各只通知一次；临期通知真实送达站内信。"""

    def _alert(self, hours_ago):
        started = datetime.utcnow() - timedelta(hours=hours_ago)
        alert = QualityAlert(
            project_id=self.project.id, scene_id=self.scene.id,
            station_id=self.station.id, source_type="model_risk", severity="warning",
            title="SLA 测试预警", evidence={},
            merge_key=f"sla-{self.case_key}",
            sla_due_at=started + timedelta(hours=24),
            last_event_at=started, created_at=started, updated_at=started,
        )
        self.db.add(alert)
        self.db.flush()
        service.append_event(self.db, alert, "created", created_at=started)
        self.db.commit()
        return alert

    def _outbox(self, alert, level):
        self.db.expire_all()
        return self.db.query(NotificationOutbox).filter(
            NotificationOutbox.idempotency_key == f"quality-alert-sla-{alert.id}-{level}",
        ).first()

    def test_due_then_overdue_notified_once_each(self):
        alert = self._alert(hours_ago=20)  # 剩 4 小时 ≤ 24 小时的 25%
        self.assertEqual(
            service.watch_sla(self.db), {"due_notified": 1, "overdue_notified": 0},
        )
        self.db.commit()
        due = self._outbox(alert, 1)
        self.assertEqual(due.event_type, "quality.alert.sla_due")
        self.assertEqual(due.severity, "warning")
        self.assertEqual(due.payload["alert_id"], str(alert.id))
        # 再巡检不重发
        self.assertEqual(
            service.watch_sla(self.db), {"due_notified": 0, "overdue_notified": 0},
        )
        self.assertIsNone(self._outbox(alert, 2))

        alert.sla_due_at = datetime.utcnow() - timedelta(minutes=5)
        self.db.commit()
        self.assertEqual(
            service.watch_sla(self.db), {"due_notified": 0, "overdue_notified": 1},
        )
        self.db.commit()
        overdue = self._outbox(alert, 2)
        self.assertEqual(overdue.event_type, "quality.alert.sla_overdue")
        self.assertEqual(overdue.severity, "critical")
        self.assertEqual(
            service.watch_sla(self.db), {"due_notified": 0, "overdue_notified": 0},
        )

    def test_plenty_of_time_left_is_not_notified(self):
        alert = self._alert(hours_ago=1)
        self.assertEqual(
            service.watch_sla(self.db), {"due_notified": 0, "overdue_notified": 0},
        )
        self.assertIsNone(self._outbox(alert, 1))

    def test_due_notification_reaches_project_owner_inbox(self):
        """验收口径「SLA 临期自动通知送达」：outbox → 订阅 → 真实站内信适配器。"""
        alert = self._alert(hours_ago=20)
        service.watch_sla(self.db)
        self.db.commit()
        outbox = self._outbox(alert, 1)
        outbox_id, event_id = outbox.id, outbox.event_id
        master_key = SecretStr(_MASTER_KEY)
        endpoint = NotificationEndpoint(
            project_id=self.project.id, kind="in_app", name=f"sla-in-app-{self.case_key}",
            destination_hint="in-app", encrypted_config=encrypt_config({}, master_key),
            enabled=True, created_by_id=self.owner.id,
        )
        self.db.add(endpoint)
        self.db.flush()
        self.db.add(NotificationSubscription(
            project_id=self.project.id, endpoint_id=endpoint.id,
            event_types=["quality.alert.sla_due", "quality.alert.sla_overdue"],
            minimum_severity="info", recipient_roles=["owner"], recipient_user_ids=[],
            enabled=True, created_by_id=self.owner.id,
        ))
        self.db.commit()
        delivery_settings = Settings(_env_file=None, notification_master_key=_MASTER_KEY)

        result = execute_notification_delivery(
            outbox_id,
            session_factory=self.Session,
            adapter_factory=lambda db: NotificationChannelRouter(db, delivery_settings),
        )

        self.assertEqual(result, "sent")
        self.db.expire_all()
        inbox = self.db.query(InAppNotification).filter(
            InAppNotification.recipient_user_id == self.owner.id,
            InAppNotification.event_id == event_id,
        ).all()
        self.assertEqual(len(inbox), 1)


class TestDemoRelay(QualityAlertApiCase):
    def test_demo_alert_is_flagged_and_kept_out_of_default_view(self):
        """验收口径：演示循环触发的预警出现在预警中心并带演示标记。"""
        alert, created = service.relay_demo_alert(
            self.db, project_id=self.project.id, demo_config_id=uuid.uuid4(),
            source_type="model_risk", severity="critical", title="演示循环告警：Demo-1",
            evidence={"error_count": 60},
        )
        self.db.commit()
        self.assertTrue(created)
        self.assertTrue(alert.is_demo)
        self.assertEqual(alert.source_ref["kind"], "demo_loop")
        listed = self.client.get(
            f"/api/projects/{self.project.id}/quality-alerts", params={"include_demo": "true"},
        ).json()["items"]
        self.assertIn(str(alert.id), {item["id"] for item in listed})
        default = self.client.get(
            f"/api/projects/{self.project.id}/quality-alerts",
        ).json()["items"]
        self.assertNotIn(str(alert.id), {item["id"] for item in default})
