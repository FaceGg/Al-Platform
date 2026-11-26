"""补齐路线第一批 F2a：SPC 基线冻结与判据链（E08 前移 / B1-02，技术方案 §9.3/§9.10）。

验收口径：
- 冻结基线可复算，所引用的样本可追溯（数据集版本 + 首末样本）；
- 重新冻结生成新版本，旧版本仍可查；样本 20–500，时段内恒定拒绝；
- 判据链绑定冻结基线：没有冻结基线时不产生 σ 类判据并给出提示；
- 修改规格定义后判据结果同步变化（全平台只有一份规格来源）。
"""
import uuid
from datetime import datetime

from app.models.data_version import DatasetVersion
from app.models.project import Project
from app.models.quality_alerts import QualitySpcBaseline
from app.models.quality_domain import QualitySpecLimit
from app.models.user import User
from app.services import quality_alerts as service
from tests.quality_alert_fixtures import QualityAlertApiCase


def _varying_rows(base, count, start_minute=0):
    """围绕 base 起伏的 force 序列（非常量），ts 逐分钟递增。"""
    return [
        {
            "vin": f"{base}-{index}", "force": base + (index % 4) * 0.5,
            "cond": "A" if index % 2 == 0 else "B",
            "ts": f"2026-11-01T00:{(start_minute + index) % 60:02d}:00Z",
        }
        for index in range(count)
    ]


class TestBaselineComputation(QualityAlertApiCase):
    def test_i_mr_matches_hand_computation(self):
        center, sigma = service.compute_i_mr([10.0, 11.0, 9.0, 10.0])
        self.assertAlmostEqual(center, 10.0)
        # 移动极差 1、2、1 → 均值 4/3；σ = 均值 / 1.128
        self.assertAlmostEqual(sigma, (4.0 / 3.0) / 1.128, places=9)

    def test_collect_applies_row_range_condition_and_time_window(self):
        version = self.make_dataset_version(_varying_rows(10.0, 40))
        values, reference = service.collect_baseline_values(
            self.db, dataset_version=version, field="force",
            condition_column="cond", condition_value="A",
            row_index_from=0, row_index_to=19,
        )
        # 行 0–19 里的偶数行（cond=A）共 10 个
        self.assertEqual(len(values), 10)
        self.assertEqual(values[0], 10.0)
        self.assertEqual(reference["first"], {"sample_id": "10.0-0", "row_index": 0})
        self.assertEqual(reference["last"], {"sample_id": "10.0-18", "row_index": 18})

        # 时间窗 00:02–00:08 → 行 2–8；未限定工况
        timed, timed_reference = service.collect_baseline_values(
            self.db, dataset_version=version, field="force", time_column="ts",
            time_from=datetime(2026, 11, 1, 0, 2), time_to=datetime(2026, 11, 1, 0, 8),
        )
        self.assertEqual(len(timed), 7)
        self.assertEqual(timed_reference["first"]["row_index"], 2)
        self.assertEqual(timed_reference["last"]["row_index"], 8)

    def test_collect_skips_non_numeric_values_and_caps_the_window(self):
        rows = _varying_rows(10.0, 30)
        rows[3]["force"] = "not-a-number"
        rows[5]["force"] = None
        version = self.make_dataset_version(rows)
        values, _ = service.collect_baseline_values(self.db, dataset_version=version, field="force")
        self.assertEqual(len(values), 28)

        wide = self.make_dataset_version(_varying_rows(5.0, 501))
        with self.assertRaisesRegex(ValueError, "SPC_BASELINE_TOO_MANY_SAMPLES"):
            service.collect_baseline_values(self.db, dataset_version=wide, field="force")


