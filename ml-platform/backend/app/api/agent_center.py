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
    token_budget: int | None
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
    return get_agent_run(run.id, db=db, current_user=current_user)


@router.get("/runs/{run_id}", response_model=AgentRunDetail)
def get_agent_run(
    run_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    run = db.get(AgentRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail={"code": "AGENT_RUN_NOT_FOUND"})
    return AgentRunDetail(
        id=str(run.id),
        project_id=_uuid_or_none(run.project_id),
        project_name=None,
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
        token_budget=run.token_budget,
        guidance_json=getattr(run, "guidance_json", None),
        memory_json=run.memory_json or {},
        result_json=run.result_json or {},
    )


@router.get("/recipes", response_model=list[PipelineRecipeOut])
def list_pipeline_recipes(
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    current_version = (
        db.query(PipelineRecipeVersion)
        .filter(PipelineRecipeVersion.version == PipelineRecipe.current_version)
        .with_entities(
            PipelineRecipeVersion.recipe_id,
            PipelineRecipeVersion.status,
            PipelineRecipeVersion.change_note,
        )
        .subquery()
    )
    rows = (
        db.query(PipelineRecipe, Project.name, current_version.c.status, current_version.c.change_note)
        .outerjoin(Project, PipelineRecipe.project_id == Project.id)
        .outerjoin(current_version, current_version.c.recipe_id == PipelineRecipe.id)
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
