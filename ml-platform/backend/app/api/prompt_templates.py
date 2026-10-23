"""Prompt template CRUD API (spec v0.9 §11.4, AutoML Agent Task A5.1)."""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.database import get_db
from app.models.prompt_template import PromptTemplate
from app.models.user import User

router = APIRouter(prefix="/api/prompt-templates", tags=["prompt-templates"])

STAGES = ("analysis", "feature", "modeling", "evaluation")


class PromptTemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    stage: str = Field(default="analysis")
    content: str = Field(min_length=1, max_length=8000)
    project_id: str | None = Field(default=None, max_length=64)


class PromptTemplateUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    stage: str | None = None
    content: str | None = Field(default=None, min_length=1, max_length=8000)


def _out(template: PromptTemplate) -> dict:
    return {
        "id": str(template.id),
        "name": template.name,
        "stage": template.stage,
        "content": template.content,
        "project_id": str(template.project_id) if template.project_id else None,
        "usage_count": template.usage_count,
    }


@router.get("")
def list_templates(
    stage: str | None = None,
    project_id: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(PromptTemplate).filter(PromptTemplate.owner_id == current_user.id)
    if stage:
        query = query.filter(PromptTemplate.stage == stage)
    if project_id:
        query = query.filter(PromptTemplate.project_id == _uuid(project_id))
    return [_out(item) for item in query.order_by(PromptTemplate.name).all()]


@router.post("", status_code=201)
def create_template(
    payload: PromptTemplateCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if payload.stage not in STAGES:
        raise HTTPException(
            422, detail={"code": "PROMPT_TEMPLATE_STAGE_INVALID", "stages": list(STAGES)}
        )
    duplicate = (
        db.query(PromptTemplate)
        .filter(
            PromptTemplate.owner_id == current_user.id,
            PromptTemplate.name == payload.name,
        )
        .first()
    )
    if duplicate is not None:
        raise HTTPException(409, detail={"code": "PROMPT_TEMPLATE_NAME_CONFLICT"})
    template = PromptTemplate(
        name=payload.name,
        stage=payload.stage,
        content=payload.content,
        owner_id=current_user.id,
        project_id=_uuid(payload.project_id) if payload.project_id else None,
    )
    db.add(template)
    db.commit()
    db.refresh(template)
    return _out(template)


@router.patch("/{template_id}")
def update_template(
    template_id: str,
    payload: PromptTemplateUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    template = _owned(db, template_id, current_user)
    if payload.name is not None:
        template.name = payload.name
    if payload.stage is not None:
        if payload.stage not in STAGES:
            raise HTTPException(422, detail={"code": "PROMPT_TEMPLATE_STAGE_INVALID"})
        template.stage = payload.stage
    if payload.content is not None:
        template.content = payload.content
    db.commit()
    db.refresh(template)
    return _out(template)


@router.delete("/{template_id}", status_code=204)
def delete_template(
    template_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    template = _owned(db, template_id, current_user)
    db.delete(template)
    db.commit()


@router.post("/{template_id}/use")
def use_template(
    template_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """向导引用一次模板：计数 +1 并返回正文（§11.4 存取复用）。"""
    template = _owned(db, template_id, current_user)
    template.usage_count = int(template.usage_count or 0) + 1
    db.commit()
    return _out(template)


def _owned(db: Session, template_id: str, current_user: User) -> PromptTemplate:
    template = db.get(PromptTemplate, _uuid(template_id))
    if template is None or template.owner_id != current_user.id:
        raise HTTPException(404, detail={"code": "PROMPT_TEMPLATE_NOT_FOUND"})
    return template


def _uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError) as error:
        raise HTTPException(422, detail={"code": "IDENTIFIER_INVALID"}) from error
