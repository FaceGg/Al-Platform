"""补齐路线第一批 F2a：SOP 版本化（E07，技术方案 §9.4/§9.10）。

验收口径：SOP 按编号、适用工况、生效时间版本化，含三类处置指引；处置单
快照记录的是当时生效的 SOP 版本（快照本身的不可变性见 test_quality_alerts）。
"""
import uuid

from app.models.quality_domain import QualityScene
from tests.quality_alert_fixtures import QualityAlertApiCase

_GUIDANCE = {
    "spec_exceed": ["停机检查", "更换电极"],
    "spc_exceed": ["加严抽检"],
    "ai_risk": ["人工复判"],
}


class TestSopVersioning(QualityAlertApiCase):
    def _sops_url(self, **params):
        query = "&".join(f"{key}={value}" for key, value in params.items())
        return f"/api/projects/{self.project.id}/quality-sops" + (f"?{query}" if query else "")

    def _create(self, code, condition_value=None, scene_id="default", title="电极更换"):
        return self.client.post(self._sops_url(), json={
            "code": code, "title": title, "content": _GUIDANCE,
            "scene_id": str(self.scene.id) if scene_id == "default" else scene_id,
            "condition_value": condition_value,
        })

    def test_new_version_retires_the_previous_one_and_history_stays_listed(self):
        code = f"SOP-{self.case_key}"
        first = self._create(code)
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json()["version"], 1)
        self.assertTrue(first.json()["is_active"])
        self.assertEqual(first.json()["content"], _GUIDANCE, "三类处置指引原样保存")

        second = self._create(code, title="电极更换（修订）")
        self.assertEqual(second.json()["version"], 2)

        history = self.client.get(self._sops_url(code=code)).json()["items"]
        self.assertEqual([item["version"] for item in history], [2, 1])
        self.assertEqual([item["is_active"] for item in history], [True, False])
        self.assertIsNotNone(next(item for item in history if item["version"] == 1)["retired_at"])
        active = self.client.get(self._sops_url(code=code, active_only="true")).json()["items"]
        self.assertEqual([item["version"] for item in active], [2])
        self.assertEqual(active[0]["title"], "电极更换（修订）")

    def test_versions_are_scoped_per_condition(self):
        code = f"SOP-C-{self.case_key}"
        self.assertEqual(self._create(code, condition_value="厚板").json()["version"], 1)
        # 另一工况同编号独立从 1 起，不退役前一工况的版本
        thick = self._create(code, condition_value="厚板").json()
        thin = self._create(code, condition_value="薄板").json()
        self.assertEqual((thick["version"], thin["version"]), (2, 1))
        active = self.client.get(self._sops_url(code=code, active_only="true")).json()["items"]
        self.assertEqual(
            sorted((item["condition_value"], item["version"]) for item in active),
            [("厚板", 2), ("薄板", 1)],
        )

    def test_disposition_snapshot_takes_sops_effective_for_the_alert(self):
        """快照收录该项目下对该场景与工况生效的 SOP，排除别的场景与别的项目的。"""
        project_wide = self._create("PW-1", scene_id=None)
        scene_bound = self._create("SC-1")
        self.assertEqual(project_wide.status_code, 200, project_wide.text)
        self.assertEqual(scene_bound.status_code, 200, scene_bound.text)
        other_scene = QualityScene(project_id=self.project.id, code=f"OTHER-{self.case_key}", name="别的场景")
        self.db.add(other_scene)
        self.db.commit()
        self._create("OTHER-1", scene_id=str(other_scene.id))
        retired = self._create("OLD-1", title="旧版")
        self._create("OLD-1", title="新版")  # 旧版退役
        # 只适用于「厚板」工况的 SOP：这条预警没有工况值，不收录
        self._create("COND-1", condition_value="厚板")

        alert = self.make_alert(condition_value=None)
        self.assertEqual(self.ack(alert.id).status_code, 200)
        response = self.client.post(
            f"/api/projects/{self.project.id}/quality-alerts/{alert.id}/disposition",
            json={"resolution": "confirmed_issue"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        sops = self.events(alert.id)[-1]["snapshot"]["sops"]
        self.assertEqual(
            sorted((sop["code"], sop["version"]) for sop in sops),
            [("OLD-1", 2), ("PW-1", 1), ("SC-1", 1)],
        )

    def test_creation_needs_manage_permission_but_reading_does_not(self):
        self.act_as(self.operator)
        self.assertEqual(self._create(f"SOP-OP-{self.case_key}").status_code, 403)
        self.act_as(self.viewer)
        self.assertEqual(self.client.get(self._sops_url()).status_code, 200)
        self.assertEqual(self._create(f"SOP-V-{self.case_key}").status_code, 403)

    def test_validation_rejects_blank_code_and_unknown_keys(self):
        blank = self.client.post(self._sops_url(), json={
            "code": "", "title": "空编号", "content": _GUIDANCE,
        })
        self.assertEqual(blank.status_code, 422)
        unknown_scene = self._create(f"SOP-X-{uuid.uuid4().hex[:4]}", scene_id=str(uuid.uuid4()))
        self.assertEqual(unknown_scene.status_code, 404)
        self.assertEqual(unknown_scene.json()["detail"]["code"], "QUALITY_SCENE_NOT_FOUND")
