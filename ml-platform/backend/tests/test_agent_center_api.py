"""Agent center read-only listing API tests (Agent plan, front-end wiring)."""

import os
import unittest
import uuid
from uuid import uuid4

os.environ.setdefault("LLM_MASTER_KEY", __import__(
    "cryptography.fernet", fromlist=["Fernet"]
).Fernet.generate_key().decode("ascii"))

from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.models.agent_run import AgentRun  # noqa: E402
from app.models.project import Project  # noqa: E402
from app.models.recipe import PipelineRecipe, PipelineRecipeVersion  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.agent.recipe import create_recipe  # noqa: E402
from tests.auth_test_support import ensure_admin  # noqa: E402

Base.metadata.create_all(bind=engine)
client = TestClient(__import__("app.main", fromlist=["app"]).app)

_ADMIN_USER = "agent-center-admin-" + uuid4().hex[:8]
_ADMIN_PASSWORD = uuid4().hex + uuid4().hex[:4]


class AgentCenterHarness(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ensure_admin(_ADMIN_USER, _ADMIN_PASSWORD)
        token = client.post(
            "/api/auth/login",
            data={"username": _ADMIN_USER, "password": _ADMIN_PASSWORD},
        ).json()["access_token"]
        cls.h = {"Authorization": "Bearer " + token}
        with SessionLocal() as db:
            cls.user_id = str(
                db.query(User).filter(User.username == _ADMIN_USER).one().id
            )

    def setUp(self):
        with SessionLocal() as db:
            db.query(AgentRun).delete()
            db.query(PipelineRecipeVersion).delete()
            db.query(PipelineRecipe).delete()
            db.query(Project).filter(Project.name.like("agent-center-%")).delete()
            db.commit()

    def _project(self, name="agent-center-proj"):
        with SessionLocal() as db:
            project = Project(name=name, owner_id=None, description="")
            db.add(project)
            db.commit()
            return str(project.id), project.name


class TestAgentRunsListing(AgentCenterHarness, unittest.TestCase):
    def test_lists_runs_with_project_name_and_metadata_only(self):
        project_id, project_name = self._project()
        with SessionLocal() as db:
            db.add(AgentRun(
                project_id=uuid.UUID(project_id),
                target_column="DECIDE",
                status="waiting_escalate",
                current_stage="s4",
                round_count=1,
                token_used=9588,
                error_code="AGENT_REVIEW_ESCALATE",
                memory_json={"rounds": [{"round": 1}]},
                result_json={"secret": "no-leak"},
            ))
            db.add(AgentRun(
                target_column="fault",
                status="running",
                current_stage="s2",
            ))
            db.commit()

        response = client.get("/api/agent/runs", headers=self.h)
        self.assertEqual(response.status_code, 200)
        items = response.json()
        self.assertEqual(len(items), 2)
        # Updated-first ordering (the running row has no timestamps edge-case;
        # both rows exist, ordering by updated_at desc).
        by_status = {item["status"]: item for item in items}
        escalated = by_status["waiting_escalate"]
        self.assertEqual(escalated["project_name"], project_name)
        self.assertEqual(escalated["current_stage"], "s4")
        self.assertEqual(escalated["round_count"], 1)
        self.assertEqual(escalated["token_used"], 9588)
        # Memory/result payloads must not be exposed.
        self.assertNotIn("memory_json", escalated)
        self.assertNotIn("result_json", escalated)
        self.assertNotIn("secret", response.text)
        self.assertIsNone(by_status["running"]["project_name"])

    def test_requires_authentication(self):
        response = client.get("/api/agent/runs")
        self.assertEqual(response.status_code, 401)

    def test_run_detail_returns_full_archive_with_memory(self):
        project_id, project_name = self._project()
        memory = {"rounds": [{
            "round": 1,
            "s2_attempts": [{"attempt": 1, "ok": True}],
            "verdict": "escalate",
            "hints": ["剔除判定列后重训"],
        }]}
        with SessionLocal() as db:
            db.add(AgentRun(
                project_id=uuid.UUID(project_id),
                target_column="DECIDE",
                status="waiting_escalate",
                current_stage="s4",
                round_count=1,
                token_used=9588,
                error_code="AGENT_REVIEW_ESCALATE",
                memory_json=memory,
                result_json={"token_used": 9588},
            ))
            db.commit()
            run_id = str(db.query(AgentRun).order_by(AgentRun.created_at.desc()).first().id)

        response = client.get(f"/api/agent/runs/{run_id}", headers=self.h)
        self.assertEqual(response.status_code, 200)
        detail = response.json()
        self.assertEqual(detail["status"], "waiting_escalate")
        self.assertEqual(detail["round_count"], 1)
        self.assertEqual(detail["memory_json"], memory)
        self.assertEqual(detail["result_json"], {"token_used": 9588})
        self.assertEqual(detail["error_code"], "AGENT_REVIEW_ESCALATE")
        # 详情页「项目」字段：详情接口与列表同一口径解析项目名（此前硬编码 None 恒显示 "-"）
        self.assertEqual(detail["project_id"], project_id)
        self.assertEqual(detail["project_name"], project_name)

    def test_run_detail_404_for_unknown_id(self):
        response = client.get(f"/api/agent/runs/{uuid4()}", headers=self.h)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"]["code"], "AGENT_RUN_NOT_FOUND")

    def test_escalated_run_decision_accept_and_reject(self):
        """升级态人工决策闭环：accept 落 accepted（冠军实测指标回填）+ 决策留痕；
        reject 落 cancelled；非升级态 409。"""
        project_id, _ = self._project()
        memory = {
            "rounds": [
                {"round": 1, "verdict": "escalate",
                 "s3": {"metrics": {"recall_minority": 0.86, "f1": 0.88}}},
                {"round": 2, "verdict": "escalate",
                 "s3": {"metrics": {"recall_minority": 0.9, "f1": 0.95}}},
            ],
            "escalation": {"code": "AGENT_REVIEW_ESCALATE", "detail": "疑似泄漏", "round": 2},
        }
        with SessionLocal() as db:
            run = AgentRun(
                project_id=uuid.UUID(project_id), target_column="fault",
                status="waiting_escalate", current_stage="s4", round_count=2,
                token_used=1000, error_code="AGENT_REVIEW_ESCALATE",
                memory_json=memory, result_json={"token_used": 1000},
            )
            db.add(run)
            db.commit()
            run_id = str(run.id)

        # 非升级态（cancelled）决策 → 409
        with SessionLocal() as db:
            done = AgentRun(
                project_id=uuid.UUID(project_id), target_column="fault",
                status="cancelled", current_stage="s4", round_count=1,
                token_used=10, error_code=None, memory_json={}, result_json={},
            )
            db.add(done)
            db.commit()
            done_id = str(done.id)
        non_escalated = client.post(
            f"/api/agent/runs/{done_id}/decision",
            json={"decision": "accept"}, headers=self.h,
        )
        self.assertEqual(non_escalated.status_code, 409)

        # reject 分支：落 cancelled + 决策留痕
        rejected = client.post(
            f"/api/agent/runs/{run_id}/decision",
            json={"decision": "reject", "note": "泄漏点名属实"}, headers=self.h,
        )
        self.assertEqual(rejected.status_code, 200)
        self.assertEqual(rejected.json()["status"], "cancelled")
        resolved = rejected.json()["memory_json"]["escalation"]["resolved"]
        self.assertEqual(resolved["decision"], "reject")
        self.assertEqual(resolved["note"], "泄漏点名属实")

        with SessionLocal() as db:
            db.query(AgentRun).delete()
            run = AgentRun(
                project_id=uuid.UUID(project_id), target_column="fault",
                status="waiting_escalate", current_stage="s4", round_count=2,
                token_used=1000, error_code="AGENT_REVIEW_ESCALATE",
                memory_json=memory, result_json={"token_used": 1000},
            )
            db.add(run)
            db.commit()
            run_id = str(run.id)
        accepted = client.post(
            f"/api/agent/runs/{run_id}/decision",
            json={"decision": "accept"}, headers=self.h,
        )
        self.assertEqual(accepted.status_code, 200)
        self.assertEqual(accepted.json()["status"], "accepted")
        self.assertEqual(accepted.json()["error_code"], None)
        # 指标取最后轮次冠军实测值（round 2），不是第一轮
        self.assertEqual(accepted.json()["result_json"]["metrics"], {"recall_minority": 0.9, "f1": 0.95})
        self.assertEqual(
            accepted.json()["memory_json"]["escalation"]["resolved"]["decision"], "accept",
        )

        # 终态后再决策 → 409
        again = client.post(
            f"/api/agent/runs/{run_id}/decision",
            json={"decision": "reject"}, headers=self.h,
        )
        self.assertEqual(again.status_code, 409)


class TestCreateAgentRun(AgentCenterHarness, unittest.TestCase):
    def test_archives_wizard_submission_with_guidance_and_pause_plan(self):
        payload = {
            "dataset_artifact_id": str(uuid4()),
            "target_column": "DECIDE(判定（最终判定）（0-不合格，1-合格）)",
            "step_by_step": True,
            "token_budget": 120000,
            "guidance": {
                "analysis": {"column_notes": [{"column": "ACTUAL_TORQUE", "note": "核心质量信号"}]},
                "feature": {"suggest_drop": [{"column": "DECIDE_ONE", "reason": "同源判定"}, {"column": "DECIDE_TWO", "reason": "同源判定"}]},
                "modeling": {"algorithm_whitelist": ["lightgbm", "hist_gradient_boosting"]},
                "evaluation": {"metric_gates": {"recall_minority": 0.92}},
            },
        }
        response = client.post("/api/agent/runs", json=payload, headers=self.h)
        self.assertEqual(response.status_code, 201)
        detail = response.json()
        self.assertEqual(detail["status"], "pending")
        self.assertEqual(detail["current_stage"], "s1")
        self.assertEqual(detail["token_budget"], 120000)
        # guidance_json is exposed via the detail payload
        self.assertIn("guidance_json", detail)
        # Step-by-step expands into the full pause plan.
        self.assertEqual(sorted(detail["guidance_json"]["pause_at_stages"]), ["s1", "s2", "s3", "s4"])
        self.assertEqual(detail["guidance_json"]["modeling"]["algorithm_whitelist"],
                         ["lightgbm", "hist_gradient_boosting"])

    def test_rejects_invalid_guidance_with_contract_errors(self):
        payload = {
            "dataset_artifact_id": str(uuid4()),
            "target_column": "fault",
            "guidance": {"analysis": {"column_notes": "not-a-mapping"}},
        }
        response = client.post("/api/agent/runs", json=payload, headers=self.h)
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["detail"]["code"], "AGENT_RUN_GUIDANCE_INVALID")

    def test_requires_authentication(self):
        response = client.post("/api/agent/runs", json={
            "dataset_artifact_id": str(uuid4()), "target_column": "fault",
        })
        self.assertEqual(response.status_code, 401)


