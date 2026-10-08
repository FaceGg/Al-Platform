"""Week 14 log contract tests: cursor pagination, bounded chunks, UTF-8
replacement decoding, redaction and end-of-stream semantics."""

import sys
import unittest
import uuid

sys.path.insert(0, ".")

from app.config import settings  # noqa: E402

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.services import kubernetes_cluster as cluster_service  # noqa: E402
from app.services import kubernetes_executor as executor  # noqa: E402
from app.services.kubernetes_client import FakeKubernetesClient  # noqa: E402
from tests.utils_week14 import (  # noqa: E402
    apply_job_settings,
    cleanup_job_rows,
    ensure_active_cluster,
    ensure_project,
    ensure_user,
    restore_job_settings,
)

Base.metadata.create_all(bind=engine)


class TestKubernetesLogs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._previous_settings = apply_job_settings()
        cls.admin = ensure_user("w14logs-admin", "admin")
        cls.project = ensure_project("w14logs-project", cls.admin.id)
        cls.cluster = ensure_active_cluster("w14logs-cluster", cls.project.id, cls.admin.id)
        cleanup_job_rows([cls.project.id])

    @classmethod
    def tearDownClass(cls):
        restore_job_settings(cls._previous_settings)

    def setUp(self):
        self.fake = FakeKubernetesClient()
        cluster_service.client_factory = lambda cluster, ref: self.fake
        self._previous_chunk = settings.kubernetes_job_log_chunk_bytes
        settings.kubernetes_job_log_chunk_bytes = 16

    def tearDown(self):
        cluster_service.client_factory = None
        settings.kubernetes_job_log_chunk_bytes = self._previous_chunk

    def _submit_run(self):
        from tests.utils_week14 import submit_payload

        db = SessionLocal()
        try:
            body = submit_payload(self.cluster.id)
            run, _ = executor.submit_job(
                db,
                project_id=self.project.id,
                cluster=self.cluster,
                credential_ref=None,
                settings=settings,
                image_ref=body["image_ref"],
                command=body["command"],
                args=body["args"],
                env=body["env"],
                resources=body["resources"],
                timeout_seconds=body["timeout_seconds"],
                idempotency_key=f"w14-logs-{uuid.uuid4()}",
                actor_id=self.admin.id,
            )
            _ = (run.id, run.operation_id, run.job_name, run.status)  # load before detach
            db.expunge(run)
            return run
        finally:
            db.close()

    def _read(self, run, cursor=0, limit_bytes=None):
        return executor.read_logs(
            self.cluster, None, settings, run, cursor=cursor, limit_bytes=limit_bytes
        )

    def test_01_cursor_pagination_returns_bounded_chunks(self):
        run = self._submit_run()
        self.fake.pod_logs[f"{run.job_name}-pod-1"] = "0123456789" * 4  # 40 ascii bytes

        first = self._read(run, cursor=0)
        self.assertEqual(16, len(first["text"]))
        self.assertEqual(16, first["next_cursor"])
        self.assertFalse(first["end_of_stream"])

        second = self._read(run, cursor=first["next_cursor"])
        self.assertEqual(16, len(second["text"]))
        self.assertEqual(32, second["next_cursor"])

        third = self._read(run, cursor=second["next_cursor"])
        self.assertEqual(8, len(third["text"]))
        self.assertEqual(40, third["next_cursor"])
        # Job is still active: no end-of-stream even though the buffer is drained.
        self.assertFalse(third["end_of_stream"])

    def test_02_end_of_stream_only_after_terminal_state(self):
        run = self._submit_run()
        self.fake.pod_logs[f"{run.job_name}-pod-1"] = "abcdefgh" * 5  # 40 bytes
        middle = self._read(run, cursor=0)
        self.assertFalse(middle["end_of_stream"], "full chunk at terminal implies more data")

        self.fake.jobs[run.job_name].update(
            {"succeeded": 1, "active": 0, "conditions": [{"type": "Complete"}]}
        )
        tail = self._read(run, cursor=40)
        self.assertEqual("", tail["text"])
        self.assertTrue(tail["end_of_stream"])

        full_chunk = self._read(run, cursor=0)
        self.assertEqual(16, len(full_chunk["text"]))
        self.assertFalse(full_chunk["end_of_stream"], "full chunk means data remains")

    def test_03_multibyte_split_decodes_with_replacement_not_error(self):
        run = self._submit_run()
        self.fake.pod_logs[f"{run.job_name}-pod-1"] = "你好世界" * 5
        result = self._read(run, cursor=0, limit_bytes=4)
        self.assertIn("\ufffd", result["text"])
        self.assertEqual(4, result["next_cursor"])

    def test_04_logs_are_redacted_before_return(self):
        run = self._submit_run()
        settings.kubernetes_job_log_chunk_bytes = 4096
        try:
            secret = "Bearer eyJhbGciOiJIUzI1NiJ9.supersecret.signature"
            filler = "A" * 40
            self.fake.pod_logs[f"{run.job_name}-pod-1"] = f"boot ok {secret} leak {filler}"
            result = self._read(run, cursor=0, limit_bytes=4096)
        finally:
            settings.kubernetes_job_log_chunk_bytes = self._previous_chunk
        self.assertIn("boot ok", result["text"])
        self.assertNotIn("supersecret", result["text"])
        self.assertNotIn(filler, result["text"])
        self.assertIn("[redacted]", result["text"])

    def test_05_pod_vanished_returns_buffered_tail(self):
        run = self._submit_run()
        self.fake.jobs[run.job_name].update(
            {"succeeded": 1, "active": 0, "conditions": [{"type": "Complete"}]}
        )
        self.fake.job_pods = []
        result = self._read(run, cursor=0)
        self.assertEqual("", result["text"])
        self.assertTrue(result["end_of_stream"])

    def test_06_request_limit_is_capped_by_settings(self):
        run = self._submit_run()
        self.fake.pod_logs[f"{run.job_name}-pod-1"] = "z" * 500
        result = self._read(run, cursor=0, limit_bytes=1000)
        self.assertLessEqual(len(result["text"]), 16)
        self.assertLessEqual(result["next_cursor"], 16)


if __name__ == "__main__":
    unittest.main()
