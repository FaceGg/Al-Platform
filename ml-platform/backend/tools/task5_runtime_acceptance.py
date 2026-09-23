"""Exercise Task 5 with a real Redis broker and killable Celery processes."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--broker", default="redis://127.0.0.1:6395/0")
    args = parser.parse_args()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=False)
    backend = Path(__file__).resolve().parents[1]
    repo = backend.parents[1]
    sys.path.insert(0, str(backend))
    database = output / "runtime.db"
    os.environ.update(
        DATABASE_URL=f"sqlite:///{database.as_posix()}",
        TASK_BACKEND="celery",
        CELERY_BROKER_URL=args.broker,
        CELERY_RESULT_BACKEND=args.broker,
        ARTIFACT_STORAGE_BACKEND="local",
        ARTIFACT_STORAGE_DIR=str(output / "artifacts"),
    )
    import redis
    from app.database import Base, engine, SessionLocal
    import app.models  # noqa: F401
    from app.models.data_version import DatasetVersion, DatasetSample
    from app.models.labeling import LabelSchema, LabelColumn
    from app.models.operation import DurableOperation
    from app.models.platform_models import GenericAnnotationTask, AnnotationTaskExecutionResult
    from app.models.project import Project
    from app.models.user import User
    from app.services.annotation_task_state import create_annotation_preview
    from app.services.annotation_task_execution import request_annotation_execution
    from app.tasks.celery_app import celery_app

    # Recovery dispatchers use Celery's production default queue. Keep the
    # harness on that queue so it exercises the same routing contract.
    queue = "celery"
    celery_app.conf.task_default_queue = queue
    worker = None
    log = None
    receipt = {
        "status": "failed",
        "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip(),
        "working_tree": subprocess.check_output(["git", "status", "--porcelain"], cwd=repo, text=True).splitlines(),
        "checks": [],
        "fault_injection": "Terminate the solo worker process after a running lease is observed; advance that dead worker's lease expiry in the isolated database.",
    }

    def wait_for(predicate, timeout=90):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            value = predicate()
            if value:
                return value
            if worker is not None and worker.poll() is not None:
                raise RuntimeError("Worker exited unexpectedly; inspect worker log")
            time.sleep(0.01)
        raise TimeoutError("Runtime assertion timed out")

    def operation_state(operation_id, desired):
        with SessionLocal() as db:
            operation = db.get(DurableOperation, operation_id)
            if operation.state == "failed":
                raise AssertionError(f"Operation failed: {operation.error_code}")
            return operation.state == desired

    def start_worker(index):
        nonlocal worker, log
        log = (output / f"worker-{index}.log").open("w", encoding="utf-8")
        worker = subprocess.Popen(
            [sys.executable, "-m", "celery", "-A", "app.tasks.celery_app:celery_app",
             "worker", "--pool=solo", "--concurrency=1", "--loglevel=INFO",
             "--queues", queue, "--hostname", f"{queue}@worker-{index}",
             "--without-gossip", "--without-mingle"],
            cwd=backend, env=os.environ.copy(), stdout=log, stderr=subprocess.STDOUT,
        )
        wait_for(lambda: " ready." in (output / f"worker-{index}.log").read_text(encoding="utf-8", errors="replace"))

    def stop_worker():
        nonlocal worker, log
        if worker is not None:
            if worker.poll() is None:
                worker.kill()
            worker.wait(timeout=20)
            worker = None
        if log is not None:
            log.close()
            log = None

    try:
        assert redis.Redis.from_url(args.broker).ping()
        Base.metadata.create_all(engine)
        with SessionLocal() as db:
            user = User(username=f"runtime-{queue}", password_hash="fixture-not-login")
            db.add(user)
            db.flush()
            project = Project(name=queue, owner_id=user.id)
            db.add(project)
            db.flush()
            schema = LabelSchema(project_id=project.id, name="runtime", version=1, status="active")
            version = DatasetVersion(project_id=project.id, operator_id=user.id, version=1,
                                     row_count=5000, column_count=1, content_hash="sha256:runtime", schema_hash="sha256:runtime")
            db.add_all([schema, version])
            db.flush()
            db.add(LabelColumn(schema_id=schema.id, machine_key="label", display_name="Label", ordinal=0, value_type="string"))
            sample_ids = [f"sample-{index:05d}" for index in range(5000)]
            db.add_all([DatasetSample(dataset_version_id=version.id, sample_id=sample_id,
                                     row_index=index, values={"feature": index})
                        for index, sample_id in enumerate(sample_ids)])
            task = GenericAnnotationTask(
                project_id=project.id, dataset_version_id=version.id, label_schema_id=schema.id,
                owner_id=user.id, mode="manual", status="draft", task_revision=0,
                sample_scope={"kind": "all"},
                task_snapshot={"config_hash": "sha256:runtime", "sample_ids": sample_ids,
                               "visible_columns": ["feature"],
                               "label_schema": {"columns": [{"machine_key": "label", "value_type": "string"}]}},
            )
            db.add(task)
            db.commit()
            task_id, owner_id = task.id, user.id
            preview = create_annotation_preview(db, task.id, 0, "sha256:runtime", user.id)
            preview_id, preview_operation = preview.id, preview.operation_id
        start_worker(1)
        celery_app.send_task("ml_platform.execute_annotation_preview",
                             args=[str(task_id), str(preview_id), str(owner_id)], queue=queue)
        wait_for(lambda: operation_state(preview_operation, "completed"))
        receipt["checks"].append("real_broker_preview_completed")
        with SessionLocal() as db:
            requested = request_annotation_execution(db, task_id, preview_id, owner_id)
            operation_id = requested.operation_id
        execution_args = [str(task_id), str(preview_id), str(owner_id), str(operation_id)]
        celery_app.send_task("ml_platform.execute_annotation_task", args=execution_args, queue=queue)
        wait_for(lambda: operation_state(operation_id, "running"))
        stop_worker()
        with SessionLocal() as db:
            operation = db.get(DurableOperation, operation_id)
            assert operation.state == "running", "Worker finished before interruption; no crash evidence"
            receipt["interrupted_stage"] = operation.stage
            receipt["interrupted_attempt"] = operation.attempt
            operation.lease_expires_at = datetime.utcnow() - timedelta(seconds=1)
            db.commit()
        start_worker(2)
        # The recovery task is itself delivered through Redis. The worker must
        # dispatch recovered operations back to the isolated queue.
        celery_app.send_task("ml_platform.recover_operations", queue=queue)
        wait_for(lambda: operation_state(operation_id, "completed"))
        with SessionLocal() as db:
            operation = db.get(DurableOperation, operation_id)
            count = db.query(AnnotationTaskExecutionResult).filter_by(operation_id=operation_id).count()
            assert count == 5000
            assert operation.attempt > receipt["interrupted_attempt"]
            assert operation.checksum and operation.progress == 100
            checksum = operation.checksum
            receipt["recovered_attempt"] = operation.attempt
            receipt["result_count"] = count
        receipt["checks"].append("worker_kill_restart_recovery_same_operation")
        duplicate = celery_app.send_task("ml_platform.execute_annotation_task", args=execution_args, queue=queue)
        result = duplicate.get(timeout=60, disable_sync_subtasks=False)
        assert result["status"] == "not_claimed"
        with SessionLocal() as db:
            assert db.get(DurableOperation, operation_id).checksum == checksum
            assert db.query(AnnotationTaskExecutionResult).filter_by(operation_id=operation_id).count() == 5000
        receipt["checks"].append("duplicate_delivery_no_duplicate_results")
        receipt["status"] = "passed"
    except Exception as error:
        receipt["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        stop_worker()
        receipt["finished_at"] = datetime.now().astimezone().isoformat()
        receipt["worker_log_sha256"] = {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in output.glob("worker-*.log")
        }
        (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        engine.dispose()
        print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
