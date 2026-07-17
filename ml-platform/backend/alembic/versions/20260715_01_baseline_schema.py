"""baseline_schema

Revision ID: 20260715_01
Revises:
Create Date: 2026-07-16 08:47:39.648288
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision = "20260715_01"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('algorithms',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=128), nullable=False),
    sa.Column('display_name', sa.String(length=256), nullable=True),
    sa.Column('category', sa.String(length=64), nullable=False),
    sa.Column('sub_category', sa.String(length=64), nullable=True),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('framework', sa.String(length=64), nullable=True),
    sa.Column('backbone', sa.String(length=128), nullable=True),
    sa.Column('params_config', sa.JSON(), nullable=True),
    sa.Column('default_params', sa.JSON(), nullable=True),
    sa.Column('benchmark_mAP', sa.Float(), nullable=True),
    sa.Column('benchmark_speed', sa.Float(), nullable=True),
    sa.Column('tags', sa.JSON(), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=True),
    sa.Column('version', sa.String(length=32), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('users',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('username', sa.String(length=64), nullable=False),
    sa.Column('password_hash', sa.String(length=256), nullable=False),
    sa.Column('role', sa.String(length=16), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_users_username'), 'users', ['username'], unique=True)
    op.create_table('agents',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=128), nullable=False),
    sa.Column('agent_type', sa.String(length=32), nullable=True),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('model_name', sa.String(length=64), nullable=True),
    sa.Column('config', sa.JSON(), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=True),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('compute_nodes',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=128), nullable=False),
    sa.Column('node_number', sa.String(length=64), nullable=True),
    sa.Column('ip_address', sa.String(length=64), nullable=True),
    sa.Column('node_type', sa.String(length=32), nullable=True),
    sa.Column('status', sa.String(length=16), nullable=True),
    sa.Column('purpose', sa.String(length=32), nullable=True),
    sa.Column('cpu_cores', sa.Integer(), nullable=True),
    sa.Column('gpu_count', sa.Integer(), nullable=True),
    sa.Column('memory_gb', sa.Float(), nullable=True),
    sa.Column('disk_gb', sa.Float(), nullable=True),
    sa.Column('current_load', sa.Float(), nullable=True),
    sa.Column('owner_id', sa.UUID(), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('tags', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('node_number')
    )
    op.create_table('edge_devices',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=128), nullable=False),
    sa.Column('group_id', sa.String(length=64), nullable=True),
    sa.Column('ip_address', sa.String(length=64), nullable=True),
    sa.Column('device_type', sa.String(length=64), nullable=True),
    sa.Column('status', sa.String(length=16), nullable=True),
    sa.Column('model_deployed', sa.String(length=256), nullable=True),
    sa.Column('version', sa.String(length=32), nullable=True),
    sa.Column('last_heartbeat', sa.DateTime(), nullable=True),
    sa.Column('owner_id', sa.UUID(), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('config', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('knowledge_bases',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=128), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('owner_id', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('projects',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=128), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('owner_id', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('artifacts',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('project_id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=256), nullable=False),
    sa.Column('type', sa.String(length=32), nullable=False),
    sa.Column('storage_path', sa.String(length=512), nullable=False),
    sa.Column('file_size', sa.BigInteger(), nullable=True),
    sa.Column('format', sa.String(length=32), nullable=True),
    sa.Column('metadata', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('chat_sessions',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('kb_id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('title', sa.String(length=256), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
    sa.ForeignKeyConstraint(['kb_id'], ['knowledge_bases.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('datasets',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=256), nullable=False),
    sa.Column('project_id', sa.UUID(), nullable=True),
    sa.Column('owner_id', sa.UUID(), nullable=False),
    sa.Column('dataset_type', sa.String(length=32), nullable=True),
    sa.Column('data_modality', sa.String(length=32), nullable=True),
    sa.Column('algorithm_type', sa.String(length=64), nullable=True),
    sa.Column('version', sa.String(length=32), nullable=True),
    sa.Column('status', sa.String(length=32), nullable=True),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('sample_count', sa.Integer(), nullable=True),
    sa.Column('labeled_count', sa.Integer(), nullable=True),
    sa.Column('file_path', sa.String(length=512), nullable=True),
    sa.Column('format', sa.String(length=32), nullable=True),
    sa.Column('labels', sa.JSON(), nullable=True),
    sa.Column('stats', sa.JSON(), nullable=True),
    sa.Column('tags', sa.JSON(), nullable=True),
    sa.Column('is_public', sa.Boolean(), nullable=True),
    sa.Column('collaborators', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('graph_entities',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('kb_id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=256), nullable=False),
    sa.Column('entity_type', sa.String(length=64), nullable=True),
    sa.Column('properties', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
    sa.ForeignKeyConstraint(['kb_id'], ['knowledge_bases.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_graph_entities_name'), 'graph_entities', ['name'], unique=False)
    op.create_table('kb_documents',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('kb_id', sa.UUID(), nullable=False),
    sa.Column('filename', sa.String(length=256), nullable=False),
    sa.Column('content', sa.Text(), nullable=True),
    sa.Column('doc_type', sa.String(length=32), nullable=True),
    sa.Column('file_path', sa.String(length=512), nullable=True),
    sa.Column('chunk_count', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
    sa.ForeignKeyConstraint(['kb_id'], ['knowledge_bases.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('workflows',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('project_id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=128), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('type', sa.String(length=16), nullable=True),
    sa.Column('is_template', sa.Boolean(), nullable=True),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('agent_tasks',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('workflow_id', sa.UUID(), nullable=True),
    sa.Column('name', sa.String(length=256), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('status', sa.String(length=16), nullable=True),
    sa.Column('parent_task_id', sa.UUID(), nullable=True),
    sa.Column('assigned_agent_id', sa.UUID(), nullable=True),
    sa.Column('input_data', sa.JSON(), nullable=True),
    sa.Column('output_data', sa.JSON(), nullable=True),
    sa.Column('priority', sa.Integer(), nullable=True),
    sa.Column('requires_review', sa.Boolean(), nullable=True),
    sa.Column('review_status', sa.String(length=16), nullable=True),
    sa.Column('review_comment', sa.Text(), nullable=True),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('started_at', sa.DateTime(), nullable=True),
    sa.Column('finished_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
    sa.ForeignKeyConstraint(['assigned_agent_id'], ['agents.id'], ),
    sa.ForeignKeyConstraint(['parent_task_id'], ['agent_tasks.id'], ),
    sa.ForeignKeyConstraint(['workflow_id'], ['workflows.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('annotation_tasks',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=256), nullable=False),
    sa.Column('dataset_id', sa.UUID(), nullable=False),
    sa.Column('owner_id', sa.UUID(), nullable=False),
    sa.Column('annotation_type', sa.String(length=32), nullable=True),
    sa.Column('status', sa.String(length=32), nullable=True),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('total_samples', sa.Integer(), nullable=True),
    sa.Column('labeled_samples', sa.Integer(), nullable=True),
    sa.Column('reviewed_samples', sa.Integer(), nullable=True),
    sa.Column('auto_label_config', sa.JSON(), nullable=True),
    sa.Column('guidelines', sa.Text(), nullable=True),
    sa.Column('assignees', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['dataset_id'], ['datasets.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('chat_messages',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('session_id', sa.UUID(), nullable=False),
    sa.Column('role', sa.String(length=16), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('sources', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
    sa.ForeignKeyConstraint(['session_id'], ['chat_sessions.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('graph_relations',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('kb_id', sa.UUID(), nullable=False),
    sa.Column('source_id', sa.UUID(), nullable=False),
    sa.Column('target_id', sa.UUID(), nullable=False),
    sa.Column('relation_type', sa.String(length=64), nullable=True),
    sa.Column('properties', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
    sa.ForeignKeyConstraint(['kb_id'], ['knowledge_bases.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['source_id'], ['graph_entities.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['target_id'], ['graph_entities.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('kb_chunks',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('doc_id', sa.UUID(), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('chunk_index', sa.Integer(), nullable=True),
    sa.Column('embedding', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['doc_id'], ['kb_documents.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('model_library',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=256), nullable=False),
    sa.Column('algorithm_id', sa.UUID(), nullable=True),
    sa.Column('project_id', sa.UUID(), nullable=True),
    sa.Column('owner_id', sa.UUID(), nullable=False),
    sa.Column('version', sa.String(length=32), nullable=True),
    sa.Column('status', sa.String(length=32), nullable=True),
    sa.Column('framework', sa.String(length=64), nullable=True),
    sa.Column('backbone', sa.String(length=128), nullable=True),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('metrics', sa.JSON(), nullable=True),
    sa.Column('params', sa.JSON(), nullable=True),
    sa.Column('model_path', sa.String(length=512), nullable=True),
    sa.Column('training_job_id', sa.UUID(), nullable=True),
    sa.Column('dataset_artifact_id', sa.UUID(), nullable=True),
    sa.Column('model_artifact_id', sa.UUID(), nullable=True),
    sa.Column('file_size', sa.Integer(), nullable=True),
    sa.Column('format', sa.String(length=32), nullable=True),
    sa.Column('tags', sa.JSON(), nullable=True),
    sa.Column('progress', sa.Float(), nullable=True),
    sa.Column('is_public', sa.Boolean(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['algorithm_id'], ['algorithms.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['dataset_artifact_id'], ['artifacts.id'], ),
    sa.ForeignKeyConstraint(['model_artifact_id'], ['artifacts.id'], ),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ),
    sa.ForeignKeyConstraint(['training_job_id'], ['training_jobs.id'], name='fk_model_library_training_job_id_training_jobs', use_alter=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('nodes',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('workflow_id', sa.UUID(), nullable=False),
    sa.Column('operator_id', sa.String(length=64), nullable=False),
    sa.Column('label', sa.String(length=128), nullable=True),
    sa.Column('position_x', sa.Float(), nullable=False),
    sa.Column('position_y', sa.Float(), nullable=False),
    sa.Column('params', sa.JSON(), nullable=True),
    sa.ForeignKeyConstraint(['workflow_id'], ['workflows.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('orchestration_apps',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=256), nullable=False),
    sa.Column('project_id', sa.UUID(), nullable=True),
    sa.Column('owner_id', sa.UUID(), nullable=False),
    sa.Column('workflow_id', sa.UUID(), nullable=True),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('status', sa.String(length=32), nullable=True),
    sa.Column('version', sa.String(length=32), nullable=True),
    sa.Column('config', sa.JSON(), nullable=True),
    sa.Column('tags', sa.JSON(), nullable=True),
    sa.Column('is_public', sa.Boolean(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['workflow_id'], ['workflows.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('workflow_runs',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('workflow_id', sa.UUID(), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=True),
    sa.Column('started_at', sa.DateTime(), nullable=True),
    sa.Column('finished_at', sa.DateTime(), nullable=True),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('error_code', sa.String(length=64), nullable=True),
    sa.Column('error_details', sa.JSON(), nullable=True),
    sa.Column('workflow_version', sa.Integer(), nullable=True),
    sa.Column('workflow_snapshot', sa.JSON(), nullable=True),
    sa.Column('logs', sa.JSON(), nullable=True),
    sa.Column('cancel_requested_at', sa.DateTime(), nullable=True),
    sa.Column('cancelled_at', sa.DateTime(), nullable=True),
    sa.Column('triggered_by', sa.UUID(), nullable=True),
    sa.ForeignKeyConstraint(['triggered_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['workflow_id'], ['workflows.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('workflow_versions',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('workflow_id', sa.UUID(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=128), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('nodes_snapshot', sa.JSON(), nullable=False),
    sa.Column('edges_snapshot', sa.JSON(), nullable=False),
    sa.Column('published_by', sa.UUID(), nullable=True),
    sa.Column('published_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['published_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['workflow_id'], ['workflows.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('workflow_id', 'version', name='uq_workflow_version')
    )
    op.create_table('agent_messages',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('task_id', sa.UUID(), nullable=False),
    sa.Column('from_agent_id', sa.UUID(), nullable=True),
    sa.Column('to_agent_id', sa.UUID(), nullable=True),
    sa.Column('message_type', sa.String(length=32), nullable=True),
    sa.Column('content', sa.Text(), nullable=True),
    sa.Column('metadata', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
    sa.ForeignKeyConstraint(['from_agent_id'], ['agents.id'], ),
    sa.ForeignKeyConstraint(['task_id'], ['agent_tasks.id'], ),
    sa.ForeignKeyConstraint(['to_agent_id'], ['agents.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('annotation_results',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('task_id', sa.UUID(), nullable=False),
    sa.Column('sample_index', sa.Integer(), nullable=True),
    sa.Column('sample_path', sa.String(length=512), nullable=True),
    sa.Column('annotations', sa.JSON(), nullable=True),
    sa.Column('status', sa.String(length=16), nullable=True),
    sa.Column('labeled_by', sa.UUID(), nullable=True),
    sa.Column('reviewed_by', sa.UUID(), nullable=True),
    sa.Column('is_auto_labeled', sa.Boolean(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['labeled_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['reviewed_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['task_id'], ['annotation_tasks.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('edges',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('workflow_id', sa.UUID(), nullable=False),
    sa.Column('source_node_id', sa.UUID(), nullable=False),
    sa.Column('source_port', sa.String(length=64), nullable=True),
    sa.Column('target_node_id', sa.UUID(), nullable=False),
    sa.Column('target_port', sa.String(length=64), nullable=True),
    sa.ForeignKeyConstraint(['source_node_id'], ['nodes.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['target_node_id'], ['nodes.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['workflow_id'], ['workflows.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('node_runs',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('run_id', sa.UUID(), nullable=False),
    sa.Column('node_id', sa.UUID(), nullable=True),
    sa.Column('status', sa.String(length=16), nullable=True),
    sa.Column('attempt', sa.Integer(), nullable=False),
    sa.Column('result', sa.JSON(), nullable=True),
    sa.Column('output_meta', sa.JSON(), nullable=True),
    sa.Column('preview_data', sa.Text(), nullable=True),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('error_code', sa.String(length=64), nullable=True),
    sa.Column('error_details', sa.JSON(), nullable=True),
    sa.Column('duration_ms', sa.Integer(), nullable=True),
    sa.Column('logs', sa.JSON(), nullable=True),
    sa.Column('started_at', sa.DateTime(), nullable=True),
    sa.Column('finished_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['node_id'], ['nodes.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['run_id'], ['workflow_runs.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('orchestration_versions',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('app_id', sa.UUID(), nullable=False),
    sa.Column('version', sa.String(length=32), nullable=True),
    sa.Column('status', sa.String(length=16), nullable=True),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('workflow_snapshot', sa.JSON(), nullable=True),
    sa.Column('edge_deployed', sa.Boolean(), nullable=True),
    sa.Column('api_published', sa.Boolean(), nullable=True),
    sa.Column('created_by', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
    sa.ForeignKeyConstraint(['app_id'], ['orchestration_apps.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('platform_apis',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=256), nullable=False),
    sa.Column('api_type', sa.String(length=32), nullable=True),
    sa.Column('algorithm_type', sa.String(length=64), nullable=True),
    sa.Column('endpoint', sa.String(length=512), nullable=True),
    sa.Column('method', sa.String(length=16), nullable=True),
    sa.Column('version', sa.String(length=32), nullable=True),
    sa.Column('status', sa.String(length=16), nullable=True),
    sa.Column('model_id', sa.UUID(), nullable=True),
    sa.Column('workflow_id', sa.UUID(), nullable=True),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('request_schema', sa.JSON(), nullable=True),
    sa.Column('response_schema', sa.JSON(), nullable=True),
    sa.Column('total_calls', sa.Integer(), nullable=True),
    sa.Column('success_calls', sa.Integer(), nullable=True),
    sa.Column('failed_calls', sa.Integer(), nullable=True),
    sa.Column('owner_id', sa.UUID(), nullable=False),
    sa.Column('is_public', sa.Boolean(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['model_id'], ['model_library.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['workflow_id'], ['workflows.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('training_jobs',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('project_id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=128), nullable=False),
    sa.Column('operator_id', sa.String(length=64), nullable=True),
    sa.Column('params', sa.JSON(), nullable=True),
    sa.Column('dataset_path', sa.String(length=512), nullable=True),
    sa.Column('dataset_artifact_id', sa.UUID(), nullable=True),
    sa.Column('status', sa.String(length=16), nullable=True),
    sa.Column('metrics', sa.JSON(), nullable=True),
    sa.Column('model_path', sa.String(length=512), nullable=True),
    sa.Column('model_artifact_id', sa.UUID(), nullable=True),
    sa.Column('model_library_id', sa.UUID(), nullable=True),
    sa.Column('feature_schema', sa.JSON(), nullable=True),
    sa.Column('target_schema', sa.JSON(), nullable=True),
    sa.Column('preprocessing', sa.JSON(), nullable=True),
    sa.Column('error_code', sa.String(length=64), nullable=True),
    sa.Column('error_details', sa.JSON(), nullable=True),
    sa.Column('logs', sa.JSON(), nullable=True),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('started_at', sa.DateTime(), nullable=True),
    sa.Column('finished_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
    sa.Column('early_stopping', sa.Boolean(), nullable=True),
    sa.Column('checkpoint_path', sa.String(length=512), nullable=True),
    sa.Column('model_version', sa.String(length=32), nullable=True),
    sa.Column('epochs_completed', sa.Integer(), nullable=True),
    sa.Column('best_metric_value', sa.Float(), nullable=True),
    sa.ForeignKeyConstraint(['dataset_artifact_id'], ['artifacts.id'], ),
    sa.ForeignKeyConstraint(['model_artifact_id'], ['artifacts.id'], ),
    sa.ForeignKeyConstraint(['model_library_id'], ['model_library.id'], ),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    _create_model_library_training_job_foreign_key()


def downgrade() -> None:
    """Downgrade schema."""
    _drop_model_library_training_job_foreign_key()
    op.drop_table('training_jobs')
    op.drop_table('platform_apis')
    op.drop_table('orchestration_versions')
    op.drop_table('node_runs')
    op.drop_table('edges')
    op.drop_table('annotation_results')
    op.drop_table('agent_messages')
    op.drop_table('workflow_versions')
    op.drop_table('workflow_runs')
    op.drop_table('orchestration_apps')
    op.drop_table('nodes')
    op.drop_table('model_library')
    op.drop_table('kb_chunks')
    op.drop_table('graph_relations')
    op.drop_table('chat_messages')
    op.drop_table('annotation_tasks')
    op.drop_table('agent_tasks')
    op.drop_table('workflows')
    op.drop_table('kb_documents')
    op.drop_index(op.f('ix_graph_entities_name'), table_name='graph_entities')
    op.drop_table('graph_entities')
    op.drop_table('datasets')
    op.drop_table('chat_sessions')
    op.drop_table('artifacts')
    op.drop_table('projects')
    op.drop_table('knowledge_bases')
    op.drop_table('edge_devices')
    op.drop_table('compute_nodes')
    op.drop_table('agents')
    op.drop_index(op.f('ix_users_username'), table_name='users')
    op.drop_table('users')
    op.drop_table('algorithms')


def _create_model_library_training_job_foreign_key() -> None:
    constraint_name = "fk_model_library_training_job_id_training_jobs"
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("model_library") as batch_op:
            batch_op.create_foreign_key(
                constraint_name,
                "training_jobs",
                ["training_job_id"],
                ["id"],
            )
        return
    op.create_foreign_key(
        constraint_name,
        "model_library",
        "training_jobs",
        ["training_job_id"],
        ["id"],
    )


def _drop_model_library_training_job_foreign_key() -> None:
    constraint_name = "fk_model_library_training_job_id_training_jobs"
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("model_library") as batch_op:
            batch_op.drop_constraint(constraint_name, type_="foreignkey")
        return
    op.drop_constraint(constraint_name, "model_library", type_="foreignkey")
