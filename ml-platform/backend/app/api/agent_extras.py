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
from app.database import SessionLocal as SessionLocal_, get_db
from app.models.agent_run import AgentRun
from app.models.artifact import Artifact
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


def _fixation_content(run: AgentRun, memory: dict, db: Session | None = None) -> dict:
    """API 侧固化构造：与 runner 同源（build_fixation_content）+ smoke_row。

    smoke_row 从源 run 数据集首行生成（S5 冒烟输入）——runner 自动固化路径
    带此参数，API fixate 路径此前漏了：档案页凭该配方服务化时 dry-run 冒烟
    必挂 RECORD_INVALID（run 4f9ffdc7 配方实测）。"""
    import pandas as pd
    import tempfile
    from pathlib import Path

    from app.services.agent.recipe import build_fixation_content, smoke_row_from_frame

    smoke_row: dict = {}
    if db is not None and run.dataset_artifact_id is not None:
        try:
            from app.services.artifact_service import build_artifact_service

            artifact_service = build_artifact_service(db)
            with artifact_service.materialize(
                run.dataset_artifact_id, run.project_id, expected_type="dataset",
            ) as dataset_path:
                probe = pd.read_csv(dataset_path, nrows=1)
            smoke_row = smoke_row_from_frame(probe)
        except Exception:  # noqa: BLE001 - 冒烟行缺失不阻断固化
            smoke_row = {}
    return build_fixation_content(
        run, memory,
        smoke_row=smoke_row,
        target_values=_target_values(db, run) if db is not None else None,
    )


def _target_values(db: Session | None, run: AgentRun) -> list | None:
    """源数据集目标列取值（target_semantics 生产输入）；失败返回 None。"""
    if db is None or run.dataset_artifact_id is None:
        return None
    try:
        import pandas as pd

        from app.services.artifact_service import build_artifact_service

        artifact_service = build_artifact_service(db)
        with artifact_service.materialize(
            run.dataset_artifact_id, run.project_id, expected_type="dataset",
        ) as dataset_path:
            series = pd.read_csv(dataset_path, usecols=[run.target_column])[run.target_column]
        return [value for value in series.dropna().unique()]
    except Exception:  # noqa: BLE001
        return None


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
        # 存量配方升级回填：早期固化的版本缺 guidance 快照（agent 重训重放
        # 的输入合同）或 smoke_row（S5 冒烟输入），补发一个新版本而不是
        # 拒绝——同配方行，版本递增。注意保留现版本的 acceptance_gates
        # （后续按引擎口径校准过的门禁不能被源 run 默认门禁覆盖）。
        from app.services.agent.recipe import get_current_version, update_recipe

        current = get_current_version(db, existing.id)
        current_content = dict(current.content_json or {})
        missing = not current_content.get("guidance") or not (
            current_content.get("smoke_row") or {}
        )
        if missing:
            rebuilt = _fixation_content(run, run.memory_json or {}, db=db)
            gates = current_content.get("acceptance_gates")
            if gates:
                rebuilt["acceptance_gates"] = gates
            update_recipe(
                db,
                existing.id,
                content=rebuilt,
                change_note="backfill guidance snapshot/smoke_row for servitize",
            )
            return {"recipe_id": str(existing.id), "version": existing.current_version,
                    "created": False, "backfilled": True}
        return {"recipe_id": str(existing.id), "version": existing.current_version,
                "created": False}
    from app.services.agent.recipe import create_recipe

    name = (payload.name or ("recipe-%s" % str(run.id)[:8]))[:64]
    recipe = create_recipe(
        db,
        project_id=run.project_id,
        name=name,
        content=_fixation_content(run, run.memory_json or {}, db=db),
        change_note=payload.change_note,
        created_by=current_user.id,
    )
    result = dict(result_json)
    result["recipe_id"] = str(recipe.id)
    run.result_json = result
    db.commit()
    return {"recipe_id": str(recipe.id), "version": 1, "created": True}


