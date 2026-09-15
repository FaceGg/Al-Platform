"""Generic automatic annotation strategy evaluation."""

from __future__ import annotations

from copy import deepcopy
from contextlib import nullcontext
from dataclasses import asdict
from dataclasses import dataclass, field
import math
from typing import Mapping, Sequence
import uuid

import joblib
import pandas as pd

from app.models.artifact import Artifact
from app.models.labeling import AnnotationStrategyArtifact
from app.services.label_schema import LabelColumnContract, LabelSchemaContract, validate_label_value
from app.services.rule_dsl import RuleEvaluationError, evaluate_rule
from app.services.weighted_clustering import InputContract, build_weighted_clusters


class StrategyConfigError(ValueError):
    def __init__(self, message: str, code: str = "STRATEGY_CONFIG_INVALID"):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class AutomaticAnnotationConfig:
    clustering: bool = False
    strategy: str | None = None
    cluster_labels: Mapping[str, Mapping[str, object]] = field(default_factory=dict)
    rules: Sequence[Mapping[str, object]] = field(default_factory=tuple)
    other_values: Mapping[str, object] = field(default_factory=dict)
    selected_clusters: Sequence[str] | None = None
    cluster_discovery: bool = False


@dataclass(frozen=True)
class AnnotationDecision:
    values: dict[str, object]
    provenance: dict[str, dict[str, object]]
    status: str = "ready"
    model_output: dict[str, object] = field(default_factory=dict)
    cluster_id: int | None = None
    matched_rule_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class PreviewStrategyResult:
    decisions: dict[str, AnnotationDecision]
    artifact: AnnotationStrategyArtifact


_RULE_OPERATORS = {"eq", "==", "neq", "!=", "ne", "gt", ">", "gte", ">=", "lt", "<", "lte", "<=", "in", "not_in", "is_null", "not_null"}
_NUMERIC_RULE_OPERATORS = {"gt", ">", "gte", ">=", "lt", "<", "lte", "<="}


def _rule_source_value_type(dtype: object) -> str:
    normalized = str(dtype or "").strip().lower()
    if "int" in normalized or "uint" in normalized:
        return "int"
    if any(token in normalized for token in ("float", "double", "decimal", "number")):
        return "float"
    if normalized in {"bool", "boolean"}:
        return "boolean"
    return "string"


def _validate_rule_expected_value(operator: str, expected: object, value_type: str) -> None:
    if operator in {"is_null", "not_null"}:
        if expected not in (None, True):
            raise StrategyConfigError("null operators require a null marker", "RULE_VALUE_TYPE_INVALID")
        return
    if operator in _NUMERIC_RULE_OPERATORS and value_type not in {"int", "float"}:
        raise StrategyConfigError("numeric comparison requires a numeric source column", "RULE_VALUE_TYPE_INVALID")
    values = expected if operator in {"in", "not_in"} else [expected]
    if operator in {"in", "not_in"} and (not isinstance(values, (list, tuple, set, frozenset)) or not values):
        raise StrategyConfigError("membership comparison requires a non-empty list", "RULE_VALUE_TYPE_INVALID")
    for value in values:
        if value_type == "string":
            if not isinstance(value, str):
                raise StrategyConfigError("string source column requires a string rule value", "RULE_VALUE_TYPE_INVALID")
        elif value_type == "boolean":
            if not isinstance(value, bool):
                raise StrategyConfigError("boolean source column requires a boolean rule value", "RULE_VALUE_TYPE_INVALID")
        elif value_type == "int":
            if isinstance(value, bool) or not isinstance(value, int):
                raise StrategyConfigError("integer source column requires an integer rule value", "RULE_VALUE_TYPE_INVALID")
        elif value_type == "float":
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                raise StrategyConfigError("numeric source column requires a finite numeric rule value", "RULE_VALUE_TYPE_INVALID")


