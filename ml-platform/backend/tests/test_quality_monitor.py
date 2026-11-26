"""补齐路线第一批 F3：监控驾驶的聚合口径与接口（B1-03/04/05，技术方案 §9B）。

验收口径：
- KPI 数字与下钻列表严格一致（同一聚合视图单测锁死）；
- 四级范围逐级收窄时数字单调不增；
- 演示数据不进任何默认聚合；
- 陈旧数据横幅三态；处置运营三指标与处置单明细同源复算；
- 推送：连接即得快照，新增预警在一个轮询周期内出现在流里；
- 确认收到 / 呼叫质量人员留痕；演示态常驻标识的数据源。
"""
import json
import unittest
import uuid
from datetime import datetime, timedelta

from app.models.access import AuditEvent
from app.models.compute import EdgeDevice
from app.models.demo_loop import DemoLoopConfig
from app.models.inference_result import InferenceResult, InferenceResultBucket
from app.models.notifications import InAppNotification
from app.models.platform_option import PlatformOption
from app.models.quality_alerts import QualityAlert, QualityAlertEvent
from app.models.quality_domain import QualityStation
from app.models.user import User
from app.api import quality_monitor as monitor_api
from app.services import quality_aggregates as agg
from tests.quality_alert_fixtures import QualityAlertApiCase


