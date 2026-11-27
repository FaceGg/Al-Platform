"""Release governance (补齐路线第二批 S2b, B2-09/02/03/G2/G3).

Challenger 别名（部署目标角色扩展，C18）/ 影子对照（只对照不接管，E14
随机抽样防选择偏差、报告不可变）/ 发布门禁五项（挂 hard_gates 体系；终验
只取 S2a 锁定盲测；不回退 E01；Wilson 下界 E02；无监督口径）/ 预授权
（G2 授权人≠申请人）/ 服务端回执与按量放量、业务回退（G3/E12）。
"""
from __future__ import annotations

import hashlib
import json
import math
import uuid
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from app.models.dataset_splitting import (
    BlindTestUsage,
    DatasetSplitMember,
    ModelingRound,
)
from app.models.release_governance import (
    CHECK_VERDICTS,
    PREAUTH_STATUSES,
    RECEIPT_STATUSES,
    ReleaseCheck,
    ReleasePreauthorization,
    RolloutReceipt,
    ShadowComparison,
)

# 发布门禁默认阈值（B2-03；可按场景/预授权验收标准加严）
DEFAULT_F1_FLOOR = 0.5
DEFAULT_BLIND_SAMPLE_FLOOR = 200
# Wilson 下界开关与容差（E02/E01）
DEFAULT_WILSON_ENABLED = False
DEFAULT_NO_REGRESSION_TOLERANCE = 0.0
# 影子窗口默认阈值：一致率低于该值不放量（G3 影子观察窗）
DEFAULT_SHADOW_AGREEMENT_FLOOR = 0.9
# 业务回退（E12）：灰度期影子/生产预警率相对基线倍数上限
DEFAULT_BUSINESS_ALERT_RATIO_CAP = 3.0


class GovernanceError(Exception):
    def __init__(self, code: str, message: str | None = None):
        super().__init__(message or code)
        self.code = code
        self.message = message or code


def wilson_lower_bound(successes: int, total: int, z: float = 1.96) -> float:
    """Wilson score 下界（E02）：小样本高点估计不放行。"""
    if total <= 0:
        return 0.0
    phat = successes / total
    denom = 1 + z * z / total
    center = phat + z * z / (2 * total)
    margin = z * math.sqrt((phat * (1 - phat) + z * z / (4 * total)) / total)
    return (center - margin) / denom


def _fingerprint(obj) -> str:
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    ).hexdigest()


def _utcnow() -> datetime:
    return datetime.utcnow()


def _active_challenger(db: Session, deployment_id) -> "object | None":
    from app.models.model_registry import DeploymentTarget

    return (
        db.query(DeploymentTarget)
        .filter(
            DeploymentTarget.revision.has(deployment_id=deployment_id),
            DeploymentTarget.role == "challenger",
        )
        .first()
    )


def register_challenger(db: Session, *, deployment, version, actor_id) -> object:
    """B2-09：注册影子候选（challenger revision + 目标，权重恒 0 不进生产路由）。
    版本须 approved 且 ≠ 当前 stable 版本；同部署活跃 challenger 唯一。"""
    from sqlalchemy import func as _func

    from app.models.model_registry import DeploymentRevision, DeploymentTarget

    if getattr(version, "approval_status", None) != "approved":
        raise GovernanceError("CHALLENGER_VERSION_NOT_APPROVED")
    stable = (
        db.query(DeploymentTarget)
        .filter(
            DeploymentTarget.revision.has(deployment_id=deployment.id),
            DeploymentTarget.role == "stable",
        )
        .first()
    )
    if stable is not None and stable.model_version_id == version.id:
        challenge_self_error = GovernanceError("CHALLENGER_SAME_AS_STABLE")
        raise challenge_self_error
    if _active_challenger(db, deployment.id) is not None:
        raise GovernanceError("CHALLENGER_ALREADY_ACTIVE")
    revision_number = int(
        db.query(_func.max(DeploymentRevision.revision_number))
        .filter(DeploymentRevision.deployment_id == deployment.id)
        .scalar() or 0
    ) + 1
    revision = DeploymentRevision(
        deployment_id=deployment.id, revision_number=revision_number,
        strategy="immediate", status="draft",
        created_by_id=actor_id,
    )
    db.add(revision)
    db.flush()
    target = DeploymentTarget(
        revision_id=revision.id,
        model_version_id=version.id,
        weight_bps=0,
        role="challenger",
        condition_value=None,
    )
    db.add(target)
    db.flush()
    _audit(db, project_id=deployment.project_id, actor_id=actor_id,
           action="challenger.register", resource_type="deployment_target",
           resource_id=str(target.id),
           changes={"version_id": str(version.id),
                    "revision_id": str(revision.id),
                    "stable_version_id": str(stable.model_version_id) if stable else None})
    return target


