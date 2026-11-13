"""M6 半监督精调档 1（技术方案 §6.2）：标签阈值重标定 + 误报形态分析报表。

档 1 的语义（方案定稿）：**只动阈值，不动特征表示与检测器主体**——
confirmed_fault（确认故障）与 false_alarm（误报）两组回流分数分布，
按「漏报罚 2×误报」的加权损失求最优阈值，替换 ThresholdPolicy.persisted。
阈值在推理侧应用（anomaly_threshold_for_version / enrich），ONNX 零重训。

前置门槛（§6.2，不满足则调用方自动顺延）：
- confirmed_fault ≥ 50 条
- 覆盖 ≥ 2 种异常形态（confirmed 特征空间 KMeans 两簇均可分，簇内样本 ≥10）

附加产出（§6.2）：**误报形态分析报表**——false_alarm 样本在特征空间的
KMeans 聚类画像（哪些参数区域误报密集），反哺用户调 contamination/特征
工程（人机协同闭环）。
"""

from __future__ import annotations

import json
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd


# §6.2 前置门槛
MIN_CONFIRMED_SAMPLES = 50
MIN_MORPHOLOGY_SAMPLES_PER_CLUSTER = 10
# 漏报权重（方案定稿：漏报罚 2×误报）
FALSE_NEGATIVE_WEIGHT = 2.0


def optimal_threshold_from_labels(
    confirmed_scores: np.ndarray,
    false_alarm_scores: np.ndarray,
) -> dict:
    """标签阈值重标定核心（纯函数）：加权损失最小化求最优阈值。

    loss(t) = 2 × FNR(t) + 1 × FPR(t)
      - FNR(t)：confirmed 中 score < t 的占比（阈值过高把真故障漏掉）
      - FPR(t)：false_alarm 中 score ≥ t 的占比（阈值过低把误报放行）

    候选阈值 = 两组分数的并集分位网格（201 点）+ 数据边界，扫描取 argmin。
    返回 dict：threshold / loss / fnr / fpr / confirmed_count /
    false_alarm_count（数据不足各返回 None 由调用方走门槛顺延）。
    """
    confirmed = np.asarray(confirmed_scores, dtype=float)
    false_alarm = np.asarray(false_alarm_scores, dtype=float)
    confirmed = confirmed[np.isfinite(confirmed)]
    false_alarm = false_alarm[np.isfinite(false_alarm)]
    if confirmed.size == 0 or false_alarm.size == 0:
        return {
            "threshold": None, "loss": None, "fnr": None, "fpr": None,
            "confirmed_count": int(confirmed.size),
            "false_alarm_count": int(false_alarm.size),
        }
    candidates = np.unique(np.concatenate([
        np.quantile(confirmed, np.linspace(0.0, 1.0, 201)),
        np.quantile(false_alarm, np.linspace(0.0, 1.0, 201)),
        [float(confirmed.min()), float(confirmed.max() + 1e-9)],
    ]))
    best_threshold = None
    best_loss = None
    for threshold in candidates:
        fnr = float(np.mean(confirmed < threshold))
        fpr = float(np.mean(false_alarm >= threshold))
        loss = FALSE_NEGATIVE_WEIGHT * fnr + fpr
        if best_loss is None or loss < best_loss:
            best_loss = loss
            best_threshold = float(threshold)
    threshold = float(best_threshold)
    fnr = float(np.mean(confirmed < threshold))
    fpr = float(np.mean(false_alarm >= threshold))
    return {
        "threshold": threshold,
        "loss": round(float(best_loss), 6),
        "fnr": round(fnr, 4),
        "fpr": round(fpr, 4),
        "confirmed_count": int(confirmed.size),
        "false_alarm_count": int(false_alarm.size),
    }


