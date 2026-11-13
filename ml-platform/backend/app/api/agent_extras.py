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


def _numeric_feature_columns(frame, target_column: str | None, drop_set: set | None = None) -> list[str]:
    """从 frame 推导引擎可用的数值特征列（服务化铸造用）。

    剔除：目标列、drop 集合、非数值列、**全 NaN 数值列**——最后一项是
    实测坑：全 NaN 列 dtype 恰为 float64 会被当特征带上，引擎
    dropna(subset=全部特征列) 时把 2180 行清零，报出误导性的
    「AutoML requires numeric features and at least ten rows」。
    """
    return [
        str(column)
        for column in frame.columns
        if column != target_column
        and (not drop_set or column not in drop_set)
        and str(frame[column].dtype) in {"int64", "float64", "int32", "float32"}
        and frame[column].notna().any()
    ]


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
    """源数据集目标列取值（target_semantics 生产输入），按出现频次升序——
    首个即少数类（缺陷类兜底依据，见 derive_error_classes）；失败返回 None。"""
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
        return list(series.dropna().value_counts(ascending=True).index)
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
    # 显式重铸（跳过触发幂等）：在途/已完成时仍强制新开一轮
    force: bool = False
    # 部署模式：s3=直接部署本次验收的冠军模型（默认，秒级零重训）；
    # engine=按配方触发 AutoML 重铸（两段式轮询，追求更高上限）
    mode: str = Field(default="s3", pattern="^(s3|engine)$")