def retire_challenger(db: Session, *, deployment_id, actor_id,
                      note: str | None = None) -> dict:
    """退役影子候选（E11 退役计划=时间+替任：替任走 model_release 审批链）。"""
    from app.models.model_registry import DeploymentTarget

    target = _active_challenger(db, deployment_id)
    if target is None:
        raise GovernanceError("CHALLENGER_NOT_FOUND")
    db.delete(target)
    db.flush()
    _audit(db, project_id=_project_of_deployment(db, deployment_id),
           actor_id=actor_id, action="challenger.retire",
           resource_type="deployment_target", resource_id=str(target.id),
           changes={"note": note or ""})
    return {"retired": True, "target_id": str(target.id)}


def _project_of_deployment(db: Session, deployment_id):
    from app.models.model_registry import InferenceDeployment

    deployment = db.get(InferenceDeployment, deployment_id)
    return deployment.project_id if deployment else None


def _audit(db: Session, *, project_id, actor_id, action: str,
           resource_type: str, resource_id: str | None, changes: dict) -> None:
    """治理动作审计（project_action 之外的服务级简化入口；同事务成链）。"""
    from app.models.access import AuditEvent
    from app.services.audit_chain import append as append_chain

    event = AuditEvent(
        project_id=project_id,
        actor_id=actor_id,
        actor_username="system",
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        result="success",
        request_id=uuid.uuid4(),
        changes=changes,
    )
    append_chain(db, "audit_events", event)
    db.add(event)


def _load_candidate_bundle(db: Session, version_id, project_id=None):
    """候选模型包加载（密封验签同 serving_deployment 路径）。"""
    from app.models.model_library import ModelLibrary
    from app.models.model_registry import ModelVersion

    version = db.get(ModelVersion, version_id)
    if version is None:
        raise GovernanceError("CHALLENGER_VERSION_NOT_FOUND")
    # 三批复审新发现：曾用 registered_model_id 查 ModelLibrary（键型错配）——
    # 影子/盲测打分在真实链路上恒 CHALLENGER_BUNDLE_MISSING（M2 演练打桩未暴露）
    library = db.get(ModelLibrary, version.source_model_library_id)
    if library is None or library.model_artifact_id is None:
        raise GovernanceError("CHALLENGER_BUNDLE_MISSING")
    from app.services.artifact_service import build_artifact_service

    artifact_service = build_artifact_service(db)
    # 归属按项目解析：训练产出的模型工件挂项目，owner_id 曾被误当 project 用
    #（影子/盲测打分在真实链路恒 Artifact not found——三批复审修复时发现）
    artifact = artifact_service.resolve(
        library.model_artifact_id,
        project_id if project_id is not None else library.owner_id,
        expected_type="model",
    )
    import io

    import joblib

    from app.services.model_artifact_sealing import seal_is_valid

    with artifact_service.storage.open(artifact.storage_uri) as handle:
        payload = handle.read()
    artifact_metadata = getattr(artifact, "metadata_", None) or {}
    if not seal_is_valid(
        artifact_metadata,
        str(artifact_metadata.get("served_sha256") or artifact_metadata.get("sha256") or ""),
    ):
        raise GovernanceError("CHALLENGER_BUNDLE_SEAL_INVALID")
    try:
        return joblib.load(io.BytesIO(payload))
    except Exception as error:  # noqa: BLE001
        raise GovernanceError("CHALLENGER_BUNDLE_LOAD_FAILED") from error


def _predict_with_bundle(bundle, frame: pd.DataFrame, feature_columns: list[str]):
    matrix = frame[feature_columns].to_numpy()
    if hasattr(bundle, "predict_proba"):
        probabilities = bundle.predict_proba(matrix)
        labels = bundle.classes_[np.argmax(probabilities, axis=1)]
        confidence = np.max(probabilities, axis=1)
        return labels, confidence
    labels = bundle.predict(matrix)
    return labels, None


