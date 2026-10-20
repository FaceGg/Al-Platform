"""电焊编排 API 调用测试：原始点焊报告 CSV → 平台特征工程（73 维）→ 调用 → 断言效果与大屏同步。

用法（在 backend venv 下运行，脚本自动把 backend 加入 sys.path 以复用平台特征工程）：
  python test_weld_orchestration_api.py --count 5
  python test_weld_orchestration_api.py --csv C:/Users/17723/Desktop/点焊数据/unlabeled.csv --count 10
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path

ML_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ML_ROOT / "scripts"))
sys.path.insert(0, str(ML_ROOT / "backend"))

from workflow_api_test import Client  # noqa: E402

DEFAULT_CSV = r"C:\Users\17723\Desktop\点焊数据\unlabeled.csv"
DEFAULT_API_SOURCE = "c52c6fb6-73b5-4c57-8adb-069c5db5ba5a"


def build_feature_rows(csv_path: str) -> list[dict]:
    """原始报告行 → 平台 73 维特征（与画布「特征工程」同一实现）。"""
    import pandas as pd

    from app.services.spot_weld_features import build_feature_frame

    frame = pd.read_csv(csv_path)
    features, _, stats = build_feature_frame(frame)
    print(f"特征工程：{len(frame)} 行 × {len(frame.columns)} 列 → {stats['feature_count']} 维特征")
    return features.to_dict(orient="records")


def schema_names(api: dict) -> list[str]:
    schema = api.get("request_schema") or {}
    record = schema.get("record") if isinstance(schema, dict) else None
    if not record:
        return []
    return [item.get("name") if isinstance(item, dict) else str(item) for item in record]


def align(record: dict, names: list[str]) -> dict:
    if not names:
        return record
    missing = [name for name in names if name not in record]
    if missing:
        raise SystemExit(f"特征工程结果缺少 {len(missing)} 个模型特征: {missing[:5]}")
    return {name: record[name] for name in names}


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
        raise SystemExit("未找到电焊编排 API（source_id 不匹配）")
    print(f"编排 API：{api['name']}（{api['version']}）")

    names = schema_names(api)
    print(f"发布特征数：{len(names)}")

    _, before = client.request("GET", f"/api/platform/apis/orchestration/{args.api_source}/showcase-status")
    print(f"调用前计数：total={before.get('total_count')} errors={before.get('error_count')} alerts={before.get('alert_count')}")

    rows = build_feature_rows(args.csv)
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
        triggered = bool(extra.get("triggered"))
        # 报错行经 true 分支到重训阈值节点（输出节点）时 branch 为 null，
        # 但 records 带 total_rows/cycle_rows —— 以此区分正常行
        is_error = body.get("branch") == "true" or extra.get("total_rows") is not None
        errors_hit += 1 if is_error else 0
        print(
            f"[{index + 1}/{args.count}] HTTP 200 | branch={body.get('branch')} "
            f"| total_rows={extra.get('total_rows')} cycle={extra.get('cycle_rows')}/{extra.get('threshold_rows')}"
            f"{' ⚠ 触发重训' if triggered else ''}"
        )
        if index < args.count - 1:
            time.sleep(args.interval)

    time.sleep(0.5)
    _, after = client.request("GET", f"/api/platform/apis/orchestration/{args.api_source}/showcase-status")
    print(f"调用后计数：total={after.get('total_count')} errors={after.get('error_count')} alerts={after.get('alert_count')}")

    assert ok == args.count, f"成功调用 {ok}/{args.count}"
    assert after.get("total_count", 0) - before.get("total_count", 0) == args.count, "大屏计数增量与调用数不一致"
    assert after.get("error_count", 0) - before.get("error_count", 0) == errors_hit, "大屏报错计数增量不一致"
    print(f"✅ 电焊编排 API 测试通过：{ok} 次调用全部 200，大屏（showcase-status）计数同步一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())
