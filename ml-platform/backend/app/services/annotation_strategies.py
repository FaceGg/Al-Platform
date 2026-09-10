"""Generic automatic annotation strategy evaluation."""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import asdict
from dataclasses import dataclass, field
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


def validate_strategy_config(config: AutomaticAnnotationConfig, schema: LabelSchemaContract) -> None:
    if not config.clustering:
        if config.strategy not in (None, "model"):
            raise StrategyConfigError("strategy is ignored when clustering is disabled")
        return
    if config.strategy not in {"cluster", "rule", "cluster_rule"}:
        raise StrategyConfigError("exactly one clustering strategy is required", "STRATEGY_EXCLUSIVE")
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
        for cluster_values in config.cluster_labels.values():
            _validate_values(cluster_values, schema)
    if config.strategy in {"rule", "cluster_rule"}:
        for rule in config.rules:
            if not rule.get("id") or not isinstance(rule.get("when"), Mapping) or not isinstance(rule.get("values"), Mapping):
                raise StrategyConfigError("invalid rule definition", "RULE_INVALID")
            _validate_values(rule["values"], schema)


def _validate_values(values: Mapping[str, object], schema: LabelSchemaContract) -> None:
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
    model_values = dict(model_output)
    if not config.clustering:
        try:
            _validate_values(model_values, schema)
        except StrategyConfigError:
            return AnnotationDecision({}, {}, status="needs_review", model_output=model_values, cluster_id=cluster_id)
        values = {key: model_values.get(key) for key in schema.by_key}
        return AnnotationDecision(values, {key: {"source": "model"} for key in values}, model_output=model_values, cluster_id=cluster_id)

    matched_rules, rule_ids = _matching_rules(config, frame_row) if config.strategy in {"rule", "cluster_rule"} else ([], [])
    cluster_values = config.cluster_labels.get(str(cluster_id), {}) if cluster_id is not None else {}
    values: dict[str, object] = {}
    provenance: dict[str, dict[str, object]] = {}
    needs_review = False
    for key in schema.by_key:
        candidates: list[tuple[str, object]] = []
        if config.strategy in {"rule", "cluster_rule"}:
            rule_values = [rule["values"][key] for rule in matched_rules if key in rule["values"]]
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
    feature_columns = contract.get("feature_columns") if isinstance(contract, Mapping) else None
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
            values[str(sample_id)] = {target_keys[0]: prediction.item() if hasattr(prediction, "item") else prediction}
            continue
        if not hasattr(prediction, "__len__") or len(prediction) != len(target_keys):
            raise StrategyConfigError("model output does not match frozen label schema", "MODEL_OUTPUT_INVALID")
        values[str(sample_id)] = {
            key: value.item() if hasattr(value, "item") else value
            for key, value in zip(target_keys, prediction)
        }
    return values


def _cluster_artifact_from_package(package: Mapping[str, object], rows: Mapping[str, Mapping[str, object]], seed: int):
    contract = package.get("input_contract") or {}
    feature_columns = contract.get("feature_columns") if isinstance(contract, Mapping) else None
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
    if config.clustering:
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
            except (ValueError, TypeError, KeyError):
                importance_source = "unavailable"
        if importance_source == "unavailable" or not isinstance(importance, (list, tuple)) or not importance:
            importance_source = "unavailable"
            decisions = {
                sample_id: _review_decision(
                    model_outputs.get(sample_id, {}) if isinstance(model_outputs.get(sample_id, {}), Mapping) else {},
                    "FEATURE_IMPORTANCE_UNAVAILABLE",
                )
                for sample_id in rows
            }
        else:
            if importance_source == "not_required":
                importance_source = "model"
            decisions = {
                sample_id: apply_annotation_strategy(
                    model_outputs.get(sample_id, {}) if isinstance(model_outputs.get(sample_id, {}), Mapping) else {},
                    int(cluster_ids[sample_id]) if sample_id in cluster_ids else None,
                    row,
                    config,
                    schema,
                )
                for sample_id, row in rows.items()
            }
    else:
        decisions = {
            sample_id: apply_annotation_strategy(
                model_outputs.get(sample_id, {}) if isinstance(model_outputs.get(sample_id, {}), Mapping) else {},
                None,
                row,
                config,
                schema,
            )
            for sample_id, row in rows.items()
        }

    artifact_payload = {
        "strategy": config.strategy or "model",
        "clustering": config.clustering,
        "importance_source": importance_source,
        "feature_importance": list(importance) if isinstance(importance, (list, tuple)) else [],
        "model_artifact_id": str(model_artifact_id) if model_artifact_id is not None else None,
        "cluster_artifact": cluster_artifact_payload,
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
            strategy=config.strategy or "model",
            artifact=artifact_payload,
            created_by=actor_id,
        )
        db.add(artifact)
        db.flush()
    return PreviewStrategyResult(decisions=decisions, artifact=artifact)
