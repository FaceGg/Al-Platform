# Production Infrastructure Contract

MLflow 3.15.0 is internal-only. The production notification stack requires
`NOTIFICATION_CRYPTO_SECRET_FILE`, `SMTP_USERNAME`, `SMTP_PASSWORD`,
`notification_crypto_configured`, `notification_worker_registered`, and
`RUN_NOTIFICATION_INTEGRATION=1` for its opt-in integration gate.
