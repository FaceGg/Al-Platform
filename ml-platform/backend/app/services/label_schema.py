import math
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Mapping

from sqlalchemy.orm import Session

from app.models.labeling import (AnnotationConfirmation, AnnotationRevision, AnnotationSampleCurrent, AnnotationTaskLabel, LabelColumn, LabelSchema, LabelValueConstraint)


DEFAULT_STRING_LABEL_MAX_BYTES = 4096
INT64_MIN = -(2 ** 63)
INT64_MAX = 2 ** 63 - 1


class LabelValueError(ValueError):
    def __init__(self, message: str, code: str = "LABEL_VALUE_INVALID"):
        super().__init__(message)
        self.code = code


def source_column_label_type(dtype: object) -> str | None:
    """Return the compatible label type for a frozen source-schema column."""
    normalized = str(dtype or "").strip().lower()
    if "int" in normalized or "uint" in normalized:
        return "int"
    if any(token in normalized for token in ("float", "double", "decimal", "number")):
        return "float"
    if normalized in {"str", "string", "object", "category"}:
        return "string"
    return None


@dataclass(frozen=True)
class LabelColumnContract:
    machine_key: str
    value_type: str
    required: bool = False
    enum_values: tuple[object, ...] = ()
    min_value: object | None = None
    max_value: object | None = None
    max_length: int | None = None


class LabelSchemaContract:
    def __init__(self, columns):
        self.columns = tuple(columns)
        self.by_key = {column.machine_key: column for column in self.columns}


@dataclass(frozen=True)
class LabelWriteResult:
    values: dict[str, object]
    revision_no: int


@dataclass(frozen=True)
class CurrentLabelSet:
    values: dict[str, object]
    revision_no: int


def validate_label_value(column: LabelColumnContract, value: object) -> object:
    if value is None:
        if column.required:
            raise LabelValueError("required label is missing", "LABEL_REQUIRED_MISSING")
        return None
    kind = column.value_type.lower()
    if kind == "int":
        if isinstance(value, bool) or not re.fullmatch(r"[+-]?\d+", str(value).strip()):
            raise LabelValueError("invalid integer label")
        result = int(str(value).strip())
        if result < INT64_MIN or result > INT64_MAX:
            raise LabelValueError("integer label is outside signed 64-bit range", "LABEL_RANGE_INVALID")
    elif kind == "float":
        if isinstance(value, bool):
            raise LabelValueError("invalid float label")
        try:
            result = float(value)
        except (TypeError, ValueError):
            raise LabelValueError("invalid float label") from None
        if not math.isfinite(result):
            raise LabelValueError("float label must be finite")
    elif kind == "string":
        if not isinstance(value, str):
            raise LabelValueError("string label required")
        result = value.strip()
        if not result:
            raise LabelValueError("string label must not be blank")
        max_length = column.max_length if column.max_length is not None else DEFAULT_STRING_LABEL_MAX_BYTES
        if len(result.encode("utf-8")) > max_length:
            raise LabelValueError("string label exceeds byte limit")
    else:
        raise LabelValueError("unsupported label type")
    if column.enum_values and result not in column.enum_values:
        raise LabelValueError("label is not in enum", "LABEL_ENUM_INVALID")
    if column.min_value is not None and result < column.min_value:
        raise LabelValueError("label is below minimum", "LABEL_RANGE_INVALID")
    if column.max_value is not None and result > column.max_value:
        raise LabelValueError("label is above maximum", "LABEL_RANGE_INVALID")
    return result


def validate_label_values(schema: LabelSchemaContract, values: Mapping[str, object], allow_partial: bool = True) -> dict[str, object]:
    unknown = set(values) - set(schema.by_key)
    if unknown:
        raise LabelValueError("unknown label column", "LABEL_COLUMN_UNKNOWN")
    if not allow_partial:
        missing = [key for key, column in schema.by_key.items() if column.required and key not in values]
        if missing:
            raise LabelValueError("required label is missing", "LABEL_REQUIRED_MISSING")
    return {key: validate_label_value(schema.by_key[key], value) for key, value in values.items()}


def _schema_contract(db: Session, schema_id) -> LabelSchemaContract:
    schema = db.get(LabelSchema, schema_id)
    if schema is None:
        raise LabelValueError("label schema not found", "LABEL_SCHEMA_NOT_FOUND")
    return LabelSchemaContract([
        LabelColumnContract(
            column.machine_key,
            column.value_type,
            required=column.required,
            enum_values=tuple(column.enum_values or ()),
            min_value=column.min_value,
            max_value=column.max_value,
            max_length=column.max_length,
        )
        for column in sorted(schema.columns, key=lambda item: item.ordinal)
    ])


def label_schema_snapshot(schema: LabelSchema) -> dict[str, object]:
    return {
        "schema_id": str(schema.id),
        "name": schema.name,
        "version": schema.version,
        "purpose": schema.purpose,
        "columns": [
            {
                "machine_key": column.machine_key,
                "display_name": column.display_name,
                "ordinal": column.ordinal,
                "value_type": column.value_type,
                "required": column.required,
                "enum_values": list(column.enum_values or []),
                "min_value": column.min_value,
                "max_value": column.max_value,
                "max_length": column.max_length,
                "instruction": column.instruction,
            }
            for column in sorted(schema.columns, key=lambda item: item.ordinal)
        ],
    }


