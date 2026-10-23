"""P1 wiring additions for the agent center (design-spec diff fixes).

Dataset profile endpoint feeds the wizard's sp-1 columns table (missing rate /
mutual-information rank per column); recipe fixation + version endpoints close
the acceptance→recipe loop (§四/§13.1).
"""

from __future__ import annotations

import uuid as uuid_module

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.database import get_db
from app.models.agent_run import AgentRun
from app.models.recipe import PipelineRecipe, PipelineRecipeVersion
from app.models.user import User

router = APIRouter(prefix="/api/agent", tags=["agent-center"])

SENSITIVE_MASK = "***"


class RecipeFix(BaseModel):
    """验收通过后的固化请求：从 run 档案生成配方 v1（§四）。"""

    run_id: str = Field(min_length=1, max_length=64)
    name: str | None = Field(default=None, max_length=64)
    change_note: str = Field(default="验收通过固化", max_length=500)


def _profile_payload(db: Session, artifact_id, project_id, target: str | None) -> dict:
    from app.services.agent.executor import AgentRunNotExecutable, _load_frame_for

    try:
        frame = _load_frame_for(db, artifact_id, project_id)
    except AgentRunNotExecutable as error:
        raise HTTPException(422, detail={"code": "AGENT_DATASET_UNREADABLE",
                                         "message": str(error)}) from error
    from app.services.agent.profile_data import profile_data

    report = profile_data(frame, target=target)
    # §17.1：行样例不出域——接口只返回列级画像。
    report.pop("row_samples", None)
    return report


@router.get("/datasets/{artifact_id}/profile")
def dataset_profile(
    artifact_id: str,
    target: str | None = None,
    project_id: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """向导 sp-1 数据：列画像（缺失率/互信息排名/注解拆分）——只读、不出域行样例。"""
    try:
        artifact_uuid = uuid_module.UUID(artifact_id)
    except (TypeError, ValueError, AttributeError) as error:
        raise HTTPException(422, detail={"code": "IDENTIFIER_INVALID"}) from error
    project_uuid = None
    if project_id:
        try:
            project_uuid = uuid_module.UUID(project_id)
        except (TypeError, ValueError, AttributeError):
            project_uuid = None
    return _profile_payload(db, artifact_uuid, project_uuid, target)


def _fixation_content(run: AgentRun, memory: dict) -> dict:
    rounds = memory.get("rounds", [])
    final_script = ""
    for record in reversed(rounds):
        for attempt in reversed(record.get("s2_attempts", [])):
            if attempt.get("script"):
                final_script = attempt["script"]
                break
        if final_script:
            break
    gates = dict(((run.guidance_json or {}).get("evaluation") or {}).get(
        "metric_gates", {}
    ))
    return {
        "domain": memory.get("last_domain") or "",
        "inputs": {"target_column": run.target_column},
        "feature_script": final_script,
        "automl_config": ((run.guidance_json or {}).get("modeling") or {}).get(
            "param_hints", {}
        ),
        "acceptance_gates": gates or {"recall_minority": 0.90},
        "baseline_metrics": (run.result_json or {}).get("metrics", {}),
        "analysis_digest": "run %s" % str(run.id)[:8],
        "optimization_report": (run.result_json or {}).get("optimization_report"),
    }


@router.post("/recipes/fixate", status_code=201)
def fixate_recipe(
    payload: RecipeFix,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """验收通过的 run → 配方 v1（幂等：同 run 重复固化返回既有配方）。"""
    try:
        run_uuid = uuid_module.UUID(payload.run_id)
    except (TypeError, ValueError, AttributeError) as error:
        raise HTTPException(422, detail={"code": "IDENTIFIER_INVALID"}) from error
    run = db.get(AgentRun, run_uuid)
    if run is None:
        raise HTTPException(404, detail={"code": "AGENT_RUN_NOT_FOUND"})
    if run.status != "accepted":
        raise HTTPException(
            409, detail={"code": "AGENT_RUN_NOT_ACCEPTED", "status": run.status}
        )
    result_json = run.result_json if isinstance(run.result_json, dict) else {}
    existing = None
    prior_id = result_json.get("recipe_id")
    if prior_id:
        try:
            existing = db.get(PipelineRecipe, uuid_module.UUID(str(prior_id)))
        except (TypeError, ValueError):
            existing = None
    if existing is not None:
        return {"recipe_id": str(existing.id), "version": existing.current_version,
                "created": False}
    from app.services.agent.recipe import create_recipe

    name = (payload.name or ("recipe-%s" % str(run.id)[:8]))[:64]
    recipe = create_recipe(
        db,
        project_id=run.project_id,
        name=name,
        content=_fixation_content(run, run.memory_json or {}),
        change_note=payload.change_note,
        created_by=current_user.id,
    )
    result = dict(result_json)
    result["recipe_id"] = str(recipe.id)
    run.result_json = result
    db.commit()
    return {"recipe_id": str(recipe.id), "version": 1, "created": True}


@router.get("/recipes/{recipe_id}/versions")
def recipe_versions(
    recipe_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.agent.recipe import RecipeNotFound, list_versions

    try:
        versions = list_versions(db, uuid_module.UUID(recipe_id))
    except (RecipeNotFound, ValueError, TypeError):
        raise HTTPException(404, detail={"code": "RECIPE_NOT_FOUND"})
    return [
        {
            "version": item.version,
            "status": item.status,
            "change_note": item.change_note,
            "created_at": item.created_at.isoformat() if item.created_at else None,
            "baseline_metrics": (item.content_json or {}).get("baseline_metrics", {}),
        }
        for item in versions
    ]


@router.post("/recipes/{recipe_id}/rollback")
def recipe_rollback(
    recipe_id: str,
    payload: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.agent.recipe import RecipeNotFound, RecipeVersionNotFound, rollback_recipe

    try:
        to_version = int((payload or {}).get("to_version"))
    except (TypeError, ValueError):
        raise HTTPException(422, detail={"code": "RECIPE_VERSION_INVALID"})
    try:
        rolled = rollback_recipe(
            db,
            uuid_module.UUID(recipe_id),
            to_version=to_version,
            created_by=current_user.id,
        )
    except RecipeVersionNotFound:
        raise HTTPException(404, detail={"code": "RECIPE_VERSION_NOT_FOUND"})
    except RecipeNotFound:
        raise HTTPException(404, detail={"code": "RECIPE_NOT_FOUND"})
    return {"recipe_id": recipe_id, "new_version": rolled.version,
            "status": rolled.status}
