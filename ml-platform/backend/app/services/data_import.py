import hashlib
import json
import math
import re
import tempfile
import time
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import numpy as np
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.artifact import Artifact
from app.models.data_version import (
    DatasetImport,
    DatasetImportProcess,
    DatasetSample,
    DatasetSchemaColumn,
    DatasetVersion,
)
from app.models.operation import DurableOperation
from app.schemas.dataset_import import ParseOptions
from app.services.artifact_service import build_artifact_service
from app.services.operation_lifecycle import claim_operation, complete_operation, fail_operation


class DataImportError(ValueError):
    def __init__(self, code: str, message: str | None = None):
        self.code = code
        super().__init__(message or code)


@dataclass
class NormalizedTable:
    frame: pd.DataFrame
    parse_contract: dict[str, Any]
    content_hash: str
    schema_hash: str
    sample_ids: list[str]
    source_path: Path | None = None
    project_id: uuid.UUID | None = None
    source_name: str | None = None


def infer_schema(frame: pd.DataFrame) -> list[dict[str, Any]]:
    """Produce the administrator-confirmable, portable import type proposal."""
    columns = []
    for name in frame.columns:
        series = frame[name]
        if pd.api.types.is_integer_dtype(series.dtype):
            dtype = "int"
        elif pd.api.types.is_float_dtype(series.dtype):
            dtype = "float"
        else:
            dtype = "string"
        columns.append({
            "name": str(name),
            "dtype": dtype,
            "nullable": bool(series.isna().any()),
        })
    return columns


def _confirmed_frame(frame: pd.DataFrame, schema: list[dict[str, Any]], sample_id_column: str | None):
    expected = [str(item.get("name", "")) for item in schema]
    if expected != [str(column) for column in frame.columns] or len(set(expected)) != len(expected):
        raise DataImportError("DATA_SCHEMA_INVALID")
    confirmed = frame.copy()
    for item in schema:
        name = str(item["name"])
        dtype = item.get("dtype")
        if dtype not in {"int", "float", "string"}:
            raise DataImportError("DATA_SCHEMA_TYPE_INVALID")
        series = confirmed[name]
        non_null = series.dropna()
        if dtype == "int":
            numeric = pd.to_numeric(non_null, errors="coerce")
            if numeric.isna().any() or (numeric % 1 != 0).any():
                raise DataImportError("DATA_SCHEMA_VALUE_INVALID", f"invalid int values in column {name}")
            confirmed[name] = pd.to_numeric(series, errors="coerce").astype("Int64")
        elif dtype == "float":
            numeric = pd.to_numeric(non_null, errors="coerce")
            if numeric.isna().any() or not np.isfinite(numeric.astype(float)).all():
                raise DataImportError("DATA_SCHEMA_VALUE_INVALID", f"invalid float values in column {name}")
            confirmed[name] = pd.to_numeric(series, errors="coerce").astype(float)
        else:
            confirmed[name] = series.where(series.isna(), series.astype(str))
    if sample_id_column is not None:
        if sample_id_column not in confirmed.columns:
            raise DataImportError("DATA_SAMPLE_ID_INVALID")
        values = confirmed[sample_id_column].tolist()
        if any(value is None or pd.isna(value) or not str(value).strip() for value in values):
            raise DataImportError("DATA_SAMPLE_ID_INVALID")
        sample_ids = [str(value) for value in values]
        if len(set(sample_ids)) != len(sample_ids):
            raise DataImportError("DATA_SAMPLE_ID_NOT_UNIQUE")
    else:
        content_hash = hashlib.sha256(
            confirmed.to_json(orient="records", date_format="iso", double_precision=15).encode()
        ).hexdigest()
        sample_ids = [str(uuid.uuid5(uuid.NAMESPACE_URL, f"dataset:{content_hash}:{index}")) for index in range(len(confirmed))]
    return confirmed, sample_ids


