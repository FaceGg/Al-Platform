from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine


_SQLITE_COLUMNS = {
    "workflow_runs": {
        "error_code": "VARCHAR(64)",
        "error_details": "JSON",
        "workflow_version": "INTEGER",
        "workflow_snapshot": "JSON",
        "timeout_seconds": "INTEGER",
        "logs": "JSON",
        "cancel_requested_at": "DATETIME",
        "cancelled_at": "DATETIME",
        "task_id": "VARCHAR(128)",
        "queue_name": "VARCHAR(64)",
        "worker_id": "VARCHAR(128)",
        "heartbeat_at": "DATETIME",
    },
    "node_runs": {
        "attempt": "INTEGER NOT NULL DEFAULT 1",
        "error_code": "VARCHAR(64)",
        "error_details": "JSON",
        "duration_ms": "INTEGER",
        "logs": "JSON",
    },
    "training_jobs": {
        "dataset_artifact_id": "CHAR(32)",
        "model_artifact_id": "CHAR(32)",
        "model_library_id": "CHAR(32)",
        "feature_schema": "JSON",
        "target_schema": "JSON",
        "preprocessing": "JSON",
        "error_code": "VARCHAR(64)",
        "error_details": "JSON",
        "logs": "JSON",
        "experiment_id": "CHAR(32)",
        "mlflow_run_id": "VARCHAR(64)",
        "task_id": "VARCHAR(128)",
        "worker_id": "VARCHAR(128)",
        "heartbeat_at": "DATETIME",
        "attempt": "INTEGER NOT NULL DEFAULT 0",
        "resumed_from_job_id": "CHAR(32)",
        "resumed_from_run_id": "VARCHAR(64)",
        "resume_checkpoint_uri": "VARCHAR(1024)",
        "latest_checkpoint_uri": "VARCHAR(1024)",
        "best_checkpoint_uri": "VARCHAR(1024)",
        "current_epoch": "INTEGER NOT NULL DEFAULT 0",
        "total_epochs": "INTEGER",
        "monitor_name": "VARCHAR(64)",
        "monitor_mode": "VARCHAR(8)",
        "early_stopping_patience": "INTEGER",
        "early_stopping_min_delta": "FLOAT",
        "restore_best": "BOOLEAN NOT NULL DEFAULT 1",
    },
    "agent_tasks": {
        "project_id": "CHAR(32)",
        "created_by_id": "CHAR(32)",
    },
    "model_library": {
        "training_job_id": "CHAR(32)",
        "dataset_artifact_id": "CHAR(32)",
        "model_artifact_id": "CHAR(32)",
    },
    "artifacts": {
        "storage_uri": "TEXT",
    },
    # Existing local SQLite databases may predate the API management
    # migration. Keep the compatibility path additive and idempotent so the
    # application can start before the next full Alembic upgrade.
    "platform_apis": {
        "source_kind": "VARCHAR(32) NOT NULL DEFAULT 'custom'",
        "source_id": "CHAR(32)",
        "published_at": "DATETIME",
        "last_error": "TEXT",
    },
    "dataset_versions": {
        "status": "VARCHAR(24) NOT NULL DEFAULT 'ready'",
    },
}

_SQLITE_INDEXES = {
    "training_jobs": {
        "ix_training_jobs_experiment_id": "experiment_id",
        "ix_training_jobs_mlflow_run_id": "mlflow_run_id",
        "ix_training_jobs_task_id": "task_id",
        "ix_training_jobs_heartbeat_at": "heartbeat_at",
    },
    "agent_tasks": {
        "ix_agent_tasks_project_id": "project_id",
        "ix_agent_tasks_created_by_id": "created_by_id",
    },
    "dataset_versions": {
        "ix_dataset_versions_project_id": "project_id",
    },
    "dataset_schema_columns": {
        "ix_dataset_schema_columns_dataset_version_id": "dataset_version_id",
    },
    "dataset_samples": {
        "ix_dataset_samples_dataset_version_id": "dataset_version_id",
    },
    "dataset_imports": {
        "ix_dataset_imports_dataset_version_id": "dataset_version_id",
    },
}


def ensure_schema_compatibility(engine: Engine) -> None:
    if engine.dialect.name != "sqlite":
        return
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    with engine.begin() as connection:
        for table, definitions in _SQLITE_COLUMNS.items():
            if table not in tables:
                continue
            existing = {column["name"] for column in inspector.get_columns(table)}
            for column, definition in definitions.items():
                if column not in existing:
                    connection.execute(text(
                        f'ALTER TABLE "{table}" ADD COLUMN "{column}" {definition}'
                    ))
        refreshed = inspect(engine)
        for table, indexes in _SQLITE_INDEXES.items():
            if table not in tables:
                continue
            existing_indexes = {item["name"] for item in refreshed.get_indexes(table)}
            for index_name, column in indexes.items():
                if index_name not in existing_indexes:
                    connection.execute(text(
                        f'CREATE INDEX "{index_name}" ON "{table}" ("{column}")'
                    ))
