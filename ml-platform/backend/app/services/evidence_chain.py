"""Evidence chain overview & export (补齐路线第一批 F2b, B1-12 / E21).

按模型版本的「闭环证据总览」与证据链 ZIP 导出（技术方案 §9.9，D24/D25）：

- 12 环节（接入 → 切分 → 智能分群 → 人工标注 → 主动选样 → 训练 → 评估 →
  发布上线 → 推送生产 → 现场验证 → 问题反馈 → 迭代优化）逐环节给出状态与
  可下钻的依据记录。
- 状态口径（五态，宁可说清楚也不冒充完成）：
  complete        该环节的记录存在
  pending         该环节尚未发生（如尚未部署）
  missing         应当存在的记录找不到（如外部模型缺训练任务以外的情况）
  not_supported   平台当前版本还不产出这类证据（切分、主动选样、现场验证），
                  注记里写明随哪一批接入
  not_applicable  对该模型不适用（如外部导入模型没有平台训练记录）
- 上线检查五项：模型文件、校验和、数据版本、评估完整性、生产版本唯一。
  总览接口不重算文件哈希（只看校验和是否已登记）；「留档」动作会重新读取
  模型文件计算 SHA-256 与登记值比对，并把当时的 12 环节快照一并存档。
- 证据包：tempdir + zipfile（先例 services/automl_report.py），注册为平台工件
  （type=evidence_export），包内附 MANIFEST.SHA256（sha256sum -c 兼容）。
"""
from __future__ import annotations

import hashlib
import json
import logging
import shutil
import tempfile
import uuid
import zipfile
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterator

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.models.access import AuditEvent
from app.models.artifact import Artifact
from app.models.data_version import DatasetVersion
from app.models.demo_loop import DemoLoopConfig
from app.models.inference_result import InferenceResult
from app.models.labeling import AnnotationSampleCurrent, AnnotationStrategyArtifact
from app.models.model_library import ModelLibrary
from app.models.model_registry import (
    InferenceDeployment,
    ModelVersion,
    RegisteredModel,
)
from app.models.platform_models import GenericAnnotationTask
from app.models.quality_alerts import ModelEvidenceCheck, QualityAlert, QualityAlertEvent
from app.models.training import TrainingJob

logger = logging.getLogger(__name__)

# (key, 中文名, 英文名)
STAGES: tuple[tuple[str, str, str], ...] = (
    ("ingest", "接入", "Ingest"),
    ("split", "切分", "Split"),
    ("clustering", "智能分群", "Clustering"),
    ("annotation", "人工标注", "Annotation"),
    ("active_sampling", "主动选样", "Active sampling"),
    ("training", "训练", "Training"),
    ("evaluation", "评估", "Evaluation"),
    ("release", "发布上线", "Release"),
    ("production", "推送生产", "Production"),
    ("field_validation", "现场验证", "Field validation"),
    ("feedback", "问题反馈", "Feedback"),
    ("iteration", "迭代优化", "Iteration"),
)

CLUSTER_STRATEGIES = ("cluster", "cluster_rule")

# 证据包里模型文件的体积上限：超过则只放元数据与校验和，不放文件本体
MODEL_FILE_SIZE_CAP = 64 * 1024 * 1024


class EvidenceExportError(ValueError):
    """证据导出的入参或前置条件不满足。"""


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (set, frozenset)):
        return sorted(str(item) for item in value)
    if isinstance(value, bytes):
        return value.hex()
    return str(value)


def dumps(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=_json_default)


def _ref(label: str, ref_type: str, ref_id: Any) -> dict:
    return {"label": label, "ref_type": ref_type, "ref_id": str(ref_id) if ref_id is not None else None}


def _stage(key: str, status: str, note: str, evidence: list[dict] | None = None) -> dict:
    title, title_en = next(((item[1], item[2]) for item in STAGES if item[0] == key))
    return {
        "key": key, "title": title, "title_en": title_en,
        "status": status, "note": note, "evidence": evidence or [],
    }


