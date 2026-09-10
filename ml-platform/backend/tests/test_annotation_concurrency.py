import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.annotator import AnnotatorAccount, ProjectAnnotatorGrant
from app.models.data_version import DatasetSample, DatasetVersion
from app.models.labeling import AnnotationAssignment, AnnotationReturnBatch, AnnotationRevision, LabelColumn, LabelSchema
from app.models.platform_models import GenericAnnotationTask
from app.models.project import Project
from app.models.user import User
from app.services.annotation_concurrency import (
    AssignmentError,
    AssignmentLockedError,
    RevisionConflict,
    create_assignments,
    confirm_assignment,
    edit_for_return,
    return_assignment,
    save_labels,
)


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def test_two_annotators_can_read_same_sample_but_stale_write_returns_full_conflict(db):
    task_id = uuid.uuid4()
    assignment_a, assignment_b = create_assignments(
        db,
        task_id=task_id,
        annotator_ids=[uuid.uuid4(), uuid.uuid4()],
        sample_scope={"kind": "ids", "sample_ids": ["s-1"]},
        actor=uuid.uuid4(),
    )

    first = save_labels(db, assignment_a.id, "s-1", {"label_a": "x", "label_b": 1}, base_revision=0)
    conflict = save_labels(db, assignment_b.id, "s-1", {"label_a": "y", "label_b": 2}, base_revision=0)

    assert first.revision_no == 1
    assert isinstance(conflict, RevisionConflict)
    assert conflict.current_values == {"label_a": "x", "label_b": 1}
    assert conflict.current_revision == 1


def test_return_is_idempotent_and_locks_assignment(db):
    assignment = _assignment(db)
    first = return_assignment(db, assignment.id, 3, assignment.scope_hash, "return-key")
    second = return_assignment(db, assignment.id, 3, assignment.scope_hash, "return-key")

    assert first.return_batch_id == second.return_batch_id
    assert db.get(AnnotationAssignment, assignment.id).state == "returned_pending_acceptance"
    with pytest.raises(AssignmentLockedError):
        save_labels(db, assignment.id, "s-1", {"label_a": "z"}, base_revision=1)


def test_edit_for_return_requires_new_revision_before_unlock(db):
    assignment = _assignment(db)
    return_assignment(db, assignment.id, 3, assignment.scope_hash, "first-key")
    edit_for_return(db, assignment.id, 3)

    with pytest.raises(AssignmentLockedError):
        return_assignment(db, assignment.id, 3, assignment.scope_hash, "second-key")

    save_labels(db, assignment.id, "s-1", {"label_a": "z", "label_b": 1}, base_revision=3)
    result = return_assignment(db, assignment.id, 4, assignment.scope_hash, "second-key")
    assert result.state == "pending"
    assert db.query(AnnotationReturnBatch).count() == 2


def _assignment(db):
    return create_assignments(
        db,
        task_id=uuid.uuid4(),
        annotator_ids=[uuid.uuid4()],
        sample_scope={"kind": "ids", "sample_ids": ["s-1"]},
        actor=uuid.uuid4(),
        initial_values={"s-1": {"label_a": "x", "label_b": 1}},
        initial_revision=3,
    )[0]