class TestRecipeListing(AgentCenterHarness, unittest.TestCase):
    def test_lists_recipes_with_current_version_metadata(self):
        project_id, project_name = self._project()
        with SessionLocal() as db:
            create_recipe(
                db,
                project_id=uuid.UUID(project_id),
                name="tightening-v1",
                domain="tightening",
                target_column="DECIDE",
                content={"features": {"keep": ["TORQUE_DEVIATION"]}},
                change_note="验收通过固化",
                created_by=uuid.UUID(self.user_id),
            )

        response = client.get("/api/agent/recipes", headers=self.h)
        self.assertEqual(response.status_code, 200)
        items = response.json()
        self.assertEqual(len(items), 1)
        recipe = items[0]
        self.assertEqual(recipe["name"], "tightening-v1")
        self.assertEqual(recipe["project_name"], project_name)
        self.assertEqual(recipe["current_version"], 1)
        self.assertEqual(recipe["version_status"], "current")
        self.assertEqual(recipe["change_note"], "验收通过固化")
        # Recipe version content must not be exposed.
        self.assertNotIn("content_json", recipe)
        self.assertNotIn("TORQUE_DEVIATION", response.text)

    def test_requires_authentication(self):
        response = client.get("/api/agent/recipes")
        self.assertEqual(response.status_code, 401)


