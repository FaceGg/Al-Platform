"""Add experiment and training tracking schema.

Revision ID: 20260717_04
Revises: 20260715_03
"""

from alembic import op
import sqlalchemy as sa


revision = "20260717_04"
down_revision = "20260715_03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "experiments",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("mlflow_experiment_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "name", name="uq_experiments_project_name"),
    )
    op.create_index("ix_experiments_project_id", "experiments", ["project_id"])
    op.create_index(
        "ix_experiments_mlflow_experiment_id",
        "experiments",
        ["mlflow_experiment_id"],
        unique=True,
    )

    columns = (
        sa.Column("experiment_id", sa.UUID(), nullable=True),
        sa.Column("mlflow_run_id", sa.String(length=64), nullable=True),
        sa.Column("task_id", sa.String(length=128), nullable=True),
        sa.Column("worker_id", sa.String(length=128), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(), nullable=True),
        sa.Column("attempt", sa.Integer(), server_default="0", nullable=False),
        sa.Column("resumed_from_job_id", sa.UUID(), nullable=True),
        sa.Column("resumed_from_run_id", sa.String(length=64), nullable=True),
        sa.Column("resume_checkpoint_uri", sa.String(length=1024), nullable=True),
        sa.Column("latest_checkpoint_uri", sa.String(length=1024), nullable=True),
        sa.Column("best_checkpoint_uri", sa.String(length=1024), nullable=True),
        sa.Column("current_epoch", sa.Integer(), server_default="0", nullable=False),
        sa.Column("total_epochs", sa.Integer(), nullable=True),
        sa.Column("monitor_name", sa.String(length=64), nullable=True),
        sa.Column("monitor_mode", sa.String(length=8), nullable=True),
        sa.Column("early_stopping_patience", sa.Integer(), nullable=True),
        sa.Column("early_stopping_min_delta", sa.Float(), nullable=True),
        sa.Column("restore_best", sa.Boolean(), server_default=sa.true(), nullable=False),
    )
    for column in columns:
        op.add_column("training_jobs", column)

    with op.batch_alter_table("training_jobs") as batch_op:
        batch_op.create_foreign_key(
            "fk_training_jobs_experiment_id_experiments",
            "experiments",
            ["experiment_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_foreign_key(
            "fk_training_jobs_resumed_from_job_id_training_jobs",
            "training_jobs",
            ["resumed_from_job_id"],
            ["id"],
            ondelete="SET NULL",
        )

    for name, column in (
        ("ix_training_jobs_experiment_id", "experiment_id"),
        ("ix_training_jobs_mlflow_run_id", "mlflow_run_id"),
        ("ix_training_jobs_task_id", "task_id"),
        ("ix_training_jobs_heartbeat_at", "heartbeat_at"),
    ):
        op.create_index(name, "training_jobs", [column])


def downgrade() -> None:
    for name in (
        "ix_training_jobs_heartbeat_at",
        "ix_training_jobs_task_id",
        "ix_training_jobs_mlflow_run_id",
        "ix_training_jobs_experiment_id",
    ):
        op.drop_index(name, table_name="training_jobs")

    with op.batch_alter_table("training_jobs") as batch_op:
        batch_op.drop_constraint(
            "fk_training_jobs_resumed_from_job_id_training_jobs",
            type_="foreignkey",
        )
        batch_op.drop_constraint(
            "fk_training_jobs_experiment_id_experiments",
            type_="foreignkey",
        )

    for name in (
        "restore_best",
        "early_stopping_min_delta",
        "early_stopping_patience",
        "monitor_mode",
        "monitor_name",
        "total_epochs",
        "current_epoch",
        "best_checkpoint_uri",
        "latest_checkpoint_uri",
        "resume_checkpoint_uri",
        "resumed_from_run_id",
        "resumed_from_job_id",
        "attempt",
        "heartbeat_at",
        "worker_id",
        "task_id",
        "mlflow_run_id",
        "experiment_id",
    ):
        op.drop_column("training_jobs", name)

    op.drop_index("ix_experiments_mlflow_experiment_id", table_name="experiments")
    op.drop_index("ix_experiments_project_id", table_name="experiments")
    op.drop_table("experiments")
