"""Tokens 用量统计按天聚合测试：本地自然日（UTC+8）分桶、「今天」语义、逐日补零。

回归（用户实测）：此前按 UTC 日期 strftime 分桶——中国用户白天调用落 UTC
当天、凌晨落前一天，桶错位 8 小时；「今天」（days=1）是滚动 24h 出两个桶；
无调用日期缺桶致趋势图断续失真。
"""
import sys, os, unittest
import uuid
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
        from app.models.user import User
        from app.database import SessionLocal

        db = SessionLocal()
        admin = db.query(User).filter(User.username == "admin").first()
        today = _local_today()
        # 造数锚定业务时区（UTC+8）的「今天」：此前用 UTC now-日期 + 固定
        # hour（01:00/15:00），在 UTC 16:00-16:59（=UTC+8 午夜）跑 CI 时数据
        # 落业务昨天、桶空（calls=0）——任意时刻跑都必须落在业务今天桶。
        probe_name = f"ut-usage-today-{today}"
        for hour_local in (9, 23):
            aware_local = datetime.now(PLATFORM_TZ).replace(
                hour=hour_local, minute=0, second=0, microsecond=0,
                tzinfo=PLATFORM_TZ,
            )
            db.add(PlatformAuditEvent(
                action="llm_gateway.egress",
                created_at=aware_local.astimezone(timezone.utc),
                actor_id=admin.id if admin else None,
                actor_username="admin" if admin else "anonymous",
                resource_type="llm_profile",
                # resource_id 是 String 列：传 UUID 对象在 SQLite 直接绑定失败
                resource_id=str(admin.id) if admin else "",
                request_id=uuid.uuid4(),
                result="success",
                changes={"model": probe_name, "purpose": "ut", "prompt_tokens": 10, "completion_tokens": 5},
            ))
        db.commit()
        try:
            r = client.get("/api/llm-profiles/usage-stats", params={"days": 1}, headers=self.h)
            self.assertEqual(r.status_code, 200)
            by_day = r.json()["by_day"]
            self.assertEqual([d["date"] for d in by_day], [today])  # 单桶且为本地今天
            # 共享生产库：今天桶含真实流量，只断言造的 2 条计入（≥2）
            self.assertGreaterEqual(by_day[0]["calls"], 2)
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
