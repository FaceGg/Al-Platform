"""Report-compatible quality validation, AutoML, clustering and rules."""

from __future__ import annotations

import base64
from collections import Counter
from dataclasses import dataclass, field
import json
from io import BytesIO
from pathlib import Path
import tempfile
import time
import uuid
from typing import Any, Callable, Iterable, Mapping, Sequence

import joblib
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from sklearn.metrics import accuracy_score, classification_report, f1_score, roc_auc_score, silhouette_score
from sklearn.model_selection import StratifiedKFold, train_test_split
from sklearn.preprocessing import StandardScaler

from app.models.model_library import ModelLibrary
from app.models.spot_weld_quality import (
    SpotWeldLabelRevision,
    SpotWeldLabelSnapshot,
    SpotWeldQualityRuleSet,
    SpotWeldQualityRun,
    SpotWeldQualitySample,
)
from app.services.artifact_service import ArtifactAccessError, ArtifactService, build_artifact_service
from app.services.automl_catalog import get_algorithm_family, resolve_algorithm_families
from app.services.automl_search import FamilySearchResult, SEARCH_METHODS, SearchConfig, run_family_search
from app.services.spot_weld_features import (
    FEATURE_SCHEMA,
    QualityPipelineError,
    REPORT_TABLE_FIELDS,
    TABLE_FEATURES,
    WAVEFORM_FIELDS,
    build_feature_frame,
    canonicalize_report_frame,
    decode_report_waveforms,
)


REPORT_RULE_ENERGY_SIGMA = 2.5
REPORT_RULE_SPATTER_CLUSTER_ID = 1
REPORT_RULESET_VERSION = "report_v2"
QUALITY_LABEL_MODES = frozenset({"automatic", "manual"})
LOCAL_QUALITY_TASK_PREFIX = "local:"
LOCAL_QUALITY_RECOVERABLE_STATUSES = ("queued", "validating", "running")
LOCAL_QUALITY_WORKER_RESTARTED_CODE = "QUALITY_RUN_LOCAL_WORKER_RESTARTED"
DEFAULT_REPORT_RULE_CONFIG: dict[str, float | int] = {
    "strong_splatter_min": 3,
    "weak_splatter_value": 2,
    "spotdiameter_small_min": 0,
    "spotdiameter_small_max": 2,
    "spotdiameter_large_min": 80,
    "energy_dev_sigma": REPORT_RULE_ENERGY_SIGMA,
    "current_max_diff_percentile": 95,
    "power_std_percentile": 95,
    "spatter_cluster_id": REPORT_RULE_SPATTER_CLUSTER_ID,
    "spatter_cluster_min_strength": 2,
}


def normalize_report_rule_config(rule_config: Mapping[str, Any] | None = None) -> dict[str, float | int]:
    """Validate the editable annotation rules before they enter a run record."""
    if rule_config is not None and not isinstance(rule_config, Mapping):
        raise QualityPipelineError("QUALITY_RULE_CONFIG_INVALID")
    supplied = dict(rule_config or {})
    if set(supplied) - set(DEFAULT_REPORT_RULE_CONFIG):
        raise QualityPipelineError("QUALITY_RULE_CONFIG_INVALID")

    normalized = dict(DEFAULT_REPORT_RULE_CONFIG)
    integer_keys = {
        "strong_splatter_min",
        "weak_splatter_value",
        "spatter_cluster_id",
        "spatter_cluster_min_strength",
    }
    for key, raw_value in supplied.items():
        if isinstance(raw_value, bool):
            raise QualityPipelineError("QUALITY_RULE_CONFIG_INVALID")
        try:
            value = float(raw_value)
        except (TypeError, ValueError) as error:
            raise QualityPipelineError("QUALITY_RULE_CONFIG_INVALID") from error
        if not np.isfinite(value):
            raise QualityPipelineError("QUALITY_RULE_CONFIG_INVALID")
        if key in integer_keys:
            if not value.is_integer():
                raise QualityPipelineError("QUALITY_RULE_CONFIG_INVALID")
            normalized[key] = int(value)
        else:
            normalized[key] = value

    if (
        normalized["strong_splatter_min"] < 0
        or normalized["weak_splatter_value"] < 0
        or normalized["spatter_cluster_id"] < 0
        or normalized["spatter_cluster_min_strength"] < 0
        or normalized["spotdiameter_small_min"] < 0
        or normalized["spotdiameter_small_min"] >= normalized["spotdiameter_small_max"]
        or normalized["spotdiameter_large_min"] <= normalized["spotdiameter_small_max"]
        or normalized["energy_dev_sigma"] <= 0
        or not 0 < normalized["current_max_diff_percentile"] <= 100
        or not 0 < normalized["power_std_percentile"] <= 100
    ):
        raise QualityPipelineError("QUALITY_RULE_CONFIG_INVALID")
    return normalized


def build_runtime_rule_thresholds(
    features: pd.DataFrame,
    rule_config: Mapping[str, Any] | None = None,
) -> dict[str, float | int]:
    """Persist both editable rule values and the run-scoped percentile cutoffs."""
    normalized = normalize_report_rule_config(rule_config)
    return {
        **normalized,
        "current_max_diff_p95": float(np.percentile(
            features["current_max_diff"],
            float(normalized["current_max_diff_percentile"]),
        )),
        "power_std_p95": float(np.percentile(
            features["power_std"],
            float(normalized["power_std_percentile"]),
        )),
    }


QUALITY_CROSS_VALIDATION_FOLDS = frozenset({3, 4, 5})


def normalize_quality_search_config(
    algorithm_ids: Sequence[str] | None = None,
    search_method: str = "bayesian",
    max_trials: int = 20,
    time_budget: int = 600,
) -> dict[str, Any]:
    if (
        search_method not in SEARCH_METHODS
        or isinstance(max_trials, bool)
        or not 5 <= int(max_trials) <= 200
        or isinstance(time_budget, bool)
        or not 60 <= int(time_budget) <= 3600
    ):
        raise QualityPipelineError("QUALITY_AUTOML_SEARCH_CONFIG_INVALID")
    try:
        families = resolve_algorithm_families(list(algorithm_ids or []))
    except ValueError as error:
        raise QualityPipelineError("QUALITY_AUTOML_SEARCH_CONFIG_INVALID") from error
    return {
        "search_contract": "optuna_v1",
        "algorithm_ids": [family.id for family in families],
        "search_method": search_method,
        "max_trials": int(max_trials),
        "time_budget": int(time_budget),
    }


def normalize_quality_evaluation_config(
    cross_validation_enabled: bool = True,
    cross_validation_folds: int | None = 3,
) -> dict[str, bool | int | None]:
    if not isinstance(cross_validation_enabled, bool):
        raise QualityPipelineError("QUALITY_EVALUATION_CONFIG_INVALID")
    if not cross_validation_enabled:
        return {
            "cross_validation_enabled": False,
            "cross_validation_folds": None,
        }
    if (
        isinstance(cross_validation_folds, bool)
        or cross_validation_folds not in QUALITY_CROSS_VALIDATION_FOLDS
    ):
        raise QualityPipelineError("QUALITY_EVALUATION_CONFIG_INVALID")
    return {
        "cross_validation_enabled": True,
        "cross_validation_folds": int(cross_validation_folds),
    }


def _quality_required_input_columns(field_mapping: Mapping[str, str] | None = None) -> list[str]:
    mapping = {name: name for name in (*REPORT_TABLE_FIELDS, *WAVEFORM_FIELDS)}
    if field_mapping:
        mapping.update({str(name): str(source) for name, source in field_mapping.items()})
    return [mapping[name] for name in (*REPORT_TABLE_FIELDS, *WAVEFORM_FIELDS)]


def _resolve_quality_input_schema(
    frame: pd.DataFrame,
    *,
    field_mapping: Mapping[str, str] | None,
    target_column: str | None,
    input_columns: Sequence[str] | None,
) -> tuple[list[str], list[dict[str, str]]]:
    frame_columns = [str(column) for column in frame.columns]
    if input_columns is None:
        selected = [column for column in frame_columns if column != target_column]
    else:
        if isinstance(input_columns, (str, bytes)):
            raise QualityPipelineError("QUALITY_INPUT_COLUMNS_INVALID")
        selected = [str(column) for column in input_columns]
        if not selected or len(selected) != len(set(selected)):
            raise QualityPipelineError("QUALITY_INPUT_COLUMNS_INVALID")
        if target_column is not None and target_column in selected:
            raise QualityPipelineError(
                "QUALITY_INPUT_COLUMNS_INVALID",
                message=f"点焊质量感知目标列不能同时作为输入列：{target_column}",
            )
        unknown_columns = [column for column in selected if column not in frame_columns]
        if unknown_columns:
            raise QualityPipelineError(
                "QUALITY_INPUT_COLUMNS_INVALID",
                message=f"点焊质量感知输入列不存在：{', '.join(unknown_columns)}",
            )
        required = _quality_required_input_columns(field_mapping)
        missing_columns = [column for column in required if column not in selected]
        if missing_columns:
            raise QualityPipelineError(
                "QUALITY_INPUT_COLUMNS_INVALID",
                message=f"点焊质量感知输入列缺少必需字段：{', '.join(missing_columns)}",
            )
    if not selected:
        raise QualityPipelineError("QUALITY_INPUT_COLUMNS_INVALID")
    return selected, [
        {"name": column, "dtype": str(frame[column].dtype)}
        for column in selected
    ]


def _resolve_quality_target_schema(
    frame: pd.DataFrame,
    target_column: str | None,
    evaluation: Mapping[str, Any],
) -> tuple[np.ndarray | None, dict[str, Any] | None]:
    if target_column is None:
        return None, None
    if not isinstance(target_column, str) or target_column not in frame.columns:
        raise QualityPipelineError("QUALITY_TARGET_COLUMN_INVALID", field_name=str(target_column or ""))
    raw_labels = frame[target_column]
    if raw_labels.isna().any():
        raise QualityPipelineError("QUALITY_TARGET_COLUMN_INVALID", field_name=target_column)
    labels = raw_labels.astype(str).str.strip().to_numpy(dtype=str)
    if not len(labels) or not np.all(labels):
        raise QualityPipelineError("QUALITY_TARGET_COLUMN_INVALID", field_name=target_column)
    classes, encoded = np.unique(labels, return_inverse=True)
    counts = np.bincount(encoded)
    if len(classes) < 2:
        raise QualityPipelineError("QUALITY_TARGET_COLUMN_INVALID", field_name=target_column)
    minimum_count = (
        int(evaluation["cross_validation_folds"])
        if evaluation["cross_validation_enabled"]
        else 2
    )
    if int(counts.min()) < minimum_count:
        raise QualityPipelineError("QUALITY_TARGET_COLUMN_INVALID", field_name=target_column)
    return labels, {
        "name": target_column,
        "dtype": str(raw_labels.dtype),
        "classes": classes.tolist(),
        "class_count": int(len(classes)),
    }


def resolve_quality_run_configuration(
    frame: pd.DataFrame,
    *,
    field_mapping: Mapping[str, str] | None = None,
    target_column: str | None = None,
    input_columns: Sequence[str] | None = None,
    cross_validation_enabled: bool = True,
    cross_validation_folds: int | None = 3,
) -> tuple[dict[str, Any], np.ndarray | None]:
    evaluation = normalize_quality_evaluation_config(
        cross_validation_enabled,
        cross_validation_folds,
    )
    selected_inputs, input_schema = _resolve_quality_input_schema(
        frame,
        field_mapping=field_mapping,
        target_column=target_column,
        input_columns=input_columns,
    )
    labels, target_schema = _resolve_quality_target_schema(
        frame,
        target_column,
        evaluation,
    )
    return {
        "target_column": target_column,
        "input_columns": selected_inputs,
        "input_schema": input_schema,
        "target_schema": target_schema,
        "evaluation": evaluation,
    }, labels


ANNOTATION_SAMPLE_EXPORT_FIELDS = (
    "source_row_index",
    "display_id",
    "automatic_label",
    "current_label",
    "current_note",
    "review_status",
    "warning_level",
    "defect_probability",
    "cluster_id",
    "rule_hits",
    "current_revision_id",
)
ANNOTATION_REVISION_EXPORT_FIELDS = (
    "revision_id",
    "sample_id",
    "author_id",
    "label",
    "note",
    "action",
    "decision",
    "review_comment",
    "parent_revision_id",
    "created_at",
)
ANNOTATION_SNAPSHOT_EXPORT_FIELDS = (
    "snapshot_id",
    "name",
    "label_source",
    "sample_id",
    "label",
    "revision_id",
    "created_at",
)


def _export_identifier(value: Any) -> str | None:
    return str(value) if value is not None else None


