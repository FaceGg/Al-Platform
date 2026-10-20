"""Model library entries adopt unified naming: project-experiment-algorithm.

Revision ID: 20261020_73
Revises: 20261019_72
Create Date: 2026-10-20

平台自动创建的模型库条目重命名为「项目名称-实验名称-算法名称」：
- 带来源任务的条目：实验名取任务关联实验（缺失回退任务名），
  算法段优先取条目名（自动建模注册结果携带算法展示名，指标含
  best_score 可识别），否则回退 backbone；
- 不带来源任务但符合闭环换模命名（*-自动模型-8位hex）的条目：
  经引用工件元数据回溯来源任务后按同一规则重命名；
- 手动导入等用户自命名的条目保持不变。重命名纯展示语义，
  所有引用（模型注册表/部署）均按主键关联，不受影响。
"""

import json
import re

from alembic import op
from sqlalchemy import text

revision = "20261020_73"
down_revision = "20261019_72"
branch_labels = None
depends_on = None

CLOSED_LOOP_NAME_PATTERN = re.compile(r"-自动模型-[0-9a-f]{8}$")


def _as_dict(value) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except (TypeError, ValueError):
            return {}
    return {}


def _compose(*segments: str) -> str:
    parts = [str(segment or "").strip() for segment in segments]
    return "-".join(part for part in parts if part)[:256]


def upgrade() -> None:
    conn = op.get_bind()
    rows = conn.execute(
        text(
        """
        SELECT m.id, m.name, m.backbone, m.metrics, m.model_artifact_id,
               p.name AS project_name, m.training_job_id AS direct_job_id,
               a.metadata AS artifact_metadata
        FROM model_library m
        LEFT JOIN projects p ON p.id = m.project_id
        LEFT JOIN artifacts a ON a.id = m.model_artifact_id
        """
        )
    ).fetchall()
    for row in rows:
        metrics = _as_dict(row.metrics)
        if row.direct_job_id is not None:
            job_id = str(row.direct_job_id)
        elif CLOSED_LOOP_NAME_PATTERN.search(str(row.name or "")):
            metadata = _as_dict(row.artifact_metadata)
            job_id = str(metadata.get("training_job_id") or "")
        else:
            continue  # 手动导入等用户自命名条目保持不变
        if not job_id:
            continue
        job = conn.execute(
            text(
            """
            SELECT j.name AS job_name, e.name AS experiment_name
            FROM training_jobs j
            LEFT JOIN experiments e ON e.id = j.experiment_id
            WHERE j.id = :job_id
            """
            ),
            {"job_id": job_id},
        ).fetchone()
        if job is None:
            continue  # 来源任务已删除，实验名不可考，保持原名
        base = (job.experiment_name or "").strip() or (job.job_name or "").strip()
        if metrics.get("best_score") is not None:
            algorithm = str(row.name or "").strip()
        else:
            algorithm = str(row.backbone or "").strip() or str(row.name or "").strip()
        metadata = _as_dict(row.artifact_metadata)
        algorithm = algorithm or str(metadata.get("best_algorithm") or "").strip()
        new_name = _compose(row.project_name, base, algorithm)
        if new_name and new_name != row.name:
            conn.execute(
                text("UPDATE model_library SET name = :name WHERE id = :id"),
                {"name": new_name, "id": str(row.id)},
            )


def downgrade() -> None:
    # 展示名重构，不回滚（原名可由用户自行调整）。
    return None
