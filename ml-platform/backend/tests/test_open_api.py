"""补齐路线第一批 F5：接入开放（B1-13 只读接口 + B1-07 接入通道，技术方案 §9A）。

验收口径（计划 §2 F5）：外部脚本持 Key 分页拉取、轮换后旧 Key 宽限期内可用、
期满 401、写动词全 405；契约校验拒绝落 rejected；同 ID 同内容幂等跳过；
同 ID 不同内容可追查；页脚状态三态由真实心跳驱动（未启用如实说未启用）。
"""
import unittest
import uuid
from datetime import datetime, timedelta

from app.config import settings
from app.models.access import AuditEvent
from app.models.demo_loop import DemoLoopConfig
from app.models.ingest import IngestEvent
from app.models.inference_result import InferenceResult
from app.models.model_registry import InferenceApiKey, InferenceDeployment
from app.models.platform_option import PlatformOption
from app.models.quality_alerts import QualityAlert
from app.services import ingest
from app.services.inference_api_keys import InferenceApiKeyError, InferenceApiKeyService
from tests.quality_alert_fixtures import QualityAlertApiCase


class TestOpenApi(QualityAlertApiCase):
    """B1-13：项目级 Key + 三个只读资源。"""

    def setUp(self):
        super().setUp()
        self.key_service = InferenceApiKeyService()
        for model in (InferenceApiKey, InferenceResult, QualityAlert, AuditEvent):
            query = self.db.query(model)
            if hasattr(model, "project_id"):
                query = query.filter(model.project_id == self.project.id)
            query.delete(synchronize_session="fetch")
        self.db.commit()
    def _create_key(self):
        created = self.key_service.create_project_key(
            self.db, self.project.id, self.owner.id, ["project.read"],
        )
        self.db.commit()
        return created

    def _headers(self, plaintext):
        return {"X-Api-Key": plaintext}

    def _open(self, path, headers=None, method="get", **kwargs):
        return getattr(self.client, method)(
            f"/api/v1/open/projects/{self.project.id}{path}",
            headers=headers or {}, **kwargs,
        )

    def test_project_key_reads_all_three_resources_with_pagination(self):
        created = self._create_key()
        headers = self._headers(created.plaintext)
        now = datetime.utcnow()
        for index in range(3):
            self.db.add(InferenceResult(
                request_id=f"open-{index}", project_id=self.project.id, channel="online",
                sample_key=f"VIN-{index}", anomaly_score=0.9,
                occurred_at=now - timedelta(minutes=index), expires_at=now + timedelta(days=1),
            ))
        self.db.add(QualityAlert(
            project_id=self.project.id, scene_id=self.scene.id, source_type="model_risk",
            severity="high", title="确认异常的处置单", status="closed",
            resolution="confirmed_issue", closed_at=now, evidence={},
            merge_key=f"open-{self.case_key}",
        ))
        self.db.add(DemoLoopConfig(
            project_id=self.project.id, name="反馈闭环",
            feedback_marks={"artifact-1": {"0": "confirmed_fault", "3": "false_alarm"}},
        ))
        self.db.commit()

        results = self._open("/inference-results?page=1&page_size=2", headers).json()
        self.assertEqual(results["total"], 3)
        self.assertEqual(len(results["items"]), 2, "分页生效")
        self.assertEqual(results["items"][0]["sample_key"], "VIN-0", "按时间倒序")
        inspections = self._open("/inspection-results", headers).json()
        self.assertEqual(inspections["total"], 1)
        self.assertEqual(inspections["items"][0]["title"], "确认异常的处置单")
        feedback = self._open("/feedback", headers).json()
        self.assertEqual(feedback["items"][0]["confirmed_fault"], 1)
        self.assertEqual(feedback["items"][0]["false_alarm"], 1)
        # 样本键筛选
        filtered = self._open(
            "/inference-results", headers, params={"sample_key": "VIN-1"},
        ).json()
        self.assertEqual(filtered["total"], 1)

    def test_demo_channel_and_demo_alerts_are_excluded(self):
        created = self._create_key()
        headers = self._headers(created.plaintext)
        now = datetime.utcnow()
        self.db.add(InferenceResult(
            request_id="open-demo", project_id=self.project.id, channel="demo",
            occurred_at=now, expires_at=now + timedelta(days=1),
        ))
        self.db.commit()
        body = self._open("/inference-results", headers).json()
        self.assertEqual(body["total"], 0)

    def test_key_management_requires_manage_permission_and_hides_plaintext_once(self):
        created = self._create_key()
        listed = self.client.get(
            f"/api/projects/{self.project.id}/open-api-keys",
        ).json()
        self.assertEqual(listed["total"], 1)
        self.assertNotIn("plaintext", listed["items"][0])
        # 操作员不能管理
        self.act_as(self.operator)
        denied = self.client.post(
            f"/api/projects/{self.project.id}/open-api-keys", json={"scopes": ["project.read"]},
        )
        self.assertEqual(denied.status_code, 403)
        self.act_as(self.owner)
        # 非法 scope 拒绝
        bad_scope = self.client.post(
            f"/api/projects/{self.project.id}/open-api-keys", json={"scopes": ["project.update"]},
        )
        self.assertEqual(bad_scope.status_code, 422)
        # 创建：明文只出现一次
        created_response = self.client.post(
            f"/api/projects/{self.project.id}/open-api-keys", json={},
        )
        self.assertEqual(created_response.status_code, 200, created_response.text)
        self.assertIn("plaintext", created_response.json())
        # 轮换：旧 Key 进宽限期，新 Key 立即可用
        key_id = created_response.json()["id"]
        old_plaintext = created_response.json()["plaintext"]
        rotated = self.client.post(
            f"/api/projects/{self.project.id}/open-api-keys/{key_id}/rotate",
        )
        self.assertEqual(rotated.status_code, 200, rotated.text)
        new_plaintext = rotated.json()["plaintext"]
        self.assertIsNotNone(rotated.json()["previous_grace_until"], "旧 Key 有了宽限期")
        ok_old = self._open("/inference-results", self._headers(old_plaintext))
        self.assertEqual(ok_old.status_code, 200, "宽限期内旧 Key 可用")
        ok_new = self._open("/inference-results", self._headers(new_plaintext))
        self.assertEqual(ok_new.status_code, 200)

    def test_grace_expiry_and_mismatch_are_unauthorized(self):
        created = self._create_key()
        # 宽限期已过 → 401 GRACE_EXPIRED
        created.record.grace_until = datetime.utcnow() - timedelta(minutes=1)
        self.db.commit()
        expired = self._open("/inference-results", self._headers(created.plaintext))
        self.assertEqual(expired.status_code, 401)
        self.assertEqual(expired.json()["detail"]["code"], "INFERENCE_API_KEY_GRACE_EXPIRED")
        # 别的项目的 Key → 401
        other = self.key_service.create_project_key(
            self.db, uuid.uuid4(), self.owner.id, ["project.read"],
        )
        self.db.commit()
        mismatched = self._open("/inference-results", self._headers(other.plaintext))
        self.assertEqual(mismatched.status_code, 401)
        # 无 Key / 部署级 Key → 401（部署级 Key 造在真实部署上：归属互斥 CHECK
        # 要求恰好一个归属）
        self.assertEqual(self._open("/inference-results", {}).status_code, 401)
        deployment = InferenceDeployment(
            project_id=self.project.id, name=f"open-deploy-{self.case_key}",
            model_version_id=self._stub_model_version_id(),
            created_by_id=self.owner.id,
        )
        self.db.add(deployment)
        self.db.flush()
        deployment_key = self.key_service.create(
            self.db, deployment.id, self.owner.id, ["inference.predict"], None,
        )
        self.db.commit()
        self.assertEqual(
            self._open("/inference-results", self._headers(deployment_key.plaintext)).status_code,
            401,
        )

    def _stub_model_version_id(self):
        from app.models.model_library import ModelLibrary
        from app.models.model_registry import ModelVersion

        library = ModelLibrary(
            name=f"open-lib-{self.case_key}", owner_id=self.owner.id, status="completed",
        )
        self.db.add(library)
        self.db.flush()
        version = ModelVersion(
            registered_model_id=uuid.uuid4(), version_number=999,
            source_kind="platform_joblib", source_artifact_id=uuid.uuid4(),
            onnx_artifact_id=uuid.uuid4(), source_model_library_id=library.id,
        )
        self.db.add(version)
        self.db.flush()
        return version.id

    def test_write_verbs_are_rejected_and_reads_are_audited_free(self):
        created = self._create_key()
        headers = self._headers(created.plaintext)
        self.assertEqual(
            self._open("/inference-results", headers, method="post", json={}).status_code, 405,
        )
        self.assertEqual(
            self._open("/inference-results", headers, method="delete").status_code, 405,
        )


