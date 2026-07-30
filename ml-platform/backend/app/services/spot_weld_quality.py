"""Report-compatible quality validation, AutoML, clustering and rules."""

from __future__ import annotations

import base64
from collections import Counter
from dataclasses import dataclass, field
import json
from pathlib import Path
import tempfile
import time
import uuid
from typing import Any, Iterable, Mapping

import joblib
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from sklearn.ensemble import ExtraTreesClassifier, GradientBoostingClassifier, HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.metrics import accuracy_score, classification_report, f1_score, roc_auc_score, silhouette_score
from sklearn.model_selection import StratifiedKFold
from sklearn.neural_network import MLPClassifier
from sklearn.preprocessing import StandardScaler

from app.models.model_library import ModelLibrary
from app.models.spot_weld_quality import (
    SpotWeldLabelSnapshot,
    SpotWeldQualityRuleSet,
    SpotWeldQualityRun,
    SpotWeldQualitySample,
)
from app.services.artifact_service import ArtifactAccessError, ArtifactService, build_artifact_service
from app.services.spot_weld_features import (
    FEATURE_SCHEMA,
    QualityPipelineError,
    REPORT_TABLE_FIELDS,
    TABLE_FEATURES,
    build_feature_frame,
    canonicalize_report_frame,
    decode_report_waveforms,
)


AUTOML_CONFIGS: tuple[dict[str, Any], ...] = (
    {"name": "LGB_v1", "type": "lgb", "params": {"n_estimators": 200, "learning_rate": 0.05, "num_leaves": 31}},
    {"name": "LGB_v2", "type": "lgb", "params": {"n_estimators": 500, "learning_rate": 0.03, "num_leaves": 63, "subsample": 0.7, "colsample_bytree": 0.7, "reg_alpha": 0.1, "reg_lambda": 0.1}},
    {"name": "XGB_v1", "type": "xgb", "params": {"n_estimators": 200, "learning_rate": 0.05, "max_depth": 5}},
    {"name": "XGB_v2", "type": "xgb", "params": {"n_estimators": 500, "learning_rate": 0.03, "max_depth": 7}},
    {"name": "CAT_v1", "type": "catboost", "params": {"iterations": 200, "learning_rate": 0.05, "depth": 6, "verbose": False}},
    {"name": "CAT_v2", "type": "catboost", "params": {"iterations": 500, "learning_rate": 0.03, "depth": 8, "verbose": False}},
    {"name": "GBDT_v1", "type": "gbdt", "params": {"n_estimators": 200, "learning_rate": 0.1, "max_depth": 5}},
    {"name": "RF_v1", "type": "rf", "params": {"n_estimators": 300, "max_depth": None}},
    {"name": "ET_v1", "type": "extra", "params": {"n_estimators": 300, "max_depth": None}},
    {"name": "HGB_v1", "type": "histgb", "params": {"max_iter": 300, "learning_rate": 0.05}},
)

SNAPSHOT_TRAINING_CONFIGS: tuple[dict[str, Any], ...] = (
    {"name": "AutoML(LGB_v2)", "type": "lgb", "params": dict(AUTOML_CONFIGS[1]["params"]), "feature_scope": "fusion"},
    {"name": "MLP_128-64-32", "type": "mlp", "params": {"hidden_layer_sizes": (128, 64, 32), "alpha": 0.001, "max_iter": 350, "early_stopping": False}, "feature_scope": "fusion"},
    {"name": "MLP_256-128-64", "type": "mlp", "params": {"hidden_layer_sizes": (256, 128, 64), "alpha": 0.0005, "max_iter": 350, "early_stopping": False}, "feature_scope": "fusion"},
    {"name": "MLP_仅表格", "type": "mlp", "params": {"hidden_layer_sizes": (128, 64, 32), "alpha": 0.001, "max_iter": 350, "early_stopping": False}, "feature_scope": "table"},
)


