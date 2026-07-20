"""Request correlation using caller-provided or generated UUIDs."""

import uuid

from starlette.middleware.base import BaseHTTPMiddleware


REQUEST_ID_HEADER = "X-Request-ID"


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        raw_value = request.headers.get(REQUEST_ID_HEADER)
        try:
            request_id = uuid.UUID(raw_value) if raw_value else uuid.uuid4()
        except (ValueError, TypeError, AttributeError):
            request_id = uuid.uuid4()
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = str(request_id)
        return response