def _has_numeric_metric(metrics: Any) -> bool:
    """评估是否留下了可比较的数字（布尔值不算）。"""
    if not isinstance(metrics, dict):
        return False
    for value in metrics.values():
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            return True
        if isinstance(value, dict) and _has_numeric_metric(value):
            return True
    return False


def collect_lineage(db: Session, version: ModelVersion) -> dict:
    """模型版本的来源链：模型库 → 训练任务 → 数据集版本；工件与部署。"""
    library = (
        db.get(ModelLibrary, version.source_model_library_id)
        if version.source_model_library_id else None
    )
    job = db.get(TrainingJob, library.training_job_id) if library and library.training_job_id else None
    dataset_artifact_id = (
        (job.dataset_artifact_id if job else None)
        or (library.dataset_artifact_id if library else None)
    )
    dataset_version = None
    if dataset_artifact_id:
        dataset_version = (
            db.query(DatasetVersion)
            .filter(or_(
                DatasetVersion.original_artifact_id == dataset_artifact_id,
                DatasetVersion.normalized_artifact_id == dataset_artifact_id,
            ))
            .order_by(DatasetVersion.version.desc())
            .first()
        )
    model_artifact = db.get(Artifact, version.source_artifact_id) if version.source_artifact_id else None
    deployments = (
        db.query(InferenceDeployment)
        .filter(InferenceDeployment.model_version_id == version.id)
        .order_by(InferenceDeployment.created_at.asc())
        .all()
    )
    return {
        "library": library, "job": job, "dataset_artifact_id": dataset_artifact_id,
        "dataset_version": dataset_version, "model_artifact": model_artifact,
        "deployments": deployments,
    }


