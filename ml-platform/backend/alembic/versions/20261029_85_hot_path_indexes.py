"""Secondary indexes for hot foreign-key/filter columns (audit A 批次十三).

Revision ID: 20261029_85
Revises: 20261026_84
Create Date: 2026-10-29
"""

import sqlalchemy as sa
from alembic import op

revision = "20261029_85"
down_revision = "20261026_84"
branch_labels = None
depends_on = None

# 12 张只有主键的表 + 3 个过滤列（审计以活库 pg_indexes 为准）
_INDEXES = (
    ("ix_projects_owner_id", "projects", ["owner_id"]),
    ("ix_workflows_project_id", "workflows", ["project_id"]),
    ("ix_workflows_created_by", "workflows", ["created_by"]),
    ("ix_workflow_runs_workflow_id", "workflow_runs", ["workflow_id"]),
    ("ix_nodes_workflow_id", "nodes", ["workflow_id"]),
    ("ix_node_runs_run_id", "node_runs", ["run_id"]),
    ("ix_edges_workflow_id", "edges", ["workflow_id"]),
    ("ix_workflow_versions_workflow_id", "workflow_versions", ["workflow_id"]),
    ("ix_kb_chunks_doc_id", "kb_chunks", ["doc_id"]),
    ("ix_kb_documents_kb_id", "kb_documents", ["kb_id"]),
    ("ix_chat_messages_session_id", "chat_messages", ["session_id"]),
    ("ix_chat_sessions_kb_id", "chat_sessions", ["kb_id"]),
    ("ix_datasets_project_id", "datasets", ["project_id"]),
    ("ix_model_library_project_id", "model_library", ["project_id"]),
    ("ix_dataset_versions_original_artifact_id", "dataset_versions", ["original_artifact_id"]),
    ("ix_dataset_versions_normalized_artifact_id", "dataset_versions", ["normalized_artifact_id"]),
    ("ix_dataset_samples_sample_id", "dataset_samples", ["sample_id"]),
)


def upgrade() -> None:
    for name, table, columns in _INDEXES:
        op.create_index(name, table, columns)


def downgrade() -> None:
    for name, table, _columns in reversed(_INDEXES):
        op.drop_index(name, table_name=table)