@dataclass
class CandidateResult:
    name: str
    model_type: str
    auc: float | None = None
    f1: float | None = None
    config_index: int = 0
    auc_std: float = 0.0
    f1_std: float = 0.0
    training_time_seconds: float = 0.0
    error_code: str | None = None
    error_message: str | None = None
    feature_importance: list[float] = field(default_factory=list)
    params: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "model_type": self.model_type,
            "auc": self.auc,
            "f1": self.f1,
            "config_index": self.config_index,
            "auc_std": self.auc_std,
            "f1_std": self.f1_std,
            "training_time_seconds": self.training_time_seconds,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "feature_importance": self.feature_importance,
            "params": self.params,
        }


def select_best_candidate(results: list[CandidateResult]) -> CandidateResult:
    successful = [result for result in results if result.error_code is None and result.auc is not None and result.f1 is not None]
    if not successful:
        raise QualityPipelineError("QUALITY_AUTOML_ALL_CANDIDATES_FAILED")
    return max(successful, key=lambda item: (float(item.auc), float(item.f1), -item.config_index))


def _build_estimator(config: Mapping[str, Any], *, seed: int = 42):
    model_type = config["type"]
    params = dict(config.get("params", {}))
    if model_type == "lgb":
        try:
            from lightgbm import LGBMClassifier
        except ImportError as error:
            raise QualityPipelineError("QUALITY_AUTOML_DEPENDENCY_UNAVAILABLE", message="lightgbm is not installed") from error
        return LGBMClassifier(random_state=seed, verbosity=-1, **params)
    if model_type == "xgb":
        try:
            from xgboost import XGBClassifier
        except ImportError as error:
            raise QualityPipelineError("QUALITY_AUTOML_DEPENDENCY_UNAVAILABLE", message="xgboost is not installed") from error
        return XGBClassifier(random_state=seed, eval_metric="logloss", n_jobs=1, **params)
    if model_type == "catboost":
        try:
            from catboost import CatBoostClassifier
        except ImportError as error:
            raise QualityPipelineError("QUALITY_AUTOML_DEPENDENCY_UNAVAILABLE", message="catboost is not installed") from error
        return CatBoostClassifier(random_seed=seed, allow_writing_files=False, **params)
    if model_type == "gbdt":
        return GradientBoostingClassifier(random_state=seed, **params)
    if model_type == "rf":
        return RandomForestClassifier(random_state=seed, n_jobs=1, **params)
    if model_type == "extra":
        return ExtraTreesClassifier(random_state=seed, n_jobs=1, **params)
    if model_type == "histgb":
        return HistGradientBoostingClassifier(random_state=seed, **params)
    if model_type == "mlp":
        params.setdefault("max_iter", 400)
        params.setdefault("early_stopping", True)
        return MLPClassifier(random_state=seed, **params)
    raise QualityPipelineError("QUALITY_AUTOML_CONFIG_INVALID", message=f"Unknown model type: {model_type}")


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


