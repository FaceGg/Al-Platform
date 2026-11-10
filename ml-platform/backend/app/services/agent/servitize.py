"""S5 servitization (spec v0.9 §12.1-§12.6): recipe → three live assets.

Draft semantics (§12.1 修正): the closed-loop config is created passively and
the model API entry is created ``offline`` (not listed) — nothing is callable
from the market until :func:`activate_servitize` flips the switch at the
human approval step. Smoke is dry-run by construction: it goes through
``DemoLoopService.predict(dry_run=True)``, which persists nothing, so a
defect-classified smoke row can never pollute the error dataset or trigger a
retrain. A project-level mutex serializes S5 (§12.6).
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.models.api_model import PlatformAPI
from app.models.demo_loop import DemoLoopConfig
from app.services.demo_loop import DemoLoopService

DEFECT_SEMANTIC_KEYWORDS = (
    "不合格", "缺陷", "故障", "不良", "次品", "异常",
    "fail", "defect", "ng", "bad", "fault",
)
_PROJECT_LOCKS: dict[str, threading.Lock] = {}
_PROJECT_LOCKS_GUARD = threading.Lock()
# 服务化闭环的重训触发行数默认值，与闭环配置界面 LoopConfigModal 初值一致
# （模型列缺省 0 = 回流永不触发，一键服务化的闭环因此从不重训）。
DEFAULT_LOOP_RETRAIN_THRESHOLD = 20


def servitize_lock(project_id) -> threading.Lock:
    key = str(project_id)
    with _PROJECT_LOCKS_GUARD:
        lock = _PROJECT_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _PROJECT_LOCKS[key] = lock
        return lock


def _bridge_feature_script(script: str | None) -> str:
    """S2 沙箱契约（def transform(df)）→ 闭环 python_script 算子契约（result=）。

    算子沙箱入参名同为 df，直接尾部追加 result 赋值；已是 result 形态的
    脚本原样返回（防双重包装）。"""
    text = (script or "").strip()
    if not text or "result = transform(" in text or "result=transform(" in text:
        return text
    return text + "\n\nresult = transform(df)\n"


def derive_error_classes(target_semantics: dict | None,
                         minority_label: str | None = None) -> tuple[list[str], list[str]]:
    """Derive defect-class labels from S1 target semantics (§12.2).

    Returns ``(error_classes, ambiguous_labels)`` — labels whose semantic
    description matches a defect keyword become error classes; the rest are
    reported as ambiguous for the wizard preview (发布批准时一眼可核).
    """
    semantics = target_semantics or {}
    error_classes: list[str] = []
    ambiguous: list[str] = []
    for label, description in semantics.items():
        text = str(description or "").lower()
        if any(keyword in text for keyword in DEFECT_SEMANTIC_KEYWORDS):
            error_classes.append(str(label))
        else:
            ambiguous.append(str(label))
    if not error_classes and semantics:
        # 无语义命中：兜底取少数类（缺陷天然稀少，与验收 recall_minority 口径
        # 一致）；缺少数类信息（旧配方）退回字典序最小。全部标 ambiguous 供
        # 发布批准时核对。
        labels = [str(label) for label in semantics]
        if minority_label is not None and str(minority_label) in labels:
            error_classes.append(str(minority_label))
        else:
            error_classes.append(sorted(labels)[0])
    return error_classes, ambiguous


@dataclass
class ServitizeDraft:
    deployment_id: str
    loop_config_id: str
    model_api_id: str
    model_api_name: str
    error_classes: list[str] = field(default_factory=list)
    ambiguous_labels: list[str] = field(default_factory=list)
    smoke: dict = field(default_factory=dict)
    activated: bool = False


def example_record(recipe_content: dict) -> dict:
    """市场调用示例行：配方冒烟行（训练集首行）剔除目标列——调用方不持有标签。"""
    target = str((recipe_content.get("inputs") or {}).get("target_column") or "")
    return {
        key: value
        for key, value in (recipe_content.get("smoke_row") or {}).items()
        if key != target
    }


def _agent_retrain_binding(db: Session, project_id, recipe_id, recipe_content: dict,
                           loop: DemoLoopConfig | None) -> dict:
    """一键服务化闭环的智能体重训绑定（配方重放 + 合并重训数据 + 阈值）。

    原先服务化闭环停在模型缺省（engine 模式、未绑配方、阈值 0、无重训数据
    集）：④ 发布编排必 422，闭环重训退化为引擎搜索，且合并集只剩报错行
    （几乎单类）。原始训练集取自配方源 run——部署模型正是用它训练的；复用
    草稿时用户已改过的阈值/数据集不覆盖；源数据集已删则不绑（不阻断服务化）。"""
    from app.models.agent_run import AgentRun
    from app.models.artifact import Artifact

    binding: dict = {
        "retrain_mode": "agent",
        "retrain_agent_recipe_id": str(recipe_id),
    }
    if loop is None or not int(loop.retrain_threshold_rows or 0):
        binding["retrain_threshold_rows"] = DEFAULT_LOOP_RETRAIN_THRESHOLD
    configured = loop is not None and bool(
        loop.retrain_dataset_artifact_ids or loop.retrain_dataset_artifact_id)
    source_run_id = recipe_content.get("source_run_id")
    if not configured and source_run_id:
        try:
            source_run = db.get(AgentRun, uuid.UUID(str(source_run_id)))
        except (TypeError, ValueError):
            source_run = None
        dataset_id = source_run.dataset_artifact_id if source_run is not None else None
        if dataset_id is not None and db.query(Artifact.id).filter(
            Artifact.id == dataset_id,
            Artifact.project_id == project_id,
            Artifact.type == "dataset",
        ).first() is not None:
            binding["retrain_dataset_artifact_ids"] = [str(dataset_id)]
    return binding


def servitize_recipe(
    db: Session,
    *,
    project_id,
    actor_id,
    deployment_id,
    recipe_content: dict,
    model_api_name: str | None = None,
    loop_name: str | None = None,
    error_classes_override: list[str] | None = None,
    recipe_id=None,
) -> ServitizeDraft:
    """Create the three S5 assets in draft state (§12.1 ①–④).

    ① deployment must already exist (model registered/approved/started via
    the standard chain); ② closed-loop config (passive — nothing feeds it
    until the model API is listed); ③ model API entry ``offline``;
    ④ dry-run smoke — zero backflow by construction. ⑤ activation is a
    separate explicit call (:func:`activate_servitize`).

    ``recipe_id`` given (one-click / auto servitize) → the loop is bound to
    agent retrain (recipe replay) with the recipe's source training dataset
    merged into every retrain; without it the loop keeps the engine default.
    """
    from app.models.model_registry import InferenceDeployment

    with servitize_lock(project_id):
        deployment_uuid = uuid.UUID(str(deployment_id))
        deployment = (
            db.query(InferenceDeployment)
            .filter(
                InferenceDeployment.id == deployment_uuid,
                InferenceDeployment.project_id == project_id,
            )
            .first()
        )
        if deployment is None:
            raise LookupError("deployment not found in project")
        from app.models.model_registry import ModelVersion

        version = (
            db.query(ModelVersion)
            .filter(ModelVersion.id == deployment.model_version_id)
            .first()
        )
        library_id = version.source_model_library_id if version is not None else None

        if error_classes_override is not None:
            error_classes = list(error_classes_override)
            ambiguous: list[str] = []
        else:
            error_classes, ambiguous = derive_error_classes(
                recipe_content.get("target_semantics"),
                recipe_content.get("minority_label"),
            )
        if not error_classes:
            raise ValueError(
                "cannot derive error classes: provide target_semantics or an override"
            )

        gates = recipe_content.get("acceptance_gates") or {}
        loop_data = {
            "name": loop_name or (model_api_name or "智能体闭环")[:120],
            "deployment_id": str(deployment.id),
            "error_classes": error_classes,
            # 脚本桥接（S2→闭环算子契约适配）：铸造部署模型按 S2 特征帧训练
            # （cur_sum/energy_per_time 等派生列），回流原始行必须过同一变换
            # 才能命中模型特征列——S2 脚本（def transform(df)，入参名与
            # python_script 算子的 df 一致）尾部追加 result 赋值即满足算子
            # 契约（result=transform(df)），冒烟即验证桥接可用；无脚本的
            # 配方回落 legacy 直通（部署模型按原始列训练的旧形态）。
            "feature_engineering_mode": (
                "script" if (recipe_content.get("feature_script") or "").strip() else "legacy"
            ),
            "feature_script": _bridge_feature_script(recipe_content.get("feature_script")),
            "retrain_target_column": recipe_content.get("inputs", {}).get(
                "target_column", ""
            ),
            "retrain_enabled": bool(recipe_content.get("retrain_enabled", True)),
            # 配方固化的集成选项（向导第三步）→ 闭环重训下发终选层集成；
            # 旧配方无此键 = 不开启，行为不变。
            "retrain_ensemble_enabled": bool(
                (recipe_content.get("retrain_ensemble") or {}).get("enabled")
            ),
            "retrain_ensemble_top_k": int(
                (recipe_content.get("retrain_ensemble") or {}).get("top_k") or 3
            ),
            # 向导算法白名单 → 闭环重训引擎搜索族（空 = 全族）
            "retrain_algorithm_ids": [
                str(x) for x in (recipe_content.get("retrain_algorithm_ids") or [])
            ],
        }
        loop_service = DemoLoopService(db)
        # One servitize entry per deployment (platform unique constraint):
        # re-servitizing an unpublished draft reuses the row (and its loop
        # config) and bumps the version; a published entry must go through a
        # new recipe version.
        api = (
            db.query(PlatformAPI)
            .filter(
                PlatformAPI.source_kind == "servitize",
                PlatformAPI.source_id == deployment.id,
            )
            .first()
        )
        reusing = api is not None and api.status == "offline"
        if reusing:
            number = "".join(ch for ch in str(api.version or "v1") if ch.isdigit())
            api.version = "v%d" % (int(number or 1) + 1)
            api_name = api.name
        elif api is not None:
            raise ValueError(
                "deployment already has a published servitize entry; "
                "publish a new recipe version instead"
            )
        else:
            api_name = (model_api_name or loop_name or "智能体闭环")[:240]

        loop_id = (
            (api.showcase_state or {}).get("loop_config_id") if api is not None else None
        )
        loop = None
        if reusing and loop_id:
            loop = db.get(DemoLoopConfig, uuid.UUID(str(loop_id)))
        if recipe_id:
            loop_data.update(_agent_retrain_binding(
                db, project_id, recipe_id, recipe_content, loop))
        if loop is not None:
            loop_service.update_config(loop, project_id, loop_data)
        else:
            loop = loop_service.create_config(project_id, actor_id, loop_data)

        if api is None:
            api = PlatformAPI(
                name=api_name,
                api_type="model",
                status="offline",  # draft: not listed until approval (§12.1 ⑤)
                source_kind="servitize",
                source_id=deployment.id,
                model_id=library_id,
                owner_id=actor_id,
                description="AutoML Agent S5 服务化草稿（待发布批准）",
                showcase_state={"loop_config_id": str(loop.id)},
            )
            db.add(api)
        else:
            api.showcase_state = {"loop_config_id": str(loop.id)}
        # 调用入口 = 闭环 scoped predict（送原始行：闭环内 S2 特征变换→推理→
        # 报错回流）。条目曾不写 endpoint，市场「调用示例/在线测试」只剩裸
        # 域名无从调用。
        api.endpoint = f"/api/projects/{project_id}/demo-loop/loops/{loop.id}/predict"
        api.method = "POST"
        api.request_schema = {
            "feature_script": recipe_content.get("feature_script") or "",
            "record": example_record(recipe_content),
        }
        db.commit()
        db.refresh(api)

        smoke_row = dict(recipe_content.get("smoke_row") or {})
        # 冒烟降级护栏：S2 特征脚本是批处理假设（nunique/全帧统计过滤），
        # 单行冒烟帧会被脚本自删特征列（cur_sum 等缺失，run 4f9ffdc7 配方
        # 实证）。smoke_row 缺部署模型特征列时改用模型 feature_schema 的
        # 合成零行——dry_run 语义不变（只验 predict 通路+零回流），批处理
        # 脚本的逐行桥接（S2 生成提示加单行守卫）留独立批次。
        raw_schema = list(getattr(version, "feature_schema", None) or [])
        feature_schema = [
            str(item.get("name") if isinstance(item, dict) else item)
            for item in raw_schema
            if (item.get("name") if isinstance(item, dict) else item)
        ]
        if feature_schema and any(column not in smoke_row for column in feature_schema):
            smoke_row = {column: 0.0 for column in feature_schema}
        smoke = loop_service.predict(loop, smoke_row, actor_id, dry_run=True)

        return ServitizeDraft(
            deployment_id=str(deployment.id),
            loop_config_id=str(loop.id),
            model_api_id=str(api.id),
            model_api_name=api.name,
            error_classes=error_classes,
            ambiguous_labels=ambiguous,
            smoke=smoke,
        )


def activate_servitize(db: Session, *, model_api_id, actor_id) -> PlatformAPI:
    """§12.1 ⑤ human approval: list the model API (one-switch activation).

    The closed-loop config is already live-but-unfed; listing the API is the
    single external switch. Orchestration publication remains a separate
    explicit action on the workflow (pendingApproval flow lives there)."""
    api = db.get(PlatformAPI, uuid.UUID(str(model_api_id)))
    if api is None:
        raise LookupError("model api not found")
    if api.status != "offline":
        raise ValueError("only a draft (offline) servitize entry can be activated")
    from datetime import datetime, timezone

    api.status = "published"
    api.published_at = datetime.now(timezone.utc)
    api.description = "AutoML Agent S5 服务化（已批准发布）"
    db.commit()
    db.refresh(api)
    return api
