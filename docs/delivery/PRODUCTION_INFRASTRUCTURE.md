# Production Infrastructure

Production mode uses PostgreSQL 16, Redis 7, Celery 5.4, MinIO, MLflow 3.15.0, the isolated TensorBoard Gateway and the ONNX inference runtime. Keep credentials in injected environment variables or `*_FILE` secret files; never commit real values.

## Required configuration

Set `POSTGRES_PASSWORD`, `DATABASE_URL`, `SECRET_KEY`, `CELERY_BROKER_URL`, `REDIS_EVENTS_URL`, `MINIO_ROOT_USER`, `MINIO_ROOT_PASSWORD`, `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY`, `MLFLOW_BACKEND_STORE_URI`, `TENSORBOARD_SESSION_SECRET` and `INFERENCE_INTERNAL_SECRET`. `DATABASE_URL` must use `postgresql+psycopg://`; JWT and inference secrets must contain at least 32 characters.

For notifications, mount the Fernet master key through `NOTIFICATION_CRYPTO_SECRET_FILE`; Compose exposes it to services only as `/run/secrets/notification_master_key`. Configure `SMTP_HOST`, `SMTP_PORT`, `SMTP_FROM`, `SMTP_USE_TLS` and, when the relay requires authentication, `SMTP_USERNAME` and `SMTP_PASSWORD`. Never put SMTP credentials, endpoint tokens, WeCom keys, Webhook signing keys, or the notification master key in images, logs, status output, or documentation.

`docker compose up -d postgres redis minio minio-init mlflow tensorboard-gateway inference-runtime migrate backend worker scheduler` creates databases and buckets, runs `alembic upgrade head`, then starts the internal runtime, API, Worker and Beat scheduler. The API refuses to start when the database revision is not current.

## Verification

- `/api/health` proves the API process is alive.
- `/api/ready` requires database connectivity and Alembic head, Redis ping, at least one Celery Worker, the MinIO bucket, MLflow `/health`, TensorBoard Gateway `/openapi.json` and inference runtime `/health`. It reports notification readiness only through the booleans `notification_crypto_configured` and `notification_worker_registered`; it never returns notification secrets or endpoint configuration.
- `docker compose logs backend worker migrate minio-init` provides startup and task evidence.
- `RUN_PRODUCTION_INTEGRATION=1 python -m unittest tests.test_production_stack -v` must run only against a dedicated test database because it truncates business tables.
- `RUN_NOTIFICATION_INTEGRATION=1 python -m unittest tests.test_notification_production_stack -v` validates transactional Outbox delivery, retry/dead-letter behavior, and in-app plus controlled email delivery. Add `RUN_NOTIFICATION_EXTERNAL_RECEIVER_INTEGRATION=1` only for an isolated Mailpit and controlled WeCom/Webhook receiver stack.

The production integration suite covers SQLite-to-PostgreSQL idempotency, MinIO round-trip, real Celery execution, duplicate delivery, Redis events, node timeout, stale heartbeat/cancellation recovery and readiness. The notification Worker registers `ml_platform.deliver_notifications`; Beat enqueues due Outbox work through `ml_platform.enqueue_due_notifications` every 30 seconds. The four delivery channels are in-app, WeCom, email, and generic Webhook; all external endpoints remain encrypted at rest and use their channel-specific safety validation.

## Rollback

Stop API and Worker writes, preserve a PostgreSQL backup and MinIO objects, then restore the previous local configuration (`APP_MODE=local`, SQLite, local dispatcher and local artifact storage). Do not point an Alembic baseline at an unversioned existing SQLite database. Use the database and artifact migration tools for a controlled forward switch instead of copying container-local paths.

Stable readiness codes include `DATABASE_UNAVAILABLE`, `DATABASE_SCHEMA_OUTDATED`, `REDIS_UNAVAILABLE`, `CELERY_UNAVAILABLE`, `MINIO_UNAVAILABLE`, `MLFLOW_UNAVAILABLE`, `TENSORBOARD_UNAVAILABLE` and `INFERENCE_RUNTIME_UNAVAILABLE`.

The runtime has no host port and uses one worker because its ONNX session cache is process-local. Beat runs `ml_platform.reconcile_inference_deployments` every 60 seconds. See `MODEL_REGISTRY_INFERENCE.md` for lifecycle and isolated verification.

## Acceptance boundary

The August 2, 2026 local WSL notification stack evidence covers the migration head `20260720_10_security_notifications`, PostgreSQL, Redis, Celery, Mailpit, controlled WeCom/Webhook receivers, and target Chromium. It is local evidence only: remote GitHub Actions, fixed-resource performance, real backup/restore RTO/RPO, N-1 upgrade, full external Chromium, and the final evidence manifest remain separate Week 11-12 gates.