def meets_m6_gate(confirmed_count: int, morphology_cluster_count: int | None) -> dict:
    """§6.2 前置门槛判定：confirmed ≥50 且形态 ≥2（聚类粗分簇数）。"""
    enough_samples = confirmed_count >= MIN_CONFIRMED_SAMPLES
    enough_morphology = morphology_cluster_count is None or morphology_cluster_count >= 2
    return {
        "unlocked": bool(enough_samples and enough_morphology),
        "confirmed_count": confirmed_count,
        "min_confirmed_required": MIN_CONFIRMED_SAMPLES,
        "morphology_cluster_count": morphology_cluster_count,
    }


def confirmed_morphology_clusters(
    confirmed_features: np.ndarray,
    *,
    max_clusters: int = 4,
    min_cluster_samples: int = MIN_MORPHOLOGY_SAMPLES_PER_CLUSTER,
    random_seed: int = 42,
) -> dict:
    """confirmed 样本的形态粗分（§6.2「标签库按形态聚类」）：KMeans k 从
    2..max_clusters 选簇间分离最优者；返回 cluster_count 与各簇样本数。
    特征需先标准化（调用方用部署版本的 scaler 语义或 StandardScaler）。
    样本过少/退化时 cluster_count=1（门槛不过，顺延）。"""
    matrix = np.asarray(confirmed_features, dtype=float)
    if matrix.ndim != 2 or matrix.shape[0] < min_cluster_samples * 2:
        return {"cluster_count": 1, "cluster_sizes": []}
    from sklearn.cluster import KMeans
    from sklearn.preprocessing import StandardScaler

    scaled = StandardScaler().fit_transform(matrix)
    best = None
    for k in range(2, max_clusters + 1):
        try:
            labels = KMeans(n_clusters=k, n_init=10, random_state=random_seed).fit_predict(scaled)
        except Exception:  # noqa: BLE001 - 退化输入跳过该 k
            continue
        sizes = sorted(int(np.sum(labels == label)) for label in np.unique(labels))
        if min(sizes) < min_cluster_samples:
            continue
        # 选取依据：簇内平方和最小（肘部简化——不做 silhouette 以控成本）
        inertia = float(
            KMeans(n_clusters=k, n_init=10, random_state=random_seed)
            .fit(scaled).inertia_
        )
        if best is None or inertia < best["inertia"]:
            best = {"cluster_count": k, "cluster_sizes": sizes, "inertia": inertia}
    if best is None:
        return {"cluster_count": 1, "cluster_sizes": []}
    return {
        "cluster_count": int(best["cluster_count"]),
        "cluster_sizes": best["cluster_sizes"],
    }


def false_alarm_morphology_report(
    false_alarm_features: np.ndarray,
    feature_names: list[str],
    *,
    max_clusters: int = 4,
    random_seed: int = 42,
) -> dict:
    """误报形态分析报表（§6.2 附加产出）：false_alarm 样本在特征空间的
    KMeans 聚类画像——各簇的特征均值画像（哪些参数区域误报密集），反哺
    contamination/特征工程调整（人机协同闭环）。"""
    matrix = np.asarray(false_alarm_features, dtype=float)
    if matrix.ndim != 2 or matrix.shape[0] < 4:
        return {"clusters": [], "sample_count": int(matrix.shape[0]) if matrix.ndim == 2 else 0}
    from sklearn.cluster import KMeans
    from sklearn.preprocessing import StandardScaler

    scaled = StandardScaler().fit_transform(matrix)
    best = None
    for k in range(2, max_clusters + 1):
        if matrix.shape[0] < k:
            continue
        clusterer = KMeans(n_clusters=k, n_init=10, random_state=random_seed)
        labels = clusterer.fit_predict(scaled)
        sizes = [int(np.sum(labels == label)) for label in np.unique(labels)]
        if min(sizes) < 2:
            continue
        inertia = float(clusterer.inertia_)
        if best is None or inertia < best["_inertia"]:
            best = {"_inertia": inertia, "k": k, "labels": labels, "sizes": sizes}
    if best is None:
        return {"clusters": [], "sample_count": int(matrix.shape[0])}
    names = list(feature_names)
    clusters = []
    for cluster_index in range(best["k"]):
        member = matrix[best["labels"] == cluster_index]
        clusters.append({
            "cluster": cluster_index,
            "sample_count": int(best["sizes"][cluster_index]),
            # 误报密集特征：簇均值最高的特征（标准化后 z 值）——「哪些参数
            # 区域误报密集」的直接画像
            "dense_features": [
                {"feature": names[index] if index < len(names) else f"f{index}",
                 "mean_z": round(float(member[:, index].mean()), 4)}
                for index in np.argsort(-member.mean(axis=0))[:3]
            ],
        })
    return {"clusters": clusters, "sample_count": int(matrix.shape[0])}


