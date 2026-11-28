"""Evidence chain overview & export API (补齐路线第一批 F2b, B1-12 / E21).

技术方案 §9.9：
- 总览：按模型版本看 12 环节状态与上线检查五项，各步带可下钻的依据引用；
- 留档：重算模型校验和并把当时的 12 环节快照存档（配置类权限）；
- 导出：按预警或按模型版本打包证据链 ZIP（附 MANIFEST.SHA256），注册为平台
  工件；审计日志只在调用方持有 audit.read 时随包；
- 下载：取回证据包工件。

权限：总览与按模型版本导出 = project.read；按预警导出 = quality.alert_handle
（与预警 CSV 导出同口径）；留档 = quality.manage。
"""
from __future__ import annotations

import logging
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, sessionmaker

from app.api.auth import get_current_user
from app.api.project_security import require_project_access
from app.database import get_db
from app.models.artifact import Artifact
from app.models.user import User
from app.services import evidence_chain as chain
from app.services.audit import AuditIntent, AuditService
from app.services.artifact_service import ArtifactAccessError, build_artifact_service
from app.services.project_access import ROLE_PERMISSIONS, ProjectAccess

logger = logging.getLogger(__name__)

router = APIRouter(tags=["evidence-chain"])

# 写端点 → 审计动作映射（合同 §6-4：新增写接口纳入既有项目访问权限测试矩阵）
PROJECT_WRITE_ACTIONS = {
    "POST /api/projects/{project_id}/model-versions/{version_id}/evidence-checks": "quality.evidence.check",
    "POST /api/projects/{project_id}/evidence-exports": "quality.evidence.export",
}


_CHECK_LABELS = {
    "model_file": ("模型文件", "Model file"),
    "checksum": ("校验和", "Checksum"),
    "data_version": ("数据版本", "Data version"),
    "evaluation": ("评估完整性", "Evaluation completeness"),
    "production_unique": ("生产版本唯一", "Single production version"),
}


class EvidenceExportRequest(BaseModel):
    scope: str = Field(pattern="^(alert|model_version)$")
    target_id: str = Field(min_length=1, max_length=64)


def _audit_service(db: Session) -> AuditService:
    return AuditService(sessionmaker(bind=db.get_bind()))


def _version_or_404(db: Session, project_id: UUID, version_id: str):
    version = chain.find_project_model_version(db, project_id, version_id)
    if version is None:
        raise HTTPException(404, {"code": "MODEL_VERSION_NOT_FOUND"})
    return version


def _labelled(checks: list[dict]) -> list[dict]:
    return [
        {**check, "title": _CHECK_LABELS[check["key"]][0], "title_en": _CHECK_LABELS[check["key"]][1]}
        for check in checks
    ]


@router.get("/api/projects/{project_id}/model-versions/{version_id}/evidence-overview")
def get_evidence_overview(
    project_id: UUID,
    version_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """12 环节状态与上线检查五项（即时计算，不重算文件哈希）。"""
    require_project_access(db, project_id, current_user.id, "project.read")
    version = _version_or_404(db, project_id, version_id)
    overview = chain.build_evidence_overview(db, project_id, version)
    overview["checks"] = _labelled(overview["checks"])
    archived = chain.latest_archived_check(db, version.id)
    overview["archived_check"] = (
        {"id": str(archived.id), "created_at": archived.created_at.isoformat(),
         "checks_passed": sum(1 for check in archived.checks if check["status"] == "pass")}
        if archived is not None else None
    )
    return overview


@router.post("/api/projects/{project_id}/model-versions/{version_id}/evidence-checks")
def archive_evidence_check(
    project_id: UUID,
    version_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """留档一次上线检查：重算模型校验和，并把当时的 12 环节快照一并存档。"""
    access: ProjectAccess = require_project_access(
        db, project_id, current_user.id, "quality.manage",
    )
    version = _version_or_404(db, project_id, version_id)
    with _audit_service(db).project_action(
        db, request=request, actor=current_user, access=access,
        permission="quality.manage",
        intent=AuditIntent(
            project_id=project_id, action="quality.evidence.check",
            resource_type="model_version", resource_id=str(version.id),
            changes={"version_number": int(version.version_number or 0)},
        ),
        allowed_changes={"version_number"},
    ):
        record, overview = chain.archive_launch_check(
            db, project_id, version, actor_id=current_user.id,
        )
        db.commit()
        db.refresh(record)
    overview["checks"] = _labelled(overview["checks"])
    overview["archived_check_id"] = str(record.id)
    return overview


@router.post("/api/projects/{project_id}/evidence-exports")
def create_evidence_export(
    project_id: UUID,
    request: Request,
    data: EvidenceExportRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """打包证据链 ZIP（附 MANIFEST.SHA256），注册为平台工件并落审计。"""
    # 按预警打包含处置轨迹，与预警 CSV 导出同一权限口径；按模型版本打包是只读
    permission = "quality.alert_handle" if data.scope == "alert" else "project.read"
    access: ProjectAccess = require_project_access(
        db, project_id, current_user.id, permission,
    )
    include_audit = "audit.read" in ROLE_PERMISSIONS[access.role]
    try:
        artifact = chain.build_evidence_export(
            db, project_id, scope=data.scope, target_id=data.target_id,
            include_audit=include_audit,
        )
    except chain.EvidenceExportError as error:
        db.rollback()
        raise _error(error) from None
    artifact_id = artifact.id
    with _audit_service(db).project_action(
        db, request=request, actor=current_user, access=access,
        permission=permission,
        intent=AuditIntent(
            project_id=project_id, action="quality.evidence.export",
            resource_type="evidence_export", resource_id=str(artifact_id),
            changes={"scope": data.scope, "target_id": data.target_id,
                     "include_audit": include_audit},
        ),
        allowed_changes={"scope", "target_id", "include_audit"},
    ):
        db.commit()
        db.refresh(artifact)
    metadata = dict(artifact.metadata_ or {})
    return {
        "artifact_id": str(artifact.id),
        "name": artifact.name,
        "file_size": artifact.file_size,
        "sha256": metadata.get("sha256"),
        "file_count": metadata.get("file_count"),
        "include_audit": include_audit,
    }


def _error(error: ValueError) -> HTTPException:
    text = str(error)
    code, _, _ = text.partition("（")
    return HTTPException(404 if code.endswith("_NOT_FOUND") else 422, {"code": code, "message": text})


@router.get("/api/projects/{project_id}/evidence-exports/{artifact_id}/download")
def download_evidence_export(
    project_id: UUID,
    artifact_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """取回证据包。对象存储取出的临时文件在上下文退出即清理，所以在上下文内读完。"""
    require_project_access(db, project_id, current_user.id, "project.read")
    try:
        with build_artifact_service(db).materialize(
            artifact_id, project_id, "evidence_export",
        ) as path:
            content = Path(path).read_bytes()
            filename = Path(path).name
    except ArtifactAccessError as error:
        raise HTTPException(404, {"code": "EVIDENCE_EXPORT_NOT_FOUND", "message": str(error)}) from None
    artifact = db.query(Artifact).filter(Artifact.id == artifact_id).first()
    download_name = artifact.name if artifact is not None and artifact.name else filename
    return Response(
        content=content,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{download_name}"'},
    )
