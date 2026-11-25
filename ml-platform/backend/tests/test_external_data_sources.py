"""外部数据源（补齐路线第一批 P4，B1-08）测试。

覆盖（技术方案 §11.1 test_external_data_sources.py 行）：
- CRUD mask：口令任何接口不回显（password_set 布尔位）；
- 白名单判定矩阵（含绕过用例）：多语句/注释绕过/嵌套子查询带 ;DROP/
  UNION 允许/危险函数/INTO OUTFILE；
- 白名单拒绝落审计（data_source.preview failed）；
- 预览/表清单/导入全链（mock 外部引擎=内存 SQLite）；
- connect_args 白名单键校验；
- 轮换工具幂等（旧密文→新密钥重加密，重跑零改动；跨列 scope）。

注：测试数据源的口令值一律运行时生成（非凭据，仅验 mask 形态）。
"""
import unittest
import uuid

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import MetaData, Table, Column, Integer, Float, create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.auth import get_current_user
from app.database import Base, get_db
from app.main import app
from app.models.access import AuditEvent
from app.models.external_data_source import ExternalDataSource
from app.models.user import User

KEY_OLD = Fernet.generate_key()
KEY_NEW = Fernet.generate_key()


def _configure_keys() -> None:
    from app import config as config_module

    settings = config_module.settings
    settings._resolved_datasource_master_key = SecretStr(KEY_OLD.decode("ascii"))


_configure_keys()


class TestSqlWhitelistMatrix(unittest.TestCase):
    """判定矩阵（技术方案 §4.2/D7 注；绕过用例锁死）。"""

    def test_legitimate_forms_pass(self):
        from app.services.sql_whitelist import validate_readonly_sql

        cases = [
            ("SELECT * FROM samples", "postgres"),
            ("WITH t AS (SELECT 1 AS a) SELECT * FROM t", "postgres"),
            ("SELECT a FROM x UNION SELECT b FROM y", "postgres"),
            ("SELECT * FROM samples LIMIT 50", "mysql"),
            ("select id, torque from welds where torque > 1 order by id", "mysql"),
        ]
        for sql, dialect in cases:
            with self.subTest(sql=sql):
                normalized = validate_readonly_sql(sql, dialect=dialect)
                self.assertTrue(normalized)

    def test_bypass_attempts_blocked(self):
        from app.services.sql_whitelist import SqlWhitelistError, validate_readonly_sql

        cases = [
            ("SELECT 1; DROP TABLE samples", "postgres"),
            ("SELECT * FROM samples;DELETE FROM samples", "postgres"),
            ("UPDATE samples SET torque = 0", "postgres"),
            ("DELETE FROM samples", "postgres"),
            ("INSERT INTO samples VALUES (1)", "postgres"),
            ("CREATE TABLE evil (a int)", "postgres"),
            ("DROP TABLE samples", "postgres"),
            ("COPY samples TO '/tmp/evil'", "postgres"),
            ("SELECT pg_sleep(10)", "postgres"),
            ("SELECT benchmark(1000000, MD5('x'))", "mysql"),
            ("SELECT load_file('/etc/passwd')", "mysql"),
            ("SELECT * FROM samples INTO OUTFILE '/tmp/evil'", "mysql"),
            # 注释绕过：分号拼接的多语句无论注释形态都拦截
            ("SELECT * FROM samples -- comment\n; DELETE FROM samples", "postgres"),
            ("/* hint */ SELECT * FROM samples; /* x */ DROP TABLE samples", "postgres"),
            # 嵌套子查询带 ;DROP：多语句拦截
            ("SELECT * FROM (SELECT 1) x; DROP TABLE samples", "postgres"),
        ]
        for sql, dialect in cases:
            with self.subTest(sql=sql):
                with self.assertRaises(SqlWhitelistError):
                    validate_readonly_sql(sql, dialect=dialect)

    def test_limit_cap_enforced(self):
        from app.services.sql_whitelist import (
            DEFAULT_PREVIEW_ROW_LIMIT,
            SqlWhitelistError,
            validate_readonly_sql,
        )

        normalized = validate_readonly_sql("SELECT * FROM samples", dialect="postgres")
        self.assertIn(f"LIMIT {DEFAULT_PREVIEW_ROW_LIMIT}", normalized)
        normalized = validate_readonly_sql(
            "SELECT * FROM samples LIMIT 50", dialect="postgres", row_limit=200,
        )
        self.assertIn("LIMIT 50", normalized)
        with self.assertRaises(SqlWhitelistError):
            validate_readonly_sql(
                "SELECT * FROM samples LIMIT 999999", dialect="postgres", row_limit=200,
            )