def _export_json(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return str(value)


def build_annotation_export(run: SpotWeldQualityRun, db, format: str = "xlsx") -> bytes:
    """Build a transient CSV/XLSX export from persisted annotation lineage."""
    if format not in {"csv", "xlsx"}:
        raise QualityPipelineError("QUALITY_ANNOTATION_EXPORT_FORMAT_INVALID")

    samples = db.query(SpotWeldQualitySample).filter(
        SpotWeldQualitySample.run_id == run.id,
    ).order_by(SpotWeldQualitySample.source_row_index, SpotWeldQualitySample.id).all()
    revisions = db.query(SpotWeldLabelRevision).filter(
        SpotWeldLabelRevision.run_id == run.id,
    ).order_by(SpotWeldLabelRevision.created_at, SpotWeldLabelRevision.id).all()
    snapshots = db.query(SpotWeldLabelSnapshot).filter(
        SpotWeldLabelSnapshot.run_id == run.id,
    ).order_by(SpotWeldLabelSnapshot.created_at, SpotWeldLabelSnapshot.id).all()

    sample_frame = pd.DataFrame([
        {
            "source_row_index": sample.source_row_index,
            "display_id": sample.display_id,
            "automatic_label": sample.automatic_label,
            "current_label": sample.current_label,
            "current_note": sample.current_note,
            "review_status": sample.review_status,
            "warning_level": sample.warning_level,
            "defect_probability": sample.defect_probability,
            "cluster_id": sample.cluster_id,
            "rule_hits": _export_json(sample.rule_hits or []),
            "current_revision_id": _export_identifier(sample.current_revision_id),
        }
        for sample in samples
    ], columns=ANNOTATION_SAMPLE_EXPORT_FIELDS)
    revision_frame = pd.DataFrame([
        {
            "revision_id": _export_identifier(revision.id),
            "sample_id": _export_identifier(revision.sample_id),
            "author_id": _export_identifier(revision.author_id),
            "label": revision.label,
            "note": revision.note,
            "action": revision.action,
            "decision": revision.decision,
            "review_comment": revision.review_comment,
            "parent_revision_id": _export_identifier(revision.parent_revision_id),
            "created_at": revision.created_at.isoformat() if revision.created_at else None,
        }
        for revision in revisions
    ], columns=ANNOTATION_REVISION_EXPORT_FIELDS)
    snapshot_rows: list[dict[str, Any]] = []
    for snapshot in snapshots:
        labels = snapshot.labels or []
        if not labels:
            snapshot_rows.append({
                "snapshot_id": _export_identifier(snapshot.id),
                "name": snapshot.name,
                "label_source": "approved",
                "sample_id": None,
                "label": None,
                "revision_id": None,
                "created_at": snapshot.created_at.isoformat() if snapshot.created_at else None,
            })
            continue
        for label in labels:
            snapshot_rows.append({
                "snapshot_id": _export_identifier(snapshot.id),
                "name": snapshot.name,
                "label_source": str(label.get("source") or "approved"),
                "sample_id": _export_identifier(label.get("sample_id")),
                "label": label.get("label"),
                "revision_id": _export_identifier(label.get("revision_id")),
                "created_at": snapshot.created_at.isoformat() if snapshot.created_at else None,
            })
    snapshot_frame = pd.DataFrame(snapshot_rows, columns=ANNOTATION_SNAPSHOT_EXPORT_FIELDS)

    output = BytesIO()
    if format == "csv":
        sample_frame.to_csv(output, index=False, encoding="utf-8-sig")
        return output.getvalue()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        sample_frame.to_excel(writer, sheet_name="标注样本", index=False)
        revision_frame.to_excel(writer, sheet_name="标签修订", index=False)
        snapshot_frame.to_excel(writer, sheet_name="标签快照", index=False)
    return output.getvalue()


def save_labeled_dataset(
    db,
    run: SpotWeldQualityRun,
    *,
    artifact_service: ArtifactService | None = None,
    label_source: str = "current",
):
    """Persist the reviewed labels beside the original dataset as a new artifact.

    ``current`` keeps a manual label when present and falls back to the persisted
    automatic label so an operator can confirm unchanged samples without editing
    every row.  The source columns stay in their original order and ``label`` is
    always the final column.
    """
    if label_source not in {"current", "automatic"}:
        raise QualityPipelineError("QUALITY_LABEL_SOURCE_INVALID")
    artifact_service = artifact_service or build_artifact_service(db)
    source_artifact, frame = resolve_dataset_frame(
        db, artifact_service, run.project_id, run.dataset_artifact_id,
    )
    samples = db.query(SpotWeldQualitySample).filter(
        SpotWeldQualitySample.run_id == run.id,
    ).order_by(SpotWeldQualitySample.source_row_index, SpotWeldQualitySample.id).all()
    labels_by_row = {
        int(sample.source_row_index): (
            sample.automatic_label
            if label_source == "automatic"
            else (sample.current_label or sample.automatic_label)
        )
        for sample in samples
    }
    missing_rows = [
        index for index in range(len(frame))
        if not str(labels_by_row.get(index) or "").strip()
    ]
    if missing_rows:
        raise QualityPipelineError(
            "QUALITY_LABELS_INCOMPLETE",
            message=f"Missing labels for {len(missing_rows)} row(s)",
            row_index=missing_rows[0],
        )

    labeled_frame = frame.drop(columns=["label"], errors="ignore").copy()
    labeled_frame["label"] = [labels_by_row[index] for index in range(len(frame))]
    source_suffix = Path(source_artifact.name or "dataset.csv").suffix.lower()
    output_suffix = ".xlsx" if source_suffix in {".xls", ".xlsx"} else ".csv"
    source_stem = Path(source_artifact.name or "dataset").stem or "dataset"
    output_name = f"{source_stem}-labeled{output_suffix}"
    metadata = {
        "source": "spot_weld_labeling",
        "source_dataset_artifact_id": str(source_artifact.id),
        "quality_run_id": str(run.id),
        "label_source": label_source,
        "row_count": int(len(labeled_frame)),
        "column_count": int(len(labeled_frame.columns)),
        "schema": [
            {
                "name": str(column),
                "dtype": str(labeled_frame[column].dtype),
                "null_count": int(labeled_frame[column].isna().sum()),
            }
            for column in labeled_frame.columns
        ],
    }
    with tempfile.TemporaryDirectory(prefix="spot-weld-labeled-") as directory:
        output_path = Path(directory) / output_name
        if output_suffix == ".xlsx":
            labeled_frame.to_excel(output_path, index=False, engine="openpyxl")
        else:
            labeled_frame.to_csv(output_path, index=False, encoding="utf-8-sig")
        return artifact_service.create_from_file(
            run.project_id,
            output_path,
            output_name,
            "dataset",
            metadata=metadata,
            commit=False,
        )


SNAPSHOT_TRAINING_CV_FOLDS = 5


@dataclass
class CandidateResult:
    algorithm_id: str
    name: str
    status: str
    config_index: int
    best_score: float | None = None
    auc: float | None = None
    f1: float | None = None
    auc_std: float = 0.0
    f1_std: float = 0.0
    best_params: dict[str, Any] = field(default_factory=dict)
    completed_trials: int = 0
    pruned_trials: int = 0
    failed_trials: int = 0
    training_time_seconds: float = 0.0
    error_code: str | None = None
    error_message: str | None = None
    feature_importance: list[float] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "algorithm_id": self.algorithm_id,
            "status": self.status,
            "best_score": self.best_score,
            "auc": self.auc,
            "f1": self.f1,
            "config_index": self.config_index,
            "auc_std": self.auc_std,
            "f1_std": self.f1_std,
            "best_params": self.best_params,
            "completed_trials": self.completed_trials,
            "pruned_trials": self.pruned_trials,
            "failed_trials": self.failed_trials,
            "training_time_seconds": self.training_time_seconds,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "feature_importance": self.feature_importance,
        }


def select_best_candidate(results: list[CandidateResult]) -> CandidateResult:
    successful = [result for result in results if result.error_code is None and result.auc is not None and result.f1 is not None]
    if not successful:
        raise QualityPipelineError("QUALITY_AUTOML_ALL_CANDIDATES_FAILED")
    return max(successful, key=lambda item: (float(item.auc), float(item.f1), -item.config_index))


def _feature_importance(model, feature_count: int) -> np.ndarray:
    importance = getattr(model, "feature_importances_", None)
    if importance is None:
        importance = np.abs(getattr(model, "coef_", np.ones((1, feature_count))))
        importance = np.asarray(importance).mean(axis=0)
    importance = np.asarray(importance, dtype=float).reshape(-1)
    if len(importance) != feature_count or not np.isfinite(importance).all() or float(importance.sum()) <= 0:
        return np.ones(feature_count, dtype=float)
    return importance


def _estimator_matrix(values: np.ndarray) -> pd.DataFrame:
    """Keep fitted and predicted model matrices on one stable feature-name contract."""
    matrix = np.asarray(values, dtype=np.float64)
    if matrix.ndim != 2:
        raise QualityPipelineError("QUALITY_AUTOML_INPUT_INVALID")
    return pd.DataFrame(matrix, columns=[f"feature_{index}" for index in range(matrix.shape[1])])


def _quality_automl_auc(y_true: np.ndarray, probabilities: np.ndarray, class_count: int) -> float:
    if class_count == 2:
        return float(roc_auc_score(y_true, probabilities[:, 1]))
    return float(roc_auc_score(
        y_true,
        probabilities,
        labels=np.arange(class_count),
        multi_class="ovr",
        average="macro",
    ))


def _quality_automl_splits(
    features: np.ndarray,
    target: np.ndarray,
    evaluation: Mapping[str, Any],
) -> tuple[tuple[np.ndarray, np.ndarray], ...]:
    if evaluation["cross_validation_enabled"]:
        splitter = StratifiedKFold(
            n_splits=int(evaluation["cross_validation_folds"]),
            shuffle=True,
            random_state=42,
        )
        return tuple(splitter.split(features, target))
    try:
        train_index, test_index = train_test_split(
            np.arange(len(target)),
            test_size=0.2,
            random_state=42,
            stratify=target,
        )
    except ValueError as error:
        raise QualityPipelineError("QUALITY_AUTOML_INSUFFICIENT_LABELS") from error
    return ((train_index, test_index),)


def _quality_estimator_metrics(
    estimator_factory: Callable[[], Any],
    *,
    features: np.ndarray,
    target: np.ndarray,
    evaluation: Mapping[str, Any],
) -> dict[str, Any]:
    class_count = len(np.unique(target))
    aucs: list[float] = []
    f1s: list[float] = []
    importances: list[np.ndarray] = []
    for train_index, test_index in _quality_automl_splits(features, target, evaluation):
        scaler = StandardScaler()
        train = scaler.fit_transform(features[train_index])
        test = scaler.transform(features[test_index])
        estimator = estimator_factory()
        estimator.fit(_estimator_matrix(train), target[train_index])
        probabilities = estimator.predict_proba(_estimator_matrix(test))
        predictions = estimator.predict(_estimator_matrix(test))
        aucs.append(_quality_automl_auc(target[test_index], probabilities, class_count))
        f1s.append(float(f1_score(
            target[test_index], predictions, average="macro", zero_division=0,
        )))
        importances.append(_feature_importance(estimator, features.shape[1]))
    return {
        "auc": float(np.mean(aucs)),
        "f1": float(np.mean(f1s)),
        "auc_std": float(np.std(aucs)),
        "f1_std": float(np.std(f1s)),
        "feature_importance": np.mean(importances, axis=0).tolist(),
    }


def _evaluate_quality_estimator(
    estimator,
    *,
    task: str,
    features: np.ndarray,
    target: np.ndarray,
    evaluation: Mapping[str, Any],
) -> float:
    if task != "classification":
        raise QualityPipelineError("QUALITY_AUTOML_SEARCH_CONFIG_INVALID")
    metrics = _quality_estimator_metrics(
        lambda: estimator,
        features=features,
        target=target,
        evaluation=evaluation,
    )
    return float(metrics["auc"])


