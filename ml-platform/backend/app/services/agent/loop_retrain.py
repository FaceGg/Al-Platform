"""闭环「智能体重训模式」（P1，DEVELOPMENT_PLAN §闭环智能体重训）。

retrain_mode=agent 时，报错回流达到增量阈值不再直接派引擎 AutoML，而是
复用部署绑定的固化配方重放智能体全流程（S1 分析 → S2 特征（沙箱）→
S3 轻量训练 → S4 硬门禁+LLM 评审），验收通过后仍由平台引擎在重放物化
的合并数据上铸造部署模型并换模（配方门禁一票否决兜底）。

与纯引擎重训的差异化价值：每次重放既消费经验（S1/S4 注入）也沉淀经验
（终态蒸馏 + 置信度闭环），特征/算法决策随回流数据演化。

护栏（防突发回流连环重训，最坏情况行为收敛）：
- 增量边沿触发：error_count - trained_baseline >= threshold；基线仅在
  换模成功时推进（失败/门禁否决不推进，回流信号不作废，熔断兜底）；
- 部署级单飞：一条闭环同一时刻最多一个重放轮（阻塞后续触发，轮次终态
  后统一评估一次追赶——用全量积累而非第二个阈值额度）；
- 项目级并发上限（默认 2）：跨部署并行重放的资源护栏（LLM/CPU/铸造）；
- 冷却期（agent 模式）：轮次终态后最小间隔；
- 24h 滚动窗口熔断（默认 3 次）：触顶停止自动触发，转管理员在环。

数据：报错+按比例正确+配置数据集按稳定顺序合并、回流行自动标注后物化
为单个工件（轻量训练器没有引擎侧惰性标注，必须物化时完成）——该工件
同时作为引擎铸造段的输入，全链一致。

快照合同：配方版本 content 必须含 guidance（UserGuidance dict）与
source_run_id；缺失 = DEMO_LOOP_AGENT_RECIPE_INVALID fail-closed，不静默
降级为引擎模式（对源 run 重新固化即可回填，fixate 端点已支持）。

无人值守合同：重放 guidance 剥离 pause_at_stages、强制 auto_servitize
=False——换模由闭环接管，不走「项目内最新 running 部署」启发式。
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.config import settings
from app.models.agent_run import AgentRun
from app.models.demo_loop import DemoLoopConfig, DemoLoopEvent

logger = logging.getLogger(__name__)

AGENT_RETRAIN_STATUSES = ("agent_running",)


def finish_agent_cycle(config: DemoLoopConfig) -> None:
    """agent 重放轮终态收尾（成功换模/门禁否决/失败/取消/超时统一调用）：

    清理重放引用；agent 模式进入冷却期（成功路径的基线推进由换模侧单独
    负责——失败/否决不推进）。引擎模式仅清引用（本就为 None，无副作用）。
    """
    config.retrain_agent_run_id = None
    config.retrain_agent_started_at = None
    if (getattr(config, "retrain_mode", None) or "engine") == "agent":
        cooldown = int(getattr(settings, "agent_retrain_cooldown_minutes", 30))
        config.retrain_cool_until = _naive_utcnow() + timedelta(minutes=cooldown)


def _naive_utcnow() -> datetime:
    """DB DateTime 列存 naive UTC（与 demo_loop.refresh 的年龄比较一致）。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _emit(db: Session, config: DemoLoopConfig, event_type: str, message: str,
          severity: str = "info", payload: dict | None = None) -> None:
    db.add(DemoLoopEvent(
        config_id=config.id,
        event_type=event_type[:32],
        severity=severity,
        message=message,
        payload=payload or {},
    ))


def _notify_admins(db: Session, config: DemoLoopConfig, title: str, body: str,
                   event_type: str, payload: dict | None = None) -> None:
    from app.services.closed_loop_actions import notify_project_admins

    try:
        notify_project_admins(db, config.project_id, title=title, body=body,
                              event_type=event_type, payload=payload or {})
    except Exception:  # noqa: BLE001 - 通知失败不阻断闭环主链
        logger.warning("agent retrain admin notify failed", exc_info=True)


