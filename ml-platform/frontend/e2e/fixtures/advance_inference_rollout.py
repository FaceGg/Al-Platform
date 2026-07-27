"""Advance an existing browser-test rollout when no Playwright worker is running."""

import json
from pathlib import Path
import sys
import uuid


BACKEND_ROOT = Path(__file__).resolve().parents[3] / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

import app.main  # noqa: E402,F401 (load the complete ORM graph)
from app.config import settings  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.services.inference_runtime_client import InferenceRuntimeClient  # noqa: E402
from app.services.inference_rollout import InferenceRolloutService  # noqa: E402


def _service() -> InferenceRolloutService:
    secret = settings.resolved_inference_internal_secret
    if secret is None or not settings.inference_runtime_url:
        raise RuntimeError("Inference runtime is not configured for browser acceptance")
    runtime = InferenceRuntimeClient(
        settings.inference_runtime_url,
        secret.get_secret_value(),
        load_timeout_seconds=settings.inference_load_timeout_seconds,
        predict_timeout_seconds=settings.inference_predict_timeout_seconds,
    )
    return InferenceRolloutService(runtime)


def main() -> int:
    if len(sys.argv) != 3:
        raise SystemExit("usage: advance_inference_rollout.py ROLLOUT_ID preload|complete")
    rollout_id = uuid.UUID(sys.argv[1])
    action = sys.argv[2]
    service = _service()

    with SessionLocal() as db:
        if action == "preload":
            rollout = service.preload(db, rollout_id)
        elif action == "complete":
            rollout = service.preload(db, rollout_id)
            while rollout.state == "progressing":
                rollout = service.advance(
                    db,
                    rollout.id,
                    expected_lock_version=rollout.lock_version,
                    observation={"error_rate": 0.0, "p95_ms": 1.0},
                )
        else:
            raise SystemExit("action must be preload or complete")

        print(json.dumps({
            "id": str(rollout.id),
            "state": rollout.state,
            "current_step": rollout.current_step,
            "lock_version": rollout.lock_version,
        }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
