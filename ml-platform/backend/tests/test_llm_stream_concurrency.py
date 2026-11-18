"""流式并发运行时配置回归（2026-11-18 用户需求：env 配置迁平台界面）。

覆盖：
- GET /api/llm-profiles/stream-concurrency 返回当前生效值；
- PUT 写平台选项并即时调整本进程动态门容量；
- 越界值 422；lower/upper 边界合法；
- 动态门语义：调小后新调用按新上限排队，在途调用不受影响；
- refresh_stream_gate 从 PlatformOption 读取（多进程各自生效的机制）。
"""

import atexit
import os
import sys
import threading
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, ".")

# 本地直跑密封化：未显式设置 DATABASE_URL 时指向进程专属临时库
if not os.environ.get("DATABASE_URL"):
    _SEALED_DIR = Path("temp_test")
    _SEALED_DIR.mkdir(exist_ok=True)
    _SEALED_DB = _SEALED_DIR / f"llm-stream-conc-{os.getpid()}-{uuid.uuid4().hex[:8]}.db"
    os.environ["DATABASE_URL"] = "sqlite:///" + _SEALED_DB.as_posix()

    def _cleanup_sealed_db():
        try:
            import app.database as _sealed_database

            _sealed_database.engine.dispose()
        except Exception:
            pass
        try:
            _SEALED_DB.unlink(missing_ok=True)
        except OSError:
            pass

    atexit.register(_cleanup_sealed_db)

os.environ.setdefault("LLM_MASTER_KEY", __import__(
    "cryptography.fernet", fromlist=["Fernet"]
).Fernet.generate_key().decode("ascii"))

from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.api.auth import pwd_context  # noqa: E402
from app.models.platform_option import PlatformOption, set_option  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.llm_gateway import (  # noqa: E402
    LLM_STREAM_CONCURRENCY_OPTION_KEY,
    STREAM_CONCURRENCY_MAX,
    STREAM_CONCURRENCY_MIN,
    _STREAM_GATE,
    refresh_stream_gate,
)

Base.metadata.create_all(bind=engine)
client = TestClient(app)


def _ensure_admin():
    db = SessionLocal()
    try:
        if db.query(User).filter(User.username == "admin").first() is None:
            db.add(User(
                username="admin",
                password_hash=pwd_context.hash("admin123"),
                role="admin",
            ))
            db.commit()
    finally:
        db.close()


def _login():
    r = client.post("/api/auth/login", data={"username": "admin", "password": "admin123"})
    return {"Authorization": "Bearer " + r.json()["access_token"]}


class TestStreamConcurrencyAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _ensure_admin()
        cls.h = _login()

    def tearDown(self):
        # 清理平台选项与门容量（共享库不残留；容量恢复默认避免影响其他用例）
        db = SessionLocal()
        try:
            row = db.get(PlatformOption, LLM_STREAM_CONCURRENCY_OPTION_KEY)
            if row is not None:
                db.delete(row)
                db.commit()
        finally:
            db.close()
        _STREAM_GATE.set_capacity(2)

    def test_get_returns_current_value(self):
        r = client.get("/api/llm-profiles/stream-concurrency", headers=self.h)
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIn("value", body)
        self.assertIn("stored", body)
        self.assertIn("env_default", body)
        self.assertGreaterEqual(body["value"], STREAM_CONCURRENCY_MIN)

    def test_put_updates_option_and_gate(self):
        r = client.put(
            "/api/llm-profiles/stream-concurrency",
            json={"value": 4},
            headers=self.h,
        )
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["value"], 4)
        self.assertEqual(_STREAM_GATE.capacity, 4)
        db = SessionLocal()
        try:
            stored = db.get(PlatformOption, LLM_STREAM_CONCURRENCY_OPTION_KEY)
            self.assertEqual(stored.value, 4)
        finally:
            db.close()
        # refresh 路径（多进程生效机制）：从平台选项读回并设置
        db = SessionLocal()
        try:
            self.assertEqual(refresh_stream_gate(db), 4)
        finally:
            db.close()

    def test_put_out_of_range_rejected(self):
        for bad in (0, -1, STREAM_CONCURRENCY_MAX + 1, 99):
            r = client.put(
                "/api/llm-profiles/stream-concurrency",
                json={"value": bad},
                headers=self.h,
            )
            self.assertEqual(r.status_code, 422, bad)
        self.assertNotEqual(_STREAM_GATE.capacity, 99)

    def test_put_accepts_boundaries(self):
        for ok in (STREAM_CONCURRENCY_MIN, STREAM_CONCURRENCY_MAX):
            r = client.put(
                "/api/llm-profiles/stream-concurrency",
                json={"value": ok},
                headers=self.h,
            )
            self.assertEqual(r.status_code, 200, ok)
            self.assertEqual(_STREAM_GATE.capacity, ok)

    def test_gate_capacity_shrink_queues_new_calls(self):
        """动态门语义：调小容量后新调用按新上限排队；在途调用不受影响。"""
        _STREAM_GATE.set_capacity(2)
        acquired = threading.Event()
        released = threading.Event()

        def holder():
            _STREAM_GATE.acquire()
            acquired.set()
            released.wait(timeout=5)
            _STREAM_GATE.release()

        thread = threading.Thread(target=holder, daemon=True)
        thread.start()
        self.assertTrue(acquired.wait(timeout=5))
        # 容量 2：第二个调用应立即获得；再调小到 1 后第三个必须等待
        _STREAM_GATE.acquire()
        _STREAM_GATE.set_capacity(1)
        third_acquired = threading.Event()

        def third():
            _STREAM_GATE.acquire()
            third_acquired.set()
            _STREAM_GATE.release()

        thread2 = threading.Thread(target=third, daemon=True)
        thread2.start()
        self.assertFalse(third_acquired.wait(timeout=0.4), "超容量调用不应立即获得槽位")
        _STREAM_GATE.release()
        released.set()
        self.assertTrue(third_acquired.wait(timeout=5), "释放后排队调用应获得槽位")
        thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
