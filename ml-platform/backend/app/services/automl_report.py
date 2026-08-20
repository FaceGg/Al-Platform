"""Generate project-scoped AutoML analysis reports."""

from __future__ import annotations

import io
import json
import tempfile
import zipfile
from pathlib import Path

import joblib
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from openpyxl.drawing.image import Image as ExcelImage
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from sklearn.inspection import permutation_importance
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler
from sqlalchemy.orm import Session

from app.models.training import TrainingJob
from app.services.artifact_service import ArtifactService
from app.services.automl_execution import read_automl_dataset, resolve_automl_feature_columns


REPORT_FILES = (
    "AutoML全流程报告.xlsx",
    "automl_results.csv",
    "automl_comparison.png",
    "feature_importance_automl.png",
    "clustering_automl.png",
)

REPORT_RESULT_COLUMNS = [
    "name",
    "algorithm_id",
    "AUC",
    "F1",
    "Accuracy",
    "best_params",
    "training_time_seconds",
    "status",
    "model_library_id",
]


def _report_results(raw_results) -> list[dict]:
    """Normalize legacy AutoML rows into the report's stable metric columns."""
    normalized = []
    for item in raw_results or []:
        if not isinstance(item, dict):
            continue
        normalized.append({
            "name": item.get("name") or item.get("model") or item.get("algorithm"),
            "algorithm_id": item.get("algorithm_id"),
            "AUC": item.get("AUC", item.get("auc", item.get("roc_auc"))),
            "F1": item.get("F1", item.get("f1", item.get("f1_weighted"))),
            "Accuracy": item.get("Accuracy", item.get("accuracy", item.get("score"))),
            "best_params": item.get("best_params") or item.get("params") or {},
            "training_time_seconds": item.get("training_time_seconds"),
            "status": item.get("status"),
            "model_library_id": item.get("model_library_id"),
        })
    return normalized


class AutoMLReportError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _json(value):
    if isinstance(value, dict):
        return {str(k): _json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json(item) for item in value]
    if isinstance(value, (np.integer, np.floating)):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    return value


