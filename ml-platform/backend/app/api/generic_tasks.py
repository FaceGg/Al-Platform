"""Industry-neutral annotation and AutoML task entrypoints."""

from __future__ import annotations

GENERICIZATION_BRIDGE_ONLY = True

import hashlib
import json
import uuid
from datetime import datetime, timezone
from copy import deepcopy
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.api.project_security import require_project_access
from app.database import get_db
from app.models.platform_models import AnnotationTaskRevisionSnapshot, GenericAnnotationTask
from app.models.access import AuditEvent
from app.models.data_version import DatasetSample, DatasetSchemaColumn, DatasetVersion
from app.models.artifact import Artifact
from app.models.labeling import AnnotationStrategyArtifact, AnnotationStrategyDecision, LabelSchema
from app.models.labeling import AnnotationAssignment
from app.models.model_registry import ModelVersion, RegisteredModel
from app.models.project import Project
from app.models.user import User
from app.services.annotation_tasks import migrate_legacy_quality_run
from app.services.annotation_task_state import current_annotation_task_preview, current_annotation_task_snapshot, list_annotation_tasks, serialize_annotation_task
from app.services.annotation_strategies import (
    StrategyConfigError,
    _config_from_snapshot,
    label_schema_contract_from_snapshot,
    validate_strategy_config,
)
from app.services.label_schema import (
    bind_label_schema_to_task,
    create_label_schema,
    label_schema_snapshot,
    source_column_label_type,
)
from app.services.annotation_concurrency import AssignmentError, create_assignments
from app.services.annotation_scope import copy_scope_revision, persist_scope_entries, scope_descriptor, scope_digest
from app.services.rule_dsl import RuleEvaluationError, evaluate_rule
from app.schemas.annotator import AssignmentCreate, AssignmentPatchRequest

router = APIRouter(tags=["generic-tasks"])


class GenericTaskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: uuid.UUID
    dataset_version_id: uuid.UUID
    label_schema_id: uuid.UUID | None = None
    model_version_id: uuid.UUID | None = None
    name: str = Field(default="", max_length=200)
    mode: Literal["manual", "automatic"] = "manual"
    sample_scope: dict = Field(default_factory=lambda: {"kind": "all"})
    label_snapshot: dict = Field(default_factory=dict)
    visible_columns: list[str] = Field(default_factory=list)
    instructions: str = ""
    completion_criteria: str = ""
    due_at: datetime | None = None
    configuration: dict = Field(default_factory=dict)

    @field_validator("sample_scope")
    @classmethod
    def validate_sample_scope(cls, value: dict) -> dict:
        if set(value) - {"kind", "sample_ids", "filters"} or value.get("kind") not in {"all", "ids", "filter"}:
            raise ValueError("sample_scope must declare kind all, ids, or filter")
        if value.get("kind") == "ids" and not isinstance(value.get("sample_ids"), list):
            raise ValueError("sample_scope.ids must be a list")
        if len(json.dumps(value, ensure_ascii=True, separators=(",", ":"))) > 16384:
            raise ValueError("sample_scope exceeds 16 KiB")
        return value

    @field_validator("label_snapshot")
    @classmethod
    def validate_label_snapshot(cls, value: dict) -> dict:
        if len(json.dumps(value, ensure_ascii=True, separators=(",", ":"))) > 65536:
            raise ValueError("label_snapshot exceeds 64 KiB")
        return value


class GenericTaskConfigurationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_revision: int = Field(ge=0)
    name: str | None = Field(default=None, max_length=200)
    visible_columns: list[str] = Field(default_factory=list)
    instructions: str = ""
    completion_criteria: str = ""
    due_at: datetime | None = None
    configuration: dict = Field(default_factory=dict)


def _uuid(value, field: str) -> uuid.UUID:
    try:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError) as error:
        raise HTTPException(status_code=422, detail={"code": "INVALID_UUID", "field": field}) from error


def _serialize(db: Session, task: GenericAnnotationTask) -> dict:
    payload = serialize_annotation_task(task, current_annotation_task_preview(db, task), current_annotation_task_snapshot(db, task))
    payload["created_at"] = task.created_at.isoformat() if task.created_at else None
    payload["name"] = task.name or ""
    payload["completion_criteria"] = task.completion_criteria or ""
    payload["due_at"] = task.due_at.isoformat() if task.due_at else None
    return payload


def _require_project(db: Session, project_id: uuid.UUID, user: User) -> Project:
    project = db.query(Project).filter(Project.id == project_id).first()
    if project is None or project.owner_id != user.id:
        raise HTTPException(status_code=404, detail={"code": "PROJECT_NOT_FOUND"})
    return project