def _depth(value: Any, level: int = 0) -> int:
    if isinstance(value, dict):
        return max([level] + [_depth(v, level + 1) for v in value.values()])
    if isinstance(value, list):
        return max([level] + [_depth(v, level + 1) for v in value])
    return level


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise DataImportError("DATA_PARSE_DUPLICATE_KEY")
        result[key] = value
    return result


def _scalar(value: Any) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def _json_value(value: Any) -> Any:
    """Convert dataframe values to values accepted by SQLAlchemy JSON."""
    if value is None or value is pd.NaT:
        return None
    if isinstance(value, (pd.Timestamp, pd.Timedelta)):
        return value.isoformat()
    if isinstance(value, (np.datetime64, np.timedelta64)):
        return str(value)
    if isinstance(value, np.generic):
        return _json_value(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _frame_json_records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return [_json_value(record) for record in frame.to_dict(orient="records")]


def _sniff_source_format(path: Path) -> str:
    with path.open("rb") as source:
        raw = source.read(4096)
    stripped = raw.lstrip()
    if raw.startswith(b"PAR1"):
        return "parquet"
    if stripped.startswith((b"[", b"{")):
        return "json"
    if stripped.startswith(b"<"):
        return "xml"
    if zipfile.is_zipfile(path):
        try:
            with zipfile.ZipFile(path) as archive:
                if "[Content_Types].xml" in set(archive.namelist()):
                    return "excel"
        except (OSError, zipfile.BadZipFile):
            pass
    return "csv"


def _decompressed_size(path: Path) -> int:
    if not zipfile.is_zipfile(path):
        return path.stat().st_size
    try:
        with zipfile.ZipFile(path) as archive:
            return sum(item.file_size for item in archive.infolist())
    except (OSError, zipfile.BadZipFile):
        return path.stat().st_size


def _check_frame(frame: pd.DataFrame, options: ParseOptions) -> None:
    if len(frame) > options.max_rows:
        raise DataImportError("DATA_LIMIT_ROWS")
    if len(frame.columns) > options.max_columns:
        raise DataImportError("DATA_LIMIT_COLUMNS")
    if len(set(map(str, frame.columns))) != len(frame.columns):
        raise DataImportError("DATA_PARSE_DUPLICATE_COLUMN")
    for column in frame.columns:
        for value in frame[column]:
            if value is not None and len(str(value).encode("utf-8")) > options.max_field_bytes:
                raise DataImportError("DATA_LIMIT_FIELD_BYTES")


def _json_records(path: Path, options: ParseOptions) -> list[dict]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_pairs)
    except DataImportError:
        raise
    except Exception as error:
        raise DataImportError("DATA_PARSE_INVALID", str(error)) from error
    if _depth(value) > options.max_depth:
        raise DataImportError("DATA_LIMIT_DEPTH")
    if options.record_path:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*", options.record_path):
            raise DataImportError("DATA_PARSE_UNSAFE_PATH")
        for part in options.record_path.split("."):
            if not isinstance(value, dict) or part not in value:
                raise DataImportError("DATA_PARSE_INVALID", "record path not found")
            value = value[part]
    if not isinstance(value, list) or not all(isinstance(row, dict) for row in value):
        raise DataImportError("DATA_PARSE_INVALID", "expected object array")
    if any(not _scalar(item) for row in value for item in row.values()):
        raise DataImportError("DATA_PARSE_NON_SCALAR")
    kinds: dict[str, set[str]] = {}
    for row in value:
        for key, item in row.items():
            if item is None:
                continue
            kind = "bool" if isinstance(item, bool) else "number" if isinstance(item, (int, float)) else "string"
            kinds.setdefault(key, set()).add(kind)
    if any(len(values) > 1 for values in kinds.values()):
        raise DataImportError("DATA_PARSE_INCOMPATIBLE_COLUMN_TYPE")
    return value