def build_stages(db: Session, version: ModelVersion, lineage: dict) -> list[dict]:
    """12 环节的状态与依据（第一批接已有证据的环节，其余如实标注）。"""
    job = lineage["job"]
    dataset_version = lineage["dataset_version"]
    stages: list[dict] = []

    # ① 接入
    if dataset_version is not None:
        stages.append(_stage(
            "ingest", "complete",
            f"数据集版本 v{dataset_version.version}：{dataset_version.row_count} 行，"
            f"内容哈希 {str(dataset_version.content_hash)[:12]}…",
            [_ref(f"数据集版本 v{dataset_version.version}", "dataset_version", dataset_version.id)],
        ))
    elif lineage["dataset_artifact_id"]:
        stages.append(_stage(
            "ingest", "complete", "训练使用的数据集工件",
            [_ref("数据集工件", "artifact", lineage["dataset_artifact_id"])],
        ))
    else:
        stages.append(_stage("ingest", "missing", "找不到训练所用数据集的版本或工件记录"))

    # ② 切分：划分管理随第二批接入；现在的随机留出不留档
    stages.append(_stage(
        "split", "not_supported",
        "平台尚无数据集划分管理（随第二批接入）：当前训练按默认 20% 随机分层留出，划分未留档",
    ))

    # ③ 智能分群 ④ 人工标注：都按数据集版本找
    strategy_rows: list[AnnotationStrategyArtifact] = []
    tasks: list[GenericAnnotationTask] = []
    if dataset_version is not None:
        tasks = (
            db.query(GenericAnnotationTask)
            .filter(GenericAnnotationTask.dataset_version_id == dataset_version.id)
            .order_by(GenericAnnotationTask.created_at.asc())
            .all()
        )
        if tasks:
            strategy_rows = (
                db.query(AnnotationStrategyArtifact)
                .filter(
                    AnnotationStrategyArtifact.task_id.in_([task.id for task in tasks]),
                    AnnotationStrategyArtifact.strategy.in_(CLUSTER_STRATEGIES),
                )
                .all()
            )
    if dataset_version is None:
        stages.append(_stage("clustering", "missing", "没有可追溯的数据集版本，无法查找分群记录"))
    elif strategy_rows:
        stages.append(_stage(
            "clustering", "complete", f"该数据集上有 {len(strategy_rows)} 条聚类策略记录",
            [_ref(f"聚类策略 · {row.strategy}", "annotation_strategy_artifact", row.id)
             for row in strategy_rows[:5]],
        ))
    else:
        stages.append(_stage("clustering", "pending", "该数据集上未执行过智能分群（可选环节）"))

    if dataset_version is None:
        stages.append(_stage("annotation", "missing", "没有可追溯的数据集版本，无法查找标注记录"))
    elif tasks:
        labeled = (
            db.query(func.count(AnnotationSampleCurrent.id))
            .filter(AnnotationSampleCurrent.task_id.in_([task.id for task in tasks]))
            .scalar()
        )
        stages.append(_stage(
            "annotation", "complete",
            f"{len(tasks)} 个标注任务，当前标签 {int(labeled or 0)} 条",
            [_ref(task.name, "annotation_task", task.id) for task in tasks[:5]],
        ))
    else:
        stages.append(_stage("annotation", "pending", "该数据集上还没有标注任务"))

    # ⑤ 主动选样：主动学习随第二批接入
    stages.append(_stage(
        "active_sampling", "not_supported", "平台尚无主动学习选样（随第二批接入）",
    ))

    # ⑥ 训练
    if job is not None:
        stages.append(_stage(
            "training", "complete", f"训练任务状态 {job.status}",
            [_ref("训练任务", "training_job", job.id)],
        ))
    elif lineage["library"] is None and version.source_kind == "onnx_artifact":
        stages.append(_stage("training", "not_applicable", "外部导入模型：平台上没有训练记录"))
    else:
        stages.append(_stage("training", "missing", "找不到该版本的训练任务记录"))

    # ⑦ 评估
    metrics = version.metrics if _has_numeric_metric(version.metrics) else (job.metrics if job else None)
    if _has_numeric_metric(metrics):
        stages.append(_stage("evaluation", "complete", "模型版本上登记了评估指标"))
    else:
        stages.append(_stage("evaluation", "missing", "没有找到数值型评估指标"))

    # ⑧ 发布上线
    if version.approval_status == "approved":
        stages.append(_stage("release", "complete", "模型版本已审批通过"))
    elif version.approval_status == "rejected":
        stages.append(_stage("release", "missing", "模型版本审批被驳回"))
    else:
        stages.append(_stage("release", "pending", f"模型版本待审批（{version.approval_status or 'pending'}）"))

    # ⑨ 推送生产
    running = [item for item in lineage["deployments"] if item.desired_state == "running"]
    if running:
        stages.append(_stage(
            "production", "complete", f"{len(running)} 个部署处于运行态",
            [_ref(deployment.name, "inference_deployment", deployment.id) for deployment in running[:5]],
        ))
    else:
        stages.append(_stage("production", "pending", "该版本尚未部署到生产"))

    # ⑩ 现场验证：盒端回执随第四批接入
    stages.append(_stage(
        "field_validation", "not_supported", "盒端回执尚未接入（随第四批接入）",
    ))

    # ⑪ 问题反馈：触发过预警的推理结果
    flagged = db.query(func.count(InferenceResult.id)).filter(
        InferenceResult.model_version_id == version.id,
        InferenceResult.alert_triggered.is_(True),
    ).scalar()
    produced = db.query(func.count(InferenceResult.id)).filter(
        InferenceResult.model_version_id == version.id,
    ).scalar()
    if flagged:
        stages.append(_stage(
            "feedback", "complete",
            f"{int(flagged)} 条推理结果触发过预警（该版本共 {int(produced)} 条推理记录）",
        ))
    else:
        stages.append(_stage(
            "feedback", "pending",
            f"该版本共 {int(produced)} 条推理记录，尚无触发预警的反馈",
        ))

    # ⑫ 迭代优化：闭环重训/换模记录（该版本由闭环换上，或闭环重训任务产出了它）
    loop_conditions = [DemoLoopConfig.swapped_model_version_id == version.id]
    if job is not None:
        loop_conditions.append(DemoLoopConfig.retrain_job_id == job.id)
    loops = (
        db.query(DemoLoopConfig).filter(or_(*loop_conditions))
        .order_by(DemoLoopConfig.id.asc()).all()
    )
    if loops:
        stages.append(_stage(
            "iteration", "complete", f"{len(loops)} 个闭环演示/重训配置涉及该版本",
            [_ref(config.name, "demo_loop_config", config.id) for config in loops[:5]],
        ))
    else:
        stages.append(_stage("iteration", "pending", "尚无闭环重训或换模记录"))

    return stages


