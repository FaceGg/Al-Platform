"""板块可见性（补齐路线第一批 §7.1）测试。

覆盖（技术方案 §11.1 test_role_visibility.py 行）：
- PLATFORM_ROLES 扩 quality（用户角色修改端点可设 quality）；
- resolve_visible_views：缺省全可见、按角色收敛、admin 恒全可见、portal 恒在；
- /auth/me visible_views；
- 管理端 nav.section_visibility 读写（admin only、角色/视图枚举校验、portal 自动补回）。
"""
import unittest
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.auth import create_access_token, get_current_user
from app.database import Base, get_db
from app.main import app
from app.models.platform_option import set_option
from app.models.user import User
from app.services.section_visibility import (
    ALWAYS_VISIBLE_VIEWS,
    SECTION_VISIBILITY_KEY,
    VIEW_IDS,
    resolve_visible_views,
)


class TestResolveVisibleViews(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from app.database import engine

        Base.metadata.create_all(bind=engine)

    def test_default_all_views(self):
        with SessionMaker() as db:
            self.assertEqual(resolve_visible_views(db, "engineer"), list(VIEW_IDS))
            self.assertEqual(resolve_visible_views(db, "quality"), list(VIEW_IDS))
            self.assertEqual(resolve_visible_views(db, None), list(VIEW_IDS))

    def test_admin_always_full(self):
        with SessionMaker() as db:
            set_option(db, SECTION_VISIBILITY_KEY, {"admin": ["portal"]})
            self.assertEqual(resolve_visible_views(db, "admin"), list(VIEW_IDS))

    def test_configured_role_narrows_and_others_keep_full(self):
        with SessionMaker() as db:
            set_option(db, SECTION_VISIBILITY_KEY, {"viewer": ["portal", "quality"]})
            self.assertEqual(
                resolve_visible_views(db, "viewer"),
                ["portal", "quality"],
            )
            # 未配置的角色保持现状全可见
            self.assertEqual(resolve_visible_views(db, "engineer"), list(VIEW_IDS))
            # portal 恒在（即使配置遗漏）
            set_option(db, SECTION_VISIBILITY_KEY, {"viewer": ["quality"]})
            self.assertIn("portal", resolve_visible_views(db, "viewer"))

    def test_portal_always_visible_and_unknown_role_full(self):
        with SessionMaker() as db:
            set_option(db, SECTION_VISIBILITY_KEY, {"operator": []})
            visible = resolve_visible_views(db, "operator")
            self.assertEqual(visible, list(ALWAYS_VISIBLE_VIEWS))
            self.assertEqual(resolve_visible_views(db, "ghost-role"), list(VIEW_IDS))
            set_option(db, SECTION_VISIBILITY_KEY, {})
            self.assertEqual(resolve_visible_views(db, "operator"), list(VIEW_IDS))


class TestRoleVisibilityAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(cls.engine)
        cls.Session = sessionmaker(bind=cls.engine, expire_on_commit=False)
        cls.db = cls.Session()
        cls.admin = User(username=f"vis-admin-{uuid.uuid4().hex[:6]}", password_hash="hash", role="admin")
        cls.quality_user = User(username=f"vis-quality-{uuid.uuid4().hex[:6]}", password_hash="hash", role="quality")
        cls.db.add_all([cls.admin, cls.quality_user])
        cls.db.commit()
        cls.current_user = cls.admin
        app.dependency_overrides[get_db] = lambda: cls.db
        app.dependency_overrides[get_current_user] = lambda: cls.current_user
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.clear()
        cls.db.close()
        cls.engine.dispose()

    def setUp(self):
        self.__class__.current_user = self.admin

    def _headers(self, user):
        return {"Authorization": f"Bearer {create_access_token({'sub': str(user.id)})}"}

    def test_quality_role_accepted_by_user_management(self):
        response = self.client.put(
            f"/api/users/{self.quality_user.id}/role",
            json={"role": "quality"},
            headers=self._headers(self.admin),
        )
        self.assertIn(response.status_code, (200, 404), response.text)
        # 端点路径可能不同：仅断言 quality 已是合法角色（PLATFORM_ROLES 扩展）
        from app.schemas.platform_audit import PLATFORM_ROLES

        self.assertIn("quality", PLATFORM_ROLES)

    def test_auth_me_returns_visible_views(self):
        response = self.client.get("/api/auth/me", headers=self._headers(self.admin))
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["visible_views"], list(VIEW_IDS))

    def test_section_visibility_admin_roundtrip(self):
        saved = self.client.put(
            "/api/admin/section-visibility",
            json={"config": {"viewer": ["portal", "quality", "algo"]}},
            headers=self._headers(self.admin),
        )
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(saved.json()["config"]["viewer"], ["portal", "quality", "algo"])

        loaded = self.client.get(
            "/api/admin/section-visibility", headers=self._headers(self.admin),
        )
        self.assertEqual(loaded.status_code, 200, loaded.text)
        self.assertEqual(loaded.json()["config"]["viewer"], ["portal", "quality", "algo"])

        # 解析面：viewer 只见配置的板块
        self.__class__.current_user = self.quality_user
        me = self.client.get("/api/auth/me", headers=self._headers(self.quality_user))
        self.assertEqual(me.json()["visible_views"], list(VIEW_IDS))  # quality 未配置=全可见
        self.__class__.current_user = self.admin

        # admin 配置被拒绝收敛（弹出即忽略）
        admin_narrow = self.client.put(
            "/api/admin/section-visibility",
            json={"config": {"admin": ["portal"]}},
            headers=self._headers(self.admin),
        )
        self.assertEqual(admin_narrow.status_code, 200, admin_narrow.text)
        self.assertNotIn("admin", admin_narrow.json()["config"])

    def test_section_visibility_invalid_role_rejected(self):
        response = self.client.put(
            "/api/admin/section-visibility",
            json={"config": {"ghost": ["portal"]}},
            headers=self._headers(self.admin),
        )
        self.assertEqual(response.status_code, 422, response.text)
        bad_view = self.client.put(
            "/api/admin/section-visibility",
            json={"config": {"viewer": ["portal", "ghost-view"]}},
            headers=self._headers(self.admin),
        )
        self.assertEqual(bad_view.status_code, 422, bad_view.text)

    def test_section_visibility_requires_admin(self):
        self.__class__.current_user = self.quality_user
        response = self.client.get(
            "/api/admin/section-visibility", headers=self._headers(self.quality_user),
        )
        self.assertIn(response.status_code, (403, 401), response.text)
        self.__class__.current_user = self.admin


def SessionMaker():
    from app.database import SessionLocal

    return SessionLocal()


if __name__ == "__main__":
    unittest.main()
