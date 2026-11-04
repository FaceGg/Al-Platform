"""Chat tools execution API (spec v0.9 §15, AutoML Agent Task A6.2).

对话操作工具的唯一 HTTP 入口：白名单校验、写确认、用户本人权限、平台审计
全部在服务层执行——本路由只做身份与错误码映射。
"""

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.api.users import get_current_admin
from app.database import get_db
from app.models.user import User
from app.services.chat_tools import (
    ToolConfirmationRequired,
    ToolNotInWhitelist,
    execute_tool,
)

router = APIRouter(prefix="/api/chat-tools", tags=["chat-tools"])


class ToolInvocation(BaseModel):
    tool: str = Field(min_length=1, max_length=64)
    params: dict = Field(default_factory=dict)
    confirmed: bool = False


@router.post("/execute")
def execute(
    payload: ToolInvocation,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # 管理员禁用的工具在执行层拒绝（前端隐藏只是第一层）
    from app.models.platform_option import get_option

    disabled = set(get_option(db, "chat_tools_disabled", []) or [])
    if payload.tool in disabled:
        return {
            "status": "rejected",
            "code": "CHAT_TOOL_DISABLED_BY_ADMIN",
            "tool": payload.tool,
            "message": "该工具已被管理员停用",
        }
    try:
        result = execute_tool(
            db,
            user=current_user,
            tool=payload.tool,
            params=payload.params,
            confirmed=payload.confirmed,
            request=request,
        )
    except ToolNotInWhitelist as error:
        return {
            "status": "rejected",
            "code": "CHAT_TOOL_NOT_IN_WHITELIST",
            "tool": str(error),
        }
    except ToolConfirmationRequired as error:
        return {
            "status": "confirmation_required",
            "code": "CHAT_TOOL_CONFIRMATION_REQUIRED",
            "tool": error.tool,
            "message": "写操作需要用户在对话中确认后执行",
        }
    except LookupError as error:
        return {"status": "failed", "code": "CHAT_TOOL_TARGET_NOT_FOUND",
                "message": str(error)}
    except ValueError as error:
        return {"status": "failed", "code": "CHAT_TOOL_PARAMS_INVALID",
                "message": str(error)}
    return {"status": "success", "tool": payload.tool, "result": result}


@router.get("/whitelist")
def whitelist(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """工具目录（中文展示名+分组+启停状态）——启停配置管理员全局生效。"""
    from app.models.platform_option import get_option
    from app.services.chat_tools import READ_TOOLS, WRITE_TOOLS, TOOL_CATALOG

    disabled = set(get_option(db, "chat_tools_disabled", []) or [])

    def _tools(kind: str, names) -> list[dict]:
        return [
            {"tool": name, "label": TOOL_CATALOG.get(name, {}).get("label", name), "kind": kind, "enabled": name not in disabled}
            for name in names
        ]

    read = _tools("read", sorted(READ_TOOLS - {"save_insight"}))
    insight = _tools("insight", ["save_insight"])
    write = _tools("write", sorted(WRITE_TOOLS))
    return {
        "read_tools": read,
        "insight_tools": insight,
        "write_tools": write,
        "all": read + insight + write,
    }


class ChatToolsConfigRequest(BaseModel):
    disabled: list[str] = Field(default_factory=list)


@router.get("/config")
def get_tools_config(
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    from app.models.platform_option import get_option
    from app.services.chat_tools import TOOL_CATALOG

    disabled = set(get_option(db, "chat_tools_disabled", []) or [])
    return {
        "tools": [
            {"tool": name, "label": meta["label"], "kind": meta["kind"], "enabled": name not in disabled}
            for name, meta in TOOL_CATALOG.items()
        ],
    }


@router.put("/config")
def put_tools_config(
    payload: ChatToolsConfigRequest,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """管理员配置工具启停（全局生效，同步全部用户）。"""
    from app.models.platform_option import set_option
    from app.services.chat_tools import TOOL_CATALOG
    from app.services.platform_audit import PlatformAuditIntent, record_platform_event

    unknown = [name for name in payload.disabled if name not in TOOL_CATALOG]
    if unknown:
        from fastapi import HTTPException

        raise HTTPException(422, detail={"code": "CHAT_TOOL_UNKNOWN", "tools": unknown})
    set_option(db, "chat_tools_disabled", sorted(set(payload.disabled)))
    record_platform_event(
        db,
        actor=admin,
        request=request,
        intent=PlatformAuditIntent(
            action="chat_tools.config",
            resource_type="platform_option",
            resource_id="chat_tools_disabled",
            changes={"disabled_count": len(set(payload.disabled))},
        ),
        result="success",
    )
    db.commit()
    return {"disabled": sorted(set(payload.disabled))}