def run_automl(
    features: np.ndarray,
    labels: Iterable[Any],
    *,
    configs: tuple[Mapping[str, Any], ...] = AUTOML_CONFIGS,
) -> tuple[list[CandidateResult], CandidateResult]:
    X = np.asarray(features, dtype=np.float64)
    y_raw = np.asarray(list(labels))
    if X.ndim != 2 or len(X) != len(y_raw):
        raise QualityPipelineError("QUALITY_AUTOML_INPUT_INVALID")
    unique, y = np.unique(y_raw, return_inverse=True)
    if len(unique) != 2:
        raise QualityPipelineError("QUALITY_AUTOML_BINARY_LABELS_REQUIRED")
    counts = np.bincount(y)
    if len(counts) < 2 or int(counts.min()) < 3:
        raise QualityPipelineError("QUALITY_AUTOML_INSUFFICIENT_LABELS")
    splitter = StratifiedKFold(n_splits=3, shuffle=True, random_state=42)
    results: list[CandidateResult] = []
    for config_index, config in enumerate(configs):
        result = CandidateResult(
            name=str(config["name"]), model_type=str(config["type"]), config_index=config_index,
            params=dict(config.get("params", {})),
        )
        aucs: list[float] = []
        f1s: list[float] = []
        importances: list[np.ndarray] = []
        try:
            for train_index, test_index in splitter.split(X, y):
                scaler = StandardScaler()
                train = scaler.fit_transform(X[train_index])
                test = scaler.transform(X[test_index])
                model = _build_estimator(config)
                model.fit(_estimator_matrix(train), y[train_index])
                probabilities = model.predict_proba(_estimator_matrix(test))[:, 1]
                predictions = (probabilities >= 0.5).astype(int)
                aucs.append(float(roc_auc_score(y[test_index], probabilities)))
                f1s.append(float(f1_score(y[test_index], predictions, zero_division=0)))
                importances.append(_feature_importance(model, X.shape[1]))
            result.auc = float(np.mean(aucs))
            result.f1 = float(np.mean(f1s))
            result.auc_std = float(np.std(aucs))
            result.f1_std = float(np.std(f1s))
            result.feature_importance = np.mean(importances, axis=0).tolist()
        except QualityPipelineError as error:
            result.error_code = error.code
            result.error_message = str(error)
        except Exception as error:  # candidate failures stay visible in the result table
            result.error_code = "QUALITY_AUTOML_CANDIDATE_FAILED"
            result.error_message = str(error)
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
    if len(importances) != X.shape[1] or not np.isfinite(importances).all() or importances.sum() <= 0:
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
    def number(name: str, default: float = 0.0) -> float:
        value = values.get(name, default)
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    hits: list[RuleHit] = []
    splatter = number("wld_spatter_strength")
    diameter = number("spotdiameter")
    if splatter >= 3:
        hits.append(RuleHit("strong_splatter", "strong_splatter", "wld_spatter_strength >= 3"))
    elif splatter == 2:
        hits.append(RuleHit("weak_splatter", "weak_splatter", "wld_spatter_strength = 2"))
    if 0 < diameter < 2:
        hits.append(RuleHit("spot_too_small", "spot_too_small", "0 < spotdiameter < 2"))
    if diameter > 80:
        hits.append(RuleHit("spot_too_large", "spot_too_large", "spotdiameter > 80"))
    if abs(number("energy_dev")) > float(thresholds.get("energy_dev_abs", 2.5)):
        hits.append(RuleHit("energy_anomaly", "energy_anomaly", "abs(energy_dev) > threshold"))
    if number("current_max_diff") > float(thresholds.get("current_max_diff_p95", np.inf)):
        hits.append(RuleHit("current_jump", "current_jump", "current_max_diff > P95"))
    if number("power_std") > float(thresholds.get("power_std_p95", np.inf)):
        hits.append(RuleHit("power_fluctuation", "power_fluctuation", "power_std > P95"))
    if anomaly_cluster is not None and cluster_id == anomaly_cluster and splatter >= 2:
        hits.append(RuleHit("anomaly_cluster", "anomaly_cluster", "cluster=anomaly and splatter >= 2"))
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

    def encode_waveform(baseline: float, amplitude: float, phase: float) -> str:
        values = baseline + amplitude * np.sin(2.0 * np.pi * (4.0 * time + phase))
        values += generator.normal(0.0, max(1.0, amplitude * 0.025), size=time.shape)
        encoded = np.clip(np.rint(values), -30000, 30000).astype(">i2")
        return base64.b64encode(encoded.tobytes()).decode("ascii")

    rows: list[dict[str, object]] = []
    for index in range(row_count):
        pattern = index % 4
        defect_scale = (0.0, 0.35, 0.75, 0.55)[pattern]
        splatter = (0.0, 2.0, 3.0, 1.0)[pattern]
        diameter = (5.4, 5.0, 5.2, 1.6)[pattern]
        phase = index / max(row_count, 1)
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
            "cvei": encode_waveform(1180.0 + 90.0 * defect_scale, 240.0 + 45.0 * defect_scale, phase),
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
    artifact_service: ArtifactService | None = None,
) -> SpotWeldQualityRun:
    artifact_service = artifact_service or build_artifact_service(db)
    artifact, frame = resolve_dataset_frame(db, artifact_service, project_id, dataset_artifact_id)
    features, schema, statistics = build_feature_frame(frame, field_mapping=field_mapping)
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
        },
        statistics={**statistics, "valid_rows": len(features)},
        rule_set_version="report_v1",
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


