"""Agent orchestration & communication tests."""
import sys, os, unittest
sys.path.insert(0, ".")

from fastapi.testclient import TestClient
from app.main import app
from app.database import Base, engine

Base.metadata.create_all(bind=engine)
client = TestClient(app)

# Ensure admin exists for fresh DB
client.post("/api/auth/register", json={"username": "admin", "password": "admin123", "role": "admin"})


def login_headers():
    r = client.post("/api/auth/login", data={"username": "admin", "password": "admin123"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


class TestAgentAPI(unittest.TestCase):
    def test_01_create_agent(self):
        h = login_headers()
        r = client.post("/api/orchestration/agents", json={
            "name": "TestPlanner", "agent_type": "planner",
            "description": "A test planner", "model_name": "gpt-4o-mini",
        }, headers=h)
        self.assertIn(r.status_code, [200, 201])
        self.__class__.agent_id = r.json()["id"]

    def test_02_list_agents(self):
        r = client.get("/api/orchestration/agents", headers=login_headers())
        self.assertEqual(r.status_code, 200)

    def test_03_update_agent(self):
        h = login_headers()
        r = client.post("/api/orchestration/agents", json={
            "name": "TmpAgent", "agent_type": "executor",
        }, headers=h)
        aid = r.json()["id"]
        r = client.put(f"/api/orchestration/agents/{aid}", json={
            "name": "UpdatedAgent", "is_active": False,
        }, headers=h)
        self.assertEqual(r.status_code, 200)

    def test_04_create_task(self):
        h = login_headers()
        r = client.post("/api/orchestration/tasks", json={
            "name": "TestTask", "description": "A test task",
            "priority": 5, "requires_review": True,
        }, headers=h)
        self.assertIn(r.status_code, [200, 201])
        self.__class__.task_id = r.json().get("id")

    def test_05_send_message(self):
        h = login_headers()
        r = client.post("/api/orchestration/agents", json={
            "name": "MsgAgent", "agent_type": "executor",
        }, headers=h)
        aid = r.json()["id"]
        r = client.post("/api/orchestration/tasks", json={
            "name": "MsgTask", "description": "Test",
        }, headers=h)
        tid = r.json().get("id")
        if tid:
            r = client.post(f"/api/orchestration/tasks/{tid}/messages", json={
                "from_agent_id": aid, "message_type": "info",
                "content": "Task started.",
            }, headers=h)
            self.assertEqual(r.status_code, 200)

    def test_06_list_messages(self):
        h = login_headers()
        r = client.post("/api/orchestration/tasks", json={
            "name": "MsgTask2", "description": "Test",
        }, headers=h)
        tid = r.json().get("id")
        if tid:
            r = client.get(f"/api/orchestration/tasks/{tid}/messages", headers=h)
            self.assertEqual(r.status_code, 200)

    def test_07_plan_task(self):
        h = login_headers()
        r = client.post("/api/orchestration/plan", json={
            "task_description": "Predict weld quality",
            "task_id": "any",
        }, headers=h)
        self.assertEqual(r.status_code, 200)

    def test_08_delete_agent_and_task(self):
        h = login_headers()
        r = client.post("/api/orchestration/agents", json={
            "name": "DelAgent", "agent_type": "executor",
        }, headers=h)
        aid = r.json()["id"]
        r = client.post("/api/orchestration/tasks", json={
            "name": "DelTask", "description": "Test",
        }, headers=h)
        tid = r.json().get("id")
        if tid:
            r = client.delete(f"/api/orchestration/tasks/{tid}", headers=h)
            self.assertEqual(r.status_code, 200)
        r = client.delete(f"/api/orchestration/agents/{aid}", headers=h)
        self.assertEqual(r.status_code, 200)


if __name__ == "__main__":
    unittest.main()
