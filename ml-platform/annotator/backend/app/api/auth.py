from fastapi import APIRouter, Form, HTTPException, Response
import httpx
from app.config import settings
from app.services.session import COOKIE_NAME, cookie_options

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
    marker = "portal_session="
    if marker in cookie_header:
        token = cookie_header.split(marker, 1)[1].split(";", 1)[0]
    if not token:
        raise HTTPException(502, "portal session was not issued")
    response.set_cookie(COOKIE_NAME, token, **cookie_options())
    return payload

@router.post("/logout", status_code=204)
def logout(response: Response):
    response.delete_cookie(COOKIE_NAME, path="/")