def _validate_rule_expression(expression: Mapping[str, object], source_column_types: Mapping[str, object] | None) -> None:
    if not isinstance(expression, Mapping) or not expression:
        raise StrategyConfigError("rule condition must be an object", "RULE_INVALID")
    grouped = [key for key in ("all", "any", "not") if key in expression]
    if grouped:
        if len(expression) != 1:
            raise StrategyConfigError("rule group cannot mix with field conditions", "RULE_INVALID")
        key = grouped[0]
        nested = expression[key]
        if key == "not":
            if not isinstance(nested, Mapping):
                raise StrategyConfigError("not requires one rule condition", "RULE_INVALID")
            _validate_rule_expression(nested, source_column_types)
            return
        if not isinstance(nested, (list, tuple)) or not nested:
            raise StrategyConfigError(f"{key} requires a non-empty condition list", "RULE_INVALID")
        for item in nested:
            if not isinstance(item, Mapping):
                raise StrategyConfigError("rule condition must be an object", "RULE_INVALID")
            _validate_rule_expression(item, source_column_types)
        return
    for column, raw_condition in expression.items():
        if not isinstance(column, str) or not column:
            raise StrategyConfigError("rule source column is invalid", "RULE_INVALID")
        if source_column_types is not None and column not in source_column_types:
            raise StrategyConfigError("rule source column is not present in the frozen dataset version", "RULE_SOURCE_COLUMN_UNKNOWN")
        condition = raw_condition if isinstance(raw_condition, Mapping) else {"eq": raw_condition}
        if not condition:
            raise StrategyConfigError("rule condition is empty", "RULE_INVALID")
        value_type = _rule_source_value_type(source_column_types[column]) if source_column_types is not None else None
        for operator, expected in condition.items():
            if str(operator) not in _RULE_OPERATORS:
                raise StrategyConfigError("rule operator is unsupported", "RULE_OPERATOR_INVALID")
            if value_type is not None:
                _validate_rule_expected_value(str(operator), expected, value_type)


def validate_strategy_config(
    config: AutomaticAnnotationConfig,
    schema: LabelSchemaContract,
    *,
    source_column_types: Mapping[str, object] | None = None,
) -> None:
    if not config.clustering:
        if config.cluster_discovery:
            raise StrategyConfigError("cluster discovery requires clustering", "STRATEGY_CONFIG_INVALID")
        if config.strategy not in (None, "model"):
            raise StrategyConfigError("strategy is ignored when clustering is disabled")
        return
    if config.cluster_discovery:
        if config.strategy is not None or config.cluster_labels or config.rules or config.other_values or config.selected_clusters is not None:
            raise StrategyConfigError("cluster discovery must run before strategy configuration", "CLUSTER_DISCOVERY_CONFIG_INVALID")
        return
    if config.strategy not in {"cluster", "rule", "cluster_rule"}:
        raise StrategyConfigError("exactly one clustering strategy is required", "STRATEGY_EXCLUSIVE")
    if not isinstance(config.cluster_labels, Mapping):
        raise StrategyConfigError("cluster labels must be an object", "STRATEGY_CONFIG_INVALID")
    if not isinstance(config.other_values, Mapping):
        raise StrategyConfigError("other fallback must be an object", "CLUSTER_FALLBACK_REQUIRED")
    if not isinstance(config.rules, (list, tuple)):
        raise StrategyConfigError("rules must be a list", "RULE_INVALID")
    if config.selected_clusters is not None and (not isinstance(config.selected_clusters, (list, tuple)) or any(isinstance(value, bool) or not isinstance(value, (str, int)) for value in config.selected_clusters)):
        raise StrategyConfigError("selected clusters must be a list of cluster identifiers")
    missing = [key for key in schema.by_key if key not in config.other_values]
    if missing:
        raise StrategyConfigError("other fallback is required for every label column", "CLUSTER_FALLBACK_REQUIRED")
    for key, value in config.other_values.items():
        if key not in schema.by_key:
            raise StrategyConfigError("unknown fallback label column", "LABEL_COLUMN_UNKNOWN")
        try:
            validate_label_value(schema.by_key[key], value)
        except ValueError as error:
            raise StrategyConfigError(str(error), "LABEL_VALUE_INVALID") from error
    if config.strategy in {"cluster", "cluster_rule"}:
        selected = {str(value) for value in config.selected_clusters or ()}
        if not selected:
            raise StrategyConfigError("at least one cluster must be selected", "CLUSTER_SELECTION_REQUIRED")
        for cluster_id, cluster_values in config.cluster_labels.items():
            if not isinstance(cluster_values, Mapping):
                raise StrategyConfigError("cluster label mapping must be an object", "CLUSTER_MAPPING_REQUIRED")
            _validate_values(cluster_values, schema)
            if str(cluster_id) in selected:
                missing_cluster_values = [key for key in schema.by_key if key not in cluster_values]
                if missing_cluster_values:
                    raise StrategyConfigError("selected cluster requires every label value", "CLUSTER_MAPPING_REQUIRED")
    if config.strategy in {"rule", "cluster_rule"}:
        for rule in config.rules:
            if not isinstance(rule, Mapping):
                raise StrategyConfigError("invalid rule definition", "RULE_INVALID")
            if type(rule.get("priority", 0)) is not int:
                raise StrategyConfigError("rule priority must be an integer", "RULE_INVALID")
            if rule.get("cluster_ids") is not None and (not isinstance(rule["cluster_ids"], (list, tuple)) or any(isinstance(value, bool) or not isinstance(value, (str, int)) for value in rule["cluster_ids"])):
                raise StrategyConfigError("rule cluster filter must be a list", "RULE_INVALID")
            if not rule.get("id") or not isinstance(rule.get("when"), Mapping) or not isinstance(rule.get("values"), Mapping):
                raise StrategyConfigError("invalid rule definition", "RULE_INVALID")
            _validate_rule_expression(rule["when"], source_column_types)
            _validate_values(rule["values"], schema)


