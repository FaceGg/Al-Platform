"""Week 14 recovery contract tests: watch lease + resourceVersion resume,
backoff/410/fallback polling, restart reconcile, timeout double-channel
single-terminal-write, cancel race and GC."""

import sys
import unittest
import uuid
from datetime import datetime, timedelta, timezone

sys.path.insert(0, ".")

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.models.kubernetes_execution import KubernetesJobRun  # noqa: E402
from app.models.operation import DurableOperation  # noqa: E402
from app.services import kubernetes_cluster as cluster_service  # noqa: E402
from app.services import kubernetes_executor as executor  # noqa: E402
from app.services.kubernetes_client import (  # noqa: E402
    FakeKubernetesClient,
    KubernetesClientError,
)
from app.services.operation_lifecycle import (  # noqa: E402
    claim_operation,
    recover_expired_operations,
)
from app.tasks import celery_app  # noqa: E402
from app.tasks import kubernetes_tasks  # noqa: E402
from tests.utils_week14 import (  # noqa: E402
    apply_job_settings,
    cleanup_job_rows,
    ensure_active_cluster,
    ensure_project,
    ensure_user,
    restore_job_settings,
    submit_payload,
)

Base.metadata.create_all(bind=engine)

CONNECTIVITY = "KUBERNETES_CONNECTIVITY_FAILED"
GONE = "KUBERNETES_GONE"


class FlakyClient:
    """Wraps a fake and raises the queued error codes on get_job before delegating."""

    def __init__(self, inner, failures):
        self._inner = inner
        self._failures = list(failures)

    def get_job(self, name):
        if self._failures:
            code = self._failures.pop(0)
            raise KubernetesClientError(code, code)
        return self._inner.get_job(name)

    def __getattr__(self, item):
        return getattr(self._inner, item)


def _no_sleep(_seconds):
    pass


