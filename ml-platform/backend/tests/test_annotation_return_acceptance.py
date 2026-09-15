import uuid
import pytest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.auth import get_current_user
from app.database import Base, get_db
from app.main import app
from app.models.annotator import AnnotatorSubjectMapping
from app.models.data_version import DatasetSample, DatasetSchemaColumn, DatasetVersion
from app.models.labeling import (
    AnnotationAssignment,
    AnnotationAssignmentSample,
    AnnotationReturnBatch,
    LabelColumn,
    LabelSchema,
)
from app.models.notifications import InAppNotification
from app.models.platform_models import GenericAnnotationTask
from app.models.project import Project
from app.models.user import User
from app.services.annotation_returns import AnnotationReturnError, accept_return_batch, reject_return_batch


def test_return_batch_cursor_must_belong_to_requested_project():
    from app.services.annotation_returns import list_return_batches

    engine, db, admin, _, project, _, _, batch = _fixture()
    try:
        other = Project(name="Other return project", owner_id=admin.id)
        db.add(other)
        db.commit()
        with pytest.raises(AnnotationReturnError, match="INVALID_CURSOR"):
            list_return_batches(db, other.id, cursor=str(batch.id))
        assert list_return_batches(db, project.id)["items"][0]["id"] == str(batch.id)
    finally:
        db.close()
        engine.dispose()


def _fixture(source_result_type=None):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()

    admin = User(username=f"return-admin-{uuid.uuid4().hex}", password_hash="hash")
    annotator_user = User(username=f"return-annotator-{uuid.uuid4().hex}", password_hash="hash")
    db.add_all([admin, annotator_user])
    db.flush()
    project = Project(name="Return acceptance", owner_id=admin.id)
    db.add(project)
    db.flush()
    source = DatasetVersion(
        project_id=project.id,
        operator_id=admin.id,
        version=1,
        row_count=2,
        column_count=2 if source_result_type else 1,
        content_hash="sha256:source",
        schema_hash="sha256:source-schema",
        parse_contract={"source_format": "csv"},
    )
    db.add(source)
    db.flush()
    db.add(DatasetSchemaColumn(
        dataset_version_id=source.id,
        name="feature",
        position=0,
        dtype="int64",
        nullable=False,
    ))
    previous_labels = {"result": "old" if source_result_type in {"string", "object"} else 1} if source_result_type else {}
    if source_result_type:
        db.add(DatasetSchemaColumn(
            dataset_version_id=source.id, name="result", position=1,
            dtype=source_result_type, nullable=False,
        ))
    db.add_all([
        DatasetSample(dataset_version_id=source.id, sample_id="sample-1", row_index=0, values={"feature": 1, **previous_labels}),
        DatasetSample(dataset_version_id=source.id, sample_id="sample-2", row_index=1, values={"feature": 2, **previous_labels}),
    ])
    schema = LabelSchema(project_id=project.id, name="return-labels", version=1, status="active")
    db.add(schema)
    db.flush()
    db.add(LabelColumn(
        schema_id=schema.id,
        machine_key="result",
        display_name="Result",
        ordinal=0,
        value_type="string",
        required=True,
    ))
    task = GenericAnnotationTask(
        project_id=project.id,
        dataset_version_id=source.id,
        label_schema_id=schema.id,
        owner_id=admin.id,
        mode="manual",
        status="awaiting_annotation",
        task_revision=4,
        sample_scope={"kind": "ids", "sample_ids": ["sample-1", "sample-2"]},
        task_snapshot={"sample_ids": ["sample-1", "sample-2"]},
    )
    db.add(task)
    db.flush()
    subject_id = uuid.uuid4()
    db.add(AnnotatorSubjectMapping(subject_id=subject_id, platform_principal_id=annotator_user.id, created_by=admin.id))
    assignment = AnnotationAssignment(
        task_id=task.id,
        annotator_subject_id=subject_id,
        sample_scope={"kind": "ids", "sample_ids": ["sample-1", "sample-2"]},
        scope_hash="sha256:return-scope",
        state="returned_pending_acceptance",
        task_revision=4,
        last_edit_revision=4,
        created_by=admin.id,
    )
    db.add(assignment)
    db.flush()
    db.add_all([
        AnnotationAssignmentSample(assignment_id=assignment.id, sample_id="sample-1", revision_no=4, values={"result": "pass"}),
        AnnotationAssignmentSample(assignment_id=assignment.id, sample_id="sample-2", revision_no=4, values={"result": "fail"}),
    ])
    batch = AnnotationReturnBatch(
        assignment_id=assignment.id,
        task_revision=4,
        scope_hash=assignment.scope_hash,
        idempotency_key="return-primary",
        state="pending",
    )
    db.add(batch)
    db.commit()
    return engine, db, admin, annotator_user, project, source, assignment, batch


@pytest.mark.parametrize("source_dtype", ["string", "object"])
def test_return_overwrites_same_type_label_in_new_version_only(source_dtype):
    engine, db, admin, _, _, source, _, batch = _fixture(source_dtype)
    try:
        accepted = accept_return_batch(db, batch.id, expected_revision=4, actor=admin)
        columns = db.query(DatasetSchemaColumn).filter_by(dataset_version_id=accepted.id).order_by(DatasetSchemaColumn.position).all()
        assert [(column.name, column.dtype) for column in columns] == [("feature", "int64"), ("result", source_dtype)]
        assert accepted.column_count == 2
        assert db.query(DatasetSample).filter_by(dataset_version_id=accepted.id, sample_id="sample-1").one().values == {"feature": 1, "result": "pass"}
        assert db.query(DatasetSample).filter_by(dataset_version_id=source.id, sample_id="sample-1").one().values == {"feature": 1, "result": "old"}
        repeated = accept_return_batch(db, batch.id, expected_revision=4, actor=admin)
        assert repeated.id == accepted.id
        assert db.query(DatasetVersion).count() == 2
    finally:
        db.close()
        engine.dispose()


