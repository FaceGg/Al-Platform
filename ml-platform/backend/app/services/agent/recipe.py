"""Recipe versioning service (spec v0.9 §四/§13.1): append-only versions with
a single current pointer, git-style rollback (a rollback issues a NEW version
with the old content), and the delta check for new-data reuse.
"""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.models.recipe import PipelineRecipe, PipelineRecipeVersion


class RecipeNotFound(LookupError):
    pass


class RecipeVersionNotFound(LookupError):
    pass


def create_recipe(
    db: Session,
    *,
    project_id: uuid.UUID | None,
    name: str,
    content: dict,
    change_note: str | None = None,
    domain: str | None = None,
    target_column: str | None = None,
    llm_profile_id: uuid.UUID | None = None,
    created_by: uuid.UUID | None = None,
) -> PipelineRecipe:
    recipe = PipelineRecipe(
        project_id=project_id,
        name=name,
        domain=domain or content.get("domain"),
        target_column=target_column
        or (content.get("inputs") or {}).get("target_column"),
        current_version=1,
        created_by=created_by,
    )
    db.add(recipe)
    db.flush()
    version = PipelineRecipeVersion(
        recipe_id=recipe.id,
        version=1,
        status="current",
        content_json=content,
        change_note=change_note,
        llm_profile_id=llm_profile_id,
        created_by=created_by,
    )
    db.add(version)
    db.commit()
    return recipe


def _get_recipe(db: Session, recipe_id: uuid.UUID) -> PipelineRecipe:
    recipe = db.get(PipelineRecipe, recipe_id)
    if recipe is None:
        raise RecipeNotFound(str(recipe_id))
    return recipe


def _issue_version(
    db: Session,
    recipe: PipelineRecipe,
    *,
    version_number: int,
    content: dict,
    change_note: str | None,
    llm_profile_id: uuid.UUID | None,
    created_by: uuid.UUID | None,
) -> PipelineRecipeVersion:
    db.query(PipelineRecipeVersion).filter(
        PipelineRecipeVersion.recipe_id == recipe.id,
        PipelineRecipeVersion.status == "current",
    ).update({PipelineRecipeVersion.status: "superseded"}, synchronize_session=False)
    version = PipelineRecipeVersion(
        recipe_id=recipe.id,
        version=version_number,
        status="current",
        content_json=content,
        change_note=change_note,
        llm_profile_id=llm_profile_id,
        created_by=created_by,
    )
    db.add(version)
    recipe.current_version = version_number
    return version


def update_recipe(
    db: Session,
    recipe_id: uuid.UUID,
    *,
    content: dict,
    change_note: str | None = None,
    llm_profile_id: uuid.UUID | None = None,
    created_by: uuid.UUID | None = None,
) -> PipelineRecipeVersion:
    recipe = _get_recipe(db, recipe_id)
    version = _issue_version(
        db,
        recipe,
        version_number=recipe.current_version + 1,
        content=content,
        change_note=change_note,
        llm_profile_id=llm_profile_id,
        created_by=created_by,
    )
    db.commit()
    return version


def rollback_recipe(
    db: Session,
    recipe_id: uuid.UUID,
    *,
    to_version: int,
    change_note: str | None = None,
    created_by: uuid.UUID | None = None,
) -> PipelineRecipeVersion:
    """Git-style: the rollback issues a NEW current version with old content."""
    recipe = _get_recipe(db, recipe_id)
    source = (
        db.query(PipelineRecipeVersion)
        .filter(
            PipelineRecipeVersion.recipe_id == recipe.id,
            PipelineRecipeVersion.version == to_version,
        )
        .first()
    )
    if source is None:
        raise RecipeVersionNotFound(f"version {to_version} not found")
    version = _issue_version(
        db,
        recipe,
        version_number=recipe.current_version + 1,
        content=source.content_json,
        change_note=change_note or f"rollback to v{to_version}",
        llm_profile_id=source.llm_profile_id,
        created_by=created_by,
    )
    db.commit()
    return version


def get_current_version(db: Session, recipe_id: uuid.UUID) -> PipelineRecipeVersion:
    version = (
        db.query(PipelineRecipeVersion)
        .filter(
            PipelineRecipeVersion.recipe_id == recipe_id,
            PipelineRecipeVersion.status == "current",
        )
        .first()
    )
    if version is None:
        raise RecipeVersionNotFound(f"no current version for {recipe_id}")
    return version


