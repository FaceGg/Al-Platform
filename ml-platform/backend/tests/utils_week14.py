"""Shared row factories for the Week 14 Kubernetes job test modules.

Service/API tests create users, projects and active clusters directly so the
executor paths under test stay on the same code path as production while the
cluster itself is replaced by ``FakeKubernetesClient``.
"""

import sys

sys.path.insert(0, ".")

from datetime import datetime, timezone  # noqa: E402

from app.api.auth import pwd_context  # noqa: E402
from app.config import settings  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.models.cloud_resources import (  # noqa: E402
    KubernetesCluster,
    KubernetesCredentialRef,
    KubernetesNamespace,
)
from app.models.access import ProjectMember  # noqa: E402
from app.models.kubernetes_execution import KubernetesJobRun  # noqa: E402
from app.models.operation import DurableOperation  # noqa: E402
from app.models.project import Project  # noqa: E402
from app.models.user import User  # noqa: E402

TEST_IMAGE = "registry.local/w14-demo@sha256:" + "a" * 64
TEST_ENV = {"W14_MODE": "fast"}


def ensure_user(username: str, role: str = "engineer") -> User:
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == username).first()
        if user is None:
            user = User(username=username, password_hash=pwd_context.hash("w14password"), role=role)
            db.add(user)
            db.commit()
            db.refresh(user)
        return user
    finally:
        db.close()


def ensure_project(name: str, owner_id) -> Project:
    db = SessionLocal()
    try:
        project = db.query(Project).filter(Project.name == name).first()
        if project is None:
            project = Project(name=name, description="week14 test", owner_id=owner_id)
            db.add(project)
            db.commit()
            db.refresh(project)
        return project
    finally:
        db.close()


def ensure_member(project_id, user_id, role: str) -> None:
    db = SessionLocal()
    try:
        exists = (
            db.query(ProjectMember.id)
            .filter(ProjectMember.project_id == project_id, ProjectMember.user_id == user_id)
            .first()
        )
        if exists is None:
            db.add(ProjectMember(project_id=project_id, user_id=user_id, role=role))
            db.commit()
    finally:
        db.close()


def ensure_active_cluster(name: str, project_id, owner_id, namespace: str = "w14-jobs") -> KubernetesCluster:
    """Create (or return) an active cluster row with credential ref and one registered namespace."""
    db = SessionLocal()
    try:
        cluster = (
            db.query(KubernetesCluster)
            .filter(KubernetesCluster.name == name, KubernetesCluster.project_id == project_id)
            .first()
        )
        if cluster is None:
            cluster = KubernetesCluster(
                project_id=project_id,
                name=name,
                display_name=f"cluster {name}",
                api_server_url="https://127.0.0.1:6443",
                provider="kind",
                status="active",
                kubernetes_version="v1.30.0",
                default_namespace=namespace,
                created_by=owner_id,
            )
            db.add(cluster)
            db.flush()
            db.add(KubernetesCredentialRef(cluster_id=cluster.id, secret_ref="env:W14_TEST_TOKEN"))
            db.add(
                KubernetesNamespace(
                    cluster_id=cluster.id,
                    project_id=project_id,
                    name=namespace,
                    status="active",
                    last_synced_at=datetime.now(timezone.utc),
                )
            )
            db.commit()
            db.refresh(cluster)
        return cluster
    finally:
        db.close()


def cleanup_job_rows(project_ids) -> None:
    """Drop this module's job runs and operations so reruns start clean.

    The suite shares one file-backed SQLite database across pytest runs; fixed
    idempotency keys would replay stale rows otherwise.
    """
    db = SessionLocal()
    try:
        db.query(KubernetesJobRun).filter(KubernetesJobRun.project_id.in_(list(project_ids))).delete(
            synchronize_session=False
        )
        db.query(DurableOperation).filter(DurableOperation.resource_type == "kubernetes_job").delete(
            synchronize_session=False
        )
        db.commit()
    finally:
        db.close()


def submit_payload(cluster_id, **overrides) -> dict:
    body = {
        "cluster_id": str(cluster_id),
        "image_ref": TEST_IMAGE,
        "command": ["/bin/sh", "-c"],
        "args": ["echo w14"],
        "env": dict(TEST_ENV),
        "resources": {"cpu_cores": 1, "memory_gb": 1},
        "timeout_seconds": 120,
    }
    body.update(overrides)
    return body


def apply_job_settings():
    """Point the job allowlists at the test fixtures; returns the previous values."""
    previous = (
        settings.kubernetes_job_approved_image_prefixes,
        settings.kubernetes_job_allowed_env_keys,
    )
    settings.kubernetes_job_approved_image_prefixes = ["registry.local/"]
    settings.kubernetes_job_allowed_env_keys = list(TEST_ENV)
    return previous


def restore_job_settings(previous) -> None:
    settings.kubernetes_job_approved_image_prefixes, settings.kubernetes_job_allowed_env_keys = previous