def test_return_rejects_same_name_different_type_without_partial_version():
    engine, db, admin, _, _, source, _, batch = _fixture("int64")
    try:
        with pytest.raises(AnnotationReturnError) as error:
            accept_return_batch(db, batch.id, expected_revision=4, actor=admin)
        assert error.value.code == "RETURN_LABEL_COLUMN_TYPE_MISMATCH"
        assert db.query(DatasetVersion).count() == 1
        assert db.get(AnnotationReturnBatch, batch.id).state == "pending"
        assert db.query(DatasetSample).filter_by(dataset_version_id=source.id, sample_id="sample-1").one().values == {"feature": 1, "result": 1}
    finally:
        db.close()
        engine.dispose()


def test_return_batch_list_is_project_scoped_cursor_paged_and_stable():
    engine, db, admin, _annotator, project, _source, assignment, batch = _fixture()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: admin
    client = TestClient(app)
    try:
        db.add(AnnotationReturnBatch(
            assignment_id=assignment.id,
            task_revision=4,
            scope_hash=assignment.scope_hash,
            idempotency_key="return-secondary",
            state="pending",
        ))
        db.commit()
        first = client.get(f"/api/projects/{project.id}/annotation-return-batches?limit=1")
        assert first.status_code == 200, first.text
        assert len(first.json()["items"]) == 1
        assert first.json()["next_cursor"]
        second = client.get(
            f"/api/projects/{project.id}/annotation-return-batches?limit=1&cursor={first.json()['next_cursor']}"
        )
        assert second.status_code == 200, second.text
        assert second.json()["items"][0]["id"] != first.json()["items"][0]["id"]
        repeated = client.get(f"/api/projects/{project.id}/annotation-return-batches?limit=1")
        assert repeated.json()["items"][0]["id"] == first.json()["items"][0]["id"]
        assert batch.id
    finally:
        app.dependency_overrides.clear()
        db.close()
        engine.dispose()


def test_return_diff_is_sample_id_aligned_and_cursor_paged():
    engine, db, admin, _annotator, _project, _source, _assignment, batch = _fixture()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: admin
    client = TestClient(app)
    try:
        response = client.get(f"/api/annotation-return-batches/{batch.id}/diff?limit=1")
        assert response.status_code == 200, response.text
        body = response.json()
        assert len(body["items"]) == 1
        assert body["items"][0]["sample_id"] in {"sample-1", "sample-2"}
        assert body["items"][0]["source_values"] == {"feature": 1} or body["items"][0]["source_values"] == {"feature": 2}
        assert body["items"][0]["label_values"] in ({"result": "pass"}, {"result": "fail"})
        assert body["next_cursor"]
        next_page = client.get(
            f"/api/annotation-return-batches/{batch.id}/diff?limit=1&cursor={body['next_cursor']}"
        )
        assert next_page.status_code == 200, next_page.text
        assert next_page.json()["items"][0]["sample_id"] != body["items"][0]["sample_id"]
    finally:
        app.dependency_overrides.clear()
        db.close()
        engine.dispose()


def test_acceptance_creates_new_dataset_version_without_mutating_source():
    engine, db, admin, _annotator, _project, source, _assignment, batch = _fixture()
    try:
        accepted = accept_return_batch(db, batch.id, expected_revision=4, actor=admin)
        assert accepted.status == "ready"
        assert accepted.id != source.id
        assert [column.name for column in db.query(DatasetSchemaColumn).filter_by(dataset_version_id=source.id).order_by(DatasetSchemaColumn.position)] == ["feature"]
        assert [column.name for column in db.query(DatasetSchemaColumn).filter_by(dataset_version_id=accepted.id).order_by(DatasetSchemaColumn.position)] == ["feature", "result"]
        assert db.query(DatasetSample).filter_by(dataset_version_id=source.id, sample_id="sample-1").one().values == {"feature": 1}
        assert db.query(DatasetSample).filter_by(dataset_version_id=accepted.id, sample_id="sample-1").one().values == {"feature": 1, "result": "pass"}
        assert db.get(AnnotationReturnBatch, batch.id).state == "accepted"
    finally:
        db.close()
        engine.dispose()


def test_rejected_return_requires_reason_and_notifies_mapped_annotator():
    engine, db, admin, annotator_user, _project, _source, _assignment, batch = _fixture()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: admin
    client = TestClient(app)
    try:
        invalid = client.post(f"/api/annotation-return-batches/{batch.id}/return", json={"task_revision": 4, "reason": "   "})
        assert invalid.status_code == 422, invalid.text
        rejected = reject_return_batch(db, batch.id, expected_revision=4, reason="result needs correction", actor=admin)
        assert rejected.state == "returned_for_changes"
        notification = db.query(InAppNotification).filter(
            InAppNotification.recipient_user_id == annotator_user.id,
            InAppNotification.event_type == "annotation_return.returned_for_changes",
        ).one()
        assert notification.payload == {"return_batch_id": str(batch.id)}
        assert "result" not in notification.body.lower()
    finally:
        app.dependency_overrides.clear()
        db.close()
        engine.dispose()
