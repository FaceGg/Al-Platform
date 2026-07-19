import uuid
import unittest
import os
from types import SimpleNamespace

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.access import ProjectMember
from app.models.project import Project
from app.models.user import User


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


class TestProjectPermissionMatrix(unittest.TestCase):
    PERMISSIONS = {
        "project.read",
        "project.update",
        "project.delete",
        "member.manage",
        "resource.create",
        "resource.update",
        "resource.delete",
        "execution.operate",
        "schedule.manage",
        "schedule.operate",
        "audit.read",
    }
    GRANTS = {
        "owner": PERMISSIONS,
        "editor": {
            "project.read",
            "resource.create",
            "resource.update",
            "resource.delete",
            "execution.operate",
            "schedule.manage",
            "schedule.operate",
        },
        "operator": {
            "project.read",
            "execution.operate",
            "schedule.operate",
        },
        "viewer": {"project.read"},
    }

    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.users = {
            role: User(
                username=f"access-{role}",
                password_hash="hash",
                role="admin" if role == "outsider" else "engineer",
            )
            for role in ("owner", "editor", "operator", "viewer", "outsider")
        }
        self.db.add_all(self.users.values())
        self.db.flush()
        self.project = Project(
            name="Permission matrix",
            owner_id=self.users["owner"].id,
        )
        self.db.add(self.project)
        self.db.flush()
        for role in ("editor", "operator", "viewer"):
            self.db.add(ProjectMember(
                project_id=self.project.id,
                user_id=self.users[role].id,
                role=role,
                created_by=self.users["owner"].id,
            ))
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_every_role_matches_the_frozen_permission_matrix(self):
        from app.services.project_access import (
            ProjectAccessError,
            ProjectAccessService,
        )

        service = ProjectAccessService()
        for role, granted in self.GRANTS.items():
            for permission in self.PERMISSIONS:
                with self.subTest(role=role, permission=permission):
                    if permission in granted:
                        access = service.require(
                            self.db,
                            self.project.id,
                            self.users[role].id,
                            permission,
                        )
                        self.assertEqual(access.role.value, role)
                    else:
                        with self.assertRaises(ProjectAccessError) as raised:
                            service.require(
                                self.db,
                                self.project.id,
                                self.users[role].id,
                                permission,
                            )
                        self.assertFalse(raised.exception.hidden)
                        self.assertEqual(
                            raised.exception.code,
                            "PROJECT_PERMISSION_DENIED",
                        )

    def test_outsider_is_hidden_and_global_admin_does_not_bypass_membership(self):
        from app.services.project_access import (
            ProjectAccessError,
            ProjectAccessService,
        )

        service = ProjectAccessService()
        self.assertIsNone(service.resolve(
            self.db,
            self.project.id,
            self.users["outsider"].id,
        ))
        with self.assertRaises(ProjectAccessError) as raised:
            service.require(
                self.db,
                self.project.id,
                self.users["outsider"].id,
                "project.read",
            )
        self.assertTrue(raised.exception.hidden)
        self.assertEqual(raised.exception.code, "PROJECT_NOT_FOUND")

    def test_owner_precedence_and_accessible_projects_are_not_duplicated(self):
        from app.services.project_access import ProjectAccessService

        self.db.add(ProjectMember(
            project_id=self.project.id,
            user_id=self.users["owner"].id,
            role="viewer",
            created_by=self.users["owner"].id,
        ))
        self.db.commit()
        service = ProjectAccessService()

        access = service.resolve(
            self.db,
            self.project.id,
            self.users["owner"].id,
        )
        projects = service.accessible_project_query(
            self.db,
            self.users["owner"].id,
        ).all()

        self.assertEqual(access.role.value, "owner")
        self.assertEqual([project.id for project in projects], [self.project.id])


