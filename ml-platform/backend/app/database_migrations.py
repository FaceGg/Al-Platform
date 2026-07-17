from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine


_SQLITE_COLUMNS = {
    "workflow_runs": {
        "error_code": "VARCHAR(64)",
        "error_details": "JSON",
        "workflow_version": "INTEGER",
        "workflow_snapshot": "JSON",
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
    },
    "model_library": {
        "training_job_id": "CHAR(32)",
        "dataset_artifact_id": "CHAR(32)",
        "model_artifact_id": "CHAR(32)",
    },
    "artifacts": {
        "storage_uri": "TEXT",
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
