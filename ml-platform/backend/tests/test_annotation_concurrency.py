import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.annotator import AnnotatorAccount, ProjectAnnotatorGrant
from app.models.data_version import DatasetSample, DatasetSchemaColumn, DatasetVersion
from app.models.labeling import (
    AnnotationAssignment,
    AnnotationAssignmentSample,
    AnnotationReturnBatch,
    AnnotationRevision,
    AnnotationSampleCurrent,
    LabelColumn,
    LabelSchema,
)
from app.models.operation import DurableOperation
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
    transition_assignment,
)
from app.tasks.annotation_return_tasks import _execute_with_session


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


def test_assignment_creation_reuses_idempotency_key_and_rejects_payload_change(db):
    task_id = uuid.uuid4()
    annotator_id = uuid.uuid4()
    actor_id = uuid.uuid4()
    first = create_assignments(
        db,
        task_id=task_id,
        annotator_ids=[annotator_id],
        sample_scope={"kind": "ids", "sample_ids": ["s-1"]},
        actor=actor_id,
        idempotency_key="assignment-key",
    )
    repeated = create_assignments(
        db,
        task_id=task_id,
        annotator_ids=[annotator_id],
        sample_scope={"kind": "ids", "sample_ids": ["s-1"]},
        actor=actor_id,
        idempotency_key="assignment-key",
    )
    assert [item.id for item in repeated] == [item.id for item in first]
    assert db.query(AnnotationAssignment).count() == 1
    with pytest.raises(AssignmentError, match="idempotency key"):
        create_assignments(
            db,
            task_id=task_id,
            annotator_ids=[annotator_id],
            sample_scope={"kind": "ids", "sample_ids": ["s-2"]},
            actor=actor_id,
            idempotency_key="assignment-key",
        )


def test_edit_for_return_requires_new_revision_before_unlock(db):
    assignment = _assignment(db)
    return_assignment(db, assignment.id, 3, assignment.scope_hash, "first-key")
    edit_for_return(db, assignment.id, 3)

    with pytest.raises(AssignmentLockedError):
        return_assignment(db, assignment.id, 3, assignment.scope_hash, "second-key")

    save_labels(db, assignment.id, "s-1", {"label_a": "z", "label_b": 1}, base_revision=3)
    result = return_assignment(db, assignment.id, 4, assignment.scope_hash, "second-key")
    assert result.state == "pending"
    batches = db.query(AnnotationReturnBatch).order_by(AnnotationReturnBatch.created_at.asc()).all()
    assert len(batches) == 2
    assert batches[0].state == "superseded"
    assert batches[1].state == "pending"


def test_assignment_pause_resume_restores_edit_for_return_state_and_is_replayable(db):
    assignment = _assignment(db)
    assignment.state = "edit_for_return"
    db.commit()

    paused = transition_assignment(
        db,
        assignment.id,
        action="pause",
        task_revision=assignment.task_revision,
        actor=assignment.created_by,
        idempotency_key="pause-assignment",
        request_id=uuid.uuid4(),
    )
    assert paused.state == "paused"
    assert paused.paused_from_state == "edit_for_return"

    resumed = transition_assignment(
        db,
        assignment.id,
        action="resume",
        task_revision=assignment.task_revision,
        actor=assignment.created_by,
        idempotency_key="resume-assignment",
        request_id=uuid.uuid4(),
    )
    assert resumed.state == "edit_for_return"
    assert resumed.paused_from_state is None

    replay = transition_assignment(
        db,
        assignment.id,
        action="pause",
        task_revision=assignment.task_revision,
        actor=assignment.created_by,
        idempotency_key="pause-assignment",
        request_id=uuid.uuid4(),
    )
    assert replay._command_response_payload["state"] == "paused"