def run_shadow_batch(
    db: Session,
    *,
    deployment,
    challenger_version,
    frame: pd.DataFrame,
    feature_columns: list[str],
    sample_source: str = "random_sample",
    sample_size: int | None = None,
    actor_id=None,
) -> int:
    """B2-02 影子打分：候选对同一批样本打分，channel='shadow' 逐行落明细
    （extra 带 champion 对照值）；不写预警表。随机抽样记种子（E14）。"""
    import joblib

    from app.models.inference_result import InferenceResult

    if sample_source not in SHADOW_SAMPLE_SOURCES:
        raise GovernanceError("SHADOW_SOURCE_INVALID")
    total = len(frame)
    if total == 0:
        raise GovernanceError("SHADOW_EMPTY_FRAME")
    seed = int(_utcnow().timestamp()) % 100000
    if sample_source == "random_sample":
        take = min(total, int(sample_size or min(total, 500)))
        rng = np.random.RandomState(seed)
        sampled = frame.iloc[sorted(rng.choice(total, size=take, replace=False))]
    else:
        sampled = frame
    bundle = _load_candidate_bundle(db, challenger_version.id,
                                    project_id=deployment.project_id)
    labels, confidence = _predict_with_bundle(bundle, sampled, feature_columns)
    champion_bundle = None
    champion_labels = None
    champion_confidence = None
    if sample_source == "random_sample":
        try:
            champion_bundle = _load_candidate_bundle(
                db, _stable_version_id(db, deployment)
            )
            champion_labels, champion_confidence = _predict_with_bundle(
                champion_bundle, sampled, feature_columns
            )
        except GovernanceError:
            champion_labels = [None] * len(sampled)
    rows = []
    for offset, (row_index, row) in enumerate(sampled.iterrows()):
        rows.append(InferenceResult(
            request_id=f"shadow-{uuid.uuid4().hex[:16]}",
            project_id=deployment.project_id,
            deployment_id=deployment.id,
            model_version_id=challenger_version.id,
            channel="shadow",
            sample_key=str(row.get("sample_key") or f"row-{row_index}"),
            predicted_label=(str(labels[offset]) if labels is not None else None),
            anomaly_score=(float(confidence[offset]) if confidence is not None else None),
            extra={
                "champion_label": (
                    str(champion_labels[offset]) if champion_labels is not None else None
                ),
                "champion_confidence": (
                    float(champion_confidence[offset])
                    if champion_confidence is not None else None
                ),
                "challenger_confidence": (
                    float(confidence[offset]) if confidence is not None else None
                ),
                "sample_source": sample_source,
                "sampling_seed": seed if sample_source == "random_sample" else None,
                "missing_reason": (
                    "champion_bundle_unavailable" if champion_labels is None else None
                ),
            },
        ))
    for start in range(0, len(rows), 1000):
        db.bulk_save_objects(rows[start:start + 1000])
    db.flush()
    return len(rows)


def _stable_version_id(db: Session, deployment):
    from app.models.model_registry import DeploymentTarget

    stable = (
        db.query(DeploymentTarget)
        .filter(
            DeploymentTarget.revision.has(deployment_id=deployment.id),
            DeploymentTarget.role == "stable",
        )
        .first()
    )
    return stable.model_version_id if stable else None


def build_shadow_report(
    db: Session,
    *,
    deployment,
    challenger_version_id,
    actor_id=None,
) -> ShadowComparison:
    """聚合一致率与分组指标 → 不可变报告行（内容变化=新行）。"""
    from app.models.inference_result import InferenceResult

    shadow_rows = (
        db.query(InferenceResult)
        .filter(
            InferenceResult.deployment_id == deployment.id,
            InferenceResult.model_version_id == challenger_version_id,
            InferenceResult.channel == "shadow",
        )
        .all()
    )
    comparable = 0
    agreed = 0
    grouped: dict[str, dict[str, int]] = {}
    for row in shadow_rows:
        extra = row.extra or {}
        champion_label = extra.get("champion_label")
        if champion_label is None:
            continue
        challenger_label = row.predicted_label
        comparable += 1
        match = str(champion_label) == str(challenger_label)
        if match:
            agreed += 1
        group = grouped.setdefault(str(champion_label), {"count": 0, "agreed": 0})
        group["count"] += 1
        group["agreed"] += int(match)
    report = ShadowComparison(
        project_id=deployment.project_id,
        deployment_id=deployment.id,
        champion_version_id=_stable_version_id(db, deployment),
        challenger_version_id=challenger_version_id,
        sample_source=(shadow_rows[0].extra or {}).get("sample_source") if shadow_rows else None,
        sample_count=len(shadow_rows),
        agreement_rate=(agreed / comparable) if comparable else None,
        detail={
            "comparable": comparable,
            "agreed": agreed,
            "grouped": grouped,
            "unmatched": len(shadow_rows) - comparable,
            "missing_reasons": sorted({
                str((row.extra or {}).get("missing_reason"))
                for row in shadow_rows
                if (row.extra or {}).get("missing_reason")
            }),
        },
        report_fingerprint=_fingerprint({
            "deployment": str(deployment.id),
            "challenger": str(challenger_version_id),
            "sample_count": len(shadow_rows),
            "agreed": agreed,
        }),
        created_by_id=actor_id,
    )
    db.add(report)
    db.flush()
    return report


