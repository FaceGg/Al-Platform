"""LLM model rows: enabled toggle (multiple models can be on at once).

Revision ID: 20261106_93
Revises: 20261106_92
Create Date: 2026-11-06

模型行启用开关（对齐 ZCode 模型设置样式）：多模型可同时开启，
is_default 仅标记平台默认（单选），语义分离。
"""

import sqlalchemy as sa
from alembic import op

revision = "20261106_93"
down_revision = "20261106_92"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("llm_profiles") as batch_op:
        batch_op.add_column(
            sa.Column(
                "enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("llm_profiles") as batch_op:
        batch_op.drop_column("enabled")