def _secure_fixture(db, *, task_status="awaiting_annotation"):
    admin = User(username=f"assignment-admin-{uuid.uuid4().hex}", password_hash="hash", role="admin")
    other = User(username=f"assignment-other-{uuid.uuid4().hex}", password_hash="hash", role="engineer")
    db.add_all([admin, other])
    db.flush()
    project = Project(name="Assignment security project", owner_id=admin.id)
    db.add(project)
    db.flush()
    version = DatasetVersion(
        project_id=project.id,
        operator_id=admin.id,
        version=1,
        row_count=1,
        column_count=1,
        content_hash="sha256:assignment-data",
        schema_hash="sha256:assignment-schema",
    )
    db.add(version)
    db.flush()
    db.add(DatasetSample(dataset_version_id=version.id, sample_id="frozen-1", row_index=0, values={"feature": 1}))
    schema = LabelSchema(project_id=project.id, name="assignment-labels", version=1, status="active")
    db.add(schema)
    db.flush()
    db.add(LabelColumn(schema_id=schema.id, machine_key="label", display_name="Label", ordinal=0, value_type="string", required=True))
    subject = uuid.uuid4()
    db.add(AnnotatorAccount(subject_id=subject, username=f"annotator-{uuid.uuid4().hex}", password_hash="hash", status="active"))
    db.add(ProjectAnnotatorGrant(project_id=project.id, subject_id=subject, status="active", granted_by=admin.id))
    task = GenericAnnotationTask(
        project_id=project.id,
        dataset_version_id=version.id,
        label_schema_id=schema.id,
        owner_id=admin.id,
        mode="manual",
        status=task_status,
        task_revision=0,
        sample_scope={"kind": "ids", "sample_ids": ["frozen-1"]},
        task_snapshot={
            "sample_ids": ["frozen-1"],
            "label_schema": {"schema_id": str(schema.id), "columns": [{"machine_key": "label", "value_type": "string", "required": True}]},
        },
    )
    db.add(task)
    db.commit()
    return admin, other, subject, task


def test_assignment_scope_must_be_within_frozen_task_snapshot(db):
    admin, _other, subject, task = _secure_fixture(db)
    with pytest.raises(AssignmentError) as error:
        create_assignments(
            db,
            task_id=task.id,
            annotator_ids=[subject],
            sample_scope={"kind": "ids", "sample_ids": ["outside-snapshot"]},
            actor=admin.id,
        )
    assert error.value.code == "SAMPLE_SCOPE_INVALID"


def test_paused_task_and_incomplete_required_labels_are_rejected(db):
    admin, _other, subject, task = _secure_fixture(db)
    assignment = create_assignments(
        db,
        task_id=task.id,
        annotator_ids=[subject],
        sample_scope={"kind": "ids", "sample_ids": ["frozen-1"]},
        actor=admin.id,
    )[0]
    task.status = "paused"
    db.commit()
    with pytest.raises(AssignmentLockedError):
        save_labels(db, assignment.id, "frozen-1", {"label": "x"}, 0, actor=admin.id)
    task.status = "awaiting_annotation"
    db.commit()
    with pytest.raises(AssignmentError) as error:
        confirm_assignment(db, assignment.id, assignment.task_revision, assignment.scope_hash)
    assert error.value.code == "LABEL_REQUIRED_MISSING"


def test_label_write_appends_revision_and_synchronizes_overlapping_assignments(db):
    admin, _other, subject, task = _secure_fixture(db)
    second_subject = uuid.uuid4()
    db.add(AnnotatorAccount(subject_id=second_subject, username=f"annotator-{uuid.uuid4().hex}", password_hash="hash", status="active"))
    db.add(ProjectAnnotatorGrant(project_id=task.project_id, subject_id=second_subject, status="active", granted_by=admin.id))
    db.commit()
    assignments = create_assignments(
        db,
        task_id=task.id,
        annotator_ids=[subject, second_subject],
        sample_scope={"kind": "ids", "sample_ids": ["frozen-1"]},
        actor=admin.id,
    )
    result = save_labels(db, assignments[0].id, "frozen-1", {"label": "x"}, 0, actor=admin.id)
    assert result.revision_no == 1
    rows = db.query(AnnotationAssignment).filter(AnnotationAssignment.task_id == task.id).all()
    assert all(db.query(AnnotationRevision).filter_by(task_id=task.id, sample_id="frozen-1", revision_no=1).count() == 1 for _ in [0])
    assert all(
        db.query(AnnotationAssignment).filter_by(id=row.id).one().task_revision == 1
        for row in rows
    )
    assert all(
        db.query(AnnotationAssignment).filter_by(id=row.id).one().state == "pending"
        for row in rows
    )
