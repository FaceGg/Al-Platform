"""Add durable production inference revisions, observability, and model cards."""

from alembic import op
import sqlalchemy as sa


revision='20260720_09_production_inference'
down_revision='20260718_08'
branch_labels=None
depends_on=None


def upgrade() -> None:
    op.create_table(
        "deployment_revisions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("deployment_id", sa.UUID(), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("strategy", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default=sa.text("'draft'")),
        sa.Column("created_by_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("activated_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint("revision_number > 0", name="ck_deployment_revisions_positive_number"),
        sa.CheckConstraint(
            "strategy IN ('immediate', 'canary', 'rolling')",
            name="ck_deployment_revisions_strategy",
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'candidate', 'stable', 'superseded', 'failed')",
            name="ck_deployment_revisions_status",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"], ["users.id"], ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["deployment_id"], ["inference_deployments.id"], ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "deployment_id",
            "revision_number",
            name="uq_deployment_revisions_number",
        ),
    )
    op.create_index(
        "ix_deployment_revisions_deployment_status",
        "deployment_revisions",
        ["deployment_id", "status"],
    )

    op.create_table(
        "deployment_targets",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("revision_id", sa.UUID(), nullable=False),
        sa.Column("model_version_id", sa.UUID(), nullable=False),
        sa.Column("weight_bps", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.CheckConstraint(
            "weight_bps >= 0 AND weight_bps <= 10000",
            name="ck_deployment_targets_weight",
        ),
        sa.CheckConstraint(
            "role IN ('stable', 'candidate')",
            name="ck_deployment_targets_role",
        ),
        sa.ForeignKeyConstraint(
            ["model_version_id"], ["model_versions.id"],
            deferrable=True, initially="DEFERRED",
        ),
        sa.ForeignKeyConstraint(
            ["revision_id"], ["deployment_revisions.id"], ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "revision_id",
            "model_version_id",
            name="uq_deployment_targets_revision_model",
        ),
    )
    op.create_index(
        "ix_deployment_targets_model_version",
        "deployment_targets",
        ["model_version_id"],
    )

    op.create_table(
        "deployment_rollouts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("deployment_id", sa.UUID(), nullable=False),
        sa.Column("from_revision_id", sa.UUID(), nullable=True),
        sa.Column("to_revision_id", sa.UUID(), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("current_step", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("lock_version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("step_schedule", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("thresholds", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("last_error_code", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "state IN ('pending', 'preloading', 'progressing', 'paused', "
            "'completed', 'failed', 'rolled_back')",
            name="ck_deployment_rollouts_state",
        ),
        sa.CheckConstraint(
            "current_step >= 0",
            name="ck_deployment_rollouts_current_step",
        ),
        sa.CheckConstraint(
            "lock_version > 0",
            name="ck_deployment_rollouts_lock_version",
        ),
        sa.ForeignKeyConstraint(
            ["deployment_id"], ["inference_deployments.id"], ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["from_revision_id"], ["deployment_revisions.id"],
            deferrable=True, initially="DEFERRED",
        ),
        sa.ForeignKeyConstraint(
            ["to_revision_id"], ["deployment_revisions.id"],
            deferrable=True, initially="DEFERRED",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    active_states = sa.text(
        "state IN ('pending', 'preloading', 'progressing', 'paused')"
    )
    op.create_index(
        "uq_deployment_rollouts_active",
        "deployment_rollouts",
        ["deployment_id"],
        unique=True,
        postgresql_where=active_states,
        sqlite_where=active_states,
    )
    op.create_index(
        "ix_deployment_rollouts_deployment_created",
        "deployment_rollouts",
        ["deployment_id", "created_at"],
    )

    op.create_table(
        "inference_api_keys",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("deployment_id", sa.UUID(), nullable=False),
        sa.Column("prefix", sa.String(length=12), nullable=False),
        sa.Column("secret_hash", sa.String(length=512), nullable=False),
        sa.Column("scopes", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("created_by_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "length(prefix) = 12",
            name="ck_inference_api_keys_prefix_length",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"], ["users.id"], ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["deployment_id"], ["inference_deployments.id"], ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_inference_api_keys_deployment_prefix",
        "inference_api_keys",
        ["deployment_id", "prefix"],
        unique=True,
    )

    op.create_table(
        "inference_request_logs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("request_id", sa.String(length=128), nullable=False),
        sa.Column("deployment_id", sa.UUID(), nullable=False),
        sa.Column("revision_id", sa.UUID(), nullable=True),
        sa.Column("model_version_id", sa.UUID(), nullable=True),
        sa.Column("api_key_id", sa.UUID(), nullable=True),
        sa.Column("batch_size", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default=sa.text("'success'")),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "status IN ('success', 'error', 'limited')",
            name="ck_inference_request_logs_status",
        ),
        sa.ForeignKeyConstraint(
            ["api_key_id"], ["inference_api_keys.id"], ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["deployment_id"], ["inference_deployments.id"], ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["model_version_id"], ["model_versions.id"], ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["revision_id"], ["deployment_revisions.id"], ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_id", name="uq_inference_request_logs_request_id"),
    )
    op.create_index(
        "ix_inference_request_logs_deployment_occurred",
        "inference_request_logs",
        ["deployment_id", "occurred_at"],
    )
    op.create_index(
        "ix_inference_request_logs_expires",
        "inference_request_logs",
        ["expires_at"],
    )

    op.create_table(
        "inference_metric_buckets",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("deployment_id", sa.UUID(), nullable=False),
        sa.Column("bucket_start", sa.DateTime(), nullable=False),
        sa.Column("request_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("success_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("error_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("limited_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("load_failure_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("batch_size_sum", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("latency_sum_ms", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("latency_max_ms", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("latency_buckets", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("traffic_weights", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.ForeignKeyConstraint(
            ["deployment_id"], ["inference_deployments.id"], ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_inference_metric_buckets_deployment_minute",
        "inference_metric_buckets",
        ["deployment_id", "bucket_start"],
        unique=True,
    )

    op.create_table(
        "model_cards",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("model_version_id", sa.UUID(), nullable=False),
        sa.Column("training_data_lineage", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("source_artifact_ids", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("input_schema", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("output_schema", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("metrics", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("approval_history", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("approval_status", sa.String(length=16), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("release_status", sa.String(length=16), nullable=False, server_default=sa.text("'unreleased'")),
        sa.Column("risk_notes", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("intended_use", sa.String(length=4000), nullable=False, server_default=sa.text("''")),
        sa.Column("limitations", sa.String(length=4000), nullable=False, server_default=sa.text("''")),
        sa.Column("operational_guidance", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("guidance_revision", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["model_version_id"], ["model_versions.id"], ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "model_version_id",
            name="uq_model_cards_model_version",
        ),
    )
    op.create_index(
        "ix_model_cards_release_status",
        "model_cards",
        ["release_status"],
    )

    _backfill_legacy_registry()


def _backfill_legacy_registry() -> None:
    connection = op.get_bind()
    deployments = sa.table(
        "inference_deployments",
        sa.column("id", sa.UUID()),
        sa.column("model_version_id", sa.UUID()),
        sa.column("created_by_id", sa.UUID()),
        sa.column("created_at", sa.DateTime()),
        sa.column("started_at", sa.DateTime()),
    )
    versions = sa.table(
        "model_versions",
        sa.column("id", sa.UUID()),
        sa.column("source_artifact_id", sa.UUID()),
        sa.column("onnx_artifact_id", sa.UUID()),
        sa.column("feature_schema", sa.JSON()),
        sa.column("output_schema", sa.JSON()),
        sa.column("metrics", sa.JSON()),
        sa.column("approval_status", sa.String()),
        sa.column("approval_comment", sa.Text()),
        sa.column("approved_by_id", sa.UUID()),
        sa.column("approved_at", sa.DateTime()),
        sa.column("created_by_id", sa.UUID()),
        sa.column("created_at", sa.DateTime()),
    )
    artifacts = sa.table(
        "artifacts",
        sa.column("id", sa.UUID()),
        sa.column("metadata", sa.JSON()),
    )
    revisions = sa.table(
        "deployment_revisions",
        sa.column("id", sa.UUID()),
        sa.column("deployment_id", sa.UUID()),
        sa.column("revision_number", sa.Integer()),
        sa.column("strategy", sa.String()),
        sa.column("status", sa.String()),
        sa.column("created_by_id", sa.UUID()),
        sa.column("created_at", sa.DateTime()),
        sa.column("activated_at", sa.DateTime()),
    )
    targets = sa.table(
        "deployment_targets",
        sa.column("id", sa.UUID()),
        sa.column("revision_id", sa.UUID()),
        sa.column("model_version_id", sa.UUID()),
        sa.column("weight_bps", sa.Integer()),
        sa.column("role", sa.String()),
    )
    cards = sa.table(
        "model_cards",
        sa.column("id", sa.UUID()),
        sa.column("model_version_id", sa.UUID()),
        sa.column("training_data_lineage", sa.JSON()),
        sa.column("source_artifact_ids", sa.JSON()),
        sa.column("input_schema", sa.JSON()),
        sa.column("output_schema", sa.JSON()),
        sa.column("metrics", sa.JSON()),
        sa.column("approval_history", sa.JSON()),
        sa.column("approval_status", sa.String()),
        sa.column("release_status", sa.String()),
        sa.column("risk_notes", sa.Text()),
        sa.column("intended_use", sa.String(length=4000)),
        sa.column("limitations", sa.String(length=4000)),
        sa.column("operational_guidance", sa.Text()),
        sa.column("guidance_revision", sa.Integer()),
        sa.column("created_at", sa.DateTime()),
        sa.column("updated_at", sa.DateTime()),
    )

    deployment_rows = connection.execute(
        sa.select(deployments).order_by(deployments.c.id)
    ).mappings().all()
    version_rows = connection.execute(
        sa.select(versions).order_by(versions.c.id)
    ).mappings().all()
    deployed_version_ids = {row["model_version_id"] for row in deployment_rows}

    revision_rows = [
        {
            "id": row["id"],
            "deployment_id": row["id"],
            "revision_number": 1,
            "strategy": "immediate",
            "status": "stable",
            "created_by_id": row["created_by_id"],
            "created_at": row["created_at"],
            "activated_at": row["started_at"] or row["created_at"],
        }
        for row in deployment_rows
    ]
    target_rows = [
        {
            "id": row["id"],
            "revision_id": row["id"],
            "model_version_id": row["model_version_id"],
            "weight_bps": 10000,
            "role": "stable",
        }
        for row in deployment_rows
    ]
    if revision_rows:
        connection.execute(sa.insert(revisions), revision_rows)
        connection.execute(sa.insert(targets), target_rows)

    artifact_ids = {
        row["source_artifact_id"]
        for row in version_rows
        if row["source_artifact_id"] is not None
    }
    artifact_metadata = {
        row["id"]: row["metadata"] or {}
        for row in connection.execute(
            sa.select(artifacts).where(artifacts.c.id.in_(artifact_ids))
        ).mappings()
    } if artifact_ids else {}
    card_rows = []
    for row in version_rows:
        source_ids = []
        for artifact_id in (row["source_artifact_id"], row["onnx_artifact_id"]):
            if artifact_id is not None and str(artifact_id) not in source_ids:
                source_ids.append(str(artifact_id))
        metadata = artifact_metadata.get(row["source_artifact_id"], {})
        lineage = {
            key: metadata[key]
            for key in (
                "source",
                "training_job_id",
                "dataset_artifact_id",
                "experiment_id",
            )
            if key in metadata
        }
        card_rows.append({
            "id": row["id"],
            "model_version_id": row["id"],
            "training_data_lineage": lineage,
            "source_artifact_ids": source_ids,
            "input_schema": row["feature_schema"] or [],
            "output_schema": row["output_schema"] or {},
            "metrics": row["metrics"] or {},
            "approval_history": [{
                "status": row["approval_status"],
                "comment": row["approval_comment"] or "",
                "approved_by_id": str(row["approved_by_id"])
                if row["approved_by_id"] is not None else None,
                "approved_at": str(row["approved_at"])
                if row["approved_at"] is not None else None,
            }],
            "approval_status": row["approval_status"],
            "release_status": (
                "released" if row["id"] in deployed_version_ids else "unreleased"
            ),
            "risk_notes": "",
            "intended_use": "",
            "limitations": "",
            "operational_guidance": "",
            "guidance_revision": 1,
            "created_at": row["created_at"],
            "updated_at": row["created_at"],
        })
    if card_rows:
        connection.execute(sa.insert(cards), card_rows)


def downgrade() -> None:
    op.drop_index("ix_model_cards_release_status", table_name="model_cards")
    op.drop_table("model_cards")
    op.drop_index(
        "uq_inference_metric_buckets_deployment_minute",
        table_name="inference_metric_buckets",
    )
    op.drop_table("inference_metric_buckets")
    op.drop_index(
        "ix_inference_request_logs_expires",
        table_name="inference_request_logs",
    )
    op.drop_index(
        "ix_inference_request_logs_deployment_occurred",
        table_name="inference_request_logs",
    )
    op.drop_table("inference_request_logs")
    op.drop_index(
        "ix_inference_api_keys_deployment_prefix",
        table_name="inference_api_keys",
    )
    op.drop_table("inference_api_keys")
    op.drop_index(
        "ix_deployment_rollouts_deployment_created",
        table_name="deployment_rollouts",
    )
    op.drop_index("uq_deployment_rollouts_active", table_name="deployment_rollouts")
    op.drop_table("deployment_rollouts")
    op.drop_index(
        "ix_deployment_targets_model_version",
        table_name="deployment_targets",
    )
    op.drop_table("deployment_targets")
    op.drop_index(
        "ix_deployment_revisions_deployment_status",
        table_name="deployment_revisions",
    )
    op.drop_table("deployment_revisions")