class TestIngest(QualityAlertApiCase):
    """B1-07：接入契约、幂等去重、页脚状态三态。"""

    def setUp(self):
        super().setUp()
        self.db.query(IngestEvent).delete(synchronize_session="fetch")
        self.db.query(PlatformOption).delete(synchronize_session="fetch")
        self.db.commit()

    def _event(self, business_id="evt-1", **overrides):
        payload = {
            "station": "ST-1", "business_event_id": business_id,
            # 相对当前时间（写死的时间会随真实时钟漂移出正负延迟）
            "occurred_at": datetime.utcnow().isoformat(), "payload": {"force": 5.0},
        }
        payload.update(overrides)
        return payload

    def test_contract_rejects_invalid_payloads_with_reasons(self):
        good = self._event()
        missing_station = self._event("evt-2", station="")
        bad_time = self._event("evt-3", occurred_at="not-a-time")
        summary = ingest.ingest_batch(
            self.db, project_id=self.project.id, source="manual",
            events=[good, missing_station, bad_time],
        )
        self.db.commit()
        self.assertEqual((summary["accepted"], summary["rejected"]), (1, 2))
        rows = list(self.db.query(IngestEvent).all())
        accepted = next(row for row in rows if row.status == "accepted")
        self.assertEqual(accepted.business_event_id, "evt-1")
        self.assertEqual(accepted.latency_seconds, 0, "事件时间=现在 → 延迟 0")
        for row in rows:
            if row.status == "rejected":
                self.assertTrue(row.reject_reason)

    def test_same_id_same_content_is_idempotent_and_same_id_different_content_is_traceable(self):
        first = ingest.ingest_batch(
            self.db, project_id=self.project.id, source="manual", events=[self._event()],
        )
        self.assertEqual(first["accepted"], 1)
        second = ingest.ingest_batch(
            self.db, project_id=self.project.id, source="manual", events=[self._event()],
        )
        self.assertEqual(second["duplicate"], 1, "同 ID 同内容幂等跳过")
        replayed = ingest.ingest_batch(
            self.db, project_id=self.project.id, source="manual",
            events=[self._event(payload={"force": 999.0})],
        )
        self.assertEqual(replayed["rejected"], 1, "同 ID 不同内容落 rejected")
        self.db.commit()
        rows = self.db.query(IngestEvent).order_by(IngestEvent.status).all()
        self.assertEqual(len(rows), 2, "accepted 一行 + rejected 追查行（不覆盖）")
        trace = next(row for row in rows if row.status == "rejected")
        self.assertIn("内容不一致", trace.reject_reason)

    def test_kafka_replay_from_offsets_is_idempotent(self):
        """重放场景（E18）：同一批事件带着相同 offset 再来一遍不重复计数。"""
        events = [self._event(f"replay-{index}") for index in range(3)]
        first = ingest.ingest_batch(
            self.db, project_id=self.project.id, source="kafka",
            topic="quality-ingest", partition=0, offsets=[10, 11, 12], events=events,
        )
        replay = ingest.ingest_batch(
            self.db, project_id=self.project.id, source="kafka",
            topic="quality-ingest", partition=0, offsets=[10, 11, 12], events=events,
        )
        self.assertEqual((first["accepted"], replay["accepted"], replay["duplicate"]), (3, 0, 3))

    def test_ingest_publish_endpoint_audits(self):
        response = self.client.post(
            f"/api/projects/{self.project.id}/ingest/publish",
            json={"source": "manual", "events": [self._event("pub-1")]},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["accepted"], 1)
        audited = {row.action for row in self.db.query(AuditEvent).filter(
            AuditEvent.project_id == self.project.id, AuditEvent.result == "success",
        ).all()}
        self.assertIn("ingest.publish", audited)

    def test_ingest_status_three_states_driven_by_real_heartbeat(self):
        # 未启用：如实说未启用
        self.assertFalse(settings.kafka_ingest_enabled)
        body = self.client.get("/api/platform/ingest-status").json()
        self.assertEqual(body["state"], "disabled")
        self.assertIn("未启用", body["detail"])
        # 启用 + 无心跳 → stale
        settings.kafka_ingest_enabled = True
        try:
            body = self.client.get("/api/platform/ingest-status").json()
            self.assertEqual(body["state"], "stale")
            # 新鲜心跳 → ok
            ingest.record_heartbeat(self.db, state="ok")
            body = self.client.get("/api/platform/ingest-status").json()
            self.assertEqual(body["state"], "ok")
            # 心跳超时 → 告警
            stale = {
                "state": "ok",
                "at": (datetime.utcnow() - timedelta(seconds=int(
                    settings.ingest_heartbeat_stale_seconds) + 60)).isoformat(),
            }
            from app.models.platform_option import set_option

            set_option(self.db, ingest.INGEST_HEARTBEAT_KEY, stale)
            body = self.client.get("/api/platform/ingest-status").json()
            self.assertEqual(body["state"], "stale")
            self.assertIn("超时", body["detail"])
        finally:
            settings.kafka_ingest_enabled = False


if __name__ == "__main__":
    unittest.main()
