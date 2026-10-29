from __future__ import annotations

import tempfile
from pathlib import Path

from app.engine.operator_contract import OperatorContext


def resolve_export_path(
    context: OperatorContext,
    operator_id: str,
    file_name: str | None,
    extension: str,
) -> Path:
    """Resolve a deterministic export path without exposing server paths to clients.

    导出一律落在工作区 exports 目录（审计 A-04：历史 legacy_file_path 分支
    可写服务器任意路径，已删除；旧工作流里的 file_path 参数由调用方降级为
    文件名提示传入 file_name，basename 在此处被截取，不含任何目录语义）。
    """
    workspace = context.workspace_dir or (
        Path(tempfile.gettempdir()) / "ml_platform_data" / "legacy" / str(context.run_id)
    )
    export_dir = Path(workspace) / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)

    suffix = f".{extension.lstrip('.')}"
    requested = Path(str(file_name or "").strip()).name
    stem = Path(requested).stem if requested else f"{operator_id}_{context.node_id}"
    if not stem or stem in {".", ".."}:
        stem = f"{operator_id}_{context.node_id}"
    return export_dir / f"{stem}{suffix}"
