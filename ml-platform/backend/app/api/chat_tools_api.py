"""Chat tools execution API (spec v0.9 §15, AutoML Agent Task A6.2).

对话操作工具的唯一 HTTP 入口：白名单校验、写确认、用户本人权限、平台审计
全部在服务层执行——本路由只做身份与错误码映射。
"""

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
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
def whitelist(current_user: User = Depends(get_current_user)):
    """LLM 系统提示据此声明能力边界——白名单即边界（§15.2 第一层）。"""
    from app.services.chat_tools import READ_TOOLS, WRITE_TOOLS

    return {
        "read_tools": sorted(READ_TOOLS - {"save_insight"}),
        "insight_tools": ["save_insight"],
        "write_tools": sorted(WRITE_TOOLS),
    }