def test_paused_assignment_rejects_label_confirm_and_return_writes(db):
    admin, _other, subject, task = _secure_fixture(db)
    assignment = create_assignments(
        db,
        task_id=task.id,
        annotator_ids=[subject],
        sample_scope={"kind": "ids", "sample_ids": ["frozen-1"]},
        actor=admin.id,
    )[0]
    transition_assignment(
        db,
        assignment.id,
        action="pause",
        task_revision=assignment.task_revision,
        actor=admin.id,
    )

    with pytest.raises(AssignmentLockedError):
        save_labels(db, assignment.id, "frozen-1", {"label": "x"}, 0, actor=admin.id)
    with pytest.raises(AssignmentLockedError):
        confirm_assignment(db, assignment.id, assignment.task_revision, assignment.scope_hash)
    with pytest.raises(AssignmentLockedError):
        return_assignment(db, assignment.id, assignment.task_revision, assignment.scope_hash, "paused-return")


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


def _secure_fixture(db, *, task_status="awaiting_annotation", sample_ids=("frozen-1",)):
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
        row_count=len(sample_ids),
        column_count=1,
        content_hash="sha256:assignment-data",
        schema_hash="sha256:assignment-schema",
    )
    db.add(version)
    db.flush()
    for row_index, sample_id in enumerate(sample_ids):
        db.add(DatasetSample(
            dataset_version_id=version.id,
            sample_id=sample_id,
            row_index=row_index,
            values={"feature": row_index + 1},
        ))
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
        sample_scope={"kind": "ids", "sample_ids": list(sample_ids)},
        task_snapshot={
            "sample_ids": list(sample_ids),
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


def test_assignment_can_reference_server_owned_frozen_task_scope(db):
    admin, _other, subject, task = _secure_fixture(db)
    assignment = create_assignments(
        db,
        task_id=task.id,
        annotator_ids=[subject],
        sample_scope={"kind": "frozen_task_scope"},
        actor=admin.id,
    )[0]
    assert assignment.sample_scope == {
        "kind": "frozen_task_scope",
        "sample_count": 1,
        "scope_hash": assignment.scope_hash,
        "task_revision": task.task_revision,
    }
    assert db.query(AnnotationAssignmentSample).filter_by(assignment_id=assignment.id).count() == 1


@pytest.mark.parametrize(
    "task_status",
    ("draft", "failed", "needs_review", "executing", "awaiting_return", "returned_pending_acceptance"),
)
def test_assignments_are_rejected_outside_publishable_or_active_task_states(db, task_status):
    admin, _other, subject, task = _secure_fixture(db, task_status=task_status)

    with pytest.raises(AssignmentError) as error:
        create_assignments(
            db,
            task_id=task.id,
            annotator_ids=[subject],
            sample_scope={"kind": "ids", "sample_ids": ["frozen-1"]},
            actor=admin.id,
        )

    assert error.value.code == "TASK_STATE_INVALID"


def test_return_edit_requires_returned_pending_acceptance_and_then_allows_one_new_revision(db):
    admin, _other, subject, task = _secure_fixture(db)
    assignment = create_assignments(
        db,
        task_id=task.id,
        annotator_ids=[subject],
        sample_scope={"kind": "ids", "sample_ids": ["frozen-1"]},
        actor=admin.id,
        initial_values={"frozen-1": {"label": "initial"}},
    )[0]
    task.status = "awaiting_return"
    assignment.state = "returned_pending_acceptance"
    db.commit()

    with pytest.raises(AssignmentError) as error:
        edit_for_return(db, assignment.id, task.task_revision)
    assert error.value.code == "TASK_STATE_INVALID"

    task.status = "returned_pending_acceptance"
    db.commit()
    with pytest.raises(AssignmentLockedError):
        save_labels(db, assignment.id, "frozen-1", {"label": "replacement"}, 0, actor=admin.id)
    edit_for_return(db, assignment.id, task.task_revision)
    saved = save_labels(db, assignment.id, "frozen-1", {"label": "replacement"}, 0, actor=admin.id)

    assert saved.revision_no == 1
    assert db.get(AnnotationAssignment, assignment.id).state == "pending"
    assert db.get(GenericAnnotationTask, task.id).status == "in_progress"


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


def test_return_operation_records_project_and_task_context(db):
    admin, _other, subject, task = _secure_fixture(db)
    assignment = create_assignments(
        db,
        task_id=task.id,
        annotator_ids=[subject],
        sample_scope={"kind": "ids", "sample_ids": ["frozen-1"]},
        actor=admin.id,
        initial_values={"frozen-1": {"label": "ready"}},
    )[0]
    confirm_assignment(db, assignment.id, assignment.task_revision, assignment.scope_hash, actor=admin.id)

    returned = return_assignment(
        db,
        assignment.id,
        task.task_revision,
        assignment.scope_hash,
        "return-operation-context",
    )
    operation = db.get(DurableOperation, returned.operation_id)

    assert operation.project_id == task.project_id
    assert operation.task_id == task.id
    assert operation.resource_type == "annotation_return"


def test_return_requires_complete_confirmed_labels(db):
    admin, _other, subject, task = _secure_fixture(db)
    assignment = create_assignments(
        db,
        task_id=task.id,
        annotator_ids=[subject],
        sample_scope={"kind": "ids", "sample_ids": ["frozen-1"]},
        actor=admin.id,
    )[0]

    with pytest.raises(AssignmentError) as error:
        return_assignment(
            db,
            assignment.id,
            assignment.task_revision,
            assignment.scope_hash,
            "incomplete-return",
        )

    assert error.value.code == "ANNOTATION_NOT_READY"


def test_partial_return_acceptance_does_not_complete_task_until_all_scope_is_accepted(db):
    admin, _other, first_subject, task = _secure_fixture(db, sample_ids=("frozen-1", "frozen-2"))
    second_subject = uuid.uuid4()
    db.add(AnnotatorAccount(
        subject_id=second_subject,
        username=f"annotator-{uuid.uuid4().hex}",
        password_hash="hash",
        status="active",
    ))
    db.add(ProjectAnnotatorGrant(
        project_id=task.project_id,
        subject_id=second_subject,
        status="active",
        granted_by=admin.id,
    ))
    db.commit()
    first = create_assignments(
        db,
        task_id=task.id,
        annotator_ids=[first_subject],
        sample_scope={"kind": "ids", "sample_ids": ["frozen-1"]},
        actor=admin.id,
        initial_values={"frozen-1": {"label": "first"}},
    )[0]
    second = create_assignments(
        db,
        task_id=task.id,
        annotator_ids=[second_subject],
        sample_scope={"kind": "ids", "sample_ids": ["frozen-2"]},
        actor=admin.id,
        initial_values={"frozen-2": {"label": "second"}},
    )[0]
    confirm_assignment(db, first.id, first.task_revision, first.scope_hash, actor=admin.id)
    confirm_assignment(db, second.id, second.task_revision, second.scope_hash, actor=admin.id)
    first_return = return_assignment(db, first.id, first.task_revision, first.scope_hash, "partial-first")
    second_return = return_assignment(db, second.id, second.task_revision, second.scope_hash, "partial-second")

    for returned in (first_return, second_return):
        assert returned.operation_id is not None
        result = _execute_with_session(
            db,
            str(returned.return_batch_id),
            str(returned.operation_id),
            f"partial-return:{returned.return_batch_id}",
        )
        assert result["status"] == "completed"

    from app.services.annotation_returns import accept_return_batch

    accept_return_batch(db, first_return.return_batch_id, task.task_revision, admin)
    db.refresh(task)
    assert task.status != "completed"

    accept_return_batch(db, second_return.return_batch_id, task.task_revision, admin)
    db.refresh(task)
    assert task.status == "completed"


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
        db.query(AnnotationAssignment).filter_by(id=row.id).one().task_revision == task.task_revision
        for row in rows
    )
    assert all(
        db.query(AnnotationAssignment).filter_by(id=row.id).one().last_edit_revision == 1
        for row in rows
    )
    assert all(
        db.query(AnnotationAssignment).filter_by(id=row.id).one().state == "pending"
        for row in rows
    )


