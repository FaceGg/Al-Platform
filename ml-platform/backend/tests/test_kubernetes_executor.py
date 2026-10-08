"""Week 14 executor contract tests: deterministic naming, hardened manifest,
idempotent database-first submission and the terminal-guarded state machine."""

import sys
import unittest
import uuid

sys.path.insert(0, ".")

from sqlalchemy.exc import IntegrityError  # noqa: E402

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.models.kubernetes_execution import KubernetesJobRun  # noqa: E402
from app.models.operation import DurableOperation  # noqa: E402
from app.services import kubernetes_cluster as cluster_service  # noqa: E402
from app.services import kubernetes_executor as executor  # noqa: E402
from app.services.kubernetes_client import (  # noqa: E402
    FakeKubernetesClient,
    _job_labels,
    build_job_manifest,
)
from tests.utils_week14 import (  # noqa: E402
    apply_job_settings,
    cleanup_job_rows,
    ensure_active_cluster,
    ensure_project,
    ensure_user,
    restore_job_settings,
    submit_payload,
    TEST_IMAGE,
)

Base.metadata.create_all(bind=engine)


class DatabaseFirstKubernetesClient(FakeKubernetesClient):
    """Fake that records whether the durable row is visible when create_job runs."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.row_visible_at_create: bool | None = None

    def create_job(self, manifest: dict) -> dict:
        probe = SessionLocal()
        try:
            row = probe.query(KubernetesJobRun).filter(KubernetesJobRun.job_name == manifest["metadata"]["name"]).first()
            self.row_visible_at_create = row is not None and row.status == "queued"
        finally:
            probe.close()
        return super().create_job(manifest)


class TestKubernetesExecutor(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._previous_settings = apply_job_settings()
        cls.admin = ensure_user("w14exec-admin", "admin")
        cls.project = ensure_project("w14exec-project", cls.admin.id)
        cls.cluster = ensure_active_cluster("w14exec-cluster", cls.project.id, cls.admin.id)
        cleanup_job_rows([cls.project.id])

    @classmethod
    def tearDownClass(cls):
        restore_job_settings(cls._previous_settings)

    def setUp(self):
        self.fake = DatabaseFirstKubernetesClient()
        cluster_service.client_factory = lambda cluster, ref: self.fake

    def tearDown(self):
        cluster_service.client_factory = None

    def _submit(self, **overrides):
        db = SessionLocal()
        try:
            body = submit_payload(self.cluster.id, **overrides)
            run, replayed = executor.submit_job(
                db,
                project_id=self.project.id,
                cluster=self.cluster,
                credential_ref=None,
                settings=settings_proxy(),
                image_ref=body["image_ref"],
                command=body["command"],
                args=body["args"],
                env=body["env"],
                resources=body["resources"],
                timeout_seconds=body["timeout_seconds"],
                idempotency_key=overrides.get("idempotency_key", f"w14-exec-{uuid.uuid4()}"),
                actor_id=self.admin.id,
            )
            _ = (run.id, run.operation_id, run.job_name, run.status, run.error_code)  # load before detach
            db.expunge(run)
            return run, replayed
        finally:
            db.close()

    def _reload(self, run) -> KubernetesJobRun:
        db = SessionLocal()
        try:
            return db.get(KubernetesJobRun, run.id)
        finally:
            db.close()

    def _operation(self, run) -> DurableOperation:
        db = SessionLocal()
        try:
            return db.get(DurableOperation, run.operation_id)
        finally:
            db.close()

    def test_01_deterministic_job_name_same_operation_same_revision(self):
        operation_id = uuid.uuid4()
        other_id = uuid.uuid4()
        name_a = executor.job_name_for(self.project.id, operation_id, 1)
        self.assertEqual(name_a, executor.job_name_for(self.project.id, operation_id, 1))
        self.assertTrue(executor.JOB_NAME_PATTERN.match(name_a), name_a)
        self.assertNotEqual(name_a, executor.job_name_for(self.project.id, other_id, 1))
        self.assertNotEqual(name_a, executor.job_name_for(self.project.id, operation_id, 2))

    def _submit_with_fixed_key(self):
        return self._submit(idempotency_key="w14-exec-deterministic")

    def test_01b_replayed_submission_reuses_the_same_job_name(self):
        first, _ = self._submit_with_fixed_key()
        second, replayed = self._submit_with_fixed_key()
        self.assertTrue(replayed)
        self.assertEqual(first.job_name, second.job_name)

    def test_02_manifest_is_security_hardened(self):
        labels = _job_labels(self.project.id, uuid.uuid4(), 3)
        manifest = build_job_manifest(
            job_name="lr-aaaaaaaa-job-bbbbbbbb-3",
            namespace="w14-jobs",
            image_ref=TEST_IMAGE,
            command=["/bin/sh", "-c"],
            args=["echo hi"],
            env={"W14_MODE": "fast"},
            resources={"cpu_cores": 2, "memory_gb": 4},
            timeout_seconds=90,
            labels=labels,
            ttl_seconds_finished=3600,
        )
        spec = manifest["spec"]
        self.assertEqual(0, spec["backoffLimit"])
        self.assertEqual(90, spec["activeDeadlineSeconds"])
        self.assertEqual(3600, spec["ttlSecondsAfterFinished"])
        pod_spec = spec["template"]["spec"]
        self.assertEqual("Never", pod_spec["restartPolicy"])
        self.assertFalse(pod_spec["automountServiceAccountToken"])
        for forbidden in ("hostNetwork", "hostPID", "hostIPC", "serviceAccountName", "volumes"):
            self.assertNotIn(forbidden, pod_spec)
        container = pod_spec["containers"][0]
        self.assertNotIn("securityContext", container)
        self.assertNotIn("ports", container)
        self.assertEqual(TEST_IMAGE, container["image"])
        for key, value in labels.items():
            self.assertEqual(value, manifest["metadata"]["labels"][key])
            self.assertEqual(value, spec["template"]["metadata"]["labels"][key])

    def test_03_image_must_be_digest_and_allowlisted(self):
        with self.assertRaises(executor.KubeJobError) as raised:
            executor.validate_image_ref("registry.local/w14-demo:latest", ["registry.local/"])
        self.assertEqual("KUBE_JOB_IMAGE_INVALID", raised.exception.code)
        with self.assertRaises(executor.KubeJobError) as raised:
            executor.validate_image_ref("evil.example.com/app@sha256:" + "a" * 64, ["registry.local/"])
        self.assertEqual("KUBE_JOB_IMAGE_FORBIDDEN", raised.exception.code)
        self.assertEqual(
            TEST_IMAGE,
            executor.validate_image_ref(TEST_IMAGE, ["registry.local/"]),
        )

    def test_04_env_resource_timeout_and_binding_rejections(self):
        with self.assertRaises(executor.KubeJobError) as raised:
            executor.validate_env({"W14_MODE": "fast", "INJECT": "1"}, ["W14_MODE"])
        self.assertEqual("KUBE_JOB_ENV_FORBIDDEN", raised.exception.code)
        with self.assertRaises(executor.KubeJobError) as raised:
            executor.validate_resources({"cpu_cores": 17, "memory_gb": 1}, settings_proxy())
        self.assertEqual("KUBE_JOB_RESOURCES_INVALID", raised.exception.code)
        with self.assertRaises(executor.KubeJobError) as raised:
            executor.validate_resources({"cpu_cores": 1, "memory_gb": 999}, settings_proxy())
        self.assertEqual("KUBE_JOB_RESOURCES_INVALID", raised.exception.code)
        with self.assertRaises(executor.KubeJobError) as raised:
            executor.validate_timeout(999999, settings_proxy())
        self.assertEqual("KUBE_JOB_TIMEOUT_INVALID", raised.exception.code)
        with self.assertRaises(executor.KubeJobError) as raised:
            executor.validate_bindings([{"artifact": "a"}], [])
        self.assertEqual(executor.BINDINGS_UNSUPPORTED, raised.exception.code)
        with self.assertRaises(executor.KubeJobError) as raised:
            executor.validate_command([], [])
        self.assertEqual("KUBE_JOB_COMMAND_INVALID", raised.exception.code)

    def test_05_submit_is_database_first(self):
        run, replayed = self._submit()
        self.assertFalse(replayed)
        self.assertTrue(self.fake.row_visible_at_create, "durable row must commit before create_job")
        self.assertEqual("submitted", run.status)
        self.assertTrue(self.fake.jobs.get(run.job_name))

    def test_06_cluster_failure_keeps_retryable_row(self):
        self.fake.fail_code = "KUBERNETES_TIMEOUT"
        run, replayed = self._submit()
        self.assertFalse(replayed)
        stored = self._reload(run)
        self.assertEqual("queued", stored.status)
        self.assertEqual("KUBERNETES_SUBMIT_FAILED", stored.error_code)

    def test_07_replay_returns_same_row_without_new_cluster_object(self):
        key = "w14-replay-key"
        first, first_replayed = self._submit(idempotency_key=key)
        creates_before = self.fake.call_log.count("create_job")
        second, second_replayed = self._submit(idempotency_key=key)
        self.assertFalse(first_replayed)
        self.assertTrue(second_replayed)
        self.assertEqual(first.id, second.id)
        self.assertEqual(creates_before, self.fake.call_log.count("create_job"))
        db = SessionLocal()
        try:
            total = (
                db.query(KubernetesJobRun)
                .filter(
                    KubernetesJobRun.project_id == self.project.id,
                    KubernetesJobRun.idempotency_key == key,
                )
                .count()
            )
            self.assertEqual(1, total)
        finally:
            db.close()

    def test_08_env_values_are_not_persisted_verbatim(self):
        secret = "w14-super-secret-value"
        run, _ = self._submit(env={"W14_MODE": secret})
        stored = self._reload(run)
        self.assertEqual({"W14_MODE": len(secret)}, stored.env_json)
        self.assertNotIn(secret, str(stored.env_json))

    def test_09_reconcile_maps_lifecycle_and_settles_operation(self):
        run, _ = self._submit()
        operation = self._operation(run)
        self.assertEqual("queued", operation.state)

        run = self._reload(run)
        executor.reconcile_job(
            SessionLocal(), run, None, settings_proxy(), client=self.fake
        )
        stored = self._reload(run)
        self.assertEqual("running", stored.status)
        self.assertIsNotNone(stored.started_at)

        self.fake.jobs[run.job_name].update(
            {"succeeded": 1, "active": 0, "conditions": [{"type": "Complete"}]}
        )
        executor.reconcile_job(SessionLocal(), self._reload(run), None, settings_proxy(), client=self.fake)
        stored = self._reload(run)
        self.assertEqual("succeeded", stored.status)
        self.assertEqual(0, stored.exit_code)
        operation = self._operation(run)
        self.assertEqual("completed", operation.state)

        # A later failure event in the cluster must not reopen the terminal state.
        self.fake.jobs[run.job_name].update(
            {"succeeded": 0, "failed": 1, "conditions": [{"type": "Failed", "reason": "BackoffLimitExceeded"}]}
        )
        executor.reconcile_job(SessionLocal(), self._reload(run), None, settings_proxy(), client=self.fake)
        stored = self._reload(run)
        self.assertEqual("succeeded", stored.status)
        self.assertEqual("completed", self._operation(run).state)

    def test_10_reconcile_maps_failed_and_timed_out(self):
        run, _ = self._submit()
        self.fake.jobs[run.job_name].update(
            {"active": 0, "failed": 1, "conditions": [{"type": "Failed", "reason": "BackoffLimitExceeded", "message": "boom"}]}
        )
        executor.reconcile_job(SessionLocal(), self._reload(run), None, settings_proxy(), client=self.fake)
        stored = self._reload(run)
        self.assertEqual("failed", stored.status)
        self.assertEqual("KUBE_JOB_FAILED", stored.error_code)
        self.assertEqual("failed", self._operation(run).state)

        run2, _ = self._submit()
        self.fake.jobs[run2.job_name].update(
            {"active": 0, "failed": 1, "conditions": [{"type": "Failed", "reason": "DeadlineExceeded"}]}
        )
        executor.reconcile_job(SessionLocal(), self._reload(run2), None, settings_proxy(), client=self.fake)
        stored2 = self._reload(run2)
        self.assertEqual("timed_out", stored2.status)
        self.assertEqual("KUBE_JOB_TIMEOUT", stored2.error_code)

    def test_11_job_disappears_maps_orphaned(self):
        run, _ = self._submit()
        self.fake.jobs[run.job_name]["deleted"] = True
        executor.reconcile_job(SessionLocal(), self._reload(run), None, settings_proxy(), client=self.fake)
        stored = self._reload(run)
        self.assertEqual("orphaned", stored.status)
        self.assertEqual("KUBE_JOB_ORPHANED", stored.error_code)

    def test_12_queued_run_resubmits_on_reconcile(self):
        self.fake.fail_code = "KUBERNETES_TIMEOUT"
        run, _ = self._submit()
        self.fake.fail_code = None
        executor.reconcile_job(SessionLocal(), self._reload(run), None, settings_proxy(), client=self.fake)
        stored = self._reload(run)
        self.assertEqual("submitted", stored.status)
        self.assertIsNone(stored.error_code)

    def test_13_terminal_guard_blocks_late_writes(self):
        run, _ = self._submit()
        stored = self._reload(run)
        self.assertTrue(
            executor._set_terminal(stored, "failed", error_code="KUBE_JOB_FAILED", detail="late")
        )
        self.assertFalse(
            executor._set_terminal(stored, "succeeded", error_code=None, detail="very late")
        )
        self.assertEqual("failed", stored.status)

    def test_14_cancel_lifecycle(self):
        run, _ = self._submit()
        db = SessionLocal()
        try:
            run = executor.cancel_job(
                db, self._reload(run), None, settings_proxy(), reason="user stop"
            )
            _ = (run.id, run.status, run.job_name)  # load before detach
            db.expunge(run)
        finally:
            db.close()
        self.assertEqual("cancelled", run.status)
        self.assertTrue(self.fake.jobs[run.job_name]["deleted"])
        operation = self._operation(run)
        self.assertEqual("failed", operation.state)
        self.assertEqual("KUBE_JOB_CANCELLED", operation.error_code)
        with self.assertRaises(executor.KubeJobError) as raised:
            executor.cancel_job(SessionLocal(), self._reload(run), None, settings_proxy(), reason="again")
        self.assertEqual(409, raised.exception.status)
        self.assertEqual("KUBE_JOB_ALREADY_TERMINAL", raised.exception.code)

    def test_15_cancel_cluster_failure_is_not_a_fake_success(self):
        run, _ = self._submit()
        self.fake.fail_code = "KUBERNETES_TIMEOUT"
        with self.assertRaises(executor.KubeJobError) as raised:
            executor.cancel_job(SessionLocal(), self._reload(run), None, settings_proxy(), reason="stop")
        self.assertEqual(502, raised.exception.status)
        self.assertEqual("submitted", self._reload(run).status)

    def test_16_operation_id_and_idempotency_are_unique(self):
        run, _ = self._submit()
        db = SessionLocal()
        try:
            stored = db.get(KubernetesJobRun, run.id)
            duplicate = KubernetesJobRun(
                project_id=stored.project_id,
                cluster_id=stored.cluster_id,
                namespace=stored.namespace,
                operation_id=stored.operation_id,
                idempotency_key="other-key",
                job_name="lr-aaaaaaaa-job-bbbbbbbb-9",
                image_ref=TEST_IMAGE,
                timeout_seconds=60,
                created_by=self.admin.id,
            )
            db.add(duplicate)
            with self.assertRaises(IntegrityError):
                db.flush()
            db.rollback()
        finally:
            db.close()


def settings_proxy():
    from app.config import settings

    return settings


if __name__ == "__main__":
    unittest.main()
