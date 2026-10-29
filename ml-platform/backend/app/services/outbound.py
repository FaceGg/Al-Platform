"""统一出站 URL 安全校验（审计 A-05，2026-10-28 批次九）。

算子出站抓取（CSVFromURL/ReadURL）历史上 `urlopen` 无协议白名单、无 DNS
解析校验、默认跟随重定向 → SSRF 面（file://、内网地址、元数据服务）。
webhook_security.validate_webhook_url 已有正确的 DNS 解析 + is_global 判定
但钉死 HTTPS:443；本模块把它泛化为 http/https 任意端口的算子出站口径。
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit

from app.services.webhook_security import (
    METADATA_HOSTS,
    _is_restricted_address,
    _resolve_host,
    _resolved_addresses,
)


class OutboundUrlError(ValueError):
    """出站 URL 被拒（稳定错误码）。"""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def validate_outbound_url(
    url: str,
    *,
    resolve=None,
) -> str:
    """校验算子出站 URL：仅 http/https、公网目标、拒绝内网/环回/链路本地/元数据。

    重定向不在此处跟随——调用方必须禁用自动重定向或对每个 Location 重新
    调用本校验（fetch_outbound_bytes 已实现为对每跳重新校验）。
    """
    if not isinstance(url, str) or not url.strip() or len(url) > 2048:
        raise OutboundUrlError("OUTBOUND_URL_INVALID")
    try:
        parsed = urlsplit(url.strip())
        port = parsed.port
    except ValueError as error:
        raise OutboundUrlError("OUTBOUND_URL_INVALID") from error

    scheme = parsed.scheme.lower()
    if scheme not in ("http", "https"):
        raise OutboundUrlError("OUTBOUND_URL_FORBIDDEN")
    host = (parsed.hostname or "").rstrip(".").lower()
    if (
        not host
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise OutboundUrlError("OUTBOUND_URL_FORBIDDEN")
    try:
        host.encode("ascii")
    except UnicodeEncodeError as error:
        raise OutboundUrlError("OUTBOUND_URL_INVALID") from error

    effective_port = port or (443 if scheme == "https" else 80)
    if host in METADATA_HOSTS or host.endswith(".metadata.google.internal"):
        raise OutboundUrlError("OUTBOUND_URL_FORBIDDEN")

    # 直接给 IP 字面量时按地址判；主机名先做 DNS 解析再判全部结果
    if _looks_like_ip(host):
        candidates = [host]
    else:
        resolver = resolve or _resolve_host
        try:
            candidates = _resolved_addresses(resolver(host, effective_port))
        except (OSError, TypeError, ValueError) as error:
            raise OutboundUrlError("OUTBOUND_URL_UNRESOLVABLE") from error
    if not candidates:
        raise OutboundUrlError("OUTBOUND_URL_UNRESOLVABLE")
    for address in candidates:
        if _is_restricted_address(address):
            raise OutboundUrlError("OUTBOUND_URL_FORBIDDEN")
    return url.strip()


def _looks_like_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def fetch_url_bytes(url: str, *, timeout: float = 60.0) -> bytes:
    """抓取出站 URL 内容：先校验，跟随跳转时对每一跳重新校验（A-05）。"""
    opener = _build_validating_opener()
    validate_outbound_url(url)
    with opener.open(url, timeout=timeout) as response:
        return response.read()


def _build_validating_opener():
    import urllib.request

    class Handler(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            validate_outbound_url(newurl)
            return super().redirect_request(req, fp, code, msg, headers, newurl)

    return urllib.request.build_opener(Handler())


def fetch_url_frame(url: str, file_type: str):
    """抓取出站 URL 并解析为 DataFrame（csv/json/excel，A-05 算子出口）。"""
    import io as _io

    import pandas as pd

    content = fetch_url_bytes(url)
    buf = _io.BytesIO(content)
    if file_type == "excel":
        return pd.read_excel(buf)
    if file_type == "json":
        return pd.read_json(buf)
    return pd.read_csv(buf)