def _fit_candidate_model(features: np.ndarray, labels: Iterable[Any], candidate: CandidateResult):
    config = next((item for item in AUTOML_CONFIGS if item["name"] == candidate.name), None)
    if config is None:
        raise QualityPipelineError("QUALITY_AUTOML_CONFIG_INVALID")
    _, encoded = np.unique(np.asarray(list(labels)), return_inverse=True)
    scaler = StandardScaler()
    transformed = scaler.fit_transform(np.asarray(features, dtype=np.float64))
    model = _build_estimator(config)
    model.fit(_estimator_matrix(transformed), encoded)
    return scaler, model


def _generated_artifacts(
    db,
    artifact_service: ArtifactService,
    run: SpotWeldQualityRun,
    features: pd.DataFrame,
    samples: list[SpotWeldQualitySample],
) -> dict[str, str]:
    with tempfile.TemporaryDirectory(prefix="spot-weld-quality-") as directory:
        root = Path(directory)
        feature_path = root / "spot_weld_quality_features.csv"
        result_path = root / "spot_weld_quality_results.json"
        features.to_csv(feature_path, index=False)
        result_path.write_text(json.dumps([
            {
                "sample_id": str(sample.id), "display_id": sample.display_id,
                "automatic_label": sample.automatic_label,
                "defect_probability": sample.defect_probability,
                "warning_level": sample.warning_level,
                "cluster_id": sample.cluster_id,
            }
            for sample in samples
        ], ensure_ascii=False), encoding="utf-8")
        metadata = {"source": "spot_weld_quality", "quality_run_id": str(run.id), "feature_version": "report_v1"}
        features_artifact = artifact_service.create_from_file(
            run.project_id, feature_path, f"spot-weld-{run.id}-features.csv", "quality_features", metadata, commit=False,
        )
        results_artifact = artifact_service.create_from_file(
            run.project_id, result_path, f"spot-weld-{run.id}-results.json", "quality_results", metadata, commit=False,
        )
    return {"features": str(features_artifact.id), "results": str(results_artifact.id)}


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
        thresholds = {
            "energy_dev_abs": 2.5,
            "current_max_diff_p95": float(np.percentile(features["current_max_diff"], 95)),
            "power_std_p95": float(np.percentile(features["power_std"], 95)),
        }
        preliminary = [apply_report_v1_rules(record, thresholds=thresholds) for record in records]
        binary_labels = np.asarray([result.primary_label != "normal" for result in preliminary], dtype=int)
        candidate_results, best_candidate = run_automl(features.to_numpy(dtype=np.float64), binary_labels)
        clustering = run_clustering(
            features.to_numpy(dtype=np.float64),
            feature_names=schema,
            feature_importance=np.asarray(best_candidate.feature_importance, dtype=float),
        )
        final_rules = [
            apply_report_v1_rules(
                record, thresholds=thresholds, cluster_id=clustering.cluster_ids[index], anomaly_cluster=clustering.anomaly_cluster,
            )
            for index, record in enumerate(records)
        ]
        scaler, model = _fit_candidate_model(features.to_numpy(dtype=np.float64), binary_labels, best_candidate)
        probabilities = model.predict_proba(_estimator_matrix(
            scaler.transform(features.to_numpy(dtype=np.float64)),
        ))[:, 1]
        db.query(SpotWeldQualitySample).filter(SpotWeldQualitySample.run_id == run.id).delete(synchronize_session=False)
        db.query(SpotWeldQualityRuleSet).filter(SpotWeldQualityRuleSet.run_id == run.id).delete(synchronize_session=False)
        db.flush()
        db.add(SpotWeldQualityRuleSet(
            project_id=run.project_id, run_id=run.id, version="report_v1", thresholds=thresholds,
        ))
        samples: list[SpotWeldQualitySample] = []
        for index, (record, waveform, rule_result, probability) in enumerate(zip(records, waveforms, final_rules, probabilities)):
            table_values = {
                key: float(canonical.iloc[index][key]) for key in REPORT_TABLE_FIELDS
            }
            sample = SpotWeldQualitySample(
                run_id=run.id,
                source_row_index=index,
                display_id=f"W-{index + 1:04d}",
                table_values=table_values,
                feature_values={key: float(value) for key, value in record.items()},
                waveforms=waveform,
                automatic_label=rule_result.primary_label,
                rule_hits=[item.to_dict() for item in rule_result.hits],
                cluster_id=clustering.cluster_ids[index],
                defect_probability=float(probability),
                warning_level=warning_level(float(probability)),
                review_status="pending_review",
            )
            db.add(sample)
            samples.append(sample)
        db.flush()
        output_artifacts = _generated_artifacts(db, artifact_service, run, features, samples)
        run.status = "completed"
        run.feature_schema = schema
        run.statistics = {**statistics, "valid_rows": len(features), "warning_counts": dict(Counter(sample.warning_level for sample in samples))}
        run.automl_results = [item.to_dict() for item in candidate_results]
        run.clustering_results = clustering.to_dict()
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


