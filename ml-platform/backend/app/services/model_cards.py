"""Generated model-card evidence and versioned operational guidance."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import math
import uuid

from app.models.artifact import Artifact
from app.models.model_registry import (
    DeploymentRevision,
    DeploymentTarget,
    InferenceDeployment,
    ModelCard,
    ModelVersion,
)


_SYSTEM_FIELDS = frozenset({
    "training_data_lineage", "source_artifact_ids", "input_schema",
    "output_schema", "metrics", "approval_history", "approval_status",
    "release_status", "risk_notes", "intended_use", "limitations",
})
_EXPORT_FIELDS = (
    "id", "model_version_id", "training_data_lineage", "source_artifact_ids",
    "input_schema", "output_schema", "metrics", "approval_history",
    "approval_status", "release_status", "risk_notes", "intended_use",
    "limitations", "operational_guidance", "guidance_revision", "created_at",
    "updated_at",
)
_LINEAGE_FIELDS = frozenset({
    "source", "training_job_id", "dataset_artifact_id", "experiment_id",
})


def _as_text(value) -> str:
    return "" if value is None else str(value)


def _timestamp(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc).isoformat()
    return value.astimezone(timezone.utc).isoformat()


def _json_value(value):
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        return _timestamp(value)
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    return deepcopy(value)


class ModelCardError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class ModelCardService:
    @staticmethod
    def _version(db, version_or_id) -> ModelVersion:
        if isinstance(version_or_id, ModelVersion):
            return version_or_id
        try:
            version_id = uuid.UUID(str(version_or_id))
        except (TypeError, ValueError, AttributeError):
            raise ModelCardError("MODEL_CARD_VERSION_NOT_FOUND") from None
        version = db.get(ModelVersion, version_id)
        if version is None:
            raise ModelCardError("MODEL_CARD_VERSION_NOT_FOUND")
        return version

    @staticmethod
    def _lineage(db, version: ModelVersion) -> dict[str, object]:
        artifact = db.get(Artifact, version.source_artifact_id)
        metadata = artifact.metadata_ if artifact is not None else {}
        metadata = metadata if isinstance(metadata, dict) else {}
        lineage = {}
        for key in _LINEAGE_FIELDS:
            if key not in metadata:
                continue
            value = metadata.get(key)
            if isinstance(value, float) and not math.isfinite(value):
                continue
            if value is None or isinstance(value, (str, int, float, bool)):
                lineage[key] = deepcopy(value)
        return lineage

    @staticmethod
    def _source_artifact_ids(version: ModelVersion) -> list[str]:
        values = []
        for artifact_id in (version.source_artifact_id, version.onnx_artifact_id):
            if artifact_id is not None and str(artifact_id) not in values:
                values.append(str(artifact_id))
        return values

    @staticmethod
    def _approval_entry(version: ModelVersion) -> dict[str, object]:
        return {
            "status": version.approval_status,
            "comment": _as_text(version.approval_comment),
            "approved_by_id": (
                str(version.approved_by_id) if version.approved_by_id is not None else None
            ),
            "approved_at": _timestamp(version.approved_at),
        }

    @staticmethod
    def _release_status(db, version: ModelVersion) -> str:
        deployed = db.query(InferenceDeployment.id).filter(
            InferenceDeployment.model_version_id == version.id,
        ).first() is not None
        if deployed:
            return "released"
        stable_target = db.query(DeploymentTarget.id).join(
            DeploymentRevision,
            DeploymentTarget.revision_id == DeploymentRevision.id,
        ).filter(
            DeploymentTarget.model_version_id == version.id,
            DeploymentRevision.status == "stable",
        ).first() is not None
        return "released" if stable_target else "unreleased"

    def _system_values(self, db, version: ModelVersion) -> dict[str, object]:
        return {
            "training_data_lineage": self._lineage(db, version),
            "source_artifact_ids": self._source_artifact_ids(version),
            "input_schema": deepcopy(version.feature_schema or []),
            "output_schema": deepcopy(version.output_schema or {}),
            "metrics": deepcopy(version.metrics or {}),
            "approval_status": version.approval_status,
            "release_status": self._release_status(db, version),
        }

    def ensure_for_version(self, db, version_or_id) -> ModelCard:
        version = self._version(db, version_or_id)
        card = db.query(ModelCard).filter(
            ModelCard.model_version_id == version.id,
        ).with_for_update().first()
        values = self._system_values(db, version)
        entry = self._approval_entry(version)
        if card is None:
            card = ModelCard(
                model_version_id=version.id,
                approval_history=[entry],
                risk_notes="",
                intended_use="",
                limitations="",
                operational_guidance="",
                guidance_revision=1,
                **values,
            )
            db.add(card)
        else:
            for name, value in values.items():
                setattr(card, name, value)
            history = list(card.approval_history or [])
            if not history or history[-1] != entry:
                history.append(entry)
                card.approval_history = history
        db.flush()
        return card

    @staticmethod
    def _card(db, card_id) -> ModelCard:
        try:
            parsed_id = uuid.UUID(str(card_id))
        except (TypeError, ValueError, AttributeError):
            raise ModelCardError("MODEL_CARD_NOT_FOUND") from None
        card = db.query(ModelCard).filter(ModelCard.id == parsed_id).with_for_update().first()
        if card is None:
            raise ModelCardError("MODEL_CARD_NOT_FOUND")
        return card

    def update_guidance(self, db, card_id, operational_guidance) -> ModelCard:
        if not isinstance(operational_guidance, str):
            raise ModelCardError("MODEL_CARD_GUIDANCE_INVALID")
        normalized = operational_guidance.strip()
        if len(normalized) > 16000:
            raise ModelCardError("MODEL_CARD_GUIDANCE_INVALID")
        card = self._card(db, card_id)
        if card.operational_guidance != normalized:
            card.operational_guidance = normalized
            card.guidance_revision = int(card.guidance_revision or 1) + 1
        db.flush()
        return card

    def update(self, db, card_id, fields: dict[str, object]) -> ModelCard:
        if not isinstance(fields, dict):
            raise ModelCardError("MODEL_CARD_UPDATE_INVALID")
        protected = set(fields) & _SYSTEM_FIELDS
        if protected:
            raise ModelCardError("MODEL_CARD_SYSTEM_FIELD_IMMUTABLE")
        if set(fields) != {"operational_guidance"}:
            raise ModelCardError("MODEL_CARD_UPDATE_INVALID")
        return self.update_guidance(db, card_id, fields["operational_guidance"])

    def export(self, db, card_id) -> dict[str, object]:
        card = self._card(db, card_id)
        return {name: _json_value(getattr(card, name)) for name in _EXPORT_FIELDS}