class TestAuditedProjectAction(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine)
        self.db = self.session_factory()
        self.owner = User(username="audit-owner", password_hash="hash")
        self.viewer = User(username="audit-viewer", password_hash="hash")
        self.db.add_all([self.owner, self.viewer])
        self.db.flush()
        self.project = Project(name="Audited project", owner_id=self.owner.id)
        self.db.add(self.project)
        self.db.flush()
        self.db.add(ProjectMember(
            project_id=self.project.id,
            user_id=self.viewer.id,
            role="viewer",
            created_by=self.owner.id,
        ))
        self.db.commit()
        self.request = SimpleNamespace(
            state=SimpleNamespace(request_id=uuid.uuid4()),
            client=SimpleNamespace(host="127.0.0.1"),
        )

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _intent(self):
        from app.services.audit import AuditIntent

        return AuditIntent(
            project_id=self.project.id,
            action="project.update",
            resource_type="project",
            resource_id=str(self.project.id),
            changes={"description": "updated", "token": "hidden"},
        )

    def test_success_commits_business_change_and_audit_together(self):
        from app.models.access import AuditEvent
        from app.services.audit import AuditService
        from app.services.project_access import ProjectAccessService

        access = ProjectAccessService().resolve(
            self.db,
            self.project.id,
            self.owner.id,
        )
        with AuditService(self.session_factory).project_action(
            self.db,
            request=self.request,
            actor=self.owner,
            access=access,
            permission="project.update",
            intent=self._intent(),
            allowed_changes={"description", "token"},
        ):
            self.project.description = "updated"

        event = self.db.query(AuditEvent).one()
        self.assertEqual(self.project.description, "updated")
        self.assertEqual(event.result, "success")
        self.assertEqual(event.changes["token"], "[REDACTED]")
        self.assertEqual(event.request_id, self.request.state.request_id)

    def test_failure_rolls_back_business_change_and_records_failed_event(self):
        from app.models.access import AuditEvent
        from app.services.audit import AuditService
        from app.services.project_access import ProjectAccessService

        access = ProjectAccessService().resolve(
            self.db,
            self.project.id,
            self.owner.id,
        )
        with self.assertRaises(RuntimeError):
            with AuditService(self.session_factory).project_action(
                self.db,
                request=self.request,
                actor=self.owner,
                access=access,
                permission="project.update",
                intent=self._intent(),
                allowed_changes={"description"},
            ):
                self.project.description = "must-roll-back"
                raise RuntimeError("database url must not be stored")

        self.db.expire_all()
        event = self.db.query(AuditEvent).one()
        self.assertEqual(self.project.description, "")
        self.assertEqual(event.result, "failed")
        self.assertEqual(event.error_code, "PROJECT_ACTION_FAILED")

    def test_visible_denial_is_recorded_but_hidden_access_is_not(self):
        from app.models.access import AuditEvent
        from app.services.audit import AuditService
        from app.services.project_access import (
            ProjectAccessError,
            ProjectAccessService,
        )

        service = AuditService(self.session_factory)
        viewer_access = ProjectAccessService().resolve(
            self.db,
            self.project.id,
            self.viewer.id,
        )
        with self.assertRaises(ProjectAccessError) as visible:
            with service.project_action(
                self.db,
                request=self.request,
                actor=self.viewer,
                access=viewer_access,
                permission="project.update",
                intent=self._intent(),
                allowed_changes={"description"},
            ):
                self.fail("denied action body must not execute")
        self.assertFalse(visible.exception.hidden)
        self.assertEqual(self.db.query(AuditEvent).one().result, "denied")

        with self.assertRaises(ProjectAccessError) as hidden:
            with service.project_action(
                self.db,
                request=self.request,
                actor=self.viewer,
                access=None,
                permission="project.read",
                intent=self._intent(),
                allowed_changes=set(),
            ):
                self.fail("hidden action body must not execute")
        self.assertTrue(hidden.exception.hidden)
        self.assertEqual(self.db.query(AuditEvent).count(), 1)

    def test_audit_commit_failure_aborts_business_change(self):
        from unittest.mock import Mock

        from app.models.access import AuditEvent
        from app.services.audit import AuditService
        from app.services.project_access import ProjectAccessService

        access = ProjectAccessService().resolve(
            self.db,
            self.project.id,
            self.owner.id,
        )
        original_commit = self.db.commit
        self.db.commit = Mock(side_effect=RuntimeError("audit persistence failed"))
        try:
            with self.assertRaises(RuntimeError):
                with AuditService(self.session_factory).project_action(
                    self.db,
                    request=self.request,
                    actor=self.owner,
                    access=access,
                    permission="project.update",
                    intent=self._intent(),
                    allowed_changes={"description"},
                ):
                    self.project.description = "must-not-commit"
        finally:
            self.db.commit = original_commit

        self.db.expire_all()
        self.assertEqual(self.project.description, "")
        event = self.db.query(AuditEvent).one()
        self.assertEqual(event.result, "failed")
        self.assertEqual(event.error_code, "PROJECT_ACTION_FAILED")


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


