"""Contained TensorBoard subprocess lifecycle management."""

import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


class SessionPathInvalid(ValueError):
    pass


class SessionRunMismatch(ValueError):
    pass


@dataclass
class TensorBoardSession:
    session_id: str
    run_id: str
    relative_logdir: str
    logdir: Path
    port: int
    expires_at: int
    last_access: float
    process: object


class TensorBoardProcessManager:
    def __init__(
        self,
        root: Path,
        *,
        idle_timeout_seconds: int,
        clock: Callable[[], float] = time.time,
        process_factory=subprocess.Popen,
        port_allocator=None,
    ):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.idle_timeout_seconds = idle_timeout_seconds
        self.clock = clock
        self.process_factory = process_factory
        self.port_allocator = port_allocator or _allocate_port
        self.sessions: dict[str, TensorBoardSession] = {}

    def resolve_logdir(self, relative_logdir: str) -> Path:
        if (
            not relative_logdir
            or "\\" in relative_logdir
            or Path(relative_logdir).is_absolute()
            or any(part in {"", ".", ".."} for part in relative_logdir.split("/"))
        ):
            raise SessionPathInvalid("TensorBoard log directory is invalid")
        resolved = (self.root / Path(*relative_logdir.split("/"))).resolve()
        try:
            resolved.relative_to(self.root)
        except ValueError as error:
            raise SessionPathInvalid("TensorBoard log directory escapes the fixed root") from error
        return resolved

    def get_or_start(
        self,
        *,
        session_id: str,
        run_id: str,
        relative_logdir: str,
        expires_at: int,
    ) -> TensorBoardSession:
        now = self.clock()
        existing = self.sessions.get(session_id)
        if existing is not None:
            if existing.run_id != run_id or existing.relative_logdir != relative_logdir:
                raise SessionRunMismatch("TensorBoard session Run does not match")
            if existing.process.poll() is None and now < existing.expires_at:
                existing.last_access = now
                return existing
            self._stop(existing)
            self.sessions.pop(session_id, None)

        logdir = self.resolve_logdir(relative_logdir)
        logdir.mkdir(parents=True, exist_ok=True)
        port = int(self.port_allocator())
        command = [
            sys.executable,
            "-m",
            "tensorboard.main",
            "--logdir",
            str(logdir),
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--path_prefix",
            f"/sessions/{session_id}",
        ]
        process = self.process_factory(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        session = TensorBoardSession(
            session_id=session_id,
            run_id=run_id,
            relative_logdir=relative_logdir,
            logdir=logdir,
            port=port,
            expires_at=int(expires_at),
            last_access=now,
            process=process,
        )
        self.sessions[session_id] = session
        return session

    def cleanup(self) -> int:
        now = self.clock()
        expired = [
            session_id
            for session_id, session in self.sessions.items()
            if now >= session.expires_at or now - session.last_access >= self.idle_timeout_seconds
        ]
        for session_id in expired:
            self._stop(self.sessions.pop(session_id))
        return len(expired)

    def close(self) -> None:
        for session in list(self.sessions.values()):
            self._stop(session)
        self.sessions.clear()

    @staticmethod
    def _stop(session: TensorBoardSession) -> None:
        if session.process.poll() is not None:
            return
        session.process.terminate()
        try:
            session.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            session.process.kill()
            session.process.wait(timeout=5)


def _allocate_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])