def _version_metrics(db: Session, version_id) -> dict:
    from app.models.model_registry import ModelVersion

    version = db.get(ModelVersion, version_id)
    return dict(getattr(version, "metrics", None) or {})


def _primary_metric_key(version, metrics: dict) -> str:
    task_kind = str(
        (getattr(version, "conversion_metadata", None) or {}).get("task")
        or metrics.get("task")
        or "classification"
    )
    return "synthetic_auc" if task_kind in {"anomaly", "anomaly_detection"} else "f1"


def _drift_severity_open(db: Session, deployment) -> dict | None:
    """近期（7 天内）severe 级漂移报告且未进提案流程 = 未消解（B2-03 拦截项）。"""
    from datetime import timedelta

    from app.models.drift import DriftReport

    report = (
        db.query(DriftReport)
        .filter(
            DriftReport.deployment_id == deployment.id,
            DriftReport.level == "severe",
            DriftReport.proposal_at.is_(None),
            DriftReport.created_at >= _utcnow() - timedelta(days=7),
        )
        .first()
    )
    return {"report_id": str(report.id), "level": report.level} if report else None


def _blind_round_for_version(db: Session, deployment):
    """该部署所属项目最近一个锁定的建模轮次（S2a 接线）。"""
    return (
        db.query(ModelingRound)
        .filter(
            ModelingRound.project_id == deployment.project_id,
            ModelingRound.status == "locked",
        )
        .order_by(ModelingRound.created_at.desc())
        .first()
    )


def evaluate_release_gates(
    db: Session,
    *,
    deployment,
    version,
    approval,
    options: dict | None = None,
) -> list[ReleaseCheck]:
    """B2-03 五项门禁（+ Wilson 开关）→ release_checks 行（随发布单归档）。

    硬检查（无盲测/泄漏）不可豁免；可豁免的只有不回退一项（E01，豁免走
    exemption 审批类型）。无监督口径（规划）：不因无 F1 误拦、也不无门槛放行
    ——读 version.metrics 同源冠军资格键。"""
    options = dict(options or {})
    checks: list[ReleaseCheck] = []
    metrics = _version_metrics(db, version.id)
    task_kind = str((version.conversion_metadata or {}).get("task") or
                    metrics.get("task") or "classification")

    def _add(check_key, threshold, observed, verdict, detail=None):
        check = ReleaseCheck(
            approval_id=approval.id, check_key=check_key,
            threshold=threshold, observed=observed,
            verdict=verdict, detail=detail,
        )
        db.add(check)
        checks.append(check)

    # 1) 指标下限（无监督按冠军资格口径；有监督 F1/召回下限）
    floor = float(options.get("f1_floor") or DEFAULT_F1_FLOOR)
    is_anomaly = task_kind in {"anomaly", "anomaly_detection"}
    primary_key = "synthetic_auc" if is_anomaly else "f1"
    primary_value = metrics.get(primary_key)
    if primary_value is None:
        _add("metric_floor", {"key": primary_key, "floor": floor}, None,
             "failed", {"reason": "metric_missing"})
    else:
        passed = float(primary_value) >= floor
        _add("metric_floor", {"key": primary_key, "floor": floor},
             {primary_key: float(primary_value)},
             "passed" if passed else "failed")

    # 2) 漂移严重级未消解 → 拦截
    severe = _drift_severity_open(db, deployment)
    _add("drift_severity", {"level": "severe", "unresolved_only": True},
         severe, "passed" if severe is None else "failed",
         None if severe is None else {"report_id": severe["report_id"]})

    # 3) 盲测样本量下限 + 4) 盲测终验（只能取自 S2a 锁定盲测）
    blind_count = _blind_sample_count(db, deployment)
    sample_floor = int(options.get("blind_sample_floor") or DEFAULT_BLIND_SAMPLE_FLOOR)
    _add("blind_sample_floor", {"floor": sample_floor}, {"blind_count": blind_count},
         "passed" if blind_count >= sample_floor else "failed")
    blind_metrics = _blind_final_metrics(db, deployment, version, options)
    if blind_metrics is None:
        _add("blind_final_validation", {"required": True}, None,
             "failed", {"reason": "no_blind_metrics"})
    else:
        blind_floor = floor
        blind_value = blind_metrics.get(primary_key)
        if blind_value is None:
            _add("blind_final_validation", {"key": primary_key, "floor": blind_floor},
                 None, "failed", {"reason": "blind_metric_missing"})
        else:
            _add("blind_final_validation", {"key": primary_key, "floor": blind_floor},
                 {primary_key: float(blind_value)},
                 "passed" if float(blind_value) >= blind_floor else "failed")

    # 5) 不回退（E01）：候选与现役冠军同批盲测配对盲评
    no_regression = evaluate_no_regression(db, deployment=deployment, version=version)
    _add("no_regression", {
        "tolerance": float(options.get("tolerance") or DEFAULT_NO_REGRESSION_TOLERANCE),
        "strict_new_miss": True,
    }, no_regression, "not_applicable" if no_regression is None else (
        "passed" if no_regression.get("passed") else "failed"
    ), no_regression)

    # 6) Wilson 下界（E02，可配开关；比例型指标，无监督不启用）
    if options.get("wilson_enabled") and not is_anomaly:
        pair = _recall_pair(db, deployment, version)
        if pair is None:
            _add("wilson_lower_bound", {"enabled": True}, None,
                 "not_applicable", {"reason": "no_confusion_pair"})
        else:
            lower = wilson_lower_bound(pair["successes"], pair["total"])
            target = float(options.get("wilson_target") or floor)
            _add("wilson_lower_bound", {"target": target},
                 {"point": pair["rate"], "lower_bound": lower,
                  "successes": pair["successes"], "total": pair["total"]},
                 "passed" if lower >= target else "failed",
                 {"note": "Wilson 下界口径：测试集 30 检出 29 → 下界 83.3%"})
    return checks