@router.get("/recipes")
def list_recipes(
    project_id: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """项目内固化配方列表（闭环 agent 重训模式绑定选择用）。

    has_guidance 标记当前版本是否已带 guidance 快照——无快照的存量配方
    绑定后触发会被 fail-closed 拒绝（需对源 run 重新固化回填）。
    """
    from app.services.agent.recipe import get_current_version

    query = db.query(PipelineRecipe)
    if project_id:
        try:
            query = query.filter(
                PipelineRecipe.project_id == uuid_module.UUID(project_id))
        except (TypeError, ValueError):
            raise HTTPException(422, detail={"code": "IDENTIFIER_INVALID"})
    rows = query.order_by(PipelineRecipe.created_at.desc()).limit(100).all()
    out = []
    for recipe in rows:
        try:
            current = get_current_version(db, recipe.id)
            content = dict(current.content_json or {})
        except LookupError:
            content = {}
        out.append({
            "id": str(recipe.id),
            "name": recipe.name,
            "domain": recipe.domain,
            "target_column": recipe.target_column,
            "current_version": recipe.current_version,
            "has_guidance": bool(content.get("guidance")),
            "created_at": recipe.created_at.isoformat() if recipe.created_at else None,
        })
    return out


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


# --------------------------------------------------------------------------
# S5 servitization (§12.1): draft (①–④ dry-run smoke) + approval switch (⑤)
# --------------------------------------------------------------------------

class ServitizeRequest(BaseModel):
    """服务化草稿请求：绑定配方当前版本 + 部署（既有或刚铸造的）。

    部署来自平台标准上线链（注册-批准-部署）；「启动并服务化」的完整语义
    由 /servitize/cast-deployment 补齐：先按配方铸造最优模型并新建部署，
    再绑定服务化（§12.2 映射表）。
    """

    recipe_id: str = Field(min_length=1, max_length=64)
    deployment_id: str = Field(min_length=1, max_length=64)
    project_id: str | None = Field(default=None, max_length=64)
    model_api_name: str | None = Field(default=None, max_length=240)
    error_classes_override: list[str] | None = None


class CastDeploymentRequest(BaseModel):
    """按配方铸造部署：触发引擎 AutoML job（白名单/集成/列指令随配方下发）。

    两段式：POST 触发返回 job_id；GET /cast-deployment/{job_id} 轮询，
    job 完成时注册冠军→批准→创建新部署→启动，返回 deployment（幂等）。
    """

    recipe_id: str = Field(min_length=1, max_length=64)
    project_id: str = Field(min_length=1, max_length=64)
    run_id: str | None = Field(default=None, max_length=64)
    dataset_artifact_id: str | None = Field(default=None, max_length=64)
    max_trials: int = Field(default=10, ge=5, le=200)
    # 集成覆盖（默认跟随配方；显式开启时用 top-K soft-voting 抬召回——
    # 引擎 CV 口径下单模型欠门禁时的补救路径，冠军仍须过配方门禁）
    ensemble_enabled: bool | None = None
    ensemble_top_k: int = Field(default=3, ge=2, le=5)


@router.post("/servitize/cast-deployment", status_code=201)
def cast_deployment(
    payload: CastDeploymentRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """铸造段①：按配方当前版本触发引擎 AutoML job（验收成果落地为可部署模型）。

    白名单/集成/特征列随配方下发（与闭环智能体重训铸造同参）；数据集默认
    取源 run 的重放合并工件，缺省回落显式传入或项目最新数据集。"""
    from datetime import datetime, timezone

    from app.models.training import TrainingJob
    from app.services.agent.recipe import get_current_version
    from app.services.closed_loop_actions import trigger_retrain_job

    try:
        recipe_uuid = uuid_module.UUID(payload.recipe_id)
        project_uuid = uuid_module.UUID(payload.project_id)
    except (TypeError, ValueError) as error:
        raise HTTPException(422, detail={"code": "IDENTIFIER_INVALID"}) from error
    recipe_row = db.get(PipelineRecipe, recipe_uuid)
    if recipe_row is None or str(recipe_row.project_id) != str(project_uuid):
        raise HTTPException(404, detail={"code": "RECIPE_NOT_FOUND"})
    try:
        version = get_current_version(db, recipe_uuid)
    except Exception:
        raise HTTPException(404, detail={"code": "RECIPE_NOT_FOUND"}) from None
    content = dict(version.content_json or {})
    inputs = content.get("inputs") or {}
    target_column = str(inputs.get("target_column") or "").strip()
    if not target_column:
        raise HTTPException(422, detail={"code": "CAST_TARGET_MISSING"})

    # 数据集：源 run 重放工件 > 显式传入 > 项目最新用户数据集
    dataset_id = payload.dataset_artifact_id
    if not dataset_id and payload.run_id:
        run_row = db.get(AgentRun, uuid_module.UUID(payload.run_id)) \
            if _is_uuid(payload.run_id) else None
        if run_row is not None and run_row.dataset_artifact_id is not None:
            dataset_id = str(run_row.dataset_artifact_id)
    if not dataset_id:
        latest = (
            db.query(Artifact)
            .filter(
                Artifact.project_id == project_uuid,
                Artifact.type == "dataset",
            )
            .order_by(Artifact.created_at.desc())
            .first()
        )
        if latest is None:
            raise HTTPException(422, detail={"code": "CAST_DATASET_MISSING"})
        dataset_id = str(latest.id)

    retrain_ensemble = dict(content.get("retrain_ensemble") or {})
    if payload.ensemble_enabled is True:
        ensemble = {"enabled": True, "top_k": payload.ensemble_top_k}
    elif payload.ensemble_enabled is False:
        ensemble = None
    else:
        ensemble = (
            {"enabled": True, "top_k": int(retrain_ensemble.get("top_k") or 3)}
            if retrain_ensemble.get("enabled") else None
        )

    # 「本次最优」的完整语义：先按配方的 S2 特征脚本把原始数据集变换为
    # 特征帧（与 S4 验收时同一张表）并物化为铸造数据集——稀疏原表直接喂
    # 引擎必然 0 行幸存（dropna 全剔），且丢弃 S2 学到的特征工程等于丢
    # 弃本次任务的核心成果。脚本失败再回落列指令推导路径。
    cast_dataset_id = dataset_id
    input_columns = [str(x) for x in (content.get("retrain_input_columns") or [])]
    feature_script = str(content.get("feature_script") or "").strip()
    if feature_script and not input_columns:
        try:
            import pandas as pd_frame

            from app.services.agent.sandbox import run_sandbox
            from app.services.artifact_service import build_artifact_service

            artifact_service = build_artifact_service(db)
            with artifact_service.materialize(
                uuid_module.UUID(dataset_id), project_uuid, expected_type="dataset",
            ) as dataset_path:
                raw_frame = pd_frame.read_csv(dataset_path)
            sandbox = run_sandbox(feature_script, raw_frame, timeout_seconds=300)
            if sandbox.ok and getattr(sandbox, "output", None) is not None:
                cast_frame = sandbox.output
                if target_column not in cast_frame.columns and target_column in raw_frame.columns:
                    cast_frame[target_column] = raw_frame[target_column].values
                import tempfile
                from pathlib import Path as _Path

                with tempfile.TemporaryDirectory() as tmp:
                    cast_path = _Path(tmp) / "cast-features.csv"
                    cast_frame.to_csv(cast_path, index=False)
                    cast_artifact = artifact_service.create_from_file(
                        project_uuid, cast_path,
                        f"服务化铸造特征集-{cycle_hint(recipe_row.name)}",
                        "dataset",
                        metadata={"source": "servitize-cast-features",
                                  "recipe_id": str(recipe_uuid),
                                  "row_count": int(len(cast_frame)),
                                  "column_count": int(len(cast_frame.columns))},
                    )
                cast_dataset_id = str(cast_artifact.id)
                input_columns = [
                    str(column)
                    for column in cast_frame.columns
                    if column != target_column
                    and str(cast_frame[column].dtype) in {"int64", "float64", "int32", "float32"}
                ]
        except Exception:  # noqa: BLE001 - 特征变换失败回落原始数据集+列推导
            cast_dataset_id = dataset_id
            input_columns = input_columns or []
    if not input_columns:
        guidance = dict(content.get("guidance") or {})
        feature_guidance = dict(guidance.get("feature") or {})
        drop_set = {
            str(item.get("column"))
            for item in (feature_guidance.get("suggest_drop") or [])
            if isinstance(item, dict) and item.get("column")
        }
        try:
            from app.services.artifact_service import build_artifact_service

            artifact_service = build_artifact_service(db)
            with artifact_service.materialize(
                uuid_module.UUID(dataset_id), project_uuid, expected_type="dataset",
            ) as dataset_path:
                import pandas as pd_frame

                probe = pd_frame.read_csv(dataset_path, nrows=5)
            input_columns = [
                str(column)
                for column in probe.columns
                if column != target_column
                and column not in drop_set
                and str(probe[column].dtype) in {"int64", "float64", "int32", "float32"}
            ]
        except Exception:  # noqa: BLE001 - 推导失败回落引擎默认全 numeric
            input_columns = []

    cycle = uuid_module.uuid4().hex[:8]
    job = trigger_retrain_job(
        db,
        project_id=project_uuid,
        actor_id=current_user.id,
        experiment_name=f"服务化铸造-{recipe_row.name[:24]}-{cycle}",
        job_name=f"服务化铸造-{cycle}",
        dataset_artifact_id=cast_dataset_id,
        target_column=target_column,
        max_trials=payload.max_trials,
        ensemble=ensemble,
        algorithm_ids=[str(x) for x in (content.get("retrain_algorithm_ids") or [])] or None,
        input_columns=input_columns or None,
    )
    # 铸造上下文存配方版本 content（幂等锚点 + 轮询端点取回）
    meta = dict(content.get("cast_deployment") or {})
    meta.update({
        "job_id": str(job.id),
        "requested_by": str(current_user.id),
        "requested_at": datetime.now(timezone.utc).isoformat(),
        "deployment_id": meta.get("deployment_id"),
    })
    updated = dict(content)
    updated["cast_deployment"] = meta
    from app.services.agent.recipe import update_recipe

    update_recipe(db, recipe_uuid, content=updated,
                  change_note="cast-deployment requested (servitize)")
    return {"job_id": str(job.id), "recipe_id": str(recipe_uuid),
            "status": job.status, "max_trials": payload.max_trials}


@router.get("/servitize/cast-deployment/{job_id}")
def cast_deployment_status(
    job_id: str,
    recipe_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """铸造段②：轮询铸造 job；完成时注册冠军→批准→新建部署→启动（幂等）。

    返回 {status, deployment_id?}；重复调用 job 完成态直接返回已建部署。"""
    from app.models.model_registry import InferenceDeployment
    from app.models.training import TrainingJob
    from app.services.agent.recipe import get_current_version, update_recipe
    from app.services.closed_loop_actions import complete_retrain_swap
    from app.services.model_registry import ModelRegistryService
    from app.services.artifact_service import build_artifact_service

    if not _is_uuid(job_id) or not _is_uuid(recipe_id):
        raise HTTPException(422, detail={"code": "IDENTIFIER_INVALID"})
    recipe_uuid = uuid_module.UUID(recipe_id)
    job = db.get(TrainingJob, uuid_module.UUID(job_id))
    if job is None:
        raise HTTPException(404, detail={"code": "CAST_JOB_NOT_FOUND"})
    try:
        version = get_current_version(db, recipe_uuid)
    except Exception:
        raise HTTPException(404, detail={"code": "RECIPE_NOT_FOUND"}) from None
    content = dict(version.content_json or {})
    meta = dict(content.get("cast_deployment") or {})

    # 幂等：已建部署直接返回
    existing = meta.get("deployment_id")
    if existing and _is_uuid(existing):
        dep = db.get(InferenceDeployment, uuid_module.UUID(existing))
        if dep is not None:
            return {"status": "deployed", "deployment_id": str(dep.id),
                    "model_version_id": str(dep.model_version_id),
                    "deployment_state": dep.observed_state}

    if job.status in {"pending", "queued", "running", "cancel_requested"}:
        return {"status": job.status}
    if job.status != "completed":
        return {"status": "failed", "error": job.error_message or job.error_code}

    # 完成：换模服务（注册+批准）→ 新建部署（不动既有部署）→ 启动。
    # recipe_id 传入供配方门禁兜底（recall_minority 键已在 P2-1 对齐）。
    version_model = complete_retrain_swap(
        db,
        deployment_id=None,  # 不绑既有部署：只注册批准，不换模
        job=job,
        actor_id=current_user.id,
        model_name=f"服务化铸造-{str(recipe_uuid)[:8]}",
        recipe_id=recipe_uuid,
    )
    if version_model is None:
        return {"status": "vetoed",
                "error": "铸造候选未过配方验收门禁（或无可注册候选），请检查配方门禁阈值"}
    from app.services.demo_loop import _deployment_service

    dep_service = _deployment_service()
    if dep_service is None:
        from app.config import settings
        from app.services.inference_deployment import InferenceDeploymentService
        from app.services.inference_runtime import InferenceRuntimeClient

        dep_service = InferenceDeploymentService(
            InferenceRuntimeClient(
                settings.inference_runtime_url,
                settings.resolved_inference_internal_secret.get_secret_value(),
            ), SessionLocal_,
        )
    deployment = dep_service.create(
        db, project_id=job.project_id, version_id=version_model.id,
        actor_id=current_user.id,
        name=f"智能体服务化-{str(recipe_uuid)[:8]}", commit=True,
    )
    dep_service.start(db, deployment.id)
    db.refresh(deployment)
    meta["deployment_id"] = str(deployment.id)
    updated = dict(content)
    updated["cast_deployment"] = meta
    update_recipe(db, recipe_uuid, content=updated,
                  change_note="cast-deployment created deployment")
    return {"status": "deployed", "deployment_id": str(deployment.id),
            "model_version_id": str(version_model.id),
            "deployment_state": deployment.observed_state}


def _is_uuid(value: str | None) -> bool:
    try:
        uuid_module.UUID(str(value))
        return True
    except (TypeError, ValueError):
        return False


def cycle_hint(name: str) -> str:
    """铸造工件命名的短后缀（配方针名可读且不撞唯一约束）。"""
    import re as _re

    base = _re.sub(r"[^\w\u4e00-\u9fff-]+", "", name)[:16] or "recipe"
    return f"{base}-{uuid_module.uuid4().hex[:6]}"


@router.post("/servitize", status_code=201)
def servitize(
    payload: ServitizeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """按配方创建三资产草稿（①部署引用 ②闭环任务 paused ③模型 API offline
    ④dry_run 冒烟零回流）。返回草稿 + 冒烟结果 + 歧义标签供发布预览。"""
    from app.models.recipe import PipelineRecipe
    from app.services.agent.recipe import get_current_version
    from app.services.agent.servitize import servitize_recipe

    try:
        recipe_uuid = uuid_module.UUID(payload.recipe_id)
    except (TypeError, ValueError) as error:
        raise HTTPException(422, detail={"code": "IDENTIFIER_INVALID"}) from error
    try:
        version = get_current_version(db, recipe_uuid)
    except Exception:
        raise HTTPException(404, detail={"code": "RECIPE_NOT_FOUND"}) from None
    recipe_row = db.get(PipelineRecipe, recipe_uuid)
    project_id = payload.project_id or (
        str(recipe_row.project_id) if recipe_row and recipe_row.project_id else None
    )
    if not project_id:
        raise HTTPException(422, detail={"code": "PROJECT_REQUIRED"})
    try:
        draft = servitize_recipe(
            db,
            project_id=uuid_module.UUID(str(project_id)),
            actor_id=current_user.id,
            deployment_id=payload.deployment_id,
            recipe_content=dict(version.content_json or {}),
            model_api_name=payload.model_api_name,
            error_classes_override=payload.error_classes_override,
        )
    except LookupError:
        raise HTTPException(404, detail={"code": "DEPLOYMENT_NOT_FOUND"})
    except ValueError as error:
        raise HTTPException(422, detail={"code": "SERVITIZE_INVALID",
                                         "message": str(error)})
    return {
        "deployment_id": draft.deployment_id,
        "loop_config_id": draft.loop_config_id,
        "model_api_id": draft.model_api_id,
        "model_api_name": draft.model_api_name,
        "error_classes": draft.error_classes,
        "ambiguous_labels": draft.ambiguous_labels,
        "smoke": draft.smoke,
        "activated": draft.activated,
    }


class ActivateRequest(BaseModel):
    model_api_id: str = Field(min_length=1, max_length=64)


@router.post("/servitize/activate")
def servitize_activate(
    payload: ActivateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """⑤ 人工批准：模型 API offline→published（唯一对外开关）。"""
    from app.services.agent.servitize import activate_servitize

    try:
        api = activate_servitize(
            db, model_api_id=payload.model_api_id, actor_id=current_user.id
        )
    except LookupError:
        raise HTTPException(404, detail={"code": "MODEL_API_NOT_FOUND"})
    except ValueError as error:
        raise HTTPException(409, detail={"code": "SERVITIZE_STATE_INVALID",
                                         "message": str(error)})
    return {"model_api_id": str(api.id), "status": api.status}
