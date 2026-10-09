"""Week 15 image build service.

The build path is gated by ``settings.image_build_approved``: with the gate
closed (the Week 15 baseline), the API returns 501 ``IMAGE_BUILD_NOT_APPROVED``
and this module only freezes the adapter contract. When a rootless builder
(Kaniko or equivalent) is approved later, the adapter executes through the Week
14 executor with a hardened manifest — never DinD, never a host docker socket.
"""

from __future__ import annotations

import re
import uuid

from sqlalchemy.orm import Session

from app.models.developer_resources import ContainerImage, ImageBuild
from app.services.kubernetes_client import redact_text

BUILDER_DIGEST_PATTERN = re.compile(r"^[^@\s]+@sha256:[a-f0-9]{64}$")


class ImageBuildError(Exception):
    def __init__(self, code: str, message: str = "", status: int = 422):
        super().__init__(message or code)
        self.code = code
        self.message = redact_text(message)
        self.status = status


def redact_build_log(text: str) -> str:
    return redact_text(text or "")


def validate_builder_image(builder_image: str) -> str:
    if not BUILDER_DIGEST_PATTERN.match(builder_image or ""):
        raise ImageBuildError("IMAGE_BUILDER_INVALID", "builder image must be a digest reference")
    return builder_image


def validate_registry_credential_ref(credential_ref: str) -> str:
    if not (credential_ref or "").startswith("env:") and not (credential_ref or "").startswith("file:"):
        raise ImageBuildError(
            "IMAGE_CREDENTIAL_INVALID",
            "registry credentials must be env:NAME or file:/path references, never material",
        )
    return credential_ref


def build_builder_manifest(
    *,
    build_id,
    builder_image: str,
    destination: str,
    registry_credential_ref: str,
    namespace: str,
    labels: dict,
) -> dict:
    """Security-hardened builder Job: no privileges, no socket, no volumes."""
    validate_builder_image(builder_image)
    validate_registry_credential_ref(registry_credential_ref)
    container = {
        "name": "linkraft-builder",
        "image": builder_image,
        "args": [f"--destination={destination}", "--no-push-fallback"],
        "env": [{"name": "REGISTRY_CREDENTIAL_REF", "value": registry_credential_ref}],
        "resources": {"requests": {"cpu": "1", "memory": "1Gi"}},
    }
    pod_spec = {
        "restartPolicy": "Never",
        "automountServiceAccountToken": False,
        "containers": [container],
    }
    return {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {
            "name": f"lr-build-{str(build_id).replace('-', '')[:12]}",
            "namespace": namespace,
            "labels": dict(labels),
        },
        "spec": {
            "backoffLimit": 0,
            "manualSelector": True,
            "selector": {"matchLabels": {"linkraft.io/build-id": str(build_id).replace("-", "")[:32]}},
            "template": {"metadata": {"labels": dict(labels)}, "spec": pod_spec},
        },
    }


class ImageBuildAdapter:
    """Frozen adapter interface: a Kaniko (or equivalent) backend implements
    these three methods; Week 15 ships the recording fake only."""

    def submit(self, manifest: dict) -> dict: ...

    def status(self, handle: dict) -> dict: ...

    def logs(self, handle: dict, cursor: int, limit_bytes: int) -> str: ...


class FakeBuildAdapter(ImageBuildAdapter):
    """Records submissions and reports success with a deterministic digest."""

    def __init__(self, output_digest: str):
        self.output_digest = output_digest
        self.submitted: list[dict] = []

    def submit(self, manifest: dict) -> dict:
        self.submitted.append(manifest)
        return {"handle": manifest["metadata"]["name"]}

    def status(self, handle: dict) -> dict:
        return {"status": "succeeded", "output_digest": self.output_digest}

    def logs(self, handle: dict, cursor: int, limit_bytes: int) -> str:
        return "build ok"


def record_build(
    db: Session,
    *,
    project_id,
    registered_by,
    builder_image: str,
    destination: str,
    source_artifact_id=None,
) -> ImageBuild:
    destination_registry, destination_repository = destination.split("/", 1)
    destination_digest = destination.split("@")[1]
    build = ImageBuild(
        project_id=project_id,
        source_artifact_id=source_artifact_id,
        builder_image=builder_image,
        status="succeeded",
    )
    db.add(build)
    db.flush()
    output = (
        db.query(ContainerImage)
        .filter(
            ContainerImage.registry == destination_registry,
            ContainerImage.repository == destination_repository.split("@")[0],
            ContainerImage.digest == destination_digest,
        )
        .first()
    )
    if output is None:
        output = ContainerImage(
            project_id=project_id,
            registry=destination_registry,
            repository=destination_repository.split("@")[0],
            digest=destination_digest,
            visibility="project",
            scan_status="pending",
            source="build",
            registered_by=registered_by,
        )
        db.add(output)
        db.flush()
    build.output_image_id = output.id
    db.commit()
    return build


def new_build_id() -> uuid.UUID:
    return uuid.uuid4()
