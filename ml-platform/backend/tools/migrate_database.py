"""Idempotently copy rows between pre-migrated SQLAlchemy databases."""

from __future__ import annotations

from argparse import ArgumentParser
from dataclasses import dataclass
from datetime import datetime
import json
import sys
from typing import Any
from uuid import UUID

from sqlalchemy import MetaData, Table, create_engine, quoted_name, select, update
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.sql.sqltypes import DateTime, JSON, Numeric


@dataclass(frozen=True)
class TableTransferResult:
    source_count: int
    target_count: int
    inserted_count: int
    mismatched_ids: tuple[str, ...]


SKIPPED_TABLES = frozenset({"alembic_version"})


def redact_url(database_url: str) -> str:
    """Return a URL without credentials, query parameters, or fragments."""
    parsed = make_url(database_url).set(query={})
    return str(parsed.set(username=None, password=None))


def _table_key(table: Table, row: dict[str, Any]) -> str:
    values = tuple(
        _canonical(row[column.name], column)
        for column in table.primary_key.columns
    )
    return ":".join(str(value) for value in values)


def _application_tables() -> dict[str, Table]:
    try:
        from app.database import Base
        import app.models  # noqa: F401

        return dict(Base.metadata.tables)
    except ImportError:
        return {}


def _raw_rows(connection: Any, table: Table) -> list[dict[str, Any]]:
    preparer = connection.dialect.identifier_preparer
    columns = ", ".join(preparer.quote(quoted_name(column.name, True)) for column in table.columns)
    qualified_name = ".".join(
        part
        for part in (
            preparer.quote_schema(quoted_name(table.schema, True)) if table.schema else None,
            preparer.quote(quoted_name(table.name, True)),
        )
        if part is not None
    )
    statement = f"SELECT {columns} FROM {qualified_name}"
    result = connection.exec_driver_sql(statement)
    return [dict(zip((column.name for column in table.columns), row)) for row in result]


def _canonical(value: Any, column: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, UUID):
        return str(value)
    if isinstance(column.type, PostgreSQLUUID):
        try:
            return str(UUID(str(value)))
        except ValueError:
            return value
    if isinstance(column.type, JSON) and isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    if isinstance(column.type, DateTime) and isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            return value
    if isinstance(column.type, Numeric) and isinstance(value, str):
        try:
            return str(UUID(value))
        except ValueError:
            return value
    return value


def _rows_equal(source: Table, source_row: dict[str, Any], target: Table, target_row: dict[str, Any]) -> bool:
    return all(
        _canonical(source_row[column.name], column)
        == _canonical(target_row.get(column.name), target.c[column.name])
        for column in source.columns
    )


def _write_value(value: Any, column: Any) -> Any:
    if value is None:
        return None
    if isinstance(column.type, JSON) and isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    if isinstance(column.type, PostgreSQLUUID):
        try:
            return UUID(str(value))
        except ValueError:
            return value
    if isinstance(column.type, DateTime) and isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value
    if isinstance(column.type, Numeric) and isinstance(value, str):
        try:
            return UUID(value)
        except ValueError:
            return value
    return value


def _cyclic_foreign_keys(tables: dict[str, Table]) -> set[tuple[str, str]]:
    dependencies = {
        name: {foreign_key.column.table.name for foreign_key in table.foreign_keys if foreign_key.column.table.name in tables}
        for name, table in tables.items()
    }
    cyclic: set[tuple[str, str]] = set()
    for table_name, table in tables.items():
        for foreign_key in table.foreign_keys:
            parent = foreign_key.column.table.name
            if parent not in tables or parent == table_name:
                if parent == table_name:
                    cyclic.add((table_name, foreign_key.parent.name))
                continue
            stack = [parent]
            seen = set()
            while stack:
                current = stack.pop()
                if current == table_name:
                    if foreign_key.parent.nullable:
                        cyclic.add((table_name, foreign_key.parent.name))
                    break
                if current not in seen:
                    seen.add(current)
                    stack.extend(dependencies[current])
    return cyclic