def list_versions(db: Session, recipe_id: uuid.UUID) -> list[PipelineRecipeVersion]:
    return (
        db.query(PipelineRecipeVersion)
        .filter(PipelineRecipeVersion.recipe_id == recipe_id)
        .order_by(PipelineRecipeVersion.version.desc())
        .all()
    )


def delta_check(
    db: Session, recipe_id: uuid.UUID, new_profile: dict
) -> dict:
    """Decide reuse-vs-full-iteration for new data against the recipe digest.

    Small delta (spec §四): column set overlap ≥0.9, row count within [0.5, 2]
    of the recorded row count, and no dtype drift on shared columns.
    """
    current = get_current_version(db, recipe_id)
    digest_columns = {
        column["name"]: column.get("dtype")
        for column in (current.content_json.get("analysis_profile") or {}).get(
            "columns", []
        )
    } or _columns_from_digest(current.content_json)
    new_columns = {
        column["name"]: column.get("dtype")
        for column in new_profile.get("columns", [])
    }

    reasons: list[str] = []
    if digest_columns:
        shared = set(digest_columns) & set(new_columns)
        union = set(digest_columns) | set(new_columns)
        overlap = len(shared) / len(union) if union else 0.0
        if overlap < 0.9:
            reasons.append(f"column_overlap_low: {overlap:.2f} < 0.90")
        drifted = sorted(
            name
            for name in shared
            if digest_columns[name] and new_columns[name]
            and digest_columns[name] != new_columns[name]
        )
        if drifted:
            reasons.append(f"dtype_drift: {drifted[:5]}")
    else:
        reasons.append("analysis_digest_columns_missing")

    recorded_rows = (current.content_json.get("analysis_profile") or {}).get("row_count")
    new_rows = new_profile.get("row_count")
    if recorded_rows and new_rows:
        ratio = new_rows / max(recorded_rows, 1)
        if not 0.5 <= ratio <= 2.0:
            reasons.append(f"row_count_ratio_out_of_band: {ratio:.2f}")

    return {"small": not reasons, "reasons": reasons}


def _json_safe(value):
    """冒烟行值清洗：NaN→None、numpy 标量→Python 标量、时间戳→ISO 串。"""
    import math

    import numpy as _np

    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if _np is not None and isinstance(value, _np.generic):
        return value.item()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def smoke_row_from_frame(frame, max_columns: int = 200) -> dict:
    """数据帧首行 → S5 冒烟行（JSON-safe，列数截断防超大 payload）。

    全 None 列剔除；上限 200 对齐宽表列上限（memory：宽表 200 列上限）——
    截断过窄会让部署模型特征列缺失、闭环 predict 走点焊特征桥而挂
    （E2E 实证：87 列数据 32 列截断后缺 wres/cve* 触发桥校验失败）。"""
    if frame is None:
        return {}
    try:
        if len(frame) == 0:
            return {}
    except TypeError:
        return {}
    row = frame.iloc[0]
    out: dict = {}
    for column in list(frame.columns)[:max_columns]:
        value = _json_safe(row[column])
        if value is not None:
            out[str(column)] = value
    return out


def _columns_from_digest(content: dict) -> dict:
    """Fallback: minimal columns digest embedded directly in the recipe."""
    digest = content.get("analysis_digest_columns")
    if isinstance(digest, dict):
        return digest
    return {}


