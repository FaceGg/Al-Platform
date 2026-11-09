"""Agent center read-only listings (AutoML Agent plan, front-end wiring).

Exposes agent run metadata and pipeline recipe metadata for the Agent Center
page. These endpoints are deliberately metadata-only: run memory/result JSON
and recipe version content (feature scripts, modeling configs) never leave
the platform through this surface.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.database import get_db
from app.models.agent_run import AgentRun
from app.models.project import Project
from app.models.recipe import PipelineRecipe, PipelineRecipeVersion
from app.models.user import User

router = APIRouter(prefix="/api/agent", tags=["agent-center"])


class AgentRunOut(BaseModel):
    id: str
    project_id: str | None
    project_name: str | None
    target_column: str | None
    status: str
    current_stage: str
    round_count: int
    token_used: int
    error_code: str | None
    created_at: str | None
    updated_at: str | None


class PipelineRecipeOut(BaseModel):
    id: str
    project_id: str | None
    project_name: str | None
    name: str
    domain: str | None
    target_column: str | None
    current_version: int
    version_status: str | None
    change_note: str | None
    created_at: str | None
    updated_at: str | None


class AgentRunDetail(AgentRunOut):
    """Full run archive: stage timeline, per-round memory and terminal result.

    The runner's memory/result JSON are LLM-produced task artifacts (spec §7
    task archive); they carry no credentials and are shown to the signed-in
    operator. List endpoints stay metadata-only; only this detail view exposes
    them.
    """

    model_config = {"protected_namespaces": ()}

    dataset_artifact_id: str | None
    llm_model_id: str | None
    llm_profile_name: str | None
    token_budget: int | None
    heartbeat_at: str | None
    guidance_json: dict | None
    memory_json: dict
    result_json: dict


def _iso(value) -> str | None:
    return value.isoformat() if value is not None else None


def _uuid_or_none(value) -> str | None:
    return str(value) if value is not None else None


@router.get("/runs", response_model=list[AgentRunOut])
def list_agent_runs(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rows = (
        db.query(AgentRun, Project.name)
        .outerjoin(Project, AgentRun.project_id == Project.id)
        .order_by(AgentRun.updated_at.desc(), AgentRun.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [
        AgentRunOut(
            id=str(run.id),
            project_id=_uuid_or_none(run.project_id),
            project_name=name,
            target_column=run.target_column,
            status=run.status,
            current_stage=run.current_stage,
            round_count=run.round_count,
            token_used=run.token_used,
            error_code=run.error_code,
            created_at=_iso(run.created_at),
            updated_at=_iso(run.updated_at),
        )
        for run, name in rows
    ]


class AgentRunCreate(BaseModel):
    dataset_artifact_id: uuid.UUID
    target_column: str = Field(min_length=1, max_length=256)
    project_id: uuid.UUID | None = None
    llm_profile_id: uuid.UUID | None = None
    llm_model_id: str | None = Field(default=None, max_length=128)
    token_budget: int | None = Field(default=None, ge=1000, le=10_000_000)
    step_by_step: bool = False
    guidance: dict = Field(default_factory=dict)


@router.post("/runs", status_code=201, response_model=AgentRunDetail)
def create_agent_run(
    payload: AgentRunCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Archive a wizard submission as a pending run (spec §11).

    The guidance dict must satisfy the fourth contract (UserGuidance); the
    step-by-step switch expands into the pause plan. Execution hand-off to the
    AutoML worker binding is staged separately — this endpoint only persists
    the submission so the task archive exists before any engine starts.
    """
    from pydantic import ValidationError

    from app.services.agent.contracts import UserGuidance
    from app.services.agent.wizard import STAGES

    try:
        guidance = UserGuidance.model_validate(payload.guidance)
    except ValidationError as error:
        raise HTTPException(
            status_code=422,
            detail={"code": "AGENT_RUN_GUIDANCE_INVALID", "errors": error.errors()[:8]},
        )
    guidance_data = guidance.model_dump()
    if payload.step_by_step:
        guidance_data["pause_at_stages"] = sorted(set(STAGES))

    run = AgentRun(
        project_id=payload.project_id,
        dataset_artifact_id=payload.dataset_artifact_id,
        target_column=payload.target_column,
        llm_profile_id=payload.llm_profile_id,
        llm_model_id=payload.llm_model_id,
        token_budget=payload.token_budget,
        status="pending",
        current_stage="s1",
        memory_json={},
        result_json={},
        guidance_json=guidance_data,
        created_by=current_user.id,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    # 执行链接线（P0）：提交即启动后台执行；状态全程落 run 行，前端轮询可见。
    from app.services.agent.executor import AgentRunNotExecutable, launch_agent_run

    try:
        launch_agent_run(run.id, actor_id=current_user.id)
    except AgentRunNotExecutable as error:
        run.status = "waiting_escalate"
        run.error_code = "AGENT_RUN_NOT_EXECUTABLE"
        run.result_json = {"executor_error": str(error)}
        db.commit()
        db.refresh(run)
    return get_agent_run(run.id, db=db, current_user=current_user)


@router.post("/runs/{run_id}/resume", response_model=AgentRunDetail)
def resume_agent_run(
    run_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """逐步确认模式的放行：从 waiting_guidance 继续执行到下一暂停位或终态。"""
    from sqlalchemy import update as sa_update

    from app.tasks.time_utils import utcnow as _agent_utcnow

    run = db.get(AgentRun, uuid.UUID(run_id))
    if run is None:
        raise HTTPException(404, detail={"code": "AGENT_RUN_NOT_FOUND"})
    if run.status != "waiting_guidance":
        raise HTTPException(
            409,
            detail={"code": "AGENT_RUN_NOT_PAUSED", "status": run.status},
        )
    # A-12：放行改 DB 级 CAS——历史上检查与派发之间无锁，并发 resume 双跑
    # （LLM 花费翻倍、memory_json 档案互相覆盖）；UPDATE 抢占成功才派发
    claimed = db.execute(
        sa_update(AgentRun)
        .where(AgentRun.id == run.id, AgentRun.status == "waiting_guidance")
        .values(status="running", heartbeat_at=_agent_utcnow())
    ).rowcount
    db.commit()
    if not claimed:
        raise HTTPException(
            409, detail={"code": "AGENT_RUN_NOT_PAUSED", "status": "running"},
        )
    from app.services.agent.executor import AgentRunNotExecutable, launch_agent_run

    try:
        launch_agent_run(run.id, actor_id=current_user.id)
    except AgentRunNotExecutable as error:
        raise HTTPException(
            422, detail={"code": "AGENT_RUN_NOT_EXECUTABLE", "message": str(error)}
        ) from error
    db.refresh(run)
    return get_agent_run(run.id, db=db, current_user=current_user)


@router.get("/runs/{run_id}", response_model=AgentRunDetail)
def get_agent_run(
    run_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    row = (
        db.query(AgentRun, Project.name)
        .outerjoin(Project, AgentRun.project_id == Project.id)
        .filter(AgentRun.id == run_id)
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "AGENT_RUN_NOT_FOUND"})
    run, project_name = row
    llm_profile_name = None
    if run.llm_profile_id is not None:
        from app.models.llm_profile import LLMProfile

        profile = db.get(LLMProfile, run.llm_profile_id)
        llm_profile_name = profile.name if profile is not None else None
    return AgentRunDetail(
        id=str(run.id),
        project_id=_uuid_or_none(run.project_id),
        project_name=project_name,
        target_column=run.target_column,
        status=run.status,
        current_stage=run.current_stage,
        round_count=run.round_count,
        token_used=run.token_used,
        error_code=run.error_code,
        created_at=_iso(run.created_at),
        updated_at=_iso(run.updated_at),
        dataset_artifact_id=_uuid_or_none(run.dataset_artifact_id),
        llm_model_id=run.llm_model_id,
        llm_profile_name=llm_profile_name,
        token_budget=run.token_budget,
        heartbeat_at=_iso(getattr(run, "heartbeat_at", None)),
        guidance_json=getattr(run, "guidance_json", None),
        memory_json=run.memory_json or {},
        result_json=run.result_json or {},
    )


@router.post("/runs/{run_id}/cancel", response_model=AgentRunDetail)
def cancel_agent_run(
    run_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """用户终止运行中的智能体任务。

    DB 级 CAS 抢占（与 resume 同款防并发）：执行线程在轮次/验收落态
    边界检查到 cancelled 即停止并保留终态；正在进行的单次 LLM 调用
    （最长约 12 分钟含重试）无法中断，在其后边界生效。"""
    from sqlalchemy import update as sa_update

    from app.tasks.time_utils import utcnow as _agent_utcnow

    run = db.get(AgentRun, uuid.UUID(run_id))
    if run is None:
        raise HTTPException(404, detail={"code": "AGENT_RUN_NOT_FOUND"})
    if current_user.role != "admin" and run.created_by != current_user.id:
        raise HTTPException(403, detail={"code": "AGENT_RUN_FORBIDDEN"})
    if run.status not in ("pending", "running"):
        raise HTTPException(
            409, detail={"code": "AGENT_RUN_NOT_ACTIVE", "status": run.status},
        )
    claimed = db.execute(
        sa_update(AgentRun)
        .where(
            AgentRun.id == run.id,
            AgentRun.status.in_(("pending", "running")),
        )
        .values(status="cancelled", heartbeat_at=_agent_utcnow())
    ).rowcount
    db.commit()
    if not claimed:
        raise HTTPException(
            409, detail={"code": "AGENT_RUN_NOT_ACTIVE", "status": "cancelled"},
        )
    db.refresh(run)
    return get_agent_run(run.id, db=db, current_user=current_user)


class AgentRunDecision(BaseModel):
    """升级态的人工决策：accept=采纳验收结论（确认指标可信），reject=确认评审
    意见（接受任务终止，可调整引导后重提）。"""

    decision: str = Field(pattern="^(accept|reject)$")
    note: str | None = Field(default=None, max_length=2000)


@router.post("/runs/{run_id}/decision", response_model=AgentRunDetail)
def decide_agent_run(
    run_id: str,
    data: AgentRunDecision,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """waiting_escalate 的人工决策闭环。

    此前「待人工决策」是死状态：resume 仅收 waiting_guidance，升级后既无
    采纳也无驳回入口，用户只能重提任务。accept 将验收落为 accepted（指标
    取最后轮次 S3 冠军实测值）；reject 落为 cancelled（保留档案与决策记录）。
    两者均写 escalation.resolved 决策留痕（决策人/时间/备注）。"""
    from datetime import datetime, timezone

    run = db.get(AgentRun, uuid.UUID(run_id))
    if run is None:
        raise HTTPException(404, detail={"code": "AGENT_RUN_NOT_FOUND"})
    if current_user.role != "admin" and run.created_by != current_user.id:
        raise HTTPException(403, detail={"code": "AGENT_RUN_FORBIDDEN"})
    if run.status != "waiting_escalate":
        raise HTTPException(
            409, detail={"code": "AGENT_RUN_NOT_ESCALATED", "status": run.status},
        )
    memory = dict(run.memory_json or {})
    escalation = dict(memory.get("escalation") or {})
    escalation["resolved"] = {
        "decision": data.decision,
        "note": (data.note or "").strip()[:2000] or None,
        "actor": str(current_user.id),
        "at": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
    }
    memory["escalation"] = escalation
    if data.decision == "accept":
        # 验收落态：指标取最后轮次 S3 冠军实测值（升级前的真实水平，非评审猜估）
        last_metrics = {}
        for entry in reversed(memory.get("rounds") or []):
            if isinstance(entry.get("s3"), dict) and entry["s3"].get("metrics"):
                last_metrics = entry["s3"]["metrics"]
                break
        run.status = "accepted"
        run.current_stage = "done"
        run.error_code = None
        result = dict(run.result_json or {})
        result.setdefault("token_used", run.token_used)
        if last_metrics:
            result["metrics"] = last_metrics
        run.result_json = result
    else:
        run.status = "cancelled"
    run.memory_json = memory
    db.commit()
    db.refresh(run)
    return get_agent_run(run.id, db=db, current_user=current_user)


# 活跃态不可删：执行线程仍在写 run 行，删除会产生孤儿写入与误导性报错。
DELETABLE_RUN_STATUSES = frozenset(
    # 终态可删；pending/running 在跑（删除需先终止，避免执行线程写回
    # 已删除行）。cancelled/superseded 同为终态，遗漏会导致用户终止后
    # 反而删不掉（7ae17d4d 实测踩坑）。
    {"waiting_escalate", "waiting_guidance", "accepted", "failed", "cancelled", "superseded"}
)


@router.delete("/runs/{run_id}", status_code=204)
def delete_agent_run(
    run_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    run = db.get(AgentRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail={"code": "AGENT_RUN_NOT_FOUND"})
    if current_user.role != "admin" and run.created_by != current_user.id:
        raise HTTPException(status_code=403, detail={"code": "AGENT_RUN_FORBIDDEN"})
    if run.status not in DELETABLE_RUN_STATUSES:
        raise HTTPException(
            status_code=409,
            detail={"code": "AGENT_RUN_ACTIVE", "status": run.status},
        )
    db.delete(run)
    db.commit()
    return None


@router.get("/recipes", response_model=list[PipelineRecipeOut])
def list_pipeline_recipes(
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # 当前版本信息直接按 (recipe_id, version == current_version) 左连版本表——
    # 此前的「version == PipelineRecipe.current_version」子查询因 PipelineRecipe
    # 不在子查询 FROM 中无法被相关化，SQLAlchemy 退化为子查询内笛卡尔积，
    # 导致列表同一配方重复出现多行（删除时"同时消失好几个"的根因）。
    # (recipe_id, version) 有唯一约束，此连接每配方恰得一行。
    rows = (
        db.query(PipelineRecipe, Project.name, PipelineRecipeVersion.status, PipelineRecipeVersion.change_note)
        .outerjoin(Project, PipelineRecipe.project_id == Project.id)
        .outerjoin(
            PipelineRecipeVersion,
            (PipelineRecipeVersion.recipe_id == PipelineRecipe.id)
            & (PipelineRecipeVersion.version == PipelineRecipe.current_version),
        )
        .order_by(PipelineRecipe.updated_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [
        PipelineRecipeOut(
            id=str(recipe.id),
            project_id=_uuid_or_none(recipe.project_id),
            project_name=name,
            name=recipe.name,
            domain=recipe.domain,
            target_column=recipe.target_column,
            current_version=recipe.current_version,
            version_status=version_status,
            change_note=change_note,
            created_at=_iso(recipe.created_at),
            updated_at=_iso(recipe.updated_at),
        )
        for recipe, name, version_status, change_note in rows
    ]


@router.get("/recipes/{recipe_id}")
def get_recipe_detail(
    recipe_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """配方详情：配方字段 + 全部版本 + 当前版本完整内容（特征脚本/门禁/重训配置）。"""
    recipe = db.get(PipelineRecipe, recipe_id)
    if recipe is None:
        raise HTTPException(404, detail={"code": "AGENT_RECIPE_NOT_FOUND"})
    versions = (
        db.query(PipelineRecipeVersion)
        .filter(PipelineRecipeVersion.recipe_id == recipe.id)
        .order_by(PipelineRecipeVersion.version.desc())
        .all()
    )
    current = next((item for item in versions if item.status == "current"), None)
    return {
        "id": str(recipe.id),
        "name": recipe.name,
        "domain": recipe.domain,
        "target_column": recipe.target_column,
        "current_version": recipe.current_version,
        "created_at": _iso(recipe.created_at),
        "updated_at": _iso(recipe.updated_at),
        "content": dict(current.content_json or {}) if current is not None else {},
        "versions": [
            {
                "version": item.version,
                "status": item.status,
                "change_note": item.change_note,
                "created_at": _iso(item.created_at),
                "baseline_metrics": (item.content_json or {}).get("baseline_metrics", {}),
            }
            for item in versions
        ],
    }


@router.delete("/recipes/{recipe_id}", status_code=204)
def delete_recipe(
    recipe_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除配方及其全部版本。

    配方无外键引用（服务化链路存内容副本而非引用），删除不影响既有部署；
    权限：admin 或创建者。"""
    recipe = db.get(PipelineRecipe, recipe_id)
    if recipe is None:
        raise HTTPException(404, detail={"code": "AGENT_RECIPE_NOT_FOUND"})
    if current_user.role != "admin" and recipe.created_by != current_user.id:
        raise HTTPException(403, detail={"code": "AGENT_RECIPE_FORBIDDEN"})
    db.query(PipelineRecipeVersion).filter(
        PipelineRecipeVersion.recipe_id == recipe.id,
    ).delete(synchronize_session=False)
    db.delete(recipe)
    db.commit()
