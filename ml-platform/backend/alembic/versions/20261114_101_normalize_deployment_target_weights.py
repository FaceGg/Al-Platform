"""Normalize deployment-target weights so every revision sums to 10000 (§6.3).

Revision ID: 20261114_101
Revises: 20261112_100
Create Date: 2026-11-14

`WeightedTargetRouter` 要求同一 revision 内各 target 的 `weight_bps` 之和
恒为 10000，否则报 `TARGET_WEIGHTS_INVALID`。机群分片挂载路径此前把既有
分片原权重复制进新 revision 再追加新分片（等分预算），导致 2 分片时权重和
为 15000 —— 存量 revision 可能已处于该状态。

本迁移做**数据归一化**：对每个 revision，按各 target 现有权重比例把总预算
10000 重新分配（最大余额法、每片至少 1 基点、单片独享时取满），使权重和恒等
10000。已是 10000 的 revision 不变（幂等）。

注意：这是**存量数据修复**，与挂载侧的新分配算法（`rows`/`total_rows` 行数
比例入参，2026-11-14 B9）配套——先定新规则、再迁存量，避免迁移按旧规则写入
后又要重做。
"""

from alembic import op

import sqlalchemy as sa

revision = "20261114_101"
down_revision = "20261112_100"
branch_labels = None
depends_on = None

TOTAL_WEIGHT_BPS = 10000


def _normalize(weights: list[int]) -> list[int]:
    """按现有比例把 10000 重新分配给各 target（每片至少 1 基点）。"""
    count = len(weights)
    if count == 0:
        return []
    if count == 1:
        return [TOTAL_WEIGHT_BPS]
    positives = [max(0, int(value)) for value in weights]
    total = sum(positives)
    pool = TOTAL_WEIGHT_BPS - count  # 每片先保底 1 基点
    if pool <= 0:
        return [1] * count
    if total <= 0:
        shares = [pool / count] * count
    else:
        shares = [pool * value / total for value in positives]
    allocated = [int(share) for share in shares]
    rest = pool - sum(allocated)
    order = sorted(
        range(count),
        key=lambda index: (-(shares[index] - allocated[index]), index),
    )
    for index in order[: max(0, rest)]:
        allocated[index] += 1
    return [1 + allocated[index] for index in range(count)]


def upgrade() -> None:
    connection = op.get_bind()
    targets = sa.table(
        "deployment_targets",
        sa.column("id", sa.String),
        sa.column("revision_id", sa.String),
        sa.column("weight_bps", sa.Integer),
    )
    revision_ids = connection.execute(
        sa.select(targets.c.revision_id).distinct()
    ).fetchall()
    for (revision_id,) in revision_ids:
        if not revision_id:
            continue
        rows = connection.execute(
            sa.select(targets.c.id, targets.c.weight_bps).where(
                targets.c.revision_id == revision_id
            )
        ).fetchall()
        weights = [int(row.weight_bps or 0) for row in rows]
        if not weights or sum(weights) == TOTAL_WEIGHT_BPS:
            continue
        normalized = _normalize(weights)
        for row, weight in zip(rows, normalized):
            if int(row.weight_bps or 0) != weight:
                connection.execute(
                    targets.update()
                    .where(targets.c.id == row.id)
                    .values(weight_bps=weight)
                )


def downgrade() -> None:
    """权重归一化不可逆（原始比例已丢失）——仅记录，不回滚。

    如需回退，按业务侧的分片行数比例重新分配即可；本迁移不猜测原始值。
    """
    pass
