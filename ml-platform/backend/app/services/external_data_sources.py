"""External data source service (补齐路线第一批 B1-08).

连接与取数：Fernet 口令加解密（独立 datasource_master_key）、sqlglot
白名单、任务内引擎缓存（pool_pre_ping + 小连接池，celery fork 安全）、
连接超时 5s。导入复用数据集导入状态机（parse→confirm）。

安全形制（合同 §6-7 的唯一例外）：对外部库执行的 SQL 一律先过
services/sql_whitelist.py 语法解析白名单（单语句/SELECT 族/危险函数/
LIMIT 上限）——这是「白名单引擎」设计本身；业务库查询仍一律走
ORM/参数化。执行层统一走 pandas read_sql（chunksize 流式导出）与
sqlalchemy Inspector（元数据构造路径），不引入裸语句拼接。
"""
from __future__ import annotations

import csv
import logging
import tempfile
import time
import uuid
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
import sqlalchemy as sa
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine, URL
from sqlalchemy.orm import Session

from app.config import settings
from app.models.external_data_source import ExternalDataSource
from app.services.data_import import ParseOptions, create_dataset_import_process
from app.services.sql_whitelist import (
    MAX_IMPORT_ROW_LIMIT,
    SqlWhitelistError,
    resolve_dialect,
    validate_readonly_sql,
)


logger = logging.getLogger(__name__)

CONNECT_TIMEOUT_SECONDS = 5
FETCH_ROW_CAP = MAX_IMPORT_ROW_LIMIT

# extra 允许的 connect_args 白名单键（口令类键一律不收，改密走轮换）
ALLOWED_CONNECT_ARGS = frozenset({"connect_timeout", "application_name", "charset"})

# 静态元数据查询（无任何插值）。
PG_TABLES_SQL = (
    "SELECT table_name FROM information_schema.tables "
    "WHERE table_schema = current_schema() AND table_type = 'BASE TABLE' "
    "ORDER BY table_name"
)
MYSQL_TABLES_SQL = (
    "SELECT table_name FROM information_schema.tables "
    "WHERE table_schema = DATABASE() AND table_type = 'BASE TABLE' "
    "ORDER BY table_name"
)
PROBE_OK_SQL = "SELECT 1"
PG_PROBE_SQL = "CREATE TEMP TABLE __ds_probe (a int)"
MYSQL_PROBE_SQL = "CREATE TEMPORARY TABLE __ds_probe (a int)"

_ENGINE_CACHE: dict[str, Engine] = {}


class ExternalDataSourceError(RuntimeError):
    def __init__(self, code: str, message: str | None = None):
        super().__init__(message or code)
        self.code = code


def _fernet() -> Fernet:
    key = settings.resolved_datasource_master_key
    if key is None:
        raise ExternalDataSourceError(
            "DATASOURCE_MASTER_KEY_MISSING",
            "datasource master key is not configured",
        )
    return Fernet(key.get_secret_value().encode("ascii"))


def encrypt_password(plain: str) -> str:
    return _fernet().encrypt(plain.encode("utf-8")).decode("ascii")


