"""SPC analysis API (补齐路线第一批 F4, B1-06).

技术方案 §9C.3：分析 = project.read；把判异点登记为预警 = quality.alert_handle
（D37）。规格限优先取场景规格定义，同时保留手工录入，结果里标明规格来源。
"""
from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, sessionmaker

from app.api.auth import get_current_user
from app.api.project_security import require_project_access
from app.database import get_db
from app.models.user import User
from app.services import spc_analysis as analysis
from app.services.audit import AuditIntent, AuditService
from app.services.project_access import ProjectAccess

router = APIRouter(tags=["spc"])


class SpcAnalyzeRequest(BaseModel):
    source: Literal["dataset", "inference"] = "dataset"
    field: str = Field(min_length=1, max_length=256)
    chart: Literal["xbar_r", "xbar_s", "i_mr", "p", "np", "c", "u"] = "i_mr"
    dataset_version_id: str | None = None
    scene_id: str | None = None
    station_id: str | None = None
    subgroup_size: int = Field(default=5, ge=2, le=10)
    # 数据集来源：行号范围与「是否缺陷」列（计数型图用）
    row_from: int | None = Field(default=None, ge=0)
    row_to: int | None = Field(default=None, ge=0)
    defect_field: str | None = Field(default=None, max_length=256)
    # 推理来源：时间窗（小时）
    hours: int = Field(default=24, ge=1, le=24 * 90)
    # 规格限：留空取场景规格定义；填了则逐项覆盖
    usl: float | None = None
    lsl: float | None = None
    target: float | None = None
    use_scene_spec: bool = True
    rules: list[int] = Field(default_factory=lambda: [1, 2, 3, 4, 5, 6, 7, 8])
    raise_alerts: bool = False


def _audit_service(db: Session) -> AuditService:
    return AuditService(sessionmaker(bind=db.get_bind()))


def _error(error: ValueError) -> HTTPException:
    text = str(error)
    code, _, _ = text.partition("（")
    status = 404 if code.endswith("_NOT_FOUND") else 422
    return HTTPException(status, {"code": code, "message": text})


@router.get("/api/projects/{project_id}/spc/fields")
def spc_fields(
    project_id: UUID,
    source: str = "dataset",
    dataset_version_id: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """可选的过程参数：数据集版本的列，或推理结果的三个数值列。"""
    require_project_access(db, project_id, current_user.id, "project.read")
    if source == "inference":
        return {
            "source": "inference",
            "fields": [
                {"name": name, "label": label, "numeric": True}
                for name, label in analysis.INFERENCE_FIELDS.items()
            ],
        }
    if not dataset_version_id:
        raise HTTPException(422, {"code": "DATASET_VERSION_REQUIRED", "message": "数据集来源需要指定数据集版本"})
    try:
        fields = analysis.dataset_fields(db, project_id, dataset_version_id)
    except analysis.SpcAnalysisError as error:
        raise _error(error) from None
    return {"source": "dataset", "fields": fields}


@router.post("/api/projects/{project_id}/spc/analyze")
def spc_analyze(
    project_id: UUID,
    request: Request,
    data: SpcAnalyzeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """执行一次 SPC 分析。raise_alerts=true 时把判异点登记为 SPC 判异类预警。"""
    permission = "quality.alert_handle" if data.raise_alerts else "project.read"
    access: ProjectAccess = require_project_access(db, project_id, current_user.id, permission)
    try:
        result = analysis.analyze(
            db, project_id, data.model_dump(), raise_alerts=data.raise_alerts,
        )
    except analysis.SpcAnalysisError as error:
        db.rollback()
        raise _error(error) from None
    if data.raise_alerts and result["alerts_raised"]:
        with _audit_service(db).project_action(
            db, request=request, actor=current_user, access=access,
            permission="quality.alert_handle",
            intent=AuditIntent(
                project_id=project_id, action="quality.spc.raise_alerts",
                resource_type="quality_alert", resource_id=None,
                changes={"field": data.field, "chart": data.chart,
                         "raised": result["alerts_raised"]},
            ),
            allowed_changes={"field", "chart", "raised"},
        ):
            db.commit()
    elif data.raise_alerts:
        # 判异点全部并入已有预警：也要提交（计数与轨迹已变化）
        db.commit()
    return result
