"""Internal TensorBoard session gateway and HTTP proxy."""

import os
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel

from app.config import settings
from app.tensorboard_gateway.processes import (
    SessionPathInvalid,
    SessionRunMismatch,
    TensorBoardProcessManager,
)
from app.tensorboard_gateway.tokens import SessionSigner, SessionTokenInvalid


class SessionRequest(BaseModel):
    token: str


def create_gateway_app(signer=None, manager=None) -> FastAPI:
    gateway = FastAPI(title="TensorBoard Session Gateway")
    gateway.state.signer = signer
    gateway.state.manager = manager

    @gateway.post("/internal/sessions")
    def create_session(data: SessionRequest, request: Request):
        runtime_signer, runtime_manager = _runtime(request)
        try:
            claims = runtime_signer.verify(data.token)
            session = runtime_manager.get_or_start(
                session_id=claims.session_id,
                run_id=claims.run_id,
                relative_logdir=claims.relative_logdir,
                expires_at=claims.expires_at,
            )
        except (SessionTokenInvalid, SessionPathInvalid, SessionRunMismatch) as error:
            raise HTTPException(403, "Invalid TensorBoard session") from error
        return {
            "session_id": session.session_id,
            "run_id": session.run_id,
            "path": f"/sessions/{session.session_id}/",
            "expires_at": session.expires_at,
        }

    @gateway.api_route(
        "/sessions/{session_id}/{path:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    )
    async def proxy(session_id: str, path: str, token: str, request: Request):
        runtime_signer, runtime_manager = _runtime(request)
        try:
            claims = runtime_signer.verify(token)
            if claims.session_id != session_id:
                raise SessionRunMismatch("Session ID mismatch")
            session = runtime_manager.get_or_start(
                session_id=claims.session_id,
                run_id=claims.run_id,
                relative_logdir=claims.relative_logdir,
                expires_at=claims.expires_at,
            )
        except (SessionTokenInvalid, SessionPathInvalid, SessionRunMismatch) as error:
            raise HTTPException(403, "Invalid TensorBoard session") from error
        target = f"http://127.0.0.1:{session.port}/sessions/{session_id}/{path}"
        async with httpx.AsyncClient() as client:
            upstream = await client.request(
                request.method,
                target,
                params={key: value for key, value in request.query_params.items() if key != "token"},
                content=await request.body(),
                headers={
                    key: value for key, value in request.headers.items()
                    if key.lower() in {"accept", "content-type", "range"}
                },
            )
        return Response(
            content=upstream.content,
            status_code=upstream.status_code,
            headers={
                key: value for key, value in upstream.headers.items()
                if key.lower() in {"content-type", "content-range", "accept-ranges", "location"}
            },
        )

    return gateway


def _runtime(request: Request):
    signer = request.app.state.signer
    manager = request.app.state.manager
    if signer is None:
        secret = settings.resolved_tensorboard_session_secret
        if secret is None:
            raise HTTPException(503, "TensorBoard gateway is not configured")
        signer = SessionSigner(secret.get_secret_value())
        request.app.state.signer = signer
    if manager is None:
        root = Path(os.environ.get("TENSORBOARD_LOG_ROOT", "/tmp/tensorboard-runs"))
        manager = TensorBoardProcessManager(
            root,
            idle_timeout_seconds=settings.tensorboard_idle_timeout_seconds,
        )
        request.app.state.manager = manager
    manager.cleanup()
    return signer, manager


app = create_gateway_app()
