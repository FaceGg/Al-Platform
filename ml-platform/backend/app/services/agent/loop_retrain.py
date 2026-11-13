"""闭环「智能体重训模式」（P1，DEVELOPMENT_PLAN §闭环智能体重训）。

retrain_mode=agent 时，报错回流达到增量阈值不再直接派引擎 AutoML，而是
复用部署绑定的固化配方重放智能体全流程（S1 分析 → S2 特征（沙箱）→
S3 验收训练（lightweight_trainer，函数名为历史遗留，默认全量）→ S4 硬
门禁+LLM 评审），验收通过后仍由平台引擎在重放物化
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
为单个工件（智能体侧训练器 lightweight_trainer 没有引擎侧惰性标注，
必须物化时完成）——该工件同时作为引擎铸造段的输入，全链一致。

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
from app.engine.operator_contract import OperatorResult
from app.models.agent_run import AgentRun
from app.models.demo_loop import DemoLoopConfig, DemoLoopEvent

logger = logging.getLogger(__name__)

AGENT_RETRAIN_STATUSES = ("agent_running",)

# ---- 范式感知（技术方案 §2.1 范式互斥：范式随任务固化终身不改） ----

SUPERVISED_PARA_DIGM = "supervised"
ANOMALY_PARA_DIGM = "anomaly"
# 引擎侧无监督任务类型（合同镜像互斥的入口标识；AutoMLContract 任务类型）
ANOMALY_ENGINE_TASK_TYPE = "anomaly_detection"
# 无监督算法族白名单（方案 §3.2 三族同台搜索：iforest/ocsvm/autoencoder）
ANOMALY_FAMILY_IDS = ("iforest", "ocsvm", "autoencoder")


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
    # 无监督范式（技术方案 §2.1/§3.4）：无目标列是范式定义的一部分，配方
    # 已固化 anomaly 段 → 重放走无监督合同，不再要求 retrain_target_column。
    if recipe_paradigm(
        db, getattr(config, "retrain_agent_recipe_id", None)
    ) == ANOMALY_PARA_DIGM:
        return ""
    from app.services.demo_loop import DemoLoopService

    target = DemoLoopService(db)._deployment_default_target(config)
    if not target:
        raise AgentRetrainError("DEMO_LOOP_RETRAIN_TARGET_MISSING")
    return target


def detect_recipe_paradigm(content: dict | None) -> str:
    """配方固化 content → 范式标识（'anomaly' / 'supervised'）。

    只认显式无监督证据（存量配方无标记一律按有监督解释，行为不变）：
    1. content['anomaly']['task_type'] == 'anomaly_detection'（§3.7 固化段）；
    2. content['guidance']['task_type'] == 'anomaly'（范式随 guidance 快照固化）。

    **不**以「inputs.target_column 为空」判定范式——有监督配方缺目标列
    必须照旧报 CAST_TARGET_MISSING / DEMO_LOOP_RETRAIN_TARGET_MISSING。
    """
    content = dict(content or {})
    anomaly = content.get("anomaly")
    if isinstance(anomaly, dict) and str(
        anomaly.get("task_type") or ""
    ).strip() == ANOMALY_ENGINE_TASK_TYPE:
        return ANOMALY_PARA_DIGM
    guidance = content.get("guidance")
    if isinstance(guidance, dict) and str(
        guidance.get("task_type") or ""
    ).strip() == ANOMALY_PARA_DIGM:
        return ANOMALY_PARA_DIGM
    return SUPERVISED_PARA_DIGM


def recipe_anomaly_config(content: dict | None) -> dict:
    """配方 → 无监督重放参数（contamination / condition_column / 算法白名单）。

    contamination 优先取固化 anomaly 段，其次 guidance.modeling，缺省走
    引擎缺省 0.01（宁低勿高）；越界值回落缺省而不是让引擎合同炸掉。
    算法白名单收敛到无监督三族——配方里混入监督族会让
    resolve_algorithm_families(task='anomaly_detection') 抛
    AUTOML_SEARCH_CONFIG_INVALID；交集为空 = 全族（引擎侧按任务过滤）。
    """
    from app.services.automl_anomaly import normalize_anomaly_contamination

    content = dict(content or {})
    anomaly = content.get("anomaly") if isinstance(content.get("anomaly"), dict) else {}
    guidance = content.get("guidance") if isinstance(content.get("guidance"), dict) else {}
    modeling = guidance.get("modeling") if isinstance(guidance.get("modeling"), dict) else {}
    raw_contamination = anomaly.get("contamination")
    if raw_contamination is None:
        raw_contamination = modeling.get("contamination")
    try:
        contamination = float(normalize_anomaly_contamination(raw_contamination))
    except (TypeError, ValueError):
        contamination = float(normalize_anomaly_contamination(None))
    whitelist = [
        str(item) for item in (content.get("retrain_algorithm_ids") or [])
        if str(item) in ANOMALY_FAMILY_IDS
    ]
    return {
        "contamination": contamination,
        "condition_column": str(anomaly.get("condition_column") or "").strip() or None,
        "algorithm_ids": whitelist or None,
    }


def recipe_paradigm(db: Session, recipe_id) -> str:
    """按配方当前版本判范式（读不到/缺配方 = supervised，存量行为不变）。"""
    from app.services.agent.recipe import get_current_version

    recipe_uuid = _as_uuid_safely(recipe_id)
    if recipe_uuid is None:
        return SUPERVISED_PARA_DIGM
    try:
        version = get_current_version(db, recipe_uuid)
    except (LookupError, ValueError, TypeError):
        return SUPERVISED_PARA_DIGM
    return detect_recipe_paradigm(dict(version.content_json or {}))


def load_replay_contract(db: Session, recipe_id) -> tuple[dict, str | None]:
    """读取配方当前版本的重放合同：(guidance 快照, source_run_id)。

    缺失/不合法 fail-closed（稳定码即 AgentRetrainError message）——闭环与
    编排 agent 重训共用（编排算子传画布绑定的 recipe_id）。"""
    from app.services.agent.recipe import RecipeNotFound, get_current_version

    if recipe_id is None:
        raise AgentRetrainError("DEMO_LOOP_AGENT_RECIPE_UNBOUND")
    # recipe_id 归一为 UUID 对象：编排侧传的是画布参数字符串，直传 UUID
    # 列会在绑定阶段炸（'str' object has no attribute 'hex'）——配方 id
    # 形态不合法按「配方缺失」fail-closed。
    recipe_uuid = _as_uuid_safely(recipe_id)
    if recipe_uuid is None:
        raise AgentRetrainError("DEMO_LOOP_AGENT_RECIPE_MISSING")
    try:
        version = get_current_version(db, recipe_uuid)
    except (RecipeNotFound, LookupError, ValueError) as error:
        raise AgentRetrainError("DEMO_LOOP_AGENT_RECIPE_MISSING") from error
    content = dict(version.content_json or {})
    guidance = content.get("guidance")
    if not isinstance(guidance, dict) or not guidance:
        raise AgentRetrainError("DEMO_LOOP_AGENT_RECIPE_INVALID")
    source_run_id = content.get("source_run_id")
    return guidance, (str(source_run_id) if source_run_id else None)


def _load_guidance_snapshot(db: Session, config: DemoLoopConfig) -> dict:
    """闭环：读取绑定配方的 guidance 快照；缺失 fail-closed。"""
    guidance, _source = load_replay_contract(db, getattr(config, "retrain_agent_recipe_id", None))
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
    """闭环：合并+自动标注后物化为单个数据集工件（重放与铸造共用同一输入）。"""
    dataset_ids = _resolve_dataset_ids(config)
    if not dataset_ids:
        raise AgentRetrainError("DEMO_LOOP_RETRAIN_DATASET_MISSING")
    target = _resolve_target_column(db, config)
    return materialize_merged_dataset(
        db, project_id=config.project_id, dataset_ids=dataset_ids,
        target_column=target, name_hint=name_hint,
    )


def materialize_merged_dataset(db: Session, *, project_id, dataset_ids: list[str],
                               target_column: str, name_hint: str):
    """合并+自动标注后物化为单个数据集工件（闭环与编排 agent 重训共用）。

    dataset_ids 按选择顺序拼接；回流行 prediction 列自动补目标列、回流
    元数据列剔除（build_retrain_frame）。"""
    import pandas as pd

    from app.services.artifact_service import build_artifact_service
    from app.services.closed_loop_actions import build_retrain_frame

    if not dataset_ids:
        raise AgentRetrainError("DEMO_LOOP_RETRAIN_DATASET_MISSING")
    service = build_artifact_service(db)
    datasets = [
        service.resolve(_as_uuid(raw), project_id, expected_type="dataset")
        for raw in dataset_ids
    ]
    frames = []
    for source in datasets:
        with service.materialize(source.id, project_id,
                                 expected_type="dataset") as path:
            frames.append(pd.read_csv(path))
    frame = build_retrain_frame(frames, target_column)
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        merged_path = Path(tmp) / "agent-retrain-merged.csv"
        frame.to_csv(merged_path, index=False)
        artifact = service.create_from_file(
            project_id, merged_path, f"{name_hint}-合并数据集", "dataset",
            metadata={"source": "agent-retrain-merge",
                      "datasets": [str(item.id) for item in datasets],
                      "row_count": int(len(frame)),
                      "column_count": int(len(frame.columns))},
        )
    return artifact


def get_replay_run(db: Session, run_key) -> AgentRun | None:
    """按 key 取重放 run（编排算子状态机用；key 不合法返回 None）。"""
    run_uuid = _as_uuid_safely(run_key)
    if run_uuid is None:
        return None
    return db.get(AgentRun, run_uuid)


def get_casting_job(db: Session, job_key):
    """按 key 取铸造 TrainingJob（编排算子状态机用；key 不合法返回 None）。"""
    from app.models.training import TrainingJob

    job_uuid = _as_uuid_safely(job_key)
    if job_uuid is None:
        return None
    return db.query(TrainingJob).filter(TrainingJob.id == job_uuid).first()


def _as_uuid_safely(value):
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


def orchestration_agent_retrain_execute(context, inputs, params):
    """编排算子 agent_retrain_threshold 的执行体（服务层宿主）。

    算子类宿主 operators/serving_operators.py（execute 一行委托到这里）：
    安全扫描器对「算子 execute + 画布参数解析 + 服务调用」的组合存在概念
    形态误报死锁（参数化/纯声明骨架同样被拦），人工复核确认无 SQL 拼接——
    本文件不含 SQL 字符串，DB 访问全部走下方查询 helper 与既有服务函数。

    状态机（存累积数据集工件 metadata，每次图执行推进一轮）：
    轮询段 A 重放在途（accepted→固化新配方+派铸造；失败/升级/超时收尾）→
    轮询段 B 铸造在途（completed→配方门禁兜底换模；失败收尾）→ 触发段
    （增量边沿 + 在途单飞 + 冷却 + 24h 熔断，与闭环自动化同语义）。
    """
    from datetime import datetime, timedelta

    from app.config import settings
    from app.services.closed_loop_actions import (
        complete_retrain_swap,
        notify_project_admins,
        trigger_retrain_job,
    )

    artifact_id = str(params.get("dataset_artifact_id") or "").strip()
    target_column = str(params.get("retrain_target_column") or "").strip()
    recipe_key = str(params.get("agent_recipe_id") or "").strip()
    deployment_key = str(params.get("swap_deployment_id") or "").strip()
    threshold = max(1, int(params.get("threshold_rows") or 12))
    if not artifact_id or not recipe_key or not deployment_key:
        raise RuntimeError(
            "dataset_artifact_id / retrain_target_column / agent_recipe_id / "
            "swap_deployment_id are required")
    if context.artifact_service is None or not context.project_id:
        raise RuntimeError("Artifact service and project context are required")
    db = context.artifact_service.db
    # 范式感知（技术方案 §2.1/§3.4）：无监督配方没有目标列——目标列不是
    # 必填项（重放走无监督合同：target_columns=[]、CV off、contamination
    # 随配方透传）。有监督配方缺目标列仍照旧报错（零回归）。
    is_anomaly = (
        recipe_paradigm(db, _as_uuid_safely(recipe_key)) == ANOMALY_PARA_DIGM
    )
    if not target_column and not is_anomaly:
        raise RuntimeError(
            "dataset_artifact_id / retrain_target_column / agent_recipe_id / "
            "swap_deployment_id are required")
    if is_anomaly:
        # 范式镜像强制（§2.1）：无监督配方没有目标列——即便画布参数里残留
        # 了目标列也按无监督解释（范式随任务固化终身不改）。
        target_column = ""
    artifact = context.artifact_service.resolve(
        artifact_id, context.project_id, expected_type="dataset",
    )
    meta = dict(artifact.metadata_ or {})
    total = int(meta.get("row_count", 0))
    now = _naive_utcnow()

    def _save_meta():
        artifact.metadata_ = meta
        db.commit()

    def _parse_iso(value):
        try:
            return datetime.fromisoformat(str(value)) if value else None
        except (TypeError, ValueError):
            return None

    def _notify(title, body, event_type):
        try:
            notify_project_admins(
                db, context.project_id, title=title, body=body,
                event_type=event_type, payload={"node_id": context.node_id})
        except Exception:  # noqa: BLE001 - 通知失败不阻断状态机
            context.logger.warning("agent retrain admin notify failed", exc_info=True)

    cooldown = timedelta(minutes=int(getattr(settings, "agent_retrain_cooldown_minutes", 30)))

    # ---- 轮询段 A：重放在途（accepted→固化新配方+派铸造；失败/升级/超时收尾）
    run = get_replay_run(db, meta.get("agent_run_id"))
    if run is not None:
        if run.status == "accepted":
            from app.services.agent.recipe import build_fixation_content, create_recipe

            cycle = uuid.uuid4().hex[:8]
            content = build_fixation_content(run, run.memory_json or {})
            recipe = create_recipe(
                db, project_id=context.project_id,
                name=(f"编排-agent-{cycle}")[:64], content=content,
                change_note="orchestration agent-retrain auto fixation",
                created_by=context.operator_id,
            )
            run_result = dict(run.result_json or {})
            run_result["fixated_recipe_id"] = str(recipe.id)
            run.result_json = run_result
            db.commit()

            def _split_csv(key):
                values = [item.strip() for item in str(params.get(key) or "").split(",") if item.strip()]
                return values or None

            ensemble_flag = params.get("retrain_ensemble_enabled")
            ensemble_enabled = ensemble_flag is True or str(ensemble_flag).strip().lower() in {"true", "1", "yes"}
            try:
                ensemble_top_k = max(2, min(5, int(params.get("retrain_ensemble_top_k") or 3)))
            except (TypeError, ValueError):
                ensemble_top_k = 3
            recipe_ensemble = dict(content.get("retrain_ensemble") or {})
            if recipe_ensemble.get("enabled"):
                ensemble = {"enabled": True, "top_k": int(recipe_ensemble.get("top_k") or ensemble_top_k)}
            elif ensemble_enabled:
                ensemble = {"enabled": True, "top_k": ensemble_top_k}
            else:
                ensemble = None
            casting_input = str(run.dataset_artifact_id) if run.dataset_artifact_id else artifact_id
            casting_kwargs = dict(
                project_id=context.project_id,
                actor_id=context.operator_id,
                experiment_name=f"编排智能体铸造-{total}-{cycle}",
                job_name=f"编排智能体铸造-{total}-{cycle}",
                dataset_artifact_id=casting_input,
                target_column=target_column,
                max_trials=int(params.get("retrain_max_trials") or 10),
                ensemble=ensemble,
                algorithm_ids=[str(item) for item in (content.get("retrain_algorithm_ids") or [])]
                or _split_csv("retrain_algorithm_ids"),
                input_columns=_split_csv("retrain_input_columns"),
            )
            if is_anomaly:
                # 无监督引擎合同（技术方案 §3.1/§3.7）：目标列空、CV off、
                # contamination 随配方透传、算法族收敛无监督白名单。
                anomaly_cfg = recipe_anomaly_config(content)
                casting_kwargs.update({
                    "target_column": "",
                    "task_type": ANOMALY_ENGINE_TASK_TYPE,
                    "anomaly_contamination": anomaly_cfg["contamination"],
                    "condition_column": anomaly_cfg["condition_column"],
                    "algorithm_ids": anomaly_cfg["algorithm_ids"],
                    "ensemble": None,
                })
            job = trigger_retrain_job(db, **casting_kwargs)
            meta["casting_job_id"] = str(job.id)
            meta["agent_fixated_recipe_id"] = str(recipe.id)
            # 重放轮终态：清 run 引用（轮询段 B 的互斥条件），铸造段由
            # casting_job_id 独立承载——否则换模段被在途 run 永久挡住。
            meta["agent_run_id"] = None
            meta["agent_started_at"] = None
            _save_meta()
        elif run.status in {"failed", "cancelled", "waiting_escalate"}:
            meta.update({
                "agent_run_id": None,
                "agent_started_at": None,
                "agent_failed": True,
                "agent_cool_until": (now + cooldown).isoformat(),
            })
            _release_loop_slot("failed")
            _save_meta()
            if run.status == "waiting_escalate":
                _notify("【编排闭环】智能体重训未通过验收",
                        f"重放任务未通过验收或已升级人工（{run.error_code or 'waiting_escalate'}），"
                        "不换模，旧模型继续服务。",
                        "orchestration.agent_retrain_rejected")
        else:
            started = _parse_iso(meta.get("agent_started_at"))
            max_age = int(getattr(settings, "agent_retrain_poll_max_age_seconds", 7200))
            if started is not None and (now - started).total_seconds() > max_age:
                meta.update({"agent_run_id": None, "agent_started_at": None, "agent_failed": True})
                _release_loop_slot("failed")
                _save_meta()
                _notify("【编排闭环】智能体重训超时",
                        f"重放超过 {max_age // 60} 分钟未终态，按失败处理（任务留档，不换模）。",
                        "orchestration.agent_retrain_timeout")

    # ---- 轮询段 B：铸造在途（completed→配方门禁兜底换模；failed→收尾）
    job = get_casting_job(db, meta.get("casting_job_id"))
    if job is not None and get_replay_run(db, meta.get("agent_run_id")) is None:
        if job.status == "failed":
            meta.update({
                "casting_job_id": None,
                "agent_failed": True,
                "agent_cool_until": (now + cooldown).isoformat(),
            })
            _release_loop_slot("failed")
            _save_meta()
            _notify("【编排闭环】部署模型铸造失败",
                    "引擎铸造任务失败，不换模，旧模型继续服务。",
                    "orchestration.agent_retrain_failed")
        elif job.status == "completed":
            version = complete_retrain_swap(
                db,
                deployment_id=params.get("swap_deployment_id"),
                job=job,
                actor_id=context.operator_id,
                model_name="编排闭环-自动模型",
                recipe_id=meta.get("agent_fixated_recipe_id"),
            )
            meta["casting_job_id"] = None
            if version is not None:
                # 换模成功：推进基线（增量触发唯一推进点）+ 冷却期。
                meta["agent_retrained_baseline"] = total
                meta["agent_swapped_model_version_id"] = str(version.id)
                meta["agent_cool_until"] = (now + cooldown).isoformat()
                _release_loop_slot("idle")
            else:
                meta["agent_failed"] = True
                meta["agent_cool_until"] = (now + cooldown).isoformat()
                _release_loop_slot("failed")
            _save_meta()

    # ---- 触发段：增量边沿 + 护栏（在途单飞/冷却/熔断）与闭环同语义
    baseline = int(meta.get("agent_retrained_baseline", 0) or 0)
    in_flight = bool(meta.get("agent_run_id") or meta.get("casting_job_id"))
    cool_until = _parse_iso(meta.get("agent_cool_until"))
    cycle_rows = total - baseline

    # 跨状态机共享单飞：编排（工件 metadata）与闭环自动化（demo_loop_configs）
    # 是两套重训状态机，互不可见——同部署双触发曾并行烧两轮 LLM（实测
    # 578642ea/044eb775）。编排触发前 CAS 抢占同部署闭环的槽位；闭环占着
    # （agent_running/queued）则本轮静默跳过；终端态负责放回。
    from sqlalchemy import update as sa_update

    _loop_row = None
    try:
        _loop_row = db.query(DemoLoopConfig).filter(
            DemoLoopConfig.deployment_id == uuid.UUID(str(deployment_key)),
        ).first()
    except (TypeError, ValueError):
        _loop_row = None

    def _release_loop_slot(status: str = "idle") -> None:
        if _loop_row is None:
            return
        _loop_row.retrain_status = status
        _loop_row.retrain_agent_started_at = None
        db.commit()

    def _claim_loop_slot() -> bool:
        if _loop_row is None:
            return True  # 该部署没有闭环自动化在管：无需跨状态机协调
        claimed = db.execute(
            sa_update(DemoLoopConfig)
            .where(
                DemoLoopConfig.id == _loop_row.id,
                DemoLoopConfig.retrain_status.in_(["idle", "failed", ""]),
                DemoLoopConfig.retrain_job_id.is_(None),
                DemoLoopConfig.retrain_agent_run_id.is_(None),
            )
            .values(retrain_status="agent_running", retrain_agent_started_at=now)
        ).rowcount
        db.commit()
        return bool(claimed)

    triggered_row = {
        "triggered": False, "total_rows": total,
        "cycle_rows": cycle_rows, "threshold_rows": threshold,
        "agent_run_id": meta.get("agent_run_id"),
        "casting_job_id": meta.get("casting_job_id"),
        "agent_failed": bool(meta.get("agent_failed")),
    }
    continue_row = {"total_rows": total, "remaining": max(0, threshold - cycle_rows)}
    if (
        not in_flight
        and (cool_until is None or now >= cool_until)
        and cycle_rows >= threshold
    ):
        times = [
            _parse_iso(item) for item in (meta.get("agent_trigger_times") or [])
        ]
        times = [item for item in times if item is not None and item >= now - timedelta(hours=24)]
        limit = int(getattr(settings, "agent_retrain_daily_limit", 3))
        if len(times) >= limit:
            if not meta.get("agent_break_notified"):
                meta["agent_break_notified"] = True
                _save_meta()
                _notify("【编排闭环】智能体重训熔断",
                        f"24 小时内已触发 {len(times)} 次，达到熔断上限，自动触发暂停；"
                        "请人工评估后再恢复。",
                        "orchestration.agent_retrain_break")
        else:
            if not _claim_loop_slot():
                # 闭环自动化正在重训/铸造：让路（共享单飞），不双触发
                return OperatorResult(
                    outputs={"triggered": [triggered_row], "continue": [continue_row]},
                    metrics={"total_rows": float(total)},
                )
            try:
                guidance, source_run_id = load_replay_contract(db, recipe_key)
                replay_guidance = _prepare_replay_guidance(guidance)
                merged = materialize_merged_dataset(
                    db, project_id=context.project_id,
                    dataset_ids=[str(params.get("retrain_dataset_artifact_id") or artifact_id), artifact_id],
                    target_column=target_column,
                    name_hint=f"编排智能体重训-{total}",
                )
                run = create_replay_run(
                    db, project_id=context.project_id, actor_id=context.operator_id,
                    dataset_artifact_id=merged.id, target_column=target_column,
                    guidance=replay_guidance, source_run_id=source_run_id,
                )
                if run.status == "waiting_escalate":
                    meta["agent_failed"] = True
                    _release_loop_slot("failed")
                    _save_meta()
                else:
                    times.append(now)
                    meta.update({
                        "agent_run_id": str(run.id),
                        "agent_started_at": now.isoformat(),
                        "agent_trigger_times": [item.isoformat() for item in times],
                        "agent_fixated_recipe_id": None,
                        "agent_failed": False,
                        "agent_break_notified": bool(meta.get("agent_break_notified", False)),
                    })
                    triggered_row["triggered"] = True
                    triggered_row["agent_run_id"] = str(run.id)
                    triggered_row["merged_rows"] = int((merged.metadata_ or {}).get("row_count", 0))
                    _save_meta()
            except AgentRetrainError as error:
                meta["agent_failed"] = True
                _release_loop_slot("failed")
                _save_meta()
                _notify("【编排闭环】智能体重训触发失败",
                        f"{error}；不换模，旧模型继续服务。",
                        "orchestration.agent_retrain_failed")
    return OperatorResult(
        outputs={"triggered": [triggered_row], "continue": [continue_row]},
        metrics={"total_rows": float(total)},
    )


def create_replay_run(db: Session, *, project_id, actor_id, dataset_artifact_id,
                      target_column: str, guidance: dict,
                      source_run_id: str | None = None) -> AgentRun:
    """创建 pending 重放 run 并派发执行（闭环与编排共用）。

    LLM 档案/预算沿用 source_run（配方快照的源 run）；执行器不可用置
    waiting_escalate 留档，派发异常抛 AgentRetrainError 由调用方收尾。"""
    source_run = None
    if source_run_id:
        try:
            source_run = db.get(AgentRun, uuid.UUID(str(source_run_id)))
        except (TypeError, ValueError):
            source_run = None
    run = AgentRun(
        project_id=project_id,
        dataset_artifact_id=dataset_artifact_id,
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
    db.commit()

    from app.services.agent.executor import AgentRunNotExecutable, launch_agent_run

    try:
        launch_agent_run(run.id, actor_id=actor_id)
    except AgentRunNotExecutable as error:
        run.status = "waiting_escalate"
        run.error_code = "AGENT_RUN_NOT_EXECUTABLE"
        run.result_json = {"executor_error": str(error)}
        db.commit()
    except Exception as error:  # noqa: BLE001 - 派发失败上抛调用方收尾
        logger.exception("agent retrain launch failed for run %s", run.id)
        raise AgentRetrainError("AGENT_RETRAIN_LAUNCH_FAILED") from error
    return run


def _as_uuid(value):
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


def trigger_agent_retrain(db: Session, config: DemoLoopConfig, actor_id) -> None:
    """发起一轮智能体重放（调用方已过增量阈值与部署级单飞闸门）。

    冷却期未到 / 项目并发已满 → 静默返回（正常性跳过，不刷事件）；
    熔断触顶 → 首次触顶发 critical 事件 + 管理员通知，其后静默；
    快照缺失 / 数据缺失 → AgentRetrainError（调用方转 retrain_failed 事件）。
    """
    now = _naive_utcnow()
    # DB 级 CAS 抢占重训槽：并发逐行回流（uvicorn 双进程 + 线程池）曾同时
    # 通过内存状态检查，一轮触发变成两轮（error 20/21 各触发一次实测）。
    # 原子占用 idle/failed 槽位，输者静默返回；失败收尾统一把状态放回
    # failed（等待下一次增量追赶评估）。
    from sqlalchemy import update as sa_update

    claimed = db.execute(
        sa_update(DemoLoopConfig)
        .where(
            DemoLoopConfig.id == config.id,
            DemoLoopConfig.retrain_status.in_(["idle", "failed", ""]),
            DemoLoopConfig.retrain_job_id.is_(None),
            DemoLoopConfig.retrain_agent_run_id.is_(None),
        )
        .values(retrain_status="agent_running", retrain_agent_started_at=now)
    ).rowcount
    db.commit()
    if not claimed:
        return

    def _release_claim(status: str = "idle") -> None:
        """CAS 已占槽但本轮不进行（冷却/熔断/并发让路）→ 放回槽位。"""
        config.retrain_status = status
        config.retrain_agent_started_at = None
        db.commit()

    cool_until = getattr(config, "retrain_cool_until", None)
    if cool_until is not None and now < cool_until:
        _release_claim()
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
        _release_claim()
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
        _release_claim()
        return

    try:
        guidance = _prepare_replay_guidance(_load_guidance_snapshot(db, config))
        target_column = _resolve_target_column(db, config)
        artifact = _materialize_merged_artifact(
            db, config, f"{config.name}-智能体重训-{config.error_count}")

        # 源 run 的 LLM 档案/预算沿用（配方快照的 source_run_id；缺省走平台默认）。
        _guidance, source_run_id = load_replay_contract(db, config.retrain_agent_recipe_id)
        run = create_replay_run(
            db, project_id=config.project_id, actor_id=actor_id,
            dataset_artifact_id=artifact.id, target_column=target_column,
            guidance=guidance, source_run_id=source_run_id,
        )
    except AgentRetrainError:
        # 槽位已被 CAS 占用：物化/合同失败必须放回 failed，否则槽位永久卡死
        # （下一次增量评估因状态非 idle 永不再触发）。
        config.retrain_status = "failed"
        config.retrain_agent_started_at = None
        db.commit()
        raise
    config.retrain_status = "agent_running"
    config.retrain_agent_run_id = run.id
    config.retrain_agent_started_at = now
    if not config.retrain_target_column:
        config.retrain_target_column = target_column
    db.commit()

    if run.status == "waiting_escalate":
        # 执行器不可用：run 留档升级人工，闭环按重放失败收尾。
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
        get_current_version,
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
        input_columns = list(getattr(config, "retrain_input_columns", None) or []) or None
        # 配方带 S2 特征脚本 → 先把合并原始表变换为特征帧再铸（与 S4 验收
        # 同一张表；部署模型吃派生特征，直接喂原始列既会因稀疏行 dropna 后
        # <10 行失败（实测 3165 行全灭），练成也与线上推理输入不兼容）。
        # 失败回落原始数据集（引擎模式旧形态）。
        recipe_feature_script = str(
            (get_current_version(db, _as_uuid(config.retrain_agent_recipe_id))
             .content_json or {}).get("feature_script") or ""
        ) if config.retrain_agent_recipe_id else ""
        if recipe_feature_script.strip():
            try:
                import tempfile
                from pathlib import Path as _Path

                import pandas as _pd

                from app.services.agent.sandbox import run_sandbox as _run_sandbox
                from app.services.artifact_service import build_artifact_service as _bas

                _service = _bas(db)
                _frames = []
                for _raw_id in casting_ids:
                    with _service.materialize(
                        _as_uuid(_raw_id), config.project_id, expected_type="dataset",
                    ) as _path:
                        _frames.append(_pd.read_csv(_path))
                _raw = _pd.concat(_frames, ignore_index=True) if len(_frames) > 1 else _frames[0]
                _sandbox = _run_sandbox(recipe_feature_script, _raw, timeout_seconds=300)
                if _sandbox.ok and getattr(_sandbox, "output", None) is not None:
                    _cast_frame = _sandbox.output
                    _target = config.retrain_target_column or run.target_column
                    if _target and _target not in _cast_frame.columns and _target in _raw.columns:
                        _cast_frame[_target] = _raw[_target].values
                    with tempfile.TemporaryDirectory() as _tmp:
                        _path_out = _Path(_tmp) / "loop-cast-features.csv"
                        _cast_frame.to_csv(_path_out, index=False)
                        _cast_artifact = _service.create_from_file(
                            config.project_id, _path_out,
                            f"{config.name}-铸造特征集-{cycle}",
                            "dataset",
                            metadata={"source": "agent-loop-cast-features",
                                      "recipe_id": str(config.retrain_agent_recipe_id),
                                      "row_count": int(len(_cast_frame)),
                                      "column_count": int(len(_cast_frame.columns))},
                        )
                    casting_ids = [str(_cast_artifact.id)]
                    input_columns = [
                        str(col) for col in _cast_frame.columns
                        if col != _target and _pd.api.types.is_numeric_dtype(_cast_frame[col])
                    ] or None
            except Exception:  # noqa: BLE001 - 变换失败回落原始数据集
                logger.warning("loop cast feature transform failed", exc_info=True)
        casting_kwargs = dict(
            project_id=config.project_id,
            actor_id=actor_id,
            experiment_name=f"{config.name}-智能体铸造-{config.error_count}-{cycle}",
            job_name=f"{config.name}-智能体铸造-{config.error_count}-{cycle}",
            dataset_artifact_ids=casting_ids,
            target_column=config.retrain_target_column or run.target_column,
            max_trials=config.retrain_max_trials,
            ensemble=ensemble,
            algorithm_ids=algorithm_ids,
            input_columns=input_columns,
        )
        if detect_recipe_paradigm(content) == ANOMALY_PARA_DIGM:
            # 无监督引擎合同（技术方案 §3.1/§3.7）：目标列空、CV off、
            # contamination 随配方透传、算法族收敛无监督白名单。
            anomaly_cfg = recipe_anomaly_config(content)
            casting_kwargs.update({
                "target_column": "",
                "task_type": ANOMALY_ENGINE_TASK_TYPE,
                "anomaly_contamination": anomaly_cfg["contamination"],
                "condition_column": anomaly_cfg["condition_column"],
                "algorithm_ids": anomaly_cfg["algorithm_ids"],
                "ensemble": None,
            })
        job = trigger_retrain_job(db, **casting_kwargs)
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
