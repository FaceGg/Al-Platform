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


def servitize_lock(project_id) -> threading.Lock:
    key = str(project_id)
    with _PROJECT_LOCKS_GUARD:
        lock = _PROJECT_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _PROJECT_LOCKS[key] = lock
        return lock


def derive_error_classes(target_semantics: dict | None) -> tuple[list[str], list[str]]:
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
        # No semantic match: fall back to the lexicographically smallest label
        # but flag everything as ambiguous so the wizard preview shows it.
        error_classes.append(sorted(str(label) for label in semantics)[0])
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
) -> ServitizeDraft:
    """Create the three S5 assets in draft state (§12.1 ①–④).

    ① deployment must already exist (model registered/approved/started via
    the standard chain); ② closed-loop config (passive — nothing feeds it
    until the model API is listed); ③ model API entry ``offline``;
    ④ dry-run smoke — zero backflow by construction. ⑤ activation is a
    separate explicit call (:func:`activate_servitize`).
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
                recipe_content.get("target_semantics")
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
            "feature_engineering_mode": "script",
            "feature_script": recipe_content.get("feature_script") or "",
            "retrain_target_column": recipe_content.get("inputs", {}).get(
                "target_column", ""
            ),
            "retrain_enabled": bool(recipe_content.get("retrain_enabled", True)),
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
            api.request_schema = {
                "feature_script": recipe_content.get("feature_script") or "",
            }
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
                request_schema={
                    "feature_script": recipe_content.get("feature_script") or "",
                },
                showcase_state={"loop_config_id": str(loop.id)},
            )
            db.add(api)
        else:
            api.showcase_state = {"loop_config_id": str(loop.id)}
        db.commit()
        db.refresh(api)

        smoke_row = recipe_content.get("smoke_row") or {}
        smoke = loop_service.predict(loop, dict(smoke_row), actor_id, dry_run=True)

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
