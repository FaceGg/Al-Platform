"""三期前置就绪件：机群特征集 diff（技术方案 §7.4——「≥3 台设备的同构特征
数据」前置，建议开工前用 S1 画像能力做特征集 diff，本工具为其轻量实现）。

输入多个设备 CSV，输出：
- 各设备列集合与 dtype
- 交集/差集矩阵（哪些列缺于哪些设备）
- 可入基线判定：全部设备列集合同构 → 通过；否则列出不对齐设备（§7.5
  「不一致列集的设备不进同一基线」）

用法::

    python tools/fleet_feature_diff.py --data a.csv b.csv c.csv --names devA devB devC
    python tools/fleet_feature_diff.py --data "*.csv" --names devA,devB,devC
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.console_encoding import force_utf8_stdio  # noqa: E402


def diff_feature_sets(paths: list[str], names: list[str] | None = None) -> dict:
    import pandas as pd

    if not paths:
        raise SystemExit("no data files given")
    resolved_names = names if names and len(names) == len(paths) else [f"device-{i + 1}" for i in range(len(paths))]
    profiles: dict[str, dict[str, str]] = {}
    for path, name in zip(paths, resolved_names):
        frame = pd.read_csv(path, nrows=50)
        profiles[name] = {column: str(dtype) for column, dtype in frame.dtypes.items()}
    sets = {name: set(columns) for name, columns in profiles.items()}
    common = set.intersection(*sets.values()) if sets else set()
    union = set.union(*sets.values()) if sets else set()
    devices = list(profiles)
    misaligned = []
    for name in devices:
        missing = sorted(union - sets[name])
        if missing:
            misaligned.append({"device": name, "missing_or_extra": missing})
    dtype_conflicts = []
    for column in sorted(common):
        dtypes = {profiles[name][column] for name in devices}
        if len(dtypes) > 1:
            dtype_conflicts.append({
                "column": column,
                "dtypes": {name: profiles[name][column] for name in devices},
            })
    return {
        "devices": resolved_names,
        "aligned": not misaligned and not dtype_conflicts,
        "common_columns": len(common),
        "union_columns": len(union),
        "per_device_columns": {name: len(columns) for name, columns in sets.items()},
        "misaligned_devices": misaligned,
        "dtype_conflicts": dtype_conflicts,
        "verdict": (
            "PASS: 全部设备特征集同构，可入同一机群基线"
            if not misaligned and not dtype_conflicts
            else "FAIL: 存在不对齐设备/dtype 冲突——按 §7.5 不对齐设备不进同一基线（先特征对齐）"
        ),
    }


def main() -> int:
    # Windows 管道 stdout 默认用 locale 代码页（cp1252），中文 print 会抛
    # UnicodeEncodeError —— 统一切 UTF-8（见 app/console_encoding.py）。
    force_utf8_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", nargs="+", required=True, help="各设备 CSV 路径（支持 glob）")
    parser.add_argument("--names", help="逗号分隔的设备名（缺省 device-N）")
    args = parser.parse_args()
    paths: list[str] = []
    for pattern in args.data:
        matched = sorted(glob.glob(pattern))
        paths.extend(matched if matched else [pattern])
    names = [name.strip() for name in args.names.split(",")] if args.names else None
    report = diff_feature_sets(paths, names)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["aligned"] else 1


if __name__ == "__main__":
    sys.exit(main())
