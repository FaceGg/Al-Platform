import hashlib
import json
import re
import tempfile
import time
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.data_version import DatasetImport, DatasetSample, DatasetSchemaColumn, DatasetVersion
from app.schemas.dataset_import import ParseOptions
from app.services.artifact_service import build_artifact_service


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


def _sniff_source_format(path: Path) -> str:
    raw = path.read_bytes()[:4096]
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
            row[child.tag] = child.text
        columns = set(row)
        if expected_columns is None:
            expected_columns = columns
        elif columns != expected_columns:
            raise DataImportError("DATA_PARSE_DUPLICATE_COLUMN")
        records.append(row)
    return records


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
    schema = [{"name": name, "dtype": str(frame[name].dtype), "nullable": bool(frame[name].isna().any())} for name in frame.columns]
    schema_hash = hashlib.sha256(json.dumps(schema, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    parse_contract = {"parser_version": "1", "source_format": source_format, "sample_id_column": options.sample_id_column, "options": options.model_dump(mode="json"), "field_mapping": {name: name for name in frame.columns}, "row_locator": {sample_id: index for index, sample_id in enumerate(sample_ids)}}
    return NormalizedTable(frame, parse_contract, content_hash, schema_hash, sample_ids, path, None, path.name)


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
        for index, (sample_id, values) in enumerate(zip(normalized.sample_ids, normalized.frame.to_dict(orient="records"))):
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