class TestBaselineFreezeApi(QualityAlertApiCase):
    def _url(self, **params):
        query = "&".join(f"{key}={value}" for key, value in params.items())
        return f"/api/projects/{self.project.id}/quality-scenes/{self.scene.id}/spc-baselines" + (
            f"?{query}" if query else ""
        )

    def _freeze(self, version, field="force", **extra):
        return self.client.post(self._url(), json={
            "dataset_version_id": str(version.id), "field": field, **extra,
        })

    def test_freeze_is_reproducible_and_versions_keep_history(self):
        first_version = self.make_dataset_version(_varying_rows(10.0, 30))
        first = self._freeze(first_version)
        self.assertEqual(first.status_code, 200, first.text)
        body = first.json()
        self.assertEqual(body["version"], 1)
        self.assertTrue(body["is_active"])
        self.assertEqual(body["sample_count"], 30)
        # 复算：与直接对同一批数据做 I-MR 的结果一致
        expected_center, expected_sigma = service.compute_i_mr(
            [10.0 + (index % 4) * 0.5 for index in range(30)]
        )
        self.assertAlmostEqual(body["center"], expected_center, places=9)
        self.assertAlmostEqual(body["sigma"], expected_sigma, places=9)
        # 追溯：数据集版本与首末样本
        self.assertEqual(body["reference"]["dataset_version_id"], str(first_version.id))
        self.assertEqual(body["reference"]["first"]["sample_id"], "10.0-0")
        self.assertEqual(body["reference"]["last"]["sample_id"], "10.0-29")

        second_version = self.make_dataset_version(_varying_rows(20.0, 30))
        second = self._freeze(second_version).json()
        self.assertEqual(second["version"], 2)
        self.assertTrue(second["is_active"])

        history = self.client.get(self._url(field="force")).json()["items"]
        self.assertEqual([item["version"] for item in history], [2, 1])
        self.assertEqual([item["is_active"] for item in history], [True, False],
                         "旧版本失效但保留可查（验收口径）")
        active = self.client.get(self._url(field="force", active_only="true")).json()["items"]
        self.assertEqual([item["version"] for item in active], [2])

    def test_freeze_rejects_invalid_windows(self):
        cases = [
            # (字段名, 行, 期望错误码)
            ("force-short", _varying_rows(10.0, 10), "SPC_BASELINE_SAMPLE_COUNT_INVALID"),
            ("force-constant", [
                {"vin": f"c-{index}", "force-constant": 7.0} for index in range(30)
            ], "SPC_BASELINE_CONSTANT_WINDOW"),
            ("force-wide", _varying_rows(5.0, 501), "SPC_BASELINE_TOO_MANY_SAMPLES"),
        ]
        for field, rows, expected_code in cases:
            with self.subTest(code=expected_code):
                for row in rows:
                    if "force" in row:
                        row[field] = row.pop("force")
                version = self.make_dataset_version(rows)
                rejected = self._freeze(version, field=field)
                self.assertEqual(rejected.status_code, 422, rejected.text)
                self.assertEqual(rejected.json()["detail"]["code"], expected_code)
                # 被拒的请求不留半截基线
                self.assertEqual(self.db.query(QualitySpcBaseline).filter(
                    QualitySpcBaseline.field == field,
                ).count(), 0)

    def test_time_window_needs_the_scene_time_role(self):
        self.scene.field_roles = {"sample_key": "vin"}
        self.db.commit()
        version = self.make_dataset_version(_varying_rows(10.0, 30))
        rejected = self._freeze(version, time_from="2026-11-01T00:00:00", time_to="2026-11-01T00:30:00")
        self.assertEqual(rejected.status_code, 422)
        self.assertEqual(rejected.json()["detail"]["code"], "SCENE_TIME_ROLE_REQUIRED")

    def test_dataset_version_must_belong_to_the_project(self):
        stranger = User(username=f"baseline-other-{uuid.uuid4().hex[:6]}", password_hash="hash")
        self.db.add(stranger)
        self.db.flush()
        other_project = Project(name="Baseline other project", owner_id=stranger.id)
        self.db.add(other_project)
        self.db.flush()
        other_version = DatasetVersion(
            project_id=other_project.id, operator_id=stranger.id, version=1,
            status="ready", row_count=1, column_count=1,
            content_hash=uuid.uuid4().hex, schema_hash=uuid.uuid4().hex,
        )
        self.db.add(other_version)
        self.db.commit()
        # 用本项目的场景去冻别的项目的数据集版本 → 拒绝
        response = self.client.post(self._url(), json={
            "dataset_version_id": str(other_version.id), "field": "force",
        })
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"]["code"], "DATASET_VERSION_NOT_FOUND")

    def test_freeze_needs_manage_permission(self):
        version = self.make_dataset_version(_varying_rows(10.0, 30))
        self.act_as(self.operator)
        self.assertEqual(self._freeze(version).status_code, 403)
        self.act_as(self.viewer)
        self.assertEqual(
            self.client.get(self._url()).status_code, 200, "只读成员可查基线",
        )


