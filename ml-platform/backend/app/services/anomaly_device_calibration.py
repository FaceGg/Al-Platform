"""设备级重标定服务（技术方案 §7，三期 M8/M9）：机群基线 + per-device calibration。

三期能力的本质：检测器主体（正常包络的联合分布形态）跨设备共享，标定/阈值
按设备独立——一期「模型主体与标定分离」架构（model.joblib + score_stats
双工件）的规模化应用。

- **机群形态判定**（§7.2.3 不适配护栏）：新设备数据对「机群基线阈值」（源
  版本 score_stats.threshold_score）的误报率超 ``FLEET_FIT_TOLERANCE``（1.5）
  倍 contamination → 判定该设备分布形态异于机群（传感器基线差异非平移可
  吸收）→ ``fleet_compatible=False`` + 建议独立建模；**不硬迁**——迁移版本
  仍产出但带 unfit 标记，挂载决策留给调用方。
- **设备级重标定**：不动检测器主体，只在新设备正常数据上重跑
  ``AnomalyScoreCalibrator``（分位数标定恰好吸收设备间分数分布的平移/伸缩，
  联合分布的形态是共有的）。
- **迁移有效性回测**：一期合成基准口径在新设备数据上回测（holdout=设备
  数据留出段，合成异常按设备数据构造）→ synthetic_auc + 各类检出率。
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from app.models.artifact import Artifact
from app.models.model_registry import (
    ModelVersion,
    RegisteredModel,
)

# §7.1/§7.2.3 机群形态容差：与一期门禁同口径（ANOMALY_ACCEPTANCE_FPR_TOLERANCE）
FLEET_FIT_TOLERANCE = 1.5
# 标定数据下限：与 M7 分片护栏同源（§6.6E，Binomial 容差教训）
DEVICE_CALIBRATION_MIN_ROWS = 200


class DeviceCalibrationError(RuntimeError):
    def __init__(self, code: str, message: str | None = None):
        self.code = code
        self.detail_message = message or code
        super().__init__(self.detail_message)


def _sanitize_device_suffix(condition_value) -> str:
    text = str(condition_value).strip() if condition_value is not None else ""
    sanitized = re.sub(r"[^\w-]+", "_", text, flags=re.UNICODE).strip("_")
    return sanitized[:64] or "default"


def recalibrate_device_version(
    db,
    *,
    source_version_id,
    calibration_artifact_id,
    condition_value: str,
    actor_id,
    contamination: float | None = None,
    calibration_rows_cap: int = 20000,
    commit: bool = True,
) -> dict:
    """新设备短期数据重标定（§7.2）：不动检测器主体，只重跑标定层。

    流程：机群形态判定（源阈值下新设备 fpr）→ 设备级标定
    （AnomalyScoreCalibrator 在新设备数据上）→ 合成基准回测 → 注册迁移
    版本（同源 model/onnx artifact，conversion_metadata 指向新 stats——
    阈值解析链与推理判定自动跟随新标定）。

    返回 dict：version_id / registered_model_id / stats_artifact_id /
    threshold_score / fleet_fit（compatible/fleet_fpr/tolerance/baseline）/
    backtest（synthetic_auc/per_class_recall/holdout_rows）/ unfit_for_fleet。
    """
    from app.services.automl_anomaly import (
        ANOMALY_ACCEPTANCE_FPR_TOLERANCE,
        AnomalyScoreCalibrator,
        build_synthetic_benchmark,
        pipeline_anomaly_scores,
    )
    from app.services.artifact_service import build_artifact_service
    from sklearn.metrics import roc_auc_score

    service = build_artifact_service(db)
    try:
        source_uuid = uuid.UUID(str(source_version_id))
    except (TypeError, ValueError, AttributeError):
        raise DeviceCalibrationError("MODEL_VERSION_NOT_FOUND") from None
    source_version = db.query(ModelVersion).filter(
        ModelVersion.id == source_uuid,
    ).first()
    if source_version is None or source_version.source_artifact_id is None:
        raise DeviceCalibrationError("MODEL_VERSION_NOT_FOUND")
    output_schema = source_version.output_schema if isinstance(source_version.output_schema, dict) else {}
    if output_schema.get("task") != "anomaly":
        raise DeviceCalibrationError("RECALIBRATE_REQUIRES_ANOMALY_VERSION")
    source_payload_stats = (
        source_version.conversion_metadata or {}
    ) if isinstance(source_version.conversion_metadata, dict) else {}
    # 机群基线阈值：源版本（机群基线/上级分片）的标定阈值
    source_stats_artifact = db.query(Artifact).filter(
        Artifact.id == source_version.source_artifact_id,
    ).first()

    # 1) 标定数据加载（只读已有工件；≥200 行护栏与 §6.6E 同源）
    calibration_artifact = db.query(Artifact).filter(
        Artifact.id == _as_uuid(calibration_artifact_id),
        Artifact.project_id == source_version.registered_model.project_id,
    ).first()
    if calibration_artifact is None:
        raise DeviceCalibrationError("CALIBRATION_DATASET_NOT_FOUND")
    with service.materialize(
        calibration_artifact.id, calibration_artifact.project_id,
        expected_type="dataset",
    ) as path:
        frame = pd.read_csv(path)
    feature_columns = [
        str(item.get("name"))
        for item in (source_version.feature_schema or [])
        if isinstance(item, dict) and item.get("name")
    ]
    if not feature_columns:
        raise DeviceCalibrationError("MODEL_FEATURE_COLUMNS_MISSING")
    device_frame = frame.reindex(columns=feature_columns).dropna(how="all")
    device_frame = device_frame.dropna()
    if len(device_frame) < DEVICE_CALIBRATION_MIN_ROWS:
        raise DeviceCalibrationError(
            "CALIBRATION_ROWS_INSUFFICIENT",
            f"标定数据需要 ≥{DEVICE_CALIBRATION_MIN_ROWS} 行，实际 {len(device_frame)}",
        )
    if len(device_frame) > calibration_rows_cap:
        rng = np.random.default_rng(42)
        device_frame = device_frame.iloc[
            np.sort(rng.choice(len(device_frame), size=calibration_rows_cap, replace=False))
        ]
    device_matrix = device_frame.to_numpy(dtype=float)

    # 2) 源模型打分（检测器主体不动）
    with service.materialize(
        source_version.source_artifact_id, source_version.registered_model.project_id,
        expected_type="model",
    ) as path:
        import joblib

        payload = joblib.load(path)
    model = payload.get("model")
    if model is None:
        raise DeviceCalibrationError("MODEL_BUNDLE_INVALID")
    scores = pipeline_anomaly_scores(model, device_matrix)

    # 3) 机群形态判定：源（机群基线）阈值下新设备数据的 fpr——分位数标定
    # 只吸收平移/伸缩；形态异于机群的设备此 fpr 会显著超标
    baseline_stats = _resolve_baseline_stats(
        db, service, source_version, source_stats_artifact,
    )
    contamination_value = (
        float(contamination) if contamination is not None
        else float(baseline_stats.get("contamination") or 0.01)
    )
    baseline_threshold = baseline_stats.get("threshold_score")
    fleet_fpr = (
        float(np.mean(scores >= float(baseline_threshold)))
        if baseline_threshold is not None else None
    )
    tolerance = ANOMALY_ACCEPTANCE_FPR_TOLERANCE * contamination_value
    fleet_compatible = (
        baseline_threshold is None or fleet_fpr is None
        or fleet_fpr <= tolerance
    )

    # 4) 设备级标定（只跑标定层，§7.2.1）
    calibrator = AnomalyScoreCalibrator.fit(scores, contamination=contamination_value)

    # 5) 迁移有效性回测：合成基准在设备数据上（holdout=设备数据留出段；
    # 模型不重新 fit——迁移语义）
    holdout_size = max(1, int(len(device_matrix) * 0.2))
    split_rng = np.random.default_rng(42)
    order = split_rng.permutation(len(device_matrix))
    backtest_train, backtest_holdout = (
        device_matrix[order[holdout_size:]],
        device_matrix[order[:holdout_size]],
    )
    benchmark = build_synthetic_benchmark(
        backtest_train, backtest_holdout, random_seed=42,
    )
    holdout_scores = pipeline_anomaly_scores(model, benchmark.holdout_matrix)
    synthetic_scores = np.concatenate([
        holdout_scores,
        pipeline_anomaly_scores(model, benchmark.uniform_outliers),
        pipeline_anomaly_scores(model, benchmark.perturbations),
        pipeline_anomaly_scores(model, benchmark.combinatorial),
    ])
    labels = np.concatenate([
        np.zeros(len(holdout_scores), dtype=int),
        np.ones(len(synthetic_scores) - len(holdout_scores), dtype=int),
    ])
    backtest_auc = (
        float(roc_auc_score(labels, synthetic_scores))
        if len(np.unique(labels)) == 2 else 0.0
    )
    per_class_recall = {
        "uniform_outlier": float(np.mean(
            pipeline_anomaly_scores(model, benchmark.uniform_outliers) >= calibrator.threshold_score
        )),
        "local_perturbation": float(np.mean(
            pipeline_anomaly_scores(model, benchmark.perturbations) >= calibrator.threshold_score
        )),
        "combinatorial_anomaly": float(np.mean(
            pipeline_anomaly_scores(model, benchmark.combinatorial) >= calibrator.threshold_score
        )),
    }

    # 6) 注册迁移版本：新 stats artifact + 同源 model/onnx artifact 的新版本
    # （RegisteredModel 名复用——同设备重标定按版本号演进，幂等重放语义）
    model_name = f"{source_version.registered_model.name}-device-{_sanitize_device_suffix(condition_value)}"[:128]
    registered_model = db.query(RegisteredModel).filter(
        RegisteredModel.project_id == source_version.registered_model.project_id,
        RegisteredModel.name == model_name,
    ).first()
    if registered_model is None:
        registered_model = RegisteredModel(
            project_id=source_version.registered_model.project_id,
            name=model_name,
            description=f"机群迁移版本（源 {source_version.registered_model.name}，"
                        f"设备 {condition_value}，仅重标定）",
            created_by_id=_as_uuid(actor_id),
        )
        db.add(registered_model)
        db.flush()
    stats_payload = {
        "kind": "anomaly_score_stats",
        "recalibration": {
            "source_version_id": str(source_version.id),
            "condition_value": str(condition_value),
            "calibration_artifact_id": str(calibration_artifact.id),
            "calibration_rows": int(len(device_frame)),
            "recalibrated_at": datetime.now(timezone.utc).isoformat(),
            "fleet_fit": {
                "compatible": bool(fleet_compatible),
                "fleet_fpr": fleet_fpr,
                "tolerance": tolerance,
                "baseline_threshold": baseline_threshold,
            },
            "backtest": {
                "synthetic_auc": backtest_auc,
                "per_class_recall": per_class_recall,
                "holdout_rows": int(len(backtest_holdout)),
            },
        },
        "threshold_score": calibrator.threshold_score,
        "contamination": contamination_value,
        "calibration": {
            "probabilities": [float(v) for v in calibrator.quantile_probabilities],
            "quantile_points": [float(v) for v in calibrator.quantile_points],
        },
        "threshold_policy": {
            "threshold_score": calibrator.threshold_score,
            "calibrated_threshold": calibrator.calibrated_threshold,
            "contamination": contamination_value,
            "persisted": True,
        },
    }
    stats_path = Path(json_stats_tempdir()) / f"device-{uuid.uuid4().hex}-score_stats.json"
    stats_path.parent.mkdir(parents=True, exist_ok=True)
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
            "condition_value": str(condition_value),
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
        # source_kind/library 组合跟随源版本——ck_model_versions_source_reference
        # CHECK 约束要求两者成对（platform_joblib↔library 非空 / onnx_artifact↔NULL）
        source_kind=source_version.source_kind,
        source_model_library_id=source_version.source_model_library_id,
        source_artifact_id=source_version.source_artifact_id,
        onnx_artifact_id=source_version.onnx_artifact_id,
        framework=source_version.framework,
        algorithm=source_version.algorithm,
        feature_schema=source_version.feature_schema,
        output_schema=source_version.output_schema,
        metrics={
            "recalibration": stats_payload["recalibration"],
        },
        conversion_metadata={
            **(source_version.conversion_metadata or {}),
            "anomaly_score_stats_artifact_id": str(stats_artifact.id),
            "condition_value": str(condition_value),
            "device_recalibration": True,
            "fleet_compatible": bool(fleet_compatible),
        },
        approval_status="pending",
        created_by_id=_as_uuid(actor_id),
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
        "threshold_score": float(calibrator.threshold_score),
        "unfit_for_fleet": not bool(fleet_compatible),
        "fleet_fit": stats_payload["recalibration"]["fleet_fit"],
        "backtest": stats_payload["recalibration"]["backtest"],
        "calibration_rows": int(len(device_frame)),
    }


def add_fleet_shard_to_deployment(
    db,
    *,
    deployment_id,
    version_id,
    condition_value,
    actor_id,
    weight_bps: int | None = None,
) -> dict:
    """迁移版本挂载为部署分片 target（§7.1.4：机群基线在部署面就是「工况
    分片」的 device 维特例）。

    新 stable revision = 现有 stable targets 全量复制 + 新 target
    （condition_value 标注）；旧 revision superseded，换 revision 轮换保证
    runtime_key 不可变语义与灰度/分片一致。weight 缺省均分（10000//N）。
    """
    from app.models.model_registry import (
        DeploymentRevision,
        DeploymentTarget,
        InferenceDeployment,
    )

    try:
        deployment_uuid = uuid.UUID(str(deployment_id))
        version_uuid = uuid.UUID(str(version_id))
    except (TypeError, ValueError, AttributeError):
        raise DeviceCalibrationError("INFERENCE_DEPLOYMENT_NOT_FOUND") from None
    deployment = db.query(InferenceDeployment).filter(
        InferenceDeployment.id == deployment_uuid,
    ).first()
    if deployment is None:
        raise DeviceCalibrationError("INFERENCE_DEPLOYMENT_NOT_FOUND")
    version = db.query(ModelVersion).filter(
        ModelVersion.id == version_uuid,
    ).first()
    if version is None or version.registered_model.project_id != deployment.project_id:
        raise DeviceCalibrationError("MODEL_VERSION_NOT_FOUND")
    if version.approval_status != "approved":
        raise DeviceCalibrationError("MODEL_NOT_APPROVED")
    stable = db.query(DeploymentRevision).filter(
        DeploymentRevision.deployment_id == deployment.id,
        DeploymentRevision.status == "stable",
    ).order_by(DeploymentRevision.revision_number.desc()).first()
    existing_targets = list(stable.targets or ()) if stable is not None else []
    existing = {
        str(target.model_version_id): getattr(target, "condition_value", None)
        for target in existing_targets
    }
    if str(version.id) in existing:
        raise DeviceCalibrationError("FLEET_SHARD_ALREADY_MOUNTED")
    count = len(existing_targets) + 1
    total_weight = 10000
    fallback_weight = max(total_weight // count, 1)
    if weight_bps is None:
        weight_bps = fallback_weight
    weight_bps = max(0, min(int(weight_bps), 10000))
    actor_uuid = _as_uuid(actor_id)
    if stable is not None:
        stable.status = "superseded"
    revision = DeploymentRevision(
        deployment_id=deployment.id,
        revision_number=(int(stable.revision_number) + 1) if stable is not None else 1,
        strategy="immediate",
        status="stable",
        created_by_id=actor_uuid,
    )
    db.add(revision)
    db.flush()
    # 现有分片全量复制（新 revision 的 targets 必须自洽完整）
    for target in existing_targets:
        db.add(DeploymentTarget(
            revision_id=revision.id,
            model_version_id=target.model_version_id,
            weight_bps=int(target.weight_bps),
            role="stable",
            condition_value=getattr(target, "condition_value", None),
        ))
    db.add(DeploymentTarget(
        revision_id=revision.id,
        model_version_id=version.id,
        weight_bps=weight_bps,
        role="stable",
        condition_value=str(condition_value).strip(),
    ))
    db.flush()
    if deployment.condition_column is None or not str(deployment.condition_column).strip():
        deployment.condition_column = "device_id"
    db.flush()
    db.commit()
    return {
        "revision_id": str(revision.id),
        "revision_number": int(revision.revision_number),
        "targets": [
            {
                "model_version_id": str(target.model_version_id),
                "condition_value": getattr(target, "condition_value", None),
                "weight_bps": int(target.weight_bps),
            }
            for target in revision.targets or ()
        ],
    }


def fleet_overview(
    db,
    *,
    deployment_id,
) -> dict:
    """机群监控聚合（§7 三-3，M10）：部署面 per-device 概览。

    返回 condition_column + stable revision 全部分片 target 的版本信息
    （condition_value/threshold/机群兼容性/回测 AUC）+ 部署 PSI 分片明细
    （demo_loop psi_state.per_shard，若配置了闭环）。
    """
    from app.models.model_registry import DeploymentRevision, InferenceDeployment
    from app.models.demo_loop import DemoLoopConfig

    try:
        deployment_uuid = uuid.UUID(str(deployment_id))
    except (TypeError, ValueError, AttributeError):
        raise DeviceCalibrationError("INFERENCE_DEPLOYMENT_NOT_FOUND") from None
    deployment = db.query(InferenceDeployment).filter(
        InferenceDeployment.id == deployment_uuid,
    ).first()
    if deployment is None:
        raise DeviceCalibrationError("INFERENCE_DEPLOYMENT_NOT_FOUND")
    stable = db.query(DeploymentRevision).filter(
        DeploymentRevision.deployment_id == deployment.id,
        DeploymentRevision.status == "stable",
    ).order_by(DeploymentRevision.revision_number.desc()).first()
    shards: list[dict] = []
    if stable is not None:
        for target in stable.targets or ():
            version = db.query(ModelVersion).filter(
                ModelVersion.id == target.model_version_id,
            ).first()
            if version is None:
                continue
            metadata = version.conversion_metadata if isinstance(version.conversion_metadata, dict) else {}
            stats_id = str(metadata.get("anomaly_score_stats_artifact_id") or "").strip()
            threshold = None
            stats_payload = None
            if stats_id:
                artifact = db.query(Artifact).filter(
                    Artifact.id == uuid.UUID(stats_id),
                ).first()
                if artifact is not None:
                    from app.services.artifact_service import build_artifact_service

                    try:
                        with build_artifact_service(db).materialize(
                            artifact.id, artifact.project_id, expected_type="report",
                        ) as path:
                            stats_payload = json.loads(Path(path).read_text(encoding="utf-8"))
                    except Exception:  # noqa: BLE001 - stats 丢失分片视图降级展示
                        stats_payload = None
            if stats_payload is None and version.source_artifact_id is not None:
                # 非分片版本回退 job 链（与 anomaly_threshold_for_version 同语义）
                payload = _score_stats_via_job_chain(db, version)
                stats_payload = payload
            if stats_payload:
                threshold = stats_payload.get("threshold_score")
            shards.append({
                "condition_value": getattr(target, "condition_value", None),
                "model_version_id": str(target.model_version_id),
                "version_number": int(version.version_number),
                "weight_bps": int(target.weight_bps),
                "threshold_score": float(threshold) if threshold is not None else None,
                "fleet_compatible": metadata.get("fleet_compatible"),
                "recalibration": metadata.get("device_recalibration") is True,
                "backtest": (metadata.get("recalibration") or {}).get("backtest")
                if isinstance(metadata.get("recalibration"), dict) else None,
                "metrics": version.metrics if isinstance(version.metrics, dict) else {},
            })
    psi_per_shard = None
    config = db.query(DemoLoopConfig).filter(
        DemoLoopConfig.deployment_id == deployment.id,
    ).first()
    if config is not None:
        state = config.psi_state if isinstance(config.psi_state, dict) else {}
        psi_per_shard = state.get("per_shard")
    # per-device 运行期报警率（§7 三-3 M10「per-device fpr/PSI 聚合」的 fpr
    # 侧）：无标签下以该设备回流数据的模型报警率为 proxy（与部署级
    # alert_comparison 同口径，按分片阈值分组统计）。回流/阈值缺失时留空。
    running_by_shard = _running_alert_rate_by_shard(db, deployment, config, shards)
    if running_by_shard:
        for shard in shards:
            shard["running"] = running_by_shard.get(shard.get("condition_value"))
    return {
        "deployment_id": str(deployment.id),
        "condition_column": deployment.condition_column,
        "revision_id": str(stable.id) if stable is not None else None,
        "revision_number": int(stable.revision_number) if stable is not None else None,
        "shards": shards,
        "psi_per_shard": psi_per_shard,
    }


def _running_alert_rate_by_shard(db, deployment, config, shards) -> dict:
    """分片运行期报警率（M10 per-device fpr proxy）：回流帧按工况列分组，
    各分片按自身阈值统计 anomaly_score≥阈值的行占比。数据/阈值缺失返回 {}。"""
    if config is None or not shards:
        return {}
    condition_column = str(getattr(deployment, "condition_column", None) or "").strip()
    if not condition_column:
        return {}
    thresholds = {
        shard.get("condition_value"): shard.get("threshold_score")
        for shard in shards
        if shard.get("threshold_score") is not None
    }
    if not thresholds:
        return {}
    import pandas as pd

    from app.models.artifact import Artifact

    frames = []
    service = None
    for artifact_id in (config.error_artifact_id, getattr(config, "correct_artifact_id", None)):
        if not artifact_id:
            continue
        try:
            artifact = db.query(Artifact).filter(
                Artifact.id == artifact_id,
                Artifact.project_id == config.project_id,
            ).first()
            if artifact is None:
                continue
            from app.services.artifact_service import build_artifact_service

            service = service or build_artifact_service(db)
            with service.materialize(
                artifact.id, config.project_id, expected_type="dataset",
            ) as path:
                frames.append(pd.read_csv(path))
        except Exception:  # noqa: BLE001 - 视图聚合降级：缺数据不报错
            continue
    if not frames:
        return {}
    running: dict[str | None, dict] = {}
    for frame in frames:
        if "anomaly_score" not in frame.columns or condition_column not in frame.columns:
            continue
        condition_series = frame[condition_column].astype(str).str.strip()
        scores = pd.to_numeric(frame["anomaly_score"], errors="coerce")
        for shard_value, threshold in thresholds.items():
            if shard_value is None:
                mask = ~condition_series.isin({
                    str(key) for key in thresholds if key is not None
                })
            else:
                mask = condition_series == str(shard_value)
            rows = scores[mask].dropna()
            if rows.empty:
                continue
            alerts = int((rows >= float(threshold)).sum())
            entry = running.setdefault(str(shard_value) if shard_value is not None else None, {"rows": 0, "alerts": 0})
            entry["rows"] += int(len(rows))
            entry["alerts"] += alerts
    for entry in running.values():
        entry["alert_rate"] = round(entry["alerts"] / entry["rows"], 4) if entry["rows"] else None
    return running


def _score_stats_via_job_chain(db, version):
    """非分片版本 score_stats 回退链：模型库 → job.metrics.score_artifact_id。"""
    from app.models.model_library import ModelLibrary
    from app.models.training import TrainingJob
    from app.services.artifact_service import build_artifact_service

    library = db.query(ModelLibrary).filter(
        ModelLibrary.id == version.source_model_library_id,
    ).first()
    if library is None or not library.training_job_id:
        return None
    job = db.query(TrainingJob).filter(
        TrainingJob.id == library.training_job_id,
    ).first()
    score_artifact_id = (job.metrics or {}).get("score_artifact_id") if job else None
    if not score_artifact_id:
        return None
    artifact = db.query(Artifact).filter(
        Artifact.id == uuid.UUID(str(score_artifact_id)),
    ).first()
    if artifact is None:
        return None
    try:
        with build_artifact_service(db).materialize(
            artifact.id, job.project_id, expected_type="report",
        ) as path:
            return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - 视图聚合降级展示
        return None


def _resolve_baseline_stats(db, service, source_version, source_model_artifact):
    """机群基线标定参数：源版本分片指针 artifact 优先，回退源 model bundle
    内嵌 score_stats，再回退默认 contamination（无证据不设基线阈值）。"""
    metadata = source_version.conversion_metadata if isinstance(source_version.conversion_metadata, dict) else {}
    shard_stats_id = str(metadata.get("anomaly_score_stats_artifact_id") or "").strip()
    if shard_stats_id:
        artifact = db.query(Artifact).filter(
            Artifact.id == uuid.UUID(shard_stats_id),
        ).first()
        if artifact is not None:
            with service.materialize(
                artifact.id, source_version.registered_model.project_id,
                expected_type="report",
            ) as path:
                return json.loads(Path(path).read_text(encoding="utf-8"))
    if source_model_artifact is not None:
        with service.materialize(
            source_model_artifact.id, source_version.registered_model.project_id,
            expected_type="model",
        ) as path:
            import joblib

            payload = joblib.load(path)
        stats = payload.get("score_stats")
        if isinstance(stats, dict):
            return stats
    return {"contamination": 0.01, "threshold_score": None}


def _as_uuid(value):
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        raise DeviceCalibrationError("UUID_INVALID") from None


def json_stats_tempdir() -> Path:
    # 容器内 app 用户无工作目录写权限——用系统临时目录（/tmp，可写）
    import tempfile

    return Path(tempfile.gettempdir()) / "device_recalibration"