def bind_label_schema_to_task(db: Session, *, task_id, schema: LabelSchema) -> AnnotationTaskLabel:
    existing = db.query(AnnotationTaskLabel).filter_by(task_id=task_id).one_or_none()
    if existing is not None:
        if existing.schema_id != schema.id:
            raise LabelValueError("task is already bound to another label schema", "LABEL_TASK_SCHEMA_MISMATCH")
        return existing
    binding = AnnotationTaskLabel(
        task_id=task_id,
        schema_id=schema.id,
        schema_snapshot=label_schema_snapshot(schema),
    )
    db.add(binding)
    return binding


def require_task_schema_binding(db: Session, *, task_id, schema_id) -> AnnotationTaskLabel:
    binding = db.query(AnnotationTaskLabel).filter_by(task_id=task_id).one_or_none()
    if binding is None:
        raise LabelValueError("task has no label schema binding", "LABEL_TASK_SCHEMA_UNBOUND")
    if binding.schema_id != schema_id:
        raise LabelValueError("task is bound to another label schema", "LABEL_TASK_SCHEMA_MISMATCH")
    return binding


def write_label_revision(db: Session, task_id, sample_id: str, values: Mapping[str, object], author_id, base_revision: int) -> LabelWriteResult:
    current = db.query(AnnotationSampleCurrent).filter_by(task_id=task_id, sample_id=sample_id).one_or_none()
    if current is None:
        raise LabelValueError("sample label state not found", "LABEL_SAMPLE_NOT_FOUND")
    if current.revision_no != base_revision:
        raise LabelValueError("label revision is stale", "LABEL_REVISION_CONFLICT")
    validated = validate_label_values(_schema_contract(db, current.schema_id), values, allow_partial=True)
    merged = dict(current.values or {})
    merged.update(validated)
    revision_no = current.revision_no + 1
    updated = db.query(AnnotationSampleCurrent).filter(
        AnnotationSampleCurrent.id == current.id,
        AnnotationSampleCurrent.revision_no == base_revision,
    ).update({
        AnnotationSampleCurrent.values: merged,
        AnnotationSampleCurrent.revision_no: revision_no,
    }, synchronize_session="fetch")
    if updated != 1:
        db.rollback()
        raise LabelValueError("label revision is stale", "LABEL_REVISION_CONFLICT")
    db.add(AnnotationRevision(
        task_id=task_id, sample_id=sample_id, schema_id=current.schema_id,
        revision_no=revision_no, base_revision=base_revision, values=merged,
        author_id=author_id, source="manual", action="edit",
    ))
    db.commit()
    return LabelWriteResult(merged, revision_no)


def get_current_label_set(db: Session, task_id, sample_id: str) -> CurrentLabelSet:
    current = db.query(AnnotationSampleCurrent).filter_by(task_id=task_id, sample_id=sample_id).one_or_none()
    if current is None:
        raise LabelValueError("sample label state not found", "LABEL_SAMPLE_NOT_FOUND")
    return CurrentLabelSet(dict(current.values or {}), current.revision_no)


def create_label_schema(
    db: Session,
    *,
    project_id,
    name: str,
    columns,
    purpose: str = "annotation",
    commit: bool = True,
) -> LabelSchema:
    latest = db.query(LabelSchema.version).filter(
        LabelSchema.project_id == project_id, LabelSchema.name == name,
    ).order_by(LabelSchema.version.desc()).first()
    schema = LabelSchema(
        project_id=project_id,
        name=name,
        version=(int(latest[0]) if latest else 0) + 1,
        status="active",
        purpose=purpose,
    )
    db.add(schema)
    db.flush()
    for ordinal, item in enumerate(columns):
        payload = item.model_dump() if hasattr(item, "model_dump") else dict(item)
        column = LabelColumn(schema_id=schema.id, ordinal=ordinal, **payload)
        db.add(column)
        db.flush()
        for kind, config in (
            ("enum", {"values": payload.get("enum_values") or []}),
            ("range", {"min": payload.get("min_value"), "max": payload.get("max_value")}),
            ("string_bytes", {"max_length": payload.get("max_length")}),
        ):
            if any(value is not None and value != [] for value in config.values()):
                db.add(LabelValueConstraint(column_id=column.id, kind=kind, config=config))
    if commit:
        db.commit()
        db.refresh(schema)
    else:
        db.flush()
    return schema


def confirm_label_values(db: Session, task_id, sample_id: str, confirmer_id):
    current = db.query(AnnotationSampleCurrent).filter_by(task_id=task_id, sample_id=sample_id).one_or_none()
    if current is None:
        raise LabelValueError("sample label state not found", "LABEL_SAMPLE_NOT_FOUND")
    validate_label_values(_schema_contract(db, current.schema_id), current.values or {}, allow_partial=False)
    revision = db.query(AnnotationRevision).filter_by(
        task_id=task_id, sample_id=sample_id, revision_no=current.revision_no,
    ).one_or_none()
    if revision is None:
        raise LabelValueError("label revision not found", "LABEL_REVISION_NOT_FOUND")
    confirmation = AnnotationConfirmation(
        task_id=task_id, sample_id=sample_id, revision_id=revision.id,
        confirmer_id=confirmer_id, action="confirm",
    )
    db.add(confirmation)
    db.commit()
    return confirmation