def _contract_error(request: Request, code: str, message: str, status_code: int = 400, details: dict | None = None):
    request_id = str(getattr(request.state, "request_id", "")) or None
    return HTTPException(
        status_code=status_code,
        detail={"request_id": request_id, "code": code, "message": message, "details": details or {}},
    )


def _model_output_value_type(dtype: object) -> str:
    normalized = str(dtype or "").strip().lower()
    if not normalized:
        raise StrategyConfigError("model output type is missing", "MODEL_OUTPUT_CONTRACT_INVALID")
    if "int" in normalized or "uint" in normalized:
        return "int"
    if any(token in normalized for token in ("float", "double", "decimal", "number")):
        return "float"
    if normalized in {"str", "string", "object", "category", "bool", "boolean"}:
        return "string"
    raise StrategyConfigError("model output type is unsupported", "MODEL_OUTPUT_CONTRACT_INVALID")


def _output_contract_columns(model_version: ModelVersion) -> list[dict[str, object]]:
    """Normalize old and new registry records into an immutable label contract."""
    output_schema = dict(model_version.output_schema or {})
    metadata = dict(model_version.conversion_metadata or {})
    input_contract = metadata.get("input_contract")
    input_contract = dict(input_contract) if isinstance(input_contract, dict) else {}
    target_schema = input_contract.get("target_schema")
    target_entries = target_schema if isinstance(target_schema, list) else [target_schema]
    target_by_name = {
        str(item.get("name")): item
        for item in target_entries
        if isinstance(item, dict) and str(item.get("name") or "").strip()
    }

    raw_columns = output_schema.get("columns")
    if not isinstance(raw_columns, list):
        if output_schema.get("name") and output_schema.get("dtype"):
            raw_columns = [output_schema]
        else:
            target_columns = output_schema.get("target_columns") or input_contract.get("target_columns")
            if not isinstance(target_columns, list) or not target_columns:
                raise StrategyConfigError("model output contract has no label columns", "MODEL_OUTPUT_CONTRACT_INVALID")
            raw_columns = []
            for name in target_columns:
                key = str(name or "").strip()
                source = target_by_name.get(key)
                if not key or source is None:
                    raise StrategyConfigError("model output column type is unavailable", "MODEL_OUTPUT_CONTRACT_INVALID")
                raw_columns.append({
                    "machine_key": key,
                    "display_name": source.get("display_name") or key,
                    "dtype": source.get("dtype"),
                    "classes": source.get("classes"),
                })

    columns: list[dict[str, object]] = []
    keys: set[str] = set()
    for raw in raw_columns:
        if not isinstance(raw, dict):
            raise StrategyConfigError("model output contract column is invalid", "MODEL_OUTPUT_CONTRACT_INVALID")
        key = str(raw.get("machine_key") or raw.get("name") or "").strip()
        display_name = str(raw.get("display_name") or raw.get("name") or key).strip()
        value_type = _model_output_value_type(raw.get("value_type") or raw.get("dtype"))
        if not key or not display_name or key in keys:
            raise StrategyConfigError("model output contract has duplicate or empty labels", "MODEL_OUTPUT_CONTRACT_INVALID")
        keys.add(key)
        columns.append({
            "machine_key": key,
            "display_name": display_name,
            "value_type": value_type,
            "required": True,
        })
    if not columns:
        raise StrategyConfigError("model output contract has no label columns", "MODEL_OUTPUT_CONTRACT_INVALID")
    return columns


