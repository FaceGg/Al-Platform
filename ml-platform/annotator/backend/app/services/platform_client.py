import httpx
import jwt
import secrets
from datetime import datetime, timedelta, timezone
from app.config import settings

class PlatformClientError(RuntimeError):
    def __init__(self, message: str, *, status_code: int = 502, detail: dict | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.detail = detail or {"code": "PORTAL_PLATFORM_UNAVAILABLE", "message": message}

class PlatformClient:
    def __init__(self, base_url: str | None = None):
        self.base_url = base_url or settings.api_origin

    async def resolve_portal_session(self, token: str) -> dict:
        try:
            async with httpx.AsyncClient(base_url=self.base_url) as client:
                response = await client.get("/portal/auth/me", cookies={"portal_session": token})
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise PlatformClientError("portal session could not be resolved") from error

    def _service_token(self, *, subject_id: str, scopes: list[str]) -> str:
        now = datetime.now(timezone.utc)
        return jwt.encode({
            "iss": settings.service_issuer,
            "aud": settings.service_audience,
            "sub": "annotator-portal",
            "project_id": "*",
            "annotator_subject_id": subject_id,
            "scope": " ".join(sorted(set(scopes))),
            "nonce": secrets.token_urlsafe(16),
            "iat": now,
            "exp": now + timedelta(seconds=60),
        }, settings.service_secret, algorithm="HS256")

    async def internal_request(self, method: str, path: str, *, subject_id: str, scope: str, **kwargs) -> dict:
        headers = dict(kwargs.pop("headers", {}))
        headers["Authorization"] = f"Bearer {self._service_token(subject_id=subject_id, scopes=[scope])}"
        try:
            async with httpx.AsyncClient(base_url=self.base_url) as client:
                response = await client.request(method, path, headers=headers, **kwargs)
            response.raise_for_status()
            return response.json() if response.content else {}
        except httpx.HTTPStatusError as error:
            if error.response.status_code in {400, 403, 404, 409, 422}:
                try:
                    payload = error.response.json()
                except ValueError:
                    payload = None
                detail = payload.get("detail") if isinstance(payload, dict) else None
                if isinstance(detail, dict) and isinstance(detail.get("code"), str):
                    raise PlatformClientError(
                        "internal portal request rejected",
                        status_code=error.response.status_code,
                        detail=detail,
                    ) from error
            raise PlatformClientError("internal portal request failed") from error
        except (httpx.HTTPError, ValueError) as error:
            raise PlatformClientError("internal portal request failed") from error