def run_automl(
    features: np.ndarray,
    labels: Iterable[Any],
    *,
    algorithm_ids: Sequence[str] | None = None,
    search_method: str = "bayesian",
    max_trials: int = 20,
    time_budget: float = 600,
    evaluation: Mapping[str, Any] | None = None,
    progress_callback: Callable[[int, int, CandidateResult], None] | None = None,
    family_search: Callable[..., FamilySearchResult] = run_family_search,
    monotonic: Callable[[], float] = time.monotonic,
) -> tuple[list[CandidateResult], CandidateResult]:
    X = np.asarray(features, dtype=np.float64)
    y_raw = np.asarray(list(labels))
    if X.ndim != 2 or len(X) != len(y_raw):
        raise QualityPipelineError("QUALITY_AUTOML_INPUT_INVALID")
    unique, y = np.unique(y_raw, return_inverse=True)
    if len(unique) < 2:
        raise QualityPipelineError("QUALITY_AUTOML_INSUFFICIENT_LABELS")
    evaluation_config = normalize_quality_evaluation_config(
        (evaluation or {}).get("cross_validation_enabled", True),
        (evaluation or {}).get("cross_validation_folds", 3),
    )
    counts = np.bincount(y)
    minimum_count = (
        int(evaluation_config["cross_validation_folds"])
        if evaluation_config["cross_validation_enabled"]
        else 2
    )
    if len(counts) < 2 or int(counts.min()) < minimum_count:
        raise QualityPipelineError("QUALITY_AUTOML_INSUFFICIENT_LABELS")
    search_config = normalize_quality_search_config(
        algorithm_ids,
        search_method,
        int(max_trials),
        int(time_budget),
    )
    families = resolve_algorithm_families(search_config["algorithm_ids"])
    deadline = monotonic() + float(search_config["time_budget"])
    planned_trials = len(families) * search_config["max_trials"]
    terminal_trials = 0
    results: list[CandidateResult] = []
    for config_index, family in enumerate(families):
        remaining = deadline - monotonic()
        if remaining <= 0:
            results.append(CandidateResult(
                algorithm_id=family.id,
                name=family.display_name,
                status="failed",
                config_index=config_index,
                error_code="QUALITY_AUTOML_BUDGET_EXHAUSTED",
                error_message="Point-weld AutoML time budget exhausted",
            ))
            continue

        def on_trial(_summary, *, current_family=family) -> None:
            nonlocal terminal_trials
            terminal_trials += 1
            if progress_callback is not None:
                progress_callback(
                    terminal_trials,
                    planned_trials,
                    CandidateResult(
                        algorithm_id=current_family.id,
                        name=current_family.display_name,
                        status="running",
                        config_index=config_index,
                    ),
                )

        family_result = family_search(
            family=family,
            task="classification",
            features=X,
            target=y,
            evaluation=evaluation_config,
            config=SearchConfig(
                method=search_config["search_method"],
                max_trials=search_config["max_trials"],
                timeout_seconds=max(0.001, remaining / (len(families) - config_index)),
            ),
            catalog_index=config_index,
            estimator_evaluator=_evaluate_quality_estimator,
            trial_callback=on_trial,
        )
        result = CandidateResult(
            algorithm_id=family.id,
            name=family.display_name,
            status=family_result.status,
            config_index=config_index,
            best_score=family_result.best_score,
            best_params=dict(family_result.best_params),
            completed_trials=family_result.completed_trials,
            pruned_trials=family_result.pruned_trials,
            failed_trials=family_result.failed_trials,
            training_time_seconds=family_result.training_time_seconds,
            error_code=family_result.error_code,
            error_message=family_result.error_message,
        )
        if family_result.status == "completed":
            metrics = _quality_estimator_metrics(
                lambda family=family, params=result.best_params: family.build("classification", params),
                features=X,
                target=y,
                evaluation=evaluation_config,
            )
            result.auc = metrics["auc"]
            result.f1 = metrics["f1"]
            result.auc_std = metrics["auc_std"]
            result.f1_std = metrics["f1_std"]
            result.feature_importance = metrics["feature_importance"]
        results.append(result)
    return results, select_best_candidate(results)


@dataclass(frozen=True)
class ClusterResult:
    best_k: int
    silhouette_scores: dict[int, float]
    cluster_ids: list[int]
    pca_coordinates: np.ndarray
    anomaly_cluster: int
    weights: list[float]

    def to_dict(self) -> dict[str, Any]:
        return {
            "best_k": self.best_k,
            "silhouette_scores": {str(key): value for key, value in self.silhouette_scores.items()},
            "cluster_ids": self.cluster_ids,
            "pca_coordinates": self.pca_coordinates.tolist(),
            "anomaly_cluster": self.anomaly_cluster,
            "weights": self.weights,
        }


def run_clustering(
    features: np.ndarray,
    *,
    feature_names: list[str],
    feature_importance: np.ndarray | Iterable[float],
) -> ClusterResult:
    X = np.asarray(features, dtype=np.float64)
    if X.ndim != 2 or X.shape[1] != len(feature_names) or len(X) < 3:
        raise QualityPipelineError("QUALITY_CLUSTER_INPUT_INVALID")
    scaler = StandardScaler()
    scaled = scaler.fit_transform(X)
    importances = np.asarray(list(feature_importance), dtype=float).reshape(-1)
    if len(importances) != X.shape[1] or not np.isfinite(importances).all():
        importances = np.ones(X.shape[1], dtype=float)
    else:
        importances = np.maximum(importances, 0.0)
        if importances.sum() <= 0:
            importances = np.ones(X.shape[1], dtype=float)
    weights = importances / importances.sum()
    weighted = scaled * np.sqrt(weights)
    max_k = min(8, len(X) - 1)
    scores: dict[int, float] = {}
    for k in range(2, max_k + 1):
        labels = KMeans(n_clusters=k, random_state=42, n_init=10).fit_predict(weighted)
        if len(set(labels)) > 1:
            scores[k] = float(silhouette_score(weighted, labels))
    if not scores:
        raise QualityPipelineError("QUALITY_CLUSTER_FAILED")
    best_k = max(scores, key=lambda key: (scores[key], -key))
    labels = KMeans(n_clusters=best_k, random_state=42, n_init=10).fit_predict(weighted)
    coordinates = PCA(n_components=2, random_state=42).fit_transform(weighted)
    # Report v1 makes the highest spatter cluster the anomaly role; ties use energy then ID.
    spatter_index = feature_names.index("spatter_total") if "spatter_total" in feature_names else None
    energy_index = feature_names.index("energy_dev") if "energy_dev" in feature_names else None
    cluster_keys = []
    for cluster_id in sorted(set(labels)):
        members = labels == cluster_id
        spatter_score = float(np.mean(X[members, spatter_index])) if spatter_index is not None else 0.0
        energy_score = float(np.mean(np.abs(X[members, energy_index]))) if energy_index is not None else 0.0
        cluster_keys.append((spatter_score, energy_score, -cluster_id, cluster_id))
    anomaly_cluster = max(cluster_keys)[-1]
    return ClusterResult(
        best_k=best_k,
        silhouette_scores=scores,
        cluster_ids=labels.astype(int).tolist(),
        pca_coordinates=coordinates,
        anomaly_cluster=int(anomaly_cluster),
        weights=weights.tolist(),
    )


@dataclass(frozen=True)
class RuleHit:
    code: str
    label: str
    reason: str

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "label": self.label, "reason": self.reason}


@dataclass(frozen=True)
class RuleResult:
    primary_label: str
    hits: tuple[RuleHit, ...]

    @property
    def hit_codes(self) -> list[str]:
        return [hit.code for hit in self.hits]

    def to_dict(self) -> dict[str, Any]:
        return {"primary_label": self.primary_label, "hits": [hit.to_dict() for hit in self.hits]}


def apply_report_v1_rules(
    values: Mapping[str, Any],
    *,
    thresholds: Mapping[str, float],
    cluster_id: int | None = None,
    anomaly_cluster: int | None = None,
) -> RuleResult:
    # Kept as a compatibility input for existing callers. Report v1 labels use
    # the fixed cluster=1 rule supplied by the process specification.
    _ = anomaly_cluster

    def number(name: str, default: float = 0.0) -> float:
        value = values.get(name, default)
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    hits: list[RuleHit] = []
    splatter = number("wld_spatter_strength")
    diameter = number("spotdiameter")
    strong_min = float(thresholds.get("strong_splatter_min", DEFAULT_REPORT_RULE_CONFIG["strong_splatter_min"]))
    weak_value = float(thresholds.get("weak_splatter_value", DEFAULT_REPORT_RULE_CONFIG["weak_splatter_value"]))
    small_min = float(thresholds.get("spotdiameter_small_min", DEFAULT_REPORT_RULE_CONFIG["spotdiameter_small_min"]))
    small_max = float(thresholds.get("spotdiameter_small_max", DEFAULT_REPORT_RULE_CONFIG["spotdiameter_small_max"]))
    large_min = float(thresholds.get("spotdiameter_large_min", DEFAULT_REPORT_RULE_CONFIG["spotdiameter_large_min"]))
    cluster_rule_id = int(thresholds.get("spatter_cluster_id", DEFAULT_REPORT_RULE_CONFIG["spatter_cluster_id"]))
    cluster_min_strength = float(thresholds.get("spatter_cluster_min_strength", DEFAULT_REPORT_RULE_CONFIG["spatter_cluster_min_strength"]))
    if splatter >= strong_min:
        hits.append(RuleHit("strong_splatter", "strong_splatter", f"wld_spatter_strength >= {strong_min:g}"))
    elif splatter == weak_value:
        hits.append(RuleHit("weak_splatter", "weak_splatter", f"wld_spatter_strength = {weak_value:g}"))
    if small_min < diameter < small_max:
        hits.append(RuleHit("spot_too_small", "spot_too_small", f"{small_min:g} < spotdiameter < {small_max:g}"))
    if diameter > large_min:
        hits.append(RuleHit("spot_too_large", "spot_too_large", f"spotdiameter > {large_min:g}"))
    energy_sigma = float(thresholds.get("energy_dev_sigma", thresholds.get("energy_dev_abs", REPORT_RULE_ENERGY_SIGMA)))
    if abs(number("energy_dev")) > energy_sigma:
        hits.append(RuleHit("energy_anomaly", "energy_anomaly", f"|energy_dev| > {energy_sigma:g}σ"))
    if number("current_max_diff") > float(thresholds.get("current_max_diff_p95", np.inf)):
        hits.append(RuleHit("current_jump", "current_jump", "current_max_diff > P95"))
    if number("power_std") > float(thresholds.get("power_std_p95", np.inf)):
        hits.append(RuleHit("power_fluctuation", "power_fluctuation", "power_std > P95"))
    if cluster_id == cluster_rule_id and splatter >= cluster_min_strength:
        hits.append(RuleHit("anomaly_cluster", "anomaly_cluster", f"cluster={cluster_rule_id} 且 飞溅等级 >= {cluster_min_strength:g}"))
    if not hits:
        hits.append(RuleHit("normal", "normal", "no report_v1 rule matched"))
    return RuleResult(primary_label=hits[0].label, hits=tuple(hits))


def warning_level(probability: float) -> str:
    probability = float(probability)
    if probability >= 0.8:
        return "critical"
    if probability >= 0.6:
        return "warning"
    if probability >= 0.3:
        return "notice"
    return "none"


def read_report_dataset(path: str | Path) -> pd.DataFrame:
    source = Path(path)
    suffix = source.suffix.lower()
    try:
        if suffix == ".csv":
            return pd.read_csv(source)
        if suffix == ".xlsx":
            return pd.read_excel(source, engine="openpyxl")
        if suffix == ".xls":
            return pd.read_excel(source, engine="xlrd")
    except Exception as error:
        # Parser exceptions vary by engine; clients need one stable validation code.
        raise QualityPipelineError("QUALITY_DATASET_INVALID", message="Dataset could not be parsed") from error
    raise QualityPipelineError("QUALITY_DATASET_FORMAT_UNSUPPORTED", message="Only CSV/XLS/XLSX datasets are supported")


