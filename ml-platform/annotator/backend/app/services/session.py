from dataclasses import dataclass
import uuid

from fastapi import Depends, HTTPException, Request

from app.services.platform_client import PlatformClient, PlatformClientError

COOKIE_NAME = "portal_session"
ADMIN_COOKIE_NAME = "admin_portal_session"

def cookie_options() -> dict:
    return {"httponly": True, "secure": True, "samesite": "lax", "path": "/"}


@dataclass(frozen=True)
class PortalPrincipal:
    subject_id: uuid.UUID | None
    username: str
    kind: str = "annotator"
    user_id: uuid.UUID | None = None


async def require_portal_session(request: Request) -> PortalPrincipal:
    """Resolve a portal session without exposing it to internal task APIs.

    The SPA sends X-Portal-Viewer (annotator|admin) on every /portal request;
    the two account kinds live in separate cookies so one browser can hold an
    annotator and an admin session side by side.
    """
    viewer = request.headers.get("X-Portal-Viewer", "annotator")
    cookie_name = ADMIN_COOKIE_NAME if viewer == "admin" else COOKIE_NAME
    token = request.cookies.get(cookie_name)
    if not token:
        raise HTTPException(status_code=401, detail={"code": "PORTAL_SESSION_REQUIRED"})
    try:
        identity = await PlatformClient().resolve_portal_session(token, viewer=viewer, cookie_name=cookie_name)
        kind = str(identity.get("kind") or "annotator")
        if kind == "admin":
            user_id = identity.get("user_id")
            if not user_id:
                raise KeyError("user_id")
            return PortalPrincipal(
                subject_id=None,
                username=str(identity["username"]),
                kind="admin",
                user_id=uuid.UUID(str(user_id)),
            )
        subject_id = identity.get("subject_id")
        if not subject_id:
            raise KeyError("subject_id")
        return PortalPrincipal(
            subject_id=uuid.UUID(str(subject_id)),
            username=str(identity["username"]),
            kind="annotator",
            user_id=None,
        )
    except (KeyError, ValueError, PlatformClientError) as error:
        raise HTTPException(status_code=401, detail={"code": "PORTAL_SESSION_INVALID"}) from error


async def require_annotator_session(principal: PortalPrincipal = Depends(require_portal_session)) -> PortalPrincipal:
    """Annotator-scoped portal routes.

    Admin sessions have no annotator subject; reject them here with a clear
    code instead of letting callers mint a service token whose
    annotator_subject_id claim would be "None" (SERVICE_SUBJECT_INVALID).
    Depends on require_portal_session so dependency overrides keep working.
    """
    if principal.subject_id is None:
        raise HTTPException(status_code=403, detail={"code": "PORTAL_ANNOTATOR_REQUIRED"})
    return principal
