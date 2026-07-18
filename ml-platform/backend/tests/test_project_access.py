import uuid
import unittest

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient


class TestAccessModels(unittest.TestCase):
    def test_member_and_audit_tables_register_constraints_and_indexes(self):
        from app.database import Base
        from app.models.access import AuditEvent, ProjectMember

        self.assertEqual(ProjectMember.__tablename__, "project_members")
        self.assertEqual(AuditEvent.__tablename__, "audit_events")
        member_table = Base.metadata.tables["project_members"]
        audit_table = Base.metadata.tables["audit_events"]
        member_constraints = {
            constraint.name for constraint in member_table.constraints
        }
        self.assertIn("uq_project_members_project_user", member_constraints)
        self.assertIn("ck_project_members_role", member_constraints)
        self.assertIn(
            "ix_project_members_user_project",
            {index.name for index in member_table.indexes},
        )
        audit_indexes = {index.name for index in audit_table.indexes}
        self.assertTrue({
            "ix_audit_events_project_created",
            "ix_audit_events_project_action_created",
            "ix_audit_events_project_actor_created",
            "ix_audit_events_request_id",
        }.issubset(audit_indexes))

    def test_audit_foreign_keys_preserve_history(self):
        from app.database import Base
        from app.models.access import AuditEvent  # noqa: F401

        foreign_keys = {
            tuple(constraint.column_keys): constraint.ondelete
            for constraint in Base.metadata.tables["audit_events"].foreign_key_constraints
        }
        self.assertEqual(foreign_keys[("project_id",)], "SET NULL")
        self.assertEqual(foreign_keys[("actor_id",)], "SET NULL")


class TestRequestCorrelation(unittest.TestCase):
    def _client(self):
        from app.middleware.request_id import RequestIdMiddleware

        app = FastAPI()
        app.add_middleware(RequestIdMiddleware)

        @app.get("/request-id")
        def request_id(request: Request):
            return {"request_id": str(request.state.request_id)}

        return TestClient(app)

    def test_missing_request_id_is_generated_and_echoed(self):
        with self._client() as client:
            response = client.get("/request-id")

        request_id = uuid.UUID(response.json()["request_id"])
        self.assertEqual(response.headers["X-Request-ID"], str(request_id))

    def test_valid_request_id_is_preserved(self):
        request_id = uuid.uuid4()
        with self._client() as client:
            response = client.get(
                "/request-id",
                headers={"X-Request-ID": str(request_id)},
            )

        self.assertEqual(response.json()["request_id"], str(request_id))
        self.assertEqual(response.headers["X-Request-ID"], str(request_id))

    def test_invalid_request_id_is_replaced(self):
        with self._client() as client:
            response = client.get(
                "/request-id",
                headers={"X-Request-ID": "not-a-uuid"},
            )

        generated = uuid.UUID(response.json()["request_id"])
        self.assertNotEqual(str(generated), "not-a-uuid")
        self.assertEqual(response.headers["X-Request-ID"], str(generated))


class TestAuditRedaction(unittest.TestCase):
    def test_only_allowlisted_fields_are_kept_and_sensitive_values_are_redacted(self):
        from app.services.audit import redact_changes

        result = redact_changes(
            {
                "role": "editor",
                "password": "hidden",
                "nested": {"token": "hidden", "count": 2},
                "params": {"max_attempts": 3},
                "unlisted": "drop-me",
            },
            allowed={"role", "nested", "params", "password"},
        )

        self.assertEqual(
            result,
            {
                "role": "editor",
                "password": "[REDACTED]",
                "nested": {"token": "[REDACTED]", "count": 2},
                "params": {"max_attempts": 3},
            },
        )


if __name__ == "__main__":
    unittest.main()
