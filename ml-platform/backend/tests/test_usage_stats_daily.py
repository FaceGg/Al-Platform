"""Tokens 用量统计按天聚合测试：本地自然日（UTC+8）分桶、「今天」语义、逐日补零。

回归（用户实测）：此前按 UTC 日期 strftime 分桶——中国用户白天调用落 UTC
当天、凌晨落前一天，桶错位 8 小时；「今天」（days=1）是滚动 24h 出两个桶；
无调用日期缺桶致趋势图断续失真。
"""
import sys, os, unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, ".")

from fastapi.testclient import TestClient
from app.main import app
from app.database import Base, engine
from tests.auth_test_support import ensure_admin

Base.metadata.create_all(bind=engine)
client = TestClient(app)

PLATFORM_TZ = timezone(timedelta(hours=8))


def _local_today() -> str:
    return datetime.now(PLATFORM_TZ).strftime("%Y-%m-%d")


def _local_yesterday() -> str:
    return (datetime.now(PLATFORM_TZ) - timedelta(days=1)).strftime("%Y-%m-%d")


class TestUsageStatsDaily(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ensure_admin()
        cls.h = login()

    def test_today_is_single_local_natural_day_bucket(self):
        """days=1「今天」：单桶、桶名为本地今天日期（此前滚动 24h 出两个 UTC 桶）。"""
        from app.models.platform_audit import PlatformAuditEvent
        from app.database import SessionLocal

        db = SessionLocal()
        today = _local_today()
        # 本地今天 09:00 = UTC 01:00（同日）；本地今天 23:00 = UTC 15:00（同日）
        probe_name = f"ut-usage-today-{today}"
        for hour_utc in (1, 15):
            db.add(PlatformAuditEvent(
                action="llm_gateway.egress",
                created_at=datetime.now(timezone.utc).replace(
                    hour=hour_utc, minute=0, second=0, microsecond=0),
                actor_id=None,
                result="success",
                changes={"model": probe_name, "purpose": "ut", "prompt_tokens": 10, "completion_tokens": 5},
            ))
        db.commit()
        try:
            r = client.get("/api/llm-profiles/usage-stats", params={"days": 1}, headers=self.h)
            self.assertEqual(r.status_code, 200)
            by_day = r.json()["by_day"]
            self.assertEqual([d["date"] for d in by_day], [today])  # 单桶且为本地今天
            self.assertEqual(by_day[0]["calls"], 2)
        finally:
            db.query(PlatformAuditEvent).filter(
                PlatformAuditEvent.action == "llm_gateway.egress",
                PlatformAuditEvent.changes["model"].as_string() == probe_name,
            ).delete(synchronize_session=False)
            db.commit()
            db.close()

    def test_seven_day_window_zero_fills_missing_dates(self):
        """days=7：逐日补零出 7 个连续本地日期桶（无调用日期不再缺失）。"""
        r = client.get("/api/llm-profiles/usage-stats", params={"days": 7}, headers=self.h)
        self.assertEqual(r.status_code, 200)
        by_day = r.json()["by_day"]
        self.assertEqual(len(by_day), 7)
        dates = [d["date"] for d in by_day]
        self.assertEqual(dates[-1], _local_today())
        # 严格连续性：相邻日期差恰为 1 天
        from datetime import date as _date
        parsed = [_date.fromisoformat(x) for x in dates]
        for a, b in zip(parsed, parsed[1:]):
            self.assertEqual((b - a).days, 1)


def login():
    r = client.post("/api/auth/login", data={"username": "admin", "password": "admin123"})
    return {"Authorization": "Bearer " + r.json()["access_token"]}


if __name__ == "__main__":
    unittest.main()
