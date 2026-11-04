"""llm profiles: provider 枚举扩三种 API 格式（responses / anthropic）

Revision ID: 20261104_87
Revises: 20261102_86
Create Date: 2026-11-04

大模型管理支持三种 API 格式：Chat Completions（openai_compatible，
存量不动）/ Responses（OpenAI 新协议 /responses）/ Anthropic Messages
（/v1/messages）。SQLite 需 batch 重建 check constraint。
"""

import sqlalchemy as sa
from alembic import op

revision = "20261104_87"
down_revision = "20261102_86"
branch_labels = None
depends_on = None

_OLD_CONSTRAINT = "ck_llm_profiles_provider"
_NEW_VALUES = "('openai_compatible', 'responses', 'anthropic', 'custom')"


def upgrade() -> None:
    with op.batch_alter_table("llm_profiles") as batch:
        batch.drop_constraint(_OLD_CONSTRAINT, type_="check")
        batch.create_check_constraint(
            _OLD_CONSTRAINT,
            sa.text(f"provider IN {_NEW_VALUES}"),
        )


def downgrade() -> None:
    with op.batch_alter_table("llm_profiles") as batch:
        batch.drop_constraint(_OLD_CONSTRAINT, type_="check")
        batch.create_check_constraint(
            _OLD_CONSTRAINT,
            sa.text("provider IN ('openai_compatible', 'custom')"),
        )
