import unittest

from sqlalchemy import create_engine, inspect, text

from app.database_migrations import ensure_schema_compatibility
from app.models.model_export import ModelExport
from app.models.model_registry import ModelVersion


class DatabaseMigrationCompatibilityTests(unittest.TestCase):
    def test_legacy_training_jobs_get_owner_scoped_automl_idempotency_unique_index(self):
        engine = create_engine("sqlite:///:memory:")
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE training_jobs (id CHAR(32) PRIMARY KEY, user_id CHAR(32) NOT NULL)"))
        ensure_schema_compatibility(engine)
        indexes = {item["name"]: item for item in inspect(engine).get_indexes("training_jobs")}
        unique = indexes["uq_training_jobs_user_automl_idempotency"]
        self.assertTrue(unique["unique"])
        self.assertEqual(unique["column_names"], ["user_id", "automl_idempotency_key"])
        with engine.begin() as connection:
            connection.execute(text("INSERT INTO training_jobs (id,user_id,automl_idempotency_key) VALUES ('1','u','k')"))
            with self.assertRaises(Exception):
                connection.execute(text("INSERT INTO training_jobs (id,user_id,automl_idempotency_key) VALUES ('2','u','k')"))

    def test_legacy_platform_api_table_gets_api_management_columns(self):
        engine = create_engine("sqlite:///:memory:")
        with engine.begin() as connection:
            connection.execute(text(
                "CREATE TABLE platform_apis ("
                "id CHAR(32) PRIMARY KEY, name VARCHAR(256) NOT NULL, "
                "version VARCHAR(32), owner_id CHAR(32) NOT NULL)"
            ))

        ensure_schema_compatibility(engine)

        columns = {column["name"]: column for column in inspect(engine).get_columns("platform_apis")}
        self.assertEqual(columns["source_kind"]["default"], "'custom'")
        self.assertIn("source_id", columns)
        self.assertIn("published_at", columns)
        self.assertIn("last_error", columns)

        with engine.connect() as connection:
            connection.execute(text(
                "INSERT INTO platform_apis (id, name, version, owner_id) "
                "VALUES ('api-1', 'Legacy API', 'v1', 'user-1')"
            ))
            self.assertEqual(
                connection.execute(text("SELECT source_kind FROM platform_apis")).scalar_one(),
                "custom",
            )

    def test_model_export_orm_declares_migration_indexes_and_idempotency_guard(self):
        constraint_names = {
            constraint.name
            for constraint in ModelExport.__table__.constraints
            if constraint.name
        }
        index_names = {index.name for index in ModelExport.__table__.indexes}

        self.assertIn("uq_model_exports_idempotency", constraint_names)
        self.assertIn("ix_model_exports_model_version_status", index_names)

    def test_model_registration_idempotency_is_scoped_to_one_task_and_key(self):
        indexes = {
            index.name: index
            for index in ModelVersion.__table__.indexes
            if index.name == "uq_model_versions_registration_idempotency"
        }

        index = indexes["uq_model_versions_registration_idempotency"]
        self.assertTrue(index.unique)
        self.assertEqual(
            [column.name for column in index.columns],
            ["registration_task_id", "registration_idempotency_key"],
        )


if __name__ == "__main__":
    unittest.main()