class TestRecipeDetailAndDelete(AgentCenterHarness, unittest.TestCase):
    def _seed(self, name: str, created_by=None) -> str:
        project_id, _ = self._project()
        with SessionLocal() as db:
            recipe = create_recipe(
                db,
                project_id=uuid.UUID(project_id),
                name=name,
                domain="tightening",
                target_column="DECIDE",
                content={
                    "features": {"keep": ["TORQUE_DEVIATION"]},
                    "feature_script": "def transform(df):\n    return df",
                    "acceptance_gates": {"recall_minority": 0.9},
                    "baseline_metrics": {"recall_minority": 0.93},
                },
                change_note="验收通过固化",
                created_by=uuid.UUID(created_by) if created_by else None,
            )
            return str(recipe.id)

    def test_detail_returns_content_and_versions(self):
        recipe_id = self._seed("recipe-detail")
        response = client.get(f"/api/agent/recipes/{recipe_id}", headers=self.h)
        self.assertEqual(response.status_code, 200)
        detail = response.json()
        self.assertEqual(detail["name"], "recipe-detail")
        # 详情页展示用：当前版本完整内容（列表接口刻意不暴露 content，详情必须暴露）
        self.assertEqual(detail["content"]["acceptance_gates"]["recall_minority"], 0.9)
        self.assertIn("def transform", detail["content"]["feature_script"])
        self.assertEqual(len(detail["versions"]), 1)
        self.assertEqual(detail["versions"][0]["status"], "current")
        self.assertEqual(detail["versions"][0]["baseline_metrics"]["recall_minority"], 0.93)

    def test_detail_404_for_unknown_id(self):
        response = client.get(f"/api/agent/recipes/{uuid4()}", headers=self.h)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"]["code"], "AGENT_RECIPE_NOT_FOUND")

    def test_delete_removes_recipe_and_all_versions(self):
        recipe_id = self._seed("recipe-del")
        response = client.delete(f"/api/agent/recipes/{recipe_id}", headers=self.h)
        self.assertEqual(response.status_code, 204)
        self.assertEqual(
            client.get(f"/api/agent/recipes/{recipe_id}", headers=self.h).status_code, 404,
        )
        with SessionLocal() as db:
            self.assertEqual(db.query(PipelineRecipeVersion).count(), 0)
            self.assertIsNone(db.get(PipelineRecipe, uuid.UUID(recipe_id)))