def test_return_uses_frozen_task_revision_after_a_new_label_revision(db):
    admin, _other, subject, task = _secure_fixture(db)
    assignment = create_assignments(
        db,
        task_id=task.id,
        annotator_ids=[subject],
        sample_scope={"kind": "ids", "sample_ids": ["frozen-1"]},
        actor=admin.id,
        initial_values={"frozen-1": {"label": "initial"}},
    )[0]
    confirm_assignment(db, assignment.id, task.task_revision, assignment.scope_hash, actor=admin.id)
    saved = save_labels(
        db,
        assignment.id,
        "frozen-1",
        {"label": "edited"},
        base_revision=0,
        actor=admin.id,
    )
    assert saved.revision_no == 1
    assert db.get(AnnotationAssignment, assignment.id).task_revision == task.task_revision
    assert db.get(AnnotationAssignment, assignment.id).last_edit_revision == 1

    confirm_assignment(db, assignment.id, task.task_revision, assignment.scope_hash, actor=admin.id)
    returned = return_assignment(
        db,
        assignment.id,
        task.task_revision,
        assignment.scope_hash,
        "return-after-edit",
    )
    batch = db.get(AnnotationReturnBatch, returned.return_batch_id)
    assert batch.task_revision == task.task_revision


def test_source_backed_manual_labels_initialize_assignment_current_values(db):
    owner = User(username=f"source-label-owner-{uuid.uuid4().hex}", password_hash="hash")
    db.add(owner)
    db.flush()
    project = Project(name="Source-backed labels", owner_id=owner.id)
    db.add(project)
    db.flush()
    version = DatasetVersion(
        project_id=project.id,
        operator_id=owner.id,
        version=1,
        row_count=1,
        column_count=2,
        content_hash="sha256:source-backed-labels",
        schema_hash="sha256:source-backed-labels-schema",
    )
    schema = LabelSchema(project_id=project.id, name="source-backed", version=1, status="active")
    db.add_all([version, schema])
    db.flush()
    db.add_all([
        DatasetSchemaColumn(dataset_version_id=version.id, name="feature", position=0, dtype="float64", nullable=False),
        DatasetSchemaColumn(dataset_version_id=version.id, name="decision", position=1, dtype="string", nullable=False),
        DatasetSample(
            dataset_version_id=version.id,
            sample_id="source-backed-1",
            row_index=0,
            values={"feature": 1.0, "decision": "initial"},
        ),
        LabelColumn(
            schema_id=schema.id,
            machine_key="decision",
            display_name="Decision",
            ordinal=0,
            value_type="string",
            required=True,
        ),
    ])
    subject = uuid.uuid4()
    db.add_all([
        AnnotatorAccount(subject_id=subject, username=f"source-backed-{uuid.uuid4().hex}", password_hash="hash", status="active"),
        ProjectAnnotatorGrant(project_id=project.id, subject_id=subject, status="active", granted_by=owner.id),
    ])
    task = GenericAnnotationTask(
        project_id=project.id,
        dataset_version_id=version.id,
        label_schema_id=schema.id,
        owner_id=owner.id,
        mode="manual",
        status="awaiting_annotation",
        task_revision=0,
        sample_scope={"kind": "ids", "sample_ids": ["source-backed-1"]},
        task_snapshot={
            "sample_ids": ["source-backed-1"],
            "label_schema": {
                "columns": [{
                    "machine_key": "decision",
                    "value_type": "string",
                    "required": True,
                }],
            },
        },
    )
    db.add(task)
    db.commit()

    assignment = create_assignments(
        db,
        task_id=task.id,
        annotator_ids=[subject],
        sample_scope={"kind": "ids", "sample_ids": ["source-backed-1"]},
        actor=owner.id,
    )[0]

    assignment_sample = db.query(AnnotationAssignmentSample).filter_by(
        assignment_id=assignment.id,
        sample_id="source-backed-1",
    ).one()
    current = db.query(AnnotationSampleCurrent).filter_by(
        task_id=task.id,
        sample_id="source-backed-1",
    ).one()
    revision = db.query(AnnotationRevision).filter_by(
        task_id=task.id,
        sample_id="source-backed-1",
        revision_no=0,
    ).one()
    assert assignment_sample.values == {"decision": "initial"}
    assert current.values == {"decision": "initial"}
    assert revision.values == {"decision": "initial"}
    assert (revision.source, revision.action) == ("manual", "initialize")


