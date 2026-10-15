"""闭环演示：调用编排 API 驱动实时大屏（演示用离线客户端）。

每次调用 = 大屏上一次数据流动（正常行蓝色链路 / 报错行红色回流 +
告警脉冲；报错累计达阈值触发自动重训，建模完成后下一次调用自动换模）。

目标地址默认本机演示平台；如需指向其他主机，必须显式加 --allow-public
（工具会解析域名并拒绝非私网/环回地址，防止被误用于探测任意远端）。

用法示例：
  # 以 fault=1 的报错行调用 3 次（触发重训）
  python closed_loop_invoke.py --csv ../backend/uploads/labeled_features_demo.csv --row 5 --count 3

  # 指定单行 JSON
  python closed_loop_invoke.py --json row.json --once

  # 自定义地址与账号
  python closed_loop_invoke.py --base-url http://localhost:8001 --username admin --password admin123
"""

from __future__ import annotations

import argparse
import csv
import http.client
import json
import socket
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

DEFAULT_BASE = "http://localhost:8001"
PRIVATE_NETWORKS_NOTE = "演示工具仅允许本机/私网地址；公网目标需显式 --allow-public"


def checked_origin(raw: str, allow_public: bool) -> tuple[str, str, int]:
    """解析并校验目标地址：http(s)、可解析、默认仅私网/环回。"""
    parsed = urlparse(raw if "://" in raw else "http://" + raw)
    scheme = parsed.scheme
    host = parsed.hostname
    port = parsed.port or (443 if scheme == "https" else 80)
    if scheme not in {"http", "https"} or not host:
        raise SystemExit("--base-url 必须是 http(s)://host[:port] 形式")
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(host, port)}
    except socket.gaierror as error:
        raise SystemExit(f"目标主机无法解析：{host}（{error}）") from error

    def is_local(address: str) -> bool:
        return (
            address == "::1"
            or address.startswith("127.")
            or address.startswith("10.")
            or address.startswith("192.168.")
            or address.startswith("169.254.")
            or address.startswith("172.16.")
            or address.startswith("172.17.")
            or address.startswith("172.18.")
            or address.startswith("172.19.")
            or address.startswith("172.2")
            or address.startswith("172.30.")
            or address.startswith("172.31.")
            or address.startswith("fe80:")
        )

    if not allow_public and not all(is_local(address) for address in addresses):
        raise SystemExit(PRIVATE_NETWORKS_NOTE)
    origin = f"{scheme}://{host}:{port}"
    return origin, host, port


class DemoClient:
    """面向已校验 origin 的最小 JSON 客户端。"""

    def __init__(self, host: str, port: int, scheme: str, token: str | None = None):
        if scheme == "https":
            self.connection = http.client.HTTPSConnection(host, port, timeout=60)
        else:
            self.connection = http.client.HTTPConnection(host, port, timeout=60)
        self.token = token

    def request(self, method: str, path: str, payload: dict | None = None) -> tuple[int, dict]:
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        self.connection.request(method, path, body=body, headers=headers)
        with self.connection.getresponse() as response:
            text = response.read().decode("utf-8")
            return response.status, (json.loads(text) if text.strip() else {})

    def login(self, username: str, password: str) -> str:
        form = f"username={username}&password={password}".encode("utf-8")
        self.connection.request(
            "POST",
            "/api/auth/login",
            body=form,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        with self.connection.getresponse() as response:
            return json.loads(response.read().decode("utf-8"))["access_token"]


def pick_orchestration_api(client: DemoClient) -> dict:
    _, data = client.request("GET", "/api/platform/apis?status=published&api_type=orchestration")
    items = [
        item for item in data.get("items", [])
        if item.get("source_kind") == "orchestration" and item.get("showcase_eligible")
    ]
    if not items:
        raise SystemExit("没有可上大屏的编排 API：需由通用闭环服务模板原样创建并发布")
    return items[0]


def align_record(record: dict, api: dict) -> dict:
    """按 API 发布时的 request_schema.record 特征清单过滤对齐输入行。"""
    schema = api.get("request_schema") or {}
    expected = schema.get("record") if isinstance(schema, dict) else None
    if not expected:
        return record
    names = [
        item.get("name") if isinstance(item, dict) else str(item)
        for item in expected
    ]
    aligned: dict = {}
    missing = [name for name in names if name not in record]
    if missing:
        raise SystemExit(
            f"输入数据缺少 {len(missing)} 个模型特征（如 {missing[:5]}）："
            "请先对原始数据做特征工程，或换用含全部特征的 CSV"
        )
    for name in names:
        aligned[name] = record[name]
    return aligned


def load_record(args) -> dict:
    if args.json:
        return json.loads(Path(args.json).read_text(encoding="utf-8"))["record"]
    if args.csv:
        with open(args.csv, encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        index = args.row if args.row is not None else 0
        row = rows[index % len(rows)]
        parsed: dict = {}
        for key, value in row.items():
            if key == "fault":
                continue
            try:
                parsed[key] = float(value)
            except ValueError:
                parsed[key] = value
        return parsed
    raise SystemExit("请用 --json 或 --csv 提供调用数据")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default=DEFAULT_BASE)
    parser.add_argument("--username", default="admin")
    parser.add_argument("--password", default="admin123")
    parser.add_argument("--csv", help="演示 CSV（默认取第 --row 行，跳过 fault 列）")
    parser.add_argument("--row", type=int, default=1, help="CSV 行号（0 起）")
    parser.add_argument("--json", help="单行请求体 JSON 文件（{\"record\": {...}}）")
    parser.add_argument("--count", type=int, default=1, help="调用次数")
    parser.add_argument("--interval", type=float, default=1.5, help="调用间隔秒")
    parser.add_argument("--allow-public", action="store_true", help=PRIVATE_NETWORKS_NOTE)
    args = parser.parse_args()

    origin, host, port = checked_origin(args.base_url, args.allow_public)
    client = DemoClient(host, port, "https" if origin.startswith("https") else "http")
    client.token = client.login(args.username, args.password)
    api = pick_orchestration_api(client)
    endpoint = f"/api/platform/apis/orchestration/{api['source_id']}/invoke"
    print(f"编排 API：{api['name']}（v{api['version']}）")

    record = load_record(args)
    record = align_record(record, api)
    for index in range(args.count):
        status, body = client.request("POST", endpoint, payload={"record": record})
        if status != 200:
            detail = body.get("detail")
            print(f"[{index + 1}/{args.count}] HTTP {status} | {json.dumps(detail, ensure_ascii=False)[:300]}")
        else:
            records = body.get("records") or []
            extra = records[0] if records and isinstance(records[0], dict) else {}
            print(
                f"[{index + 1}/{args.count}] HTTP {status} | branch={body.get('branch')} "
                f"| total_rows={extra.get('total_rows')} cycle={extra.get('cycle_rows')}/"
                f"{extra.get('threshold_rows')} triggered={extra.get('triggered')}"
            )
        if index < args.count - 1:
            time.sleep(args.interval)
    print("提示：报错累计达阈值会触发自动建模；建模完成后，下一次调用将自动完成换模。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
