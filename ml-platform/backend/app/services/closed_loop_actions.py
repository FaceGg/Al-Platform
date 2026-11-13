"""Reusable closed-loop actions shared by the demo-loop service and the
orchestration serving operators (append error dataset / notify admins /
retrain threshold trigger + completion swap)."""

from __future__ import annotations

import hashlib
import io
import json
import logging
import tempfile
import threading
import uuid
from datetime import datetime
from pathlib import Path

import pandas as pd

from app.config import settings
from app.database import SessionLocal
from app.models.artifact import Artifact
from app.models.experiment import Experiment, ExperimentAutoMLBinding
from app.models.model_registry import (
    DeploymentRevision,
    DeploymentTarget,
    InferenceDeployment,
    ModelVersion,
)
from app.models.notifications import InAppNotification
from app.models.project import Project
from app.models.training import TrainingJob
from app.models.user import User
from app.services.artifact_service import build_artifact_service
from app.services.automl_catalog import AUTOML_FAMILY_IDS, resolve_algorithm_families
from app.services.automl_execution import normalize_evaluation_config, resolve_automl_feature_columns
from app.services.automl_search import normalize_search_controls, validate_target_columns
from app.services.model_registry import ModelRegistryService, ModelRegistryError

logger = logging.getLogger(__name__)


class ClosedLoopError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


_LOCKS_GUARD = threading.Lock()
_LOCKS: dict[str, threading.Lock] = {}


def lock_for(key: str) -> threading.Lock:
    with _LOCKS_GUARD:
        lock = _LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _LOCKS[key] = lock
        return lock


