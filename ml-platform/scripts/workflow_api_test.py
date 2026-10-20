"""工作流编排 API 连通性测试脚本。

针对指定工作流（画布页 URL 里的 ID），自动找到它已发布的编排 API，
按发布时的 request_schema 对齐输入行并调用，验证预测链路是否打通。

用法示例：
  # 1) 探测某工作流的已发布 API 并用 schema 自动生成一条样例数据调用
  python workflow_api_test.py --workflow c5b8256e-bdd3-495c-8d65-c9a34883b996

  # 2) 用 CSV 的第 0 行调用（自动按 schema 对齐列）
  python workflow_api_test.py --workflow c5b8256e-... --csv data.csv --row 0 --count 3

  # 3) 用单行 JSON 调用（{"record": {...}}）并打印完整响应
  python workflow_api_test.py --workflow c5b8256e-... --json row.json --verbose

  # 通过前端内嵌 nginx 反代调用（与 5173 页面同源）
  python workflow_api_test.py --workflow c5b8256e-... --base-url http://localhost:5173
"""

from __future__ import annotations

import argparse
import csv
import http.client
import json
import sys
import time
from pathlib import Path

DEFAULT_BASE = "http://localhost:8001"


class Client:
    """最小 JSON 客户端（连接复用，令牌自动附加）。"""

    def __init__(self, base_url: str, timeout: float = 120.0):
        parsed = http.client.urlsplit(base_url if "://" in base_url else "http://" + base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise SystemExit("--base-url 必须是 http(s)://host[:port] 形式")
        self.prefix = f"{parsed.scheme}://{parsed.hostname}:{parsed.port or (443 if parsed.scheme == 'https' else 80)}"
        if parsed.scheme == "https":
            self.connection = http.client.HTTPSConnection(parsed.hostname, parsed.port or 443, timeout=timeout)
        else:
            self.connection = http.client.HTTPConnection(parsed.hostname, parsed.port or 80, timeout=timeout)
        self.token: str | None = None

    def request(self, method: str, path: str, payload: dict | None = None) -> tuple[int, dict]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        self.connection.request(method, path, body=body, headers=headers)
        with self.connection.getresponse() as response:
            text = response.read().decode("utf-8")
            try:
                data = json.loads(text) if text.strip() else {}
            except json.JSONDecodeError:
                data = {"raw": text[:500]}
            return response.status, data

    def login(self, username: str, password: str) -> None:
        form = f"username={username}&password={password}".encode("utf-8")
        self.connection.request(
            "POST",
            "/api/auth/login",
            body=form,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        with self.connection.getresponse() as response:
            body = json.loads(response.read().decode("utf-8"))
        if response.status != 200 or "access_token" not in body:
            raise SystemExit(f"登录失败（HTTP {response.status}）：{json.dumps(body, ensure_ascii=False)[:300]}")
        self.token = body["access_token"]


def resolve_workflow_api(client: Client, workflow_id: str) -> dict:
    """工作流 → 版本列表 → 已发布的编排 API（按版本 ID 匹配）。"""
    status, data = client.request("GET", f"/api/workflows/{workflow_id}/versions")
    if status == 404:
        raise SystemExit(f"工作流不存在或无权访问：{workflow_id}")
    if status != 200:
        raise SystemExit(f"查询工作流版本失败（HTTP {status}）：{json.dumps(data, ensure_ascii=False)[:300]}")
    version_ids = {item["id"]: item for item in data.get("items", [])}
    if not version_ids:
        raise SystemExit("该工作流还没有发布过版本，请先在画布页发布")

    status, data = client.request("GET", "/api/platform/apis?status=published&api_type=orchestration")
    if status != 200:
        raise SystemExit(f"查询已发布 API 失败（HTTP {status}）：{json.dumps(data, ensure_ascii=False)[:300]}")
    matched = [
        item for item in data.get("items", [])
        if item.get("source_kind") == "orchestration" and item.get("source_id") in version_ids
    ]
    if not matched:
        raise SystemExit(
            "该工作流的版本尚未发布为编排 API：请在「应用编排/API 市场」发布后重试。"
            f"（工作流现有 {len(version_ids)} 个版本均未命中已发布编排 API）"
        )
    matched.sort(key=lambda item: version_ids[item["source_id"]]["version"], reverse=True)
    return matched[0]


def schema_fields(api: dict) -> list[str]:
    schema = api.get("request_schema") or {}
    record = schema.get("record") if isinstance(schema, dict) else None
    if not record:
        return []
    return [item.get("name") if isinstance(item, dict) else str(item) for item in record]


def sample_record(api: dict) -> dict:
    """无外部数据时按 request_schema 生成一条连通性样例（数值 0 / 文本空串）。"""
    fields = schema_fields(api)
    if not fields:
        raise SystemExit("该 API 未登记 request_schema，请用 --csv/--json 提供输入行")
    record: dict = {}
    for field in fields:
        record[field] = 0.0 if _looks_numeric(api, field) else ""
    return record


def _looks_numeric(api: dict, field: str) -> bool:
    schema = api.get("request_schema") or {}
    record = schema.get("record") if isinstance(schema, dict) else None
    for item in record or []:
        if isinstance(item, dict) and item.get("name") == field:
            return str(item.get("dtype") or item.get("type") or "").lower() not in {"str", "string", "object", "text"}
    return True


def align_record(record: dict, api: dict) -> dict:
    """按发布时的 request_schema 对齐输入行；缺列直接报错，防止误测。"""
    fields = schema_fields(api)
    if not fields:
        return record
    missing = [name for name in fields if name not in record]
    if missing:
        raise SystemExit(
            f"输入行缺少 {len(missing)} 个模型特征（如 {missing[:5]}）："
            "原始数据需先过特征工程，或换用含全部特征列的 CSV"
        )
    return {name: record[name] for name in fields}


def load_record(args) -> dict:
    if args.json:
        payload = json.loads(Path(args.json).read_text(encoding="utf-8"))
        return payload.get("record", payload)
    if args.csv:
        with open(args.csv, encoding="utf-8-sig") as handle:
            rows = list(csv.DictReader(handle))
        if not rows:
            raise SystemExit(f"CSV 无数据行：{args.csv}")
        row = rows[args.row % len(rows)]
        parsed: dict = {}
        for key, value in row.items():
            if key is None:
                continue
            try:
                parsed[key] = float(value)
            except (TypeError, ValueError):
                parsed[key] = value
        return parsed
    return {}


def summarize(records: list) -> str:
    if not records or not isinstance(records[0], dict):
        return "-"
    row = records[0]
    prediction = row.get("prediction")
    extra = []
    for key in ("total_rows", "cycle_rows", "threshold_rows", "triggered"):
        if key in row:
            extra.append(f"{key}={row[key]}")
    suffix = (" | " + " ".join(extra)) if extra else ""
    return f"prediction={prediction}{suffix}"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--workflow", required=True, help="工作流 ID（画布页 URL /workspace/<id> 中的 ID）")
    parser.add_argument("--base-url", default=DEFAULT_BASE, help="平台地址（默认 http://localhost:8001，可用 http://localhost:5173 走前端反代）")
    parser.add_argument("--username", default="admin")
    parser.add_argument("--password", default="admin123")
    parser.add_argument("--csv", help="输入 CSV（取 --row 行，自动按 schema 对齐）")
    parser.add_argument("--row", type=int, default=0, help="CSV 行号（0 起）")
    parser.add_argument("--json", help='单行 JSON 文件（{"record": {...}}）')
    parser.add_argument("--sample", action="store_true", help="不提供数据时按 request_schema 生成连通性样例行")
    parser.add_argument("--count", type=int, default=1, help="调用次数")
    parser.add_argument("--interval", type=float, default=1.0, help="调用间隔秒")
    parser.add_argument("--verbose", action="store_true", help="打印首次调用的完整响应")
    args = parser.parse_args()

    client = Client(args.base_url)
    client.login(args.username, args.password)

    api = resolve_workflow_api(client, args.workflow)
    version_id = api["source_id"]
    print(f"编排 API：{api['name']}（v{api['version']}，状态 {api['status']}）")
    print(f"调用端点：POST {client.prefix}/api/platform/apis/orchestration/{version_id}/invoke")

    record = load_record(args)
    if not record:
        if not args.sample:
            print("未提供 --csv/--json，自动使用 --sample 生成连通性样例行")
        record = sample_record(api)
    record = align_record(record, api)
    print(f"输入字段 {len(record)} 个：{list(record)[:6]}{' ...' if len(record) > 6 else ''}")
    print("-" * 72)

    failures = 0
    for index in range(args.count):
        status, body = client.request(
            "POST", f"/api/platform/apis/orchestration/{version_id}/invoke",
            payload={"record": record},
        )
        if status != 200:
            failures += 1
            print(f"[{index + 1}/{args.count}] HTTP {status} | {json.dumps(body.get('detail'), ensure_ascii=False)[:300]}")
            continue
        if index == 0 and args.verbose:
            print(json.dumps(body, ensure_ascii=False, indent=2)[:3000])
        print(f"[{index + 1}/{args.count}] HTTP {status} | branch={body.get('branch')} | {summarize(body.get('records') or [])}")
        if index < args.count - 1:
            time.sleep(args.interval)

    print("-" * 72)
    if failures:
        print(f"完成：{args.count - failures}/{args.count} 成功，{failures} 失败")
        return 1
    print(f"完成：{args.count}/{args.count} 全部成功，预测链路打通")
    return 0


if __name__ == "__main__":
    sys.exit(main())