# ----------------------------------------------------------------------
# 上线检查五项
# ----------------------------------------------------------------------

def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str) and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def verify_model_checksum(db: Session, project_id, version: ModelVersion) -> dict | None:
    """重新读取模型文件计算 SHA-256。读不到文件返回 None（不猜测、不冒充）。"""
    from app.services.artifact_service import build_artifact_service

    if not version.source_artifact_id:
        return None
    try:
        with build_artifact_service(db).materialize(
            version.source_artifact_id, project_id,
        ) as path:
            digest = hashlib.sha256()
            with Path(path).open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            return {"computed": digest.hexdigest()}
    except Exception as error:  # noqa: BLE001 - 存储不可用只影响这一项检查
        logger.warning("model checksum recomputation unavailable: %s", error)
        return None


def build_launch_checks(
    db: Session, project_id, version: ModelVersion, lineage: dict,
    *, recompute_checksum: bool = False,
) -> list[dict]:
    """上线检查五项：模型文件、校验和、数据版本、评估完整性、生产版本唯一。

    recompute_checksum=False（总览）：校验和一项只看是否登记了有效的 SHA-256；
    True（留档）：重新读取模型文件计算并与登记值比对。
    """
    artifact = lineage["model_artifact"]
    checks: list[dict] = []

    file_ok = artifact is not None and artifact.archived_at is None
    checks.append({
        "key": "model_file", "status": "pass" if file_ok else "fail",
        "detail": (
            f"工件 {artifact.name}（{int(artifact.file_size or 0)} 字节）" if file_ok
            else "模型工件已归档" if artifact is not None else "找不到模型工件"
        ),
        "value": str(artifact.id) if artifact is not None else None,
    })

    metadata = dict(artifact.metadata_ or {}) if artifact is not None else {}
    recorded = metadata.get("sha256")
    seal_note = "；模型密封标签在位" if metadata.get("model_seal") else ""
    if not _is_sha256(recorded):
        checksum_status = "fail"
        checksum_detail = "模型工件未登记有效的 SHA-256"
    elif recompute_checksum:
        computed = verify_model_checksum(db, project_id, version)
        if computed is None:
            checksum_status, checksum_detail = "fail", "无法读取模型文件重新计算校验和"
        elif computed["computed"] == recorded:
            checksum_status, checksum_detail = "pass", "重新计算模型文件的 SHA-256 与登记值一致"
        else:
            checksum_status, checksum_detail = "fail", "重新计算的 SHA-256 与登记值不一致"
    else:
        checksum_status = "pass"
        checksum_detail = "工件登记了 SHA-256（总览不重算文件哈希，「留档」时会重算比对）"
    checks.append({
        "key": "checksum", "status": checksum_status,
        "detail": checksum_detail + seal_note,
        "value": recorded if _is_sha256(recorded) else None,
    })

    dataset_version = lineage["dataset_version"]
    version_ok = dataset_version is not None and dataset_version.status == "ready"
    checks.append({
        "key": "data_version", "status": "pass" if version_ok else "fail",
        "detail": (
            f"数据集版本 v{dataset_version.version}（就绪）" if version_ok
            else "找不到就绪的数据集版本"
        ),
        "value": str(dataset_version.id) if dataset_version is not None else None,
    })

    job = lineage["job"]
    evaluation_ok = _has_numeric_metric(version.metrics) or (
        job is not None and _has_numeric_metric(job.metrics)
    )
    checks.append({
        "key": "evaluation", "status": "pass" if evaluation_ok else "fail",
        "detail": "有数值型评估指标" if evaluation_ok else "没有数值型评估指标",
    })

    sibling_ids = [
        row.id for row in db.query(ModelVersion.id).filter(
            ModelVersion.registered_model_id == version.registered_model_id,
        ).all()
    ]
    active_versions = {
        row[0] for row in db.query(InferenceDeployment.model_version_id).filter(
            InferenceDeployment.model_version_id.in_(sibling_ids),
            InferenceDeployment.desired_state == "running",
        ).distinct().all()
    }
    if not active_versions:
        unique_status, unique_detail = "pass", "同一模型下没有版本在生产，无冲突"
    elif active_versions == {version.id}:
        unique_status, unique_detail = "pass", "该版本是同一模型下唯一的生产版本"
    else:
        unique_status = "fail"
        unique_detail = f"同一模型下有 {len(active_versions)} 个版本同时在生产"
    checks.append({
        "key": "production_unique", "status": unique_status, "detail": unique_detail,
        "value": sorted(str(item) for item in active_versions),
    })
    return checks


