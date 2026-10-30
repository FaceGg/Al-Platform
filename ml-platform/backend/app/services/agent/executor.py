"""Agent run executor (P0 wiring): run rows created by the wizard actually run.

`execute_agent_run` assembles everything a run needs (dataset frame from the
artifact store, deterministic profile, gateway-resolved LLM config, guidance
from the submission) and drives :class:`AgentRunner` to a terminal state with
the real lightweight trainer (stratified split → few sklearn families → best
by minority recall). `launch_agent_run` does the same on a daemon thread so
the API returns immediately; status/progress is persisted on the run row.
"""

from __future__ import annotations

import io
import threading
from uuid import UUID

from app.config import settings
from app.models.agent_run import AgentRun


class AgentRunNotExecutable(RuntimeError):
    """The run row lacks what the executor needs (dataset/target/profile)."""


def _load_frame_for(db, artifact_id, project_id):
    """Load a dataset artifact as a DataFrame (shared by executor + wizard API)."""
    import pandas as pd

    from app.services.artifact_service import build_artifact_service

    service = build_artifact_service(db)
    artifact = service.resolve(
        str(artifact_id), project_id, expected_type="dataset"
    )
    with service.storage.open(artifact.storage_uri) as handle:
        payload = handle.read()
    return pd.read_csv(io.BytesIO(payload))


def _load_dataset_frame(db, run: AgentRun):
    frame = _load_frame_for(db, run.dataset_artifact_id, run.project_id)
    if run.target_column and run.target_column not in frame.columns:
        raise AgentRunNotExecutable(
            "target column %s not in dataset" % run.target_column[:64]
        )
    return frame


def _resolve_config(db, run: AgentRun):
    from app.services.llm_gateway import resolve_profile

    profile_id = str(run.llm_profile_id) if run.llm_profile_id else None
    config = resolve_profile(db, profile_id=profile_id, purpose="agent_run")
    if not config.api_key:
        raise AgentRunNotExecutable(
            "LLM profile has no api key; configure the gateway first"
        )
    return config


def lightweight_trainer(feature_frame, y, hints: dict) -> dict:
    """S3 真训练（轻量）：分层切分 + 少量 sklearn 家族，按少数类召回选优。

    返回 Runner/S4 需要的形状：metrics / topk_metrics / importance。

    行/宽双重上限对齐"轻量"定位：全量数据上高基数类别经 get_dummies 会
    展开成数千列宽矩阵，随机森林单核可跑数十分钟（8381156a 事故——
    非挂死，是无限时慢算）。分层抽样 2 万行 + 类别编码截断 top 200。
    """
    import pandas as pd
    from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import (
        accuracy_score,
        f1_score,
        precision_score,
        recall_score,
        roc_auc_score,
    )
    from sklearn.model_selection import train_test_split
    from sklearn.preprocessing import LabelEncoder

    frame = feature_frame if isinstance(feature_frame, pd.DataFrame) else pd.DataFrame(feature_frame)
    labels = LabelEncoder().fit_transform([str(value) for value in y])
    minority = 1 if (labels == 1).mean() <= 0.5 else 0
    if len(labels) > 20000:
        keep, _ = train_test_split(
            range(len(labels)), train_size=20000, random_state=7,
            stratify=labels,
        )
        frame = frame.iloc[keep].reset_index(drop=True)
        labels = labels[keep]
    numeric = frame.select_dtypes(include=["number"]).fillna(0.0)
    categorical = frame.select_dtypes(exclude=["number"]).astype(str)
    if not categorical.empty and categorical.shape[1]:
        # 每列只保留 top 200 类别，其余归并 __other__，防宽矩阵爆炸。
        for column in categorical.columns:
            top = categorical[column].value_counts().head(200).index
            categorical[column] = categorical[column].where(
                categorical[column].isin(top), "__other__"
            )
        X = pd.get_dummies(categorical, dummy_na=True).join(numeric)
    else:
        X = numeric
    stratify = labels if min((labels == c).sum() for c in set(labels)) >= 2 else None
    X_train, X_test, y_train, y_test = train_test_split(
        X, labels, test_size=0.25, random_state=7, stratify=stratify
    )
    families = {
        "logistic": LogisticRegression(max_iter=500, class_weight="balanced"),
        "random_forest": RandomForestClassifier(
            n_estimators=120, min_samples_leaf=2, class_weight="balanced",
            random_state=7, n_jobs=-1,
        ),
        "hist_gb": HistGradientBoostingClassifier(max_iter=120, random_state=7),
    }
    scored = []
    for name, model in families.items():
        try:
            model.fit(X_train, y_train)
            proba = model.predict_proba(X_test)[:, list(model.classes_).index(minority)]
            preds = (proba >= 0.5).astype(int)
            truth = y_test == minority
            recall = float(recall_score(truth, preds, zero_division=0))
            f1 = float(f1_score(truth, preds, zero_division=0))
            precision = float(precision_score(truth, preds, zero_division=0))
            accuracy = float(accuracy_score(y_test, preds))
            # roc_auc 需要测试集两类齐全；单类测试集下无定义 → 置 None 跳过门禁。
            roc_auc = (
                float(roc_auc_score(truth.astype(int), proba))
                if len(set(y_test)) > 1
                else None
            )
        except Exception:  # noqa: BLE001 - 单家族失败不拖垮整个 S3
            continue
        scored.append((name, model, recall, f1, precision, accuracy, roc_auc))
    if not scored:
        return {"metrics": {}, "topk_metrics": [], "importance": []}
    scored.sort(key=lambda item: item[2], reverse=True)
    best_name, best, best_recall, best_f1, best_precision, best_accuracy, best_roc_auc = scored[0]
    if hasattr(best, "feature_importances_"):
        weights = best.feature_importances_
    else:
        weights = abs(getattr(best, "coef_", [0])[0]) if best_name == "logistic" else [0]
    importance = sorted(
        (
            {"feature": str(name), "importance": float(weight)}
            for name, weight in zip(X.columns, weights)
        ),
        key=lambda item: -item["importance"],
    )[:12]
    metrics = {
        "recall_minority": round(best_recall, 4),
        "f1": round(best_f1, 4),
        "precision": round(best_precision, 4),
        "accuracy": round(best_accuracy, 4),
    }
    if best_roc_auc is not None:
        metrics["roc_auc"] = round(best_roc_auc, 4)
    return {
        "metrics": metrics,
        "topk_metrics": [
            {"recall_minority": round(recall, 4)}
            for _n, _m, recall, _f, _p, _a, _r in scored
        ],
        "importance": importance,
    }