def _copy_order(tables: dict[str, Table]) -> list[str]:
    dependencies = {
        name: {foreign_key.column.table.name for foreign_key in table.foreign_keys if foreign_key.column.table.name in tables and foreign_key.column.table.name != name}
        for name, table in tables.items()
    }
    order: list[str] = []
    remaining = {name: set(parents) for name, parents in dependencies.items()}
    while remaining:
        ready = sorted(name for name, parents in remaining.items() if not parents)
        if not ready:
            ready = [sorted(remaining)[0]]
        for name in ready:
            if name not in remaining:
                continue
            order.append(name)
            del remaining[name]
        for parents in remaining.values():
            parents.difference_update(ready)
    return order


def copy_database(source_engine: Engine, target_engine: Engine) -> dict[str, TableTransferResult]:
    source_metadata = MetaData()
    target_metadata = MetaData()
    source_metadata.reflect(bind=source_engine)
    target_metadata.reflect(bind=target_engine)
    source_tables = {name: table for name, table in source_metadata.tables.items() if name not in SKIPPED_TABLES}
    target_tables = {name: table for name, table in target_metadata.tables.items() if name not in SKIPPED_TABLES}
    application_tables = _application_tables()
    cyclic_keys = _cyclic_foreign_keys(source_tables)
    source_rows: dict[str, list[dict[str, Any]]] = {}
    results: dict[str, TableTransferResult] = {}
    pending_updates: list[tuple[Table, dict[str, Any], dict[str, Any]]] = []

    with source_engine.connect() as source_connection:
        for name in _copy_order(source_tables):
            source_rows[name] = _raw_rows(source_connection, source_tables[name])

    with target_engine.begin() as target_connection:
        for name in _copy_order(source_tables):
            source_table = source_tables[name]
            target_table = target_tables.get(name)
            if target_table is None:
                raise ValueError(f"Target schema is missing table: {name}")
            target_by_key = {_table_key(target_table, row): row for row in _raw_rows(target_connection, target_table)}
            application_table = application_tables.get(name)
            write_table = (
                application_table
                if application_table is not None
                and {column.name for column in application_table.columns}
                == {column.name for column in target_table.columns}
                else target_table
            )
            inserted = 0
            mismatches: list[str] = []
            for source_row in source_rows[name]:
                key = _table_key(source_table, source_row)
                target_row = target_by_key.get(key)
                if target_row is not None:
                    if not _rows_equal(source_table, source_row, target_table, target_row):
                        mismatches.append(key)
                    continue
                values = {
                    column.name: _write_value(source_row[column.name], write_table.c[column.name])
                    for column in source_table.columns
                }
                for column in source_table.columns:
                    if (name, column.name) in cyclic_keys:
                        pending_updates.append(
                            (write_table, {column.name: _write_value(source_row[column.name], write_table.c[column.name])}, source_row)
                        )
                        values[column.name] = None
                target_connection.execute(write_table.insert().values(values))
                inserted += 1
            target_count = _raw_rows(target_connection, target_table)
            results[name] = TableTransferResult(len(source_rows[name]), len(target_count), inserted, tuple(mismatches))
        for target_table, values, source_row in pending_updates:
            key_values = {
                column.name: _write_value(source_row[column.name], target_table.c[column.name])
                for column in target_table.primary_key.columns
            }
            target_connection.execute(update(target_table).where(
                *[column == value for column, value in ((target_table.c[key], val) for key, val in key_values.items())]
            ).values(values))
    return results


def main(argv: list[str] | None = None) -> int:
    parser = ArgumentParser(description="Copy data between pre-migrated databases")
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--target-url", required=True)
    args = parser.parse_args(argv)
    source_safe = redact_url(args.source_url)
    target_safe = redact_url(args.target_url)
    if source_safe == target_safe:
        print("source and target URLs must differ")
        return 1
    print(f"source={source_safe}")
    print(f"target={target_safe}")
    source_engine = create_engine(args.source_url)
    target_engine = create_engine(args.target_url)
    try:
        results = copy_database(source_engine, target_engine)
    except (SQLAlchemyError, ValueError) as error:
        print(f"migration failed: {error}")
        return 1
    finally:
        source_engine.dispose()
        target_engine.dispose()
    failed = False
    for name, result in results.items():
        print(f"{name}: source={result.source_count} target={result.target_count} inserted={result.inserted_count} mismatched={len(result.mismatched_ids)}")
        failed |= bool(result.mismatched_ids) or result.source_count != result.target_count
    print("migration failed" if failed else "migration complete")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
