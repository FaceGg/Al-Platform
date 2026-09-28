"""Week 13 migration contract: fresh upgrade, targeted downgrade, data retention."""

import os
import unittest

import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from app.config import settings

CLUSTER_TABLES = (
    "kubernetes_resource_groups",
    "kubernetes_namespaces",
    "kubernetes_credential_refs",
    "kubernetes_clusters",
)
DOWNGRADE_REVISION = "20260926_61"


class TestCloudResourceMigrations(unittest.TestCase):
    def test_upgrade_downgrade_preserves_unrelated_data(self):
        original_url = settings.database_url
        with __import__("tempfile").TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "w13_migrations.db").replace("\\", "/")
            settings.database_url = f"sqlite:///{db_path}"
            try:
                cfg = Config("alembic.ini")
                command.upgrade(cfg, "head")
                engine = sa.create_engine(f"sqlite:///{db_path}")
                inspector = sa.inspect(engine)
                for table in CLUSTER_TABLES:
                    self.assertIn(table, inspector.get_table_names())
                # Seed unrelated data that must survive the downgrade.
                with engine.begin() as conn:
                    conn.execute(
                        sa.text("INSERT INTO projects (id, name, description) VALUES (:id, :name, '')"),
                        {"id": "11111111111111111111111111111111", "name": "w13-retention"},
                    )
                command.downgrade(cfg, DOWNGRADE_REVISION)
                inspector = sa.inspect(engine)
                for table in CLUSTER_TABLES:
                    self.assertNotIn(table, inspector.get_table_names())
                with engine.connect() as conn:
                    kept = conn.execute(
                        sa.text("SELECT name FROM projects WHERE id = '11111111111111111111111111111111'")
                    ).fetchall()
                self.assertEqual([("w13-retention",)], kept)
                command.upgrade(cfg, "head")
                inspector = sa.inspect(engine)
                for table in CLUSTER_TABLES:
                    self.assertIn(table, inspector.get_table_names())
                engine.dispose()
            finally:
                settings.database_url = original_url


if __name__ == "__main__":
    unittest.main()
