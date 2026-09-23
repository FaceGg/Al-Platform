"""Create independent annotator identity tables."""
from alembic import op
import sqlalchemy as sa

revision = "20260908_30"
down_revision = "20260908_29"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table("annotator_accounts",
        sa.Column("id", sa.Uuid(), nullable=False), sa.Column("subject_id", sa.Uuid(), nullable=False),
        sa.Column("username", sa.String(64), nullable=False), sa.Column("email", sa.String(320)),
        sa.Column("password_hash", sa.String(512), nullable=False), sa.Column("status", sa.String(16), nullable=False),
        sa.Column("session_version", sa.Integer(), nullable=False), sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False), sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("subject_id"), sa.UniqueConstraint("username", name="uq_annotator_accounts_username"))
    op.create_index("ix_annotator_accounts_subject", "annotator_accounts", ["subject_id"])
    op.create_table("annotator_sessions",
        sa.Column("id", sa.Uuid(), nullable=False), sa.Column("account_id", sa.Uuid(), nullable=False), sa.Column("token_hash", sa.String(128), nullable=False),
        sa.Column("session_version", sa.Integer(), nullable=False), sa.Column("expires_at", sa.DateTime(), nullable=False), sa.Column("revoked_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False), sa.Column("last_seen_at", sa.DateTime()), sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["account_id"], ["annotator_accounts.id"], ondelete="CASCADE"), sa.UniqueConstraint("token_hash"))
    op.create_index("ix_annotator_sessions_account", "annotator_sessions", ["account_id", "revoked_at"])
    op.create_table("annotator_subject_mappings",
        sa.Column("id", sa.Uuid(), nullable=False), sa.Column("subject_id", sa.Uuid(), nullable=False), sa.Column("platform_principal_id", sa.Uuid()),
        sa.Column("created_by", sa.Uuid()), sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False), sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["subject_id"], ["annotator_accounts.subject_id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["platform_principal_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"), sa.UniqueConstraint("subject_id"))
    op.create_table("project_annotator_grants",
        sa.Column("id", sa.Uuid(), nullable=False), sa.Column("project_id", sa.Uuid(), nullable=False), sa.Column("subject_id", sa.Uuid(), nullable=False), sa.Column("status", sa.String(16), nullable=False),
        sa.Column("granted_by", sa.Uuid()), sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False), sa.Column("revoked_at", sa.DateTime()), sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["subject_id"], ["annotator_accounts.subject_id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["granted_by"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("project_id", "subject_id", name="uq_project_annotator_grants_project_subject"))
    op.create_index("ix_project_annotator_grants_subject", "project_annotator_grants", ["subject_id", "status"])

def downgrade():
    op.drop_index("ix_project_annotator_grants_subject", table_name="project_annotator_grants"); op.drop_table("project_annotator_grants")
    op.drop_table("annotator_subject_mappings"); op.drop_index("ix_annotator_sessions_account", table_name="annotator_sessions"); op.drop_table("annotator_sessions")
    op.drop_index("ix_annotator_accounts_subject", table_name="annotator_accounts"); op.drop_table("annotator_accounts")