# ----------------------------------------------------------------------
# 总览与留档
# ----------------------------------------------------------------------

def model_version_summary(db: Session, version: ModelVersion, lineage: dict) -> dict:
    registered = db.get(RegisteredModel, version.registered_model_id)
    dataset_version = lineage["dataset_version"]
    job = lineage["job"]
    return {
        "id": str(version.id),
        "version_number": version.version_number,
        "model_name": registered.name if registered is not None else None,
        "source_kind": version.source_kind,
        "algorithm": version.algorithm,
        "framework": version.framework,
        "approval_status": version.approval_status,
        "lifecycle_state": version.lifecycle_state,
        "training_job_id": str(job.id) if job is not None else None,
        "dataset_version_id": str(dataset_version.id) if dataset_version is not None else None,
    }


STAGE_STATUSES = ("complete", "pending", "missing", "not_supported", "not_applicable")


def build_evidence_overview(
    db: Session, project_id, version: ModelVersion, *, recompute_checksum: bool = False,
) -> dict:
    """一屏看清一个模型版本的 12 环节状态与上线检查结果。"""
    lineage = collect_lineage(db, version)
    stages = build_stages(db, version, lineage)
    checks = build_launch_checks(
        db, project_id, version, lineage, recompute_checksum=recompute_checksum,
    )
    return {
        "model_version": model_version_summary(db, version, lineage),
        "stages": stages,
        "checks": checks,
        "summary": {
            status: sum(1 for stage in stages if stage["status"] == status)
            for status in STAGE_STATUSES
        },
        "checks_passed": sum(1 for check in checks if check["status"] == "pass"),
        "checksum_verified": recompute_checksum,
        "generated_at": datetime.utcnow().isoformat(),
    }


def archive_launch_check(
    db: Session, project_id, version: ModelVersion, actor_id=None,
) -> tuple[ModelEvidenceCheck, dict]:
    """留档一次上线检查：重算模型校验和，并把当时的 12 环节快照一并存档。"""
    overview = build_evidence_overview(db, project_id, version, recompute_checksum=True)
    record = ModelEvidenceCheck(
        model_version_id=version.id,
        checks=overview["checks"],
        summary={"stages": overview["stages"], "generated_at": overview["generated_at"]},
        created_by_id=actor_id,
        created_at=datetime.utcnow(),
    )
    db.add(record)
    db.flush()
    return record, overview


def latest_archived_check(db: Session, version_id) -> ModelEvidenceCheck | None:
    return (
        db.query(ModelEvidenceCheck)
        .filter(ModelEvidenceCheck.model_version_id == version_id)
        .order_by(ModelEvidenceCheck.created_at.desc())
        .first()
    )


# ----------------------------------------------------------------------
# 证据链 ZIP 导出
# ----------------------------------------------------------------------

def _row(record) -> dict:
    """ORM 行 → 可序列化字典：按表列取值，不靠手写字段清单（漏字段即丢证据）。"""
    return {column.key: getattr(record, column.key) for column in record.__table__.columns}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _uuid(value, code: str):
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        raise EvidenceExportError(code) from None


