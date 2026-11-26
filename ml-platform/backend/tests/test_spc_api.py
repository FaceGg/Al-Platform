"""补齐路线第一批 F4：SPC 分析接口（B1-06，技术方案 §9C.3，D36–D37）。

验收口径：
- 两种取数来源在结果中可区分；规格限取场景规格定义，手工录入逐项覆盖并标明来源；
- 缺规格限时能力指数留空不报错；组内 σ 无法得到时如实标明回退；
- SPC 页点位与预警中心的对应预警可互相跳转：判异点带样本键；登记后预警可追溯回分析参数。
"""
import unittest
from datetime import datetime, timedelta

from app.models.data_version import DatasetSchemaColumn
from app.models.inference_result import InferenceResult
from app.models.quality_alerts import QualityAlert, QualityAlertEvent, QualitySpcBaseline
from app.models.quality_domain import QualitySpecLimit
from tests.quality_alert_fixtures import QualityAlertApiCase


class TestSpcApi(QualityAlertApiCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # 40 个点：10.0 / 10.5 / 11.0 / 11.5 循环，最后一个点是 20.0 的离群值
        cls.values = [10.0 + (index % 4) * 0.5 for index in range(40)]
        cls.values[-1] = 20.0
        cls.dataset = QualityAlertApiCase.make_dataset_version(
            cls,
            [{"vin": f"spc-{index}", "force": value, "quality": int(value > 19)}
             for index, value in enumerate(cls.values)],
        )
        # 字段清单读的是数据集的列定义表；通用夹具只造样本行，这里补上列定义
        for position, (name, dtype) in enumerate(
            [("vin", "string"), ("force", "float64"), ("quality", "int64")]
        ):
            cls.db.add(DatasetSchemaColumn(
                dataset_version_id=cls.dataset.id, name=name, position=position,
                dtype=dtype, nullable=False,
            ))
        cls.db.commit()

    def _base(self):
        return f"/api/projects/{self.project.id}/spc"

    def setUp(self):
        """场景是类级夹具：每条用例前清掉本用例家族写入的规格、基线、推理明细与预警，
        否则 (场景, 字段, 统计量) 的唯一约束会撞。"""
        super().setUp()
        alert_ids = [row.id for row in self.db.query(QualityAlert.id).filter(
            QualityAlert.project_id == self.project.id,
        )]
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
        for model in (QualitySpecLimit, QualitySpcBaseline):
            self.db.query(model).filter(model.scene_id == self.scene.id).delete(
                synchronize_session="fetch",
            )
        self.db.query(InferenceResult).filter(
            InferenceResult.project_id == self.project.id,
        ).delete(synchronize_session="fetch")
        self.db.commit()

    def _analyze(self, **payload):
        return self.client.post(f"{self._base()}/analyze", json=payload)

    def test_fields_for_both_sources(self):
        dataset_fields = self.client.get(f"{self._base()}/fields", params={
            "source": "dataset", "dataset_version_id": str(self.dataset.id),
        }).json()["fields"]
        force = next(item for item in dataset_fields if item["name"] == "force")
        self.assertTrue(force["numeric"])
        inference = self.client.get(f"{self._base()}/fields", params={"source": "inference"}).json()
        self.assertEqual([item["name"] for item in inference["fields"]],
                         ["predicted_value", "anomaly_score", "probability"])

    def test_dataset_source_i_mr_with_scene_spec(self):
        self.db.add(QualitySpecLimit(
            scene_id=self.scene.id, field="force", statistic="value",
            usl=12.0, lsl=9.0, target=10.75, unit="kN",
        ))
        self.db.commit()
        response = self._analyze(
            source="dataset", dataset_version_id=str(self.dataset.id), field="force",
            chart="i_mr", scene_id=str(self.scene.id),
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual((body["source"], body["sample_count"]), ("dataset", 40))
        self.assertEqual(body["spec"]["source"], "scene_spec")
        self.assertEqual(body["spec"]["usl"], 12.0)
        # 离群点被判异，且带样本键——SPC 页点位可跳回样本
        last = body["charts"]["i"]["points"][-1]
        self.assertEqual(last["violations"], [1])
        self.assertEqual(last["sample_key"], "spc-39")
        self.assertEqual(body["violations"][0]["sample_key"], "spc-39")
        # 没有冻结基线、也不是子群图：组内 σ 回退整体 σ，结果里如实写明
        self.assertEqual(body["capability"]["within_sigma_source"], "overall")
        self.assertTrue(any("整体标准差估计" in note for note in body["notes"]), body["notes"])
        self.assertEqual(body["spec"]["usl"], 12.0)

    def test_manual_limits_override_scene_spec_per_limit(self):
        self.db.add(QualitySpecLimit(
            scene_id=self.scene.id, field="force", statistic="value", usl=12.0, lsl=9.0,
        ))
        self.db.commit()
        body = self._analyze(
            source="dataset", dataset_version_id=str(self.dataset.id), field="force",
            chart="i_mr", scene_id=str(self.scene.id), usl=15.0,
        ).json()
        self.assertEqual(body["spec"]["source"], "scene_spec+manual")
        self.assertEqual((body["spec"]["usl"], body["spec"]["lsl"]), (15.0, 9.0))

    def test_missing_spec_limits_leave_capability_blank_without_error(self):
        body = self._analyze(
            source="dataset", dataset_version_id=str(self.dataset.id), field="force",
            chart="i_mr", use_scene_spec=False,
        ).json()
        self.assertEqual(body["spec"]["source"], "none")
        for name in ("cp", "cpk", "pp", "ppk", "ppm"):
            self.assertIsNone(body["capability"][name], name)
        self.assertTrue(any("未提供规格限" in note for note in body["notes"]))

    def test_frozen_baseline_supplies_within_sigma(self):
        self.db.add(QualitySpecLimit(
            scene_id=self.scene.id, field="force", statistic="value", usl=12.0, lsl=9.0,
        ))
        self.db.add(QualitySpcBaseline(
            project_id=self.project.id, scene_id=self.scene.id, field="force",
            statistic="value", center=10.75, sigma=0.5, sample_count=30,
            window_start=datetime.utcnow() - timedelta(days=1), window_end=datetime.utcnow(),
            reference={}, version=2, is_active=True,
        ))
        self.db.commit()
        body = self._analyze(
            source="dataset", dataset_version_id=str(self.dataset.id), field="force",
            chart="i_mr", scene_id=str(self.scene.id),
        ).json()
        self.assertEqual(body["capability"]["within_sigma_source"], "baseline")
        self.assertAlmostEqual(body["capability"]["cp"], 3.0 / (6 * 0.5), places=9)
        self.assertTrue(any("冻结基线 v2" in note for note in body["notes"]), body["notes"])

    def test_xbar_r_drops_incomplete_trailing_subgroup(self):
        body = self._analyze(
            source="dataset", dataset_version_id=str(self.dataset.id), field="force",
            chart="xbar_r", subgroup_size=5,
        ).json()
        self.assertEqual(body["subgroup_count"], 8, "40 个点按 5 个一组正好 8 个完整子群")
        self.assertEqual(set(body["charts"]), {"xbar", "r"})
        self.assertEqual(len(body["charts"]["xbar"]["points"]), 8)
        self.assertEqual(body["capability"]["within_sigma_source"], "range")

    def test_raising_alerts_merges_repeated_analysis(self):
        payload = dict(
            source="dataset", dataset_version_id=str(self.dataset.id), field="force",
            chart="i_mr", raise_alerts=True,
        )
        first = self._analyze(**payload)
        self.assertEqual(first.status_code, 200, first.text)
        # I-MR 有两张图：单值图上的离群点与移动极差图上的大极差各成一组预警
        self.assertEqual(first.json()["alerts_raised"], 2)
        again = self._analyze(**payload).json()
        self.assertEqual(again["alerts_raised"], 0, "窗口内重复分析并入已有预警")
        self.db.expire_all()
        alerts = {
            alert.merge_key: alert
            for alert in self.db.query(QualityAlert).filter(
                QualityAlert.project_id == self.project.id,
                QualityAlert.source_type == "spc_violation",
            ).all()
        }
        self.assertEqual(
            set(alerts), {"spc:i_mr:force:i:1", "spc:i_mr:force:mr:1"},
        )
        self.assertTrue(all(alert.occurrence_count == 2 for alert in alerts.values()))
        # 预警带样本键与分析参数，可追溯回 SPC 页
        self.assertEqual(alerts["spc:i_mr:force:i:1"].sample_key, "spc-39")
        self.assertEqual(alerts["spc:i_mr:force:i:1"].evidence["rule"], "i:1")
        self.assertEqual(
            alerts["spc:i_mr:force:i:1"].source_ref,
            {"kind": "spc_analysis", "chart": "i_mr", "field": "force"},
        )

    def test_inference_source_and_attribute_chart(self):
        now = datetime.utcnow()
        # 30 个点：第一组（5 个）全是异常，其余正常。p_bar = 5/30，第一组占比 1.0
        # 远超 3σ 上限 0.667 → P 图上第一个点越限
        flags = [True] * 5 + [False] * 25
        for index, is_anomaly in enumerate(flags):
            self.db.add(InferenceResult(
                request_id=f"spc-inf-{index}", project_id=self.project.id, channel="online",
                scene_id=self.scene.id, station_id=self.station.id,
                anomaly_score=0.9 if is_anomaly else 0.1, is_anomaly=is_anomaly,
                sample_key=f"inf-{index}", occurred_at=now - timedelta(minutes=30 - index),
                expires_at=now + timedelta(days=1),
            ))
        self.db.commit()
        body = self._analyze(
            source="inference", field="anomaly_score", chart="i_mr",
            scene_id=str(self.scene.id),
        ).json()
        self.assertEqual((body["source"], body["sample_count"]), ("inference", 30))
        self.assertEqual(body["charts"]["i"]["points"][0]["sample_key"], "inf-0")
        p_chart = self._analyze(
            source="inference", field="anomaly_score", chart="p", subgroup_size=5,
            scene_id=str(self.scene.id),
        ).json()
        self.assertEqual(p_chart["subgroup_count"], 6)
        self.assertEqual([item["index"] for item in p_chart["violations"]], [0])
        self.assertEqual(p_chart["charts"]["p"]["points"][0]["value"], 1.0)

    def test_invalid_requests_are_rejected(self):
        base = {"source": "inference", "scene_id": str(self.scene.id)}
        rejected = self._analyze(**base, field="force")
        self.assertEqual(rejected.status_code, 422)
        self.assertEqual(rejected.json()["detail"]["code"], "SPC_INFERENCE_FIELD_INVALID")
        too_few = self._analyze(
            source="dataset", dataset_version_id=str(self.dataset.id), field="force",
            chart="xbar_r", subgroup_size=10, row_from=30,
        )
        self.assertEqual(too_few.status_code, 422)
        self.assertEqual(too_few.json()["detail"]["code"], "SPC_NOT_ENOUGH_SUBGROUPS")
        bad_size = self._analyze(source="dataset", dataset_version_id=str(self.dataset.id), field="force", subgroup_size=11)
        self.assertEqual(bad_size.status_code, 422)

    def test_permissions(self):
        payload = dict(source="dataset", dataset_version_id=str(self.dataset.id), field="force")
        self.act_as(self.viewer)
        self.assertEqual(self._analyze(**payload).status_code, 200, "只读成员可以做分析")
        self.assertEqual(self._analyze(**payload, raise_alerts=True).status_code, 403)


if __name__ == "__main__":
    unittest.main()
