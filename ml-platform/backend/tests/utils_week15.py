"""Shared row factories for the Week 15 developer-resource test modules."""

import sys

sys.path.insert(0, ".")

from datetime import datetime, timezone  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models.developer_resources import (  # noqa: E402
    ContainerImage,
    GpuResourceClass,
    NotebookSession,
)
from tests.utils_week14 import ensure_active_cluster, ensure_project, ensure_user  # noqa: E402

TEST_DIGEST = "sha256:" + "b" * 64


def ensure_image(
    project_id,
    registered_by,
    *,
    registry: str = "registry.local",
    repository: str = "w15/notebook-base",
    digest: str | None = None,
    visibility: str = "project",
    scan_status: str = "passed",
) -> ContainerImage:
    digest = digest or TEST_DIGEST
    db = SessionLocal()
    try:
        image = (
            db.query(ContainerImage)
            .filter(
                ContainerImage.registry == registry,
                ContainerImage.repository == repository,
                ContainerImage.digest == digest,
            )
            .first()
        )
        if image is None:
            image = ContainerImage(
                project_id=project_id if visibility == "project" else None,
                registry=registry,
                repository=repository,
                digest=digest,
                visibility=visibility,
                scan_status=scan_status,
                source="manual_registry",
                registered_by=registered_by,
            )
            db.add(image)
            db.commit()
            db.refresh(image)
        return image
    finally:
        db.close()


def image_ref(image: ContainerImage) -> str:
    return f"{image.registry}/{image.repository}@{image.digest}"


def ensure_gpu_class(cluster_id, name: str = "w15-gpu", **overrides) -> GpuResourceClass:
    db = SessionLocal()
    try:
        gpu_class = (
            db.query(GpuResourceClass)
            .filter(GpuResourceClass.cluster_id == cluster_id, GpuResourceClass.name == name)
            .first()
        )
        if gpu_class is None:
            payload = {
                "cluster_id": cluster_id,
                "name": name,
                "resource_name": "nvidia.com/gpu",
                "memory_gb": 16,
                "vendor": "nvidia",
                "node_selector_json": {"linkraft.io/gpu-pool": name},
                "tolerations_json": [{"key": "nvidia.com/gpu", "operator": "Exists", "effect": "NoSchedule"}],
                "max_per_session": 2,
                "status": "active",
                "allocatable_snapshot_json": {"allocatable": 4},
                "snapshotted_at": datetime.now(timezone.utc).replace(tzinfo=None),
            }
            payload.update(overrides)
            gpu_class = GpuResourceClass(**payload)
            db.add(gpu_class)
            db.commit()
            db.refresh(gpu_class)
        return gpu_class
    finally:
        db.close()


def notebook_payload(cluster_id, image=None, **overrides) -> dict:
    body = {
        "cluster_id": str(cluster_id),
        "image_ref": image_ref(image) if image is not None else "",
        "resources": {"cpu_cores": 1, "memory_gb": 1},
        "idle_timeout_seconds": 3600,
    }
    body.update(overrides)
    return body


def cleanup_week15_rows() -> None:
    """Drop all Week 15 rows so reruns start clean (the suite shares one
    file-backed SQLite database across pytest invocations)."""
    db = SessionLocal()
    try:
        from app.models.developer_resources import ImageBuild

        db.query(NotebookSession).delete(synchronize_session=False)
        db.query(ImageBuild).delete(synchronize_session=False)
        db.query(ContainerImage).delete(synchronize_session=False)
        db.query(GpuResourceClass).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()
