from __future__ import annotations

import tempfile
from pathlib import Path

from app.engine.operator_contract import OperatorContext


def resolve_export_path(
    context: OperatorContext,
    operator_id: str,
    file_name: str | None,
    extension: str,
    *,
    legacy_file_path: str | None = None,
) -> Path:
    """Resolve a deterministic export path without exposing server paths to clients."""
    if legacy_file_path and str(legacy_file_path).strip():
        path = Path(str(legacy_file_path)).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

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