def build_demo_report_frame(row_count: int = 60) -> pd.DataFrame:
    """Build deterministic report-shaped data for an authorized local demo."""
    if row_count < 12:
        raise QualityPipelineError(
            "QUALITY_DEMO_ROW_COUNT_INVALID",
            message="Demo data requires at least 12 rows",
        )

    generator = np.random.default_rng(42)
    time = np.linspace(0.0, 1.0, 870, endpoint=False)

    def encode_waveform(
        baseline: float,
        amplitude: float,
        phase: float,
        *,
        jump_strength: float = 0.0,
    ) -> str:
        values = baseline + amplitude * np.sin(2.0 * np.pi * (4.0 * time + phase))
        values += generator.normal(0.0, max(1.0, amplitude * 0.025), size=time.shape)
        if jump_strength > 0:
            values[len(values) // 2:] += jump_strength
        encoded = np.clip(np.rint(values), -30000, 30000).astype(">i2")
        return base64.b64encode(encoded.tobytes()).decode("ascii")

    rows: list[dict[str, object]] = []
    for index in range(row_count):
        pattern = index % 4
        defect_scale = (0.0, 0.35, 0.75, 0.55)[pattern]
        splatter = (0.0, 2.0, 3.0, 1.0)[pattern]
        diameter = (5.4, 5.0, 5.2, 1.6)[pattern]
        phase = index / max(row_count, 1)
        current_jump = (
            350.0 + 2.0 * (index // 16)
            if row_count >= 1000 and pattern == 0 and index % 16 == 0
            else 0.0
        )
        rows.append({
            "wld1c": 8.0 + 0.18 * pattern + generator.normal(0.0, 0.06),
            "wld2c": 10.0 + 0.22 * pattern + generator.normal(0.0, 0.06),
            "tipv1": 2.1 + 0.08 * pattern + generator.normal(0.0, 0.02),
            "tipv2": 2.5 + 0.07 * pattern + generator.normal(0.0, 0.02),
            "wres": 0.28 + 0.03 * defect_scale + generator.normal(0.0, 0.006),
            "energy": 100.0 + (18.0 if pattern == 2 else -8.0 if pattern == 3 else 0.0) + generator.normal(0.0, 2.5),
            "wld_spatter_strength": splatter,
            "wld1_spatter_strength": splatter * 0.65,
            "wld2_spatter_strength": splatter * 0.35,
            "spatterpos_wld": 12.0 * defect_scale + generator.normal(0.0, 0.4),
            "spatterpos_pre": 5.0 * defect_scale + generator.normal(0.0, 0.3),
            "spotdiameter": diameter + generator.normal(0.0, 0.08),
            "spotposition": 1.0 + 0.1 * pattern + generator.normal(0.0, 0.02),
            "spattercode": float(pattern * 10),
            "cvei": encode_waveform(
                1180.0 + 90.0 * defect_scale,
                240.0 + 45.0 * defect_scale,
                phase,
                jump_strength=current_jump,
            ),
            "cvev": encode_waveform(420.0 + 34.0 * defect_scale, 88.0 + 18.0 * defect_scale, phase + 0.12),
            "cver": encode_waveform(54.0 + 12.0 * defect_scale, 15.0 + 7.0 * defect_scale, phase + 0.24),
            "cvep": encode_waveform(520.0 + 125.0 * defect_scale, 130.0 + 52.0 * defect_scale, phase + 0.36),
        })
    return pd.DataFrame(rows)


def create_demo_quality_dataset(
    db,
    *,
    project_id,
    row_count: int = 60,
    artifact_service: ArtifactService | None = None,
):
    """Persist report-compatible demo data through the normal Artifact boundary."""
    artifact_service = artifact_service or build_artifact_service(db)
    frame = build_demo_report_frame(row_count)
    with tempfile.TemporaryDirectory(prefix="spot-weld-demo-") as directory:
        source = Path(directory) / "spot-weld-report-demo.csv"
        frame.to_csv(source, index=False)
        schema = [
            {
                "name": str(column),
                "dtype": str(frame[column].dtype),
                "null_count": int(frame[column].isna().sum()),
            }
            for column in frame.columns
        ]
        return artifact_service.create_from_file(
            project_id,
            source,
            "spot-weld-report-demo.csv",
            "dataset",
            metadata={
                "source": "spot_weld_demo",
                "row_count": int(len(frame)),
                "column_count": int(len(frame.columns)),
                "schema": schema,
                "feature_version": "report_v1",
            },
            commit=False,
        )


def validate_report_frame(frame: pd.DataFrame, field_mapping: Mapping[str, str] | None = None) -> dict[str, Any]:
    try:
        features, schema, statistics = build_feature_frame(frame, field_mapping=field_mapping)
    except QualityPipelineError as initial_error:
        try:
            canonical = canonicalize_report_frame(frame, field_mapping)
        except QualityPipelineError as error:
            row_count = int(len(frame)) if isinstance(frame, pd.DataFrame) else 0
            return {
                "row_count": row_count,
                "valid_rows": 0,
                "invalid_rows": row_count,
                "feature_schema": list(FEATURE_SCHEMA),
                "errors": [error.to_dict()],
            }

        errors: list[dict[str, object]] = []
        for row_index in range(len(canonical)):
            try:
                build_feature_frame(canonical.iloc[[row_index]].reset_index(drop=True))
            except QualityPipelineError as error:
                errors.append(QualityPipelineError(
                    error.code,
                    row_index=row_index,
                    field_name=error.field_name,
                ).to_dict())
        if not errors:
            errors.append(initial_error.to_dict())
        return {
            "row_count": int(len(canonical)),
            "valid_rows": int(len(canonical) - len(errors)),
            "invalid_rows": len(errors),
            "feature_schema": list(FEATURE_SCHEMA),
            "errors": errors,
        }
    return {
        "row_count": int(len(frame)),
        "valid_rows": int(len(features)),
        "invalid_rows": 0,
        "feature_schema": schema,
        "statistics": statistics,
        "errors": [],
    }


def resolve_dataset_frame(
    db,
    artifact_service: ArtifactService,
    project_id,
    dataset_artifact_id,
) -> tuple[Any, pd.DataFrame]:
    try:
        artifact = artifact_service.resolve(dataset_artifact_id, project_id, expected_type="dataset")
        with artifact_service.materialize(artifact.id, project_id, expected_type="dataset") as path:
            return artifact, read_report_dataset(path)
    except (ArtifactAccessError, QualityPipelineError, OSError, ValueError) as error:
        if isinstance(error, QualityPipelineError):
            raise
        raise QualityPipelineError("DATASET_ARTIFACT_INVALID", message=str(error)) from error


def create_quality_run_record(
    db,
    *,
    project_id,
    user_id,
    dataset_artifact_id,
    field_mapping: Mapping[str, str] | None = None,
    algorithm_ids: Sequence[str] | None = None,
    search_method: str = "bayesian",
    max_trials: int = 20,
    time_budget: int = 600,
    target_column: str | None = None,
    input_columns: Sequence[str] | None = None,
    cross_validation_enabled: bool = True,
    cross_validation_folds: int | None = 3,
    label_mode: str = "automatic",
    rule_config: Mapping[str, Any] | None = None,
    artifact_service: ArtifactService | None = None,
) -> SpotWeldQualityRun:
    if not isinstance(label_mode, str) or label_mode not in QUALITY_LABEL_MODES:
        raise QualityPipelineError("QUALITY_LABEL_MODE_INVALID")
    search_config = normalize_quality_search_config(
        algorithm_ids,
        search_method,
        max_trials,
        time_budget,
    )
    normalized_rule_config = normalize_report_rule_config(rule_config)
    artifact_service = artifact_service or build_artifact_service(db)
    artifact, frame = resolve_dataset_frame(db, artifact_service, project_id, dataset_artifact_id)
    features, schema, statistics = build_feature_frame(frame, field_mapping=field_mapping)
    run_configuration, _ = resolve_quality_run_configuration(
        frame,
        field_mapping=field_mapping,
        target_column=target_column,
        input_columns=input_columns,
        cross_validation_enabled=cross_validation_enabled,
        cross_validation_folds=cross_validation_folds,
    )
    run = SpotWeldQualityRun(
        project_id=project_id,
        dataset_artifact_id=artifact.id,
        created_by_id=user_id,
        status="queued",
        field_mapping=dict(field_mapping or {}),
        feature_schema=schema,
        input_fingerprint={
            "artifact_id": str(artifact.id),
            "sha256": (artifact.metadata_ or {}).get("sha256"),
            "row_count": len(frame),
            **search_config,
            "label_mode": label_mode,
            "rule_config": normalized_rule_config,
            **run_configuration,
        },
        statistics={**statistics, "valid_rows": len(features), **run_configuration},
        rule_set_version=REPORT_RULESET_VERSION,
        automl_results=[],
        clustering_results={},
        output_artifacts={},
        error_details={},
    )
    db.add(run)
    db.flush()
    return run


@dataclass(frozen=True)
class QualityRunOutcome:
    run_id: str
    status: str
    error_code: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return {"run_id": self.run_id, "status": self.status, "error_code": self.error_code}


def claim_quality_run(
    db,
    run_id,
    *,
    worker_id: str | None = None,
    task_id: str | None = None,
) -> SpotWeldQualityRun | None:
    """Claim one queued run with a status conditional update shared by all workers."""
    values: dict[object, object] = {
        SpotWeldQualityRun.status: "running",
        SpotWeldQualityRun.worker_id: worker_id,
    }
    if task_id:
        values[SpotWeldQualityRun.task_id] = task_id
    claimed = db.query(SpotWeldQualityRun).filter(
        SpotWeldQualityRun.id == run_id,
        SpotWeldQualityRun.status.in_(("queued", "validating")),
    ).update(values, synchronize_session=False)
    db.commit()
    if claimed != 1:
        return None
    return db.query(SpotWeldQualityRun).filter(SpotWeldQualityRun.id == run_id).first()


def recover_orphaned_local_quality_runs(db) -> int:
    """Fail local tasks left non-terminal when their in-process worker restarts."""
    runs = db.query(SpotWeldQualityRun).filter(
        SpotWeldQualityRun.task_id.like(f"{LOCAL_QUALITY_TASK_PREFIX}%"),
        SpotWeldQualityRun.status.in_(LOCAL_QUALITY_RECOVERABLE_STATUSES),
    ).all()
    for run in runs:
        run.status = "failed"
        run.error_code = LOCAL_QUALITY_WORKER_RESTARTED_CODE
        run.error_details = {
            "code": LOCAL_QUALITY_WORKER_RESTARTED_CODE,
            "message": "Local quality worker stopped during service restart; rerun this task.",
        }
    if runs:
        db.commit()
    return len(runs)


def _annotation_progress(annotated_count: int, total_count: int) -> dict[str, int | float]:
    total = max(int(total_count), 0)
    annotated = min(max(int(annotated_count), 0), total) if total else 0
    return {
        "annotated_count": annotated,
        "total_count": total,
        "percent": round((annotated / total) * 100, 2) if total else 0.0,
    }


def _modeling_progress(completed_count: int, total_count: int) -> dict[str, int | float]:
    total = max(int(total_count), 0)
    completed = min(max(int(completed_count), 0), total) if total else 0
    return {
        "completed_count": completed,
        "total_count": total,
        "percent": round((completed / total) * 100, 2) if total else 0.0,
    }


def update_quality_run_rules(
    db,
    run: SpotWeldQualityRun,
    rule_config: Mapping[str, Any] | None,
    *,
    batch_size: int = 10,
    progress_callback: Callable[[dict[str, int | float]], None] | None = None,
) -> SpotWeldQualityRun:
    """Persist edited rules and recalculate automatic labels in-place."""
    if run.status in LOCAL_QUALITY_RECOVERABLE_STATUSES:
        raise QualityPipelineError("QUALITY_RUN_ACTIVE")
    if run.status not in {"completed", "failed", "cancelled"}:
        raise QualityPipelineError("QUALITY_RUN_NOT_RECALCULABLE")
    normalized = normalize_report_rule_config(rule_config)
    run_input = dict(run.input_fingerprint or {})
    label_mode = run_input.get("label_mode", "automatic")
    if label_mode not in QUALITY_LABEL_MODES:
        raise QualityPipelineError("QUALITY_LABEL_MODE_INVALID")
    run.input_fingerprint = {**run_input, "rule_config": normalized}

    samples = db.query(SpotWeldQualitySample).filter(
        SpotWeldQualitySample.run_id == run.id,
    ).order_by(SpotWeldQualitySample.source_row_index).all()
    combined_records = [
        {**(sample.table_values or {}), **(sample.feature_values or {})}
        for sample in samples
    ]
    feature_frame = pd.DataFrame(combined_records)
    thresholds: dict[str, float | int] = dict(normalized)
    if not feature_frame.empty and {"current_max_diff", "power_std"}.issubset(feature_frame.columns):
        thresholds = build_runtime_rule_thresholds(feature_frame, normalized)

    rule_set = db.query(SpotWeldQualityRuleSet).filter(
        SpotWeldQualityRuleSet.run_id == run.id,
        SpotWeldQualityRuleSet.version == REPORT_RULESET_VERSION,
    ).one_or_none()
    if rule_set is None:
        rule_set = SpotWeldQualityRuleSet(
            project_id=run.project_id,
            run_id=run.id,
            version=REPORT_RULESET_VERSION,
            thresholds=thresholds,
        )
        db.add(rule_set)
    else:
        rule_set.thresholds = thresholds
    run.rule_set_version = REPORT_RULESET_VERSION

    if label_mode == "manual":
        db.commit()
        db.refresh(run)
        return run

    total_count = len(samples)
    run.status = "running"
    run.error_code = None
    run.error_details = {}
    run.statistics = {
        **(run.statistics or {}),
        "annotation_progress": _annotation_progress(0, total_count),
    }
    db.commit()
    if progress_callback:
        progress_callback(run.statistics["annotation_progress"])

    commit_size = max(1, int(batch_size))
    for index, (sample, record) in enumerate(zip(samples, combined_records), start=1):
        result = apply_report_v1_rules(record, thresholds=thresholds, cluster_id=sample.cluster_id)
        sample.automatic_label = result.primary_label
        sample.rule_hits = [hit.to_dict() for hit in result.hits]
        if index % commit_size == 0 or index == total_count:
            run.statistics = {
                **(run.statistics or {}),
                "annotation_progress": _annotation_progress(index, total_count),
            }
            db.commit()
            if progress_callback:
                progress_callback(run.statistics["annotation_progress"])

    run.status = "completed"
    run.statistics = {
        **(run.statistics or {}),
        "annotation_progress": _annotation_progress(total_count, total_count),
    }
    db.commit()
    db.refresh(run)
    return run


def _json_value(value: Any) -> Any:
    """Keep the source row JSON-safe without narrowing its original column set."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return [_json_value(item) for item in value.tolist()]
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if pd.isna(value):
        return None
    return str(value)


def _source_row_values(frame: pd.DataFrame, row_index: int) -> dict[str, Any]:
    row = frame.iloc[row_index]
    return {str(column): _json_value(row[column]) for column in frame.columns}


def _fit_candidate_model(features: np.ndarray, labels: Iterable[Any], candidate: CandidateResult):
    try:
        family = get_algorithm_family(candidate.algorithm_id)
    except ValueError as error:
        raise QualityPipelineError("QUALITY_AUTOML_SEARCH_CONFIG_INVALID") from error
    model = family.build("classification", candidate.best_params)
    if candidate.error_code is not None:
        raise QualityPipelineError("QUALITY_AUTOML_SEARCH_CONFIG_INVALID")
    _, encoded = np.unique(np.asarray(list(labels)), return_inverse=True)
    scaler = StandardScaler()
    transformed = scaler.fit_transform(np.asarray(features, dtype=np.float64))
    model.fit(_estimator_matrix(transformed), encoded)
    return scaler, model


QUALITY_REPORT_CHART_KEYS = (
    "model_comparison_chart",
    "cluster_pca_chart",
    "feature_importance_chart",
    "warning_distribution_chart",
    "waveform_comparison_chart",
)


def _write_quality_run_charts(
    directory: Path,
    *,
    features: pd.DataFrame,
    samples: list[SpotWeldQualitySample],
    candidates: list[CandidateResult],
    best_candidate: CandidateResult | None,
    clustering: ClusterResult | None,
) -> dict[str, Path]:
    """Generate the five report figures once so XLSX and UI use identical artifacts."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    paths = {key: directory / f"{key}.png" for key in QUALITY_REPORT_CHART_KEYS}

    def save(key: str, figure) -> None:
        figure.tight_layout()
        figure.savefig(paths[key], dpi=140, bbox_inches="tight")
        plt.close(figure)

    names = [item.name for item in candidates]
    aucs = [float(item.auc or 0.0) for item in candidates]
    f1s = [float(item.f1 or 0.0) for item in candidates]
    figure, axis = plt.subplots(figsize=(9, 4.8))
    positions = np.arange(len(names))
    axis.bar(positions - 0.18, aucs, width=0.36, label="AUC")
    axis.bar(positions + 0.18, f1s, width=0.36, label="F1")
    axis.set_title("AutoML Model Comparison")
    axis.set_xticks(positions, names, rotation=35, ha="right")
    axis.set_ylim(0, max(1.0, *(aucs or [0.0]), *(f1s or [0.0])))
    axis.legend()
    save("model_comparison_chart", figure)

    figure, axis = plt.subplots(figsize=(7.2, 5.2))
    if clustering is not None and len(clustering.pca_coordinates):
        coordinates = np.asarray(clustering.pca_coordinates, dtype=float)
        scatter = axis.scatter(
            coordinates[:, 0],
            coordinates[:, 1],
            c=clustering.cluster_ids,
            cmap="tab10",
            s=22,
            alpha=0.85,
        )
        axis.figure.colorbar(scatter, ax=axis, label="Cluster")
    else:
        axis.text(0.5, 0.5, "No clustering result", ha="center", va="center")
    axis.set_title("Cluster PCA Visualization")
    axis.set_xlabel("PC1")
    axis.set_ylabel("PC2")
    save("cluster_pca_chart", figure)

    importance = (
        list(best_candidate.feature_importance)
        if best_candidate is not None and len(best_candidate.feature_importance) == len(features.columns)
        else []
    )
    top_features = sorted(zip(features.columns, importance), key=lambda item: item[1], reverse=True)[:20]
    figure, axis = plt.subplots(figsize=(8.5, 6.2))
    if top_features:
        feature_names, values = zip(*reversed(top_features))
        axis.barh(feature_names, values, color="#1677ff")
    else:
        axis.text(0.5, 0.5, "No feature importance", ha="center", va="center")
    axis.set_title("Feature Importance Top 20")
    save("feature_importance_chart", figure)

    warning_counts = Counter(sample.warning_level or "none" for sample in samples)
    warning_levels = ["critical", "warning", "notice", "none"]
    figure, axis = plt.subplots(figsize=(7.2, 4.8))
    axis.bar(
        warning_levels,
        [warning_counts.get(level, 0) for level in warning_levels],
        color=["#cf1322", "#fa8c16", "#d4b106", "#52c41a"],
    )
    axis.set_title("Defect Warning Distribution")
    axis.set_ylabel("Samples")
    save("warning_distribution_chart", figure)

    normal_waveforms = [
        np.asarray((sample.waveforms or {}).get("current", []), dtype=float)
        for sample in samples
        if sample.automatic_label == "normal"
    ]
    defect_waveforms = [
        np.asarray((sample.waveforms or {}).get("current", []), dtype=float)
        for sample in samples
        if sample.automatic_label and sample.automatic_label != "normal"
    ]
    figure, axis = plt.subplots(figsize=(9, 4.8))
    if normal_waveforms and defect_waveforms:
        point_count = min(
            min(len(values) for values in normal_waveforms),
            min(len(values) for values in defect_waveforms),
        )
        axis.plot(np.mean([values[:point_count] for values in normal_waveforms], axis=0), label="Normal current")
        axis.plot(np.mean([values[:point_count] for values in defect_waveforms], axis=0), label="Defect current")
        axis.legend()
    else:
        axis.text(0.5, 0.5, "No normal/defect waveform pair", ha="center", va="center")
    axis.set_title("Normal vs Defect Waveform")
    axis.set_xlabel("Sample point")
    axis.set_ylabel("Current")
    save("waveform_comparison_chart", figure)
    return paths


def _write_quality_run_report(
    path: Path,
    *,
    run: SpotWeldQualityRun,
    features: pd.DataFrame,
    samples: list[SpotWeldQualitySample],
    candidates: list[CandidateResult],
    best_candidate: CandidateResult | None,
    clustering: ClusterResult | None,
    chart_paths: Mapping[str, Path],
    evaluation_actual_labels: list[str],
    evaluation_predicted_labels: list[str],
) -> None:
    """Write the report available immediately after a quality run completes."""
    run_input = run.input_fingerprint or {}
    run_statistics = run.statistics or {}
    target_schema = run_statistics.get("target_schema") or run_input.get("target_schema") or {}
    if not isinstance(target_schema, Mapping):
        target_schema = {}
    input_columns = run_statistics.get("input_columns") or run_input.get("input_columns") or [
        item.get("name")
        for item in run_statistics.get("input_schema") or []
        if isinstance(item, Mapping) and item.get("name")
    ]
    evaluation = run_statistics.get("evaluation") or run_input.get("evaluation") or {
        "cross_validation_enabled": True,
        "cross_validation_folds": 3,
    }
    evaluation_summary = (
        f"cross_validation: {evaluation.get('cross_validation_folds')} folds"
        if evaluation.get("cross_validation_enabled")
        else "deterministic_holdout"
    )
    summary = pd.DataFrame([
        {"指标": "质量运行", "值": str(run.id)},
        {"指标": "特征版本", "值": "report_v1"},
        {"指标": "规则集版本", "值": run.rule_set_version},
        {"指标": "标注模式", "值": run_statistics.get("label_mode") or run_input.get("label_mode") or "automatic"},
        {"指标": "目标列", "值": target_schema.get("name") or "-"},
        {"指标": "输入列", "值": ", ".join(str(column) for column in input_columns) or "-"},
        {"指标": "评估配置", "值": evaluation_summary},
        {"指标": "样本数", "值": len(samples)},
        {"指标": "特征数", "值": len(features.columns)},
        {"指标": "最优模型", "值": best_candidate.name if best_candidate is not None else "-"},
        {"指标": "最优AUC", "值": best_candidate.auc if best_candidate is not None else None},
        {"指标": "最优F1", "值": best_candidate.f1 if best_candidate is not None else None},
    ])
    automl = pd.DataFrame([
        {
            "算法家族": item.algorithm_id,
            "显示名称": item.name,
            "状态": item.status,
            "最佳分数": item.best_score,
            "AUC": item.auc,
            "AUC标准差": item.auc_std,
            "F1": item.f1,
            "F1标准差": item.f1_std,
            "完成试验": item.completed_trials,
            "剪枝试验": item.pruned_trials,
            "失败试验": item.failed_trials,
            "训练耗时(秒)": item.training_time_seconds,
            "错误码": item.error_code,
            "最佳参数": _export_json(item.best_params),
        }
        for item in candidates
    ], columns=[
        "算法家族", "显示名称", "状态", "最佳分数", "AUC", "AUC标准差",
        "F1", "F1标准差", "完成试验", "剪枝试验", "失败试验",
        "训练耗时(秒)", "错误码", "最佳参数",
    ])
    deep_learning = pd.DataFrame([
        {
            "模型": "未启用独立深度学习比较",
            "说明": "点焊质量运行统一使用七类算法家族的 Optuna 搜索。",
        },
    ], columns=["模型", "说明"])
    labels_frame = pd.DataFrame([
        {
            "sample_id": str(sample.id),
            "display_id": sample.display_id,
            "automatic_label": sample.automatic_label,
            "current_label": sample.current_label,
            "review_status": sample.review_status,
            "rule_hits": _export_json(sample.rule_hits or []),
        }
        for sample in samples
    ], columns=[
        "sample_id", "display_id", "automatic_label", "current_label", "review_status", "rule_hits",
    ])
    grouped_samples: dict[int | None, list[SpotWeldQualitySample]] = {}
    for sample in samples:
        grouped_samples.setdefault(sample.cluster_id, []).append(sample)
    cluster_frame = pd.DataFrame([
        {
            "cluster_id": cluster_id,
            "sample_count": len(group),
            "avg_defect_probability": float(np.mean([
                sample.defect_probability or 0.0 for sample in group
            ])),
            "critical_count": sum(sample.warning_level == "critical" for sample in group),
            "best_k": clustering.best_k if clustering is not None else None,
            "silhouette_score": (
                clustering.silhouette_scores.get(clustering.best_k)
                if clustering is not None else None
            ),
            "anomaly_cluster": clustering.anomaly_cluster if clustering is not None else None,
        }
        for cluster_id, group in sorted(
            grouped_samples.items(),
            key=lambda item: (-1 if item[0] is None else int(item[0])),
        )
    ], columns=[
        "cluster_id", "sample_count", "avg_defect_probability", "critical_count", "best_k", "silhouette_score", "anomaly_cluster",
    ])
    importance_values = (
        best_candidate.feature_importance
        if best_candidate is not None and len(best_candidate.feature_importance) == len(features.columns)
        else []
    )
    importance_frame = pd.DataFrame([
        {
            "特征": feature_name,
            "重要性": float(importance),
            "类型": "表格" if feature_name in TABLE_FEATURES else "波形",
        }
        for feature_name, importance in sorted(
            zip(features.columns, importance_values), key=lambda item: item[1], reverse=True,
        )
    ], columns=["特征", "重要性", "类型"])
    coordinates = (
        clustering.pca_coordinates
        if clustering is not None and len(clustering.pca_coordinates) == len(samples)
        else None
    )
    inference_frame = pd.DataFrame([
        {
            "display_id": sample.display_id,
            "automatic_label": sample.automatic_label,
            "current_label": sample.current_label,
            "predicted_label": (
                evaluation_predicted_labels[index]
                if index < len(evaluation_predicted_labels)
                else None
            ),
            "defect_probability": sample.defect_probability,
            "warning_level": sample.warning_level,
            "cluster_id": sample.cluster_id,
            "pca_x": float(coordinates[index, 0]) if coordinates is not None else None,
            "pca_y": float(coordinates[index, 1]) if coordinates is not None else None,
        }
        for index, sample in enumerate(samples)
    ], columns=[
        "display_id", "automatic_label", "current_label", "predicted_label", "defect_probability", "warning_level", "cluster_id", "pca_x", "pca_y",
    ])
    actual_labels = [str(label) for label in evaluation_actual_labels]
    predicted_labels = [str(label) for label in evaluation_predicted_labels]
    if actual_labels and len(actual_labels) == len(predicted_labels):
        labels = sorted(set(actual_labels) | set(predicted_labels))
        evaluation_frame = pd.DataFrame(classification_report(
            actual_labels,
            predicted_labels,
            labels=labels,
            target_names=labels,
            output_dict=True,
            zero_division=0,
        )).transpose().reset_index().rename(columns={"index": "label"})
    else:
        evaluation_frame = pd.DataFrame(columns=["label", "precision", "recall", "f1-score", "support"])
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        summary.to_excel(writer, sheet_name="总览", index=False)
        automl.to_excel(writer, sheet_name="AutoML选型", index=False)
        deep_learning.to_excel(writer, sheet_name="深度学习对比", index=False)
        labels_frame.to_excel(writer, sheet_name="缺陷标签", index=False)
        cluster_frame.to_excel(writer, sheet_name="聚类画像", index=False)
        importance_frame.to_excel(writer, sheet_name="特征重要性", index=False)
        inference_frame.to_excel(writer, sheet_name="推理结果", index=False)
        evaluation_frame.to_excel(writer, sheet_name="多分类评估", index=False)
        from openpyxl.drawing.image import Image as ExcelImage

        chart_sheets = {
            "model_comparison_chart": "AutoML选型",
            "cluster_pca_chart": "聚类画像",
            "feature_importance_chart": "特征重要性",
            "warning_distribution_chart": "推理结果",
            "waveform_comparison_chart": "总览",
        }
        for chart_key, sheet_name in chart_sheets.items():
            chart_path = chart_paths.get(chart_key)
            if chart_path is None or not chart_path.is_file():
                continue
            image = ExcelImage(str(chart_path))
            image.width = 620
            image.height = 360
            writer.book[sheet_name].add_image(image, "K2")


def _generated_artifacts(
    db,
    artifact_service: ArtifactService,
    run: SpotWeldQualityRun,
    features: pd.DataFrame,
    samples: list[SpotWeldQualitySample],
    candidates: list[CandidateResult],
    best_candidate: CandidateResult | None,
    clustering: ClusterResult | None,
    evaluation_actual_labels: list[str],
    evaluation_predicted_labels: list[str],
) -> dict[str, str]:
    with tempfile.TemporaryDirectory(prefix="spot-weld-quality-") as directory:
        root = Path(directory)
        feature_path = root / "spot_weld_quality_features.csv"
        result_path = root / "spot_weld_quality_results.json"
        report_path = root / "spot_weld_quality_report.xlsx"
        features.to_csv(feature_path, index=False)
        run_statistics = run.statistics or {}
        candidate_results = [candidate.to_dict() for candidate in candidates]
        result_path.write_text(json.dumps({
            "run_id": str(run.id),
            "target_schema": run_statistics.get("target_schema"),
            "input_schema": run_statistics.get("input_schema") or [],
            "evaluation": run_statistics.get("evaluation") or {},
            "search": run_statistics.get("search") or {},
            "candidate_results": candidate_results,
            "samples": [
                {
                    "sample_id": str(sample.id), "display_id": sample.display_id,
                    "automatic_label": sample.automatic_label,
                    "predicted_label": (
                        evaluation_predicted_labels[index]
                        if index < len(evaluation_predicted_labels)
                        else None
                    ),
                    "defect_probability": sample.defect_probability,
                    "warning_level": sample.warning_level,
                    "cluster_id": sample.cluster_id,
                }
                for index, sample in enumerate(samples)
            ],
        }, ensure_ascii=False), encoding="utf-8")
        chart_paths = _write_quality_run_charts(
            root,
            features=features,
            samples=samples,
            candidates=candidates,
            best_candidate=best_candidate,
            clustering=clustering,
        )
        _write_quality_run_report(
            report_path,
            run=run,
            features=features,
            samples=samples,
            candidates=candidates,
            best_candidate=best_candidate,
            clustering=clustering,
            chart_paths=chart_paths,
            evaluation_actual_labels=evaluation_actual_labels,
            evaluation_predicted_labels=evaluation_predicted_labels,
        )
        metadata = {
            "source": "spot_weld_quality",
            "quality_run_id": str(run.id),
            "feature_version": "report_v1",
            "rule_set_version": run.rule_set_version,
            "target_column": run_statistics.get("target_column"),
            "input_columns": run_statistics.get("input_columns") or [],
            "evaluation": run_statistics.get("evaluation") or {},
            "candidate_results": candidate_results,
        }
        features_artifact = artifact_service.create_from_file(
            run.project_id, feature_path, f"spot-weld-{run.id}-features.csv", "quality_features", metadata, commit=False,
        )
        results_artifact = artifact_service.create_from_file(
            run.project_id, result_path, f"spot-weld-{run.id}-results.json", "quality_results", metadata, commit=False,
        )
        report_artifact = artifact_service.create_from_file(
            run.project_id, report_path, f"spot-weld-{run.id}-report.xlsx", "quality_report", metadata, commit=False,
        )
        chart_artifacts = {
            chart_key: artifact_service.create_from_file(
                run.project_id,
                chart_path,
                f"spot-weld-{run.id}-{chart_key}.png",
                "quality_report_chart",
                {**metadata, "report_chart": chart_key},
                commit=False,
            )
            for chart_key, chart_path in chart_paths.items()
        }
    return {
        "features": str(features_artifact.id),
        "results": str(results_artifact.id),
        "report": str(report_artifact.id),
        **{chart_key: str(artifact.id) for chart_key, artifact in chart_artifacts.items()},
    }


def execute_quality_run(
    db,
    run_id,
    *,
    worker_id: str | None = None,
    task_id: str | None = None,
    artifact_service: ArtifactService | None = None,
) -> QualityRunOutcome:
    try:
        identifier = uuid.UUID(str(run_id))
    except (TypeError, ValueError):
        return QualityRunOutcome(str(run_id), "failed", "QUALITY_RUN_NOT_FOUND")
    run = claim_quality_run(db, identifier, worker_id=worker_id, task_id=task_id)
    if run is None:
        existing = db.query(SpotWeldQualityRun).filter(SpotWeldQualityRun.id == identifier).first()
        if existing is None:
            return QualityRunOutcome(str(run_id), "failed", "QUALITY_RUN_NOT_FOUND")
        return QualityRunOutcome(str(existing.id), existing.status, existing.error_code)
    artifact_service = artifact_service or build_artifact_service(db)
    try:
        _, frame = resolve_dataset_frame(db, artifact_service, run.project_id, run.dataset_artifact_id)
        features, schema, statistics = build_feature_frame(frame, field_mapping=run.field_mapping or None)
        canonical = canonicalize_report_frame(frame, run.field_mapping or None)
        waveforms = decode_report_waveforms(frame, run.field_mapping or None)
        records = features.to_dict(orient="records")
        run_input = run.input_fingerprint or {}
        label_mode = run_input.get("label_mode", "automatic")
        if not isinstance(label_mode, str) or label_mode not in QUALITY_LABEL_MODES:
            raise QualityPipelineError("QUALITY_LABEL_MODE_INVALID")
        normalized_rule_config = normalize_report_rule_config(run_input.get("rule_config"))
        thresholds = build_runtime_rule_thresholds(features, normalized_rule_config)
        search_config = normalize_quality_search_config(
            run_input.get("algorithm_ids"),
            run_input.get("search_method", "bayesian"),
            run_input.get("max_trials", 20),
            run_input.get("time_budget", 600),
        )
        run_configuration, supervised_labels = resolve_quality_run_configuration(
            frame,
            field_mapping=run.field_mapping or None,
            target_column=run_input.get("target_column"),
            input_columns=run_input.get("input_columns"),
            cross_validation_enabled=(run_input.get("evaluation") or {}).get(
                "cross_validation_enabled",
                True,
            ),
            cross_validation_folds=(run_input.get("evaluation") or {}).get(
                "cross_validation_folds",
                3,
            ),
        )
        evaluation = run_configuration["evaluation"]
        total_count = len(records)
        preliminary_rules = (
            [apply_report_v1_rules(record, thresholds=thresholds) for record in records]
            if label_mode == "automatic"
            else [None] * total_count
        )
        run.rule_set_version = REPORT_RULESET_VERSION
        db.query(SpotWeldQualitySample).filter(SpotWeldQualitySample.run_id == run.id).delete(synchronize_session=False)
        db.query(SpotWeldQualityRuleSet).filter(SpotWeldQualityRuleSet.run_id == run.id).delete(synchronize_session=False)
        db.flush()
        db.add(SpotWeldQualityRuleSet(
            project_id=run.project_id, run_id=run.id, version=REPORT_RULESET_VERSION, thresholds=thresholds,
        ))
        run.statistics = {
            **statistics,
            "valid_rows": len(features),
            "label_mode": label_mode,
            **run_configuration,
            "annotation_progress": _annotation_progress(0, total_count),
            "search": {
                "contract": search_config["search_contract"],
                "method": search_config["search_method"],
                "max_trials": search_config["max_trials"],
                "time_budget": search_config["time_budget"],
                "algorithm_ids": search_config["algorithm_ids"],
                "budget_exhausted": False,
            },
            "modeling_progress": _modeling_progress(
                0,
                len(search_config["algorithm_ids"]) * search_config["max_trials"]
                if label_mode == "automatic" or supervised_labels is not None else 0,
            ),
        }
        db.commit()

        samples: list[SpotWeldQualitySample] = []
        batch_size = 10
        annotated_count = 0
        for index, (record, waveform) in enumerate(zip(records, waveforms)):
            rule_result = preliminary_rules[index]
            sample = SpotWeldQualitySample(
                run_id=run.id,
                source_row_index=index,
                display_id=f"W-{index + 1:04d}",
                table_values=_source_row_values(frame, index),
                feature_values={key: float(value) for key, value in record.items()},
                waveforms=waveform,
                automatic_label=rule_result.primary_label if rule_result is not None else None,
                rule_hits=[item.to_dict() for item in rule_result.hits] if rule_result is not None else [],
                cluster_id=None,
                defect_probability=None,
                warning_level="none",
                review_status="pending_review",
            )
            db.add(sample)
            samples.append(sample)
            if label_mode == "automatic" and sample.automatic_label is not None:
                annotated_count += 1
            if (index + 1) % batch_size == 0 or index == total_count - 1:
                db.flush()
                run.statistics = {
                    **(run.statistics or {}),
                    "annotation_progress": _annotation_progress(annotated_count, total_count),
                }
                db.commit()

        def update_model_progress(completed_count: int, candidate_total: int, result: CandidateResult) -> None:
            run.statistics = {
                **(run.statistics or {}),
                "modeling_progress": _modeling_progress(completed_count, candidate_total),
                "search": {
                    **((run.statistics or {}).get("search") or {}),
                    "current_algorithm": result.algorithm_id,
                },
            }
            db.commit()

        best_candidate: CandidateResult | None = None
        evaluation_actual_labels: list[str] = []
        evaluation_predicted_labels: list[str] = []
        if supervised_labels is not None:
            candidate_results, best_candidate = run_automl(
                features.to_numpy(dtype=np.float64),
                supervised_labels,
                algorithm_ids=search_config["algorithm_ids"],
                search_method=search_config["search_method"],
                max_trials=search_config["max_trials"],
                time_budget=search_config["time_budget"],
                evaluation=evaluation,
                progress_callback=update_model_progress,
            )
            clustering = run_clustering(
                features.to_numpy(dtype=np.float64),
                feature_names=schema,
                feature_importance=np.asarray(best_candidate.feature_importance, dtype=float),
            )
            final_rules = (
                [
                    apply_report_v1_rules(
                        record,
                        thresholds=thresholds,
                        cluster_id=clustering.cluster_ids[index],
                    )
                    for index, record in enumerate(records)
                ]
                if label_mode == "automatic"
                else [None] * len(records)
            )
            scaler, model = _fit_candidate_model(
                features.to_numpy(dtype=np.float64),
                supervised_labels,
                best_candidate,
            )
            probabilities_by_class = model.predict_proba(_estimator_matrix(
                scaler.transform(features.to_numpy(dtype=np.float64)),
            ))
            supervised_classes = np.unique(supervised_labels)
            prediction_codes = np.asarray(model.predict(_estimator_matrix(
                scaler.transform(features.to_numpy(dtype=np.float64)),
            ))).reshape(-1)
            normal_indexes = np.where(supervised_classes == "normal")[0]
            probabilities = (
                1.0 - probabilities_by_class[:, int(normal_indexes[0])]
                if len(normal_indexes)
                else np.max(probabilities_by_class, axis=1)
            )
            evaluation_actual_labels = [str(label) for label in supervised_labels]
            evaluation_predicted_labels = [
                str(supervised_classes[int(code)]) for code in prediction_codes
            ]
            cluster_ids: list[int | None] = list(clustering.cluster_ids)
        elif label_mode == "automatic":
            preliminary = [apply_report_v1_rules(record, thresholds=thresholds) for record in records]
            automatic_labels = np.asarray([result.primary_label for result in preliminary], dtype=str)
            candidate_results, best_candidate = run_automl(
                features.to_numpy(dtype=np.float64),
                automatic_labels,
                algorithm_ids=search_config["algorithm_ids"],
                search_method=search_config["search_method"],
                max_trials=search_config["max_trials"],
                time_budget=search_config["time_budget"],
                evaluation=evaluation,
                progress_callback=update_model_progress,
            )
            clustering = run_clustering(
                features.to_numpy(dtype=np.float64),
                feature_names=schema,
                feature_importance=np.asarray(best_candidate.feature_importance, dtype=float),
            )
            final_rules = [
                apply_report_v1_rules(
                    record, thresholds=thresholds, cluster_id=clustering.cluster_ids[index],
                )
                    for index, record in enumerate(records)
            ]
            scaler, model = _fit_candidate_model(features.to_numpy(dtype=np.float64), automatic_labels, best_candidate)
            probabilities_by_class = model.predict_proba(_estimator_matrix(
                scaler.transform(features.to_numpy(dtype=np.float64)),
            ))
            automatic_classes = np.unique(automatic_labels)
            prediction_codes = np.asarray(model.predict(_estimator_matrix(
                scaler.transform(features.to_numpy(dtype=np.float64)),
            ))).reshape(-1)
            normal_indexes = np.where(automatic_classes == "normal")[0]
            probabilities = (
                1.0 - probabilities_by_class[:, int(normal_indexes[0])]
                if len(normal_indexes)
                else np.max(probabilities_by_class, axis=1)
            )
            evaluation_actual_labels = [str(label) for label in automatic_labels]
            evaluation_predicted_labels = [
                str(automatic_classes[int(code)]) for code in prediction_codes
            ]
            cluster_ids: list[int | None] = list(clustering.cluster_ids)
        else:
            candidate_results = []
            clustering = None
            final_rules = [None] * len(records)
            probabilities = [None] * len(records)
            cluster_ids = [None] * len(records)
        # Model-progress commits expire the initial batch objects. Reload once before
        # updating per-sample predictions so assignments do not trigger N single-row reads.
        samples = db.query(SpotWeldQualitySample).filter(
            SpotWeldQualitySample.run_id == run.id,
        ).order_by(SpotWeldQualitySample.source_row_index).all()
        for index, sample in enumerate(samples):
            rule_result = final_rules[index]
            probability = probabilities[index]
            sample.automatic_label = rule_result.primary_label if rule_result is not None else None
            sample.rule_hits = [item.to_dict() for item in rule_result.hits] if rule_result is not None else []
            sample.cluster_id = cluster_ids[index]
            sample.defect_probability = float(probability) if probability is not None else None
            sample.warning_level = warning_level(float(probability)) if probability is not None else "none"
        db.flush()
        annotated_count = total_count if label_mode == "automatic" else 0
        completed_trials = sum(
            item.completed_trials + item.pruned_trials + item.failed_trials
            for item in candidate_results
        )
        planned_trials = len(search_config["algorithm_ids"]) * search_config["max_trials"]
        run.statistics = {
            **(run.statistics or {}),
            "annotation_progress": _annotation_progress(annotated_count, total_count),
            "modeling_progress": _modeling_progress(completed_trials, planned_trials),
            "search": {
                **((run.statistics or {}).get("search") or {}),
                "budget_exhausted": any(
                    item.error_code == "QUALITY_AUTOML_BUDGET_EXHAUSTED"
                    for item in candidate_results
                ),
            },
        }
        db.commit()
        samples = db.query(SpotWeldQualitySample).filter(
            SpotWeldQualitySample.run_id == run.id,
        ).order_by(SpotWeldQualitySample.source_row_index).all()
        output_artifacts = _generated_artifacts(
            db,
            artifact_service,
            run,
            features,
            samples,
            candidate_results,
            best_candidate,
            clustering,
            evaluation_actual_labels,
            evaluation_predicted_labels,
        )
        run.status = "completed"
        run.feature_schema = schema
        run.statistics = {
            **statistics,
            "valid_rows": len(features),
            "label_mode": label_mode,
            **run_configuration,
            "annotation_progress": _annotation_progress(annotated_count, total_count),
            "modeling_progress": _modeling_progress(completed_trials, planned_trials),
            "search": {
                **((run.statistics or {}).get("search") or {}),
                "budget_exhausted": any(
                    item.error_code == "QUALITY_AUTOML_BUDGET_EXHAUSTED"
                    for item in candidate_results
                ),
            },
            "warning_counts": dict(Counter(sample.warning_level for sample in samples)),
        }
        run.automl_results = [item.to_dict() for item in candidate_results]
        run.clustering_results = clustering.to_dict() if clustering is not None else {}
        run.output_artifacts = output_artifacts
        run.error_code = None
        run.error_details = {}
        db.commit()
        return QualityRunOutcome(str(run.id), "completed")
    except QualityPipelineError as error:
        db.rollback()
        run = db.query(SpotWeldQualityRun).filter(SpotWeldQualityRun.id == identifier).first()
        if run is not None:
            run.status = "failed"
            run.error_code = error.code
            run.error_details = error.to_dict()
            db.commit()
        return QualityRunOutcome(str(identifier), "failed", error.code)
    except Exception as error:
        db.rollback()
        run = db.query(SpotWeldQualityRun).filter(SpotWeldQualityRun.id == identifier).first()
        if run is not None:
            run.status = "failed"
            run.error_code = "QUALITY_RUN_EXECUTION_FAILED"
            run.error_details = {"code": "QUALITY_RUN_EXECUTION_FAILED", "message": str(error)}
            db.commit()
        return QualityRunOutcome(str(identifier), "failed", "QUALITY_RUN_EXECUTION_FAILED")


def _snapshot_or_error(db, snapshot_id) -> SpotWeldLabelSnapshot:
    try:
        identifier = uuid.UUID(str(snapshot_id))
    except (TypeError, ValueError) as error:
        raise QualityPipelineError("QUALITY_LABEL_SNAPSHOT_NOT_FOUND") from error
    snapshot = db.query(SpotWeldLabelSnapshot).filter(SpotWeldLabelSnapshot.id == identifier).first()
    if snapshot is None:
        raise QualityPipelineError("QUALITY_LABEL_SNAPSHOT_NOT_FOUND")
    return snapshot


def _snapshot_label_source(snapshot: SpotWeldLabelSnapshot) -> str:
    sources = {str(item.get("source", "approved")) for item in (snapshot.labels or [])}
    if not sources:
        return "approved"
    if len(sources) != 1 or not sources.issubset({"approved", "automatic"}):
        raise QualityPipelineError("QUALITY_LABEL_SNAPSHOT_INVALID")
    return sources.pop()


def _snapshot_training_data(
    db,
    snapshot: SpotWeldLabelSnapshot,
    run: SpotWeldQualityRun,
) -> tuple[np.ndarray, np.ndarray, list[str], list[SpotWeldQualitySample]]:
    frozen_labels = snapshot.labels or []
    if not frozen_labels:
        raise QualityPipelineError("QUALITY_LABEL_SNAPSHOT_EMPTY")
    sample_ids: list[uuid.UUID] = []
    labels: list[str] = []
    for item in frozen_labels:
        try:
            sample_ids.append(uuid.UUID(str(item["sample_id"])))
            labels.append(str(item["label"]))
        except (KeyError, TypeError, ValueError) as error:
            raise QualityPipelineError("QUALITY_LABEL_SNAPSHOT_INVALID") from error
    if len(set(sample_ids)) != len(sample_ids):
        raise QualityPipelineError("QUALITY_LABEL_SNAPSHOT_INVALID")
    samples = db.query(SpotWeldQualitySample).filter(
        SpotWeldQualitySample.run_id == run.id,
        SpotWeldQualitySample.id.in_(sample_ids),
    ).all()
    by_id = {sample.id: sample for sample in samples}
    if len(by_id) != len(sample_ids):
        raise QualityPipelineError("QUALITY_LABEL_SNAPSHOT_INVALID")
    feature_names = list(run.feature_schema or FEATURE_SCHEMA)
    if not feature_names:
        raise QualityPipelineError("QUALITY_TRAINING_FEATURE_SCHEMA_INVALID")
    ordered_samples = [by_id[sample_id] for sample_id in sample_ids]
    try:
        features = np.asarray([
            [float((sample.feature_values or {})[name]) for name in feature_names]
            for sample in ordered_samples
        ], dtype=np.float64)
    except (KeyError, TypeError, ValueError) as error:
        raise QualityPipelineError("QUALITY_TRAINING_FEATURE_SCHEMA_INVALID") from error
    if features.ndim != 2 or features.shape[1] != len(feature_names) or not np.isfinite(features).all():
        raise QualityPipelineError("QUALITY_TRAINING_FEATURE_SCHEMA_INVALID")
    counts = Counter(labels)
    if len(counts) < 2 or min(counts.values()) < 5:
        raise QualityPipelineError("QUALITY_LABELS_INSUFFICIENT_FOR_5_FOLD")
    return features, np.asarray(labels, dtype=str), feature_names, ordered_samples


def run_snapshot_training(
    features: np.ndarray,
    labels: np.ndarray,
    feature_names: list[str],
    *,
    algorithm_ids: Sequence[str] | None = None,
    search_method: str = "bayesian",
    max_trials: int = 20,
    time_budget: int = 600,
    family_search: Callable[..., FamilySearchResult] = run_family_search,
) -> tuple[list[CandidateResult], CandidateResult, np.ndarray]:
    if features.ndim != 2 or features.shape[1] != len(feature_names):
        raise QualityPipelineError("QUALITY_TRAINING_FEATURE_SCHEMA_INVALID")
    classes, encoded = np.unique(labels, return_inverse=True)
    counts = np.bincount(encoded)
    if len(classes) < 2 or int(counts.min()) < 5:
        raise QualityPipelineError("QUALITY_LABELS_INSUFFICIENT_FOR_5_FOLD")
    results, winner = run_automl(
        features,
        labels,
        algorithm_ids=algorithm_ids,
        search_method=search_method,
        max_trials=max_trials,
        time_budget=time_budget,
        evaluation={
            "cross_validation_enabled": True,
            "cross_validation_folds": SNAPSHOT_TRAINING_CV_FOLDS,
        },
        family_search=family_search,
    )
    return results, winner, classes


def _fit_snapshot_model(
    features: np.ndarray,
    labels: np.ndarray,
    feature_names: list[str],
    best_candidate: CandidateResult,
) -> tuple[Any, StandardScaler, np.ndarray, list[int]]:
    try:
        family = get_algorithm_family(best_candidate.algorithm_id)
    except ValueError as error:
        raise QualityPipelineError("QUALITY_AUTOML_SEARCH_CONFIG_INVALID") from error
    _, encoded = np.unique(labels, return_inverse=True)
    indexes = list(range(len(feature_names)))
    scaler = StandardScaler()
    transformed = scaler.fit_transform(features[:, indexes])
    model = family.build("classification", best_candidate.best_params)
    model.fit(_estimator_matrix(transformed), encoded)
    return model, scaler, encoded, indexes


def _write_snapshot_report(
    path: Path,
    *,
    run: SpotWeldQualityRun,
    snapshot: SpotWeldLabelSnapshot,
    candidates: list[CandidateResult],
    feature_importance: Mapping[str, float],
    snapshot_samples: list[SpotWeldQualitySample],
    all_samples: list[SpotWeldQualitySample],
    labels: np.ndarray,
    encoded_labels: np.ndarray,
    predictions: np.ndarray,
    probabilities: np.ndarray,
    classes: np.ndarray,
) -> None:
    label_source = _snapshot_label_source(snapshot)
    run_input = run.input_fingerprint or {}
    run_statistics = run.statistics or {}
    target_schema = run_statistics.get("target_schema") or run_input.get("target_schema") or {}
    input_columns = run_input.get("input_columns") or [
        item.get("name")
        for item in run_statistics.get("input_schema") or []
        if isinstance(item, Mapping) and item.get("name")
    ]
    evaluation = run_statistics.get("evaluation") or run_input.get("evaluation") or {
        "cross_validation_enabled": True,
        "cross_validation_folds": 3,
    }
    run_evaluation_summary = (
        f"cross_validation: {evaluation.get('cross_validation_folds')} folds"
        if evaluation.get("cross_validation_enabled")
        else "deterministic_holdout"
    )
    snapshot_evaluation_summary = f"cross_validation: {SNAPSHOT_TRAINING_CV_FOLDS} folds"
    summary = pd.DataFrame([
        {"指标": "质量运行", "值": str(run.id)},
        {"指标": "标签快照", "值": str(snapshot.id)},
        {"指标": "标签来源", "值": label_source},
        {"指标": "特征版本", "值": "report_v1"},
        {"指标": "源数据目标列", "值": target_schema.get("name") or "-"},
        {"指标": "源数据输入列", "值": ", ".join(str(column) for column in input_columns) or "-"},
        {"指标": "质量运行评估配置", "值": run_evaluation_summary},
        {"指标": "快照训练评估配置", "值": snapshot_evaluation_summary},
        {"指标": "训练标签样本", "值": len(snapshot_samples)},
        {"指标": "全量样本", "值": len(all_samples)},
        {"指标": "最优模型", "值": next((item.name for item in candidates if item.error_code is None and item.auc == max((candidate.auc or -1) for candidate in candidates)), "-")},
    ])
    automl = pd.DataFrame([item.to_dict() for item in candidates])
    deep_learning = pd.DataFrame([{
        "状态": "已移除固定候选",
        "说明": "标签快照训练统一复用七类算法家族和 Optuna 搜索。",
    }])
    labels_frame = pd.DataFrame([
        {
            "sample_id": str(sample.id),
            "display_id": sample.display_id,
            "label": label,
            "review_status": sample.review_status,
            "revision_id": next((item.get("revision_id") for item in (snapshot.labels or []) if item.get("sample_id") == str(sample.id)), None),
            "source": next((item.get("source", "approved") for item in (snapshot.labels or []) if item.get("sample_id") == str(sample.id)), label_source),
        }
        for sample, label in zip(snapshot_samples, labels)
    ])
    cluster_frame = pd.DataFrame([
        {
            "cluster_id": cluster_id,
            "sample_count": len(group),
            "avg_defect_probability": float(np.mean([sample.defect_probability or 0.0 for sample in group])),
            "critical_count": sum(sample.warning_level == "critical" for sample in group),
        }
        for cluster_id, group in sorted(
            ((cluster_id, [sample for sample in all_samples if sample.cluster_id == cluster_id]) for cluster_id in {sample.cluster_id for sample in all_samples}),
            key=lambda item: (-1 if item[0] is None else int(item[0])),
        )
    ])
    importance_frame = pd.DataFrame([
        {"特征": name, "重要性": value, "类型": "表格" if name in TABLE_FEATURES else "波形"}
        for name, value in sorted(feature_importance.items(), key=lambda item: item[1], reverse=True)
    ])
    inference_frame = pd.DataFrame([
        {
            "display_id": sample.display_id,
            "automatic_label": sample.automatic_label,
            "current_label": sample.current_label,
            "defect_probability": sample.defect_probability,
            "warning_level": sample.warning_level,
            "cluster_id": sample.cluster_id,
        }
        for sample in all_samples
    ])
    evaluation = classification_report(
        encoded_labels,
        predictions,
        labels=np.arange(len(classes)),
        target_names=classes.tolist(),
        output_dict=True,
        zero_division=0,
    )
    evaluation_frame = pd.DataFrame(evaluation).transpose().reset_index().rename(columns={"index": "label"})
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        summary.to_excel(writer, sheet_name="总览", index=False)
        automl.to_excel(writer, sheet_name="AutoML选型", index=False)
        deep_learning.to_excel(writer, sheet_name="深度学习对比", index=False)
        labels_frame.to_excel(writer, sheet_name="缺陷标签", index=False)
        cluster_frame.to_excel(writer, sheet_name="聚类画像", index=False)
        importance_frame.to_excel(writer, sheet_name="特征重要性", index=False)
        inference_frame.to_excel(writer, sheet_name="推理结果", index=False)
        evaluation_frame.to_excel(writer, sheet_name="多分类评估", index=False)


@dataclass(frozen=True)
class QualityTrainingOutcome:
    snapshot_id: str
    run_id: str
    model_library: ModelLibrary
    output_artifacts: dict[str, str]


def train_label_snapshot(
    db,
    snapshot_id,
    *,
    artifact_service: ArtifactService | None = None,
    commit: bool = True,
) -> QualityTrainingOutcome:
    """Train from immutable approved or explicitly sourced automatic-label snapshots."""
    snapshot = _snapshot_or_error(db, snapshot_id)
    run = db.query(SpotWeldQualityRun).filter(
        SpotWeldQualityRun.id == snapshot.run_id,
        SpotWeldQualityRun.project_id == snapshot.project_id,
    ).first()
    if run is None:
        raise QualityPipelineError("QUALITY_RUN_NOT_FOUND")
    artifact_service = artifact_service or build_artifact_service(db)
    label_source = _snapshot_label_source(snapshot)
    features, labels, feature_names, snapshot_samples = _snapshot_training_data(db, snapshot, run)
    run_input = run.input_fingerprint or {}
    search_config = normalize_quality_search_config(
        run_input.get("algorithm_ids"),
        run_input.get("search_method", "bayesian"),
        run_input.get("max_trials", 20),
        run_input.get("time_budget", 600),
    )
    candidates, best_candidate, classes = run_snapshot_training(
        features,
        labels,
        feature_names,
        algorithm_ids=search_config["algorithm_ids"],
        search_method=search_config["search_method"],
        max_trials=search_config["max_trials"],
        time_budget=search_config["time_budget"],
    )
    model, scaler, encoded_labels, indexes = _fit_snapshot_model(features, labels, feature_names, best_candidate)
    selected_feature_names = [feature_names[index] for index in indexes]
    importance_values = _feature_importance(model, len(indexes))
    feature_importance = {
        feature_names[index]: float(value)
        for index, value in zip(indexes, importance_values)
    }
    transformed_features = _estimator_matrix(scaler.transform(features[:, indexes]))
    probabilities = model.predict_proba(transformed_features)
    predictions = model.predict(transformed_features)
    best_metrics = {
        "cv_auc": best_candidate.auc,
        "cv_auc_std": best_candidate.auc_std,
        "cv_f1": best_candidate.f1,
        "cv_f1_std": best_candidate.f1_std,
        "train_accuracy": float(accuracy_score(encoded_labels, predictions)),
    }
    all_samples = db.query(SpotWeldQualitySample).filter(
        SpotWeldQualitySample.run_id == run.id,
    ).order_by(SpotWeldQualitySample.source_row_index).all()
    try:
        all_features = np.asarray([
            [float((sample.feature_values or {})[name]) for name in selected_feature_names]
            for sample in all_samples
        ], dtype=np.float64)
    except (KeyError, TypeError, ValueError) as error:
        raise QualityPipelineError("QUALITY_TRAINING_FEATURE_SCHEMA_INVALID") from error
    all_probabilities = model.predict_proba(_estimator_matrix(scaler.transform(all_features)))
    normal_index = int(np.where(classes == "normal")[0][0]) if "normal" in classes else None
    defect_probabilities = 1.0 - all_probabilities[:, normal_index] if normal_index is not None else np.max(all_probabilities, axis=1)
    for sample, probability in zip(all_samples, defect_probabilities):
        sample.defect_probability = float(probability)
        sample.warning_level = warning_level(float(probability))

    metadata = {
        "source": "spot_weld_quality",
        "quality_run_id": str(run.id),
        "label_snapshot_id": str(snapshot.id),
        "label_source": label_source,
        "feature_version": "report_v1",
        "rule_set_version": run.rule_set_version,
        "algorithm_id": best_candidate.algorithm_id,
        "algorithm_ids": search_config["algorithm_ids"],
        "search_method": search_config["search_method"],
        "max_trials": search_config["max_trials"],
        "time_budget": search_config["time_budget"],
        "best_params": best_candidate.best_params,
    }
    with tempfile.TemporaryDirectory(prefix="spot-weld-quality-training-") as directory:
        root = Path(directory)
        model_path = root / "spot_weld_quality_model.joblib"
        schema_path = root / "spot_weld_quality_schema.json"
        report_path = root / "spot_weld_quality_report.xlsx"
        joblib.dump({
            "scaler": scaler,
            "model": model,
            "feature_schema": selected_feature_names,
            "classes": classes.tolist(),
            "feature_version": "report_v1",
            "label_snapshot_id": str(snapshot.id),
            "label_source": label_source,
            "algorithm_id": best_candidate.algorithm_id,
            "algorithm_ids": search_config["algorithm_ids"],
            "search_method": search_config["search_method"],
            "max_trials": search_config["max_trials"],
            "time_budget": search_config["time_budget"],
            "best_params": best_candidate.best_params,
        }, model_path)
        schema_path.write_text(json.dumps({
            "feature_schema": selected_feature_names,
            "classes": classes.tolist(),
            "metrics": best_metrics,
            "feature_importance": feature_importance,
            "label_source": label_source,
            "algorithm_id": best_candidate.algorithm_id,
            "algorithm_ids": search_config["algorithm_ids"],
            "search_method": search_config["search_method"],
            "best_params": best_candidate.best_params,
        }, ensure_ascii=False), encoding="utf-8")
        _write_snapshot_report(
            report_path,
            run=run,
            snapshot=snapshot,
            candidates=candidates,
            feature_importance=feature_importance,
            snapshot_samples=snapshot_samples,
            all_samples=all_samples,
            labels=labels,
            encoded_labels=encoded_labels,
            predictions=predictions,
            probabilities=probabilities,
            classes=classes,
        )
        model_artifact = artifact_service.create_from_file(
            run.project_id, model_path, f"spot-weld-{run.id}-model.joblib", "model", metadata, commit=False,
        )
        schema_artifact = artifact_service.create_from_file(
            run.project_id, schema_path, f"spot-weld-{run.id}-schema.json", "quality_schema", metadata, commit=False,
        )
        report_artifact = artifact_service.create_from_file(
            run.project_id, report_path, f"spot-weld-{run.id}-report.xlsx", "quality_report", metadata, commit=False,
        )
    model_library = ModelLibrary(
        name=f"点焊质量模型 {str(run.id)[:8]}",
        project_id=run.project_id,
        owner_id=snapshot.created_by_id,
        version="report_v1",
        status="completed",
        framework="scikit-learn",
        backbone=best_candidate.algorithm_id,
        description=("基于报告复现自动标签快照的质量感知模型" if label_source == "automatic" else "基于已审核点焊标签快照的质量感知模型"),
        metrics=best_metrics,
        params={
            "source": "spot_weld_quality",
            "quality_run_id": str(run.id),
            "label_snapshot_id": str(snapshot.id),
            "label_source": label_source,
            "feature_version": "report_v1",
            "rule_set_version": run.rule_set_version,
            "schema_artifact_id": str(schema_artifact.id),
            "algorithm_id": best_candidate.algorithm_id,
            "algorithm_ids": search_config["algorithm_ids"],
            "search_method": search_config["search_method"],
            "max_trials": search_config["max_trials"],
            "time_budget": search_config["time_budget"],
            "best_params": best_candidate.best_params,
        },
        dataset_artifact_id=run.dataset_artifact_id,
        model_artifact_id=model_artifact.id,
        file_size=model_artifact.file_size,
        format="joblib",
        tags=["spot_weld_quality", "report_v1"],
        progress=1.0,
    )
    db.add(model_library)
    db.flush()
    output_artifacts = {
        **(run.output_artifacts or {}),
        "model": str(model_artifact.id),
        "schema": str(schema_artifact.id),
        "report": str(report_artifact.id),
    }
    run.output_artifacts = output_artifacts
    run.statistics = {
        **(run.statistics or {}),
        "label_snapshot_id": str(snapshot.id),
        "label_source": label_source,
        "model_library_id": str(model_library.id),
        "training_warning_counts": dict(Counter(sample.warning_level for sample in all_samples)),
    }
    if commit:
        db.commit()
        db.refresh(model_library)
    else:
        db.flush()
    return QualityTrainingOutcome(
        snapshot_id=str(snapshot.id),
        run_id=str(run.id),
        model_library=model_library,
        output_artifacts=output_artifacts,
    )