def _validate_values(values: Mapping[str, object], schema: LabelSchemaContract) -> None:
    if not isinstance(values, Mapping):
        raise StrategyConfigError("label values must be an object", "LABEL_VALUE_INVALID")
    for key, value in values.items():
        if key not in schema.by_key:
            raise StrategyConfigError("unknown label column", "LABEL_COLUMN_UNKNOWN")
        try:
            validate_label_value(schema.by_key[key], value)
        except ValueError as error:
            raise StrategyConfigError(str(error), "LABEL_VALUE_INVALID") from error


def _matching_rules(config: AutomaticAnnotationConfig, row: Mapping[str, object]) -> tuple[list[Mapping[str, object]], list[str]]:
    matches: list[Mapping[str, object]] = []
    ids: list[str] = []
    for rule in config.rules:
        try:
            matched = evaluate_rule(rule["when"], row)
        except RuleEvaluationError as error:
            raise StrategyConfigError(str(error), "RULE_INVALID") from error
        if matched:
            matches.append(rule)
            ids.append(str(rule["id"]))
    return matches, ids


def apply_annotation_strategy(
    model_output: Mapping[str, object],
    cluster_id: int | None,
    frame_row: Mapping[str, object],
    config: AutomaticAnnotationConfig,
    schema: LabelSchemaContract | None = None,
) -> AnnotationDecision:
    if schema is None:
        raise StrategyConfigError("label schema is required", "LABEL_SCHEMA_REQUIRED")
    validate_strategy_config(config, schema)
    if config.cluster_discovery:
        raise StrategyConfigError("cluster discovery does not produce final labels", "CLUSTER_DISCOVERY_INCOMPLETE")
    if not isinstance(model_output, Mapping):
        raise StrategyConfigError("model output must be an object", "MODEL_OUTPUT_INVALID")
    model_values = dict(model_output)
    expected_keys = set(schema.by_key)
    if set(model_values) != expected_keys:
        raise StrategyConfigError("model output does not match frozen label schema", "MODEL_OUTPUT_INVALID")
    try:
        model_values = {
            key: validate_label_value(schema.by_key[key], model_values[key])
            for key in schema.by_key
        }
    except ValueError as error:
        raise StrategyConfigError("model output violates frozen label schema", "MODEL_OUTPUT_INVALID") from error
    if not config.clustering:
        values = {key: model_values.get(key) for key in schema.by_key}
        return AnnotationDecision(values, {key: {"source": "model"} for key in values}, model_output=model_values, cluster_id=cluster_id)

    selected = config.selected_clusters is None or str(cluster_id) in {str(value) for value in config.selected_clusters}
    matched_rules, rule_ids = _matching_rules(config, frame_row) if config.strategy in {"rule", "cluster_rule"} and (config.strategy == "rule" or selected) else ([], [])
    matched_rules = [rule for rule in matched_rules if rule.get("cluster_ids") is None or str(cluster_id) in {str(value) for value in rule["cluster_ids"]}]
    rule_ids = [str(rule["id"]) for rule in matched_rules]
    cluster_values = config.cluster_labels.get(str(cluster_id), {}) if cluster_id is not None else {}
    if not selected:
        cluster_values = {}
    values: dict[str, object] = {}
    provenance: dict[str, dict[str, object]] = {}
    needs_review = False
    for key in schema.by_key:
        candidates: list[tuple[str, object]] = []
        if config.strategy in {"rule", "cluster_rule"}:
            column_rules = [rule for rule in matched_rules if key in rule["values"]]
            highest_priority = min((rule.get("priority", 0) for rule in column_rules), default=0)
            rule_values = [rule["values"][key] for rule in column_rules if rule.get("priority", 0) == highest_priority]
            if rule_values:
                if len(set(map(repr, rule_values))) > 1:
                    needs_review = True
                    values[key] = None
                    provenance[key] = {"source": "rule", "rule_ids": rule_ids, "conflict": True}
                    continue
                candidates.append(("rule", rule_values[0]))
        if config.strategy in {"cluster", "cluster_rule"} and key in cluster_values:
            candidates.append(("cluster", cluster_values[key]))
        if not candidates:
            candidates.append(("other", config.other_values[key]))
        source, value = candidates[0]
        try:
            values[key] = validate_label_value(schema.by_key[key], value)
        except ValueError:
            needs_review = True
            values[key] = None
        provenance[key] = {"source": source}
    return AnnotationDecision(values, provenance, status="needs_review" if needs_review else "ready", model_output=model_values, cluster_id=cluster_id, matched_rule_ids=tuple(rule_ids))