class _Bundle:
    """证据包的文件集合：每个文件记相对路径，清单按相对路径逐个计算哈希。"""

    def __init__(self, root: Path):
        self.root = root
        self.entries: list[tuple[str, Path]] = []

    def json(self, relpath: str, payload: Any) -> None:
        path = self.root / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(dumps(payload), encoding="utf-8")
        self.entries.append((relpath, path))

    def file(self, relpath: str, source: Path) -> None:
        path = self.root / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, path)
        self.entries.append((relpath, path))


def find_project_model_version(
    db: Session, project_id, version_id, *, code: str = "MODEL_VERSION_NOT_FOUND",
) -> ModelVersion | None:
    """按项目取模型版本（模型版本的归属在已注册模型上）。"""
    return (
        db.query(ModelVersion)
        .join(RegisteredModel, RegisteredModel.id == ModelVersion.registered_model_id)
        .filter(
            ModelVersion.id == _uuid(version_id, code),
            RegisteredModel.project_id == project_id,
        )
        .first()
    )


def _write_model_files(
    db: Session, project_id, version: ModelVersion, bundle: _Bundle, service,
    *, include_model_file: bool,
) -> list[str]:
    """模型版本相关的证据文件；返回审计检索用的资源 id。"""
    lineage = collect_lineage(db, version)
    overview = build_evidence_overview(db, project_id, version)
    bundle.json("model/model_version.json", {
        "version": _row(version), "lineage": overview["model_version"],
    })
    bundle.json("model/stages.json", overview["stages"])
    bundle.json("model/launch_checks.json", overview["checks"])
    archived = latest_archived_check(db, version.id)
    if archived is not None:
        bundle.json("model/archived_check.json", {
            "checks": archived.checks, "summary": archived.summary,
            "created_at": archived.created_at,
        })
    resource_ids = [str(version.id)]

    job = lineage["job"]
    if job is not None:
        bundle.json("training/training_job.json", {"job": _row(job)})
        resource_ids.append(str(job.id))

    dataset_version = lineage["dataset_version"]
    if dataset_version is not None:
        tasks = (
            db.query(GenericAnnotationTask)
            .filter(GenericAnnotationTask.dataset_version_id == dataset_version.id)
            .all()
        )
        bundle.json("data/dataset_version.json", {
            "dataset_version": _row(dataset_version),
            "annotation_tasks": [_row(task) for task in tasks],
        })
        resource_ids.append(str(dataset_version.id))

    deployments = lineage["deployments"]
    bundle.json("production/deployments.json", {"deployments": [_row(item) for item in deployments]})
    resource_ids.extend(str(item.id) for item in deployments)

    # 与该版本相关的预警：经推理明细的 alert_id 回链（预警表的证据是 JSON，不做 JSON 查询）
    alert_ids = [
        row[0] for row in db.query(InferenceResult.alert_id).filter(
            InferenceResult.model_version_id == version.id,
            InferenceResult.alert_id.isnot(None),
        ).distinct().limit(500).all()
    ]
    alerts = (
        db.query(QualityAlert).filter(QualityAlert.id.in_(alert_ids)).all()
        if alert_ids else []
    )
    bundle.json("production/alerts.json", {
        "count": len(alerts), "items": [_row(alert) for alert in alerts],
    })
    resource_ids.extend(str(alert.id) for alert in alerts)

    artifact = lineage["model_artifact"]
    if artifact is not None:
        bundle.json("model/model_artifact.json", {"artifact": _row(artifact)})
        size = int(artifact.file_size or 0)
        if include_model_file and size <= MODEL_FILE_SIZE_CAP:
            with service.materialize(artifact.id, project_id) as path:
                bundle.file(f"model_file/{Path(artifact.name).name}", Path(path))
        elif include_model_file:
            bundle.json("model/model_file_omitted.json", {
                "reason": "文件超过证据包体积上限，只随包附元数据与校验和",
                "size": size, "cap": MODEL_FILE_SIZE_CAP,
            })
    return resource_ids