def test_editing_after_return_immediately_supersedes_the_pending_batch(db):
    admin, _other, subject, task = _secure_fixture(db)
    assignment = create_assignments(
        db,
        task_id=task.id,
        annotator_ids=[subject],
        sample_scope={"kind": "ids", "sample_ids": ["frozen-1"]},
        actor=admin.id,
        initial_values={"frozen-1": {"label": "initial"}},
    )[0]
    confirm_assignment(db, assignment.id, task.task_revision, assignment.scope_hash, actor=admin.id)
    returned = return_assignment(
        db,
        assignment.id,
        task.task_revision,
        assignment.scope_hash,
        "return-before-edit",
    )
    worker_result = _execute_with_session(
        db,
        str(returned.return_batch_id),
        str(returned.operation_id),
        f"edit-after-return:{returned.return_batch_id}",
    )
    assert worker_result["status"] == "completed"

    edit_for_return(db, assignment.id, task.task_revision)
    save_labels(
        db,
        assignment.id,
        "frozen-1",
        {"label": "corrected"},
        base_revision=0,
        actor=admin.id,
    )

    assert db.get(AnnotationReturnBatch, returned.return_batch_id).state == "superseded"
    assert db.get(AnnotationAssignment, assignment.id).state == "pending"
    assert db.get(GenericAnnotationTask, task.id).status == "in_progress"