def label_schema_contract_from_snapshot(snapshot: Mapping[str, object]) -> LabelSchemaContract:
    columns = snapshot.get("columns", [])
    if not isinstance(columns, list) or not columns:
        raise StrategyConfigError("frozen label schema is required", "LABEL_SCHEMA_REQUIRED")
    return LabelSchemaContract([
        LabelColumnContract(
            machine_key=str(column["machine_key"]),
            value_type=str(column.get("value_type", "string")),
            required=bool(column.get("required", False)),
            enum_values=tuple(column.get("enum_values") or ()),
            min_value=column.get("min_value"),
            max_value=column.get("max_value"),
            max_length=column.get("max_length"),
        )
        for column in columns
        if isinstance(column, Mapping) and column.get("machine_key")
    ])


def _config_from_snapshot(configuration: Mapping[str, object]) -> AutomaticAnnotationConfig:
    return AutomaticAnnotationConfig(
        clustering=bool(configuration.get("clustering", False)),
        strategy=configuration.get("strategy") if configuration.get("strategy") != "model" else None,
        cluster_labels=configuration.get("cluster_labels") or {},
        rules=configuration.get("rules") or (),
        other_values=configuration.get("other_values") or {},
        selected_clusters=configuration.get("selected_clusters"),
        cluster_discovery=bool(configuration.get("cluster_discovery", False)),
    )


def _review_decision(model_output: Mapping[str, object], reason: str) -> AnnotationDecision:
    return AnnotationDecision(
        values={},
        provenance={},
        status="needs_review",
        model_output=dict(model_output),
        matched_rule_ids=(),
    )


