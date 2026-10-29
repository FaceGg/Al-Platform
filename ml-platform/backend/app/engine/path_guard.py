"""算子文件访问边界（审计 A-04，2026-10-28 批次九）。

历史行为：import 类算子的 `file_path` 无任何边界，可读服务器任意文件、
export 类算子经 `legacy_file_path` 可写任意路径（均已容器内实证）。
统一口径：读取仅允许「平台上传目录」与「当前运行工作区」两个根下的文件；
导出一律落在工作区 exports 目录（legacy 分支删除，旧参数降级为文件名提示）。
"""

from __future__ import annotations

import os
from pathlib import Path

from app.engine.operator_contract import OperatorContext

# 与历史 app/api/operators.py 的上传目录保持同一路径（单一来源）
UPLOAD_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "uploads"))


class OperatorPathError(RuntimeError):
    """算子文件路径越界（稳定错误码，供上层转算子失败详情）。"""

    def __init__(self, code: str = "OPERATOR_PATH_OUTSIDE_WORKSPACE"):
        self.code = code
        super().__init__(code)


def allowed_read_roots(context: OperatorContext | None) -> list[Path]:
    """算子可读取的根目录：上传目录 + 运行工作区。"""
    roots = [Path(UPLOAD_DIR)]
    workspace = getattr(context, "workspace_dir", None)
    if workspace:
        roots.append(Path(workspace))
    return roots


def resolve_operator_read_path(context: OperatorContext | None, raw: str) -> Path:
    """解析算子读取路径并强制落在允许根内（符号链接先 resolve 再判定）。"""
    if not isinstance(raw, str) or not raw.strip():
        raise OperatorPathError("OPERATOR_PATH_REQUIRED")
    candidate = Path(raw.strip()).expanduser()
    if not candidate.is_absolute():
        # 相对路径按上传目录解析（上传接口返回的是绝对路径，这里兼容手写相对名）
        candidate = Path(UPLOAD_DIR) / candidate
    resolved = candidate.resolve()
    for root in allowed_read_roots(context):
        try:
            if resolved.is_relative_to(root.resolve()):
                return resolved
        except OSError:
            continue
    raise OperatorPathError("OPERATOR_PATH_OUTSIDE_WORKSPACE")
