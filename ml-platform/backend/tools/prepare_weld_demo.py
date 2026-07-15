from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.weld_demo_service import WeldDemoPreparationError, WeldDemoService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prepare a compact feature table from resistance spot welding data.",
    )
    parser.add_argument("--source-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser


def run(argv: list[str] | None = None) -> str:
    args = build_parser().parse_args(argv)
    result = WeldDemoService().prepare(args.source_dir, args.output)
    return json.dumps({
        "output_path": str(result.output_path),
        "row_count": result.row_count,
        "columns": result.columns,
        "class_distribution": result.class_distribution,
        "source_hashes": result.source_hashes,
        "generated_at": result.generated_at,
        "preparation_version": result.preparation_version,
    }, ensure_ascii=False)


def main() -> int:
    try:
        print(run())
        return 0
    except WeldDemoPreparationError as exc:
        print(json.dumps({
            "error": {"code": exc.code, "message": str(exc), "details": exc.details},
        }, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