def _artifact_model_package(db, project_id, artifact_id):
    try:
        artifact_uuid = artifact_id if isinstance(artifact_id, uuid.UUID) else uuid.UUID(str(artifact_id))
    except (TypeError, ValueError, AttributeError) as error:
        raise StrategyConfigError("model artifact id is invalid", "MODEL_ARTIFACT_INVALID") from error
    artifact = db.query(Artifact).filter_by(id=artifact_uuid, project_id=project_id, type="model").one_or_none()
    if artifact is None:
        raise StrategyConfigError("model artifact is not available in this project", "MODEL_ARTIFACT_NOT_FOUND")
    if artifact.storage_uri:
        from app.services.artifact_service import build_artifact_service
        materialized = build_artifact_service(db).materialize(artifact.id, project_id, "model")
    else:
        from pathlib import Path
        path = Path(artifact.storage_path or "")
        if not path.is_file():
            raise StrategyConfigError("model artifact content is unavailable", "MODEL_ARTIFACT_UNAVAILABLE")
        materialized = nullcontext(path)
    with materialized as path:
        package = joblib.load(path)
    if not isinstance(package, Mapping) or package.get("model") is None:
        raise StrategyConfigError("model artifact package is invalid", "MODEL_ARTIFACT_INVALID")
    return package


def _model_outputs_from_package(package: Mapping[str, object], rows: Mapping[str, Mapping[str, object]], schema: LabelSchemaContract) -> dict[str, dict[str, object]]:
    contract = package.get("input_contract") or {}
    feature_columns = (
        contract.get("feature_columns") or contract.get("input_columns")
        if isinstance(contract, Mapping) else None
    )
    if not isinstance(feature_columns, (list, tuple)) or not feature_columns:
        raise StrategyConfigError("model artifact input contract is invalid", "MODEL_CONTRACT_INVALID")
    frame = pd.DataFrame.from_dict(rows, orient="index")
    missing = [column for column in feature_columns if column not in frame.columns]
    if missing:
        raise StrategyConfigError("preview rows do not satisfy model input contract", "MODEL_INPUT_MISSING")
    predictions = package["model"].predict(frame.loc[:, list(feature_columns)])
    target_keys = tuple(schema.by_key)
    values: dict[str, dict[str, object]] = {}
    for sample_id, prediction in zip(frame.index, predictions):
        if len(target_keys) == 1:
            candidate = {target_keys[0]: prediction.item() if hasattr(prediction, "item") else prediction}
            values[str(sample_id)] = _validated_model_output(candidate, schema)
            continue
        if not hasattr(prediction, "__len__") or len(prediction) != len(target_keys):
            raise StrategyConfigError("model output does not match frozen label schema", "MODEL_OUTPUT_INVALID")
        candidate = {
            key: value.item() if hasattr(value, "item") else value
            for key, value in zip(target_keys, prediction)
        }
        values[str(sample_id)] = _validated_model_output(candidate, schema)
    return values


def _cluster_artifact_from_package(package: Mapping[str, object], rows: Mapping[str, Mapping[str, object]], seed: int):
    contract = package.get("input_contract") or {}
    feature_columns = (
        contract.get("feature_columns") or contract.get("input_columns")
        if isinstance(contract, Mapping) else None
    )
    if not isinstance(feature_columns, (list, tuple)) or not feature_columns:
        raise StrategyConfigError("model artifact input contract is invalid", "MODEL_CONTRACT_INVALID")
    frame = pd.DataFrame.from_dict(rows, orient="index")
    artifact = build_weighted_clusters(
        frame,
        package["model"],
        InputContract(feature_columns=tuple(str(column) for column in feature_columns)),
        seed=seed,
    )
    payload = asdict(artifact)
    payload["assignments"] = {str(sample_id): int(label) for sample_id, label in zip(frame.index, artifact.labels)}
    return artifact, payload


def _frozen_discovery_artifact(db, task_id) -> tuple[dict[str, object], dict[str, object]] | None:
    artifacts = db.query(AnnotationStrategyArtifact).filter(
        AnnotationStrategyArtifact.task_id == task_id,
    ).order_by(
        AnnotationStrategyArtifact.task_revision.desc(),
        AnnotationStrategyArtifact.created_at.desc(),
    ).all()
    for artifact in artifacts:
        payload = dict(artifact.artifact or {})
        cluster_artifact = payload.get("cluster_artifact")
        assignments = cluster_artifact.get("assignments") if isinstance(cluster_artifact, Mapping) else None
        if payload.get("configuration_complete") is False and isinstance(assignments, Mapping) and assignments:
            return payload, deepcopy(dict(cluster_artifact))
    return None


