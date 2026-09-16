import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.labeling import LabelColumn, LabelSchema, LabelValueConstraint, AnnotationSampleCurrent, AnnotationRevision
from app.services.label_schema import (
    LabelColumnContract,
    LabelSchemaContract,
    LabelValueError,
    get_current_label_set,
    validate_label_value,
    validate_label_values,
    write_label_revision,
    create_label_schema,
    confirm_label_values,
)
from app.schemas.labeling import LabelColumnCreate


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    yield session
    session.close()
    engine.dispose()


def test_label_types_reject_invalid_values():
    assert validate_label_value(LabelColumnContract("count", "int"), "12") == 12
    with pytest.raises(LabelValueError):
        validate_label_value(LabelColumnContract("count", "int"), "12.5")
    with pytest.raises(LabelValueError):
        validate_label_value(LabelColumnContract("score", "float"), float("nan"))
    with pytest.raises(LabelValueError):
        validate_label_value(LabelColumnContract("score", "float"), True)
    with pytest.raises(LabelValueError):
        validate_label_value(LabelColumnContract("name", "string", max_length=4), "abcdef")


def test_string_labels_are_trimmed_nonempty_and_limited_to_default_utf8_bytes():
    column = LabelColumnContract("name", "string")

    assert validate_label_value(column, "  accepted  ") == "accepted"
    with pytest.raises(LabelValueError):
        validate_label_value(column, " \t ")
    with pytest.raises(LabelValueError):
        validate_label_value(column, "x" * 4097)


def test_integer_labels_are_limited_to_signed_64_bit_range():
    column = LabelColumnContract("count", "int")

    assert validate_label_value(column, "-9223372036854775808") == -(2 ** 63)
    assert validate_label_value(column, "9223372036854775807") == 2 ** 63 - 1
    with pytest.raises(LabelValueError):
        validate_label_value(column, "9223372036854775808")
    with pytest.raises(LabelValueError):
        validate_label_value(column, "-9223372036854775809")


def test_new_label_columns_default_to_required(db):
    schema = create_label_schema(
        db,
        project_id=uuid.uuid4(),
        name="default-required",
        columns=[{
            "machine_key": "decision",
            "display_name": "Decision",
            "value_type": "string",
        }],
    )

    assert schema.columns[0].required is True
    assert LabelColumnCreate(
        machine_key="api_decision",
        display_name="API decision",
        value_type="string",
    ).required is True


def test_column_constraints_match_the_declared_value_type():
    with pytest.raises(ValueError):
        LabelColumnCreate(machine_key="count", display_name="Count", value_type="int", enum_values=[1.5])
    with pytest.raises(ValueError):
        LabelColumnCreate(machine_key="count", display_name="Count", value_type="int", min_value=0.5)


def test_partial_edit_preserves_unmodified_label_columns(db):
    schema = LabelSchema(name="quality", version=1, project_id=uuid.uuid4())
    db.add(schema)
    db.flush()
    db.add_all([
        LabelColumn(schema_id=schema.id, machine_key="label_a", display_name="A", ordinal=0, value_type="string", required=True),
        LabelColumn(schema_id=schema.id, machine_key="label_b", display_name="B", ordinal=1, value_type="int", required=True),
    ])
    current = AnnotationSampleCurrent(task_id=uuid.uuid4(), sample_id="sample-1", schema_id=schema.id, revision_no=2, values={"label_a": "old", "label_b": 3})
    db.add(current)
    db.commit()

    result = write_label_revision(db, current.task_id, current.sample_id, {"label_a": "accepted"}, uuid.uuid4(), base_revision=2)
    assert result.values == {"label_a": "accepted", "label_b": 3}
    assert result.revision_no == 3


def test_completion_rejects_missing_required_label():
    schema = LabelSchemaContract([
        LabelColumnContract("label_a", "int", required=True),
        LabelColumnContract("label_b", "int", required=True),
    ])
    with pytest.raises(LabelValueError) as error:
        validate_label_values(schema, {"label_a": 1}, allow_partial=False)
    assert error.value.code == "LABEL_REQUIRED_MISSING"


def test_current_label_set_returns_revision_values(db):
    task_id, schema_id = uuid.uuid4(), uuid.uuid4()
    current = AnnotationSampleCurrent(task_id=task_id, sample_id="sample-2", schema_id=schema_id, revision_no=1, values={"x": 1})
    db.add(current)
    db.commit()
    result = get_current_label_set(db, task_id, "sample-2")
    assert result.values == {"x": 1}
    assert result.revision_no == 1


def test_schema_creation_freezes_typed_constraints(db):
    project_id = uuid.uuid4()
    column = LabelColumnContract("score", "float", required=True, min_value=0, max_value=1)
    schema = create_label_schema(db, project_id=project_id, name="scores", columns=[{
        "machine_key": column.machine_key, "display_name": "Score", "value_type": column.value_type,
        "required": column.required, "enum_values": [], "min_value": 0, "max_value": 1, "max_length": None,
    }])
    assert schema.version == 1
    assert db.query(LabelValueConstraint).count() == 1
    schema.name = "changed"
    with pytest.raises(ValueError, match="IMMUTABLE_LABEL_HISTORY"):
        db.commit()
    db.rollback()


def test_revision_conflict_and_confirmation_require_complete_values(db):
    schema = LabelSchema(name="required", version=1, project_id=uuid.uuid4())
    db.add(schema)
    db.flush()
    db.add_all([
        LabelColumn(schema_id=schema.id, machine_key="a", display_name="A", ordinal=0, value_type="int", required=True),
        LabelColumn(schema_id=schema.id, machine_key="b", display_name="B", ordinal=1, value_type="int", required=True),
    ])
    current = AnnotationSampleCurrent(task_id=uuid.uuid4(), sample_id="s", schema_id=schema.id, revision_no=0, values={})
    db.add(current)
    db.commit()
    author = uuid.uuid4()
    write_label_revision(db, current.task_id, "s", {"a": 1}, author, 0)
    with pytest.raises(LabelValueError, match="stale") as conflict:
        write_label_revision(db, current.task_id, "s", {"b": 2}, author, 0)
    assert conflict.value.code == "LABEL_REVISION_CONFLICT"
    with pytest.raises(LabelValueError) as incomplete:
        confirm_label_values(db, current.task_id, "s", author)
    assert incomplete.value.code == "LABEL_REQUIRED_MISSING"