def _recall_pair(db: Session, deployment, version) -> dict | None:
    """比例型指标的成功/总数对（Wilson 用）：读 version.metrics 的混淆要素。"""
    metrics = _version_metrics(db, version.id)
    for count_key, total_key in (
        ("recall_minority_true_positive", "recall_minority_total"),
        ("true_positive", "total_positive"),
    ):
        if metrics.get(count_key) is not None and metrics.get(total_key):
            return {
                "successes": int(metrics[count_key]),
                "total": int(metrics[total_key]),
                "rate": float(metrics[count_key]) / int(metrics[total_key]),
            }
    return None


def evaluate_no_regression(db: Session, *, deployment, version) -> dict | None:
    """E01 不回退：候选与现役冠军在**同一批盲测样本**上的指标配对比较。

    三批复审重构：原实现比较两版本各自的 version.metrics（浅验证集口径，
    等于没有配对）。现在对同一 blind 段用两版本分别真实打分（score_blind_
    split），同批由「同一 frame」构造性保证；盲测样本集指纹进 detail。
    记账一次（purpose=no_regression_check，受 E03 上限约束）。无监督任务
    保持 version.metrics 口径（detail 标注）。基线缺失 → not_applicable。
    """
    from app.models.model_registry import ModelVersion

    champion_version_id = _stable_version_id(db, deployment)
    if champion_version_id is None:
        return None
    round_row = _blind_round_for_version(db, deployment)
    if round_row is None:
        return None
    candidate_version = version
    champion_version = db.get(ModelVersion, champion_version_id)
    candidate_key = _primary_metric_key(candidate_version, _version_metrics(db, candidate_version.id))
    champion_key = _primary_metric_key(champion_version, _version_metrics(db, champion_version_id))
    if candidate_key != champion_key:
        return {
            "passed": False, "reason": "metric_kind_mismatch",
            "candidate_key": candidate_key, "champion_key": champion_key,
        }
    task_kind = str((getattr(candidate_version, "conversion_metadata", None) or {}).get("task")
                    or (_version_metrics(db, candidate_version.id).get("task") or "classification"))
    from app.services.modeling_rounds import RoundError, record_blind_evaluation

    # 无监督：保持冠军资格口径的配对（version.metrics），detail 如实标注
    if task_kind in {"anomaly", "anomaly_detection"}:
        candidate_value = _version_metrics(db, candidate_version.id).get(candidate_key)
        champion_value = _version_metrics(db, champion_version_id).get(champion_key)
        if candidate_value is None or champion_value is None:
            return {"passed": False, "reason": "metric_missing"}
        tolerance = DEFAULT_NO_REGRESSION_TOLERANCE
        return {
            "passed": float(candidate_value) >= float(champion_value) - tolerance,
            "candidate": {candidate_key: float(candidate_value)},
            "champion": {champion_key: float(champion_value)},
            "scored_from": "version_metrics",
            "note": "无监督冠军资格口径配对，盲测逐样本打分待口径评审",
        }
    # 有监督：同一 blind 段两版本分别打分（同批构造性成立）
    try:
        candidate_scored = score_blind_split(db, deployment=deployment,
                                             version=candidate_version, round_row=round_row)
        champion_scored = score_blind_split(db, deployment=deployment,
                                            version=champion_version, round_row=round_row)
    except GovernanceError as error:
        return {"passed": False, "reason": error.code}
    try:
        record_blind_evaluation(
            db, round_id=round_row.id, purpose="no_regression_check",
            used_by_id=None, sample_count=candidate_scored["sample_count"],
            samples_fingerprint=candidate_scored["samples_fingerprint"],
        )
    except RoundError:
        return {"passed": False, "reason": "blind_eval_cap_reached"}
    tolerance = DEFAULT_NO_REGRESSION_TOLERANCE
    return {
        "passed": candidate_scored["f1"] >= champion_scored["f1"] - tolerance,
        "candidate": {candidate_key: candidate_scored["f1"]},
        "champion": {champion_key: champion_scored["f1"]},
        "same_blind_samples": True,
        "sample_count": candidate_scored["sample_count"],
        "samples_fingerprint": candidate_scored["samples_fingerprint"],
        "tolerance": tolerance,
    }