@router.post("/servitize/cast-deployment", status_code=201)
def cast_deployment(
    payload: CastDeploymentRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """部署段①：把验收成果落地为 running 部署。

    mode=s3（默认，直接部署本次模型）：源 run 验收时物化的 S3 冠军工件
    → ModelLibrary → 注册（含 ONNX 端口转换）→ 批准 → 新建部署 → 启动。
    秒级完成、零重训——部署的就是 S4 验收时评的那个模型。
    mode=engine（引擎重铸）：按配方触发 AutoML job（全量+搜索+集成终选），
    两段式轮询——追求更高上限时用。"""
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

    # ---- s3 快路径：直接部署本次验收的冠军模型（无训练） ----
    if payload.mode == "s3":
        run_key = payload.run_id
        run_row = None
        if run_key and _is_uuid(run_key):
            run_row = db.get(AgentRun, uuid_module.UUID(run_key))
        if run_row is None or run_row.project_id != project_uuid:
            raise HTTPException(404, detail={"code": "AGENT_RUN_NOT_FOUND"})
        champion_key = str((run_row.result_json or {}).get("s3_champion_artifact_id") or "")
        if not champion_key or not _is_uuid(champion_key):
            raise HTTPException(422, detail={
                "code": "S3_CHAMPION_NOT_PERSISTED",
                "message": "该任务验收时未物化 S3 冠军模型（旧版本任务）——"
                           "请用引擎重铸模式，或重新提交任务后再直接部署",
            })
        deployment_id = _deploy_s3_champion(
            db, project_uuid=project_uuid, champion_artifact_id=champion_key,
            actor_id=current_user.id, recipe_row=recipe_row, run_row=run_row,
        )
        return {"mode": "s3", "status": "deployed",
                "deployment_id": deployment_id,
                "recipe_id": str(recipe_uuid)}

    # ---- engine 慢路径：按配方触发 AutoML 重铸（两段式轮询） ----
    try:
        version = get_current_version(db, recipe_uuid)
    except Exception:
        raise HTTPException(404, detail={"code": "RECIPE_NOT_FOUND"}) from None
    content = dict(version.content_json or {})
    inputs = content.get("inputs") or {}
    target_column = str(inputs.get("target_column") or "").strip()
    # 范式感知（技术方案 §2.1/§3.4/§3.7）：无监督配方本就没有目标列——
    # 配方固化 content 带 anomaly 段，重放走同一无监督引擎合同
    # （target_columns=[]、CV off、contamination 随配方透传），
    # 不再因缺目标列 422。有监督配方缺目标列仍照旧报 CAST_TARGET_MISSING。
    from app.services.agent.loop_retrain import (
        ANOMALY_ENGINE_TASK_TYPE,
        ANOMALY_PARA_DIGM,
        detect_recipe_paradigm,
        recipe_anomaly_config,
    )

    is_anomaly = detect_recipe_paradigm(content) == ANOMALY_PARA_DIGM
    if not target_column and not is_anomaly:
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

    # 触发幂等（页面重复点击/退出重进场景）：配方已有在途铸造 job 或已建
    # 部署时直接返回既有状态，不再新开 job（此前每次点击都新开——DB 堆
    # 多个 running 的实测根因）。显式 force=True 才允许重铸。
    existing_cast = dict(content.get("cast_deployment") or {})
    existing_job_key = str(existing_cast.get("job_id") or "")
    if existing_job_key and _is_uuid(existing_job_key) and not payload.force:
        from app.models.training import TrainingJob as _TJ

        existing_job = db.get(_TJ, uuid_module.UUID(existing_job_key))
        existing_dep_key = str(existing_cast.get("deployment_id") or "")
        if existing_dep_key and _is_uuid(existing_dep_key):
            dep_row = db.get(InferenceDeployment, uuid_module.UUID(existing_dep_key))
            if dep_row is not None:
                return {"job_id": existing_job_key, "recipe_id": str(recipe_uuid),
                        "status": "deployed", "deployment_id": existing_dep_key,
                        "max_trials": payload.max_trials, "resumed": True}
        if existing_job is not None and existing_job.status in {
            "pending", "queued", "running", "cancel_requested",
        }:
            return {"job_id": existing_job_key, "recipe_id": str(recipe_uuid),
                    "status": existing_job.status,
                    "max_trials": payload.max_trials, "resumed": True}

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
                # 无监督无目标列（target_column=""）→ 不回填目标列。
                if (target_column and target_column not in cast_frame.columns
                        and target_column in raw_frame.columns):
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
                input_columns = _numeric_feature_columns(cast_frame, target_column)
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
                input_columns = _numeric_feature_columns(probe, target_column, drop_set)
                # probe 前 5 行全空的数值列不能直接判死（可能是偶发缺失），
                # 全量复核后剔除真全 NaN 列（dropna 清空全部行的元凶）
                suspicious = [
                    column for column in input_columns
                    if probe[column].notna().sum() == 0
                ]
                if suspicious:
                    full = pd_frame.read_csv(dataset_path)
                    input_columns = [
                        column for column in input_columns
                        if column not in suspicious
                        or full[column].notna().any()
                    ]
        except Exception:  # noqa: BLE001 - 推导失败回落引擎默认全 numeric
            input_columns = []

    cycle = uuid_module.uuid4().hex[:8]
    cast_kwargs = dict(
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
    if is_anomaly:
        # 无监督引擎合同（技术方案 §3.1/§3.7，复用引擎既有构造器）：
        # target_columns=[]、CV off、contamination 随配方透传、算法族收敛
        # 无监督白名单（iforest/ocsvm/autoencoder）。特征列走数值列推导
        # （无监督无目标列可剔除）。
        anomaly_cfg = recipe_anomaly_config(content)
        cast_kwargs.update({
            "target_column": "",
            "task_type": ANOMALY_ENGINE_TASK_TYPE,
            "anomaly_contamination": anomaly_cfg["contamination"],
            "condition_column": anomaly_cfg["condition_column"],
            "algorithm_ids": anomaly_cfg["algorithm_ids"],
            "ensemble": None,
        })
    job = trigger_retrain_job(db, **cast_kwargs)
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




def _deploy_s3_champion(
    db, *, project_uuid, champion_artifact_id: str, actor_id, recipe_row, run_row,
) -> str:
    """S3 冠军工件 → 库 → 注册（ONNX 端口）→ 批准 → 新建部署 → 启动。幂等：
    同工件重复部署复用已建部署（配方 cast_deployment 元数据锚定）。"""
    from app.models.model_library import ModelLibrary
    from app.models.model_registry import InferenceDeployment, RegisteredModel
    from app.services.artifact_service import build_artifact_service
    from app.services.model_registry import ModelRegistryService

    from app.services.agent.recipe import get_current_version

    version_row = get_current_version(db, recipe_row.id)
    meta = dict((version_row.content_json or {}).get("cast_deployment") or {})
    # s3 直部署的幂等锚独立于 engine 铸造（deployment_id）——两种模式
    # 各自的产物互不顶替：s3 部署记 s3_deployment_id，重复调用复用。
    existing = str(meta.get("s3_deployment_id") or "")
    if existing and _is_uuid(existing):
        dep = db.get(InferenceDeployment, uuid_module.UUID(existing))
        if dep is not None:
            return str(dep.id)

    artifact_service = build_artifact_service(db)
    artifact = artifact_service.resolve(
        uuid_module.UUID(champion_artifact_id), project_uuid, expected_type="model")
    artifact_meta = dict(artifact.metadata_ or {})
    library = ModelLibrary(
        name=f"智能体S3-{str(run_row.id)[:8]}",
        project_id=project_uuid,
        owner_id=actor_id,
        status="completed",
        format="joblib",
        framework="sklearn",
        backbone=str(artifact_meta.get("algorithm") or "s3-champion"),
        metrics=dict(artifact_meta.get("metrics") or {}),
        params={},
    )
    db.add(library)
    db.flush()
    library.model_artifact_id = artifact.id
    db.commit()

    registered = RegisteredModel(
        project_id=project_uuid, name=f"agent-s3-{str(run_row.id)[:8]}",
        created_by_id=actor_id)
    db.add(registered)
    db.flush()
    registry = ModelRegistryService(artifact_service=artifact_service)
    try:
        version = registry.register_platform_version(
            db, model_id=registered.id,
            source_model_library_id=library.id, actor_id=actor_id)
    except Exception as error:  # noqa: BLE001 - 转换失败原样上抛（422 呈现）
        db.rollback()
        raise HTTPException(422, detail={
            "code": "S3_DEPLOY_CONVERSION_FAILED",
            "message": f"S3 冠军模型注册/ONNX 转换失败：{error}",
        }) from error
    if version.approval_status != "approved":
        registry.transition_model_version(db, version.id, "approve", actor_id)

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
            ), SessionLocal_)
    deployment = dep_service.create(
        db, project_id=project_uuid, version_id=version.id, actor_id=actor_id,
        name=f"智能体部署-{str(run_row.id)[:8]}", commit=True)
    dep_service.start(db, deployment.id)
    db.refresh(deployment)
    # 配方锚定（幂等）+ 留档：s3 部署写独立锚，不覆盖 engine 铸造锚
    updated = dict(version_row.content_json or {})
    cast_meta = dict(updated.get("cast_deployment") or {})
    cast_meta["s3_deployment_id"] = str(deployment.id)
    cast_meta["mode"] = "s3"
    cast_meta["s3_run_id"] = str(run_row.id)
    updated["cast_deployment"] = cast_meta
    from app.services.agent.recipe import update_recipe

    update_recipe(db, recipe_row.id, content=updated,
                  change_note="s3 champion deployed (direct)")
    return str(deployment.id)


