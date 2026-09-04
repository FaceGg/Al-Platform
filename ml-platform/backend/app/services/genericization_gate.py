"""Fail-closed source gate for the industry-neutral production boundary."""

from pathlib import Path


FORBIDDEN_REFERENCES = (
    "spot_weld",
    "SpotWeld",
    "spot-weld",
    "weld_fault",
    "report_v1",
    "FEATURE_SCHEMA",
)
ADAPTER_MARKERS = ("LEGACY_ADAPTER_ONLY = True", "GENERICIZATION_BRIDGE_ONLY = True")
LEGACY_ADAPTER_FILES = {
    "models/spot_weld_quality.py",
    "services/spot_weld_quality.py",
    "services/spot_weld_features.py",
    "tasks/spot_weld_quality_tasks.py",
    "api/spot_weld_quality.py",
    "services/annotation_tasks.py",
    "api/generic_tasks.py",
    "main.py",
    "models/__init__.py",
    "operators/processing.py",
    "tasks/celery_app.py",
}


def _resolve_app_root(root: Path) -> Path:
    root = Path(root).resolve()
    candidates = [root / "app", root / "backend" / "app"]
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    raise ValueError(f"production app directory not found below {root}")


def scan_production_sources(root: Path) -> list[str]:
    """Return forbidden references outside explicitly marked bridge files.

    ``root`` may be either ``ml-platform/backend`` or ``ml-platform``.  The
    scanner intentionally fails when no production app is present so a bad
    caller cannot turn an empty scan into a false pass.
    """
    app_root = _resolve_app_root(root)
    violations: list[str] = []
    scanned = 0
    for path in sorted(app_root.rglob("*.py")):
        scanned += 1
        rel = path.relative_to(app_root).as_posix()
        if rel == "services/genericization_gate.py":
            continue
        text = path.read_text(encoding="utf-8")
        references = [token for token in FORBIDDEN_REFERENCES if token in text]
        if not references:
            continue
        marked = any(marker in text for marker in ADAPTER_MARKERS)
        if rel not in LEGACY_ADAPTER_FILES:
            violations.append(f"{rel}: forbidden reference {references[0]}")
        elif not marked:
            violations.append(f"{rel}: missing LEGACY_ADAPTER_ONLY marker")
    if scanned == 0:
        raise ValueError(f"production app directory is empty: {app_root}")
    return violations