class TestDeleteAgentRun(AgentCenterHarness, unittest.TestCase):
    def _seed_run(self, status, created_by=None):
        with SessionLocal() as db:
            run = AgentRun(
                target_column="DECIDE",
                status=status,
                current_stage="s4",
                round_count=1,
                token_used=10,
                memory_json={},
                result_json={},
                created_by=uuid.UUID(created_by) if created_by else None,
            )
            db.add(run)
            db.commit()
            return str(run.id)

    def test_creator_can_delete_a_terminal_run(self):
        run_id = self._seed_run("waiting_escalate", created_by=self.user_id)
        response = client.delete(f"/api/agent/runs/{run_id}", headers=self.h)
        self.assertEqual(response.status_code, 204)
        with SessionLocal() as db:
            self.assertIsNone(db.get(AgentRun, uuid.UUID(run_id)))

    def test_active_run_rejects_delete_with_409(self):
        run_id = self._seed_run("running", created_by=self.user_id)
        response = client.delete(f"/api/agent/runs/{run_id}", headers=self.h)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"]["code"], "AGENT_RUN_ACTIVE")

    def test_non_owner_non_admin_rejects_delete_with_403(self):
        from app.api.auth import pwd_context

        other_user = "agent-other-" + uuid4().hex[:8]
        other_password = uuid4().hex + uuid4().hex[:4]
        with SessionLocal() as db:
            db.add(User(username=other_user, password_hash=pwd_context.hash(other_password), role="engineer"))
            db.commit()
        token = client.post(
            "/api/auth/login", data={"username": other_user, "password": other_password},
        ).json()["access_token"]
        run_id = self._seed_run("waiting_escalate", created_by=self.user_id)
        response = client.delete(
            f"/api/agent/runs/{run_id}", headers={"Authorization": "Bearer " + token},
        )
        self.assertEqual(response.status_code, 403)

    def test_delete_unknown_run_returns_404(self):
        response = client.delete(f"/api/agent/runs/{uuid4()}", headers=self.h)
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