def json_value(value):
    import math

    import numpy as np

    if value is None or value is pd.NaT:
        return None
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if isinstance(value, np.generic):
        return json_value(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {str(key): json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(item) for item in value]
    return value


# Backwards-compatible alias for the demo_loop service.
_json_value = json_value


def automl_dispatcher():
    if getattr(settings, "task_backend", "local") == "celery":
        # CeleryTrainingDispatcher lives in the training API module; the celery
        # task itself lives in app.tasks.training_tasks.
        from app.api.training import CeleryTrainingDispatcher
        from app.tasks.training_tasks import execute_automl_task

        return CeleryTrainingDispatcher(execute_automl_task)
    from app.tasks.training_tasks import LocalTrainingDispatcher, execute_local_automl_task

    return LocalTrainingDispatcher(execute_local_automl_task)


# Backwards-compatible alias: demo_loop re-exports this so its tests can patch
# the dispatcher on the demo_loop module.
_automl_dispatcher = automl_dispatcher


# ---------------------------------------------------------------- dataset append


def _as_uuid(value) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


def append_rows_to_dataset_artifact(
    db, artifact_service, artifact: Artifact, rows: list[dict],
) -> int:
    """Append JSON-safe rows to a CSV dataset artifact in place.

    Returns the new total row count. Concurrency is serialized per artifact.
    """
    if not rows:
        return int((artifact.metadata_ or {}).get("row_count", 0))
    columns = sorted({key for row in rows for key in row})
    # A-11：进程内 threading.Lock 在 worker prefork 多进程下不互斥（先写者
    # 行丢失、旧对象变孤儿）。改为 DB 级乐观锁：以读取时的 storage_uri 为
    # 前置条件做 UPDATE，冲突方重读重试（≤3 次），仍冲突则抛稳定错误。
    from sqlalchemy import update as sa_update
    from sqlalchemy.exc import SQLAlchemyError

    for attempt in range(3):
        expected_uri = artifact.storage_uri
        with artifact_service.storage.materialize(expected_uri) as path:
            frame = pd.read_csv(path)
        # Schema evolution: new row keys (e.g. the auto-label target column)
        # extend the CSV; old rows stay empty for those columns.
        new_columns = [column for column in columns if column not in frame.columns]
        if new_columns:
            for column in new_columns:
                frame[column] = pd.NA
        for row in rows:
            frame.loc[len(frame)] = [json_value(row.get(column)) for column in frame.columns]
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "rows.csv"
            frame.to_csv(out, index=False)
            stored = artifact_service.storage.put(
                out,
                project_id=str(artifact.project_id),
                artifact_id=str(artifact.id),
                filename=Path(artifact.name).name or "rows.csv",
            )
        schema = [
            {"name": str(column), "dtype": str(frame[column].dtype),
             "null_count": int(frame[column].isna().sum())}
            for column in frame.columns
        ]
        claimed = db.execute(
            sa_update(Artifact)
            .where(
                Artifact.id == artifact.id,
                Artifact.storage_uri == expected_uri,
            )
            .values(
                storage_uri=stored.uri,
                file_size=stored.size,
                metadata_={
                    **(artifact.metadata_ or {}),
                    "sha256": stored.sha256,
                    "row_count": int(len(frame)),
                    "column_count": int(len(frame.columns)),
                    "schema": schema,
                },
            )
        ).rowcount
        db.commit()
        if not claimed:
            db.rollback()
            # 并发写者已推进：重读最新行后重试（保住"读-改-写"完整追加语义）
            db.refresh(artifact)
            if attempt == 2:
                raise ClosedLoopError(
                    "APPEND_CONFLICT",
                    "并发追加冲突，重试后仍不一致",
                )
            continue
        if expected_uri and expected_uri != stored.uri:
            try:
                artifact_service.storage.delete(expected_uri)
            except Exception:
                logger.debug("stale dataset artifact cleanup failed: %s", expected_uri, exc_info=True)
        artifact.storage_uri = stored.uri
        artifact.file_size = stored.size
        artifact.metadata_ = {
            **(artifact.metadata_ or {}),
            "sha256": stored.sha256,
            "row_count": int(len(frame)),
            "column_count": int(len(frame.columns)),
            "schema": schema,
        }
        return int(len(frame))
    raise ClosedLoopError("APPEND_CONFLICT", "并发追加冲突")


# ---------------------------------------------------------------- notifications


def notify_project_admins(
    db, project_id, title: str, body: str, *,
    severity: str = "warning",
    event_type: str = "closed_loop.notify",
    payload: dict | None = None,
) -> int:
    project_id = _as_uuid(project_id)
    recipients: set = set()
    project = db.query(Project).filter(Project.id == project_id).first()
    if project is not None and project.owner_id:
        recipients.add(uuid.UUID(str(project.owner_id)))
    for row in db.query(User.id).filter(User.role == "admin").all():
        recipients.add(row.id)
    for recipient in recipients:
        db.add(InAppNotification(
            recipient_user_id=recipient,
            project_id=project_id,
            event_id=uuid.uuid4(),
            event_type=event_type,
            deduplication_key=f"cl-{uuid.uuid4().hex[:16]}",
            severity=severity,
            title=title,
            body=body,
            payload=json_value(payload or {}) or {},
        ))
    db.commit()
    return len(recipients)


# ---------------------------------------------------------------- retrain


RETRAIN_METADATA_COLUMNS = ("prediction", "confidence", "anomaly_score", "feedback")


def apply_feedback_marks(frame: pd.DataFrame, marks: dict | None) -> pd.DataFrame:
    """把报警确认标记打为 ``feedback`` 列（技术方案 §3.6 弱监督回流）。

    ``marks`` 形态 ``{"<artifact_id>": {"<row_index>": mark}}``；frame 是单个
    数据集物化后的整帧（行号=CSV 行序，append-only 不漂移）。mark 仅接受
    ``confirmed_fault``/``false_alarm``，其余值忽略。
    """
    if not marks:
        return frame
    applied = 0
    feedback = [""] * len(frame)
    for artifact_marks in (marks or {}).values():
        if not isinstance(artifact_marks, dict):
            continue
        for raw_index, mark in artifact_marks.items():
            try:
                index = int(raw_index)
            except (TypeError, ValueError):
                continue
            if not 0 <= index < len(frame) or str(mark) not in {"confirmed_fault", "false_alarm"}:
                continue
            feedback[index] = str(mark)
            applied += 1
    if applied:
        frame = frame.copy()
        frame["feedback"] = feedback
    return frame


def build_retrain_frame(
    frames: list[pd.DataFrame],
    target_column: str,
    *,
    anomaly_threshold_score: float | None = None,
) -> pd.DataFrame:
    """Merge retrain source frames, auto-label reflow rows and strip leakage.

    Shared by the engine retrain path (:func:`trigger_retrain_job`) and the
    agent retrain mode (app.services.agent.loop_retrain) — 智能体侧训练器
    （lightweight_trainer，函数名为历史遗留，现为默认全量的验收训练）
    没有引擎侧惰性标注，物化前必须完成整帧标注。

    自动标注：回流数据集没有人工标签列，但回流行自带 prediction 列
    （推理结果）。目标列整列缺失时直接由推理结果生成；部分缺失时补齐。

    无监督模式（``target_column`` 为空，技术方案 §3.6 仅正常数据重拟合）：
    - 剔除高分回流行（anomaly_score ≥ 阈值）——防把缓变故障学进正常包络；
      确认故障行（分数天然高分）随之自然排除；
    - 剔除用户标记的误报行（feedback=false_alarm，排除集）——重拟合收窄
      误包容（§3.6 弱监督反馈闭环的消费端）；
    - anomaly_score/feedback 列不进特征；无监督任务无目标列，不做标注。
    """
    frame = pd.concat(frames, ignore_index=True) if len(frames) > 1 else frames[0]
    anomaly_mode = not target_column
    if anomaly_mode:
        if "feedback" in frame.columns:
            feedback = frame["feedback"].fillna("").astype(str).str.strip()
            frame = frame[feedback != "false_alarm"]
        if anomaly_threshold_score is not None and "anomaly_score" in frame.columns:
            scores = pd.to_numeric(frame["anomaly_score"], errors="coerce")
            # 无分数行（旧回流）保留——剔除判据只对带分数的行生效
            frame = frame[scores.isna() | (scores < float(anomaly_threshold_score))]
        frame = frame.drop(columns=list(RETRAIN_METADATA_COLUMNS), errors="ignore")
        if len(frames) > 1:
            common = set(frames[0].columns) - set(RETRAIN_METADATA_COLUMNS)
            for part in frames[1:]:
                common &= set(part.columns) - set(RETRAIN_METADATA_COLUMNS)
            keep = [column for column in frame.columns if column in common]
            frame = frame[keep]
        return frame
    if target_column not in frame.columns:
        if "prediction" not in frame.columns:
            raise ClosedLoopError(
                "CLOSED_LOOP_TARGET_MISSING", f"目标列 {target_column} 不在重训数据集中")
        frame[target_column] = frame["prediction"]
    unlabeled = frame[target_column].isna() | (frame[target_column].astype(str).str.strip() == "")
    if unlabeled.any():
        if "prediction" in frame.columns:
            filled = frame.loc[unlabeled, "prediction"]
            if filled.notna().any():
                frame.loc[unlabeled, target_column] = filled
        if frame[target_column].isna().any() or (frame[target_column].astype(str).str.strip() == "").any():
            raise ClosedLoopError(
                "CLOSED_LOOP_TARGET_MISSING",
                f"目标列 {target_column} 存在缺失值且无推理结果可自动补齐",
            )
    # 混合来源的标签可能是数字与字符串（"1" 与 1），统一为数值避免类别分裂。
    coerced = pd.to_numeric(frame[target_column], errors="coerce")
    if coerced.notna().all():
        frame[target_column] = coerced
    # 回流元数据列不能进特征（标签泄漏）：标注完成后从训练帧剔除。
    frame = frame.drop(columns=list(RETRAIN_METADATA_COLUMNS), errors="ignore")
    if len(frames) > 1:
        # 多数据集列体系可能不同（特征工程后 vs 原始报告列）；取交集保行数，
        # 否则并集列在来源缺之行全 NaN，drop_rows 策略会把所有行丢光。
        common = set(frames[0].columns) - set(RETRAIN_METADATA_COLUMNS)
        for part in frames[1:]:
            common &= set(part.columns) - set(RETRAIN_METADATA_COLUMNS)
        common.add(target_column)
        keep = [column for column in frame.columns if column in common]
        if target_column not in keep:
            keep.append(target_column)
        frame = frame[keep]
    return frame


def resolve_retrain_dataset_ids(config) -> list[str]:
    """闭环重训数据集选择（引擎/agent 重训共用，顺序稳定）：

    用户配置数据集 → 闭环收集的报错数据集（置最前）→ 按比例收集的正确
    数据集（紧随报错数据）。全部去重；为空返回 []（调用方决定报错方式）。
    """
    dataset_ids = list(getattr(config, "retrain_dataset_artifact_ids", None) or [])
    if not dataset_ids and config.retrain_dataset_artifact_id is not None:
        dataset_ids = [config.retrain_dataset_artifact_id]
    # 闭环收集的报错数据集默认参与重训（置于最前，去重）。
    if config.error_artifact_id:
        error_id = str(config.error_artifact_id)
        dataset_ids = [error_id] + [did for did in dataset_ids if did != error_id]
    # 按比例收集的正确数据集同样参与合并（紧随报错数据）。
    if getattr(config, "correct_artifact_id", None):
        correct_id = str(config.correct_artifact_id)
        dataset_ids = [did for did in dataset_ids if did != correct_id]
        insert_at = 1 if dataset_ids and dataset_ids[0] == str(config.error_artifact_id) else 0
        dataset_ids.insert(insert_at, correct_id)
    return dataset_ids


def trigger_retrain_job(
    db, *, project_id, actor_id, experiment_name: str, job_name: str,
    dataset_artifact_id=None, dataset_artifact_ids=None, target_column: str = "",
    max_trials: int = 10,
    ensemble: dict | None = None,
    algorithm_ids: list[str] | None = None,
    input_columns: list[str] | None = None,
    task_type: str = "classification",
    anomaly_threshold_score: float | None = None,
    anomaly_contamination: float | None = None,
    feedback_marks: dict | None = None,
    condition_column: str | None = None,
) -> TrainingJob:
    """Create and dispatch one AutoML job on the given dataset(s)/target.

    Multiple datasets are concatenated in selection order. Rows that lack the
    target column but carry a ``prediction`` column (closed-loop reflow rows)
    are auto-labeled with that inference result. ``ensemble``（{"enabled",
    "top_k"}）转发给引擎终选层：部署换模模型本身可为加权投票集成体。
    ``algorithm_ids``（向导算法白名单）缩小引擎搜索族；空 = 全族。
    ``input_columns``（重训特征列白名单）：稀疏宽表必配——引擎 dropna 只对
    选定列进行，缺列整行剔除的全 numeric 默认会 0 行幸存；空 = 全部数值列。

    无监督重拟合（技术方案 §3.6，task_type="anomaly_detection"）：目标列必须
    为空（镜像互斥）；``anomaly_threshold_score``（部署模型 score_stats 阈值）
    驱动「仅正常数据重拟合」剔除；contamination 随合同透传。
    ``condition_column``（§6.3 分片重拟合，二期 M7）：分片部署的闭环重拟合
    必须携带工况列——引擎按它重新分片训练（N bundle），缺失会退化单段全量，
    换模后的分片 targets 就断了。
    """
    project_id = _as_uuid(project_id)
    actor_id = _as_uuid(actor_id)
    service = build_artifact_service(db)
    raw_ids = list(dataset_artifact_ids or [])
    if not raw_ids and dataset_artifact_id is not None:
        raw_ids = [dataset_artifact_id]
    if not raw_ids:
        raise ClosedLoopError("CLOSED_LOOP_DATASET_MISSING", "未提供重训数据集")
    datasets = [
        service.resolve(_as_uuid(raw), project_id, expected_type="dataset")
        for raw in raw_ids
    ]

    experiment = db.query(Experiment).filter(
        Experiment.project_id == project_id,
        Experiment.name == experiment_name,
    ).first()
    if experiment is None:
        experiment = Experiment(
            project_id=project_id,
            created_by=actor_id,
            name=experiment_name,
            description="闭环流程自动创建的实验",
            # Unique placeholder; the real tracking id is registered below and
            # the column is globally unique.
            mlflow_experiment_id=f"pending-{uuid.uuid4().hex[:24]}",
        )
        db.add(experiment)
        db.flush()
    if experiment.mlflow_experiment_id.startswith("pending-"):
        # Register the experiment with the real tracking backend so the
        # AutoML worker can start a run against it.
        from mlflow.tracking import MlflowClient

        from app.services.experiment_tracking import (
            MlflowExperimentTracking,
            resolve_tracking_configuration,
        )
        tracking_uri, artifact_root = resolve_tracking_configuration(settings)
        tracking = MlflowExperimentTracking(
            client=MlflowClient(tracking_uri=tracking_uri),
            artifact_root=artifact_root,
        )
        experiment.mlflow_experiment_id = tracking.ensure_experiment(
            f"project/{experiment.project_id}/{experiment.id}",
        )
        db.flush()

    frames = []
    for source in datasets:
        with service.materialize(source.id, project_id, expected_type="dataset") as path:
            frames.append(apply_feedback_marks(pd.read_csv(path), (feedback_marks or {}).get(str(source.id))))
    is_anomaly = task_type == "anomaly_detection"
    frame = build_retrain_frame(
        frames, "" if is_anomaly else target_column,
        anomaly_threshold_score=anomaly_threshold_score if is_anomaly else None,
    )
    if len(datasets) > 1:
        # Worker 训练读取 job.dataset_artifact_id 指向的单个数据集；多选时
        # 必须把合并+自动标注后的帧物化为新数据集，否则特征列与训练数据
        # 不一致（合并帧的列不在第一个数据集里 → AUTOML 输入列缺失）。
        with tempfile.TemporaryDirectory() as tmp:
            merged_path = Path(tmp) / "merged.csv"
            frame.to_csv(merged_path, index=False)
            dataset = service.create_from_file(
                project_id, merged_path, f"{job_name}-合并数据集", "dataset",
                metadata={"source": "closed-loop-merge",
                          "datasets": [str(item.id) for item in datasets],
                          # 数据管理列表按 row_count 展示行数；缺失会显示为空
                          "row_count": int(len(frame)),
                          "column_count": int(len(frame.columns))},
            )
    else:
        dataset = datasets[0]
    if is_anomaly:
        validate_target_columns(frame, task_type, [])
        feature_columns = resolve_automl_feature_columns(frame, None, None, target_columns=[])
    else:
        validate_target_columns(frame, task_type, [target_column])
        feature_columns = resolve_automl_feature_columns(
            frame, target_column, None, target_columns=[target_column],
        )
    # 向导算法白名单缩小引擎搜索族（空/未配置 = 全族，行为不变）；
    # 按任务过滤白名单（M1 目录互斥）：anomaly 全族 = iforest/ocsvm。
    families = resolve_algorithm_families(
        [str(item) for item in (algorithm_ids or [])] or list(AUTOML_FAMILY_IDS),
        task=task_type,
    )
    evaluation = (
        normalize_evaluation_config(False, None)
        if is_anomaly
        else normalize_evaluation_config(True, 3)
    )
    controls = normalize_search_controls(strength="light", time_budget=600, class_weight=True)
    trials = max(int(max_trials or 10), len(families))
    fingerprint = hashlib.sha256(json.dumps({
        "experiment": experiment_name,
        "datasets": [str(item.id) for item in datasets],
        "target": target_column,
    }, sort_keys=True).encode("utf-8")).hexdigest()
    job = TrainingJob(
        id=uuid.uuid4(),
        project_id=project_id,
        user_id=actor_id,
        experiment_id=experiment.id,
        name=job_name or f"{experiment_name}-job",
        operator_id="automl",
        params={
            **({
                "target_column": target_column,
                "target_columns": [target_column],
            } if not is_anomaly else {"target_columns": []}),
            # 重训特征列白名单：转发给引擎（resolve_automl_feature_columns 的
            # requested_input_columns），dropna/特征集均按选定列；空 = 全 numeric。
            "input_columns": (
                [str(item).strip() for item in (input_columns or []) if str(item).strip()]
                or list(feature_columns)
            ),
            "task": task_type,
            "search_contract": "optuna_v1",
            "algorithm_ids": [family.id for family in families],
            "search_method": "bayesian",
            "max_trials": trials,
            **evaluation,
            "time_budget": controls["time_budget"],
            "search_strength": controls["strength"],
            "class_weight": controls["class_weight"],
            **({"contamination": float(anomaly_contamination)} if is_anomaly and anomaly_contamination else {}),
            **({"ensemble": dict(ensemble)} if ensemble else {}),
            # 工况分片重拟合（§6.3，二期 M7）：分片部署闭环重训必须带工况列，
            # 引擎按它重新分片训练（N bundle）——缺失会退化单段全量训练。
            **({
                "condition_column": str(condition_column).strip()
            } if is_anomaly and str(condition_column or "").strip() else {}),
        },
        dataset_artifact_id=dataset.id,
        dataset_path=service.storage_reference(dataset),
        status="pending",
        automl_contract={
            "task_type": task_type,
            "target_columns": [] if is_anomaly else [target_column],
            "cross_validation_folds": evaluation.get("cross_validation_folds") or 0,
            "cv_strategy": "synthetic_benchmark" if is_anomaly else "stratified",
            "random_seed": 42,
            **({"contamination": float(anomaly_contamination)} if is_anomaly and anomaly_contamination else {}),
            "idempotency_fingerprint": fingerprint,
        },
        automl_idempotency_key=f"closed-loop-{fingerprint[:24]}",
    )
    db.add(job)
    db.add(ExperimentAutoMLBinding(experiment_id=experiment.id, job_id=job.id))
    db.flush()
    # 先提交再派发：worker 领取用 with_for_update 查询，未提交的 INSERT
    # 对 worker 不可见 → claim 落空返回 skipped，任务永久滞留 pending
    # （生产复现过：任务 3ms 内 skipped）。
    db.commit()
    # Local dispatcher only registers on enqueue and needs start(task_id)
    # to spawn the worker thread; Celery's delay runs it inside enqueue.
    dispatcher = automl_dispatcher()
    task_id = dispatcher.enqueue(job.id)
    if hasattr(dispatcher, "start"):
        dispatcher.start(task_id)
    return job


# ---------------------------------------------------------------- model swap


def candidate_score(row: dict) -> float:
    metrics = row.get("metrics") or {}
    if isinstance(metrics, dict):
        for key in ("auc", "accuracy", "f1", "precision", "recall", "r2"):
            value = metrics.get(key)
            if isinstance(value, (int, float)):
                return float(value)
        for value in metrics.values():
            if isinstance(value, (int, float)):
                return float(value)
    return 0.0


def _condition_shard_model_suffix(condition_value) -> str:
    """RegisteredModel 名字后缀（唯一约束）：净化路径分隔/控制字符，保留
    unicode 字母数字（中文工况值是真实场景，不能整段抹掉）。"""
    import re as _re

    text = str(condition_value).strip() if condition_value is not None else ""
    sanitized = _re.sub(r"[^\w-]+", "_", text, flags=_re.UNICODE).strip("_")
    return sanitized[:64] or "default"


def _register_condition_shard_versions(
    db, registry, *, job, bundles, base_model_name, actor_id,
) -> list[dict]:
    """工况分片版本注册（技术方案 §6.3，二期 M7）。

    每个 bundle 独立走 artifact 信任链注册（register_platform_version 的
    source_model_artifact_id 分支：source=automl + training_job completed 校验，
    段 artifact 自动建模型库条目），并写分片身份：

    - registration_task_id / registration_idempotency_key（``closed-loop-{job}
      -cond-{suffix}``）：闭环重放幂等——同一 job 再次换模复用已注册版本；
    - conversion_metadata.anomaly_score_stats_artifact_id：推理阈值按分片独立
      解析（anomaly_threshold_for_version 优先读它；job 顶层 score_artifact_id
      是最差段的，直接复用会张冠李戴）。

    返回 rows 降序的 ``[{"version", "condition_value", "rows"}]``——首个即
    「默认分片」（训练量最大，ConditionValueRouter 未命中回退它）。
    """
    base = str(base_model_name).strip()
    entries: list[dict] = []
    sorted_bundles = sorted(
        bundles,
        key=lambda item: int(item.get("rows") or 0),
        reverse=True,
    )
    for bundle in sorted_bundles:
        # unfit 工位段（§7.5 护栏）：fpr 超 1.5×contamination 的分片不挂载
        # ——挂了会把设备个体偏差当异常（误报失控）；该工位的请求由通配
        # 全局 bundle 兜底路由。fleet_global 通配 bundle（condition_value
        # =None）保留挂载（B 主+A 兜底的 B 侧兜底）。
        if bundle.get("unfit") and bundle.get("condition_value") is not None:
            continue
        raw_value = bundle.get("condition_value")
        condition_value = str(raw_value).strip() if raw_value is not None else None
        if condition_value is not None and not condition_value:
            condition_value = None
        suffix = _condition_shard_model_suffix(condition_value)
        idempotency_key = f"closed-loop-{job.id}-cond-{suffix}"[:128]
        existing = db.query(ModelVersion).filter(
            ModelVersion.registration_task_id == job.id,
            ModelVersion.registration_idempotency_key == idempotency_key,
        ).first()
        if existing is not None:
            entries.append({
                "version": existing,
                "condition_value": condition_value,
                "rows": int(bundle.get("rows") or 0),
            })
            continue
        model = registry.create_registered_model(
            db,
            project_id=job.project_id,
            actor_id=actor_id,
            name=f"{base}-{suffix}"[:128],
            description="",
        )
        version = registry.register_platform_version(
            db,
            model_id=model.id,
            source_model_artifact_id=str(bundle.get("model_artifact_id")),
            actor_id=actor_id,
            commit=False,
        )
        version.registration_task_id = job.id
        version.registration_candidate_id = f"condition:{condition_value or 'default'}"
        version.registration_idempotency_key = idempotency_key
        version.lifecycle_state = "pending_review"
        metadata = dict(version.conversion_metadata or {})
        metadata["anomaly_score_stats_artifact_id"] = str(bundle.get("stats_artifact_id") or "")
        metadata["condition_value"] = condition_value
        version.conversion_metadata = metadata
        db.flush()
        entries.append({
            "version": version,
            "condition_value": condition_value,
            "rows": int(bundle.get("rows") or 0),
        })
    return entries


def _anomaly_detection_retention(db, deployment_id, job, best) -> dict | None:
    """无监督换模门禁评估（技术方案 §3.6）：新模型对基线期已知报警样本分数不下降。

    样本池 = 报错数据集 ``feedback="confirmed_fault"`` 行（报警确认弱监督回流的
    验证集）；旧命中 = 回流行 ``anomaly_score``（旧模型推理时写下的分数）≥ 旧
    阈值（部署版本 score_stats 基线，零额外打分）；新命中 = 候选模型管线对该批
    特征打分 ≥ 新阈值（候选 bundle 自带）。返回 ``{"old_hit_rate", "new_hit_rate"}``；
    无确认样本/旧分数缺失/部署缺失 → None（不设门禁，保持可换模）。

    工况分片（§6.3 per-shard 门禁）：job 带 condition_bundles 且确认样本带工况
    列时逐分片判定——每分片用自己的 bundle 模型对该工况内样本打分，任一分片
    命中率下降即拒绝换模（最差分片口径，与训练冠军=最差段同语义）；无工况列
    或无分片样本时回退单模型整体判定。
    """
    import joblib as _joblib

    from app.models.demo_loop import DemoLoopConfig
    from app.services.automl_anomaly import pipeline_anomaly_scores

    deployment = db.query(InferenceDeployment).filter(
        InferenceDeployment.id == _as_uuid(deployment_id),
    ).first()
    if deployment is None:
        return None
    config = db.query(DemoLoopConfig).filter(
        DemoLoopConfig.deployment_id == deployment.id,
    ).first()
    if config is None or not config.error_artifact_id:
        return None
    service = build_artifact_service(db)
    try:
        with service.materialize(config.error_artifact_id, config.project_id, expected_type="dataset") as path:
            frame = pd.read_csv(path)
    except Exception:
        return None
    frame = apply_feedback_marks(frame, config.feedback_marks)
    confirmed = frame[frame["feedback"].fillna("").astype(str).str.strip() == "confirmed_fault"]
    if confirmed.empty or "anomaly_score" not in confirmed.columns:
        return None
    old_scores = pd.to_numeric(confirmed["anomaly_score"], errors="coerce").dropna()
    if old_scores.empty:
        return None
    old_threshold = _deployment_score_threshold(db, deployment)
    if old_threshold is None:
        return None
    # 工况分片（§6.3 per-shard 门禁）：逐分片用各自 bundle 模型判定，返回
    # 最差分片口径（任一分片能力下降即整体拒换模）；不适用则走单模型整体。
    shard_retention = _retention_per_shard(
        db, job=job, confirmed=confirmed, old_threshold=old_threshold,
    )
    if shard_retention is not None:
        return shard_retention
    old_hit_rate = float((old_scores >= old_threshold).mean())
    # 新候选模型打分：候选工件（type=model，M1 bundle 含 Pipeline 与 score_stats）
    try:
        artifact = service.resolve(
            _as_uuid(best.get("model_artifact_id")), job.project_id, expected_type="model",
        )
        with service.materialize(artifact.id, job.project_id, expected_type="model") as path:
            payload = _joblib.load(path)
        model = payload.get("model")
        feature_columns = [item["name"] for item in (payload.get("feature_schema") or []) if item.get("name")]
        new_threshold = float((payload.get("score_stats") or {}).get("threshold_score") or 0.0)
        if model is None or not feature_columns:
            return None
        features = confirmed.reindex(columns=feature_columns)
        scores = pipeline_anomaly_scores(model, features.to_numpy(dtype=float))
        new_hit_rate = float((scores >= new_threshold).mean())
    except Exception:
        return None
    return {"old_hit_rate": round(old_hit_rate, 4), "new_hit_rate": round(new_hit_rate, 4)}


def _retention_per_shard(db, *, job, confirmed, old_threshold) -> dict | None:
    """分片 retention 门禁（§6.3）：逐分片判定，返回最差分片口径。

    每分片用自己的 bundle 模型对该工况内 confirmed 样本打分；condition_value
    为 None 的 bundle 吃未匹配任何已知工况值的样本（通配兜底）。全部分片均无
    可判样本（无工况列/无匹配行/打分失败）→ None（回退单模型整体判定）。
    """
    import joblib as _joblib

    from app.services.automl_anomaly import pipeline_anomaly_scores

    job_metrics = job.metrics if isinstance(job.metrics, dict) else {}
    condition_column = str(job_metrics.get("condition_column") or "").strip()
    bundles = [
        dict(bundle)
        for bundle in job_metrics.get("condition_bundles") or []
        if isinstance(bundle, dict) and bundle.get("model_artifact_id")
    ]
    if not condition_column or condition_column not in confirmed.columns or not bundles:
        return None
    service = build_artifact_service(db)
    condition_series = confirmed[condition_column].astype(str).str.strip()
    known_values = {
        str(bundle.get("condition_value")).strip()
        for bundle in bundles
        if bundle.get("condition_value") is not None
    }
    shard_reports: list[dict] = []
    for bundle in bundles:
        raw_value = bundle.get("condition_value")
        shard_value = str(raw_value).strip() if raw_value is not None else None
        if shard_value:
            shard_rows = confirmed[condition_series == shard_value]
        else:
            shard_rows = confirmed[~condition_series.isin(known_values)]
        if shard_rows.empty:
            continue
        shard_scores = pd.to_numeric(shard_rows["anomaly_score"], errors="coerce").dropna()
        if shard_scores.empty:
            continue
        try:
            artifact = service.resolve(
                _as_uuid(bundle["model_artifact_id"]), job.project_id, expected_type="model",
            )
            with service.materialize(artifact.id, job.project_id, expected_type="model") as path:
                payload = _joblib.load(path)
            model = payload.get("model")
            feature_columns = [
                item["name"]
                for item in (payload.get("feature_schema") or [])
                if item.get("name")
            ]
            new_threshold = float((payload.get("score_stats") or {}).get("threshold_score") or 0.0)
            if model is None or not feature_columns:
                continue
            features = shard_rows.reindex(columns=feature_columns)
            scores = pipeline_anomaly_scores(model, features.to_numpy(dtype=float))
            new_hit_rate = float((scores >= new_threshold).mean())
        except Exception:  # noqa: BLE001 - 单分片证据缺失不阻断其余分片判定
            continue
        shard_reports.append({
            "condition_value": shard_value,
            "rows": int(len(shard_scores)),
            "old_hit_rate": round(float((shard_scores >= old_threshold).mean()), 4),
            "new_hit_rate": round(new_hit_rate, 4),
        })
    if not shard_reports:
        return None
    worst = min(
        shard_reports,
        key=lambda item: float(item["new_hit_rate"]) - float(item["old_hit_rate"]),
    )
    return {
        "old_hit_rate": worst["old_hit_rate"],
        "new_hit_rate": worst["new_hit_rate"],
        "shards": shard_reports,
    }


def _deployment_score_threshold(db, deployment) -> float | None:
    """部署版本关联训练任务的分数阈值（score_stats.threshold_score）。"""
    import json as _json

    from app.models.model_registry import ModelLibrary

    try:
        version = db.query(ModelVersion).filter(
            ModelVersion.id == deployment.model_version_id,
        ).first()
        if version is None or not version.source_model_library_id:
            return None
        library = db.query(ModelLibrary).filter(
            ModelLibrary.id == version.source_model_library_id,
        ).first()
        if library is None or not library.training_job_id:
            return None
        job = db.query(TrainingJob).filter(TrainingJob.id == library.training_job_id).first()
        score_artifact_id = (job.metrics or {}).get("score_artifact_id") if job else None
        if not score_artifact_id:
            return None
        # JSON 列取出的 id 恒为 str：UUID 列绑定必须转 uuid 对象
        artifact = db.query(Artifact).filter(Artifact.id == uuid.UUID(str(score_artifact_id))).first()
        if artifact is None:
            return None
        with build_artifact_service(db).materialize(
            artifact.id, job.project_id, expected_type="report",
        ) as path:
            payload = _json.loads(Path(path).read_text(encoding="utf-8"))
        threshold = payload.get("threshold_score")
        return float(threshold) if threshold is not None else None
    except Exception:
        return None


def complete_retrain_swap(
    db, *, deployment_id, job: TrainingJob, actor_id, model_name: str,
    recipe_id=None,
):
    """Register the best candidate of a finished AutoML job, approve it and
    point the deployment at it. Returns the new ModelVersion, or None when
    the job has no registerable candidates or the candidate fails the bound
    recipe's acceptance gates (spec v0.9 §12.3: 换模候选须过配方门禁).

    项目级换模锁：跨闭环（agent 重放多部署并行）同时到达换模段时，
    model_version_id 指向 + revision 轮换是 last-writer-wins，乱序会把
    部署停在旧版本且事件流失序；同项目换模串行化（无碍单闭环路径）。"""
    deployment_id = _as_uuid(deployment_id) if deployment_id else None
    actor_id = _as_uuid(actor_id)
    project_id = None
    if deployment_id is not None:
        deployment_row = db.query(InferenceDeployment).filter(
            InferenceDeployment.id == deployment_id,
        ).first()
        project_id = deployment_row.project_id if deployment_row is not None else None
    lock_key = f"model-swap-{project_id or 'global'}"
    with lock_for(lock_key):
        return _complete_retrain_swap_locked(
            db, deployment_id=deployment_id, job=job, actor_id=actor_id,
            model_name=model_name, recipe_id=recipe_id,
        )


def _complete_retrain_swap_locked(
    db, *, deployment_id, job: TrainingJob, actor_id, model_name: str,
    recipe_id=None,
):
    deployment_id = _as_uuid(deployment_id) if deployment_id else None
    actor_id = _as_uuid(actor_id)
    registry = ModelRegistryService(artifact_service=build_artifact_service(db))
    candidates = registry.list_registerable_candidates(db, job.id)
    if not candidates:
        return None
    # 换模优先采用任务冠军（metrics.best_candidate）：它已编码引擎的家族排序
    # 与集成采纳决定（采纳时为 "ensemble"），与 AutoML 详情页的最佳模型一致；
    # 冠军不可注册时才退回按指标取分。此前单输出候选指标为空、恒选目录第一个族。
    champion_id = str((job.metrics or {}).get("best_candidate") or "")
    best = next(
        (row for row in candidates if champion_id and str(row.get("candidate_id")) == champion_id),
        None,
    ) or max(candidates, key=candidate_score)
    if recipe_id is not None:
        from app.models.recipe import PipelineRecipeVersion
        from app.services.agent.hard_gates import evaluate_hard_gates

        gate_version = (
            db.query(PipelineRecipeVersion)
            .filter(
                PipelineRecipeVersion.recipe_id == _as_uuid(recipe_id),
                PipelineRecipeVersion.status == "current",
            )
            .first()
        )
        gates = (gate_version.content_json or {}).get("acceptance_gates") if gate_version else None
        if gates:
            gate_report = evaluate_hard_gates(dict(best.get("metrics") or {}), gates=gates)
            if not gate_report.passed:
                # 门禁一票否决：不注册不批准不换模，闭环保持旧模型继续服务。
                return None
    if str((job.metrics or {}).get("task_type") or "") == "anomaly_detection":
        # 无监督换模门禁（技术方案 §3.6）：新模型对基线期已知报警样本（报警
        # 确认弱监督回流的验证集）分数不下降——防重拟合洗掉历史检出能力。
        retention = _anomaly_detection_retention(db, deployment_id, job, best)
        if retention is not None and retention["new_hit_rate"] < retention["old_hit_rate"]:
            return None
    candidate_id = best.get("candidate_id") or best.get("id")
    # registered_models has a (project_id, name) unique constraint — one model
    # entry per retrain cycle, suffixed by job id for determinism/idempotency.
    unique_model_name = f"{model_name}-{str(job.id)[:8]}"
    # metrics 非 dict（测试 Mock/异常载荷）时按无分片处理——迭代 Mock 会炸。
    job_metrics = job.metrics if isinstance(job.metrics, dict) else {}
    condition_bundles = [
        bundle for bundle in job_metrics.get("condition_bundles") or []
        if isinstance(bundle, dict) and bundle.get("model_artifact_id")
    ]
    is_condition_sharded = (
        str(job_metrics.get("task_type") or "") == "anomaly_detection"
        and bool(condition_bundles)
    )
    shard_entries: list[dict] = []
    if is_condition_sharded:
        # 工况分片挂载（§6.3）：每个 bundle 独立注册版本（独立 RegisteredModel
        # 条目 + 段 artifact 信任链），rows 降序——首个即「默认分片」（训练量
        # 最大，ConditionValueRouter 未命中回退它）。
        shard_entries = _register_condition_shard_versions(
            db,
            registry,
            job=job,
            bundles=condition_bundles,
            base_model_name=unique_model_name,
            actor_id=actor_id,
        )
        version = shard_entries[0]["version"]
    else:
        version, _created = registry.register_automl_candidate(
            db,
            task_id=job.id,
            candidate_id=candidate_id,
            model_name=unique_model_name,
            actor_id=actor_id,
            idempotency_key=f"closed-loop-{job.id}",
        )
    # 幂等重放（同一 job 再次换模）时版本可能已批准，重复 approve 会报状态冲突。
    if version is not None and version.approval_status != "approved":
        registry.transition_model_version(db, version.id, "approve", actor_id)
    for entry in shard_entries:
        entry_version = entry["version"]
        if entry_version.approval_status != "approved":
            registry.transition_model_version(db, entry_version.id, "approve", actor_id)
    if deployment_id is not None:
        deployment = db.query(InferenceDeployment).filter(
            InferenceDeployment.id == deployment_id,
        ).first()
        if deployment is not None:
            deployment.model_version_id = version.id
            if shard_entries:
                # 分片换模同时声明工况路由列（迁移 20261112_100）：部署从此
                # 进入工况分片路由模式（predict 按记录工况值选分片）。
                condition_column = str((job.metrics or {}).get("condition_column") or "").strip()
                if condition_column:
                    deployment.condition_column = condition_column
            # 换模跟随的另一半：闭环的特征脚本必须跟到新配方的 S2 脚本——
            # 新模型吃新派生特征，回流行仍按旧脚本变换会缺特征列（实测换模
            # 后 predict 全量 422「缺少模型特征列：ron_delta, …」）。
            if recipe_id is not None:
                from app.models.demo_loop import DemoLoopConfig as _Loop

                _loop = db.query(_Loop).filter(
                    _Loop.deployment_id == deployment.id,
                ).first()
                if _loop is not None:
                    from app.services.agent.recipe import get_current_version as _gcv
                    from app.services.agent.servitize import (
                        _bridge_feature_script as _bridge,
                    )

                    try:
                        _content = dict(_gcv(db, _as_uuid(recipe_id)).content_json or {})
                    except Exception:  # noqa: BLE001 - 脚本跟随失败不影响换模
                        _content = {}
                    _script = str(_content.get("feature_script") or "").strip()
                    if _script:
                        _loop.feature_script = _bridge(_script)
                        _loop.feature_engineering_mode = "script"
                        db.flush()
            # 运行时规格与路由都从最新 stable revision 的 target 取模，revision
            # 与其 runtime_key 不可变；换模必须轮换 revision，否则运行时永远
            # 指向旧模型。若最新 stable 已指向该版本（幂等重放）则不再轮换。
            stable = db.query(DeploymentRevision).filter(
                DeploymentRevision.deployment_id == deployment.id,
                DeploymentRevision.status == "stable",
            ).order_by(DeploymentRevision.revision_number.desc()).first()
            if shard_entries:
                # 分片幂等判定按 targets 集合（版本+工况值）整体比对：同一 job
                # 重放时 stable 已挂全套分片 targets 则不再轮换。
                desired_shards = {
                    (str(entry["version"].id), entry["condition_value"])
                    for entry in shard_entries
                }
                already_stable = stable is not None and {
                    (str(target.model_version_id), target.condition_value)
                    for target in (stable.targets or ())
                } == desired_shards
            else:
                already_stable = stable is not None and any(
                    target.model_version_id == version.id for target in (stable.targets or ())
                )
            if stable is not None and not already_stable:
                stable.status = "superseded"
                latest = db.query(DeploymentRevision.revision_number).filter(
                    DeploymentRevision.deployment_id == deployment.id,
                ).order_by(DeploymentRevision.revision_number.desc()).first()
                revision = DeploymentRevision(
                    deployment_id=deployment.id,
                    revision_number=int(latest[0]) + 1,
                    strategy="immediate",
                    status="stable",
                    created_by_id=actor_id,
                )
                db.add(revision)
                db.flush()
                if shard_entries:
                    total_rows = sum(int(entry["rows"] or 0) for entry in shard_entries) or len(shard_entries)
                    remaining = 10000
                    for index, entry in enumerate(shard_entries):
                        if index == len(shard_entries) - 1:
                            weight = remaining
                        else:
                            weight = int(round(10000 * int(entry["rows"] or 0) / total_rows))
                            remaining -= weight
                        db.add(DeploymentTarget(
                            revision_id=revision.id,
                            model_version_id=entry["version"].id,
                            weight_bps=max(weight, 0),
                            role="stable",
                            condition_value=entry["condition_value"],
                        ))
                else:
                    db.add(DeploymentTarget(
                        revision_id=revision.id,
                        model_version_id=version.id,
                        weight_bps=10000,
                        role="stable",
                    ))
                db.flush()
    if hasattr(version, "_sa_instance_state"):
        db.commit()
        db.refresh(version)
    if deployment_id is not None:
        # Revision 已提交后再加载运行时；失败不回滚换模（推理回退进程内）。
        _best_effort_runtime_start(deployment_id)
    return version


def _best_effort_runtime_start(deployment_id) -> bool:
    try:
        from app.tasks.inference_tasks import build_inference_deployment_service

        service = build_inference_deployment_service()
    except Exception:  # noqa: BLE001 - runtime 未配置时静默跳过
        return False
    session = SessionLocal()
    try:
        service.start(session, deployment_id)
        return True
    except Exception:  # noqa: BLE001 - 加载失败保留换模，由 reconcile/回退兜底
        return False
    finally:
        session.close()