def build_fixation_content(run, memory: dict, smoke_row: dict | None = None,
                           target_values: list | None = None) -> dict:
    """验收通过的 run → 配方版本 content（固化/重放共用的唯一构造器）。

    从 API 层（agent_extras.fixate_recipe）下沉：闭环 agent 重训模式需要
    从配方版本重放 guidance 快照，构造器必须与服务侧共用，避免双处漂移。
    guidance 全量快照 + source_run_id 是 agent 重训的输入合同；缺失时触发
    端 fail-closed（DEMO_LOOP_AGENT_RECIPE_INVALID），不静默降级引擎模式。
    smoke_row：S5 服务化 dry-run 冒烟行（此前有消费方无生产方，档案页
    servitize 对任何固化配方都挂 RECORD_INVALID——本处补上生产方）。
    target_values：目标列取值集合 → target_semantics（{label: ""}）。此前
    全系统无 target_semantics 生产者，auto_servitize 的三资产起草必然
    「cannot derive error classes」降级——取值走 derive_error_classes 的
    字典序兜底 + ambiguous 预览（发布批准时人工核对修正，把关不变）。
    """
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
    modeling = dict((run.guidance_json or {}).get("modeling") or {})
    ensemble = dict(modeling.get("ensemble") or {})
    task_type = str((run.guidance_json or {}).get("task_type") or "supervised")
    is_anomaly = task_type == "anomaly"
    # 默认门禁随范式切换（技术方案 §3.4，与 runner.DEFAULT_GATES_ANOMALY 同源；
    # guidance.evaluation.metric_gates 显式给值时替换默认——merge 语义在
    # 重放消费方 hard_gates/wizard.merge_gates，此处只固化）
    if gates:
        acceptance_gates = gates
    elif is_anomaly:
        # 无监督默认门禁随污染率推导（技术方案 §3.3：normal_fpr ≤ contamination×1.5）
        # ——与 runner.DEFAULT_GATES_ANOMALY 同源，此前两处都硬编码 0.015
        # （= contamination 0.01 的特例），用户改污染率后配方固化的门禁与
        # 实际训练判据脱节（2026-11-14 第八轮审计 B15 收尾）。
        from app.services.agent.runner import anomaly_default_gates

        acceptance_gates = anomaly_default_gates(modeling.get("contamination"))
    else:
        acceptance_gates = {"recall_minority": 0.90}
    # 算法白名单随配方固化：服务化后闭环重训按白名单缩小引擎搜索族
    # （此前 guidance.modeling.algorithm_whitelist 无任何消费方，勾选形同虚设）
    content = {
        "domain": memory.get("last_domain") or "",
        "inputs": {"target_column": None if is_anomaly else run.target_column},
        "feature_script": final_script,
        "automl_config": modeling.get("param_hints", {}),
        "acceptance_gates": acceptance_gates,
        # 向导第三步的集成选项随配方固化 → 服务化后闭环重训沿用（集成走到线上的最后一环）
        "retrain_ensemble": (
            {"enabled": True, "top_k": int(ensemble.get("top_k") or 3)}
            if ensemble.get("enabled")
            else {"enabled": False}
        ),
        "retrain_algorithm_ids": [str(x) for x in modeling.get("algorithm_whitelist") or []],
        # agent 重训重放输入：完整 UserGuidance 快照 + 源 run（LLM 档案/预算沿用）
        "guidance": dict(run.guidance_json or {}),
        "source_run_id": str(run.id),
        # S5 服务化 dry-run 冒烟行（servitize_recipe 的 zero-backflow 冒烟输入）
        "smoke_row": dict(smoke_row or {}),
        # 目标列取值语义（servitize derive_error_classes 的推导输入；空描述
        # 走少数类兜底 + 全量 ambiguous，发布批准时人工核对）
        "target_semantics": {str(label): "" for label in (target_values or [])[:20]},
        # 少数类（target_values 按频次升序，首个即少数类）：缺陷类兜底依据——
        # 缺陷天然稀少，且与验收链路 recall_minority 口径一致。此前兜底取字典
        # 序最小标签：拧紧 0=不合格碰巧对，点焊 0=正常则把正常焊点全判报错回流
        "minority_label": str(target_values[0]) if target_values else None,
        "baseline_metrics": (run.result_json or {}).get("metrics", {}),
        "analysis_digest": "run %s" % str(run.id)[:8],
        "optimization_report": (run.result_json or {}).get("optimization_report"),
    }
    if is_anomaly:
        # 无监督配方段（技术方案 §3.7）：重放走同一合同；condition_column
        # 随 guidance 固化（M4 合同链；部署路由拓扑二期）。
        content["anomaly"] = {
            "task_type": "anomaly_detection",
            "method": (run.result_json or {}).get("s3_champion", {}).get("algorithm") or "",
            "contamination": modeling.get("contamination") or 0.01,
            "condition_column": modeling.get("condition_column") or None,
        }
        # 无监督无目标语义：置空防止 derive_error_classes 拿空标签误推导
        content["target_semantics"] = {}
        content["minority_label"] = None
    return content
