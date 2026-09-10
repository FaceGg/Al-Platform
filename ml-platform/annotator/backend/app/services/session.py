from dataclasses import dataclass
import uuid

from fastapi import HTTPException, Request

from app.services.platform_client import PlatformClient, PlatformClientError

COOKIE_NAME = "portal_session"

def cookie_options() -> dict:
    return {"httponly": True, "secure": True, "samesite": "lax", "path": "/"}


@dataclass(frozen=True)
class PortalPrincipal:
    subject_id: uuid.UUID
    username: str


async def require_portal_session(request: Request) -> PortalPrincipal:
    """Resolve a portal session without exposing it to internal task APIs."""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail={"code": "PORTAL_SESSION_REQUIRED"})
    try:
        identity = await PlatformClient().resolve_portal_session(token)
        return PortalPrincipal(subject_id=uuid.UUID(identity["subject_id"]), username=str(identity["username"]))
    except (KeyError, ValueError, PlatformClientError) as error:
        raise HTTPException(status_code=401, detail={"code": "PORTAL_SESSION_INVALID"}) from error