def grant_preauthorization(
    db: Session, *, project_id, deployment_id, gates_fingerprint: str,
    expires_at, max_releases: int, granted_by_id, note: str | None = None,
) -> ReleasePreauthorization:
    """G2 发布预授权（授权人=持有 approval.approve 者；申请人≠授权人在使用时强制）。"""
    auth = ReleasePreauthorization(
        project_id=project_id,
        deployment_id=deployment_id,
        acceptance_gates_fingerprint=gates_fingerprint,
        expires_at=expires_at,
        max_releases=int(max_releases),
        status="active",
        granted_by_id=granted_by_id,
        note=(note or "")[:256] or None,
    )
    db.add(auth)
    db.flush()
    _audit(db, project_id=project_id, actor_id=granted_by_id,
           action="release_preauthorization.grant",
           resource_type="release_preauthorization", resource_id=str(auth.id),
           changes={"expires_at": expires_at.isoformat(), "max_releases": int(max_releases)})
    return auth


def check_preauthorization(
    db: Session, *, auth_id, deployment_id, gates_fingerprint: str, applicant_id,
) -> ReleasePreauthorization:
    """G2 使用检查：active + 未过期 + 未超次 + 指纹一致 + 申请人≠授权人。
    四种失效情形（过期/超次/撤销/质量门变更）与同人使用均不再命中。"""
    auth = db.get(ReleasePreauthorization, auth_id)
    if auth is None:
        raise GovernanceError("PREAUTH_NOT_FOUND")
    now = _utcnow()
    if auth.status != "active":
        raise GovernanceError("PREAUTH_REVOKED")
    if auth.expires_at <= now:
        raise GovernanceError("PREAUTH_EXPIRED")
    if auth.releases_used >= auth.max_releases:
        raise GovernanceError("PREAUTH_EXHAUSTED")
    if auth.acceptance_gates_fingerprint != gates_fingerprint:
        raise GovernanceError("PREAUTH_GATES_CHANGED")
    if str(applicant_id) == str(auth.granted_by_id):
        raise GovernanceError("PREAUTH_SELF_GRANTED_DENIED")
    if auth.deployment_id is not None and str(auth.deployment_id) != str(deployment_id):
        raise GovernanceError("PREAUTH_DEPLOYMENT_MISMATCH")
    auth.releases_used += 1
    _audit(db, project_id=auth.project_id, actor_id=applicant_id,
           action="release_preauthorization.use",
           resource_type="release_preauthorization", resource_id=str(auth.id),
           changes={"releases_used": auth.releases_used})
    return auth


def revoke_preauthorization(db: Session, *, auth_id, actor_id) -> dict:
    auth = db.get(ReleasePreauthorization, auth_id)
    if auth is None:
        raise GovernanceError("PREAUTH_NOT_FOUND")
    auth.status = "revoked"
    _audit(db, project_id=auth.project_id, actor_id=actor_id,
           action="release_preauthorization.revoke",
           resource_type="release_preauthorization", resource_id=str(auth.id),
           changes={})
    return {"revoked": True}


def record_rollout_receipt(
    db: Session, *, project_id, rollout_id, revision_id=None, effective_alias: str,
    scored_count: int, artifact_digest: str | None, window_start=None,
    window_end=None, expected_digest: str | None = None, routing_key=None,
    reported_by_id=None,
) -> RolloutReceipt:
    """G3 服务端回执（契约四要素：版本、产物摘要、打分量、时间窗）。
    产物摘要与候选包不符 → digest_mismatch（E12「不符的回执被拒绝」）。"""
    status = "valid"
    if expected_digest and artifact_digest and artifact_digest != expected_digest:
        status = "digest_mismatch"
    receipt = RolloutReceipt(
        project_id=project_id, rollout_id=rollout_id, revision_id=revision_id,
        routing_key=routing_key, effective_alias=effective_alias,
        scored_count=int(scored_count), artifact_digest=artifact_digest,
        window_start=window_start, window_end=window_end,
        status=status, reported_by_id=reported_by_id,
    )
    db.add(receipt)
    db.flush()
    _audit(db, project_id=project_id, actor_id=reported_by_id,
           action="rollout.receipt", resource_type="rollout_receipt",
           resource_id=str(receipt.id),
           changes={"status": status, "scored_count": int(scored_count)})
    return receipt


