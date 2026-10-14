"""Project-level workflow templates: save-as-template / list / instantiate.

Templates are workflows flagged is_template=True; welding-scenario hardcoded
and industrial templates were retired."""
import sys
import unittest
import uuid

sys.path.insert(0, ".")

from fastapi.testclient import TestClient

from app.main import app
from app.database import Base, SessionLocal, engine
from app.models.workflow import Workflow
from tests.auth_test_support import ensure_admin

Base.metadata.create_all(bind=engine)
client = TestClient(app)


def login():
    r = client.post("/api/auth/login", data={"username": "admin", "password": "admin123"})
    return {"Authorization": "Bearer " + r.json()["access_token"]}


class WorkflowTemplatesAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ensure_admin()
        cls.h = login()
        r = client.post("/api/projects", json={"name": "TemplatesProject"}, headers=cls.h)
        cls.project_id = r.json()["id"]

    def _create_workflow(self, name, node_count=2):
        nodes = [
            {"id": f"n{i}", "operator_id": "api_input", "label": f"节点{i}",
             "params": {}, "position": {"x": i * 100, "y": 100}}
            for i in range(node_count)
        ]
        edges = [
            {"id": "e1", "source": "n0", "target": "n1",
             "source_port": "data", "target_port": "data"},
            {"id": "e2", "source": "n1", "target": "n2",
             "source_port": "data", "target_port": "data"},
        ] if node_count >= 3 else (
            [{"id": "e1", "source": "n0", "target": "n1",
              "source_port": "data", "target_port": "data"}] if node_count >= 2 else []
        )
        r = client.post(
            f"/api/projects/{self.project_id}/workflows",
            json={"name": name, "nodes": nodes, "edges": edges},
            headers=self.h,
        )
        self.assertEqual(r.status_code, 201, r.text)
        return r.json()

    def test_01_save_list_instantiate_and_isolation(self):
        wf = self._create_workflow(f"闭环服务-{uuid.uuid4().hex[:6]}", node_count=3)
        wf_id = wf["id"]

        # 保存为模板（默认名 = 工作流名-模板）
        r = client.post(
            f"/api/projects/{self.project_id}/workflows/{wf_id}/save-as-template",
            json={}, headers=self.h,
        )
        self.assertEqual(r.status_code, 201, r.text)
        template = r.json()
        self.assertTrue(template["name"].endswith("-模板"))
        self.assertEqual(len(template["nodes"]), 3)
        self.assertEqual(len(template["edges"]), 2)
        # 连线必须指向模板自己的新节点（复制时按源图节点 id 照抄会丢连线）
        node_ids = {n["id"] for n in template["nodes"]}
        for e in template["edges"]:
            self.assertIn(str(e["source_node_id"]), node_ids)
            self.assertIn(str(e["target_node_id"]), node_ids)
        template_id = template["id"]

        # 模板列表可见，且普通工作流列表不再混入模板
        r = client.get(f"/api/projects/{self.project_id}/workflow-templates", headers=self.h)
        self.assertEqual(r.status_code, 200)
        items = r.json()["items"]
        self.assertGreaterEqual(r.json()["total"], 1)
        mine = [t for t in items if t["id"] == template_id]
        self.assertEqual(len(mine), 1)
        self.assertEqual(mine[0]["node_count"], 3)

        r = client.get(f"/api/projects/{self.project_id}/workflows", headers=self.h)
        listed_ids = [w["id"] for w in r.json()]
        self.assertIn(wf_id, listed_ids)
        self.assertNotIn(template_id, listed_ids)

        # 从模板创建：图完整复制且相互独立
        r = client.post(
            f"/api/projects/{self.project_id}/workflow-templates/{template_id}/instantiate",
            json={"name": "从模板创建的服务"}, headers=self.h,
        )
        self.assertEqual(r.status_code, 201, r.text)
        copy = r.json()
        self.assertEqual(copy["name"], "从模板创建的服务")
        self.assertEqual(len(copy["nodes"]), 3)
        copy_node_ids = {n["id"] for n in copy["nodes"]}
        for e in copy["edges"]:
            self.assertIn(str(e["source_node_id"]), copy_node_ids)
            self.assertIn(str(e["target_node_id"]), copy_node_ids)
        self.assertNotEqual(copy["id"], template_id)

        # 修改副本不影响模板
        r = client.put(
            f"/api/projects/{self.project_id}/workflows/{copy['id']}",
            json={"name": "从模板创建的服务", "nodes": [
                {"id": "x", "operator_id": "api_input", "label": "x", "params": {},
                 "position": {"x": 0, "y": 0}},
            ], "edges": []},
            headers=self.h,
        )
        self.assertEqual(r.status_code, 200, r.text)
        db = SessionLocal()
        try:
            tpl = db.query(Workflow).filter(Workflow.id == uuid.UUID(template_id)).one()
            self.assertEqual(len(tpl.nodes), 3)
        finally:
            db.close()

        # 清理：模板与副本可删（模板删除走工作流删除端点）
        for wid in (copy["id"], template_id, wf_id):
            r = client.delete(f"/api/projects/{self.project_id}/workflows/{wid}", headers=self.h)
            self.assertIn(r.status_code, (200, 204), r.text)

    def test_02_welding_templates_retired(self):
        # 焊接场景硬编码模板已下线，通用模板保留
        r = client.get("/api/templates", headers=self.h)
        self.assertEqual(r.status_code, 200)
        ids = [t["id"] for t in r.json()["items"]]
        for retired in ("weld_quality", "param_recommend", "anomaly_detect"):
            self.assertNotIn(retired, ids)
        self.assertIn("full_ml_pipeline", ids)

    def _member_session(self):
        # 注册一次性成员账号（密码运行时随机生成，非真实凭据）
        username = f"tpl-member-{uuid.uuid4().hex[:8]}"
        password = f"tpl-{uuid.uuid4().hex}-Pw"
        r = client.post("/api/auth/register", json={"username": username, "password": password})
        self.assertEqual(r.status_code, 200, r.text)
        r = client.post("/api/auth/login", data={"username": username, "password": password})
        headers = {"Authorization": "Bearer " + r.json()["access_token"]}
        r = client.post("/api/projects", json={"name": f"MemberProject-{username}"}, headers=headers)
        self.assertIn(r.status_code, (200, 201), r.text)
        return headers, r.json()["id"]

    def test_03_global_template_cross_project(self):
        # 管理员把带项目绑定参数的服务图存为平台通用模板
        nodes = [
            {"id": "n0", "operator_id": "csv_import", "label": "导入",
             "params": {"dataset_artifact_id": "src-artifact", "file_path": "E:/data/x.csv"},
             "position": {"x": 0, "y": 0}},
            {"id": "n1", "operator_id": "api_input", "label": "出参",
             "params": {"model_artifact_id": "src-model"},
             "position": {"x": 100, "y": 0}},
        ]
        edges = [{"id": "e1", "source": "n0", "target": "n1",
                  "source_port": "data", "target_port": "data"}]
        r = client.post(
            f"/api/projects/{self.project_id}/workflows",
            json={"name": f"通用服务-{uuid.uuid4().hex[:6]}", "nodes": nodes, "edges": edges},
            headers=self.h,
        )
        self.assertEqual(r.status_code, 201, r.text)
        wf_id = r.json()["id"]

        r = client.post(
            f"/api/projects/{self.project_id}/workflows/{wf_id}/save-as-template",
            json={"name": "平台通用服务模板", "scope": "global"}, headers=self.h,
        )
        self.assertEqual(r.status_code, 201, r.text)
        template_id = r.json()["id"]

        db = SessionLocal()
        try:
            tpl = db.query(Workflow).filter(Workflow.id == uuid.UUID(template_id)).one()
            self.assertIsNone(tpl.project_id)
        finally:
            db.close()

        # 其他项目（成员自有项目）的模板列表可见通用模板，scope=global
        member_headers, member_project_id = self._member_session()
        r = client.get(f"/api/projects/{member_project_id}/workflow-templates", headers=member_headers)
        self.assertEqual(r.status_code, 200, r.text)
        items = r.json()["items"]
        mine = [t for t in items if t["id"] == template_id]
        self.assertEqual(len(mine), 1)
        self.assertEqual(mine[0]["scope"], "global")

        # 成员在自有项目实例化通用模板：项目绑定参数被清除，其余参数保留
        r = client.post(
            f"/api/projects/{member_project_id}/workflow-templates/{template_id}/instantiate",
            json={"name": "成员的实例"}, headers=member_headers,
        )
        self.assertEqual(r.status_code, 201, r.text)
        instance = r.json()
        params_by_label = {n["label"]: n["params"] for n in instance["nodes"]}
        self.assertNotIn("dataset_artifact_id", params_by_label["导入"])
        self.assertEqual(params_by_label["导入"].get("file_path"), "E:/data/x.csv")
        self.assertNotIn("model_artifact_id", params_by_label["出参"])

        # 通用模板的编辑/删除权限：普通用户 403，管理员放行
        member_put = {"name": "x", "nodes": [
            {"id": "x", "operator_id": "api_input", "label": "x", "params": {},
             "position": {"x": 0, "y": 0}},
        ], "edges": []}
        r = client.put(f"/api/workflows/{template_id}", json=member_put, headers=member_headers)
        self.assertEqual(r.status_code, 403, r.text)
        r = client.put(
            f"/api/workflows/{template_id}",
            json={**member_put, "name": "平台通用服务模板 v2"},
            headers=self.h,
        )
        self.assertEqual(r.status_code, 200, r.text)

        r = client.delete(
            f"/api/projects/{member_project_id}/workflows/{template_id}",
            headers=member_headers,
        )
        self.assertEqual(r.status_code, 403, r.text)
        r = client.delete(
            f"/api/projects/{self.project_id}/workflows/{template_id}",
            headers=self.h,
        )
        self.assertIn(r.status_code, (200, 204), r.text)
        # 清理：实例归成员项目所有（用成员身份删），其余用管理员身份删
        r = client.delete(
            f"/api/projects/{member_project_id}/workflows/{instance['id']}",
            headers=member_headers,
        )
        self.assertIn(r.status_code, (200, 204), r.text)
        r = client.delete(f"/api/projects/{self.project_id}/workflows/{wf_id}", headers=self.h)
        self.assertIn(r.status_code, (200, 204), r.text)

    def test_04_member_cannot_publish_global_template(self):
        member_headers, member_project_id = self._member_session()
        r = client.post(
            f"/api/projects/{member_project_id}/workflows",
            json={"name": "成员的服务", "nodes": [
                {"id": "n0", "operator_id": "api_input", "label": "n0",
                 "params": {}, "position": {"x": 0, "y": 0}},
            ], "edges": []},
            headers=member_headers,
        )
        self.assertEqual(r.status_code, 201, r.text)
        member_wf_id = r.json()["id"]
        # 成员非平台管理员：保存为通用模板被拒
        r = client.post(
            f"/api/projects/{member_project_id}/workflows/{member_wf_id}/save-as-template",
            json={"scope": "global"}, headers=member_headers,
        )
        self.assertEqual(r.status_code, 403, r.text)
        # 默认 project 作用域不受影响
        r = client.post(
            f"/api/projects/{member_project_id}/workflows/{member_wf_id}/save-as-template",
            json={}, headers=member_headers,
        )
        self.assertEqual(r.status_code, 201, r.text)


if __name__ == "__main__":
    unittest.main()