class TestQualityMonitor(QualityAlertApiCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        tag = uuid.uuid4().hex[:6]
        cls.station_b = QualityStation(
            scene_id=cls.scene.id, code=f"MB-{tag}", name="乙工位",
            factory="F1", workshop="W1", production_line="L1",
        )
        cls.station_c = QualityStation(
            scene_id=cls.scene.id, code=f"MC-{tag}", name="丙工位",
            factory="F2", workshop="W2", production_line="L2",
        )
        cls.station_d = QualityStation(
            scene_id=cls.scene.id, code=f"MD-{tag}", name="丁工位",
            factory="F1", workshop="W1", production_line="L9",
        )
        cls.db.add_all([cls.station_b, cls.station_c, cls.station_d])
        cls.db.commit()

    def setUp(self):
        """聚合口径的断言都是「本项目全部数据」的绝对数字：每条用例前清空本项目的建设数据。

        同类用例共用一个内存库，前一条用例留下的聚合桶和预警会把整项目的数字累加。
        """
        super().setUp()
        alert_ids = [
            row.id for row in self.db.query(QualityAlert.id).filter(
                QualityAlert.project_id == self.project.id,
            )
        ]
        if alert_ids:
            self.db.query(QualityAlertEvent).filter(
                QualityAlertEvent.alert_id.in_(alert_ids),
            ).delete(synchronize_session="fetch")
            self.db.query(InferenceResult).filter(
                InferenceResult.alert_id.in_(alert_ids),
            ).update({"alert_id": None}, synchronize_session=False)
            self.db.query(QualityAlert).filter(
                QualityAlert.id.in_(alert_ids),
            ).delete(synchronize_session="fetch")
        for model in (InferenceResultBucket, InferenceResult, InAppNotification,
                      AuditEvent, DemoLoopConfig):
            self.db.query(model).filter(model.project_id == self.project.id).delete(
                synchronize_session="fetch",
            )
        self.db.query(PlatformOption).filter(
            PlatformOption.key == agg.project_option_key(agg.OPTION_NG_VOCABULARY, self.project.id),
        ).delete(synchronize_session="fetch")
        for station in (self.station, self.station_b, self.station_c, self.station_d):
            station.edge_device_id = None
            station.responsible_user_id = None
        self.db.commit()

    def _base(self):
        return f"/api/projects/{self.project.id}/quality-monitor"

    def _bucket(self, station, hour, total, ok, anomaly):
        """聚合桶；工况值带用例键，满足 (小时, 场景, 工位, 工况) 唯一约束且不影响聚合。"""
        self.db.add(InferenceResultBucket(
            bucket_start=hour, project_id=self.project.id, scene_id=self.scene.id,
            station_id=station.id, condition_value=f"c-{self.case_key}",
            total=total, ok_count=ok, anomaly_count=anomaly,
        ))

    def _alert(self, index, **overrides):
        overrides.setdefault("merge_key", f"mon-{self.case_key}-{index}")
        return self.make_alert(**overrides)

    def _dashboard(self, **params):
        response = self.client.get(f"{self._base()}/dashboard", params=params)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def _seed_common(self):
        """甲、乙工位属 F1/W1/L1，丙工位属 F2/W2/L2。产量：甲 15、丙 20。"""
        hour = datetime.utcnow().replace(minute=0, second=0, microsecond=0)
        self._bucket(self.station, hour - timedelta(hours=1), 10, 7, 3)
        self._bucket(self.station, hour - timedelta(hours=2), 5, 5, 0)
        self._bucket(self.station_c, hour - timedelta(hours=1), 20, 15, 5)
        self._alert(1, station_id=self.station.id, severity="high")
        self._alert(2, station_id=self.station.id)
        self._alert(3, station_id=self.station.id, status="closed", resolution="confirmed_issue",
                    occurrence_count=3, closed_at=datetime.utcnow())
        self._alert(4, station_id=self.station.id, status="closed", resolution="other",
                    closed_at=datetime.utcnow())
        self._alert(5, station_id=self.station_b.id, severity="critical")
        # 演示预警：不得进入任何默认聚合
        self._alert(6, station_id=self.station.id, is_demo=True, merge_key=f"demo-{self.case_key}")
        self.db.commit()

    def test_kpi_equals_station_drilldown_sum_and_trend_total(self):
        self._seed_common()
        whole = self._dashboard()
        self.assertEqual(whole["production"], {"total": 35, "ok": 27, "anomaly": 8})
        self.assertEqual(whole["alerts"]["alerts_in_window"], 5)
        self.assertEqual(whole["alerts"]["open"], 3)
        self.assertEqual(whole["alerts"]["high_risk"], 2)
        self.assertEqual(whole["alerts"]["confirmed_ng"], 3, "确认 NG 按发生次数计")
        self.assertEqual(whole["alerts"]["closed_in_window"], 2)
        self.assertEqual(whole["alerts"]["hit_rate"], 0.5)
        # 趋势页同窗合计 = 驾驶舱 KPI
        self.assertEqual(whole["trend"]["totals"]["total"], 35)
        self.assertEqual(whole["trend"]["totals"]["confirmed_ng"], 3)
        # 下钻：各工位之和 = 整体
        parts = {
            station.code: self._dashboard(station_id=str(station.id))
            for station in (self.station, self.station_b, self.station_c)
        }
        self.assertEqual(sum(part["production"]["total"] for part in parts.values()), 35)
        self.assertEqual(sum(part["alerts"]["open"] for part in parts.values()), 3)
        self.assertEqual(sum(part["alerts"]["confirmed_ng"] for part in parts.values()), 3)
        self.assertEqual(parts[self.station.code]["production"]["total"], 15)
        self.assertEqual(parts[self.station_b.code]["production"]["total"], 0)

    def test_scope_narrows_monotonically_through_four_levels(self):
        self._seed_common()
        totals = [
            self._dashboard()["production"]["total"],
            self._dashboard(factory="F1")["production"]["total"],
            self._dashboard(factory="F1", workshop="W1")["production"]["total"],
            self._dashboard(factory="F1", workshop="W1", production_line="L1")["production"]["total"],
            self._dashboard(factory="F1", workshop="W1", production_line="L1",
                            station_id=str(self.station.id))["production"]["total"],
        ]
        self.assertEqual(totals, [35, 15, 15, 15, 15])
        # 另一个工厂的数字与整体对得上：F1 15 + F2 20 = 35
        self.assertEqual(self._dashboard(factory="F2")["production"]["total"], 20)
        self.assertEqual(self._dashboard(scene_id=str(self.scene.id))["production"]["total"], 35)
        options = self.client.get(f"{self._base()}/scope-options").json()
        self.assertEqual(options["factory"], ["F1", "F2"])
        self.assertIn("L2", options["production_line"])

    def test_demo_alerts_never_enter_default_aggregates(self):
        self._seed_common()
        pareto = self.client.get(f"{self._base()}/trends", params={"dimension": "station"}).json()["pareto"]
        self.assertEqual(pareto["total"], 7, "发生次数之和：甲 1+1+3+1、乙 1；演示预警不计")
        self.assertEqual(sum(item["count"] for item in pareto["items"]), pareto["total"])
        self.assertEqual(pareto["items"][-1]["cumulative"], 1.0)

    def test_stale_banner_three_states(self):
        now = datetime.utcnow()
        hour = now.replace(minute=0, second=0, microsecond=0)
        self._bucket(self.station, hour - timedelta(hours=1), 3, 3, 0)
        self._bucket(self.station_d, hour - timedelta(hours=30), 4, 4, 0)
        self.db.commit()
        fresh = self._dashboard(station_id=str(self.station.id))["stale"]
        self.assertFalse(fresh["stale"])
        old = self._dashboard(station_id=str(self.station_d.id))["stale"]
        self.assertTrue(old["stale"])
        self.assertGreater(old["hours"], 24)
        never = self._dashboard(station_id=str(self.station_c.id))["stale"]
        self.assertTrue(never["stale"] and never["never_produced"])
        self.assertIsNone(never["last_production_at"])

    def test_disposition_ops_match_disposition_records(self):
        now = datetime.utcnow()
        created = now - timedelta(hours=2)
        self._alert(1, status="closed", resolution="confirmed_issue",
                    created_at=created, last_event_at=created, closed_at=now)
        self._alert(2, status="closed", resolution="other",
                    created_at=created, last_event_at=created, closed_at=now)
        self._alert(3)
        hour = now.replace(minute=0, second=0, microsecond=0)
        self._bucket(self.station, hour - timedelta(hours=1), 35, 30, 5)
        # 首次处理时间：确认异常的那条 60 分钟、另一条 20 分钟（都落在时间窗内）
        for alert in self.db.query(QualityAlert).filter(
            QualityAlert.merge_key.like(f"mon-{self.case_key}-%"),
            QualityAlert.status == "closed",
        ).all():
            minutes = 60 if alert.resolution == "confirmed_issue" else 20
            alert.first_ack_at = alert.created_at + timedelta(minutes=minutes)
        self.db.commit()
        ops = self._dashboard()["disposition_ops"]
        self.assertAlmostEqual(ops["per_thousand"], 2 / 35 * 1000, places=9)
        self.assertEqual(ops["mean_first_ack_seconds"], 2400.0)
        self.assertEqual(ops["closure_rate"], 2 / 3, "窗内产生 3 条、已关闭 2 条")

    def test_pareto_by_defect_maps_labels_through_ng_vocabulary(self):
        self._alert(1, evidence={"kind": "model_risk", "predicted_label": "spatter"}, occurrence_count=2)
        self._alert(2, evidence={"kind": "model_risk", "predicted_label": "porosity"}, occurrence_count=1)
        self._alert(3, evidence={"kind": "model_risk"})
        self.db.commit()
        saved = self.client.put(f"{self._base()}/ng-vocabulary", json={
            "vocabulary": {"spatter": "飞溅", "porosity": "气孔"},
        })
        self.assertEqual(saved.status_code, 200, saved.text)
        trends = self.client.get(f"{self._base()}/trends", params={"dimension": "defect"}).json()
        items = trends["pareto"]["items"]
        self.assertEqual(trends["pareto"]["total"], 4)
        self.assertEqual((items[0]["label"], items[0]["count"]), ("飞溅", 2))
        # 并列项按字典序，这里只断言集合与累计；未登记词表的标签归「未标注预测标签」单列
        self.assertEqual({item["label"] for item in items}, {"飞溅", "气孔", "未标注预测标签"})
        self.assertEqual([item["count"] for item in items], [2, 1, 1])
        self.assertEqual(items[-1]["cumulative"], 1.0)
        self.assertEqual(trends["ng_vocabulary"], {"spatter": "飞溅", "porosity": "气孔"})
        self.act_as(self.operator)
        self.assertEqual(self.client.put(f"{self._base()}/ng-vocabulary", json={"vocabulary": {"a": "b"}}).status_code, 403)

    def test_station_cards_reflect_latest_result_shift_and_device_heartbeat(self):
        now = datetime.utcnow()
        shift_start, shift_label = agg.current_shift_start(now, None)
        self._bucket(self.station, shift_start.replace(minute=0, second=0, microsecond=0), 12, 10, 2)
        offline = EdgeDevice(name=f"off-{self.case_key}", owner_id=self.owner.id,
                             last_heartbeat=now - timedelta(minutes=30))
        online = EdgeDevice(name=f"on-{self.case_key}", owner_id=self.owner.id, last_heartbeat=now)
        self.db.add_all([offline, online])
        self.db.flush()
        self.station.edge_device_id = online.id
        self.station_b.edge_device_id = offline.id
        self.db.add(InferenceResult(
            request_id=f"mon-{self.case_key}", project_id=self.project.id, channel="online",
            station_id=self.station.id, product_code="P-1", batch_no="B-9", shift=shift_label,
            is_anomaly=True, anomaly_score=0.91, occurred_at=now, expires_at=now + timedelta(days=1),
        ))
        self._alert(1, station_id=self.station.id, severity="high")
        self.db.commit()
        body = self.client.get(f"{self._base()}/stations").json()
        self.assertEqual(body["shift"]["label"], shift_label)
        cards = {card["code"]: card for card in body["cards"]}
        mine = cards[self.station.code]
        self.assertEqual((mine["product"], mine["batch"], mine["shift"]), ("P-1", "B-9", shift_label))
        self.assertEqual((mine["result"], mine["score"]), ("anomaly", 0.91))
        self.assertEqual((mine["shift_total"], mine["shift_anomaly"]), (12, 2))
        self.assertEqual(mine["open_alerts"], 1)
        self.assertEqual(mine["latest_alert"]["severity"], "high")
        self.assertTrue(mine["device"]["online"])
        self.assertFalse(cards[self.station_b.code]["device"]["online"], "心跳过期 = 离线")
        lines = {node["title"]: node for node in body["tree"]}
        self.assertEqual(len(lines["L1"]["children"]), 2, "产线 / 工位 / 设备三级树取自工位归属")
        self.assertIsNone(lines["L2"]["children"][0]["device"])

    def test_stream_sends_snapshot_then_new_alert_events_within_a_tick(self):
        self._alert(1, station_id=self.station.id)
        stream = monitor_api.monitor_event_stream(
            self.project.id, agg.MonitorScope(), session_factory=self.Session,
            poll_seconds=0, heartbeat_seconds=3600, max_ticks=1, sleep=lambda _seconds: None,
        )
        first = json.loads(next(stream)[len("data: "):])
        self.assertEqual(first["type"], "snapshot")
        self.assertEqual(first["dashboard"]["alerts"]["open"], 1)
        # 两次推送之间产生一条新预警并确认另一条
        self._alert(2, station_id=self.station.id, severity="critical")
        second = json.loads(next(stream)[len("data: "):])
        self.assertEqual(second["type"], "alerts")
        self.assertIn("created", {event["action"] for event in second["events"]})
        self.assertEqual(second["counts"], {"open": 2, "high_risk": 1})

    def test_stream_endpoint_is_scoped_and_uses_event_stream(self):
        def finite(project_id, scope):
            yield monitor_api._sse({"type": "snapshot", "dashboard": {"alerts": {"open": 0}}})

        original = monitor_api.monitor_event_stream
        monitor_api.monitor_event_stream = finite
        try:
            # 后续请求也必须落在替换窗口内：真实流是无限的，直接请求会挂住
            response = self.client.get(f"{self._base()}/stream")
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.headers["content-type"].startswith("text/event-stream"))
            self.assertIn('"type": "snapshot"', response.text)
            self.act_as(self.viewer)
            viewer = self.client.get(f"{self._base()}/stream")
            self.assertEqual(viewer.status_code, 200, "只读成员可以订阅推送")
        finally:
            monitor_api.monitor_event_stream = original

    def test_ack_received_confirms_open_alerts_of_that_station_only(self):
        self._alert(1, station_id=self.station.id)
        self._alert(2, station_id=self.station.id, severity="high")
        self._alert(3, station_id=self.station_b.id)
        url = f"/api/projects/{self.project.id}/quality-stations/{self.station.id}/ack-received"
        self.act_as(self.operator)
        response = self.client.post(url)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["acknowledged"], 2)
        self.db.expire_all()
        station_alerts = self.db.query(QualityAlert).filter(
            QualityAlert.station_id == self.station.id,
            QualityAlert.merge_key.like(f"mon-{self.case_key}-%"),
        ).all()
        self.assertEqual({alert.status for alert in station_alerts}, {"acknowledged"})
        self.assertEqual({alert.assigned_to_id for alert in station_alerts}, {self.operator.id})
        other = self.db.query(QualityAlert).filter(
            QualityAlert.station_id == self.station_b.id,
            QualityAlert.merge_key.like(f"mon-{self.case_key}-%"),
        ).one()
        self.assertEqual(other.status, "open")
        audited = {row.action for row in self.db.query(AuditEvent).filter(
            AuditEvent.project_id == self.project.id, AuditEvent.result == "success",
        ).all()}
        self.assertIn("quality.station.ack_received", audited)

    def test_call_quality_notifies_owner_and_station_responsible(self):
        self.station.responsible_user_id = self.operator.id
        self.db.commit()
        before = self.db.query(InAppNotification).count()
        url = f"/api/projects/{self.project.id}/quality-stations/{self.station.id}/call-quality"
        response = self.client.post(url, json={"reason": "连续三件飞溅，请到场确认"})
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertTrue(body["responsible_notified"])
        self.db.expire_all()
        notices = self.db.query(InAppNotification).filter(
            InAppNotification.event_type == "quality.station.call",
        ).all()
        self.assertEqual({row.recipient_user_id for row in notices}, {self.owner.id, self.operator.id})
        self.assertEqual(len(notices), body["notified"] + 1)
        self.assertGreaterEqual(len(notices), 2)
        self.assertEqual(self.client.post(url, json={"reason": "x"}).status_code, 422)
        self.assertEqual(self.client.post(
            f"/api/projects/{self.project.id}/quality-stations/{uuid.uuid4()}/call-quality",
            json={"reason": "查无此工位"},
        ).status_code, 404)
        self.assertGreater(self.db.query(InAppNotification).count(), before)

    def test_demo_presence_lists_accessible_projects_with_demo_configs(self):
        self.assertFalse(self.client.get("/api/demo-loop/presence").json()["present"])
        self.db.add(DemoLoopConfig(project_id=self.project.id))
        self.db.commit()
        body = self.client.get("/api/demo-loop/presence").json()
        self.assertTrue(body["present"])
        self.assertEqual([item["id"] for item in body["projects"]], [str(self.project.id)])
        stranger = User(username=f"mon-stranger-{uuid.uuid4().hex[:6]}", password_hash="hash")
        self.db.add(stranger)
        self.db.commit()
        self.act_as(stranger)
        self.assertFalse(self.client.get("/api/demo-loop/presence").json()["present"])


if __name__ == "__main__":
    unittest.main()
