"""Bounded RSI service (spec v0.9 §10.3): 经验库 → SKILL.md 修订提案 →
离线回归 → 分级审批 → 版本化生效，全部有界：

- **触发去抖**：同一技能同一时刻至多一个未决提案（单实例队列）；
- **单向收紧**：门禁变更只允许提高阈值，放宽类提案在提交时即拒绝；
- **回归集有界**：候选配方 >10 时按"域代表 + 最新优先"抽样，且回归只跑
  S1/S2/S4（S3/AutoML 永不重跑）；
- **分级审批**：low（提示词/示例）回归通过即自动生效；medium/high（默认
  动作/门禁收紧）必须人工批准；
- **版本化回滚**：生效发新版本号，任一版本可回滚（回滚同样发新版本号）；
- 改进对象只有技能文档与策略——平台工具、硬门禁执行器、沙箱不可被修改，
  正在运行的任务不受影响（演进只在任务间离线发生）。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.recipe import PipelineRecipe, PipelineRecipeVersion
from app.models.skill_revision import SkillRevision

ACTIVE_STATUSES = ("proposed", "regression_running", "pending_approval")
REGRESSION_SAMPLE_LIMIT = 10
REGRESSION_STAGES = ("s1", "s2", "s4")  # S3/AutoML never re-runs
TOUCH_RISK = {
    "prompts": "low",
    "examples": "low",
    "defaults": "medium",
    "workflow": "medium",
    "gates": "high",
}


class RevisionDebounced(RuntimeError):
    """Another proposal for this skill is still unresolved."""


class RevisionNotPermitted(ValueError):
    """The proposal relaxes gates/contract — tightening-only violation."""


class RevisionStateError(ValueError):
    """Status transition not allowed from the current state."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def classify_risk(touched: list[str]) -> str:
    levels = [TOUCH_RISK.get(item, "medium") for item in (touched or [])]
    if "high" in levels:
        return "high"
    if "medium" in levels:
        return "medium"
    return "low"


def propose_revision(
    db: Session,
    *,
    skill_name: str,
    base_version: int,
    current_gates: dict,
    proposal: dict,
    basis_entries: list[str] | None = None,
) -> SkillRevision:
    """Stage a revision proposal. Enforces debounce and tightening-only."""
    active = (
        db.query(SkillRevision)
        .filter(
            SkillRevision.skill_name == skill_name,
            SkillRevision.status.in_(ACTIVE_STATUSES),
        )
        .first()
    )
    if active is not None:
        raise RevisionDebounced(
            "skill %s already has an unresolved proposal: %s"
            % (skill_name, active.id)
        )

    touched = list(proposal.get("touched") or [])
    gate_changes = dict(proposal.get("gate_changes") or {})
    if gate_changes and "gates" not in touched:
        touched.append("gates")
    # 单向收紧：任何门禁变更只能提高阈值。
    for key, new_value in gate_changes.items():
        old_value = (current_gates or {}).get(key)
        if old_value is None or float(new_value) < float(old_value):
            raise RevisionNotPermitted(
                "gate %s may only tighten (%s -> %s not allowed)"
                % (key, old_value, new_value)
            )

    revision = SkillRevision(
        skill_name=skill_name,
        base_version=base_version,
        status="proposed",
        risk_level=classify_risk(touched),
        proposal_json={
            "diff": proposal.get("diff") or "",
            "rationale": proposal.get("rationale") or "",
            "touched": touched,
            "gate_changes": gate_changes,
        },
        basis_entries=basis_entries or [],
    )
    db.add(revision)
    db.commit()
    return revision


def select_representative_recipes(
    versions: list[PipelineRecipeVersion], limit: int = REGRESSION_SAMPLE_LIMIT
) -> list[PipelineRecipeVersion]:
    """域代表 + 最新优先：每个域保留其最新配方，再按新旧补足到上限。"""
    by_domain: dict[str, list[PipelineRecipeVersion]] = {}
    for version in sorted(versions, key=lambda item: item.created_at or _now(), reverse=True):
        domain = (version.content_json or {}).get("domain") or "unknown"
        by_domain.setdefault(domain, []).append(version)
    representatives = [entries[0] for entries in by_domain.values()]
    if len(representatives) >= limit:
        return representatives[:limit]
    chosen_ids = {version.id for version in representatives}
    for version in sorted(versions, key=lambda item: item.created_at or _now(), reverse=True):
        if len(representatives) >= limit:
            break
        if version.id not in chosen_ids:
            representatives.append(version)
            chosen_ids.add(version.id)
    return representatives