def _training_feature_indexes(config: Mapping[str, Any], feature_names: list[str]) -> list[int]:
    if config.get("feature_scope") != "table":
        return list(range(len(feature_names)))
    missing = [name for name in TABLE_FEATURES if name not in feature_names]
    if missing:
        raise QualityPipelineError("QUALITY_TRAINING_FEATURE_SCHEMA_INVALID")
    return [feature_names.index(name) for name in TABLE_FEATURES]


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


def _snapshot_auc(y_true: np.ndarray, probabilities: np.ndarray, class_count: int) -> float:
    if class_count == 2:
        return float(roc_auc_score(y_true, probabilities[:, 1]))
    return float(roc_auc_score(
        y_true,
        probabilities,
        labels=np.arange(class_count),
        multi_class="ovr",
        average="weighted",
    ))


def run_snapshot_training(
    features: np.ndarray,
    labels: np.ndarray,
    feature_names: list[str],
    *,
    configs: tuple[Mapping[str, Any], ...] = SNAPSHOT_TRAINING_CONFIGS,
) -> tuple[list[CandidateResult], CandidateResult, np.ndarray]:
    classes, encoded = np.unique(labels, return_inverse=True)
    counts = np.bincount(encoded)
    if len(classes) < 2 or int(counts.min()) < 5:
        raise QualityPipelineError("QUALITY_LABELS_INSUFFICIENT_FOR_5_FOLD")
    splitter = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    results: list[CandidateResult] = []
    for config_index, config in enumerate(configs):
        result = CandidateResult(
            name=str(config["name"]),
            model_type=str(config["type"]),
            config_index=config_index,
            params={**dict(config.get("params", {})), "feature_scope": str(config.get("feature_scope", "fusion"))},
        )
        started = time.perf_counter()
        aucs: list[float] = []
        f1s: list[float] = []
        importances: list[np.ndarray] = []
        try:
            indexes = _training_feature_indexes(config, feature_names)
            for train_index, test_index in splitter.split(features, encoded):
                scaler = StandardScaler()
                train = scaler.fit_transform(features[train_index][:, indexes])
                test = scaler.transform(features[test_index][:, indexes])
                model = _build_estimator(config)
                model.fit(_estimator_matrix(train), encoded[train_index])
                probabilities = model.predict_proba(_estimator_matrix(test))
                predictions = model.predict(_estimator_matrix(test))
                aucs.append(_snapshot_auc(encoded[test_index], probabilities, len(classes)))
                f1s.append(float(f1_score(encoded[test_index], predictions, average="weighted", zero_division=0)))
                expanded = np.zeros(len(feature_names), dtype=float)
                expanded[indexes] = _feature_importance(model, len(indexes))
                importances.append(expanded)
            result.auc = float(np.mean(aucs))
            result.f1 = float(np.mean(f1s))
            result.auc_std = float(np.std(aucs))
            result.f1_std = float(np.std(f1s))
            result.feature_importance = np.mean(importances, axis=0).tolist()
        except QualityPipelineError as error:
            result.error_code = error.code
            result.error_message = str(error)
        except Exception as error:
            result.error_code = "QUALITY_SNAPSHOT_TRAINING_CANDIDATE_FAILED"
            result.error_message = str(error)
        result.training_time_seconds = time.perf_counter() - started
        results.append(result)
    return results, select_best_candidate(results), classes


