"""Request-level security enforcement for the platform API."""

from __future__ import annotations

from fastapi import HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.services.security import SecurityPolicy, enforce_request_security


class RequestSecurityMiddleware(BaseHTTPMiddleware):
    """Apply the shared origin and CSRF policy before CORS processing."""

    def __init__(self, app, *, allowed_origins: frozenset[str]):
        super().__init__(app)
        self.policy = SecurityPolicy(allowed_origins=allowed_origins)

    async def dispatch(self, request: Request, call_next):
        try:
            enforce_request_security(request, self.policy)
        except HTTPException as error:
            # The policy intentionally raises FastAPI's HTTPException so the
            # same contract can be used by route-level tests. Middleware
            # cannot rely on FastAPI's exception handlers, so serialize it.
            status_code = getattr(error, "status_code", 403)
            detail = getattr(error, "detail", {"code": "REQUEST_FORBIDDEN", "message": "request rejected"})
            headers = getattr(error, "headers", None) or {}
            return JSONResponse(status_code=status_code, content={"detail": detail}, headers=headers)
        return await call_next(request)


__all__ = ["RequestSecurityMiddleware"]