def valid_receipt_volume(db: Session, rollout_id) -> int:
    """该 rollout 的有效回执打分量合计（按量放量判据）。"""
    rows = (
        db.query(RolloutReceipt)
        .filter(
            RolloutReceipt.rollout_id == rollout_id,
            RolloutReceipt.status == "valid",
        )
        .all()
    )
    return int(sum(row.scored_count for row in rows))


def shadow_window_gate(db: Session, *, deployment, floor: float | None = None) -> dict:
    """G3 影子观察窗前置校验：近期影子报告一致率 ≥ floor 才放行灰度；
    不足 → 未放行（超时接管走 quality.manage 强制放行 + 审计——「交回自动复验」
    = 重新校验）。"""
    from datetime import timedelta

    floor = float(floor or DEFAULT_SHADOW_AGREEMENT_FLOOR)
    since = _utcnow() - timedelta(days=7)
    reports = (
        db.query(ShadowComparison)
        .filter(
            ShadowComparison.deployment_id == deployment.id,
            ShadowComparison.created_at >= since,
        )
        .order_by(ShadowComparison.created_at.desc())
        .all()
    )
    if not reports:
        return {"passed": False, "reason": "no_shadow_report"}
    latest = reports[0]
    rate = latest.agreement_rate
    if rate is None:
        return {"passed": False, "reason": "shadow_report_not_comparable"}
    return {"passed": rate >= floor, "agreement_rate": float(rate), "floor": floor}


def business_alert_ratio(db: Session, *, deployment, window_hours: int = 24) -> dict | None:
    """E12 业务口径回退的观测：灰度期影子/生产预警率 vs 上一窗口基线倍数。"""
    from app.models.inference_result import InferenceResult

    now = _utcnow()
    start = now - timedelta(hours=window_hours)

    def _ratio(window_start, window_end):
        total = (
            db.query(InferenceResult)
            .filter(
                InferenceResult.deployment_id == deployment.id,
                InferenceResult.occurred_at >= window_start,
                InferenceResult.occurred_at < window_end,
            )
            .count()
        )
        if total == 0:
            return None
        alerted = (
            db.query(InferenceResult)
            .filter(
                InferenceResult.deployment_id == deployment.id,
                InferenceResult.occurred_at >= window_start,
                InferenceResult.occurred_at < window_end,
                InferenceResult.alert_triggered.is_(True),
            )
            .count()
        )
        return alerted / total

    current = _ratio(start, now)
    if current is None:
        return None
    previous = _ratio(start - timedelta(hours=window_hours), start)
    if previous in (None, 0):
        return {"current": current, "previous": previous, "ratio": None}
    return {"current": current, "previous": previous, "ratio": current / previous}


def _blind_sample_count(db: Session, deployment) -> int:
    round_row = _blind_round_for_version(db, deployment)
    if round_row is None:
        return 0
    members = (
        db.query(DatasetSplitMember)
        .filter(
            DatasetSplitMember.split_id == round_row.split_id,
            DatasetSplitMember.role == "blind",
        )
        .count()
    )
    return int(members)


def materialize_version_frame(db: Session, project_id, dataset_version_id) -> pd.DataFrame:
    """物化数据集版本 frame（B2-02 影子 / B2-03 盲测终验共用取数路径）。"""
    import pandas as pd

    from app.models.data_version import DatasetVersion
    from app.services.artifact_service import build_artifact_service

    version = db.get(DatasetVersion, dataset_version_id)
    artifact_id = (
        version.normalized_artifact_id or version.original_artifact_id if version else None
    )
    if artifact_id is None:
        raise GovernanceError("DATASET_VERSION_NO_ARTIFACT")
    artifact_service = build_artifact_service(db)
    with artifact_service.materialize(
        artifact_id, project_id, expected_type="dataset",
    ) as dataset_path:
        return pd.read_csv(dataset_path)


def deployment_feature_columns(db: Session, deployment) -> list:
    """部署的推理特征列（来自 stable 版本的 feature_schema）。"""
    from app.models.model_registry import ModelVersion

    stable_version_id = deployment.model_version_id
    version = db.get(ModelVersion, stable_version_id) if stable_version_id else None
    columns = list(getattr(version, "feature_schema", None) or []) if version else []
    return [str(column) for column in columns if column]