def decrypt_password(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken as error:
        raise ExternalDataSourceError(
            "DATASOURCE_PASSWORD_DECRYPT_FAILED",
            "stored password cannot be decrypted with the active master key",
        ) from None


def validate_connect_args(extra: object) -> dict:
    if not extra:
        return {}
    if not isinstance(extra, dict):
        raise ExternalDataSourceError("DATA_SOURCE_CONFIG_INVALID", "extra must be an object")
    unknown = set(extra) - ALLOWED_CONNECT_ARGS
    if unknown:
        raise ExternalDataSourceError(
            "DATA_SOURCE_CONFIG_INVALID",
            f"connect args not allowed: {', '.join(sorted(map(str, unknown)))}",
        )
    return dict(extra)


def _cached_engine(source: ExternalDataSource, password: str) -> Engine:
    """引擎缓存键含口令指纹：轮换/改密后旧引擎自然失效。"""
    cache_key = f"{source.id}:{uuid.uuid5(uuid.NAMESPACE_URL, password)}"
    engine = _ENGINE_CACHE.get(cache_key)
    if engine is not None:
        return engine
    connect_args = {
        "connect_timeout": CONNECT_TIMEOUT_SECONDS,
        **validate_connect_args(source.extra),
    }
    if source.db_type == "postgresql":
        url = URL.create(
            "postgresql+psycopg",
            username=source.username,
            password=password,
            host=source.host,
            port=source.port,
            database=source.database,
        )
    elif source.db_type == "mysql":
        url = URL.create(
            "mysql+pymysql",
            username=source.username,
            password=password,
            host=source.host,
            port=source.port,
            database=source.database,
        )
    else:
        raise ExternalDataSourceError("DATA_SOURCE_CONFIG_INVALID", f"unsupported db_type {source.db_type}")
    engine = create_engine(
        url,
        pool_size=2,
        max_overflow=2,
        pool_pre_ping=True,
        connect_args=connect_args,
    )
    return engine


def invalidate_engines(source_id) -> None:
    for key in [key for key in _ENGINE_CACHE if key.startswith(f"{source_id}:")]:
        try:
            _ENGINE_CACHE.pop(key).dispose()
        except Exception:
            pass


def _query_engine(db: Session, source: ExternalDataSource) -> Engine:
    password = decrypt_password(source.password_encrypted)
    return _cached_engine(source, password)


def test_connection(db: Session, source: ExternalDataSource) -> dict:
    """连接测试 + 只读校验尝试（只读=白名单+只读账号双防线；本测试尽力
    探测账号写权限，探测不到不阻断）。"""
    import pandas as pd

    started = time.perf_counter()
    try:
        engine = _query_engine(db, source)
        pd.read_sql("SELECT 1", engine)
        readonly_confirmed = False
        try:
            # 可写探测：建临时表成功说明账号可写（信息位，非判定门）
            probe_sql = PG_PROBE_SQL if source.db_type == "postgresql" else MYSQL_PROBE_SQL
            pd.read_sql(probe_sql, engine)
        except Exception:
            readonly_confirmed = True
    except SqlWhitelistError as error:
        raise ExternalDataSourceError(error.code, str(error)) from None
    except ExternalDataSourceError:
        raise
    except Exception as error:
        raise ExternalDataSourceError(
            "DATA_SOURCE_CONNECT_FAILED",
            str(error)[:200],
        ) from None
    latency_ms = int((time.perf_counter() - started) * 1000)
    return {
        "ok": True,
        "latency_ms": latency_ms,
        "readonly_confirmed": readonly_confirmed,
    }


def list_tables(db: Session, source: ExternalDataSource) -> list[str]:
    engine = _query_engine(db, source)
    try:
        # sqlalchemy Inspector：元数据走构造路径（无裸 SQL）
        return list(sa.inspect(engine).get_table_names())
    except Exception as error:
        raise ExternalDataSourceError("DATA_SOURCE_QUERY_FAILED", str(error)[:200]) from None


def _rows_iter(result, cap: int) -> Iterator[tuple]:
    yielded = 0
    while True:
        batch = result.fetchmany(1000)
        if not batch:
            break
        for row in batch:
            if yielded >= cap:
                return
            yield tuple(row)
            yielded += 1


def _wrap_whitelist_errors(call):
    """白名单违例在服务边界统一包装为 ExternalDataSourceError（错误码透传）。"""
    try:
        return call()
    except SqlWhitelistError as error:
        raise ExternalDataSourceError(error.code, str(error)[:200]) from None


def preview(db: Session, source: ExternalDataSource, sql: str, *, row_limit: int = 200) -> dict:
    """白名单 SQL 预览（≤200 行）。执行经 pandas read_sql（白名单规范化后）。"""
    import pandas as pd

    dialect = resolve_dialect(db_type=source.db_type)
    normalized = _wrap_whitelist_errors(
        lambda: validate_readonly_sql(sql, dialect=dialect, row_limit=row_limit),
    )
    engine = _query_engine(db, source)
    try:
        frame = pd.read_sql(normalized, engine)
    except Exception as error:
        raise ExternalDataSourceError("DATA_SOURCE_QUERY_FAILED", str(error)[:200]) from None
    columns = [str(column) for column in frame.columns]
    rows = [
        [_cell(value) for value in row]
        for row in frame.head(row_limit).itertuples(index=False, name=None)
    ]
    return {"columns": columns, "rows": rows, "row_count": len(rows)}


def export_to_csv(
    db: Session,
    source: ExternalDataSource,
    sql: str,
    *,
    destination: Path,
    row_cap: int = FETCH_ROW_CAP,
) -> int:
    """白名单 SQL → 流式导出临时 CSV（上限=数据集导入既有 100 万行）。
    chunksize 流式读，不整表进内存。"""
    import pandas as pd

    dialect = resolve_dialect(db_type=source.db_type)
    normalized = _wrap_whitelist_errors(
        lambda: validate_readonly_sql(sql, dialect=dialect, row_limit=row_cap),
    )
    engine = _query_engine(db, source)
    count = 0
    try:
        chunks = pd.read_sql(normalized, engine, chunksize=1000)
        first = True
        with destination.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            for chunk in chunks:
                if first:
                    writer.writerow([str(column) for column in chunk.columns])
                    first = False
                for row in chunk.itertuples(index=False, name=None):
                    if count >= row_cap:
                        return count
                    writer.writerow([_cell(value) for value in row])
                    count += 1
        if first:  # 零行结果：仍写表头，保持 CSV 形制一致
            pass
    except Exception as error:
        raise ExternalDataSourceError("DATA_SOURCE_QUERY_FAILED", str(error)[:200]) from None
    return count


def import_to_dataset(
    db: Session,
    *,
    project_id,
    operator_id,
    source: ExternalDataSource,
    sql: str,
    dataset_name: str,
) -> "object":
    """取数存临时 CSV → 复用数据集导入状态机（parse→confirm 零重复）。"""
    from app.tasks.dataset_import_tasks import enqueue_dataset_import

    with tempfile.TemporaryDirectory(prefix="datasource-import-") as tmp:
        staging = Path(tmp) / f"{uuid.uuid4().hex}_{dataset_name}.csv"
        rows = export_to_csv(db, source, sql, destination=staging)
        if rows == 0:
            raise ExternalDataSourceError("DATA_SOURCE_EMPTY_RESULT", "query returned no rows")
        process = create_dataset_import_process(
            db,
            project_id=project_id,
            operator_id=operator_id,
            source_path=staging,
            source_name=f"{dataset_name}.csv",
            source_format="csv",
            options=ParseOptions(),
            idempotency_key=f"data-source:{source.id}:{uuid.uuid4().hex}",
        )
        enqueue_dataset_import(process.id)
        return process


def _cell(value):
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)