@router.get("/servitize/cast-deployment/current")
def cast_deployment_current(
    recipe_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """页面恢复入口：配方当前铸造状态（无/job 态/deployed/failed）。

    进入任务页时调用——退出重进后前端据此恢复铸造 UI（在途自动续轮询、
    已部署自动选中），不必重新点「② 铸造新部署」。"""
    from app.models.model_registry import InferenceDeployment
    from app.models.training import TrainingJob
    from app.services.agent.recipe import get_current_version

    if not _is_uuid(recipe_id):
        raise HTTPException(422, detail={"code": "IDENTIFIER_INVALID"})
    try:
        version = get_current_version(db, uuid_module.UUID(recipe_id))
    except Exception:
        raise HTTPException(404, detail={"code": "RECIPE_NOT_FOUND"}) from None
    meta = dict((version.content_json or {}).get("cast_deployment") or {})
    # s3 直部署锚优先（新默认路径），回落 engine 铸造锚
    dep_key = str(meta.get("s3_deployment_id") or meta.get("deployment_id") or "")
    if dep_key and _is_uuid(dep_key):
        dep = db.get(InferenceDeployment, uuid_module.UUID(dep_key))
        if dep is not None:
            # 附带该部署的服务化条目状态（published/offline/none）——前端
            # 恢复时据此把③④步直接置为完成/草稿态，已发布的不再让用户
            # 重复点③触发 "already published" 防护报错。
            from app.models.api_model import PlatformAPI

            api_row = (
                db.query(PlatformAPI)
                .filter(
                    PlatformAPI.source_kind == "servitize",
                    PlatformAPI.source_id == uuid_module.UUID(dep_key),
                )
                .first()
            )
            servitize_state = (
                {
                    "status": api_row.status,
                    "model_api_id": str(api_row.id),
                    "model_api_name": api_row.name,
                }
                if api_row is not None
                else {"status": "none"}
            )
            return {"status": "deployed", "job_id": meta.get("job_id"),
                    "deployment_id": dep_key,
                    "model_version_id": str(dep.model_version_id),
                    "deployment_state": dep.observed_state,
                    "servitize": servitize_state}
    job_key = str(meta.get("job_id") or "")
    if job_key and _is_uuid(job_key):
        job = db.get(TrainingJob, uuid_module.UUID(job_key))
        if job is not None:
            payload_out = {"status": job.status, "job_id": job_key}
            if job.status == "failed":
                payload_out["error"] = job.error_message or job.error_code
            if job.status == "completed":
                # job 完成但无部署：补一轮收尾（幂等）再返回
                return cast_deployment_status(
                    job_key, recipe_id=recipe_id, db=db, current_user=current_user)
            return payload_out
    return {"status": "idle"}


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
            recipe_id=recipe_uuid,
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


class PublishTargetsRequest(BaseModel):
    """④ 批准发布的三目标开关（默认全发）：api+loop 走既有 activate，
    orchestration 实例化闭环服务模板并发布编排 API。"""
    model_api_id: str = Field(min_length=1, max_length=64)
    project_id: str = Field(min_length=1, max_length=64)
    publish_api: bool = True
    publish_orchestration: bool = True


@router.post("/servitize/publish")
def servitize_publish(
    payload: PublishTargetsRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """④ 一键发布（默认 API+闭环+编排三目标全发）。

    api+loop：activate_servitize（既有）；orchestration：从服务化草稿绑定的
    闭环任务读全部参数（部署/配方/特征脚本/阈值/白名单/集成），实例化
    「闭环服务模板」→参数替换→发布工作流 v1→发布编排 API（幂等复用）。"""
    from app.models.api_model import PlatformAPI
    from app.models.demo_loop import DemoLoopConfig
    from app.services.agent.orchestration_publish import (
        publish_orchestration_from_recipe,
    )
    from app.services.agent.servitize import activate_servitize

    api = db.get(PlatformAPI, uuid_module.UUID(payload.model_api_id))
    if api is None:
        raise HTTPException(404, detail={"code": "MODEL_API_NOT_FOUND"})
    result: dict = {"model_api_id": str(api.id)}

    if payload.publish_api:
        try:
            activated = activate_servitize(
                db, model_api_id=payload.model_api_id, actor_id=current_user.id)
            result["api_status"] = activated.status
        except ValueError as error:
            raise HTTPException(409, detail={"code": "SERVITIZE_STATE_INVALID",
                                             "message": str(error)})

    if payload.publish_orchestration:
        loop_id = (api.showcase_state or {}).get("loop_config_id")
        loop = db.get(DemoLoopConfig, uuid_module.UUID(str(loop_id))) \
            if loop_id else None
        if loop is None:
            raise HTTPException(422, detail={
                "code": "ORCHESTRATION_LOOP_MISSING",
                "message": "服务化草稿未绑定闭环任务，无法推导编排参数"})
        if not loop.deployment_id:
            raise HTTPException(422, detail={
                "code": "ORCHESTRATION_DEPLOYMENT_MISSING",
                "message": "闭环任务未绑定部署"})
        from app.services.agent.recipe import get_current_version

        recipe_uuid = uuid_module.UUID(str(loop.retrain_agent_recipe_id)) \
            if getattr(loop, "retrain_agent_recipe_id", None) else None
        if recipe_uuid is None:
            raise HTTPException(422, detail={
                "code": "ORCHESTRATION_RECIPE_MISSING",
                "message": "闭环任务未绑定固化配方（agent 重训模式），无法生成编排"})
        version = get_current_version(db, recipe_uuid)
        content = dict(version.content_json or {})
        guidance = dict(content.get("guidance") or {})
        feature_guidance = dict(guidance.get("feature") or {})
        # 回流/累积数据集只能是闭环专属报错集。它原在首次回流时惰性创建，
        # 新闭环直接发布编排必缺（一键发布卡 422）——按回流行同构列（原始
        # 记录列+prediction/confidence/目标列）预建空集，首次回流直接追加。
        # 绝不回落重训数据集：编排 append_error_dataset 会把报错行写进
        # 原始训练集（服务化闭环的重训数据集就是用户原始训练集）。
        if not loop.error_artifact_id:
            smoke = content.get("smoke_row")
            if isinstance(smoke, dict) and smoke:
                from app.services.demo_loop import DemoLoopService

                columns = set(smoke) | {"prediction", "confidence"}
                if loop.retrain_target_column:
                    columns.add(loop.retrain_target_column)
                DemoLoopService(db).ensure_error_dataset(loop, sorted(columns))
        accum_id = str(loop.error_artifact_id) if loop.error_artifact_id else ""
        retrain_ids = list(getattr(loop, "retrain_dataset_artifact_ids", None) or [])
        if not retrain_ids and loop.retrain_dataset_artifact_id:
            retrain_ids = [loop.retrain_dataset_artifact_id]
        retrain_dataset_id = (str(retrain_ids[0]) if retrain_ids else accum_id)
        if not accum_id:
            # 配方缺冒烟行（无法推导回流列）且闭环从未回流：静默发布会让
            # 编排图节点带空 dataset_artifact_id，invoke 期必然失败——
            # 这里显式拒绝，给出可操作指引。
            raise HTTPException(422, detail={
                "code": "ORCHESTRATION_ERROR_DATASET_MISSING",
                "message": "闭环任务尚无报错数据集（error_artifact_id 为空），"
                           "无法发布编排：请先执行一次闭环预测触发报错回流，"
                           "或在闭环自动化中配置报错数据集后重试"})
        # 模型特征列：注入 apply_model.feature_columns（模型包无
        # feature_names_in_ 时运行期按名选列的唯一依据）。
        model_feature_names: list[str] = []
        if loop.deployment_id:
            from app.models.model_registry import InferenceDeployment, ModelVersion

            dep_row = db.get(InferenceDeployment, loop.deployment_id)
            if dep_row is not None and dep_row.model_version_id:
                mv_row = db.get(ModelVersion, dep_row.model_version_id)
                if mv_row is not None:
                    # feature_schema 兼容两种形态：[{name, dtype}] 列表
                    # 或 {feature_names: [...]} 字典。
                    schema = mv_row.feature_schema
                    if isinstance(schema, list):
                        model_feature_names = [
                            str(item.get("name")) for item in schema
                            if isinstance(item, dict) and item.get("name")
                        ]
                    elif isinstance(schema, dict):
                        model_feature_names = [
                            str(n) for n in (schema.get("feature_names") or [])]
        try:
            orch_api, workflow = publish_orchestration_from_recipe(
                db,
                project_id=payload.project_id,
                actor_id=current_user.id,
                recipe_id=recipe_uuid,
                deployment_id=loop.deployment_id,
                feature_script=str(content.get("feature_script") or ""),
                target_column=loop.retrain_target_column or "",
                error_classes=list(loop.error_classes or []),
                threshold_rows=int(loop.retrain_threshold_rows or 12),
                retrain_dataset_id=retrain_dataset_id,
                accum_dataset_id=accum_id,
                error_dataset_id=accum_id,
                ensemble_enabled=bool(getattr(loop, "retrain_ensemble_enabled", False)),
                algorithm_ids=[
                    str(item) for item in
                    (content.get("retrain_algorithm_ids")
                     or getattr(loop, "retrain_algorithm_ids", None) or [])
                ],
                input_columns=list(
                    getattr(loop, "retrain_input_columns", None) or []),
                model_feature_names=model_feature_names,
            )
            result["orchestration"] = {
                "api_id": str(orch_api.id),
                "status": orch_api.status,
                "workflow_id": str(workflow.id),
                "endpoint": orch_api.endpoint,
            }
        except ValueError as error:
            raise HTTPException(422, detail={
                "code": "ORCHESTRATION_PUBLISH_FAILED",
                "message": str(error)})
    return result