class AgentRetrainError(LookupError):
    """稳定错误码包装（message 即 code，调用方转事件文案）。"""


def _resolve_target_column(db: Session, config: DemoLoopConfig) -> str:
    target = (config.retrain_target_column or "").strip()
    if target:
        return target
    from app.services.demo_loop import DemoLoopService

    target = DemoLoopService(db)._deployment_default_target(config)
    if not target:
        raise AgentRetrainError("DEMO_LOOP_RETRAIN_TARGET_MISSING")
    return target


def _load_guidance_snapshot(db: Session, config: DemoLoopConfig) -> dict:
    """读取配方当前版本的 guidance 快照；缺失 fail-closed。"""
    from app.services.agent.recipe import RecipeNotFound, get_current_version

    recipe_id = getattr(config, "retrain_agent_recipe_id", None)
    if recipe_id is None:
        raise AgentRetrainError("DEMO_LOOP_AGENT_RECIPE_UNBOUND")
    try:
        version = get_current_version(db, config.retrain_agent_recipe_id)
    except (RecipeNotFound, LookupError, ValueError) as error:
        raise AgentRetrainError("DEMO_LOOP_AGENT_RECIPE_MISSING") from error
    content = dict(version.content_json or {})
    guidance = content.get("guidance")
    if not isinstance(guidance, dict) or not guidance:
        raise AgentRetrainError("DEMO_LOOP_AGENT_RECIPE_INVALID")
    return guidance


def _prepare_replay_guidance(snapshot: dict) -> dict:
    """快照 → 无人值守重放 guidance：合同校验 + 剥逐步暂停、关自动服务化。

    快照来自固化时的 UserGuidance（已校验），此处再验一道防手改配方内容：
    不合法 = fail-closed（DEMO_LOOP_AGENT_GUIDANCE_INVALID），不静默放行。
    """
    from pydantic import ValidationError

    from app.services.agent.contracts import UserGuidance

    try:
        guidance = UserGuidance.model_validate(snapshot).model_dump()
    except ValidationError as error:
        logger.warning("agent retrain guidance snapshot invalid: %s", error.errors()[:4])
        raise AgentRetrainError("DEMO_LOOP_AGENT_GUIDANCE_INVALID") from error
    guidance.pop("pause_at_stages", None)
    guidance.pop("auto_servitize", None)
    return guidance


def _circuit_break_state(db: Session, config: DemoLoopConfig) -> int:
    """24h 滚动窗口内已触发的 agent 重放次数（按事件计）。"""
    since = _naive_utcnow() - timedelta(hours=24)
    return db.query(DemoLoopEvent).filter(
        DemoLoopEvent.config_id == config.id,
        DemoLoopEvent.event_type == "retrain_agent_triggered",
        DemoLoopEvent.created_at >= since,
    ).count()


def _resolve_dataset_ids(config: DemoLoopConfig) -> list[str]:
    from app.services.closed_loop_actions import resolve_retrain_dataset_ids

    return resolve_retrain_dataset_ids(config)


def _materialize_merged_artifact(db: Session, config: DemoLoopConfig,
                                 name_hint: str):
    """合并+自动标注后物化为单个数据集工件（重放与铸造共用同一输入）。"""
    import pandas as pd

    from app.services.artifact_service import build_artifact_service
    from app.services.closed_loop_actions import build_retrain_frame

    dataset_ids = _resolve_dataset_ids(config)
    if not dataset_ids:
        raise AgentRetrainError("DEMO_LOOP_RETRAIN_DATASET_MISSING")
    service = build_artifact_service(db)
    datasets = [
        service.resolve(_as_uuid(raw), config.project_id, expected_type="dataset")
        for raw in dataset_ids
    ]
    frames = []
    for source in datasets:
        with service.materialize(source.id, config.project_id,
                                 expected_type="dataset") as path:
            frames.append(pd.read_csv(path))
    target = _resolve_target_column(db, config)
    frame = build_retrain_frame(frames, target)
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        merged_path = Path(tmp) / "agent-retrain-merged.csv"
        frame.to_csv(merged_path, index=False)
        artifact = service.create_from_file(
            config.project_id, merged_path, f"{name_hint}-合并数据集", "dataset",
            metadata={"source": "agent-retrain-merge",
                      "datasets": [str(item.id) for item in datasets],
                      "row_count": int(len(frame)),
                      "column_count": int(len(frame.columns))},
        )
    return artifact


