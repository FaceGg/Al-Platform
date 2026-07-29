"""Capture a redacted acceptance-host environment manifest."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Callable, Mapping
from uuid import UUID, uuid4

from pydantic import SecretStr

from app.api.auth import create_access_token, pwd_context
from app.config import settings
from app.database import SessionLocal
from app.models.access import ProjectMember
from app.models.notifications import NotificationEndpoint
from app.models.project import Project
from app.models.user import User
from app.services.notification_crypto import encrypt_config
from tools.redaction import redact_text


ALLOWED_CONFIGURATION_KEYS = (
    "APP_MODE",
    "TASK_BACKEND",
    "ARTIFACT_STORAGE_BACKEND",
)
PACKAGE_NAMES = ("fastapi", "sqlalchemy", "alembic", "celery")

_WEB_CONTEXT_ROLES = ("owner", "editor", "operator", "viewer", "outsider")
_WEB_CONTEXT_KEYS = frozenset(
    {"schema_version", "project_id", "endpoint_id", "user_ids", "tokens"},
)


def redact(value: str) -> str:
    """Remove URL userinfo and conventional secret assignments from text."""
    return redact_text(value)


def _command_output(command: list[str]) -> str:
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return "unavailable"
    if completed.returncode != 0:
        return "unavailable"
    return redact(completed.stdout.strip())


def _memory_bytes() -> int | None:
    try:
        page_size = os.sysconf("SC_PAGE_SIZE")
        pages = os.sysconf("SC_PHYS_PAGES")
    except (AttributeError, OSError, ValueError):
        return None
    return int(page_size) * int(pages)


def _package_versions() -> dict[str, str]:
    versions = {}
    for package in PACKAGE_NAMES:
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = "unavailable"
    return versions


def collect_environment(environment: Mapping[str, str] | None = None) -> dict[str, object]:
    """Collect only explicitly allowlisted configuration, never secret values."""
    values = environment if environment is not None else os.environ
    allowed = {
        name: redact(str(values[name]))
        for name in ALLOWED_CONFIGURATION_KEYS
        if name in values
    }
    return {
        "runtime": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "cpu_count": os.cpu_count(),
            "memory_bytes": _memory_bytes(),
        },
        "packages": _package_versions(),
        "git": {"commit": _command_output(["git", "rev-parse", "HEAD"])},
        "migration": {"current": _command_output(["alembic", "current"])},
        "container": {
            "image_digest": redact(values.get("ACCEPTANCE_IMAGE_DIGEST", "unavailable")),
            "compose": _command_output(["docker", "compose", "ps", "--format", "json"]),
        },
        "configuration": allowed,
    }


def _write_private_json(path: Path, value: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    try:
        path.chmod(0o600)
    except OSError:
        # Windows ACLs may not model POSIX modes; the caller still owns an isolated path.
        pass


def _validated_web_context(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != _WEB_CONTEXT_KEYS:
        raise ValueError("web security context is invalid")
    if value.get("schema_version") != 1:
        raise ValueError("web security context is invalid")
    for key in ("project_id", "endpoint_id"):
        try:
            UUID(str(value.get(key, "")))
        except (TypeError, ValueError):
            raise ValueError("web security context is invalid") from None
    for key in ("user_ids", "tokens"):
        entries = value.get(key)
        if not isinstance(entries, dict) or set(entries) != set(_WEB_CONTEXT_ROLES):
            raise ValueError("web security context is invalid")
        for role in _WEB_CONTEXT_ROLES:
            entry = entries.get(role)
            if not isinstance(entry, str) or not entry:
                raise ValueError("web security context is invalid")
            if key == "user_ids":
                try:
                    UUID(entry)
                except ValueError:
                    raise ValueError("web security context is invalid") from None
    return value


def _delete_web_security_resources(
    context: Mapping[str, object],
    *,
    session_factory: Callable[[], object],
) -> None:
    project_id = UUID(str(context["project_id"]))
    user_ids = [UUID(str(value)) for value in dict(context["user_ids"]).values()]
    db = session_factory()
    try:
        db.query(NotificationEndpoint).filter(
            NotificationEndpoint.project_id == project_id,
        ).delete(synchronize_session=False)
        db.query(ProjectMember).filter(ProjectMember.project_id == project_id).delete(
            synchronize_session=False,
        )
        db.query(Project).filter(Project.id == project_id).delete(
            synchronize_session=False,
        )
        db.query(User).filter(User.id.in_(user_ids)).delete(synchronize_session=False)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def create_web_security_context(
    output: Path,
    *,
    session_factory: Callable[[], object] = SessionLocal,
    notification_master_key: SecretStr | None = None,
    token_factory: Callable[[dict[str, str]], str] = create_access_token,
) -> dict[str, object]:
    """Seed an isolated project and issue real JWTs for the web-security gate."""
    master_key = notification_master_key or settings.resolved_notification_master_key
    if master_key is None:
        raise RuntimeError("notification master key is unavailable")

    prefix = f"week12-web-security-{uuid4().hex}"
    db = session_factory()
    context: dict[str, object] | None = None
    try:
        users = {
            role: User(
                username=f"{prefix}-{role}",
                password_hash=pwd_context.hash(uuid4().hex),
                role="engineer",
            )
            for role in _WEB_CONTEXT_ROLES
        }
        db.add_all(users.values())
        db.flush()

        project = Project(name=f"{prefix}-project", owner_id=users["owner"].id)
        db.add(project)
        db.flush()
        db.add_all(
            ProjectMember(
                project_id=project.id,
                user_id=users[role].id,
                role=role,
                created_by=users["owner"].id,
            )
            for role in ("editor", "operator", "viewer")
        )
        endpoint = NotificationEndpoint(
            project_id=project.id,
            kind="in_app",
            name=f"{prefix}-endpoint",
            destination_hint="acceptance in-app recipient",
            encrypted_config=encrypt_config(
                {"recipient_user_ids": [str(users["owner"].id)]},
                master_key,
            ),
            created_by_id=users["owner"].id,
        )
        db.add(endpoint)
        db.flush()
        context = {
            "schema_version": 1,
            "project_id": str(project.id),
            "endpoint_id": str(endpoint.id),
            "user_ids": {role: str(user.id) for role, user in users.items()},
            "tokens": {
                role: token_factory({"sub": str(user.id)})
                for role, user in users.items()
            },
        }
        _validated_web_context(context)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    try:
        _write_private_json(output, context)
    except Exception:
        _delete_web_security_resources(context, session_factory=session_factory)
        raise
    return context


def cleanup_web_security_context(
    context_path: Path,
    *,
    session_factory: Callable[[], object] = SessionLocal,
) -> None:
    """Delete only the project and users generated by ``create_web_security_context``."""
    try:
        context = _validated_web_context(
            json.loads(context_path.read_text(encoding="utf-8")),
        )
        _delete_web_security_resources(context, session_factory=session_factory)
    finally:
        context_path.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command",
        choices=("environment", "web-context", "web-context-cleanup"),
        nargs="?",
        default="environment",
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--context", type=Path)
    args = parser.parse_args(argv)
    if args.command == "environment":
        if args.output is None:
            parser.error("--output is required for environment")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(collect_environment(), ensure_ascii=True, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    elif args.command == "web-context":
        if args.output is None:
            parser.error("--output is required for web-context")
        create_web_security_context(args.output)
    else:
        if args.context is None:
            parser.error("--context is required for web-context-cleanup")
        cleanup_web_security_context(args.context)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