def test_assignment_edits_update_current_labels_for_later_assignments(db):
    db.expire_on_commit = False
    admin, _other, first_subject, task = _secure_fixture(db)
    task.mode = "automatic"
    db.add(AnnotationSampleCurrent(
        task_id=task.id,
        sample_id="frozen-1",
        schema_id=task.label_schema_id,
        revision_no=0,
        values={"label": "automatic"},
    ))
    db.add(AnnotationRevision(
        task_id=task.id,
        sample_id="frozen-1",
        schema_id=task.label_schema_id,
        revision_no=0,
        base_revision=0,
        values={"label": "automatic"},
        author_id=admin.id,
        source="automatic",
        action="initialize",
        provenance_ref="annotation-execution:test",
    ))
    db.commit()
    first = create_assignments(
        db,
        task_id=task.id,
        annotator_ids=[first_subject],
        sample_scope={"kind": "ids", "sample_ids": ["frozen-1"]},
        actor=admin.id,
        idempotency_key="automatic-current-first",
    )[0]
    assert db.query(AnnotationAssignmentSample).filter_by(assignment_id=first.id, sample_id="frozen-1").one().values == {"label": "automatic"}

    edited = save_labels(db, first.id, "frozen-1", {"label": "reviewed"}, base_revision=0, actor=admin.id)
    assert edited.revision_no == 1
    current = db.query(AnnotationSampleCurrent).filter_by(task_id=task.id, sample_id="frozen-1").one()
    assert (current.values, current.revision_no) == ({"label": "reviewed"}, 1)

    second_subject = uuid.uuid4()
    db.add_all([
        AnnotatorAccount(subject_id=second_subject, username=f"annotator-{uuid.uuid4().hex}", password_hash="hash", status="active"),
        ProjectAnnotatorGrant(project_id=task.project_id, subject_id=second_subject, status="active", granted_by=admin.id),
    ])
    db.commit()
    second = create_assignments(
        db,
        task_id=task.id,
        annotator_ids=[second_subject],
        sample_scope={"kind": "ids", "sample_ids": ["frozen-1"]},
        actor=admin.id,
        idempotency_key="automatic-current-second",
    )[0]
    copied = db.query(AnnotationAssignmentSample).filter_by(assignment_id=second.id, sample_id="frozen-1").one()
    assert (copied.values, copied.revision_no) == ({"label": "reviewed"}, 1)