def _as_uuid(value):
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


def trigger_agent_retrain(db: Session, config: DemoLoopConfig, actor_id) -> None:
    """发起一轮智能体重放（调用方已过增量阈值与部署级单飞闸门）。

    冷却期未到 / 项目并发已满 → 静默返回（正常性跳过，不刷事件）；
    熔断触顶 → 首次触顶发 critical 事件 + 管理员通知，其后静默；
    快照缺失 / 数据缺失 → AgentRetrainError（调用方转 retrain_failed 事件）。
    """
    now = _naive_utcnow()
    cool_until = getattr(config, "retrain_cool_until", None)
    if cool_until is not None and now < cool_until:
        return
    triggered = _circuit_break_state(db, config)
    if triggered >= int(settings.agent_retrain_daily_limit):
        # 首次触顶：一次性熔断事件 + 管理员通知（24h 窗口内已熔断则静默积累）。
        since = _naive_utcnow() - timedelta(hours=24)
        already_broken = (
            db.query(DemoLoopEvent)
            .filter(
                DemoLoopEvent.config_id == config.id,
                DemoLoopEvent.event_type == "retrain_agent_circuit_break",
                DemoLoopEvent.created_at >= since,
            )
            .count()
        )
        if not already_broken:
            _emit(db, config, "retrain_agent_circuit_break",
                  f"24 小时内智能体重训已触发 {triggered} 次，达到熔断上限，"
                  "自动触发已暂停；报错数据继续积累，请人工评估后再恢复。",
                  severity="critical", payload={"triggered": triggered})
            _notify_admins(
                db, config,
                title=f"【{config.name}】智能体重训熔断",
                body=(f"闭环「{config.name}」24 小时内已触发 {triggered} 次智能体重训，"
                      "已达熔断上限。持续高报错可能不是重训能解决的问题，请人工评估。"),
                event_type="demo_loop.agent_retrain_break",
                payload={"config_id": str(config.id), "triggered": triggered},
            )
            db.commit()
        return
    # 项目级并发上限（跨部署资源护栏）：同项目其他闭环正在重放 → 让路。
    busy = (
        db.query(DemoLoopConfig)
        .filter(
            DemoLoopConfig.project_id == config.project_id,
            DemoLoopConfig.id != config.id,
            DemoLoopConfig.retrain_agent_run_id.isnot(None),
            DemoLoopConfig.retrain_status.in_(AGENT_RETRAIN_STATUSES),
        )
        .count()
    )
    if busy >= int(settings.agent_retrain_project_concurrency):
        return

    guidance = _prepare_replay_guidance(_load_guidance_snapshot(db, config))
    target_column = _resolve_target_column(db, config)
    cycle = uuid.uuid4().hex[:8]
    artifact = _materialize_merged_artifact(
        db, config, f"{config.name}-智能体重训-{config.error_count}")

    # 源 run 的 LLM 档案/预算沿用（配方快照的 source_run_id；缺省走平台默认）。
    source_run = None
    from app.services.agent.recipe import get_current_version

    version = get_current_version(db, config.retrain_agent_recipe_id)
    source_run_id = (version.content_json or {}).get("source_run_id")
    if source_run_id:
        try:
            source_run = db.get(AgentRun, uuid.UUID(str(source_run_id)))
        except (TypeError, ValueError):
            source_run = None

    run = AgentRun(
        project_id=config.project_id,
        dataset_artifact_id=artifact.id,
        target_column=target_column,
        llm_profile_id=source_run.llm_profile_id if source_run is not None else None,
        llm_model_id=source_run.llm_model_id if source_run is not None else None,
        token_budget=source_run.token_budget if source_run is not None else None,
        status="pending",
        current_stage="s1",
        memory_json={},
        result_json={},
        guidance_json=guidance,
        created_by=actor_id,
    )
    db.add(run)
    db.flush()
    config.retrain_status = "agent_running"
    config.retrain_agent_run_id = run.id
    config.retrain_agent_started_at = now
    if not config.retrain_target_column:
        config.retrain_target_column = target_column
    db.commit()

    from app.services.agent.executor import AgentRunNotExecutable, launch_agent_run

    try:
        launch_agent_run(run.id, actor_id=actor_id)
    except AgentRunNotExecutable as error:
        run.status = "waiting_escalate"
        run.error_code = "AGENT_RUN_NOT_EXECUTABLE"
        run.result_json = {"executor_error": str(error)}
        db.commit()
    except Exception:  # noqa: BLE001 - 派发失败按重放失败处理，闭环保活
        logger.exception("agent retrain launch failed for run %s", run.id)
        config.retrain_status = "failed"
        finish_agent_cycle(config)
        db.commit()
        _emit(db, config, "retrain_agent_failed",
              "智能体重训任务派发失败（执行器不可用）", severity="critical")
        db.commit()
        return
    _emit(db, config, "retrain_agent_triggered",
          f"报错数据达到 {config.error_count} 行，智能体重训已触发"
          f"（重放配方 {str(config.retrain_agent_recipe_id)[:8]}，合并数据 "
          f"{(artifact.metadata_ or {}).get('row_count', '?')} 行）",
          severity="warning",
          payload={"agent_run_id": str(run.id),
                   "dataset_artifact_id": str(artifact.id),
                   "error_count": int(config.error_count or 0)})
    db.commit()


