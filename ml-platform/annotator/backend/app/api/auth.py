from fastapi import APIRouter, Depends, Form, Header, HTTPException, Response
import httpx
from app.config import settings
from app.services.session import ADMIN_COOKIE_NAME, COOKIE_NAME, PortalPrincipal, cookie_options, require_portal_session

router = APIRouter(prefix="/portal/auth", tags=["portal-auth"])

@router.post("/register", status_code=201)
async def register(username: str = Form(...), password: str = Form(...)):
    async with httpx.AsyncClient(base_url=settings.api_origin) as client:
        response = await client.post("/portal/auth/register", json={"username": username, "password": password})
    if response.status_code >= 400:
        raise HTTPException(response.status_code, response.json().get("detail", "registration failed"))
    return response.json()

@router.post("/login")
async def login(response: Response, username: str = Form(...), password: str = Form(...)):
    async with httpx.AsyncClient(base_url=settings.api_origin) as client:
        upstream = await client.post("/portal/auth/login", data={"username": username, "password": password})
    if upstream.status_code >= 400:
        raise HTTPException(upstream.status_code, upstream.json().get("detail", "login failed"))
    payload = upstream.json()
    cookie_header = upstream.headers.get("set-cookie", "")
    token = None
    issued_name = None
    # Admin marker must be tested first: "admin_portal_session=" contains
    # "portal_session=" as a substring.
    for name in (ADMIN_COOKIE_NAME, COOKIE_NAME):
        marker = f"{name}="
        if marker in cookie_header:
            issued_name = name
            token = cookie_header.split(marker, 1)[1].split(";", 1)[0]
            break
    if not token:
        raise HTTPException(502, "portal session was not issued")
    response.set_cookie(issued_name, token, **cookie_options())
    return payload

@router.post("/logout", status_code=204)
def logout(
    response: Response,
    viewer: str = Header(default="annotator", alias="X-Portal-Viewer"),
):
    # Secure cookies can only be deleted by a Set-Cookie that also carries the
    # Secure attribute (RFC 6265bis strict secure cookies), so the deletion must
    # mirror cookie_options() or browsers silently ignore it. Only the active
    # viewer's cookie is cleared: the annotator and admin sessions coexist in
    # separate cookies, so logging out of one must not kill the other.
    active = ADMIN_COOKIE_NAME if viewer == "admin" else COOKIE_NAME
    response.delete_cookie(active, path="/", secure=True, httponly=True, samesite="lax")

@router.get("/me")
def me(principal: PortalPrincipal = Depends(require_portal_session)):
    # Lets the SPA restore an authenticated queue view after a browser
    # refresh instead of dropping the annotator back to the login page.
    # Admin sessions have no annotator subject; kind/user_id let the SPA
    # route them to the admin review area instead of the annotator queue.
    return {
        "subject_id": str(principal.subject_id) if principal.subject_id is not None else None,
        "username": principal.username,
        "kind": principal.kind,
        "user_id": str(principal.user_id) if principal.user_id is not None else None,
    }