def run_regression(
    db: Session,
    *,
    revision_id: uuid.UUID,
    regression_fn,
    limit: int = REGRESSION_SAMPLE_LIMIT,
    actor_id=None,
) -> SkillRevision:
    """Offline regression over a representative recipe sample.

    ``regression_fn(recipe_content, stages)`` must return
    ``{"metrics": {...}}`` computed by re-running ONLY the stages given
    (S1/S2/S4 — never S3/AutoML). A recipe degrades when any metric that its
    own baseline records falls below the recorded value.
    """
    revision = db.get(SkillRevision, revision_id)
    if revision is None or revision.status not in ("proposed",):
        raise RevisionStateError("revision is not awaiting regression")
    revision.status = "regression_running"
    db.commit()

    candidates = (
        db.query(PipelineRecipeVersion)
        .join(PipelineRecipe, PipelineRecipe.id == PipelineRecipeVersion.recipe_id)
        .filter(PipelineRecipeVersion.status == "current")
        .all()
    )
    sample = select_representative_recipes(candidates, limit=limit)

    results: list[dict] = []
    degraded = False
    for version in sample:
        content = version.content_json or {}
        baseline = dict(content.get("baseline_metrics") or {})
        outcome = regression_fn(content, list(REGRESSION_STAGES)) or {}
        after = dict(outcome.get("metrics") or {})
        drops = {
            key: {"baseline": baseline[key], "after": after[key]}
            for key in baseline
            if key in after and float(after[key]) < float(baseline[key]) - 1e-9
        }
        recipe_degraded = bool(drops)
        degraded = degraded or recipe_degraded
        results.append(
            {
                "recipe_id": str(version.recipe_id),
                "version": version.version,
                "domain": content.get("domain") or "unknown",
                "degraded": recipe_degraded,
                "drops": drops,
            }
        )

    revision.regression_json = {"stages": list(REGRESSION_STAGES), "results": results}
    revision.regression_passed = not degraded
    if degraded:
        revision.status = "regression_failed"
        _annotate_basis_rejected(db, revision)
    elif revision.risk_level == "low":
        _activate(db, revision, approved_by=None, auto=True)
    else:
        revision.status = "pending_approval"
    db.commit()
    db.refresh(revision)
    return revision


def _annotate_basis_rejected(db: Session, revision: SkillRevision) -> None:
    """驳回即回写经验：该教训不可泛化（§10.3 步骤 2）。"""
    from app.models.experience_entry import ExperienceEntry

    for entry_id in revision.basis_entries or []:
        try:
            entry_uuid = uuid.UUID(str(entry_id))
        except (TypeError, ValueError, AttributeError):
            continue
        entry = db.get(ExperienceEntry, entry_uuid)
        if entry is not None:
            note = "RSI 回归驳回：%s 不可泛化（%s）" % (
                entry.lesson[:40],
                str(revision.id)[:8],
            )
            entry.human_note = (
                ("%s\n%s" % (entry.human_note, note)) if entry.human_note else note
            )


def _next_version(db: Session, skill_name: str) -> int:
    max_activated = (
        db.query(SkillRevision.new_version)
        .filter(
            SkillRevision.skill_name == skill_name,
            SkillRevision.new_version.isnot(None),
        )
        .order_by(SkillRevision.new_version.desc())
        .first()
    )
    base = max_activated[0] if max_activated and max_activated[0] else 0
    return int(base) + 1


def _activate(db: Session, revision: SkillRevision, *, approved_by, auto: bool) -> None:
    revision.status = "auto_activated" if auto else "activated"
    revision.new_version = _next_version(db, revision.skill_name)
    revision.approved_by = approved_by


def decide_revision(
    db: Session,
    *,
    revision_id: uuid.UUID,
    approve: bool,
    actor_id,
) -> SkillRevision:
    """分级审批：low 已自动生效；medium/high 必须人工批准/驳回。"""
    revision = db.get(SkillRevision, revision_id)
    if revision is None:
        raise LookupError("revision not found")
    if revision.status != "pending_approval":
        raise RevisionStateError(
            "only pending_approval revisions accept human decisions"
        )
    if approve:
        _activate(db, revision, approved_by=_as_uuid(actor_id), auto=False)
    else:
        revision.status = "rejected"
        revision.approved_by = _as_uuid(actor_id)
        _annotate_basis_rejected(db, revision)
    db.commit()
    db.refresh(revision)
    return revision


def rollback_skill(
    db: Session, *, skill_name: str, to_version: int, actor_id=None
) -> SkillRevision:
    """一键回滚：把该版本的生效修订标记 rolled_back，版本计数继续前进。"""
    revision = (
        db.query(SkillRevision)
        .filter(
            SkillRevision.skill_name == skill_name,
            SkillRevision.new_version == to_version,
            SkillRevision.status.in_(("activated", "auto_activated")),
        )
        .order_by(SkillRevision.created_at.desc())
        .first()
    )
    if revision is None:
        raise LookupError("no active revision at version %s" % to_version)
    revision.status = "rolled_back"
    revision.approved_by = _as_uuid(actor_id)
    db.commit()
    db.refresh(revision)
    return revision


def _as_uuid(value):
    if value is None:
        return None
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        return None