def poll_agent_retrain(db: Session, config: DemoLoopConfig, actor_id) -> bool:
    """refresh_retrain_status 的 agent 分支。返回 True 表示本调用已处理
    （调用方不再进入引擎分支）；铸造派发后状态机交还引擎路径。"""
    from app.services.agent.recipe import (
        build_fixation_content,
        create_recipe,
    )
    from app.services.closed_loop_actions import trigger_retrain_job

    run = db.get(AgentRun, config.retrain_agent_run_id)
    if run is None:
        config.retrain_status = "failed"
        finish_agent_cycle(config)
        _emit(db, config, "retrain_agent_failed",
              "智能体重训任务记录丢失（可能已被清扫）", severity="warning")
        db.commit()
        return True

    status = run.status
    if status == "accepted":
        if config.retrain_job_id is not None:
            # 铸造已派发（本调用前的并发轮询已处理过）：交还引擎分支。
            return False
        cycle = uuid.uuid4().hex[:8]
        content = build_fixation_content(run, run.memory_json or {})
        recipe = create_recipe(
            db,
            project_id=config.project_id,
            name=(f"{config.name}-agent-{cycle}")[:64],
            content=content,
            change_note="agent-retrain auto fixation (closed loop)",
            created_by=actor_id,
        )
        # 每轮配方 id 记入 run 档案：换模段读取并传给配方门禁兜底。
        run_result = dict(run.result_json or {})
        run_result["fixated_recipe_id"] = str(recipe.id)
        run.result_json = run_result
        db.flush()
        # 铸造段：引擎 job 用重放物化的合并工件 + 配方白名单/集成（D5：
        # 铸造冠军与验收冠军同族；空 = 全族，行为与引擎模式一致）。
        algorithm_ids = [
            str(item) for item in (content.get("retrain_algorithm_ids") or [])
        ] or (list(getattr(config, "retrain_algorithm_ids", None) or []) or None)
        retrain_ensemble = dict(content.get("retrain_ensemble") or {})
        ensemble = (
            {"enabled": True, "top_k": int(retrain_ensemble.get("top_k") or 3)}
            if retrain_ensemble.get("enabled")
            else (
                {"enabled": True, "top_k": int(config.retrain_ensemble_top_k or 3)}
                if getattr(config, "retrain_ensemble_enabled", False)
                else None
            )
        )
        casting_ids = (
            [str(run.dataset_artifact_id)] if run.dataset_artifact_id is not None
            else _resolve_dataset_ids(config)
        )
        job = trigger_retrain_job(
            db,
            project_id=config.project_id,
            actor_id=actor_id,
            experiment_name=f"{config.name}-智能体铸造-{config.error_count}-{cycle}",
            job_name=f"{config.name}-智能体铸造-{config.error_count}-{cycle}",
            dataset_artifact_ids=casting_ids,
            target_column=config.retrain_target_column or run.target_column,
            max_trials=config.retrain_max_trials,
            ensemble=ensemble,
            algorithm_ids=algorithm_ids,
            input_columns=list(getattr(config, "retrain_input_columns", None) or []) or None,
        )
        config.retrain_job_id = job.id
        config.retrain_status = "queued"
        _emit(db, config, "retrain_agent_accepted",
              f"智能体重放验收通过（轮次 {run.round_count}，配方 {recipe.name}），"
              "引擎铸造部署模型中", severity="info",
              payload={"agent_run_id": str(run.id), "recipe_id": str(recipe.id),
                       "job_id": str(job.id)})
        _emit(db, config, "retrain_casting_started",
              f"铸造任务已触发（{job.params['max_trials']} 组试验）",
              severity="warning", payload={"job_id": str(job.id)})
        db.commit()
        return True

    if status in {"failed", "cancelled", "waiting_escalate"}:
        reason = (run.error_code or "") if status != "cancelled" else "已取消"
        config.retrain_status = "failed"
        finish_agent_cycle(config)
        # 基线不推进：旧模型继续服务，回流信号不作废（熔断/冷却兜底）。
        if status == "waiting_escalate":
            _emit(db, config, "retrain_agent_rejected",
                  f"智能体重放未通过验收或已升级人工（{reason or 'waiting_escalate'}），"
                  "不换模，旧模型继续服务", severity="critical",
                  payload={"agent_run_id": str(run.id), "error_code": run.error_code})
            _notify_admins(
                db, config,
                title=f"【{config.name}】智能体重训未通过验收",
                body=(f"闭环「{config.name}」的重放任务未通过验收（{reason}），"
                      "已保持旧模型服务；报错数据继续积累，下一轮将带全量数据重试。"),
                event_type="demo_loop.agent_retrain_rejected",
                payload={"config_id": str(config.id), "agent_run_id": str(run.id)},
            )
        else:
            _emit(db, config, "retrain_agent_failed",
                  f"智能体重放失败（{reason or status}），不换模，旧模型继续服务",
                  severity="critical", payload={"agent_run_id": str(run.id)})
        db.commit()
        return True

    # pending / running / waiting_guidance：仍在执行。超时熔断。
    started = config.retrain_agent_started_at
    if started is not None:
        elapsed = (_naive_utcnow() - started).total_seconds()
        if elapsed > int(settings.agent_retrain_poll_max_age_seconds):
            config.retrain_status = "failed"
            finish_agent_cycle(config)
            _emit(db, config, "retrain_agent_timeout",
                  f"智能体重放超过 {int(elapsed // 60)} 分钟未终态，按失败处理"
                  "（任务留档，不换模）", severity="critical",
                  payload={"agent_run_id": str(run.id), "elapsed_seconds": int(elapsed)})
            db.commit()
            return True
    config.retrain_status = "agent_running"
    return True