@unittest.skipUnless(
    os.getenv("RUN_PROJECT_ACCESS_INTEGRATION") == "1",
    "RUN_PROJECT_ACCESS_INTEGRATION is not enabled",
)
class TestProjectAccessProductionStack(unittest.TestCase):
    def test_postgres_roles_and_audit_transactions(self):
        from app.database import SessionLocal, engine
        from app.models.access import AuditEvent
        from app.services.audit import AuditIntent, AuditService
        from app.services.project_access import ProjectAccessError, ProjectAccessService

        self.assertEqual(engine.dialect.name, "postgresql")
        suffix = uuid.uuid4().hex
        with SessionLocal() as db:
            users = {
                role: User(username=f"production-access-{role}-{suffix}", password_hash="hash")
                for role in ("owner", "editor", "operator", "viewer", "outsider")
            }
            db.add_all(users.values())
            db.flush()
            project = Project(name=f"Production access {suffix}", owner_id=users["owner"].id)
            db.add(project)
            db.flush()
            db.add_all([
                ProjectMember(
                    project_id=project.id,
                    user_id=users[role].id,
                    role=role,
                    created_by=users["owner"].id,
                )
                for role in ("editor", "operator", "viewer")
            ])
            db.commit()
            project_id = project.id
            user_ids = [user.id for user in users.values()]

            service = ProjectAccessService()
            self.assertEqual(service.resolve(db, project_id, users["editor"].id).role.value, "editor")
            self.assertEqual(service.resolve(db, project_id, users["operator"].id).role.value, "operator")
            self.assertEqual(service.resolve(db, project_id, users["viewer"].id).role.value, "viewer")
            self.assertIsNone(service.resolve(db, project_id, users["outsider"].id))

            request = SimpleNamespace(
                state=SimpleNamespace(request_id=uuid.uuid4()),
                client=SimpleNamespace(host="127.0.0.1"),
            )
            audit = AuditService(SessionLocal)
            with audit.project_action(
                db,
                request=request,
                actor=users["editor"],
                access=service.resolve(db, project_id, users["editor"].id),
                permission="resource.update",
                intent=AuditIntent(
                    project_id=project_id,
                    action="production_access.update",
                    resource_type="project",
                    resource_id=str(project_id),
                    changes={"description": "postgres verified"},
                ),
                allowed_changes={"description"},
            ):
                project.description = "postgres verified"

            with self.assertRaises(ProjectAccessError):
                with audit.project_action(
                    db,
                    request=request,
                    actor=users["viewer"],
                    access=service.resolve(db, project_id, users["viewer"].id),
                    permission="resource.update",
                    intent=AuditIntent(
                        project_id=project_id,
                        action="production_access.update",
                        resource_type="project",
                        resource_id=str(project_id),
                    ),
                    allowed_changes=set(),
                ):
                    pass

            events = db.query(AuditEvent).filter(
                AuditEvent.project_id == project_id,
                AuditEvent.action == "production_access.update",
            ).all()
            self.assertEqual({event.result for event in events}, {"success", "denied"})
            self.assertEqual(project.description, "postgres verified")

            db.query(AuditEvent).filter(AuditEvent.project_id == project_id).delete()
            db.delete(project)
            db.flush()
            db.query(User).filter(User.id.in_(user_ids)).delete(synchronize_session=False)
            db.commit()

if __name__ == "__main__":
    unittest.main()