def _model_output_contract(model_version: ModelVersion, columns: list[dict[str, object]]) -> dict[str, object]:
    payload = {
        "model_version_id": str(model_version.id),
        "registered_model_id": str(model_version.registered_model_id),
        "model_name": model_version.registered_model.name,
        "version_number": model_version.version_number,
        "columns": deepcopy(columns),
    }
    canonical = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return {**payload, "contract_hash": "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()}


def _annotation_model_version(db: Session, project_id: uuid.UUID, model_version_id: uuid.UUID) -> ModelVersion:
    version = db.query(ModelVersion).join(
        RegisteredModel, ModelVersion.registered_model_id == RegisteredModel.id,
    ).filter(
        ModelVersion.id == model_version_id,
        RegisteredModel.project_id == project_id,
    ).one_or_none()
    if version is None:
        raise StrategyConfigError("model version does not belong to this project", "MODEL_VERSION_NOT_FOUND")
    if version.approval_status != "approved" or version.lifecycle_state != "enabled":
        raise StrategyConfigError("model version is not enabled", "MODEL_VERSION_NOT_ENABLED")
    if version.source_kind != "platform_joblib":
        raise StrategyConfigError("automatic annotation requires a platform joblib model", "MODEL_SOURCE_UNSUPPORTED")
    artifact = db.query(Artifact).filter(
        Artifact.id == version.source_artifact_id,
        Artifact.project_id == project_id,
        Artifact.type == "model",
    ).one_or_none()
    if artifact is None:
        raise StrategyConfigError("model version source artifact is unavailable", "MODEL_ARTIFACT_NOT_FOUND")
    return version


def _annotation_model_view(version: ModelVersion) -> dict[str, object]:
    columns = _output_contract_columns(version)
    return {
        "id": str(version.id),
        "registered_model_id": str(version.registered_model_id),
        "model_name": version.registered_model.name,
        "version_number": version.version_number,
        "algorithm": version.algorithm,
        "feature_schema": version.feature_schema or [],
        "output_contract": _model_output_contract(version, columns),
    }


def _automatic_configuration(
    configuration: dict,
    model_version: ModelVersion,
    output_contract: dict[str, object],
) -> dict:
    forbidden = {"model_artifact_id", "model_outputs", "feature_importance", "cluster_ids", "model_output_contract", "model_version_id"}
    supplied = set(configuration)
    internal = sorted(supplied & forbidden)
    if internal:
        raise StrategyConfigError(
            "automatic model binding is controlled by the server",
            "AUTOMATIC_CONFIG_INTERNAL_FIELD",
        )
    return {
        **deepcopy(configuration),
        "model_version_id": str(model_version.id),
        "model_artifact_id": str(model_version.source_artifact_id),
        "model_output_contract": output_contract,
    }


def _automatic_schema_name(model_version: ModelVersion) -> str:
    return f"automatic-output-{model_version.registered_model_id}-{model_version.version_number}"[:128]


def _scope_filter_expression(scope: dict) -> dict | None:
    if scope.get("kind") != "filter":
        return None
    filters = scope.get("filters")
    if not isinstance(filters, dict) or not filters:
        raise ValueError("SAMPLE_SCOPE_FILTER_INVALID")
    expression = filters.get("when") if set(filters) == {"when"} else filters
    if not isinstance(expression, dict) or not expression:
        raise ValueError("SAMPLE_SCOPE_FILTER_INVALID")
    return expression


def _selected_scope_entries(samples_query, scope: dict, matched_ids: set[str] | None = None):
    """Yield one controlled, source-ordered scope without accumulating rows."""
    expression = _scope_filter_expression(scope)
    query = samples_query.order_by(DatasetSample.row_index.asc(), DatasetSample.id.asc()).yield_per(500)
    for sample in query:
        if expression is not None:
            try:
                if not evaluate_rule(expression, dict(sample.values or {})):
                    continue
            except RuleEvaluationError as error:
                raise ValueError("SAMPLE_SCOPE_FILTER_INVALID") from error
        sample_id = str(sample.sample_id)
        if matched_ids is not None:
            matched_ids.add(sample_id)
        yield sample_id, int(sample.row_index)


def _cluster_discovery_ids(db: Session, task: GenericAnnotationTask) -> set[str]:
    artifacts = db.query(AnnotationStrategyArtifact).filter(
        AnnotationStrategyArtifact.task_id == task.id,
    ).order_by(
        AnnotationStrategyArtifact.task_revision.desc(),
        AnnotationStrategyArtifact.created_at.desc(),
    ).all()
    for artifact in artifacts:
        payload = dict(artifact.artifact or {})
        cluster_artifact = payload.get("cluster_artifact")
        assignments = cluster_artifact.get("assignments") if isinstance(cluster_artifact, dict) else None
        if payload.get("configuration_complete") is not False:
            continue
        persisted = db.query(AnnotationStrategyDecision.cluster_id).filter(
            AnnotationStrategyDecision.strategy_artifact_id == artifact.id,
            AnnotationStrategyDecision.cluster_id.isnot(None),
        ).distinct().order_by(AnnotationStrategyDecision.cluster_id.asc()).limit(16).all()
        if persisted:
            return {str(cluster_id) for (cluster_id,) in persisted}
        # Artifacts created before normalized decision storage remain readable.
        if isinstance(assignments, dict):
            return {str(value) for value in assignments.values()}
    return set()


def _validate_automatic_configuration(
    db: Session,
    task: GenericAnnotationTask | None,
    configuration: dict,
    schema_snapshot: dict,
    dataset_version: DatasetVersion | None = None,
) -> None:
    config = _config_from_snapshot(configuration)
    schema = label_schema_contract_from_snapshot(schema_snapshot)
    version = dataset_version or (db.get(DatasetVersion, task.dataset_version_id) if task is not None else None)
    source_column_types = {
        str(column.name): str(column.dtype)
        for column in (version.schema_columns if version is not None else [])
    }
    validate_strategy_config(config, schema, source_column_types=source_column_types)
    if task is not None and config.cluster_discovery:
        raise StrategyConfigError("create a new automatic task to re-run cluster discovery", "CLUSTER_DISCOVERY_IMMUTABLE")
    if (
        task is not None
        and config.clustering
        and not config.cluster_discovery
        and config.strategy in {"cluster", "cluster_rule"}
    ):
        known = _cluster_discovery_ids(db, task)
        selected = {str(value) for value in config.selected_clusters or ()}
        if not known:
            raise StrategyConfigError("run a cluster discovery preview before saving mappings", "CLUSTER_DISCOVERY_REQUIRED")
        if not selected <= known:
            raise StrategyConfigError("selected cluster is not present in the discovery preview", "CLUSTER_SELECTION_INVALID")
        for rule in config.rules:
            rule_clusters = {str(value) for value in rule.get("cluster_ids") or ()}
            if not rule_clusters <= known:
                raise StrategyConfigError("rule cluster filter is not present in the discovery preview", "CLUSTER_SELECTION_INVALID")


@router.get("/api/projects/{project_id}/annotation-model-versions")
def list_annotation_model_versions(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_project(db, project_id, current_user)
    versions = db.query(ModelVersion).join(
        RegisteredModel, ModelVersion.registered_model_id == RegisteredModel.id,
    ).filter(
        RegisteredModel.project_id == project_id,
        or_(
            ModelVersion.lifecycle_state.is_(None),
            ModelVersion.lifecycle_state.notin_(("archived", "revoked")),
        ),
    ).order_by(RegisteredModel.name.asc(), ModelVersion.version_number.desc()).all()
    items = []
    for version in versions:
        # Registered models must stay visible in the picker so users can see
        # why a version cannot back an automatic task; execution itself still
        # requires an approved, enabled platform-joblib version with a usable
        # frozen output contract.
        reason = None
        if version.approval_status != "approved" or (version.lifecycle_state or "pending_review") != "enabled":
            reason = "MODEL_VERSION_NOT_ENABLED"
        elif version.source_kind != "platform_joblib":
            reason = "MODEL_SOURCE_UNSUPPORTED"
        try:
            view = _annotation_model_view(version)
        except StrategyConfigError:
            view = {
                "id": str(version.id),
                "registered_model_id": str(version.registered_model_id),
                "model_name": version.registered_model.name,
                "version_number": version.version_number,
                "algorithm": version.algorithm,
                "feature_schema": version.feature_schema or [],
                "output_contract": None,
            }
            if reason is None:
                reason = "MODEL_OUTPUT_CONTRACT_INVALID"
        items.append({**view, "selectable": reason is None, "ineligible_reason": reason})
    return {"items": items, "total": len(items)}


@router.get("/api/annotation-tasks")
def list_generic_annotation_tasks(
    project_id: uuid.UUID | None = Query(default=None), cursor: str | None = Query(default=None), limit: int = Query(default=50, ge=1, le=200), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    try:
        return list_annotation_tasks(db, project_id, current_user.id, cursor, limit)
    except ValueError as error:
        raise HTTPException(status_code=422, detail={"code": str(error)}) from error


def _assignment_view(assignment: AnnotationAssignment) -> dict[str, object]:
    return {
        "id": str(assignment.id),
        "task_id": str(assignment.task_id),
        "annotator_subject_id": str(assignment.annotator_subject_id),
        "sample_scope": assignment.sample_scope or {},
        "scope_hash": assignment.scope_hash,
        "state": assignment.state,
        "task_revision": assignment.task_revision,
        "due_at": assignment.due_at.isoformat() if assignment.due_at else None,
    }


@router.get("/api/annotation-tasks/{task_id}/assignments")
def list_generic_annotation_assignments(
    task_id: uuid.UUID,
    request: Request,
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    task = db.query(GenericAnnotationTask).filter(
        GenericAnnotationTask.id == task_id,
        GenericAnnotationTask.owner_id == current_user.id,
        GenericAnnotationTask.archived_at.is_(None),
    ).one_or_none()
    if task is None:
        raise _contract_error(request, "TASK_NOT_FOUND", "The task was not found.", status_code=404)
    query = db.query(AnnotationAssignment).filter(
        AnnotationAssignment.task_id == task_id,
    )
    total = query.count()
    if cursor:
        try:
            marker_id = uuid.UUID(str(cursor))
        except (TypeError, ValueError, AttributeError) as error:
            raise _contract_error(request, "INVALID_CURSOR", "The cursor is invalid.", status_code=422) from error
        marker = query.filter(AnnotationAssignment.id == marker_id).one_or_none()
        if marker is None:
            raise _contract_error(request, "INVALID_CURSOR", "The cursor is invalid.", status_code=422)
        query = query.filter(AnnotationAssignment.id < marker.id)
    rows = query.order_by(AnnotationAssignment.id.desc()).limit(limit + 1).all()
    has_next = len(rows) > limit
    rows = rows[:limit]
    return {
        "items": [_assignment_view(row) for row in rows],
        "total": total,
        "next_cursor": str(rows[-1].id) if has_next and rows else None,
    }


@router.post("/api/annotation-tasks/{task_id}/assignments", status_code=status.HTTP_202_ACCEPTED)
def create_generic_annotation_assignments(
    task_id: uuid.UUID,
    data: AssignmentCreate,
    request: Request,
    x_request_id: str | None = Header(default=None, alias="X-Request-ID"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    task = db.query(GenericAnnotationTask).filter(
        GenericAnnotationTask.id == task_id,
        GenericAnnotationTask.owner_id == current_user.id,
        GenericAnnotationTask.archived_at.is_(None),
    ).one_or_none()
    if task is None:
        raise _contract_error(request, "TASK_NOT_FOUND", "The task was not found.", status_code=404)
    if not idempotency_key:
        raise _contract_error(request, "IDEMPOTENCY_KEY_REQUIRED", "Idempotency-Key is required.", status_code=400)
    if not x_request_id or str(getattr(request.state, "request_id", "")) != x_request_id:
        raise _contract_error(request, "REQUEST_ID_REQUIRED", "X-Request-ID is required.", status_code=400)
    try:
        assignments = create_assignments(
            db,
            task_id=task_id,
            annotator_ids=data.annotator_ids,
            sample_scope=data.sample_scope,
            due_at=data.due_at,
            actor=current_user.id,
            idempotency_key=idempotency_key,
        )
    except (ValueError, AssignmentError) as error:
        raise _contract_error(
            request,
            getattr(error, "code", "ASSIGNMENT_INVALID"),
            str(error),
            status_code=422,
        ) from error
    return {
        "assignment_ids": [str(item.id) for item in assignments],
        "items": [_assignment_view(item) for item in assignments],
        "sample_scope_hash": assignments[0].scope_hash if assignments else None,
        "task_revision": task.task_revision,
    }


@router.patch("/api/annotation-tasks/{task_id}/assignments/{assignment_id}")
def patch_generic_annotation_assignment(
    task_id: uuid.UUID,
    assignment_id: uuid.UUID,
    data: AssignmentPatchRequest,
    request: Request,
    x_request_id: str | None = Header(default=None, alias="X-Request-ID"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _request_context(request, x_request_id, idempotency_key)
    assignment = db.query(AnnotationAssignment).join(
        GenericAnnotationTask,
        GenericAnnotationTask.id == AnnotationAssignment.task_id,
    ).filter(
        AnnotationAssignment.id == assignment_id,
        AnnotationAssignment.task_id == task_id,
        GenericAnnotationTask.owner_id == current_user.id,
        GenericAnnotationTask.archived_at.is_(None),
    ).one_or_none()
    if assignment is None:
        raise _contract_error(request, "ASSIGNMENT_NOT_FOUND", "The assignment was not found.", status_code=404)
    try:
        from app.services.annotation_concurrency import transition_assignment
        updated = transition_assignment(
            db,
            assignment.id,
            action=data.action,
            task_revision=data.task_revision,
            actor=current_user,
            idempotency_key=idempotency_key,
            request_id=getattr(request.state, "request_id", None),
        )
    except (ValueError, AssignmentError) as error:
        raise _contract_error(
            request,
            getattr(error, "code", "ASSIGNMENT_STATE_INVALID"),
            str(error),
            status_code=409,
        ) from error
    stored = getattr(updated, "_command_response_payload", None)
    return stored if isinstance(stored, dict) else _assignment_view(updated)


@router.delete("/api/annotation-tasks/{task_id}", status_code=204)
def delete_generic_annotation_task(
    task_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    task = db.query(GenericAnnotationTask).filter(
        GenericAnnotationTask.id == task_id,
        GenericAnnotationTask.owner_id == current_user.id,
        GenericAnnotationTask.archived_at.is_(None),
    ).one_or_none()
    if task is None:
        raise _contract_error(request, "TASK_NOT_FOUND", "The task was not found.", status_code=404)
    if task.status in {"executing", "awaiting_annotation", "in_progress", "awaiting_return"}:
        raise _contract_error(
            request,
            "TASK_ACTIVE",
            "Cancel the active task before deleting it.",
            status_code=409,
        )
    task.archived_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()


@router.post("/api/annotation-tasks/{task_id}/restore")
def restore_generic_annotation_task(
    task_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    task = db.query(GenericAnnotationTask).filter(
        GenericAnnotationTask.id == task_id,
        GenericAnnotationTask.owner_id == current_user.id,
        GenericAnnotationTask.archived_at.is_not(None),
    ).one_or_none()
    if task is None:
        raise _contract_error(request, "TASK_NOT_FOUND", "The task was not found.", status_code=404)
    task.archived_at = None
    db.commit()
    return serialize_annotation_task(task)


def _request_context(request: Request, x_request_id: str | None, idempotency_key: str | None):
    request_id = getattr(request.state, "request_id", None)
    if not x_request_id or request_id is None or str(request_id) != x_request_id:
        raise _contract_error(request, "REQUEST_ID_REQUIRED", "X-Request-ID is required")
    if not idempotency_key or len(idempotency_key) > 128:
        raise _contract_error(request, "IDEMPOTENCY_KEY_REQUIRED", "Idempotency-Key is required")
    return idempotency_key


def _validated_visible_columns(
    source_columns: list[DatasetSchemaColumn],
    requested_columns: list[str],
) -> list[str]:
    visible_columns = list(requested_columns)
    source_names = {str(column.name) for column in source_columns}
    if len(visible_columns) != len(set(visible_columns)) or any(
        column not in source_names for column in visible_columns
    ):
        raise ValueError("VISIBLE_COLUMN_INVALID")
    return visible_columns


def _validate_manual_source_label_columns(
    schema: LabelSchema,
    source_columns: list[DatasetSchemaColumn],
) -> None:
    source_by_name = {str(column.name): column for column in source_columns}
    for label_column in schema.columns:
        source_column = source_by_name.get(str(label_column.machine_key))
        if source_column is None:
            continue
        source_type = source_column_label_type(source_column.dtype)
        if source_type is None:
            raise ValueError("LABEL_SOURCE_COLUMN_TYPE_UNSUPPORTED")
        if source_type != str(label_column.value_type).lower():
            raise ValueError("LABEL_SOURCE_COLUMN_TYPE_MISMATCH")


def _snapshot_with_configuration(
    task: GenericAnnotationTask,
    data: GenericTaskConfigurationUpdate,
    previous: dict,
    configuration: dict,
    visible_columns: list[str],
) -> dict:
    scope = dict(previous.get("scope") or {})
    if not scope:
        scope = scope_descriptor(*scope_digest(
            (str(sample_id), index)
            for index, sample_id in enumerate(previous.get("sample_ids") or [])
        ))
    snapshot = {
        "dataset_version": dict(previous.get("dataset_version") or {}),
        "scope": scope,
        "visible_columns": list(visible_columns),
        "label_schema": dict(previous.get("label_schema") or task.label_snapshot or {}),
        "instructions": data.instructions,
        "completion_criteria": data.completion_criteria,
        "configuration": deepcopy(configuration),
    }
    canonical = json.dumps(snapshot, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    snapshot["config_hash"] = "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return snapshot


@router.post("/api/annotation-tasks", status_code=status.HTTP_201_CREATED)
def create_generic_annotation_task(
    data: GenericTaskCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    x_request_id: str | None = Header(default=None, alias="X-Request-ID"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    key = _request_context(request, x_request_id, idempotency_key)
    project_id = data.project_id
    require_project_access(db, project_id, current_user.id, "resource.create")
    existing = db.query(GenericAnnotationTask).filter(
        GenericAnnotationTask.idempotency_key == key,
        GenericAnnotationTask.owner_id == current_user.id,
    ).first()
    if existing is not None:
        return _serialize(db, existing)
    version = db.query(DatasetVersion).filter(
        DatasetVersion.id == data.dataset_version_id,
        DatasetVersion.project_id == project_id,
        DatasetVersion.status == "ready",
    ).one_or_none()
    if version is None:
        raise _contract_error(request, "DATASET_VERSION_NOT_FOUND", "The dataset version does not belong to this project.", status_code=404)
    source_columns = db.query(DatasetSchemaColumn).filter(
        DatasetSchemaColumn.dataset_version_id == version.id,
    ).order_by(DatasetSchemaColumn.position.asc()).all()
    try:
        visible_columns = _validated_visible_columns(source_columns, data.visible_columns)
    except ValueError as error:
        raise _contract_error(
            request,
            str(error),
            "Visible columns must be unique source dataset columns.",
            status_code=422,
        ) from error
    schema: LabelSchema
    configuration = deepcopy(data.configuration)
    if data.mode == "automatic":
        try:
            if data.model_version_id is None:
                raise StrategyConfigError("automatic tasks require an enabled model version", "MODEL_VERSION_REQUIRED")
            model_version = _annotation_model_version(db, project_id, data.model_version_id)
            contract_columns = _output_contract_columns(model_version)
            output_contract = _model_output_contract(model_version, contract_columns)
            if data.label_schema_id is not None:
                raise StrategyConfigError("automatic task labels are derived from the model output contract", "AUTOMATIC_SCHEMA_MANAGED")
            configuration = _automatic_configuration(configuration, model_version, output_contract)
            _validate_automatic_configuration(
                db,
                None,
                configuration,
                {"columns": contract_columns},
                version,
            )
            schema = create_label_schema(
                db,
                project_id=project_id,
                name=_automatic_schema_name(model_version),
                columns=contract_columns,
                commit=False,
            )
        except StrategyConfigError as error:
            raise _contract_error(request, error.code, str(error), status_code=422) from error
    else:
        if data.label_schema_id is None:
            raise _contract_error(request, "LABEL_SCHEMA_REQUIRED", "A manual task requires a label schema.", status_code=422)
        schema = db.get(LabelSchema, data.label_schema_id)
        if schema is None or schema.project_id != project_id:
            raise _contract_error(
                request,
                "LABEL_SCHEMA_NOT_FOUND",
                "The label schema does not belong to this project.",
                status_code=404,
            )
        try:
            _validate_manual_source_label_columns(schema, source_columns)
        except ValueError as error:
            raise _contract_error(
                request,
                str(error),
                "A source-backed label column must preserve its source data type.",
                status_code=422,
            ) from error
    requested_ids = (
        {str(sample_id) for sample_id in data.sample_scope.get("sample_ids", []) if str(sample_id)}
        if data.sample_scope.get("kind") == "ids" else None
    )
    samples_query = db.query(DatasetSample).filter(DatasetSample.dataset_version_id == version.id)
    if requested_ids is not None:
        samples_query = samples_query.filter(DatasetSample.sample_id.in_(requested_ids))
    matched_ids: set[str] = set()
    try:
        scope_count, scope_hash = scope_digest(_selected_scope_entries(
            samples_query,
            data.sample_scope,
            matched_ids,
        ))
    except ValueError as error:
        raise _contract_error(request, str(error), "The sample scope filter is invalid.", status_code=422) from error
    if requested_ids is not None and matched_ids != requested_ids:
        raise _contract_error(request, "SAMPLE_SCOPE_INVALID", "The sample scope contains unknown sample ids.", status_code=422)
    schema_snapshot = label_schema_snapshot(schema)
    if data.mode == "automatic":
        try:
            _validate_automatic_configuration(db, None, configuration, schema_snapshot, version)
        except StrategyConfigError as error:
            raise _contract_error(
                request,
                error.code,
                str(error),
                status_code=422,
            ) from error
    task_snapshot = {
        "dataset_version": {
            "id": str(version.id),
            "version": version.version,
            "content_hash": version.content_hash,
            "schema_hash": version.schema_hash,
            "columns": [
                {"name": column.name, "dtype": column.dtype, "nullable": column.nullable, "position": column.position}
                for column in source_columns
            ],
        },
        "scope": scope_descriptor(scope_count, scope_hash),
        "visible_columns": visible_columns,
        "label_schema": schema_snapshot,
        "instructions": data.instructions,
        "completion_criteria": data.completion_criteria,
        "configuration": configuration,
    }
    canonical = json.dumps(task_snapshot, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    task_snapshot["config_hash"] = "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    task = GenericAnnotationTask(
        project_id=project_id,
        dataset_version_id=data.dataset_version_id,
        label_schema_id=schema.id,
        owner_id=current_user.id,
        name=data.name.strip(),
        completion_criteria=data.completion_criteria,
        due_at=data.due_at,
        mode=data.mode,
        status="draft",
        sample_scope=data.sample_scope,
        label_snapshot=schema_snapshot,
        task_snapshot=task_snapshot,
        idempotency_key=key,
    )
    db.add(task)
    try:
        db.flush()
        persisted_count = persist_scope_entries(
            db,
            task.id,
            task.task_revision,
            _selected_scope_entries(samples_query, data.sample_scope),
        )
        if persisted_count != scope_count:
            raise RuntimeError("SAMPLE_SCOPE_PERSISTENCE_MISMATCH")
        bind_label_schema_to_task(db, task_id=task.id, schema=schema)
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.query(GenericAnnotationTask).filter(
            GenericAnnotationTask.idempotency_key == key,
            GenericAnnotationTask.owner_id == current_user.id,
        ).first()
        if existing is None:
            raise
        return _serialize(db, existing)
    db.refresh(task)
    return _serialize(db, task)


@router.put("/api/annotation-tasks/{task_id}/configuration")
def update_generic_annotation_task_configuration(
    task_id: uuid.UUID,
    data: GenericTaskConfigurationUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    task = db.query(GenericAnnotationTask).filter(
        GenericAnnotationTask.id == task_id,
        GenericAnnotationTask.owner_id == current_user.id,
    ).one_or_none()
    if task is None:
        raise _contract_error(request, "TASK_NOT_FOUND", "The task was not found.", status_code=404)
    if task.task_revision != data.task_revision:
        raise _contract_error(request, "TASK_REVISION_CONFLICT", "The task revision has changed.", status_code=409)
    if task.status not in {"draft", "failed", "needs_review"}:
        raise _contract_error(request, "TASK_STATE_INVALID", "The task configuration cannot be changed in its current state.", status_code=409)
    source_columns = db.query(DatasetSchemaColumn).filter(
        DatasetSchemaColumn.dataset_version_id == task.dataset_version_id,
    ).order_by(DatasetSchemaColumn.position.asc()).all()
    try:
        visible_columns = _validated_visible_columns(source_columns, data.visible_columns)
    except ValueError as error:
        raise _contract_error(
            request,
            str(error),
            "Visible columns must be unique source dataset columns.",
            status_code=422,
        ) from error
    previous = current_annotation_task_snapshot(db, task)
    configuration = deepcopy(data.configuration)
    if task.mode == "automatic":
        frozen = dict(previous.get("configuration") or {})
        protected = {key: frozen.get(key) for key in ("model_version_id", "model_artifact_id", "model_output_contract")}
        for key, value in protected.items():
            if key in configuration and configuration[key] != value:
                raise _contract_error(request, "MODEL_VERSION_IMMUTABLE", "The automatic task model version is frozen.", status_code=422)
        configuration = {**configuration, **protected}
        try:
            _validate_automatic_configuration(
                db,
                task,
                configuration,
                dict(previous.get("label_schema") or task.label_snapshot or {}),
            )
        except StrategyConfigError as error:
            raise _contract_error(request, error.code, str(error), status_code=422) from error
    snapshot = _snapshot_with_configuration(
        task,
        data,
        previous,
        configuration,
        visible_columns,
    )
    if data.name is not None:
        task.name = data.name.strip()
    task.completion_criteria = data.completion_criteria
    task.due_at = data.due_at
    task.task_revision += 1
    if task.status != "draft":
        task.status = "draft"
    copy_scope_revision(
        db,
        task,
        from_revision=data.task_revision,
        to_revision=task.task_revision,
        source_snapshot=previous,
        target_snapshot=snapshot,
    )
    db.add(AnnotationTaskRevisionSnapshot(task_id=task.id, task_revision=task.task_revision, snapshot=snapshot))
    db.add(AuditEvent(
        project_id=task.project_id,
        actor_id=current_user.id,
        actor_username=current_user.username,
        action="annotation_task.configuration_updated",
        resource_type="annotation_task",
        resource_id=str(task.id),
        result="success",
        request_id=uuid.uuid4(),
        changes={"from_revision": data.task_revision, "to_revision": task.task_revision, "config_hash": snapshot["config_hash"]},
    ))
    db.commit()
    db.refresh(task)
    payload = _serialize(db, task)
    payload["task_snapshot"] = snapshot
    return payload


@router.post("/api/projects/{project_id}/spot-weld/runs", status_code=status.HTTP_410_GONE)
def reject_legacy_spot_weld_write(
    project_id: uuid.UUID,
    request: Request,
    data: dict | None = None,
    current_user: User = Depends(get_current_user),
    x_request_id: str | None = Header(default=None, alias="X-Request-ID"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    """Close the industry-specific write path during generic migration."""
    _request_context(request, x_request_id, idempotency_key)
    request_id = str(getattr(request.state, "request_id", "")) or None
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail={
            "request_id": request_id,
            "code": "GENERIC_API_REQUIRED",
            "message": "Use /api/annotation-tasks or /api/automl-tasks.",
            "details": {},
            "legacy_route": f"/api/projects/{project_id}/spot-weld/runs",
        },
    )


@router.post("/api/annotation-tasks/{legacy_run_id}/migrate", status_code=status.HTTP_201_CREATED)
def migrate_legacy_task(
    legacy_run_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    x_request_id: str | None = Header(default=None, alias="X-Request-ID"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    _request_context(request, x_request_id, idempotency_key)
    from app.models.spot_weld_quality import SpotWeldQualityRun
    run = db.query(SpotWeldQualityRun).filter(SpotWeldQualityRun.id == legacy_run_id).first()
    if run is None:
        raise HTTPException(status_code=404, detail={"code": "LEGACY_QUALITY_RUN_NOT_FOUND", "message": "Legacy run not found"})
    if run.created_by_id != current_user.id or run.project_id is None:
        raise HTTPException(status_code=404, detail={"code": "LEGACY_QUALITY_RUN_NOT_FOUND", "message": "Legacy run not found"})
    _require_project(db, run.project_id, current_user)
    task = migrate_legacy_quality_run(db, legacy_run_id)
    return _serialize(db, task)