class TestExternalDataSourceAPI(unittest.TestCase):
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
        cls.users = {
            role: User(username=f"ds-{role}-{uuid.uuid4().hex[:6]}", password_hash="hash")
            for role in ("owner", "editor", "operator", "viewer", "outsider")
        }
        cls.db.add_all(cls.users.values())
        cls.db.flush()
        from app.models.project import Project
        from app.models.access import ProjectMember

        cls.project = Project(name="DS project", owner_id=cls.users["owner"].id)
        cls.db.add(cls.project)
        cls.db.flush()
        for role in ("editor", "operator", "viewer"):
            cls.db.add(ProjectMember(
                project_id=cls.project.id,
                user_id=cls.users[role].id,
                role=role,
                created_by=cls.users["owner"].id,
            ))
        cls.db.commit()

        cls.current_user = cls.users["owner"]
        app.dependency_overrides[get_db] = lambda: cls.db
        app.dependency_overrides[get_current_user] = lambda: cls.current_user
        cls.client = TestClient(app)

        # mock 外部引擎：内存 SQLite + samples 表（构造路径建表插数）
        cls.mock_engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        metadata = MetaData()
        cls.samples_table = Table(
            "samples", metadata,
            Column("id", Integer),
            Column("torque", Float),
        )
        metadata.create_all(cls.mock_engine)
        with cls.mock_engine.begin() as conn:
            conn.execute(cls.samples_table.insert().values([
                {"id": 1, "torque": 1.1},
                {"id": 2, "torque": 1.2},
                {"id": 3, "torque": 0.9},
            ]))

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.clear()
        cls.db.close()
        cls.engine.dispose()
        cls.mock_engine.dispose()

    def setUp(self):
        self.__class__.current_user = self.users["owner"]

    def _create_source(self, name="primary", **overrides):
        payload = {
            "name": name,
            "db_type": "postgresql",
            "host": "db.example.com",
            "port": 5432,
            "database": "mes",
            "username": "readonly",
            "password": f"pw-{uuid.uuid4().hex[:12]}",
            "ssl_mode": "require",
        }
        payload.update(overrides)
        response = self.client.post(
            f"/api/projects/{self.project.id}/data-sources", json=payload,
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    # ------------------------------------------------------------- CRUD

    def test_crud_and_password_mask(self):
        source = self._create_source()
        self.assertTrue(source["password_set"])
        self.assertNotIn("password", source)
        self.assertNotIn("password_encrypted", source)

        listed = self.client.get(f"/api/projects/{self.project.id}/data-sources")
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertEqual(listed.json()["total"], 1)
        self.assertNotIn("password", listed.json()["items"][0])

        updated = self.client.put(
            f"/api/projects/{self.project.id}/data-sources/{source['id']}",
            json={"password": f"pw-{uuid.uuid4().hex[:12]}", "port": 5433},
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()["port"], 5433)
        self.assertNotIn("password", updated.json())

        deleted = self.client.delete(
            f"/api/projects/{self.project.id}/data-sources/{source['id']}"
        )
        self.assertEqual(deleted.status_code, 204, deleted.text)

    def test_duplicate_name_conflict(self):
        self._create_source(name="dup-source")
        response = self.client.post(
            f"/api/projects/{self.project.id}/data-sources",
            json={
                "name": "dup-source",
                "db_type": "postgresql",
                "host": "h", "port": 5432, "database": "d",
                "username": "u", "password": f"pw-{uuid.uuid4().hex[:12]}",
            },
        )
        self.assertEqual(response.status_code, 409, response.text)

    def test_invalid_db_type_and_connect_args(self):
        response = self.client.post(
            f"/api/projects/{self.project.id}/data-sources",
            json={
                "name": "bad-type", "db_type": "oracle",
                "host": "h", "port": 1521, "database": "d",
                "username": "u", "password": f"pw-{uuid.uuid4().hex[:12]}",
            },
        )
        self.assertEqual(response.status_code, 422, response.text)
        # connect_args 白名单键：password 类键拒绝
        bad_extra = self.client.post(
            f"/api/projects/{self.project.id}/data-sources",
            json={
                "name": "bad-extra", "db_type": "postgresql",
                "host": "h", "port": 5432, "database": "d",
                "username": "u", "password": f"pw-{uuid.uuid4().hex[:12]}",
                "extra": {"password": "x"},
            },
        )
        self.assertEqual(bad_extra.status_code, 400, bad_extra.text)
        ok_extra = self.client.post(
            f"/api/projects/{self.project.id}/data-sources",
            json={
                "name": "ok-extra", "db_type": "postgresql",
                "host": "h", "port": 5432, "database": "d",
                "username": "u", "password": f"pw-{uuid.uuid4().hex[:12]}",
                "extra": {"application_name": "platform"},
            },
        )
        self.assertEqual(ok_extra.status_code, 201, ok_extra.text)

    def test_write_permission_matrix(self):
        # editor 可建（resource.create 对 editor 授予）；operator 拒绝
        self.__class__.current_user = self.users["operator"]
        response = self.client.post(
            f"/api/projects/{self.project.id}/data-sources",
            json={
                "name": "perm-check", "db_type": "postgresql",
                "host": "h", "port": 5432, "database": "d",
                "username": "u", "password": f"pw-{uuid.uuid4().hex[:12]}",
            },
        )
        self.assertEqual(response.status_code, 403, response.text)
        self.__class__.current_user = self.users["viewer"]
        listed = self.client.get(f"/api/projects/{self.project.id}/data-sources")
        self.assertEqual(listed.status_code, 200, listed.text)
        self.__class__.current_user = self.users["owner"]

    # ------------------------------------------------ 查询动作与审计

    def test_preview_rejects_and_audits(self):
        source = self._create_source(name="audit-src")
        response = self.client.post(
            f"/api/projects/{self.project.id}/data-sources/{source['id']}/preview",
            json={"sql": "UPDATE samples SET torque = 0"},
        )
        self.assertEqual(response.status_code, 400, response.text)
        # 拒绝落审计（白名单拒绝 → failed 事件）
        audit = (
            self.db.query(AuditEvent)
            .filter(
                AuditEvent.action == "data_source.preview",
                AuditEvent.result == "failed",
                AuditEvent.resource_id == source["id"],
            )
            .order_by(AuditEvent.id.desc())
            .first()
        )
        self.assertIsNotNone(audit)
        self.assertEqual(audit.error_code, "SQL_WHITELIST_INVALID")

    def test_preview_success_with_mock_engine(self):
        source = self._create_source(name="preview-src")
        from unittest.mock import patch

        from app.services import external_data_sources as service_module

        with patch.object(service_module, "_query_engine", return_value=self.mock_engine):
            response = self.client.post(
                f"/api/projects/{self.project.id}/data-sources/{source['id']}/preview",
                json={"sql": "SELECT id, torque FROM samples WHERE torque > 1.0"},
            )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["columns"], ["id", "torque"])
        self.assertEqual(body["row_count"], 2)
        self.assertTrue(body["whitelisted"])

    def test_tables_with_mock_engine(self):
        source = self._create_source(name="tables-src")
        from unittest.mock import patch

        from app.services import external_data_sources as service_module

        with patch.object(service_module, "_query_engine", return_value=self.mock_engine):
            response = self.client.get(
                f"/api/projects/{self.project.id}/data-sources/{source['id']}/tables",
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("samples", response.json()["items"])

    def test_import_full_chain_with_mock_engine(self):
        source = self._create_source(name="import-src")
        from unittest.mock import patch

        from app.services import external_data_sources as service_module

        enqueued = []
        with (
            patch.object(service_module, "_query_engine", return_value=self.mock_engine),
            patch(
                "app.tasks.dataset_import_tasks.enqueue_dataset_import",
                side_effect=lambda import_id: enqueued.append(str(import_id)),
            ),
        ):
            response = self.client.post(
                f"/api/projects/{self.project.id}/data-sources/{source['id']}/import",
                json={"sql": "SELECT id, torque FROM samples", "dataset_name": "外部取数"},
            )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["status"], "queued")
        self.assertEqual(len(enqueued), 1)
        # 导入进程真实落库（复用数据集导入状态机）
        from app.models.data_version import DatasetImportProcess

        process = self.db.query(DatasetImportProcess).filter(
            DatasetImportProcess.id == uuid.UUID(body["import_id"]),
        ).one()
        self.assertIsNotNone(process.id)
        # 拒绝形态同样进不了导入链
        denied = self.client.post(
            f"/api/projects/{self.project.id}/data-sources/{source['id']}/import",
            json={"sql": "DELETE FROM samples", "dataset_name": "bad"},
        )
        self.assertEqual(denied.status_code, 400, denied.text)
        self.assertEqual(len(enqueued), 1)


