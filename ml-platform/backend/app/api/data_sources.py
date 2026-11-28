"""External data source API (补齐路线第一批 B1-08，项目级只读数据源).

- 权限：读走 project.read；写动词走 resource.create/update/delete 通用键；
  查询类动作（test/tables/preview/import）落项目审计（action 前缀
  data_source.*），白名单拒绝也落审计。
- 口令任何接口不回显：响应 mask 为「已设置」布尔位（同通知凭据口径）。
- 白名单拒绝统一 400 SQL_WHITELIST_*；连接失败 502 DATA_SOURCE_CONNECT_FAILED。
"""

import uuid
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.api.auth import get_current_user
from app.api.project_security import require_project_access
from app.database import get_db
from app.models.external_data_source import ExternalDataSource
from app.models.user import User
from app.services.audit import AuditIntent, AuditService
from app.services.external_data_sources import (
    ExternalDataSourceError,
    encrypt_password,
    import_to_dataset,
    invalidate_engines,
    list_tables,
    preview,
    test_connection,
    validate_connect_args,
)
from app.services.project_access import ProjectAccess
from pydantic import BaseModel, ConfigDict, Field

router = APIRouter(tags=["data_sources"])

# 写端点审计登记（横向合同 §6-4；第三轮复审 2026-11-28 补齐）。test/preview/
# import 三端点的 action 字面量经 _audit_query 位置参数传入。
PROJECT_WRITE_ACTIONS = {
    "POST /api/projects/{project_id}/data-sources": "data_source.create",
    "PUT /api/projects/{project_id}/data-sources/{source_id}": "data_source.update",
    "DELETE /api/projects/{project_id}/data-sources/{source_id}": "data_source.delete",
    "POST /api/projects/{project_id}/data-sources/{source_id}/test": "data_source.test",
    "POST /api/projects/{project_id}/data-sources/{source_id}/preview": "data_source.preview",
    "POST /api/projects/{project_id}/data-sources/{source_id}/import": "data_source.import",
}

ALLOWED_DB_TYPES = ("postgresql", "mysql")
ALLOWED_SSL_MODES = ("disable", "prefer", "require", "verify-full")


def _audit_service(db: Session) -> AuditService:
    return AuditService(sessionmaker(bind=db.get_bind()))


def _source_out(item: ExternalDataSource) -> dict:
    return {
        "id": str(item.id),
        "project_id": str(item.project_id),
        "name": item.name,
        "db_type": item.db_type,
        "host": item.host,
        "port": item.port,
        "database": item.database,
        "username": item.username,
        "password_set": True,
        "ssl_mode": item.ssl_mode,
        "extra": item.extra or {},
        "created_by": str(item.created_by_id) if item.created_by_id else None,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
    }


def _get_source(db: Session, project_id: UUID, source_id, ) -> ExternalDataSource:
    source = db.query(ExternalDataSource).filter(
        ExternalDataSource.id == _uuid_or_404(source_id),
        ExternalDataSource.project_id == project_id,
    ).first()
    if source is None:
        raise HTTPException(404, {"code": "DATA_SOURCE_NOT_FOUND"})
    return source


def _uuid_or_404(value, code: str = "DATA_SOURCE_NOT_FOUND") -> uuid.UUID:
    try:
        return value if isinstance(value, UUID) else uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        raise HTTPException(404, {"code": code})


def _datasource_error(error: ExternalDataSourceError) -> HTTPException:
    status = 502 if error.code == "DATA_SOURCE_CONNECT_FAILED" else 400
    if error.code == "DATA_SOURCE_NOT_FOUND_LOCAL":
        status = 404
    return HTTPException(status, {"code": error.code, "message": str(error)[:200]})


class DataSourceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=128)
    db_type: str
    host: str = Field(min_length=1, max_length=256)
    port: int = Field(ge=1, le=65535)
    database: str = Field(min_length=1, max_length=128)
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=512)
    ssl_mode: str = "prefer"
    extra: dict | None = None


class DataSourceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=128)
    host: str | None = Field(default=None, min_length=1, max_length=256)
    port: int | None = Field(default=None, ge=1, le=65535)
    database: str | None = Field(default=None, min_length=1, max_length=128)
    username: str | None = Field(default=None, min_length=1, max_length=128)
    password: str | None = Field(default=None, min_length=1, max_length=512)
    ssl_mode: str | None = None
    extra: dict | None = None


class SqlQueryBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sql: str = Field(min_length=1, max_length=100_000)


class ImportBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sql: str = Field(min_length=1, max_length=100_000)
    dataset_name: str = Field(min_length=1, max_length=128)


def _validate_payload(data: DataSourceCreate | DataSourceUpdate) -> None:
    if getattr(data, "db_type", None) is not None and data.db_type not in ALLOWED_DB_TYPES:
        raise HTTPException(422, {"code": "DATA_SOURCE_DB_TYPE_INVALID"})
    ssl_mode = getattr(data, "ssl_mode", None)
    if ssl_mode is not None and ssl_mode not in ALLOWED_SSL_MODES:
        raise HTTPException(422, {"code": "DATA_SOURCE_SSL_MODE_INVALID"})
    extra = data.extra
    if extra:
        try:
            validate_connect_args(extra)  # 白名单键校验
        except ExternalDataSourceError as error:
            raise HTTPException(400, {"code": error.code, "message": str(error)[:200]}) from None


@router.get("/api/projects/{project_id}/data-sources")
def list_data_sources(
    project_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, current_user.id, "project.read")
    items = (
        db.query(ExternalDataSource)
        .filter(ExternalDataSource.project_id == project_id)
        .order_by(ExternalDataSource.created_at.asc(), ExternalDataSource.id.asc())
        .all()
    )
    return {"items": [_source_out(item) for item in items], "total": len(items)}


@router.post("/api/projects/{project_id}/data-sources", status_code=201)
def create_data_source(
    project_id: UUID,
    request: Request,
    data: DataSourceCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    access: ProjectAccess = require_project_access(
        db, project_id, current_user.id, "resource.create",
    )
    _validate_payload(data)
    source_id = uuid.uuid4()
    try:
        with _audit_service(db).project_action(
            db,
            request=request,
            actor=current_user,
            access=access,
            permission="resource.create",
            intent=AuditIntent(
                project_id=project_id,
                action="data_source.create",
                resource_type="external_data_source",
                resource_id=str(source_id),
                changes={"name": data.name, "db_type": data.db_type, "host": data.host},
            ),
            allowed_changes={"name", "db_type", "host", "database", "username", "ssl_mode"},
        ):
            source = ExternalDataSource(
                id=source_id,
                project_id=project_id,
                name=data.name.strip(),
                db_type=data.db_type,
                host=data.host.strip(),
                port=data.port,
                database=data.database.strip(),
                username=data.username.strip(),
                password_encrypted=encrypt_password(data.password),
                ssl_mode=data.ssl_mode,
                extra=validate_connect_args(data.extra) or None,
                created_by_id=current_user.id,
            )
            db.add(source)
            db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, {"code": "DATA_SOURCE_NAME_CONFLICT"}) from None
    db.refresh(source)
    return _source_out(source)


@router.get("/api/projects/{project_id}/data-sources/{source_id}")
def get_data_source(
    project_id: UUID,
    source_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, current_user.id, "project.read")
    return _source_out(_get_source(db, project_id, source_id))


