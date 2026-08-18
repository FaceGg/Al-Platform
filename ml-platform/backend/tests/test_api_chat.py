"""Chat API integration tests."""
import sys, os, unittest
sys.path.insert(0, ".")

from fastapi.testclient import TestClient
from app.main import app
from app.database import Base, engine
from tests.auth_test_support import ensure_admin

Base.metadata.create_all(bind=engine)
client = TestClient(app)


def login():
    r = client.post("/api/auth/login", data={"username": "admin", "password": "admin123"})
    return {"Authorization": "Bearer " + r.json()["access_token"]}


class TestChatAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Ensure admin exists for fresh DB
        ensure_admin()
        cls.h = login()

    def test_01_chat_status(self):
        r = client.get("/api/chat/status")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("configured", data)
        self.assertIn("model", data)

    def test_02_chat_without_api_key(self):
        """Chat should return error message when LLM not configured."""
        r = client.post("/api/chat", json={"message": "Hello"}, headers=self.h)
        self.assertIn(r.status_code, [200, 201])
        data = r.json()
        self.assertIn("type", data)
        self.assertEqual(data["type"], "error")

    def test_03_chat_with_system_prompt(self):
        r = client.post("/api/chat", json={
            "message": "What is spot welding?",
            "system_prompt": "You are an expert in welding manufacturing.",
        }, headers=self.h)
        self.assertIn(r.status_code, [200, 201])

    def test_04_chat_empty_message(self):
        r = client.post("/api/chat", json={"message": ""}, headers=self.h)
        self.assertIn(r.status_code, [200, 201, 422])

    def test_05_chat_requires_auth(self):
        r = client.post("/api/chat", json={"message": "Hello"})
        self.assertEqual(r.status_code, 401)

    def test_06_chat_status_no_auth(self):
        r = client.get("/api/chat/status")
        self.assertEqual(r.status_code, 200)

    def test_07_chat_long_message(self):
        long_msg = "Tell me about " + "welding " * 200
        r = client.post("/api/chat", json={"message": long_msg}, headers=self.h)
        self.assertIn(r.status_code, [200, 201])


if __name__ == "__main__":
    unittest.main()
