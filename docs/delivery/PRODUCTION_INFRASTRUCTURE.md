# Production Infrastructure

Production mode uses PostgreSQL 16, Redis 7, Celery 5.4, MinIO, MLflow 3.2.0, the isolated TensorBoard Gateway and the ONNX inference runtime. Keep credentials in injected environment variables or `*_FILE` secret files; never commit real values.

## Required configuration

Set `POSTGRES_PASSWORD`, `DATABASE_URL`, `SECRET_KEY`, `CELERY_BROKER_URL`, `REDIS_EVENTS_URL`, `MINIO_ROOT_USER`, `MINIO_ROOT_PASSWORD`, `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY`, `MLFLOW_BACKEND_STORE_URI`, `TENSORBOARD_SESSION_SECRET` and `INFERENCE_INTERNAL_SECRET`. `DATABASE_URL` must use `postgresql+psycopg://`; JWT and inference secrets must contain at least 32 characters.

`docker compose up -d postgres redis minio minio-init mlflow tensorboard-gateway inference-runtime migrate backend worker scheduler` creates databases and buckets, runs `alembic upgrade head`, then starts the internal runtime, API, Worker and Beat scheduler. The API refuses to start when the database revision is not current.

## Verification

- `/api/health` proves the API process is alive.
- `/api/ready` requires database connectivity and Alembic head, Redis ping, at least one Celery Worker, the MinIO bucket, MLflow `/health`, TensorBoard Gateway `/openapi.json` and inference runtime `/health`.
- `docker compose logs backend worker migrate minio-init` provides startup and task evidence.
- `RUN_PRODUCTION_INTEGRATION=1 python -m unittest tests.test_production_stack -v` must run only against a dedicated test database because it truncates business tables.

The production integration suite covers SQLite-to-PostgreSQL idempotency, MinIO round-trip, real Celery execution, duplicate delivery, Redis events, node timeout, stale heartbeat/cancellation recovery and readiness.

## Rollback

Stop API and Worker writes, preserve a PostgreSQL backup and MinIO objects, then restore the previous local configuration (`APP_MODE=local`, SQLite, local dispatcher and local artifact storage). Do not point an Alembic baseline at an unversioned existing SQLite database. Use the database and artifact migration tools for a controlled forward switch instead of copying container-local paths.

Stable readiness codes include `DATABASE_UNAVAILABLE`, `DATABASE_SCHEMA_OUTDATED`, `REDIS_UNAVAILABLE`, `CELERY_UNAVAILABLE`, `MINIO_UNAVAILABLE`, `MLFLOW_UNAVAILABLE`, `TENSORBOARD_UNAVAILABLE` and `INFERENCE_RUNTIME_UNAVAILABLE`.

The runtime has no host port and uses one worker because its ONNX session cache is process-local. Beat runs `ml_platform.reconcile_inference_deployments` every 60 seconds. See `MODEL_REGISTRY_INFERENCE.md` for lifecycle and isolated verification.