def _collect_alert(
    db: Session, project_id, alert_id, bundle: _Bundle, service,
) -> list[str]:
    """按预警打包：预警与轨迹、判据链、触发它的推理明细，及其模型版本的证据。"""
    from app.services.quality_alerts import evaluate_criteria_chain

    alert = (
        db.query(QualityAlert)
        .filter(
            QualityAlert.id == _uuid(alert_id, "ALERT_NOT_FOUND"),
            QualityAlert.project_id == project_id,
        )
        .first()
    )
    if alert is None:
        raise EvidenceExportError("ALERT_NOT_FOUND")
    events = (
        db.query(QualityAlertEvent)
        .filter(QualityAlertEvent.alert_id == alert.id)
        .order_by(QualityAlertEvent.created_at.asc())
        .all()
    )
    bundle.json("alert/alert.json", {"alert": _row(alert), "events": [_row(event) for event in events]})
    bundle.json("alert/criteria.json", {
        "criteria": evaluate_criteria_chain(db, alert),
        "recomputed_at": datetime.utcnow().isoformat(),
        "note": "判据链按导出时的现行规格与冻结基线复算；处置单里的当时快照见 alert/alert.json 的 events",
    })
    results = (
        db.query(InferenceResult)
        .filter(InferenceResult.alert_id == alert.id)
        .order_by(InferenceResult.occurred_at.asc())
        .limit(2000)
        .all()
    )
    bundle.json("alert/inference_results.json", {
        "count": len(results), "truncated": len(results) >= 2000,
        "items": [_row(result) for result in results],
    })
    resource_ids = [str(alert.id)]
    raw_version_id = (alert.evidence or {}).get("model_version_id")
    if raw_version_id:
        version = find_project_model_version(db, project_id, raw_version_id, code="IGNORED")
        if version is not None:
            resource_ids.extend(_write_model_files(
                db, project_id, version, bundle, service, include_model_file=True,
            ))
    return resource_ids


def build_evidence_export(
    db: Session, project_id, *, scope: str, target_id, include_audit: bool = False,
    storage=None,
) -> Artifact:
    """组装证据包并注册为平台工件（type=evidence_export；调用方负责 commit）。

    include_audit 只应由持有 audit.read 的调用方开启——审计日志不属于普通只读成员。
    """
    if scope not in ("alert", "model_version"):
        raise EvidenceExportError("EVIDENCE_SCOPE_INVALID")
    from app.services.artifact_service import ArtifactService, build_artifact_service

    with tempfile.TemporaryDirectory() as workdir:
        bundle = _Bundle(Path(workdir) / "evidence")
        service = ArtifactService(db, storage) if storage is not None else build_artifact_service(db)
        if scope == "alert":
            resource_ids = _collect_alert(db, project_id, target_id, bundle, service)
        else:
            version = find_project_model_version(db, project_id, target_id)
            if version is None:
                raise EvidenceExportError("MODEL_VERSION_NOT_FOUND")
            resource_ids = _write_model_files(
                db, project_id, version, bundle, service, include_model_file=True,
            )
        if include_audit:
            audit_rows = (
                db.query(AuditEvent)
                .filter(
                    AuditEvent.project_id == project_id,
                    AuditEvent.resource_id.in_(resource_ids),
                )
                .order_by(AuditEvent.created_at.asc())
                .limit(5000)
                .all()
            )
            bundle.json("audit/audit_events.json", {
                "count": len(audit_rows), "items": [_row(row) for row in audit_rows],
            })

        # MANIFEST.SHA256：「<哈希>  <相对路径>」两空格分隔，sha256sum -c 直接可校验
        manifest = Path(workdir) / "MANIFEST.SHA256"
        lines = [f"{_sha256_file(path)}  {relpath}" for relpath, path in sorted(bundle.entries)]
        manifest.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
        zip_path = Path(workdir) / "evidence.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
            for relpath, path in sorted(bundle.entries):
                archive.write(path, arcname=relpath)
            archive.write(manifest, arcname="MANIFEST.SHA256")

        stamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
        return service.create_from_file(
            project_id, zip_path, f"evidence-{scope}-{stamp}.zip", "evidence_export",
            metadata={
                "source": "generated", "kind": "evidence_export", "scope": scope,
                "target_id": str(target_id), "file_count": len(bundle.entries),
                "include_audit": bool(include_audit),
            },
            commit=False,
        )
