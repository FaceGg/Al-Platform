"""Agent center read-only listings (AutoML Agent plan, front-end wiring).

Exposes agent run metadata and pipeline recipe metadata for the Agent Center
page. These endpoints are deliberately metadata-only: run memory/result JSON
and recipe version content (feature scripts, modeling configs) never leave
the platform through this surface.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
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
