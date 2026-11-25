"""Read-only SQL whitelist backed by sqlglot parsing (补齐路线第一批 B1-08/D7).

判定矩阵（技术方案 §4.2，单测锁死含绕过用例）：
- 单语句；根节点 SELECT（含 WITH→SELECT；同库 UNION 允许，只受白名单
  结构约束）；
- 拒绝 INTO OUTFILE / COPY TO / 一切 DML / DDL（白名单形态：根节点非
  SELECT 族即拒）；
- 危险函数清单拒绝（pg_sleep/sleep/benchmark/load_file 等）；
- 无 LIMIT 自动补（预览默认 200 行；导入行数上限沿用数据集导入既有
  100 万行上限，由取数层执行）；
- 注释由解析器自然剥除。

字符串匹配方案被否（路线更正 C20）：判定必须基于语法解析。
sqlparse 表达力不足（被否）。
"""
from __future__ import annotations

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError


class SqlWhitelistError(ValueError):
    """ Raised with a stable code when SQL fails the read-only whitelist. """

    def __init__(self, code: str, detail: str | None = None):
        super().__init__(code)
        self.code = code
        self.detail = detail


# 危险函数清单（拒绝执行期副作用/探测函数）；sqlglot 函数名统一小写比较
DANGEROUS_FUNCTIONS = frozenset({
    "pg_sleep",
    "pg_sleep_for",
    "pg_sleep_until",
    "pg_read_file",
    "pg_ls_dir",
    "pg_terminate_backend",
    "pg_reload_conf",
    "lo_import",
    "lo_export",
    "sleep",
    "benchmark",
    "load_file",
    "sys_exec",
    "sys_eval",
    "shell_exec",
    "dbms_sql.execute",
    "utl_file.fopen",
    "xp_cmdshell",
    "readfile",
    "writefile",
})

# 允许的根节点形态：SELECT 族（WITH 归一为带 CTE 的 SELECT；UNION 由
# Select 的 args 承载；Subquery 兜底括号包裹形态）
_SELECT_TYPES = (exp.Select, exp.Union, exp.Except, exp.Intersect)

DEFAULT_PREVIEW_ROW_LIMIT = 200
MAX_IMPORT_ROW_LIMIT = 1_000_000

# db_type → sqlglot 方言（db_type 是存储枚举 'postgresql'/'mysql'）
DIALECT_BY_DB_TYPE = {"postgresql": "postgres", "mysql": "mysql"}


def resolve_dialect(db_type: str) -> str:
    try:
        return DIALECT_BY_DB_TYPE[db_type]
    except KeyError as error:
        raise SqlWhitelistError(
            "SQL_WHITELIST_INVALID",
            f"unsupported db_type {db_type}",
        ) from None


def validate_readonly_sql(sql: str, *, dialect: str, row_limit: int = DEFAULT_PREVIEW_ROW_LIMIT) -> str:
    """校验只读白名单并返回补齐 LIMIT 的规范化 SQL；违例抛 SqlWhitelistError。

    错误码（对外稳定）：SQL_WHITESIGHT_INVALID 由调用方映射 HTTP 400——
    统一码为 SQL_WHITELIST_INVALID / SQL_WHITELIST_MULTIPLE / SQL_WHITELIST_LIMIT。
    """
    if not isinstance(sql, str) or not sql.strip():
        raise SqlWhitelistError("SQL_WHITELIST_INVALID", "empty statement")
    try:
        statements = sqlglot.parse(sql, read=dialect)
    except ParseError as error:
        raise SqlWhitelistError("SQL_WHITELIST_INVALID", str(error)) from None
    if statements is None:
        raise SqlWhitelistError("SQL_WHITELIST_INVALID", "empty statement")
    statements = [statement for statement in statements if statement is not None]
    if len(statements) != 1:
        # 多语句（含引号外分号拼接、尾随 ;DROP）
        raise SqlWhitelistError("SQL_WHITELIST_MULTIPLE")
    root = statements[0]
    # WITH→SELECT：sqlglot 把 CTE 挂在 Select.with_ 上，根节点仍是 Select；
    # 但显式容一层 Subquery 括号包裹形态
    if isinstance(root, exp.Subquery):
        root = root.unnest()
    if not isinstance(root, _SELECT_TYPES):
        raise SqlWhitelistError("SQL_WHITELIST_INVALID", "only SELECT statements are allowed")
    # SELECT ... INTO / INTO OUTFILE（PG COPY TO 是 Command，已被白名单形态拒绝）
    if root.args.get("into") is not None:
        raise SqlWhitelistError("SQL_WHITELIST_INVALID", "INTO clauses are not allowed")
    # 危险函数（含嵌套子查询内的函数；注释已在解析时剥除）
    for node in root.walk():
        name = getattr(node, "sql_name", None)
        if callable(name) and str(name()).lower() in DANGEROUS_FUNCTIONS:
            raise SqlWhitelistError(
                "SQL_WHITELIST_INVALID",
                f"function {name()} is not allowed",
            )
        if isinstance(node, exp.Anonymous):
            func_name = str(node.this or "").strip().lower()
            if func_name in DANGEROUS_FUNCTIONS:
                raise SqlWhitelistError(
                    "SQL_WHITELIST_INVALID",
                    f"function {func_name} is not allowed",
                )
    # 无 LIMIT 自动补；已有 LIMIT 不得越过本层上限
    if isinstance(root, exp.Select) and root.args.get("limit") is None and not isinstance(root, exp.Union):
        root = root.limit(row_limit)
        return root.sql(dialect=dialect)
    if isinstance(root, exp.Union):
        # UNION 顶层无 LIMIT 时包一层补齐
        if root.args.get("limit") is None:
            wrapped = exp.select("*").from_(root.subquery())
            wrapped = wrapped.limit(row_limit)
            return wrapped.sql(dialect=dialect)
        return root.sql(dialect=dialect)
    existing = root.args.get("limit")
    if existing is not None:
        literal = existing.expression if isinstance(existing, exp.Limit) else existing
        try:
            declared = int(literal.this) if hasattr(literal, "this") else int(literal)
        except (TypeError, ValueError, AttributeError):
            declared = None
        if declared is not None and declared > row_limit:
            raise SqlWhitelistError(
                "SQL_WHITELIST_LIMIT",
                f"LIMIT {declared} exceeds the row limit {row_limit}",
            )
    return root.sql(dialect=dialect)