def _validated_model_output(values: Mapping[str, object], schema: LabelSchemaContract) -> dict[str, object]:
    if set(values) != set(schema.by_key):
        raise StrategyConfigError("model output does not match frozen label schema", "MODEL_OUTPUT_INVALID")
    try:
        return {
            key: validate_label_value(schema.by_key[key], values[key])
            for key in schema.by_key
        }
    except ValueError as error:
        raise StrategyConfigError("model output violates frozen label schema", "MODEL_OUTPUT_INVALID") from error


def _validated_model_outputs(
    model_outputs: Mapping[str, object],
    rows: Mapping[str, Mapping[str, object]],
    schema: LabelSchemaContract,
) -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {}
    for sample_id in rows:
        values = model_outputs.get(sample_id)
        if not isinstance(values, Mapping):
            raise StrategyConfigError("model output is missing for a preview sample", "MODEL_OUTPUT_INVALID")
        result[sample_id] = _validated_model_output(values, schema)
    return result


def apply_preview_annotation_strategy(
    db,
    *,
    task_id,
    task_revision: int,
    config_hash: str,
    actor_id,
    project_id=None,
    schema_snapshot: Mapping[str, object],
    configuration: Mapping[str, object],
    rows: Mapping[str, Mapping[str, object]],
) -> PreviewStrategyResult:
    """Evaluate a frozen automatic strategy and persist its immutable metadata.

    The caller supplies only frozen snapshot data. A clustering configuration
    without a verified importance vector is intentionally closed as
    ``needs_review``; it never substitutes equal weights.
    """
    schema = label_schema_contract_from_snapshot(schema_snapshot)
    config = _config_from_snapshot(configuration)
    validate_strategy_config(config, schema)
    model_outputs = configuration.get("model_outputs") or {}
    if not isinstance(model_outputs, Mapping):
        raise StrategyConfigError("model outputs must be an object", "MODEL_OUTPUT_INVALID")

    importance = configuration.get("feature_importance")
    importance_source = "not_required"
    cluster_ids: Mapping[str, int] = configuration.get("cluster_ids") or {}
    cluster_artifact_payload = None
    package = None
    model_artifact_id = configuration.get("model_artifact_id")
    if model_artifact_id is not None:
        if project_id is None:
            raise StrategyConfigError("project context is required for a model artifact", "MODEL_ARTIFACT_CONTEXT_REQUIRED")
        package = _artifact_model_package(db, project_id, model_artifact_id)
        if not model_outputs:
            model_outputs = _model_outputs_from_package(package, rows, schema)
    model_outputs = _validated_model_outputs(model_outputs, rows, schema)
    if config.clustering:
        if config.cluster_discovery:
            if package is not None:
                try:
                    cluster_artifact, cluster_artifact_payload = _cluster_artifact_from_package(
                        package,
                        rows,
                        int(configuration.get("random_seed", 42)),
                    )
                    importance = list(cluster_artifact.weights.values())
                    cluster_ids = cluster_artifact_payload["assignments"]
                    importance_source = "model_artifact"
                except StrategyConfigError:
                    raise
                except (ValueError, TypeError, KeyError) as error:
                    code = str(error).split(":", 1)[0]
                    raise StrategyConfigError(
                        "weighted clustering cannot complete for this task range",
                        code if code.startswith(("CLUSTER_", "FEATURE_IMPORTANCE_")) else "CLUSTERING_FAILED",
                    ) from error
            elif isinstance(cluster_ids, Mapping) and cluster_ids:
                cluster_artifact_payload = {"assignments": {str(key): int(value) for key, value in cluster_ids.items()}}
            if importance_source == "unavailable" or not isinstance(importance, (list, tuple)) or not importance:
                raise StrategyConfigError(
                    "weighted clustering requires a valid model feature-importance vector",
                    "FEATURE_IMPORTANCE_UNAVAILABLE",
                )
            if importance_source == "not_required":
                importance_source = "model"
            missing_assignments = [sample_id for sample_id in rows if sample_id not in cluster_ids]
            if missing_assignments:
                raise StrategyConfigError("cluster discovery did not assign every preview sample", "CLUSTERING_FAILED")
            decisions = {
                sample_id: AnnotationDecision(
                    values={},
                    provenance={},
                    status="pending_configuration",
                    model_output=model_outputs[sample_id],
                    cluster_id=int(cluster_ids[sample_id]),
                )
                for sample_id in rows
            }
        else:
            frozen = _frozen_discovery_artifact(db, task_id)
            if frozen is None:
                raise StrategyConfigError("run a cluster discovery preview before generating final labels", "CLUSTER_DISCOVERY_REQUIRED")
            discovery_payload, cluster_artifact_payload = frozen
            assignments = cluster_artifact_payload.get("assignments")
            if not isinstance(assignments, Mapping):
                raise StrategyConfigError("cluster discovery artifact is invalid", "CLUSTER_DISCOVERY_REQUIRED")
            cluster_ids = {str(sample_id): int(cluster_id) for sample_id, cluster_id in assignments.items()}
            missing_assignments = [sample_id for sample_id in rows if sample_id not in cluster_ids]
            if missing_assignments:
                raise StrategyConfigError("cluster discovery artifact does not match the frozen sample scope", "CLUSTER_DISCOVERY_REQUIRED")
            importance = discovery_payload.get("feature_importance")
            importance_source = str(discovery_payload.get("importance_source") or "frozen_discovery")
            if not isinstance(importance, (list, tuple)) or not importance:
                raise StrategyConfigError("cluster discovery artifact has no valid feature importance", "FEATURE_IMPORTANCE_UNAVAILABLE")
            decisions = {
                sample_id: apply_annotation_strategy(
                    model_outputs[sample_id],
                    cluster_ids[sample_id],
                    row,
                    config,
                    schema,
                )
                for sample_id, row in rows.items()
            }
    else:
        decisions = {
            sample_id: apply_annotation_strategy(
                model_outputs[sample_id],
                None,
                row,
                config,
                schema,
            )
            for sample_id, row in rows.items()
        }

    cluster_counts: dict[str, int] = {}
    for decision in decisions.values():
        if decision.cluster_id is not None:
            key = str(decision.cluster_id)
            cluster_counts[key] = cluster_counts.get(key, 0) + 1
    artifact_payload = {
        "strategy": "cluster_discovery" if config.cluster_discovery else config.strategy or "model",
        "clustering": config.clustering,
        "importance_source": importance_source,
        "feature_importance": list(importance) if isinstance(importance, (list, tuple)) else [],
        "model_artifact_id": str(model_artifact_id) if model_artifact_id is not None else None,
        "model_version_id": configuration.get("model_version_id"),
        "model_output_contract_hash": (configuration.get("model_output_contract") or {}).get("contract_hash") if isinstance(configuration.get("model_output_contract"), Mapping) else None,
        "cluster_artifact": cluster_artifact_payload,
        "clusters": [
            {"cluster_id": int(cluster_id) if cluster_id.lstrip("-").isdigit() else cluster_id, "sample_count": cluster_counts[cluster_id]}
            for cluster_id in sorted(cluster_counts, key=lambda value: (not value.lstrip("-").isdigit(), value))
        ],
        "configuration_complete": not config.cluster_discovery,
        "review_count": sum(decision.status == "needs_review" for decision in decisions.values()),
        "sample_count": len(decisions),
    }
    artifact = db.query(AnnotationStrategyArtifact).filter_by(
        task_id=task_id,
        task_revision=task_revision,
        config_hash=config_hash,
    ).one_or_none()
    if artifact is None:
        artifact = AnnotationStrategyArtifact(
            task_id=task_id,
            task_revision=task_revision,
            config_hash=config_hash,
            strategy="cluster_discovery" if config.cluster_discovery else config.strategy or "model",
            artifact=artifact_payload,
            created_by=actor_id,
        )
        db.add(artifact)
        db.flush()
    return PreviewStrategyResult(decisions=decisions, artifact=artifact)