def execute_agent_run(run_id, actor_id=None) -> AgentRun:
    """Synchronous execution — used by the launcher thread and by tests."""
    from app.database import SessionLocal
    from app.services.agent.profile_data import profile_data
    from app.services.agent.runner import AgentRunner

    db = SessionLocal()
    try:
        run = db.get(AgentRun, UUID(str(run_id)))
        if run is None:
            raise AgentRunNotExecutable("run not found: %s" % run_id)
        if run.status not in ("pending", "running", "waiting_guidance"):
            return run
        # 记录进程内执行心跳：恢复扫描据此判断 run 是否仍在执行。
        from app.tasks.time_utils import utcnow as _agent_utcnow

        run.heartbeat_at = _agent_utcnow()
        db.commit()
        frame = _load_dataset_frame(db, run)
        config = _resolve_config(db, run)
        profile = profile_data(frame, target=run.target_column)
        runner = AgentRunner(
            db,
            run=run,
            config=config,
            profile_report=profile,
            dataset_frame=frame,
            guidance=dict(run.guidance_json or {}),
            trainer=lightweight_trainer,
            actor=actor_id or run.created_by,
        )
        return runner.run_to_completion()
    finally:
        db.close()


def launch_agent_run(run_id, actor_id=None) -> None:
    """Fire-and-forget daemon thread; all state lands on the run row."""

    def _worker():
        try:
            execute_agent_run(run_id, actor_id=actor_id)
        except Exception:  # noqa: BLE001 - 后台线程崩溃也要在 run 行留下尸检信息
            import logging
            import traceback as _traceback

            from app.database import SessionLocal

            logging.getLogger(__name__).exception(
                "agent executor thread crashed for run %s", run_id
            )
            db = SessionLocal()
            try:
                run = db.get(AgentRun, UUID(str(run_id)))
                if run is not None and run.status in ("pending", "running"):
                    run.status = "waiting_escalate"
                    run.error_code = "AGENT_EXECUTOR_CRASHED"
                    # JSON 列变更检测按对象身份：必须写入"新字典"再赋值，
                    # 原地改再赋回同一对象会被 ORM 判为无变化而跳过 UPDATE
                    # （677d973d 崩溃时 escalation 丢失的根因）。
                    memory = dict(run.memory_json or {})
                    memory["escalation"] = {
                        "code": "AGENT_EXECUTOR_CRASHED",
                        "detail": _traceback.format_exc()[-2000:],
                        "round": run.round_count,
                    }
                    run.memory_json = memory
                    db.commit()
            finally:
                db.close()

    thread = threading.Thread(target=_worker, name="agent-run-%s" % str(run_id)[:8], daemon=True)
    thread.start()


def recover_stale_agent_runs(db, stale_after) -> int:
    """把进程重启后遗留的 running 状态 AgentRun 标记为失败。

    判定依据 heartbeat_at：NULL（列出现前的历史行）或早于 stale_after 的行
    都视为已中断。waiting_guidance（暂停等待用户确认）与终态行不参与清扫。
    """
    from sqlalchemy import or_

    from app.tasks.time_utils import utcnow as _sweep_utcnow

    cutoff = _sweep_utcnow() - stale_after
    stale_runs = db.query(AgentRun).filter(
        AgentRun.status == "running",
        or_(
            AgentRun.heartbeat_at.is_(None),
            AgentRun.heartbeat_at < cutoff,
        ),
    ).all()
    for run in stale_runs:
        run.status = "failed"
        run.error_code = "AGENT_RUN_INTERRUPTED"
        # 尸检随行：心跳超时是"为什么死"的第一手信息（执行进程重启/线程
        # 无响应），不留会让详情页只有错误码可看。写新字典（JSON 列身份坑）。
        memory = dict(run.memory_json or {})
        memory["escalation"] = {
            "code": "AGENT_RUN_INTERRUPTED",
            "detail": (
                "heartbeat stale: last beat at "
                f"{run.heartbeat_at.isoformat() if run.heartbeat_at else 'never'}"
                f", cutoff {( _sweep_utcnow() - stale_after).isoformat()}"
                " — 执行进程重启或执行线程无响应，由陈旧恢复清扫标记。"
            ),
            "round": run.round_count,
        }
        run.memory_json = memory
    if stale_runs:
        db.commit()
    return len(stale_runs)