class TestRotateFernetKeys(unittest.TestCase):
    """轮换工具：旧密文→新密钥重加密；重跑幂等零改动；跨列 scope。"""

    @classmethod
    def setUpClass(cls):
        from app.database import engine

        Base.metadata.create_all(bind=engine)
        from app.database import SessionLocal
        from app.models.project import Project
        from app.models.user import User

        with SessionLocal() as db:
            user = User(username=f"rotate-owner-{uuid.uuid4().hex[:6]}", password_hash="hash")
            db.add(user)
            db.flush()
            project = Project(name="Rotate project", owner_id=user.id)
            db.add(project)
            db.commit()
            cls.project_id = project.id

    def _seed_datasource(self, secret: str, name: str):
        from app.database import SessionLocal
        from app.models.external_data_source import ExternalDataSource
        from app.services.external_data_sources import encrypt_password

        with SessionLocal() as db:
            source = ExternalDataSource(
                project_id=self.project_id,
                name=name,
                db_type="postgresql",
                host="h", port=5432, database="d", username="u",
                password_encrypted=encrypt_password(secret),
            )
            db.add(source)
            db.commit()
            return source.id

    def test_rotation_reencrypts_and_is_idempotent(self):
        from app.database import SessionLocal
        from app.models.external_data_source import ExternalDataSource
        from tools.rotate_fernet_keys import rotate_datasources

        source_id = self._seed_datasource(
            "row-secret", f"rotate-ds-{uuid.uuid4().hex[:6]}",
        )
        # 工具的加解密走 settings 当前密钥（KEY_OLD）；new 为全新密钥
        service_settings = __import__("app.config", fromlist=["settings"]).settings
        service_settings._resolved_datasource_master_key = SecretStr(KEY_OLD.decode("ascii"))
        old_fernet = Fernet(KEY_OLD)
        new_fernet = Fernet(KEY_NEW)
        first = rotate_datasources(
            SecretStr(KEY_OLD.decode("ascii")), SecretStr(KEY_NEW.decode("ascii")),
            old_fernet, new_fernet, dry_run=False,
        )
        # 密封库含其他用例类残留的数据源行 → 至少轮换本用例行
        self.assertGreaterEqual(first, 1)
        with SessionLocal() as db:
            row = db.query(ExternalDataSource).filter(
                ExternalDataSource.id == source_id,
            ).one()
            plain = new_fernet.decrypt(row.password_encrypted.encode("ascii"))
            self.assertEqual(plain.decode("utf-8"), "row-secret")
        # 幂等：重跑零改动
        second = rotate_datasources(
            SecretStr(KEY_OLD.decode("ascii")), SecretStr(KEY_NEW.decode("ascii")),
            old_fernet, new_fernet, dry_run=False,
        )
        self.assertEqual(second, 0)

    def test_notification_rotation_roundtrip(self):
        from app.database import SessionLocal
        from app.models.notifications import NotificationEndpoint
        from app.services.notification_crypto import decrypt_config, encrypt_config
        from tools.rotate_fernet_keys import rotate_notifications

        old_secret = SecretStr(KEY_OLD.decode("ascii"))
        with SessionLocal() as db:
            endpoint = NotificationEndpoint(
                project_id=self.project_id,
                kind="webhook",
                name=f"rotate-notif-{uuid.uuid4().hex[:6]}",
                destination_hint="https://example.invalid/hook",
                encrypted_config=encrypt_config(
                    {"url": "https://example.invalid/hook"}, old_secret,
                ),
            )
            db.add(endpoint)
            db.commit()
            endpoint_id = endpoint.id

        new_fernet = Fernet(KEY_NEW)
        old_fernet = Fernet(KEY_OLD)
        count = rotate_notifications(
            old_secret, SecretStr(KEY_NEW.decode("ascii")), old_fernet, new_fernet,
            dry_run=False,
        )
        self.assertGreaterEqual(count, 1)
        with SessionLocal() as db:
            row = db.query(NotificationEndpoint).filter(
                NotificationEndpoint.id == endpoint_id,
            ).one()
            config = decrypt_config(row.encrypted_config, SecretStr(KEY_NEW.decode("ascii")))
            self.assertEqual(config["url"], "https://example.invalid/hook")

    def test_dry_run_does_not_write(self):
        from app.database import SessionLocal
        from app.models.external_data_source import ExternalDataSource
        from tools.rotate_fernet_keys import rotate_datasources

        source_id = self._seed_datasource(
            "dry-secret", f"dry-ds-{uuid.uuid4().hex[:6]}",
        )
        with SessionLocal() as db:
            row = db.query(ExternalDataSource).filter(ExternalDataSource.id == source_id).one()
            old_token = row.password_encrypted
        count = rotate_datasources(
            SecretStr(KEY_OLD.decode("ascii")), SecretStr(KEY_NEW.decode("ascii")),
            Fernet(KEY_OLD), Fernet(KEY_NEW), dry_run=True,
        )
        self.assertGreaterEqual(count, 1)
        with SessionLocal() as db:
            row = db.query(ExternalDataSource).filter(ExternalDataSource.id == source_id).one()
            self.assertEqual(row.password_encrypted, old_token)


if __name__ == "__main__":
    unittest.main()