def _fit_snapshot_model(
    features: np.ndarray,
    labels: np.ndarray,
    feature_names: list[str],
    best_candidate: CandidateResult,
) -> tuple[Any, StandardScaler, np.ndarray, list[int]]:
    config = next((item for item in SNAPSHOT_TRAINING_CONFIGS if item["name"] == best_candidate.name), None)
    if config is None:
        raise QualityPipelineError("QUALITY_AUTOML_CONFIG_INVALID")
    _, encoded = np.unique(labels, return_inverse=True)
    indexes = _training_feature_indexes(config, feature_names)
    scaler = StandardScaler()
    transformed = scaler.fit_transform(features[:, indexes])
    model = _build_estimator(config)
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
    summary = pd.DataFrame([
        {"指标": "质量运行", "值": str(run.id)},
        {"指标": "标签快照", "值": str(snapshot.id)},
        {"指标": "特征版本", "值": "report_v1"},
        {"指标": "已审核样本", "值": len(snapshot_samples)},
        {"指标": "全量样本", "值": len(all_samples)},
        {"指标": "最优模型", "值": next((item.name for item in candidates if item.error_code is None and item.auc == max((candidate.auc or -1) for candidate in candidates)), "-")},
    ])
    automl = pd.DataFrame([item.to_dict() for item in candidates])
    deep_learning = automl.loc[:, [column for column in ("name", "model_type", "auc", "auc_std", "f1", "f1_std", "training_time_seconds", "error_code") if column in automl.columns]]
    labels_frame = pd.DataFrame([
        {
            "sample_id": str(sample.id),
            "display_id": sample.display_id,
            "label": label,
            "review_status": sample.review_status,
            "revision_id": next((item.get("revision_id") for item in (snapshot.labels or []) if item.get("sample_id") == str(sample.id)), None),
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
    """Train only from immutable approved-label snapshots and generated feature data."""
    snapshot = _snapshot_or_error(db, snapshot_id)
    run = db.query(SpotWeldQualityRun).filter(
        SpotWeldQualityRun.id == snapshot.run_id,
        SpotWeldQualityRun.project_id == snapshot.project_id,
    ).first()
    if run is None:
        raise QualityPipelineError("QUALITY_RUN_NOT_FOUND")
    artifact_service = artifact_service or build_artifact_service(db)
    features, labels, feature_names, snapshot_samples = _snapshot_training_data(db, snapshot, run)
    candidates, best_candidate, classes = run_snapshot_training(features, labels, feature_names)
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
        "feature_version": "report_v1",
        "rule_set_version": run.rule_set_version,
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
        }, model_path)
        schema_path.write_text(json.dumps({
            "feature_schema": selected_feature_names,
            "classes": classes.tolist(),
            "metrics": best_metrics,
            "feature_importance": feature_importance,
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
        backbone=best_candidate.name,
        description="基于已审核点焊标签快照的质量感知模型",
        metrics=best_metrics,
        params={
            "source": "spot_weld_quality",
            "quality_run_id": str(run.id),
            "label_snapshot_id": str(snapshot.id),
            "feature_version": "report_v1",
            "rule_set_version": run.rule_set_version,
            "schema_artifact_id": str(schema_artifact.id),
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