@router.put("/api/projects/{project_id}/data-sources/{source_id}")
def update_data_source(
    project_id: UUID,
    source_id: str,
    request: Request,
    data: DataSourceUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    access: ProjectAccess = require_project_access(
        db, project_id, current_user.id, "resource.update",
    )
    _validate_payload(data)
    source = _get_source(db, project_id, source_id)
    with _audit_service(db).project_action(
        db,
        request=request,
        actor=current_user,
        access=access,
        permission="resource.update",
        intent=AuditIntent(
            project_id=project_id,
            action="data_source.update",
            resource_type="external_data_source",
            resource_id=str(source.id),
            changes=data.model_dump(exclude_none=True, exclude={"password"}),
        ),
        allowed_changes={"name", "host", "port", "database", "username", "ssl_mode"},
    ):
        if data.name is not None:
            source.name = data.name.strip()
        if data.host is not None:
            source.host = data.host.strip()
        if data.port is not None:
            source.port = data.port
        if data.database is not None:
            source.database = data.database.strip()
        if data.username is not None:
            source.username = data.username.strip()
        if data.password:
            source.password_encrypted = encrypt_password(data.password)
        if data.ssl_mode is not None:
            source.ssl_mode = data.ssl_mode
        if data.extra is not None:
            try:
                source.extra = validate_connect_args(data.extra) or None
            except ExternalDataSourceError as error:
                raise HTTPException(400, {"code": error.code, "message": str(error)[:200]}) from None
        db.flush()
    invalidate_engines(source.id)
    db.refresh(source)
    return _source_out(source)


@router.delete("/api/projects/{project_id}/data-sources/{source_id}", status_code=204)
def delete_data_source(
    project_id: UUID,
    source_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    access: ProjectAccess = require_project_access(
        db, project_id, current_user.id, "resource.delete",
    )
    source = _get_source(db, project_id, source_id)
    with _audit_service(db).project_action(
        db,
        request=request,
        actor=current_user,
        access=access,
        permission="resource.delete",
        intent=AuditIntent(
            project_id=project_id,
            action="data_source.delete",
            resource_type="external_data_source",
            resource_id=str(source.id),
            changes={"name": source.name},
        ),
        allowed_changes={"name"},
    ):
        db.delete(source)
        db.flush()
    invalidate_engines(source.id)
    return None


@router.post("/api/projects/{project_id}/data-sources/{source_id}/test")
def test_data_source(
    project_id: UUID,
    source_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    access: ProjectAccess = require_project_access(
        db, project_id, current_user.id, "project.read",
    )
    source = _get_source(db, project_id, source_id)
    try:
        result = test_connection(db, source)
    except ExternalDataSourceError as error:
        _audit_query(db, request, current_user, access, project_id, source.id, "data_source.test", error.code)
        raise _datasource_error(error) from None
    _audit_query(db, request, current_user, access, project_id, source.id, "data_source.test", "ok")
    return result


@router.get("/api/projects/{project_id}/data-sources/{source_id}/tables")
def list_data_source_tables(
    project_id: UUID,
    source_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, current_user.id, "project.read")
    source = _get_source(db, project_id, source_id)
    try:
        return {"items": list_tables(db, source), "total": 0}
    except ExternalDataSourceError as error:
        raise _datasource_error(error) from None


@router.post("/api/projects/{project_id}/data-sources/{source_id}/preview")
def preview_data_source(
    project_id: UUID,
    source_id: str,
    request: Request,
    body: SqlQueryBody,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    access: ProjectAccess = require_project_access(
        db, project_id, current_user.id, "project.read",
    )
    source = _get_source(db, project_id, source_id)
    try:
        result = preview(db, source, body.sql)
        result["whitelisted"] = True
        _audit_query(db, request, current_user, access, project_id, source.id, "data_source.preview", "ok")
        return result
    except ExternalDataSourceError as error:
        _audit_query(db, request, current_user, access, project_id, source.id, "data_source.preview", error.code)
        raise _datasource_error(error) from None


@router.post("/api/projects/{project_id}/data-sources/{source_id}/import")
def import_data_source(
    project_id: UUID,
    source_id: str,
    request: Request,
    body: ImportBody,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    access: ProjectAccess = require_project_access(
        db, project_id, current_user.id, "resource.create",
    )
    source = _get_source(db, project_id, source_id)
    try:
        process = import_to_dataset(
            db,
            project_id=project_id,
            operator_id=current_user.id,
            source=source,
            sql=body.sql,
            dataset_name=body.dataset_name.strip(),
        )
    except ExternalDataSourceError as error:
        _audit_query(db, request, current_user, access, project_id, source.id, "data_source.import", error.code)
        raise _datasource_error(error) from None
    _audit_query(db, request, current_user, access, project_id, source.id, "data_source.import", "ok")
    return {
        "import_id": str(process.id),
        "status": process.status,
        "dataset_name": body.dataset_name.strip(),
    }


def _audit_query(db, request, current_user, access, project_id, source_id, action: str, result: str) -> None:
    """查询类动作统一审计（成功与拒绝同形；失败经 failed 路径落库）。"""
    service = _audit_service(db)
    intent = AuditIntent(
        project_id=project_id,
        action=action,
        resource_type="external_data_source",
        resource_id=str(source_id),
        changes={"result": result},
    )
    if result == "ok":
        with service.project_action(
            db,
            request=request,
            actor=current_user,
            access=access,
            permission="project.read",
            intent=intent,
            allowed_changes={"result"},
        ):
            pass
        return
    # 拒绝/失败路径：project_action 的 denied 分支要求权限不足才触发；
    # 白名单/连接失败不是权限问题 → 直接落 failed 事件
    from app.services.audit import audit_request_context

    from app.models.access import AuditEvent

    request_id, source_ip = audit_request_context(request)
    db.add(AuditEvent(
        project_id=project_id,
        actor_id=current_user.id,
        actor_username=current_user.username,
        action=action,
        resource_type="external_data_source",
        resource_id=str(source_id),
        result="failed",
        request_id=request_id,
        source_ip=source_ip,
        changes={"result": result},
        error_code=result,
    ))
    db.commit()