def _tabular(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.map(
        lambda value: json.dumps(_json(value), ensure_ascii=False, sort_keys=True)
        if isinstance(value, (dict, list, tuple, np.ndarray))
        else _json(value),
    )


def _importance(model, features: pd.DataFrame, target: pd.Series, task: str):
    names = [str(column) for column in features.columns]
    values = getattr(model, "feature_importances_", None)
    if values is None and hasattr(model, "coef_"):
        coefficients = np.abs(np.asarray(model.coef_))
        values = coefficients.mean(axis=0) if coefficients.ndim > 1 else coefficients
    if values is None:
        try:
            scoring = "accuracy" if task == "classification" else "r2"
            result = permutation_importance(model, features, target, n_repeats=5, random_state=42, scoring=scoring)
            values = result.importances_mean
        except Exception as error:
            raise AutoMLReportError("AUTOML_REPORT_SOURCE_UNAVAILABLE", "无法计算最佳模型特征重要性") from error
    values = np.asarray(values, dtype=float).reshape(-1)
    if len(values) != len(names):
        raise AutoMLReportError("AUTOML_REPORT_SOURCE_UNAVAILABLE", "最佳模型特征维度与数据集不一致")
    values = np.nan_to_num(np.abs(values), nan=0.0, posinf=0.0, neginf=0.0)
    if float(values.sum()) <= 0:
        values = np.ones(len(names), dtype=float)
    weights = values / values.sum()
    return names, values, weights


def _cluster(features: pd.DataFrame, weights: np.ndarray):
    scaled = StandardScaler().fit_transform(features)
    weighted = scaled * np.sqrt(weights)
    scores = {}
    max_k = min(8, len(features) - 1)
    for k in range(2, max_k + 1):
        labels = KMeans(n_clusters=k, random_state=42, n_init=10).fit_predict(weighted)
        if len(np.unique(labels)) > 1:
            scores[str(k)] = float(silhouette_score(weighted, labels))
    best_k = max(scores, key=lambda key: (scores[key], -int(key))) if scores else None
    labels = KMeans(n_clusters=int(best_k), random_state=42, n_init=10).fit_predict(weighted) if best_k else np.zeros(len(features), dtype=int)
    coordinates = (
        PCA(n_components=2, random_state=42).fit_transform(weighted)
        if weighted.shape[1] >= 2
        else np.column_stack([weighted[:, 0], np.zeros(len(weighted))])
    )
    counts = {str(int(key)): int(value) for key, value in zip(*np.unique(labels, return_counts=True))}
    return {"scores": scores, "best_k": int(best_k) if best_k else None, "silhouette": scores.get(best_k) if best_k else None, "counts": counts, "labels": labels, "coordinates": coordinates}


def _chart_bytes(kind: str, data: dict, names: list[str], values: np.ndarray, rows: list[dict]) -> bytes:
    figure, axis = plt.subplots(figsize=(8, 4.5), dpi=140)
    if kind == "comparison":
        labels = [str(item.get("name", item.get("algorithm_id", "-"))) for item in rows]
        positions = np.arange(len(labels))
        width = 0.25
        for offset, metric_name, legend_name, color in [(-width, "AUC", "AUC", "#1677ff"), (0, "F1", "F1", "#13c2c2"), (width, "Accuracy", "ACC", "#722ed1")]:
            scores = [float(item[metric_name]) if item.get(metric_name) is not None else 0 for item in rows]
            axis.bar(positions + offset, scores, width=width, label=legend_name, color=color)
        axis.set_xticks(positions, labels)
        axis.set_ylabel("AUC / F1 / ACC")
        axis.set_ylim(0, 1)
        axis.legend()
        axis.tick_params(axis="x", rotation=35)
    elif kind == "importance":
        order = np.argsort(values)[-20:][::-1]
        axis.barh([names[i] for i in order][::-1], values[order][::-1], color="#13c2c2")
        axis.set_xlabel("Importance")
    else:
        coordinates = data["coordinates"]
        labels = data["labels"]
        axis.scatter(coordinates[:, 0], coordinates[:, 1], c=labels, cmap="viridis", s=22)
        axis.set_title(f"Weighted KMeans (K={data['best_k'] or '-'}, silhouette={data['silhouette'] or 0:.4f})")
    figure.tight_layout()
    output = io.BytesIO(); figure.savefig(output, format="png"); plt.close(figure)
    return output.getvalue()


def generate_automl_report(
    db: Session,
    job: TrainingJob,
    artifact_service: ArtifactService,
    *,
    regenerate: bool = False,
) -> dict:
    if job.operator_id != "automl" or job.status != "completed":
        raise AutoMLReportError("AUTOML_REPORT_NOT_READY", "仅已完成的自动建模任务可以生成报告")
    metrics = dict(job.metrics or {})
    source = {
        "report_version": 3,
        "job_id": str(job.id),
        "model_artifact_id": str(job.model_artifact_id),
        "dataset_artifact_id": str(job.dataset_artifact_id),
        "best_model": metrics.get("best_model"),
        "results": metrics.get("all_results") or metrics.get("algorithm_results"),
    }
    fingerprint = json.dumps(_json(source), sort_keys=True, ensure_ascii=False)
    existing = metrics.get("automl_report")
    if not regenerate and existing and existing.get("fingerprint") == fingerprint:
        try:
            for artifact_id in (existing.get("artifacts") or {}).values():
                artifact_service.resolve(artifact_id, job.project_id, expected_type="report")
            return existing
        except Exception:
            pass
    if not job.model_artifact_id or not job.dataset_artifact_id:
        raise AutoMLReportError("AUTOML_REPORT_SOURCE_UNAVAILABLE", "任务缺少模型或数据集制品")
    params = dict(job.params or {})
    with artifact_service.materialize(job.dataset_artifact_id, job.project_id, expected_type="dataset") as dataset_path:
        frame = read_automl_dataset(dataset_path)
    target_column = params.get("target_column")
    feature_columns = resolve_automl_feature_columns(frame, target_column, params.get("input_columns"))
    prepared = frame.dropna(subset=[target_column, *feature_columns])
    features = prepared.loc[:, feature_columns]
    target = prepared[target_column]
    with artifact_service.materialize(job.model_artifact_id, job.project_id, expected_type="model") as model_path:
        payload = joblib.load(model_path)
    model = payload.get("model", payload) if isinstance(payload, dict) else payload
    target_schema = payload.get("target_schema", {}) if isinstance(payload, dict) else {}
    task = str(target_schema.get("task") or params.get("task", "classification"))
    if task == "classification":
        classes = [str(value) for value in (target_schema.get("classes") or [])]
        class_index = {value: index for index, value in enumerate(classes)}
        target_for_model = target.astype(str).map(class_index) if classes else target
    else:
        target_for_model = target
    names, importances, weights = _importance(model, features, target_for_model, task)
    clusters = _cluster(features, weights)
    prediction = model.predict(features)
    if task == "classification" and classes:
        display_prediction = [classes[int(value)] if 0 <= int(value) < len(classes) else str(value) for value in prediction]
    else:
        display_prediction = prediction
    inference = pd.DataFrame({target_column: target.astype(str) if task == "classification" else target, "predicted": display_prediction})
    if task == "classification" and hasattr(model, "predict_proba"):
        probabilities = np.asarray(model.predict_proba(features))
        inference["confidence"] = probabilities.max(axis=1)
    if task == "regression": inference["residual"] = inference[target_column] - inference["predicted"]
    results = _report_results(metrics.get("all_results") or metrics.get("algorithm_results"))
    importance_rows = [{"feature": name, "importance": float(value), "weight": float(weight)} for name, value, weight in zip(names, importances, weights)]
    importance_rows.sort(key=lambda row: row["importance"], reverse=True)
    preview = {"overview": {"project": job.project.name if job.project else None, "experiment": job.experiment.name if job.experiment else None, "task": job.name, "rows": len(prepared), "features": len(names), "best_model": metrics.get("best_model") or metrics.get("best_candidate"), "best_k": clusters["best_k"], "silhouette": clusters["silhouette"]}, "selection": results, "clustering": {k: v for k, v in clusters.items() if k not in {"labels", "coordinates"}}, "importance": importance_rows[:20], "inference": _json(inference.head(100).to_dict(orient="records")), "inference_total": len(inference)}
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        comparison = _chart_bytes("comparison", clusters, names, importances, results)
        importance_png = _chart_bytes("importance", clusters, names, importances, results)
        cluster_png = _chart_bytes("cluster", clusters, names, importances, results)
        (root / "automl_comparison.png").write_bytes(comparison)
        (root / "feature_importance_automl.png").write_bytes(importance_png)
        (root / "clustering_automl.png").write_bytes(cluster_png)
        selection_frame = _tabular(pd.DataFrame(results, columns=REPORT_RESULT_COLUMNS))
        selection_frame.to_csv(root / "automl_results.csv", index=False, encoding="utf-8-sig")
        sheets = {"总览": _tabular(pd.DataFrame([preview["overview"]])), "AutoML选型": selection_frame, "聚类画像": _tabular(pd.DataFrame([preview["clustering"]])), "特征重要性": _tabular(pd.DataFrame(importance_rows)), "推理结果": _tabular(inference)}
        with pd.ExcelWriter(root / "AutoML全流程报告.xlsx", engine="openpyxl") as writer:
            for sheet_name, data in sheets.items(): data.to_excel(writer, sheet_name=sheet_name, index=False)
            workbook = writer.book
            for sheet_name, image_name in [("总览", "automl_comparison.png"), ("特征重要性", "feature_importance_automl.png"), ("聚类画像", "clustering_automl.png")]:
                worksheet = workbook[sheet_name]
                image_row = worksheet.max_row + 2
                worksheet.add_image(ExcelImage(str(root / image_name)), f"A{image_row}")
        zip_path = root / "automl-report.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
            for name in REPORT_FILES: archive.write(root / name, name)
        artifact_ids = {}
        for name in REPORT_FILES + ("automl-report.zip",):
            artifact = artifact_service.create_from_file(job.project_id, root / ("automl-report.zip" if name == "automl-report.zip" else name), name, "report", metadata={"source": "automl_report", "training_job_id": str(job.id)})
            artifact_ids[name] = str(artifact.id)
    manifest = {"fingerprint": fingerprint, "artifacts": artifact_ids, "preview": preview}
    job.metrics = {**metrics, "automl_report": manifest}
    db.commit()
    return manifest
