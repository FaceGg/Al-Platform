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


def _load_dataset_frame(db, run: AgentRun):
    import pandas as pd

    from app.services.artifact_service import build_artifact_service

    if run.dataset_artifact_id is None:
        raise AgentRunNotExecutable("dataset_artifact_id missing")
    service = build_artifact_service(db)
    artifact = service.resolve(
        str(run.dataset_artifact_id), run.project_id, expected_type="dataset"
    )
    with service.storage.open(artifact.storage_uri) as handle:
        payload = handle.read()
    frame = pd.read_csv(io.BytesIO(payload))
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
    """
    import pandas as pd
    from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import f1_score, recall_score
    from sklearn.model_selection import train_test_split
    from sklearn.preprocessing import LabelEncoder

    frame = feature_frame if isinstance(feature_frame, pd.DataFrame) else pd.DataFrame(feature_frame)
    labels = LabelEncoder().fit_transform([str(value) for value in y])
    minority = 1 if (labels == 1).mean() <= 0.5 else 0
    numeric = frame.select_dtypes(include=["number"]).fillna(0.0)
    categorical = frame.select_dtypes(exclude=["number"]).astype(str)
    if not categorical.empty and categorical.shape[1]:
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
            n_estimators=120, min_samples_leaf=2, class_weight="balanced", random_state=7
        ),
        "hist_gb": HistGradientBoostingClassifier(max_iter=120, random_state=7),
    }
    scored = []
    for name, model in families.items():
        try:
            model.fit(X_train, y_train)
            proba = model.predict_proba(X_test)[:, list(model.classes_).index(minority)]
            preds = (proba >= 0.5).astype(int)
            recall = float(recall_score(y_test == minority, preds, zero_division=0))
            f1 = float(f1_score(y_test == minority, preds, zero_division=0))
        except Exception:  # noqa: BLE001 - 单家族失败不拖垮整个 S3
            continue
        scored.append((name, model, recall, f1))
    if not scored:
        return {"metrics": {}, "topk_metrics": [], "importance": []}
    scored.sort(key=lambda item: item[2], reverse=True)
    best_name, best, best_recall, best_f1 = scored[0]
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
    return {
        "metrics": {"recall_minority": round(best_recall, 4), "f1": round(best_f1, 4)},
        "topk_metrics": [
            {"recall_minority": round(recall, 4)} for _n, _m, recall, _f in scored
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
            from app.database import SessionLocal

            db = SessionLocal()
            try:
                run = db.get(AgentRun, UUID(str(run_id)))
                if run is not None and run.status in ("pending", "running"):
                    run.status = "waiting_escalate"
                    run.error_code = "AGENT_EXECUTOR_CRASHED"
                    db.commit()
            finally:
                db.close()

    thread = threading.Thread(target=_worker, name="agent-run-%s" % str(run_id)[:8], daemon=True)
    thread.start()