class TestCriteriaChain(QualityAlertApiCase):
    """判据优先级链：规格超限 → 3σ 超限 → 2σ 偏离 → 基线偏离 30%。"""

    def _alert(self, recorded_value, field="force"):
        return self.make_alert(
            source_type="param_exceed", merge_key=f"crit-{self.case_key}-{recorded_value}",
            evidence={"kind": "param_exceed", "field": field, "recorded_value": recorded_value},
        )

    def _chain(self, alert):
        response = self.client.get(
            f"/api/projects/{self.project.id}/quality-alerts/{alert.id}/criteria",
        )
        self.assertEqual(response.status_code, 200, response.text)
        return {item["criterion"]: item for item in response.json()["criteria"]}

    def _baseline(self, center=10.0, sigma=0.5, field="force"):
        self.db.add(QualitySpcBaseline(
            project_id=self.project.id, scene_id=self.scene.id, field=field,
            statistic="value", center=center, sigma=sigma, sample_count=30,
            window_start=datetime(2026, 11, 1), window_end=datetime(2026, 11, 2),
            reference={}, version=1, is_active=True,
        ))
        self.db.commit()

    def test_without_baseline_sigma_criteria_are_skipped_with_a_hint(self):
        chain = self._chain(self._alert(14.0, field="force-no-baseline"))
        self.assertEqual(chain["spec_exceed"]["status"], "skipped")
        for criterion in ("sigma_3", "sigma_2", "baseline_deviation_30"):
            self.assertEqual(chain[criterion]["status"], "skipped", criterion)
            self.assertIn("未冻结基线", chain[criterion]["detail"])

    def test_chain_hits_in_priority_order(self):
        # 规格与基线按字段唯一（同一字段只能有一条规格），用例各用各的字段名
        field = "force-chain"
        self.db.add(QualitySpecLimit(
            scene_id=self.scene.id, field=field, statistic="value",
            usl=12.0, lsl=4.0, unit="kN",
        ))
        self.db.commit()
        self._baseline(center=10.0, sigma=0.5, field=field)

        blown = self._chain(self._alert(14.0, field=field))
        self.assertEqual([blown[key]["status"] for key in (
            "spec_exceed", "sigma_3", "sigma_2", "baseline_deviation_30",
        )], ["hit", "hit", "hit", "hit"])
        self.assertEqual(blown["sigma_3"]["detail"]["baseline"]["version"], 1)

        drifting = self._chain(self._alert(11.2, field=field))
        self.assertEqual([drifting[key]["status"] for key in (
            "spec_exceed", "sigma_3", "sigma_2", "baseline_deviation_30",
        )], ["pass", "pass", "hit", "pass"])

        fine = self._chain(self._alert(10.3, field=field))
        self.assertEqual({fine[key]["status"] for key in fine}, {"pass"})

    def test_spec_change_is_reflected_in_recomputed_chain(self):
        """验收口径：修改规格定义后判据结果同步变化（规格只有一份来源）。"""
        field = "force-spec-change"
        spec = QualitySpecLimit(
            scene_id=self.scene.id, field=field, statistic="value", usl=12.0,
        )
        self.db.add(spec)
        self.db.commit()
        alert = self._alert(14.0, field=field)
        self.assertEqual(self._chain(alert)["spec_exceed"]["status"], "hit")
        spec.usl = 20.0
        self.db.commit()
        recomputed = self._chain(alert)["spec_exceed"]
        self.assertEqual(recomputed["status"], "pass")
        self.assertEqual(recomputed["detail"]["usl"], 20.0)

    def test_model_risk_alert_without_a_field_skips_numeric_criteria(self):
        alert = self.make_alert(evidence={"kind": "model_risk", "score": 0.9})
        chain = self._chain(alert)
        self.assertEqual({item["status"] for item in chain.values()}, {"skipped"})
