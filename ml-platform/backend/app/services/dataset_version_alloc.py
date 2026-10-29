"""DatasetVersion 版本号分配（审计 A-18，2026-10-28 批次十二）。

4 处 `version = max+1` 裸算在并发下撞唯一索引 `uq_dataset_versions_project_version`。
共享助手：给版本号构造函数，flush 撞唯一索引时 rollback 后重读重试（≤3 次），
仍冲突抛稳定错误码。双方言合同（SQLite/PG）下优于 PG-only sequence。
"""

from __future__ import annotations

from typing import Callable

from sqlalchemy.exc import IntegrityError


class DatasetVersionConflict(RuntimeError):
    def __init__(self, code: str = "DATASET_VERSION_CONFLICT"):
        self.code = code
        super().__init__(code)


def allocate_dataset_version(db, project_id, build: Callable[[int], object]) -> object:
    """构建并 flush 一个 DatasetVersion 行，唯一索引冲突时换号重试。

    ``build(next_version)`` 必须只构造并 db.add 新版本行（不写子行）；
    flush 成功后返回该对象供调用方继续写 schema 列等子行。
    """
    from app.models.data_version import DatasetVersion

    for _attempt in range(3):
        latest = (
            db.query(DatasetVersion.version)
            .filter(DatasetVersion.project_id == project_id)
            .order_by(DatasetVersion.version.desc())
            .first()
        )
        row = build((int(latest[0]) if latest else 0) + 1)
        db.add(row)
        try:
            db.flush()
            return row
        except IntegrityError:
            db.rollback()
    raise DatasetVersionConflict()