def _xml_records(path: Path, options: ParseOptions) -> list[dict]:
    raw = path.read_bytes()
    if len(raw) > options.max_decompressed_bytes or re.search(br"<!DOCTYPE|<!ENTITY|SYSTEM\s+['\"]|PUBLIC\s+['\"]", raw, re.I):
        raise DataImportError("DATA_PARSE_UNSAFE_XML")
    try:
        from defusedxml import ElementTree
        root = ElementTree.parse(path).getroot()
    except Exception as error:
        raise DataImportError("DATA_PARSE_UNSAFE_XML", str(error)) from error
    record_path = options.record_path or ".//record"
    if not re.fullmatch(r"(?:\.//)?[A-Za-z_][A-Za-z0-9_.-]*(?:/[A-Za-z_][A-Za-z0-9_.-]*)*", record_path):
        raise DataImportError("DATA_PARSE_UNSAFE_PATH")
    nodes = root.findall(record_path)
    if not nodes:
        raise DataImportError("DATA_PARSE_INVALID", "no records")
    records = []
    expected_columns = None
    for node in nodes:
        row = dict(node.attrib)
        for child in list(node):
            if list(child):
                raise DataImportError("DATA_PARSE_NON_SCALAR")
            if child.tag in row:
                raise DataImportError("DATA_PARSE_DUPLICATE_COLUMN")
            row[child.tag] = _coerce_xml_scalar(child.text)
        columns = set(row)
        if expected_columns is None:
            expected_columns = columns
        elif columns != expected_columns:
            raise DataImportError("DATA_PARSE_DUPLICATE_COLUMN")
        records.append(row)
    return records


def _coerce_xml_scalar(value: Any) -> Any:
    """Recover unambiguous scalar types from XML text nodes."""
    if value is None or not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return value
    if re.fullmatch(r"[+-]?\d+", text):
        try:
            return int(text)
        except ValueError:
            return value
    if re.fullmatch(
        r"[+-]?(?:\d+\.\d*|\.\d+)(?:[eE][+-]?\d+)?|[+-]?\d+[eE][+-]?\d+",
        text,
    ):
        try:
            number = float(text)
            return number if math.isfinite(number) else value
        except ValueError:
            return value
    if text.lower() in {"true", "false"}:
        return text.lower() == "true"
    return value


