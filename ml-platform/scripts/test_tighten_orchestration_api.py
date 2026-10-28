"""拧紧编排 API 调用测试：原始拧紧记录 CSV → 派生 TIGHTEN_* 特征（与平台 tighten_feature_engineering 同公式）→ 调用 → 断言效果与大屏同步。

用法（backend venv 下运行）：
  python test_tighten_orchestration_api.py --count 5
  python test_tighten_orchestration_api.py --csv C:/Users/17723/Desktop/拧紧/tighten_test.csv --count 10
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
from pathlib import Path

ML_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ML_ROOT / "scripts"))

from workflow_api_test import Client  # noqa: E402

DEFAULT_CSV = r"C:\Users\17723\Desktop\拧紧\tighten_test.csv"
DEFAULT_API_SOURCE = "65bba646-b7b3-4a17-8aa6-64f285cfd955"  # gitleaks:allow 演示环境资源 ID，非凭据

# 平台 tighten_feature_engineering 的原始输入列（CSV 中带中文注解，按基础名解析）
RAW_NUMERIC = [
    "ID", "PROGRAM_NO", "TARGET_TORQUE", "UPPER_LIMIT", "LOWER_LIMIT",
    "ACTUAL_TORQUE", "ACTUAL_TORQUE_TWO", "TYPE_IDENTITY",
]


def read_rows(csv_path: str, limit: int) -> list[dict]:
    import csv as csv_mod

    with open(csv_path, encoding="utf-8-sig") as handle:
        rows = list(csv_mod.DictReader(handle))
    return rows[: max(limit * 3, 50)]  # 多读一些，便于中位数填充


def base_resolver(row: dict):
    """按基础名解析带中文注解的列（与平台算子 resolve_column 同规则）。"""
    lookup = {column.casefold(): column for column in row}

    def resolve(name: str):
        folded = name.casefold()
        if folded in lookup:
            return lookup[folded]
        for column_folded, original in lookup.items():
            base = re.split(r"[(（]", column_folded, maxsplit=1)[0].strip()
            if base == folded:
                return original
        return None

    return resolve


def derive_features(rows: list[dict]) -> list[dict]:
    """复刻平台派生公式：先对原始数值列 median 填充，再派生 6 个 TIGHTEN_* 列。"""
    resolve = base_resolver(rows[0])

    def numeric(row, name):
        column = resolve(name)
        if column is None:
            return None
        try:
            value = float(str(row[column]).strip())
        except (TypeError, ValueError):
            return None
        return value

    # median 填充（与 missing_strategy=median 一致）
    medians: dict[str, float] = {}
    for name in RAW_NUMERIC:
        values = [v for row in rows if (v := numeric(row, name)) is not None]
        if values:
            medians[name] = statistics.median(values)

    def value_or(row, name):
        v = numeric(row, name)
        return v if v is not None else medians.get(name)

    derived_rows = []
    for row in rows:
        torque = value_or(row, "ACTUAL_TORQUE")
        target = value_or(row, "TARGET_TORQUE")
        upper = value_or(row, "UPPER_LIMIT")
        lower = value_or(row, "LOWER_LIMIT")
        torque_two = value_or(row, "ACTUAL_TORQUE_TWO")
        # 原始数值列空值按中位数回填（与平台 missing_strategy=median 一致，
        # 模型原始特征列不接受空串）
        for name in RAW_NUMERIC:
            filled = value_or(row, name)
            column = resolve(name)
            if column is not None and str(row.get(column, "")).strip() == "":
                row[column] = filled
        band = (upper - lower) if upper is not None and lower is not None else None
        features = dict(row)
        features["TIGHTEN_TORQUE_DEVIATION"] = torque - target
        features["TIGHTEN_DEVIATION_RATIO"] = (
            (torque - target) / band if band not in (None, 0) else None)
        features["TIGHTEN_UPPER_MARGIN"] = upper - torque
        features["TIGHTEN_LOWER_MARGIN"] = torque - lower
        features["TIGHTEN_DUAL_AXIS_DIFF"] = torque - torque_two
        missing = any(numeric(row, name) is None for name in RAW_NUMERIC)
        features["TIGHTEN_MISSING_FLAG"] = 1 if missing else 0
        # 派生列残留缺失（零带宽比率）也按中位数补齐
        derived_rows.append(features)

    for name in ("TIGHTEN_DEVIATION_RATIO",):
        values = [r[name] for r in derived_rows if r.get(name) is not None]
        if values:
            median = statistics.median(values)
            for r in derived_rows:
                if r.get(name) is None:
                    r[name] = median
    return derived_rows


def schema_names(api: dict) -> list[str]:
    schema = api.get("request_schema") or {}
    record = schema.get("record") if isinstance(schema, dict) else None
    if not record:
        return []
    return [item.get("name") if isinstance(item, dict) else str(item) for item in record]


def to_number(value):
    try:
        number = float(str(value).strip())
        return int(number) if number == int(number) else number
    except (TypeError, ValueError):
        return value


def align(row: dict, names: list[str]) -> dict:
    resolve = base_resolver(row)

    def find(name: str):
        column = resolve(name)
        if column is None:
            # 请求名带注解而 CSV 列是基础名（或反之）时按基础名再试
            base = re.split(r"[(（]", name, maxsplit=1)[0].strip()
            column = resolve(base) if base else None
        return column

    record: dict = {}
    missing = []
    for name in names:
        column = find(name)
        if column is not None and str(row.get(column)).strip() != "":
            record[name] = to_number(row.get(column))
        elif name in row and str(row.get(name)).strip() != "":
            record[name] = to_number(row.get(name))
        else:
            missing.append(name)
    if missing:
        raise SystemExit(f"输入行缺少 {len(missing)} 个模型特征: {missing[:5]}")
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--csv", default=DEFAULT_CSV)
    parser.add_argument("--count", type=int, default=5)
    parser.add_argument("--api-source", default=DEFAULT_API_SOURCE)
    parser.add_argument("--interval", type=float, default=0.3)
    args = parser.parse_args()

    client = Client("http://localhost:8001")
    import os
    reused = os.environ.get("PLATFORM_TOKEN")
    if reused:
        client.token = reused
    else:
        client.login("admin", "admin123")

    status, apis = client.request("GET", "/api/platform/apis?api_type=orchestration")
    api = next((a for a in apis.get("items", []) if str(a.get("source_id")) == args.api_source), None)
    if api is None:
        raise SystemExit("未找到拧紧编排 API（source_id 不匹配）")
    print(f"编排 API：{api['name']}（{api['version']}）")

    names = schema_names(api)
    print(f"发布特征数：{len(names)}")

    _, before = client.request("GET", f"/api/platform/apis/orchestration/{args.api_source}/showcase-status")
    print(f"调用前计数：total={before.get('total_count')} errors={before.get('error_count')} alerts={before.get('alert_count')}")

    rows = derive_features(read_rows(args.csv, args.count))
    endpoint = f"/api/platform/apis/orchestration/{args.api_source}/invoke"
    ok = errors_hit = 0
    for index in range(args.count):
        record = align(rows[index % len(rows)], names)
        status, body = client.request("POST", endpoint, payload={"record": record})
        if status != 200:
            detail = body.get("detail")
            print(f"[{index + 1}/{args.count}] HTTP {status} | {json.dumps(detail, ensure_ascii=False)[:200]}")
            continue
        ok += 1
        records = body.get("records") or []
        extra = records[0] if records and isinstance(records[0], dict) else {}
        branch = body.get("branch")
        # 报错行经 true 分支到重训阈值节点（输出节点）时 branch 为 null，
        # 但 records 带 total_rows/cycle_rows —— 以此区分正常行
        is_error = branch == "true" or extra.get("total_rows") is not None
        errors_hit += 1 if is_error else 0
        print(
            f"[{index + 1}/{args.count}] HTTP 200 | branch={branch} "
            f"| total_rows={extra.get('total_rows')} cycle={extra.get('cycle_rows')}/{extra.get('threshold_rows')}"
            f"{' ⚠ 触发重训' if extra.get('triggered') else ''}"
        )
        if index < args.count - 1:
            time.sleep(args.interval)

    time.sleep(0.5)
    _, after = client.request("GET", f"/api/platform/apis/orchestration/{args.api_source}/showcase-status")
    print(f"调用后计数：total={after.get('total_count')} errors={after.get('error_count')} alerts={after.get('alert_count')}")

    assert ok == args.count, f"成功调用 {ok}/{args.count}"
    assert after.get("total_count", 0) - before.get("total_count", 0) == args.count, "大屏计数增量与调用数不一致"
    assert after.get("error_count", 0) - before.get("error_count", 0) == errors_hit, "大屏报错计数增量不一致"
    print(f"✅ 拧紧编排 API 测试通过：{ok} 次调用全部 200，大屏（showcase-status）计数同步一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())
