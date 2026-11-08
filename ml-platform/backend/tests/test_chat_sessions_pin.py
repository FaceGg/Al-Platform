"""AI 对话多会话 API：置顶字段往返 + 列表置顶优先排序。"""
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


class TestChatSessionsPin(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ensure_admin()
        cls.h = login()

    def test_pin_roundtrip_and_ordering(self):
        # 建两个会话（列表最新在前）
        r1 = client.post("/api/chat-sessions", json={"title": "会话A"}, headers=self.h).json()
        r2 = client.post("/api/chat-sessions", json={"title": "会话B"}, headers=self.h).json()
        try:
            # 默认顺序：B（新）在前
            sessions = client.get("/api/chat-sessions", headers=self.h).json()
            self.assertEqual(sessions[0]["id"], r2["id"])
            # 置顶旧会话 A
            r = client.put(f"/api/chat-sessions/{r1['id']}", json={"pinned": True}, headers=self.h)
            self.assertEqual(r.status_code, 200)
            self.assertTrue(r.json()["pinned"])
            # 列表：A 置顶排到最前
            sessions = client.get("/api/chat-sessions", headers=self.h).json()
            self.assertEqual(sessions[0]["id"], r1["id"])
            self.assertTrue(sessions[0]["pinned"])
            # 取消置顶恢复
            client.put(f"/api/chat-sessions/{r1['id']}", json={"pinned": False}, headers=self.h)
            sessions = client.get("/api/chat-sessions", headers=self.h).json()
            self.assertEqual(sessions[0]["id"], r2["id"])
        finally:
            client.delete(f"/api/chat-sessions/{r1['id']}", headers=self.h)
            client.delete(f"/api/chat-sessions/{r2['id']}", headers=self.h)

    def test_pin_unknown_session_404(self):
        r = client.put("/api/chat-sessions/00000000-0000-0000-0000-000000000000", json={"pinned": True}, headers=self.h)
        self.assertEqual(r.status_code, 404)


if __name__ == "__main__":
    unittest.main()