def score_blind_split(db: Session, *, deployment, version, round_row) -> dict:
    """对锁定盲测段用指定版本模型打分（三批复审重构：终验与不回退共用）。

    原 `_blind_final_metrics` 直接取 `version.metrics`（与浅验证集同源，等于
    没有盲测终验）；`evaluate_no_regression` 比较的也是各版本自己的指标而非
    同批配对——两条都是本阶段对标竞品的核心卖点，复审判 failed。本函数是
    修复的基座：物化轮次数据集版本 → 取 blind 段 → 密封验签加载模型包 →
    真实打分 → 与 target 真值比对。

    返回 {"f1", "sample_count", "samples_fingerprint"}；无监督任务由调用方
    保持 version.metrics 口径（detail 标注），不进入本函数。
    """
    from sklearn.metrics import f1_score

    from app.models.dataset_splitting import DatasetSplit
    from app.services.dataset_splitting import filter_frame_by_roles, load_role_indices

    split = db.get(DatasetSplit, round_row.split_id)
    target_column = (split.params or {}).get("target_column") if split else None
    if not target_column:
        raise GovernanceError("BLIND_TARGET_COLUMN_MISSING")
    frame = materialize_version_frame(db, deployment.project_id, round_row.dataset_version_id)
    roles = load_role_indices(db, round_row.split_id)
    blind_frame = filter_frame_by_roles(frame, roles, "blind")
    if blind_frame.empty:
        raise GovernanceError("BLIND_EMPTY_FRAME")
    feature_columns = deployment_feature_columns(db, deployment)
    missing = [column for column in feature_columns if column not in blind_frame.columns]
    if missing:
        raise GovernanceError("BLIND_FEATURE_COLUMNS_MISSING")
    if target_column not in blind_frame.columns:
        raise GovernanceError("BLIND_TARGET_COLUMN_MISSING")
    bundle = _load_candidate_bundle(db, version.id, project_id=deployment.project_id)
    labels, _confidence = _predict_with_bundle(bundle, blind_frame, feature_columns)
    truth = [str(value) for value in blind_frame[target_column].tolist()]
    predicted = [str(value) for value in labels]
    sample_keys = [
        str(value) for value in (
            blind_frame["sample_key"].tolist() if "sample_key" in blind_frame.columns
            else blind_frame.index.tolist()
        )
    ]
    fingerprint = _fingerprint({"blind_sample_keys": sample_keys})
    return {
        "f1": float(f1_score(truth, predicted, average="macro")),
        "sample_count": len(blind_frame),
        "samples_fingerprint": fingerprint,
    }


def _blind_final_metrics(db: Session, deployment, version, options) -> dict | None:
    """终验指标：有监督任务对锁定盲测段真实打分（经记账受 E03 上限约束）；
    无监督保持 version.metrics 冠军资格口径（detail 标注 scored_from）。"""
    round_row = _blind_round_for_version(db, deployment)
    if round_row is None:
        return None
    metrics = _version_metrics(db, version.id)
    primary_key = _primary_metric_key(version, metrics)
    task_kind = str((getattr(version, "conversion_metadata", None) or {}).get("task")
                    or metrics.get("task") or "classification")
    is_anomaly = task_kind in {"anomaly", "anomaly_detection"}
    blind_count = _blind_sample_count(db, deployment)
    if is_anomaly:
        value = metrics.get(primary_key)
        if value is None:
            return None
        from app.services.modeling_rounds import RoundError, record_blind_evaluation

        try:
            record_blind_evaluation(
                db, round_id=round_row.id, purpose="release_final_validation",
                used_by_id=None, sample_count=blind_count,
                samples_fingerprint=_fingerprint({"version": str(version.id),
                                                  "key": primary_key,
                                                  "value": float(value)}),
            )
        except RoundError:
            return None
        return {primary_key: float(value),
                "scored_from": "version_metrics",
                "note": "无监督冠军资格口径（合成基准），盲测逐样本打分待无监督口径评审"}
    from app.services.modeling_rounds import RoundError, record_blind_evaluation

    try:
        scored = score_blind_split(db, deployment=deployment, version=version,
                                   round_row=round_row)
    except GovernanceError as error:
        _audit(db, project_id=deployment.project_id, actor_id=None,
               action="blind_final_validation.failed",
               resource_type="modeling_round", resource_id=str(round_row.id),
               changes={"reason": error.code})
        return None
    try:
        record_blind_evaluation(
            db, round_id=round_row.id, purpose="release_final_validation",
            used_by_id=None, sample_count=scored["sample_count"],
            samples_fingerprint=scored["samples_fingerprint"],
        )
    except RoundError:
        return None
    return {primary_key: scored["f1"],
            "scored_from": "blind_split",
            "sample_count": scored["sample_count"],
            "samples_fingerprint": scored["samples_fingerprint"]}