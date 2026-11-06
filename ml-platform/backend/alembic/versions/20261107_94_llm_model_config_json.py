"""LLM model config JSON (context window / input types / capabilities / reasoning).

Revision ID: 20261107_94
Revises: 20261106_93
Create Date: 2026-11-07

「编辑模型配置」弹窗（对齐 ZCode 模型设置）：上下文窗口、最大输出 Token、
输入类型、模型能力、推理等级与推理参数映射等，统一存 model_config_json。
"""

import sqlalchemy as sa
from alembic import op

revision = "20261107_94"
down_revision = "20261106_93"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("llm_profiles") as batch_op:
        batch_op.add_column(sa.Column("model_config_json", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("llm_profiles") as batch_op:
        batch_op.drop_column("model_config_json")
