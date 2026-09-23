from pathlib import Path

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.services.security import (
    RateLimitPolicy,
    SecurityPolicy,
    SlidingWindowRateLimiter,
    enforce_request_security,
    validate_upload_filename,
    validate_upload_magic,
    expand_local_dev_origins,
)


def _request(method: str, *, origin: str | None = None, referer: str | None = None, cookies: dict[str, str] | None = None, headers: dict[str, str] | None = None) -> Request:
    all_headers = dict(headers or {})
    if origin:
        all_headers["origin"] = origin
    if referer:
        all_headers["referer"] = referer
    if cookies:
        all_headers["cookie"] = "; ".join(f"{key}={value}" for key, value in cookies.items())
    return Request({
        "type": "http",
        "method": method,
        "path": "/portal/auth/login",
        "headers": [(key.lower().encode(), value.encode()) for key, value in all_headers.items()],
    })


def test_unknown_origin_is_rejected_before_cors_response():
    policy = SecurityPolicy(allowed_origins=frozenset({"https://portal.example"}))
    with pytest.raises(HTTPException) as error:
        enforce_request_security(_request("OPTIONS", origin="https://unknown.example"), policy)
    assert error.value.status_code == 403
    assert error.value.detail["code"] == "CORS_ORIGIN_FORBIDDEN"


def test_local_dev_origin_expansion_is_bounded_to_loopback_aliases():
    origins = expand_local_dev_origins({"http://localhost:5173", "https://portal.example"})
    assert "http://localhost:5173" in origins
    assert "http://127.0.0.1:5173" in origins
    assert "http://localhost:5174" in origins
    assert "http://127.0.0.1:5174" in origins
    assert "http://localhost:5175" in origins
    assert "http://127.0.0.1:5175" in origins
    assert "https://portal.example" in origins
    assert "http://evil.example:5173" not in origins


def test_cookie_state_change_requires_origin_and_matching_csrf_token():
    policy = SecurityPolicy(allowed_origins=frozenset({"https://portal.example"}))
    with pytest.raises(HTTPException) as missing:
        enforce_request_security(
            _request("POST", origin="https://portal.example", cookies={"portal_session": "s"}),
            policy,
        )
    assert missing.value.detail["code"] == "CSRF_TOKEN_REQUIRED"

    enforce_request_security(
        _request(
            "POST",
            origin="https://portal.example",
            cookies={"portal_session": "s", "csrf_token": "token"},
            headers={"x-csrf-token": "token"},
        ),
        policy,
    )


def test_unrelated_cookie_does_not_trigger_portal_csrf_validation():
    policy = SecurityPolicy(allowed_origins=frozenset({"https://portal.example"}))
    enforce_request_security(
        _request(
            "POST",
            origin="https://portal.example",
            cookies={"analytics_id": "visitor"},
        ),
        policy,
    )


def test_bearer_authorization_with_stray_portal_cookie_skips_csrf():
    policy = SecurityPolicy(allowed_origins=frozenset({"https://portal.example"}))
    # A portal session cookie from the same host must not force the
    # double-submit check on a request that authenticates via an explicit
    # Bearer credential.
    enforce_request_security(
        _request(
            "DELETE",
            origin="https://portal.example",
            cookies={"portal_session": "s"},
            headers={"authorization": "Bearer jwt"},
        ),
        policy,
    )


def test_cookie_state_change_without_origin_or_referer_is_rejected():
    policy = SecurityPolicy(allowed_origins=frozenset({"https://portal.example"}))
    with pytest.raises(HTTPException) as error:
        enforce_request_security(
            _request("POST", cookies={"portal_session": "s", "csrf_token": "token"}, headers={"x-csrf-token": "token"}),
            policy,
        )
    assert error.value.detail["code"] == "CSRF_ORIGIN_REQUIRED"


def test_login_rate_limit_is_fail_closed():
    limiter = SlidingWindowRateLimiter()
    policy = RateLimitPolicy(capacity=2, window_seconds=60)
    assert limiter.check("login:ip", policy).allowed
    assert limiter.check("login:ip", policy).allowed
    decision = limiter.check("login:ip", policy)
    assert not decision.allowed
    assert decision.retry_after_seconds >= 1


def test_upload_filename_and_magic_byte_validation_rejects_ambiguous_input(tmp_path: Path):
    with pytest.raises(ValueError, match="UPLOAD_PATH_INVALID"):
        validate_upload_filename("../payload.csv")
    with pytest.raises(ValueError, match="UPLOAD_MAGIC_INVALID"):
        validate_upload_magic("csv", b"PK\x03\x04")
    assert validate_upload_filename("rows.csv") == "rows.csv"
    assert validate_upload_magic("csv", b"a,b\n1,2\n") == "csv"