class TestKubernetesRecovery(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._previous_settings = apply_job_settings()
        cls.admin = ensure_user("w14rec-admin", "admin")
        cls.project = ensure_project("w14rec-project", cls.admin.id)
        cls.cluster = ensure_active_cluster("w14rec-cluster", cls.project.id, cls.admin.id)
        cleanup_job_rows([cls.project.id])

    @classmethod
    def tearDownClass(cls):
        restore_job_settings(cls._previous_settings)

    def setUp(self):
        self.fake = FakeKubernetesClient()
        cluster_service.client_factory = lambda cluster, ref: self.fake
        self.sleeps = []
        self.sleep_fn = self.sleeps.append

    def tearDown(self):
        cluster_service.client_factory = None

    def _submit(self, **overrides):
        db = SessionLocal()
        try:
            body = submit_payload(self.cluster.id, **overrides)
            run, _ = executor.submit_job(
                db,
                project_id=self.project.id,
                cluster=self.cluster,
                credential_ref=None,
                settings=settings_ref(),
                image_ref=body["image_ref"],
                command=body["command"],
                args=body["args"],
                env=body["env"],
                resources=body["resources"],
                timeout_seconds=body["timeout_seconds"],
                idempotency_key=overrides.get("idempotency_key", f"w14-rec-{uuid.uuid4()}"),
                actor_id=self.admin.id,
            )
            _ = (run.id, run.operation_id, run.job_name, run.status)  # load before detach
            db.expunge(run)
            return run
        finally:
            db.close()

    def _reload(self, run) -> KubernetesJobRun:
        db = SessionLocal()
        try:
            return db.get(KubernetesJobRun, run.id)
        finally:
            db.close()

    def _operation_state(self, run):
        db = SessionLocal()
        try:
            return db.get(DurableOperation, run.operation_id).state
        finally:
            db.close()

    def test_01_celery_tasks_registered_with_beat_schedule(self):
        self.assertIn("app.tasks.kubernetes_tasks", celery_app.celery_app.conf.include)
        beat = celery_app.celery_app.conf.beat_schedule
        self.assertEqual("ml_platform.kubernetes_jobs_reconcile", beat["kubernetes-job-reconcile"]["task"])
        self.assertEqual("ml_platform.kubernetes_jobs_gc", beat["kubernetes-job-gc"]["task"])
        for name in (
            "ml_platform.kubernetes_job_submit",
            "ml_platform.kubernetes_job_watch",
            "ml_platform.kubernetes_jobs_reconcile",
            "ml_platform.kubernetes_jobs_gc",
        ):
            self.assertIn(name, celery_app.celery_app.tasks)

    def test_02_watch_claims_lease_and_completes_operation_once(self):
        run = self._submit()
        summary = kubernetes_tasks.watch_job_run(
            SessionLocal(),
            self._reload(run),
            None,
            settings_ref(),
            client=self.fake,
            worker_id="watcher-a",
            max_iterations=1,
            sleep_fn=self.sleep_fn,
        )
        self.assertTrue(summary["claimed"])
        self.assertEqual("running", summary["status"])
        self.assertEqual("running", self._operation_state(run))

        self.fake.jobs[run.job_name].update(
            {"succeeded": 1, "active": 0, "conditions": [{"type": "Complete"}]}
        )
        summary = kubernetes_tasks.watch_job_run(
            SessionLocal(),
            self._reload(run),
            None,
            settings_ref(),
            client=self.fake,
            worker_id="watcher-a",
            max_iterations=3,
            sleep_fn=self.sleep_fn,
        )
        self.assertEqual("succeeded", summary["status"])
        self.assertEqual("completed", self._operation_state(run))

        gets_before = self.fake.call_log.count("get_job")
        summary = kubernetes_tasks.watch_job_run(
            SessionLocal(),
            self._reload(run),
            None,
            settings_ref(),
            client=self.fake,
            worker_id="watcher-b",
            max_iterations=3,
            sleep_fn=self.sleep_fn,
        )
        self.assertFalse(summary["claimed"])
        self.assertEqual(gets_before, self.fake.call_log.count("get_job"))
        self.assertEqual("completed", self._operation_state(run))

    def test_03_watch_backs_off_then_converges(self):
        run = self._submit()
        self.fake.jobs[run.job_name].update(
            {"succeeded": 1, "active": 0, "conditions": [{"type": "Complete"}]}
        )
        flaky = FlakyClient(self.fake, [CONNECTIVITY, CONNECTIVITY])
        summary = kubernetes_tasks.watch_job_run(
            SessionLocal(),
            self._reload(run),
            None,
            settings_ref(),
            client=flaky,
            worker_id="watcher-backoff",
            max_iterations=6,
            sleep_fn=self.sleep_fn,
        )
        self.assertEqual([1, 2], self.sleeps)
        self.assertEqual("succeeded", summary["status"])
        self.assertFalse(summary["fell_back"])

    def test_04_watch_resets_resource_version_on_410_gone(self):
        run = self._submit()
        self.fake.jobs[run.job_name].update(
            {"succeeded": 1, "active": 0, "conditions": [{"type": "Complete"}], "resource_version": "42"}
        )
        flaky = FlakyClient(self.fake, [GONE])
        summary = kubernetes_tasks.watch_job_run(
            SessionLocal(),
            self._reload(run),
            None,
            settings_ref(),
            client=flaky,
            worker_id="watcher-gone",
            since_resource_version="7",
            max_iterations=4,
            sleep_fn=self.sleep_fn,
        )
        self.assertEqual([1], self.sleeps)
        self.assertEqual("succeeded", summary["status"])
        self.assertEqual("42", summary["last_resource_version"])

    def test_05_watch_falls_back_to_bounded_polling(self):
        run = self._submit()
        flaky = FlakyClient(self.fake, [CONNECTIVITY] * 99)
        summary = kubernetes_tasks.watch_job_run(
            SessionLocal(),
            self._reload(run),
            None,
            settings_ref(),
            client=flaky,
            worker_id="watcher-fallback",
            max_iterations=5,
            fallback_after=2,
            sleep_fn=self.sleep_fn,
        )
        self.assertEqual([1, 30, 30, 30, 30], self.sleeps)
        self.assertTrue(summary["fell_back"])
        self.assertEqual("submitted", summary["status"])

    def test_06_watch_tracks_cluster_resource_version(self):
        run = self._submit()
        self.fake.jobs[run.job_name]["resource_version"] = "42"
        summary = kubernetes_tasks.watch_job_run(
            SessionLocal(),
            self._reload(run),
            None,
            settings_ref(),
            client=self.fake,
            worker_id="watcher-rv",
            max_iterations=1,
            sleep_fn=self.sleep_fn,
        )
        self.assertEqual("42", summary["last_resource_version"])
        summary = kubernetes_tasks.watch_job_run(
            SessionLocal(),
            self._reload(run),
            None,
            settings_ref(),
            client=self.fake,
            worker_id="watcher-rv",
            since_resource_version="42",
            max_iterations=1,
            sleep_fn=self.sleep_fn,
        )
        self.assertTrue(summary["claimed"])
        self.assertEqual("42", summary["last_resource_version"])

    def test_07_expired_lease_is_recovered_and_reclaimable(self):
        run = self._submit()
        db = SessionLocal()
        try:
            self.assertTrue(claim_operation(db, run.operation_id, "worker-a", 30))
            operation = db.get(DurableOperation, run.operation_id)
            operation.lease_expires_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=5)
            db.commit()
        finally:
            db.close()
        recovered = recover_expired_operations(SessionLocal(), worker_id="recovery", lease_seconds=30)
        self.assertIn(str(run.operation_id), {str(op_id) for op_id in recovered})

        # Recovery now holds a live lease: expire it again so watcher-b can claim.
        db = SessionLocal()
        try:
            operation = db.get(DurableOperation, run.operation_id)
            operation.lease_expires_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=5)
            db.commit()
        finally:
            db.close()
        self.fake.jobs[run.job_name]["resource_version"] = "9"
        summary = kubernetes_tasks.watch_job_run(
            SessionLocal(),
            self._reload(run),
            None,
            settings_ref(),
            client=self.fake,
            worker_id="watcher-b",
            max_iterations=1,
            sleep_fn=self.sleep_fn,
        )
        self.assertTrue(summary["claimed"])
        self.assertEqual("running", self._operation_state(run))

    def test_08_worker_restart_reconciles_non_terminal_rows(self):
        ok_run = self._submit()
        self.fake.jobs[ok_run.job_name].update(
            {"succeeded": 1, "active": 0, "conditions": [{"type": "Complete"}]}
        )
        self.fake.fail_code = "KUBERNETES_TIMEOUT"
        stuck_run = self._submit()
        self.fake.fail_code = None

        db = SessionLocal()
        try:
            results = kubernetes_tasks.reconcile_non_terminal_jobs(db, None, settings_ref(), client=self.fake)
        finally:
            db.close()
        self.assertEqual("succeeded", results[str(ok_run.id)])
        self.assertEqual("submitted", results[str(stuck_run.id)])
        self.assertEqual("completed", self._operation_state(ok_run))

    def test_09_timeout_dual_channel_writes_terminal_once(self):
        run = self._submit()
        db = SessionLocal()
        try:
            stored = db.get(KubernetesJobRun, run.id)
            stored.submitted_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
                seconds=stored.timeout_seconds + 120
            )
            db.commit()
        finally:
            db.close()
        self.fake.jobs[run.job_name].update(
            {"active": 0, "failed": 1, "conditions": [{"type": "Failed", "reason": "DeadlineExceeded"}]}
        )

        timed_out = kubernetes_tasks.mark_timed_out_jobs(SessionLocal())
        self.assertIn(str(run.id), timed_out)
        first = self._reload(run)
        self.assertEqual("timed_out", first.status)
        self.assertEqual("KUBE_JOB_TIMEOUT", first.error_code)
        self.assertEqual("failed", self._operation_state(run))
        finished_once = first.finished_at

        executor.reconcile_job(SessionLocal(), self._reload(run), None, settings_ref(), client=self.fake)
        second = self._reload(run)
        self.assertEqual("timed_out", second.status)
        self.assertEqual(finished_once, second.finished_at)

    def test_10_cancel_then_reconcile_never_becomes_orphaned(self):
        run = self._submit()
        executor.cancel_job(SessionLocal(), self._reload(run), None, settings_ref(), reason="stop")
        self.fake.jobs[run.job_name]["deleted"] = True
        executor.reconcile_job(SessionLocal(), self._reload(run), None, settings_ref(), client=self.fake)
        stored = self._reload(run)
        self.assertEqual("cancelled", stored.status)
        self.assertNotEqual("orphaned", stored.status)

    def test_11_gc_deletes_only_finished_jobs_past_ttl(self):
        fresh = self._submit()
        old = self._submit()
        self.fake.jobs[fresh.job_name].update(
            {"succeeded": 1, "active": 0, "conditions": [{"type": "Complete"}]}
        )
        self.fake.jobs[old.job_name].update(
            {"succeeded": 1, "active": 0, "conditions": [{"type": "Complete"}]}
        )
        executor.reconcile_job(SessionLocal(), self._reload(fresh), None, settings_ref(), client=self.fake)
        executor.reconcile_job(SessionLocal(), self._reload(old), None, settings_ref(), client=self.fake)
        db = SessionLocal()
        try:
            cutoff_old = db.get(KubernetesJobRun, old.id)
            cutoff_old.finished_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
                seconds=settings_ref().kubernetes_job_ttl_seconds_finished + 60
            )
            db.commit()
        finally:
            db.close()
        deleted = kubernetes_tasks.gc_finished_jobs(SessionLocal(), None, settings_ref(), client=self.fake)
        self.assertEqual(1, deleted)
        self.assertTrue(self.fake.jobs[old.job_name]["deleted"])
        stored_fresh = self._reload(fresh)
        self.assertEqual("succeeded", stored_fresh.status)
        self.assertFalse(self.fake.jobs[fresh.job_name]["deleted"])


def settings_ref():
    from app.config import settings

    return settings


if __name__ == "__main__":
    unittest.main()