class ThresholdRecalibrationError(RuntimeError):
    def __init__(self, code: str, message: str | None = None):
        self.code = code
        self.detail_message = message or code
        super().__init__(self.detail_message)


def _as_actor_uuid(value):
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        return None


def _old_threshold_of(db, service, source_version) -> float | None:
    """源版本当前阈值（分片指针优先），用于新旧对比证据。"""
    from app.models.artifact import Artifact as _Artifact

    metadata = source_version.conversion_metadata if isinstance(source_version.conversion_metadata, dict) else {}
    stats_id = str(metadata.get("anomaly_score_stats_artifact_id") or "").strip()
    if stats_id:
        artifact = db.query(_Artifact).filter(
            _Artifact.id == uuid.UUID(stats_id),
        ).first()
        if artifact is not None:
            with service.materialize(
                artifact.id, artifact.project_id, expected_type="report",
            ) as path:
                return float(json.loads(Path(path).read_text(encoding="utf-8")).get("threshold_score"))
    return None


def label_recalibrate_version(
    db,
    *,
    source_version_id,
    labeled_artifact_id,
    actor_id,
    feedback_marks: dict | None = None,
    commit: bool = True,
) -> dict:
    """M6 半监督档 1 服务层（技术方案 §6.2）：标签阈值重标定并注册新版本。

    与三期 M9（anomaly_device_calibration）同骨架、不同标定目标——M9 用
    contamination 分位（无监督），本函数用 **confirmed/false_alarm 标签的
    加权损失最优阈值**（弱监督档 1）。前置门槛不满足抛
    M6_GATE_NOT_UNLOCKED（调用方自动顺延，方案 §6.2）。

    产物与 M9 同形态：新 score_stats artifact（threshold_score 替换为标签
    最优阈值，label_recalibration 元数据含误报形态报表）+ 迁移形态新版本
    （同源 artifact + 分片阈值指针指向新 stats）——阈值在推理侧生效，
    ONNX 零重训。
    """
    from app.models.artifact import Artifact
    from app.models.model_registry import (
        ModelVersion,
        RegisteredModel,
    )

    try:
        source_uuid = uuid.UUID(str(source_version_id))
    except (TypeError, ValueError, AttributeError):
        raise ThresholdRecalibrationError("MODEL_VERSION_NOT_FOUND") from None
    source_version = db.query(ModelVersion).filter(
        ModelVersion.id == source_uuid,
    ).first()
    if source_version is None or source_version.source_artifact_id is None:
        raise ThresholdRecalibrationError("MODEL_VERSION_NOT_FOUND")
    output_schema = source_version.output_schema if isinstance(source_version.output_schema, dict) else {}
    if output_schema.get("task") != "anomaly":
        raise ThresholdRecalibrationError("RECALIBRATE_REQUIRES_ANOMALY_VERSION")

    service = build_service(db)
    try:
        labeled_uuid = uuid.UUID(str(labeled_artifact_id))
    except (TypeError, ValueError, AttributeError):
        raise ThresholdRecalibrationError("LABELED_DATASET_NOT_FOUND") from None
    labeled_artifact = db.query(Artifact).filter(
        Artifact.id == labeled_uuid,
    ).first()
    if labeled_artifact is None:
        raise ThresholdRecalibrationError("LABELED_DATASET_NOT_FOUND")

    from app.services.closed_loop_actions import apply_feedback_marks

    with service.materialize(
        labeled_artifact.id, labeled_artifact.project_id, expected_type="dataset",
    ) as path:
        frame = apply_feedback_marks(pd.read_csv(path), feedback_marks)
    feedback_series = frame["feedback"].fillna("").astype(str).str.strip()
    confirmed_frame = frame[feedback_series == "confirmed_fault"]
    false_alarm_frame = frame[feedback_series == "false_alarm"]

    feature_names = [
        str(item.get("name"))
        for item in (source_version.feature_schema or [])
        if isinstance(item, dict) and item.get("name")
    ]
    confirmed_features = (
        confirmed_frame.reindex(columns=feature_names).dropna().to_numpy(dtype=float)
        if feature_names else np.empty((0, 0))
    )
    morphology = confirmed_morphology_clusters(confirmed_features)
    gate = meets_m6_gate(len(confirmed_frame), morphology.get("cluster_count"))
    if not gate["unlocked"]:
        raise ThresholdRecalibrationError(
            "M6_GATE_NOT_UNLOCKED",
            f"档 1 前置门槛未达：confirmed {gate['confirmed_count']}/50、"
            f"形态簇 {gate['morphology_cluster_count']}/2（§6.2 自动顺延）",
        )

    confirmed_scores = _scores_of(confirmed_frame)
    false_alarm_scores = _scores_of(false_alarm_frame)
    if confirmed_scores.size == 0 or false_alarm_scores.size == 0:
        # 回流行缺分数列：用源模型对标签行补打分（检测器主体不动，档 1 语义）
        with service.materialize(
            source_version.source_artifact_id,
            source_version.registered_model.project_id,
            expected_type="model",
        ) as model_path:
            import joblib

            bundle = joblib.load(model_path)
        model = bundle.get("model")
        if model is None:
            raise ThresholdRecalibrationError("MODEL_BUNDLE_INVALID")
        from app.services.automl_anomaly import pipeline_anomaly_scores

        if confirmed_scores.size == 0:
            matrix = confirmed_frame.reindex(columns=feature_names).dropna().to_numpy(dtype=float)
            confirmed_scores = pipeline_anomaly_scores(model, matrix)
        if false_alarm_scores.size == 0:
            matrix = false_alarm_frame.reindex(columns=feature_names).dropna().to_numpy(dtype=float)
            false_alarm_scores = pipeline_anomaly_scores(model, matrix)

    recalibrated = optimal_threshold_from_labels(confirmed_scores, false_alarm_scores)
    if recalibrated.get("threshold") is None:
        raise ThresholdRecalibrationError("RECALIBRATION_INSUFFICIENT_DATA")
    report = false_alarm_morphology_report(
        false_alarm_frame.reindex(columns=feature_names).dropna().to_numpy(dtype=float),
        feature_names,
    )

    model_name = f"{source_version.registered_model.name}-label-recal"[:128]
    registered_model = db.query(RegisteredModel).filter(
        RegisteredModel.project_id == source_version.registered_model.project_id,
        RegisteredModel.name == model_name,
    ).first()
    if registered_model is None:
        registered_model = RegisteredModel(
            project_id=source_version.registered_model.project_id,
            name=model_name,
            description=f"半监督档 1 阈值重标定版本（源 {source_version.registered_model.name}）",
            created_by_id=_as_actor_uuid(actor_id),
        )
        db.add(registered_model)
        db.flush()
    old_threshold = _old_threshold_of(db, service, source_version)
    stats_payload = {
        "kind": "anomaly_score_stats",
        "label_recalibration": {
            "source_version_id": str(source_version.id),
            "labeled_artifact_id": str(labeled_artifact.id),
            "recalibrated_at": datetime.now(timezone.utc).isoformat(),
            "gate": gate,
            "morphology": morphology,
            "false_alarm_report": report,
            "old_threshold": old_threshold,
        },
        "threshold_score": recalibrated["threshold"],
        "calibration": {
            "probabilities": [],
            "quantile_points": [],
            "label_optimal": True,
        },
        "threshold_policy": {
            "threshold_score": recalibrated["threshold"],
            "calibrated_threshold": recalibrated["threshold"],
            "persisted": True,
            "source": "m6_label_recalibration",
        },
    }
    addon_dir = Path(tempfile.gettempdir()) / "m6_label_recalibration"
    addon_dir.mkdir(parents=True, exist_ok=True)
    stats_path = addon_dir / f"{uuid.uuid4().hex}-score_stats.json"
    stats_path.write_text(json.dumps(stats_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    stats_artifact = service.create_from_file(
        source_version.registered_model.project_id,
        stats_path,
        f"{registered_model.name}-score_stats.json",
        "report",
        metadata={
            "source": "automl",
            "kind": "anomaly_score_stats",
            "recalibration_for": str(source_version.id),
            "label_recalibration": True,
        },
    )
    stats_path.unlink(missing_ok=True)
    next_number = 1 + (
        db.query(ModelVersion.registered_model_id).filter(
            ModelVersion.registered_model_id == registered_model.id,
        ).count()
    )
    device_version = ModelVersion(
        registered_model_id=registered_model.id,
        version_number=next_number,
        # source_kind/library 组合跟随源版本（CHECK 约束，同 M9 经验）
        source_kind=source_version.source_kind,
        source_model_library_id=source_version.source_model_library_id,
        source_artifact_id=source_version.source_artifact_id,
        onnx_artifact_id=source_version.onnx_artifact_id,
        framework=source_version.framework,
        algorithm=source_version.algorithm,
        feature_schema=source_version.feature_schema,
        output_schema=source_version.output_schema,
        metrics={"label_recalibration": {
            "old_threshold": old_threshold,
            "new_threshold": recalibrated["threshold"],
            "loss": recalibrated["loss"],
            "fnr": recalibrated["fnr"],
            "fpr": recalibrated["fpr"],
            "confirmed_count": recalibrated["confirmed_count"],
            "false_alarm_count": recalibrated["false_alarm_count"],
            "false_alarm_report": report,
        }},
        conversion_metadata={
            **(source_version.conversion_metadata or {}),
            "anomaly_score_stats_artifact_id": str(stats_artifact.id),
            "label_recalibration": True,
            "m6_recalibration": True,
        },
        approval_status="pending",
        created_by_id=_as_actor_uuid(actor_id),
    )
    db.add(device_version)
    db.flush()
    if commit:
        db.commit()
        db.refresh(device_version)
    else:
        db.flush()
    return {
        "version_id": str(device_version.id),
        "registered_model_id": str(registered_model.id),
        "registered_model_name": registered_model.name,
        "stats_artifact_id": str(stats_artifact.id),
        "old_threshold": old_threshold,
        "new_threshold": recalibrated["threshold"],
        "loss": recalibrated["loss"],
        "fnr": recalibrated["fnr"],
        "fpr": recalibrated["fpr"],
        "gate": gate,
        "false_alarm_report": report,
        "confirmed_count": recalibrated["confirmed_count"],
        "false_alarm_count": recalibrated["false_alarm_count"],
    }


def build_service(db):
    from app.services.artifact_service import build_artifact_service

    return build_artifact_service(db)


def _scores_of(frame) -> np.ndarray:
    """回流行 anomaly_score 列（推理时写下的分数）；缺失返回空数组。"""
    if "anomaly_score" not in frame.columns:
        return np.array([])
    import pandas as _pd

    return _pd.to_numeric(frame["anomaly_score"], errors="coerce").dropna().to_numpy(dtype=float)


def export_labeled_reflow_dataset(
    db,
    *,
    source_version_id,
    labeled_artifact_id,
    actor_id,
    dataset_name: str | None = None,
    positive_label: str = "fault",
    commit: bool = True,
) -> dict:
    """弱监督演进派生导出（技术方案 §2.3.3）：回流行带标签导出为监督数据集。

    confirmed_fault → 1（正类），false_alarm 与未标注正常回流 → 0（负类），
    特征列对齐部署版本 feature_schema（预填特征）；产物为标准 dataset
    artifact——现场可直接用它创建监督分类任务（并存对比、达标切换部署，
    保留无监督模型回退能力）。无标注行（feedback 空）的行被剔除。
    """
    from app.models.artifact import Artifact
    from app.models.model_registry import ModelVersion

    try:
        source_uuid = uuid.UUID(str(source_version_id))
    except (TypeError, ValueError, AttributeError):
        raise ThresholdRecalibrationError("MODEL_VERSION_NOT_FOUND") from None
    source_version = db.query(ModelVersion).filter(
        ModelVersion.id == source_uuid,
    ).first()
    if source_version is None:
        raise ThresholdRecalibrationError("MODEL_VERSION_NOT_FOUND")
    feature_names = [
        str(item.get("name"))
        for item in (source_version.feature_schema or [])
        if isinstance(item, dict) and item.get("name")
    ]
    if not feature_names:
        raise ThresholdRecalibrationError("MODEL_FEATURE_COLUMNS_MISSING")
    try:
        labeled_uuid = uuid.UUID(str(labeled_artifact_id))
    except (TypeError, ValueError, AttributeError):
        raise ThresholdRecalibrationError("LABELED_DATASET_NOT_FOUND") from None
    labeled_artifact = db.query(Artifact).filter(
        Artifact.id == labeled_uuid,
    ).first()
    if labeled_artifact is None:
        raise ThresholdRecalibrationError("LABELED_DATASET_NOT_FOUND")

    from app.services.closed_loop_actions import apply_feedback_marks
    from app.services.artifact_service import build_artifact_service

    service = build_artifact_service(db)
    with service.materialize(
        labeled_artifact.id, labeled_artifact.project_id, expected_type="dataset",
    ) as path:
        frame = apply_feedback_marks(pd.read_csv(path), None)
    feedback = frame["feedback"].fillna("").astype(str).str.strip()
    labeled = frame[feedback.isin({"confirmed_fault", "false_alarm"})].copy()
    if labeled.empty:
        raise ThresholdRecalibrationError("NO_LABELED_ROWS")
    labeled[positive_label] = (feedback.loc[labeled.index] == "confirmed_fault").astype(int)
    export_frame = labeled.reindex(columns=feature_names + [positive_label]).dropna()
    if export_frame.empty:
        raise ThresholdRecalibrationError("LABELED_ROWS_MISSING_FEATURES")
    addon_dir = Path(tempfile.gettempdir()) / "supervised_derivation"
    addon_dir.mkdir(parents=True, exist_ok=True)
    out_path = addon_dir / f"{uuid.uuid4().hex}-labeled.csv"
    export_frame.to_csv(out_path, index=False)
    final_name = (dataset_name or f"{source_version.registered_model.name}-labeled")[:120]
    dataset_artifact = service.create_from_file(
        source_version.registered_model.project_id,
        out_path,
        f"{final_name}.csv",
        "dataset",
        metadata={
            "source": "supervised_derivation",
            "source_version_id": str(source_version.id),
            "positive_label": positive_label,
            "positives": int((export_frame[positive_label] == 1).sum()),
            "negatives": int((export_frame[positive_label] == 0).sum()),
            "row_count": int(len(export_frame)),
        },
        commit=False,
    )
    out_path.unlink(missing_ok=True)
    db.flush()
    if commit:
        db.commit()
    return {
        "dataset_artifact_id": str(dataset_artifact.id),
        "dataset_name": f"{final_name}.csv",
        "rows": int(len(export_frame)),
        "positives": int((export_frame[positive_label] == 1).sum()),
        "negatives": int((export_frame[positive_label] == 0).sum()),
        "feature_columns": feature_names,
        "label_column": positive_label,
    }
