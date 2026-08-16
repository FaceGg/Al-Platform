"""Fail-closed ownership resolvers for user-private resources."""

import uuid

from app.models.platform_models import AnnotationResult, AnnotationTask
from app.services.project_access import ProjectAccessService


class ResourceAccessError(Exception):
    def __init__(self, code: str = "RESOURCE_NOT_FOUND"):
        super().__init__(code)
        self.code = code


def _resource_uuid(resource_id) -> uuid.UUID:
    try:
        return resource_id if isinstance(resource_id, uuid.UUID) else uuid.UUID(str(resource_id))
    except (TypeError, ValueError, AttributeError) as error:
        raise ResourceAccessError() from error


class ResourceAccessService:
    def require_owned(self, db, model, resource_id, user_id):
        if not hasattr(model, "id") or not hasattr(model, "owner_id"):
            raise ResourceAccessError()
        row = db.query(model).filter(model.id == _resource_uuid(resource_id)).first()
        if row is None or row.owner_id != user_id:
            raise ResourceAccessError()
        return row

    def require_annotation_sample(self, db, sample_id, user_id):
        sample = db.query(AnnotationResult).filter(
            AnnotationResult.id == _resource_uuid(sample_id)
        ).first()
        if sample is None:
            raise ResourceAccessError()
        task = db.query(AnnotationTask).filter(
            AnnotationTask.id == sample.task_id
        ).first()
        if task is None or task.owner_id != user_id:
            raise ResourceAccessError()
        return sample, task

    def require_owned_project_resource(
        self,
        db,
        model,
        resource_id,
        user_id,
        permission: str,
    ):
        if not hasattr(model, "id") or not hasattr(model, "project_id"):
            raise ResourceAccessError()
        row = db.query(model).filter(model.id == _resource_uuid(resource_id)).first()
        if row is None or row.project_id is None:
            raise ResourceAccessError()
        try:
            ProjectAccessService().require(db, row.project_id, user_id, permission)
        except ValueError as error:
            raise ResourceAccessError() from error
        return row
