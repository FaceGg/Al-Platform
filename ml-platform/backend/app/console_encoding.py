"""控制台输出编码加固（Windows 代码页）。

背景（2026-11-14 CI 失败定位）：Windows 上 ``sys.stdout`` 在「输出被重定向到
管道」时使用 ``locale.getpreferredencoding(False)``——CI 的 ``windows-latest``
runner 为 ``cp1252``，**无法编码中文**。任何 ``print(中文)`` 都会抛
``UnicodeEncodeError: 'charmap' codec can't encode characters``，把整个验收
脚本打挂（``Quality (windows-latest)`` 的 ``test_m6_precision_at_k`` 即此症状：
209 模块里只有它失败，且 Ubuntu 同提交全绿）。

本模块把 stdout/stderr 统一切到 UTF-8，并对无法映射的字符退化为
``replace``（不再抛异常）。幂等，可重复调用；对被替换成非 ``TextIOWrapper``
的流（如 pytest/unittest 的捕获流）静默跳过。

用法::

    from app.console_encoding import force_utf8_stdio

    def main() -> int:
        force_utf8_stdio()
        ...
"""

from __future__ import annotations

import sys
from typing import Any


def force_utf8_stdio() -> None:
    """把 stdout/stderr 重配为 UTF-8（``errors="replace"``），永不抛异常。"""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            # 流已关闭 / 被替换成非 TextIOWrapper → 跳过，不影响主流程
            continue


def stream_encoding(stream: Any) -> str | None:
    """返回流的编码名（无法判定时返回 None）——供测试断言用。"""
    encoding = getattr(stream, "encoding", None)
    return encoding if isinstance(encoding, str) else None
