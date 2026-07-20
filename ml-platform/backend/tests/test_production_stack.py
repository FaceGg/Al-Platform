import os
import tempfile
import time
import unittest
import uuid
from datetime import timedelta
from pathlib import Path

from redis import Redis
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

import app.main  # noqa: F401 (load the complete production model graph)
from app.config import settings
from app.database import Base, SessionLocal, engine
from app.models.project import Project
from app.models.run import WorkflowRun
from app.models.user import User
from app.models.workflow import Workflow, WorkflowNode
from app.services.readiness_service import ReadinessService
from app.storage.minio import MinioStorage
from app.tasks.celery_app import celery_app
from app.tasks.recovery import reconcile_stale_runs
from app.tasks.workflow_tasks import execute_workflow_task, utcnow
from tools.migrate_database import copy_database


@unittest.skipUnless(
    os.getenv("RUN_PRODUCTION_INTEGRATION") == "1",
    "RUN_PRODUCTION_INTEGRATION is not enabled",
)
class TestProductionStack(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._reset_business_tables()
        cls.redis = Redis.from_url(
            settings.redis_events_url.get_secret_value(),
            decode_responses=False,
        )
        cls.storage = MinioStorage.from_settings(settings)
        cls.migration_result = cls._migrate_sqlite_fixture()
        cls.user_id = cls._migration_user_id

    @classmethod
    def tearDownClass(cls):
        cls.redis.close()

    @classmethod
    def _reset_business_tables(cls):
        table_names = [
            name
            for name in inspect(engine).get_table_names()
            if name != "alembic_version"
        ]
        if not table_names:
            return
        preparer = engine.dialect.identifier_preparer
        quoted = ", ".join(preparer.quote(name) for name in table_names)
        with engine.begin() as connection:
            connection.exec_driver_sql(
                f"TRUNCATE TABLE {quoted} RESTART IDENTITY CASCADE",
            )

    @classmethod
    def _migrate_sqlite_fixture(cls):
        source_engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(source_engine)
        source_session = sessionmaker(bind=source_engine)()
        try:
            user = User(
                username=f"production-migration-{uuid.uuid4().hex}",
                password_hash="integration-only-hash",
                role="admin",
            )
            source_session.add(user)
            source_session.commit()
            cls._migration_user_id = user.id
        finally:
            source_session.close()

        first = copy_database(source_engine, engine)
        second = copy_database(source_engine, engine)
        source_engine.dispose()
        cls._second_migration_result = second
        return first

    @staticmethod
    def _wait_for_run(run_id, statuses, timeout=30):
        deadline = time.monotonic() + timeout
        last = None
        while time.monotonic() < deadline:
            with SessionLocal() as db:
                last = db.query(WorkflowRun).filter(
                    WorkflowRun.id == run_id,
                ).first()
                if last is not None and last.status in statuses:
                    list(last.node_runs)
                    db.expunge(last)
                    return last
            time.sleep(0.2)
        raise AssertionError(
            f"Run {run_id} did not reach {sorted(statuses)}; "
            f"last status was {getattr(last, 'status', None)}",
        )

    @classmethod
    def _create_run(cls, operator_id="condition", params=None):
        with SessionLocal() as db:
            project = Project(
                name=f"production-project-{uuid.uuid4().hex}",
                owner_id=cls.user_id,
            )
            db.add(project)
            db.flush()
            workflow = Workflow(
                project_id=project.id,
                name="Production integration workflow",
                created_by=cls.user_id,
            )
            db.add(workflow)
            db.flush()
            node = WorkflowNode(
                workflow_id=workflow.id,
                operator_id=operator_id,
                label="Production node",
                position_x=0,
                position_y=0,
                params=params or {},
            )
            db.add(node)
            run = WorkflowRun(
                workflow_id=workflow.id,
                status="pending",
                triggered_by=cls.user_id,
            )
            db.add(run)
            db.commit()
            return run.id

    def test_01_database_transfer_is_idempotent(self):
        with engine.connect() as connection:
            self.assertEqual(connection.exec_driver_sql("SELECT 1").scalar(), 1)
        self.assertEqual(self.migration_result["users"].inserted_count, 1)
        self.assertEqual(
            self._second_migration_result["users"].inserted_count,
            0,
        )
        self.assertFalse(self._second_migration_result["users"].mismatched_ids)

    def test_02_minio_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "production-integration.txt"
            source.write_text("production-integration", encoding="utf-8")
            stored = self.storage.put(
                source,
                "integration",
                uuid.uuid4().hex,
                source.name,
            )
            try:
                self.assertTrue(
                    self.storage.verify(stored.uri, stored.sha256, stored.size),
                )
            finally:
                self.storage.delete(stored.uri)

    def test_03_celery_executes_once_and_publishes_redis_event(self):
        run_id = self._create_run()
        pubsub = self.redis.pubsub()
        pubsub.psubscribe(f"ml-platform:runs:{run_id}")
        pubsub.get_message(timeout=2)
        try:
            first_task = execute_workflow_task.delay(str(run_id))
            completed = self._wait_for_run(run_id, {"completed"})
            self.assertTrue(completed.node_runs)
            self.assertTrue(
                all(node.status == "completed" for node in completed.node_runs),
            )

            event = None
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                message = pubsub.get_message(
                    ignore_subscribe_messages=True,
                    timeout=1,
                )
                if message and b'"type": "run_completed"' in message["data"]:
                    event = message
                    break
            self.assertIsNotNone(event, "Redis run_completed event was not published")
            self.assertEqual(first_task.get(timeout=10)["status"], "completed")

            duplicate = execute_workflow_task.delay(str(run_id)).get(timeout=10)
            self.assertEqual(duplicate["status"], "skipped")
            with SessionLocal() as db:
                self.assertEqual(
                    db.query(WorkflowRun).filter(WorkflowRun.id == run_id).one().status,
                    "completed",
                )
        finally:
            pubsub.close()

    def test_04_timeout_recovery_and_readiness(self):
        timeout_run_id = self._create_run(
            operator_id="execute_python",
            params={
                "script": "import time\ntime.sleep(1)\nresult = []",
                "timeout_seconds": 0.1,
            },
        )
        execute_workflow_task.delay(str(timeout_run_id))
        timed_out = self._wait_for_run(timeout_run_id, {"failed"})
        self.assertEqual(timed_out.error_code, "NODE_TIMED_OUT")

        with SessionLocal() as db:
            stale = WorkflowRun(
                workflow_id=timed_out.workflow_id,
                status="running",
                task_id="missing-task",
                worker_id="lost-worker",
                heartbeat_at=utcnow() - timedelta(minutes=10),
            )
            cancelled = WorkflowRun(
                workflow_id=timed_out.workflow_id,
                status="cancel_requested",
                task_id="cancelled-task",
                worker_id="lost-worker",
                heartbeat_at=utcnow() - timedelta(minutes=10),
            )
            db.add_all([stale, cancelled])
            db.commit()
            self.assertEqual(
                reconcile_stale_runs(db, set(), timedelta(minutes=5)),
                2,
            )
            self.assertEqual(stale.status, "failed")
            self.assertEqual(stale.error_code, "TASK_HARD_TIMEOUT")
            self.assertEqual(cancelled.status, "cancelled")

        readiness = ReadinessService(
            engine,
            settings,
            redis_client=self.redis,
            celery_app=celery_app,
            storage=self.storage,
        ).check_all()
        self.assertTrue(readiness["ready"], readiness)
        self.assertTrue(all(
            readiness[name]["ready"]
            for name in ("database", "redis", "celery", "storage")
        ))


if __name__ == "__main__":
    unittest.main()