def read_dataset_upload(path: Path, source_format: str | None, options: ParseOptions) -> NormalizedTable:
    path = Path(path)
    started = time.monotonic()
    if not path.is_file() or path.stat().st_size > options.max_file_bytes:
        raise DataImportError("DATA_LIMIT_FILE_BYTES")
    if _decompressed_size(path) > options.max_decompressed_bytes:
        raise DataImportError("DATA_LIMIT_DECOMPRESSED_BYTES")
    detected_format = _sniff_source_format(path)
    if source_format is None:
        source_format = detected_format
    else:
        source_format = source_format.lower().lstrip(".")
        source_format = "excel" if source_format in {"xlsx", "xls"} else source_format
    if source_format != detected_format:
        raise DataImportError("DATA_FORMAT_MISMATCH", f"declared format {source_format!r} does not match detected format {detected_format!r}")
    try:
        if source_format == "csv":
            header = path.read_text(encoding="utf-8-sig").splitlines()[0]
            header_columns = next(__import__("csv").reader([header]))
            if len(set(header_columns)) != len(header_columns):
                raise DataImportError("DATA_PARSE_DUPLICATE_COLUMN")
            frame = pd.read_csv(path, sep=options.delimiter, encoding=options.encoding, header=0 if options.has_header else None)
            if not options.has_header:
                frame.columns = [f"column_{index}" for index in range(len(frame.columns))]
        elif source_format in {"excel", "xlsx", "xls"}:
            frame = pd.read_excel(path, sheet_name=options.sheet_name)
            source_format = "excel"
        elif source_format == "parquet":
            frame = pd.read_parquet(path)
        elif source_format == "json":
            frame = pd.DataFrame(_json_records(path, options))
        elif source_format == "xml":
            frame = pd.DataFrame(_xml_records(path, options))
        else:
            raise DataImportError("DATA_PARSE_UNSUPPORTED_FORMAT")
    except DataImportError:
        raise
    except Exception as error:
        raise DataImportError("DATA_PARSE_INVALID", str(error)) from error
    frame.columns = [str(column) for column in frame.columns]
    if time.monotonic() - started > options.max_time_seconds:
        raise DataImportError("DATA_LIMIT_TIME")
    _check_frame(frame, options)
    content_hash = hashlib.sha256(frame.to_json(orient="records", date_format="iso", double_precision=15).encode()).hexdigest()
    if options.sample_id_column:
        if options.sample_id_column not in frame:
            raise DataImportError("DATA_SAMPLE_ID_INVALID")
        values = frame[options.sample_id_column].tolist()
        if any(value is None or pd.isna(value) or not str(value).strip() for value in values):
            raise DataImportError("DATA_SAMPLE_ID_INVALID")
        sample_ids = [str(value) for value in values]
        if len(set(sample_ids)) != len(sample_ids):
            raise DataImportError("DATA_SAMPLE_ID_NOT_UNIQUE")
    else:
        sample_ids = [str(uuid.uuid5(uuid.NAMESPACE_URL, f"dataset:{content_hash}:{index}")) for index in range(len(frame))]
    schema = infer_schema(frame)
    schema_hash = hashlib.sha256(json.dumps(schema, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    parse_contract = {"parser_version": "1", "source_format": source_format, "sample_id_column": options.sample_id_column, "options": options.model_dump(mode="json"), "field_mapping": {name: name for name in frame.columns}, "row_locator": {sample_id: index for index, sample_id in enumerate(sample_ids)}}
    return NormalizedTable(frame, parse_contract, content_hash, schema_hash, sample_ids, path, None, path.name)


def create_dataset_import_process(
    db: Session,
    *,
    project_id: uuid.UUID,
    operator_id: uuid.UUID,
    source_path: Path,
    source_name: str,
    source_format: str | None,
    options: ParseOptions,
    idempotency_key: str,
) -> DatasetImportProcess:
    """Persist the source artifact and a durable parse operation before parsing it."""
    service = build_artifact_service(db)
    original = None
    try:
        original = service.create_from_file(
            project_id,
            source_path,
            source_name,
            "dataset",
            {"source": "dataset_import_original"},
            commit=False,
        )
        operation = DurableOperation(
            resource_key=f"dataset-import:{project_id}",
            idempotency_key=idempotency_key,
            state="queued",
            stage="queued",
        )
        db.add(operation)
        db.flush()
        process = DatasetImportProcess(
            project_id=project_id,
            operator_id=operator_id,
            operation_id=operation.id,
            status="queued",
            source_name=source_name,
            source_format=(source_format or source_path.suffix.lstrip(".")).lower(),
            parse_options=options.model_dump(mode="json"),
            original_artifact_id=original.id,
        )
        db.add(process)
        db.commit()
        db.refresh(process)
        return process
    except Exception:
        db.rollback()
        if original is not None:
            try:
                service.storage.delete(original.storage_uri)
            except Exception:
                pass
        raise


def process_dataset_import(
    db: Session,
    process_id: uuid.UUID,
    *,
    worker_id: str = "dataset-import",
) -> DatasetImportProcess:
    """Parse a durable import into a pending-schema process, never a data version."""
    process = db.get(DatasetImportProcess, process_id)
    if process is None:
        raise DataImportError("DATA_IMPORT_NOT_FOUND")
    if process.status == "pending_schema":
        return process
    if process.status == "ready":
        return process
    if process.operation_id is None or not claim_operation(db, process.operation_id, worker_id, 300):
        db.refresh(process)
        return process

    service = build_artifact_service(db)
    normalized_artifact = None
    try:
        original = db.get(Artifact, process.original_artifact_id)
        if original is None:
            raise DataImportError("DATA_IMPORT_ORIGINAL_MISSING")
        with service.storage.materialize(original.storage_uri) as source_path:
            table = read_dataset_upload(
                source_path,
                process.source_format,
                ParseOptions.model_validate(process.parse_options),
            )
        with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as handle:
            normalized_path = Path(handle.name)
        try:
            table.frame.to_parquet(normalized_path, index=False)
            normalized_artifact = service.create_from_file(
                process.project_id,
                normalized_path,
                "normalized.parquet",
                "dataset",
                {"source": "dataset_import_normalized", "dataset_import_id": str(process.id)},
                commit=False,
            )
        finally:
            normalized_path.unlink(missing_ok=True)
        process.status = "pending_schema"
        process.normalized_artifact_id = normalized_artifact.id
        process.parse_contract = table.parse_contract
        process.inferred_schema = infer_schema(table.frame)
        process.content_hash = table.content_hash
        process.schema_hash = table.schema_hash
        process.error = None
        db.flush()
        complete_operation(
            db,
            process.operation_id,
            worker_id,
            normalized_artifact.id,
            "sha256:" + normalized_artifact.metadata_["sha256"],
        )
        db.refresh(process)
        return process
    except Exception as error:
        db.rollback()
        if normalized_artifact is not None:
            try:
                service.storage.delete(normalized_artifact.storage_uri)
            except Exception:
                pass
        process = db.get(DatasetImportProcess, process_id)
        if process is not None:
            process.status = "failed"
            process.error = {"code": getattr(error, "code", "DATA_IMPORT_FAILED"), "message": str(error)[:300]}
            db.commit()
            fail_operation(db, process.operation_id, process.error["code"], process.error)
        raise


def confirm_dataset_import_schema(
    db: Session,
    process_id: uuid.UUID,
    *,
    schema: list[dict[str, Any]],
    sample_id_column: str | None,
    operator_id: uuid.UUID,
) -> DatasetVersion:
    process = db.get(DatasetImportProcess, process_id)
    if process is None:
        raise DataImportError("DATA_IMPORT_NOT_FOUND")
    if process.status not in {"pending_schema", "confirming"}:
        raise DataImportError("DATA_IMPORT_NOT_PENDING")
    service = build_artifact_service(db)
    original = db.get(Artifact, process.original_artifact_id)
    normalized = db.get(Artifact, process.normalized_artifact_id)
    if original is None or normalized is None:
        raise DataImportError("DATA_IMPORT_ARTIFACT_MISSING")
    if normalized.format != "parquet":
        # Legacy CSV intermediates cannot recover lost string/null distinctions.
        raise DataImportError("DATA_IMPORT_REIMPORT_REQUIRED")
    with service.storage.materialize(normalized.storage_uri) as normalized_path:
        frame = pd.read_parquet(normalized_path)
    confirmed, sample_ids = _confirmed_frame(frame, schema, sample_id_column)
    confirmed_schema = [
        {"name": str(item["name"]), "dtype": str(item["dtype"]), "nullable": bool(confirmed[str(item["name"])].isna().any())}
        for item in schema
    ]
    schema_hash = hashlib.sha256(json.dumps(confirmed_schema, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    parse_contract = {
        **(process.parse_contract or {}),
        "sample_id_column": sample_id_column,
        "confirmed_schema": confirmed_schema,
        "row_locator": {sample_id: index for index, sample_id in enumerate(sample_ids)},
        "options": {
            **((process.parse_contract or {}).get("options") or {}),
            "sample_id_column": sample_id_column,
        },
    }
    latest = db.query(DatasetVersion.version).filter(
        DatasetVersion.project_id == process.project_id
    ).order_by(DatasetVersion.version.desc()).first()
    content_hash = hashlib.sha256(
        confirmed.to_json(orient="records", date_format="iso", double_precision=15).encode()
    ).hexdigest()
    confirmed_artifact = None
    try:
        with tempfile.TemporaryDirectory() as directory:
            confirmed_path = Path(directory) / "confirmed.parquet"
            confirmed.to_parquet(confirmed_path, index=False)
            confirmed_artifact = service.create_from_file(
                process.project_id, confirmed_path, "normalized.parquet", "dataset",
                {"source": "dataset_import_confirmed", "dataset_import_id": str(process.id)},
                commit=False,
            )
        return _freeze_confirmed_import(
            db, process, original, confirmed_artifact, operator_id, confirmed,
            sample_ids, confirmed_schema, parse_contract, content_hash, schema_hash,
            (latest[0] if latest else 0) + 1,
        )
    except Exception:
        db.rollback()
        if confirmed_artifact is not None:
            service.storage.delete(confirmed_artifact.storage_uri)
        raise


def _freeze_confirmed_import(
    db, process, original, normalized, operator_id, confirmed, sample_ids,
    confirmed_schema, parse_contract, content_hash, schema_hash, version_number,
):
    version = DatasetVersion(
        project_id=process.project_id,
        operator_id=operator_id,
        version=version_number,
        status="ready",
        row_count=len(confirmed),
        column_count=len(confirmed.columns),
        content_hash=content_hash,
        schema_hash=schema_hash,
        parse_contract=parse_contract,
        original_artifact_id=original.id,
        normalized_artifact_id=normalized.id,
    )
    db.add(version)
    db.flush()
    for position, item in enumerate(confirmed_schema):
        db.add(DatasetSchemaColumn(
            dataset_version_id=version.id,
            name=item["name"],
            position=position,
            dtype=item["dtype"],
            nullable=item["nullable"],
        ))
    for index, (sample_id, values) in enumerate(zip(sample_ids, _frame_json_records(confirmed))):
        db.add(DatasetSample(
            dataset_version_id=version.id,
            sample_id=sample_id,
            row_index=index,
            values=values,
        ))
    db.add(DatasetImport(
        dataset_version_id=version.id,
        source_format=process.source_format,
        parse_contract=parse_contract,
        content_hash=content_hash,
        schema_hash=schema_hash,
    ))
    process.dataset_version_id = version.id
    process.normalized_artifact_id = normalized.id
    process.content_hash = content_hash
    process.status = "ready"
    process.inferred_schema = confirmed_schema
    process.schema_hash = schema_hash
    process.parse_contract = parse_contract
    db.commit()
    db.refresh(version)
    return version


def execute_dataset_import_confirmation(
    db: Session,
    process_id: uuid.UUID,
    *,
    worker_id: str = "dataset-import-confirmation",
) -> DatasetImportProcess:
    process = db.get(DatasetImportProcess, process_id)
    if process is None:
        raise DataImportError("DATA_IMPORT_NOT_FOUND")
    if process.status == "ready":
        return process
    if process.status != "confirming" or process.confirmation_operation_id is None:
        raise DataImportError("DATA_IMPORT_CONFIRMATION_INVALID")
    if not claim_operation(db, process.confirmation_operation_id, worker_id, 300):
        db.refresh(process)
        return process
    confirmation = (process.parse_contract or {}).get("confirmation") or {}
    try:
        confirm_dataset_import_schema(
            db,
            process.id,
            schema=list(confirmation.get("schema") or []),
            sample_id_column=confirmation.get("sample_id_column"),
            operator_id=process.operator_id,
        )
        complete_operation(
            db,
            process.confirmation_operation_id,
            worker_id,
            process.dataset_version_id,
            "sha256:" + process.schema_hash,
        )
        db.refresh(process)
        return process
    except Exception as error:
        db.rollback()
        process = db.get(DatasetImportProcess, process_id)
        process.status = "failed"
        process.error = {"code": getattr(error, "code", "DATA_IMPORT_CONFIRMATION_FAILED"), "message": str(error)[:300]}
        db.commit()
        fail_operation(db, process.confirmation_operation_id, process.error["code"], process.error)
        raise


def require_ready_dataset_artifact(db: Session, artifact_id, *, project_id=None) -> None:
    query = db.query(DatasetImportProcess).filter(
        (DatasetImportProcess.original_artifact_id == artifact_id)
        | (DatasetImportProcess.normalized_artifact_id == artifact_id),
    )
    if project_id is not None:
        query = query.filter(DatasetImportProcess.project_id == project_id)
    process = query.first()
    if process is not None and process.status != "ready":
        raise DataImportError("DATASET_NOT_READY", "Dataset import must be schema-confirmed before use")


def freeze_dataset_version(db: Session, normalized: NormalizedTable, operator_id: uuid.UUID) -> DatasetVersion:
    for attempt in range(3):
        try:
            return _freeze_dataset_version_once(db, normalized, operator_id)
        except IntegrityError as error:
            db.rollback()
            if attempt == 2:
                raise DataImportError("DATA_VERSION_CONFLICT", "dataset version allocation conflicted") from error


def _freeze_dataset_version_once(db: Session, normalized: NormalizedTable, operator_id: uuid.UUID) -> DatasetVersion:
    if normalized.project_id is None:
        raise DataImportError("DATA_PROJECT_REQUIRED")
    service = build_artifact_service(db)
    artifacts = []
    try:
        original = service.create_from_file(normalized.project_id, normalized.source_path, normalized.source_name or normalized.source_path.name, "dataset", {"source": "original"}, commit=False) if normalized.source_path else None
        if original is not None:
            artifacts.append(original)
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as handle:
            normalized_path = Path(handle.name)
        try:
            normalized.frame.to_csv(normalized_path, index=False)
            normalized_artifact = service.create_from_file(normalized.project_id, normalized_path, "normalized.csv", "dataset", {"source": "normalized"}, commit=False)
        finally:
            normalized_path.unlink(missing_ok=True)
        artifacts.append(normalized_artifact)
        latest_version = db.query(DatasetVersion.version).filter(DatasetVersion.project_id == normalized.project_id).order_by(DatasetVersion.version.desc()).first()
        next_version = (latest_version[0] if latest_version else 0) + 1
        version = DatasetVersion(project_id=normalized.project_id, operator_id=operator_id, version=next_version, row_count=len(normalized.frame), column_count=len(normalized.frame.columns), content_hash=normalized.content_hash, schema_hash=normalized.schema_hash, parse_contract=normalized.parse_contract, original_artifact_id=original.id if original else None, normalized_artifact_id=normalized_artifact.id)
        db.add(version)
        db.flush()
        for position, name in enumerate(normalized.frame.columns):
            db.add(DatasetSchemaColumn(dataset_version_id=version.id, name=name, position=position, dtype=str(normalized.frame[name].dtype), nullable=bool(normalized.frame[name].isna().any())))
        for index, (sample_id, values) in enumerate(zip(normalized.sample_ids, _frame_json_records(normalized.frame))):
            db.add(DatasetSample(dataset_version_id=version.id, sample_id=sample_id, row_index=index, values=values))
        db.add(DatasetImport(dataset_version_id=version.id, source_format=normalized.parse_contract["source_format"], parse_contract=normalized.parse_contract, content_hash=normalized.content_hash, schema_hash=normalized.schema_hash))
        db.commit()
        db.refresh(version)
        return version
    except IntegrityError:
        db.rollback()
        _cleanup_artifacts_or_raise(service, artifacts, None)
        raise
    except Exception as error:
        db.rollback()
        _cleanup_artifacts_or_raise(service, artifacts, error)
        raise


def _cleanup_artifacts_or_raise(service, artifacts, original_error):
    cleanup_errors = []
    for artifact in artifacts:
        try:
            service.storage.delete(artifact.storage_uri)
        except Exception as cleanup_error:
            cleanup_errors.append(f"{artifact.storage_uri}: {cleanup_error}")
    if cleanup_errors:
        raise DataImportError("DATA_CLEANUP_FAILED", "; ".join(cleanup_errors)) from original_error
