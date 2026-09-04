import json
import math
import uuid
import asyncio
import io

import pandas as pd
import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.data_version import DatasetSample, DatasetSchemaColumn, DatasetVersion
from app.models.data_version import DatasetImport
from app.models.artifact import Artifact
from app.api import datasets as datasets_api
from app.schemas.dataset_import import ParseOptions
from app.services.data_import import DataImportError, freeze_dataset_version, read_dataset_upload
from app.services.input_contract import (
    build_input_contract,
    validate_input_contract,
)
from app.services.artifact_service import ArtifactService
from app.storage.local import LocalStorage


def test_json_object_array_is_normalized_and_hash_is_stable(tmp_path):
    path = tmp_path / "rows.json"
    path.write_text(
        '[{"id": 1, "score": 2.5}, {"id": 2, "score": 3.0}]',
        encoding="utf-8",
    )

    table = read_dataset_upload(path, "json", ParseOptions(record_path=None))
    repeated = read_dataset_upload(path, "json", ParseOptions(record_path=None))

    assert table.frame.columns.tolist() == ["id", "score"]
    assert table.parse_contract["parser_version"]
    assert table.schema_hash == repeated.schema_hash
    assert table.content_hash == repeated.content_hash
    assert table.sample_ids == repeated.sample_ids
    assert len(set(table.sample_ids)) == 2


def test_csv_excel_and_parquet_are_normalized(tmp_path):
    frame = pd.DataFrame({"sample": ["a", "b"], "value": [1.0, 2.0]})
    csv_path = tmp_path / "rows.csv"
    xlsx_path = tmp_path / "rows.xlsx"
    parquet_path = tmp_path / "rows.parquet"
    frame.to_csv(csv_path, index=False)
    frame.to_excel(xlsx_path, index=False)
    frame.to_parquet(parquet_path, index=False)

    for path, source_format in (
        (csv_path, "csv"),
        (xlsx_path, "excel"),
        (parquet_path, "parquet"),
    ):
        table = read_dataset_upload(
            path,
            source_format,
            ParseOptions(sample_id_column="sample"),
        )
        assert table.frame.columns.tolist() == ["sample", "value"]
        assert table.sample_ids == ["a", "b"]
        assert table.parse_contract["source_format"] == source_format


def test_json_record_path_and_xml_records_are_flattened(tmp_path):
    json_path = tmp_path / "nested.json"
    json_path.write_text(
        json.dumps({"payload": [{"key": "a", "value": 1}, {"key": "b", "value": 2}]}),
        encoding="utf-8",
    )
    xml_path = tmp_path / "rows.xml"
    xml_path.write_text(
        "<root><record id='a'><value>1</value></record>"
        "<record id='b'><value>2</value></record></root>",
        encoding="utf-8",
    )

    json_table = read_dataset_upload(
        json_path, "json", ParseOptions(record_path="payload")
    )
    xml_table = read_dataset_upload(
        xml_path, "xml", ParseOptions(record_path=".//record")
    )

    assert json_table.frame.to_dict(orient="records") == [
        {"key": "a", "value": 1},
        {"key": "b", "value": 2},
    ]
    assert xml_table.frame.columns.tolist() == ["id", "value"]
    assert xml_table.frame.to_dict(orient="records") == [
        {"id": "a", "value": "1"},
        {"id": "b", "value": "2"},
    ]


def test_json_duplicate_key_is_rejected_without_partial_table(tmp_path):
    path = tmp_path / "duplicate.json"
    path.write_text('[{"a": 1, "a": 2}]', encoding="utf-8")

    with pytest.raises(DataImportError) as error:
        read_dataset_upload(path, "json", ParseOptions(record_path=None))

    assert error.value.code == "DATA_PARSE_DUPLICATE_KEY"


def test_xml_external_entity_is_rejected_before_entity_expansion(tmp_path):
    path = tmp_path / "evil.xml"
    path.write_text(
        "<!DOCTYPE r [<!ENTITY xxe SYSTEM 'file:///etc/passwd'>]>"
        "<r><record><value>&xxe;</value></record></r>",
        encoding="utf-8",
    )

    with pytest.raises(DataImportError) as error:
        read_dataset_upload(path, "xml", ParseOptions(record_path=".//record"))

    assert error.value.code == "DATA_PARSE_UNSAFE_XML"


def test_non_scalar_json_and_xml_values_are_rejected(tmp_path):
    json_path = tmp_path / "non-scalar.json"
    json_path.write_text('[{"id": 1, "tags": ["a", "b"]}]', encoding="utf-8")
    xml_path = tmp_path / "non-scalar.xml"
    xml_path.write_text(
        "<root><record><value><nested>1</nested></value></record></root>",
        encoding="utf-8",
    )

    with pytest.raises(DataImportError) as json_error:
        read_dataset_upload(json_path, "json", ParseOptions(record_path=None))
    with pytest.raises(DataImportError) as xml_error:
        read_dataset_upload(xml_path, "xml", ParseOptions(record_path=".//record"))

    assert json_error.value.code == "DATA_PARSE_NON_SCALAR"
    assert xml_error.value.code == "DATA_PARSE_NON_SCALAR"


def test_parser_limits_reject_large_rows_columns_depth_and_fields(tmp_path):
    rows = tmp_path / "rows.json"
    rows.write_text('[{"a": 1}, {"a": 2}]', encoding="utf-8")
    with pytest.raises(DataImportError) as row_error:
        read_dataset_upload(rows, "json", ParseOptions(max_rows=1))

    columns = tmp_path / "columns.csv"
    columns.write_text("a,b,c\n1,2,3\n", encoding="utf-8")
    with pytest.raises(DataImportError) as column_error:
        read_dataset_upload(columns, "csv", ParseOptions(max_columns=2))

    deep = tmp_path / "deep.json"
    deep.write_text('{"a":{"b":{"c":[{"value": 1}]}}}', encoding="utf-8")
    with pytest.raises(DataImportError) as depth_error:
        read_dataset_upload(
            deep, "json", ParseOptions(record_path="a.b.c", max_depth=2)
        )

    field = tmp_path / "field.json"
    field.write_text('[{"value": "abcdef"}]', encoding="utf-8")
    with pytest.raises(DataImportError) as field_error:
        read_dataset_upload(field, "json", ParseOptions(max_field_bytes=3))

    assert row_error.value.code == "DATA_LIMIT_ROWS"
    assert column_error.value.code == "DATA_LIMIT_COLUMNS"
    assert depth_error.value.code == "DATA_LIMIT_DEPTH"
    assert field_error.value.code == "DATA_LIMIT_FIELD_BYTES"


def test_parser_rejects_duplicate_columns_and_unsafe_record_paths(tmp_path):
    csv_path = tmp_path / "duplicate.csv"
    csv_path.write_text("a,a\n1,2\n", encoding="utf-8")
    with pytest.raises(DataImportError) as duplicate_error:
        read_dataset_upload(csv_path, "csv", ParseOptions())

    json_path = tmp_path / "path.json"
    json_path.write_text('{"payload": [{"id": 1}]}', encoding="utf-8")
    with pytest.raises(DataImportError) as path_error:
        read_dataset_upload(
            json_path, "json", ParseOptions(record_path="payload/../secret")
        )

    assert duplicate_error.value.code == "DATA_PARSE_DUPLICATE_COLUMN"
    assert path_error.value.code == "DATA_PARSE_UNSAFE_PATH"


def test_selected_sample_id_must_be_non_empty_and_unique(tmp_path):
    path = tmp_path / "samples.csv"
    path.write_text("id,value\na,1\na,2\n", encoding="utf-8")

    with pytest.raises(DataImportError) as error:
        read_dataset_upload(
            path, "csv", ParseOptions(sample_id_column="id")
        )

    assert error.value.code == "DATA_SAMPLE_ID_NOT_UNIQUE"


def test_input_contract_distinguishes_missing_column_from_null_value():
    missing_report = validate_input_contract(
        pd.DataFrame({"x": [1]}),
        {
            "required_columns": ["x", "y"],
            "columns": {"x": {"dtype": "int"}, "y": {"dtype": "float"}},
        },
    )
    null_report = validate_input_contract(
        pd.DataFrame({"x": [1, None]}),
        {
            "required_columns": ["x"],
            "columns": {"x": {"dtype": "int", "missing_policy": "reject"}},
        },
    )

    assert missing_report.code == "INPUT_REQUIRED_COLUMN_MISSING"
    assert missing_report.partial_output_allowed is False
    assert null_report.code == "INPUT_NULL_VALUE"
    assert null_report.partial_output_allowed is False


def test_input_contract_accepts_extra_columns_and_validates_ranges_and_finite_floats():
    frame = pd.DataFrame({"x": [1, 2], "score": [0.5, 0.75], "extra": ["ok", "ok"]})
    contract = build_input_contract(
        frame,
        feature_columns=["x", "score"],
        missing_policy={"x": "reject", "score": "reject"},
        preprocessing_version="prep-1",
    )
    contract["columns"]["score"].update({"min_value": 0.0, "max_value": 1.0})

    report = validate_input_contract(frame, contract)
    invalid = frame.copy()
    invalid.loc[1, "score"] = math.inf
    invalid_report = validate_input_contract(invalid, contract)

    assert report.code == "OK"
    assert report.partial_output_allowed is True
    assert invalid_report.code == "INPUT_NONFINITE_FLOAT"
    assert invalid_report.partial_output_allowed is False


def test_input_contract_enforces_sample_id_and_strict_dtypes():
    frame = pd.DataFrame({"sample_id": ["a", "b"], "count": [1, 2]})
    contract = build_input_contract(
        frame,
        feature_columns=["count"],
        missing_policy={"count": "reject"},
        preprocessing_version="prep-1",
    )
    contract["sample_id_column"] = "sample_id"

    valid = validate_input_contract(frame, contract)
    bad_dtype = validate_input_contract(
        pd.DataFrame({"sample_id": ["a", "b"], "count": [1.0, 2.0]}),
        contract,
    )
    duplicate_ids = validate_input_contract(
        pd.DataFrame({"sample_id": ["a", "a"], "count": [1, 2]}),
        contract,
    )

    assert valid.code == "OK"
    assert bad_dtype.code == "INPUT_DTYPE_MISMATCH"
    assert duplicate_ids.code == "INPUT_SAMPLE_ID_INVALID"


def test_freeze_dataset_version_persists_immutable_schema_and_samples(tmp_path):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    project_id = uuid.uuid4()
    operator_id = uuid.uuid4()
    path = tmp_path / "rows.csv"
    path.write_text("sample,value\na,1\nb,2\n", encoding="utf-8")
    table = read_dataset_upload(
        path, "csv", ParseOptions(sample_id_column="sample")
    )
    table.project_id = project_id

    version = freeze_dataset_version(db, table, operator_id)

    assert version.row_count == 2
    assert version.content_hash == table.content_hash
    assert db.query(DatasetSchemaColumn).filter_by(dataset_version_id=version.id).count() == 2
    assert db.query(DatasetSample).filter_by(dataset_version_id=version.id).count() == 2
    assert inspect(engine).has_table("dataset_versions")
    assert inspect(engine).has_table("dataset_imports")

    version.status = "mutated"
    with pytest.raises(ValueError, match="immutable"):
        db.commit()
    db.rollback()
    assert db.get(DatasetVersion, version.id).status == "ready"


@pytest.mark.parametrize(
    ("name", "source_format", "payload"),
    [
        ("rows.json", "json", b'[{"id":"a","value":1}]'),
        ("rows.xml", "xml", b"<root><record id='a'><value>1</value></record></root>"),
    ],
)
def test_api_dataset_import_creates_original_normalized_artifacts_and_version(
    tmp_path, monkeypatch, name, source_format, payload,
):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    project_id = uuid.uuid4()
    operator = type("Operator", (), {"id": uuid.uuid4()})()
    service = ArtifactService(db, LocalStorage(tmp_path / "storage"))
    monkeypatch.setattr("app.services.data_import.build_artifact_service", lambda _db: service)
    monkeypatch.setattr(datasets_api, "resolve_project_access", lambda *_args: object())
    upload = datasets_api.UploadFile(filename=name, file=io.BytesIO(payload))

    result = asyncio.run(datasets_api.import_dataset_version(
        str(project_id), None, upload, source_format, None, db, operator,
    ))

    version = db.get(DatasetVersion, uuid.UUID(result["dataset_version_id"]))
    assert version is not None
    assert db.query(Artifact).filter(Artifact.id.in_([
        version.original_artifact_id, version.normalized_artifact_id,
    ])).count() == 2
    assert db.query(DatasetImport).filter_by(dataset_version_id=version.id).count() == 1


def test_api_dataset_import_accepts_parquet_and_creates_version(tmp_path, monkeypatch):
    path = tmp_path / "rows.parquet"
    pd.DataFrame({"id": ["a"], "value": [1]}).to_parquet(path)
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    project_id = uuid.uuid4()
    operator = type("Operator", (), {"id": uuid.uuid4()})()
    service = ArtifactService(db, LocalStorage(tmp_path / "storage"))
    monkeypatch.setattr("app.services.data_import.build_artifact_service", lambda _db: service)
    monkeypatch.setattr(datasets_api, "resolve_project_access", lambda *_args: object())
    upload = datasets_api.UploadFile(filename="rows.parquet", file=io.BytesIO(path.read_bytes()))
    result = asyncio.run(datasets_api.import_dataset_version(
        str(project_id), None, upload, "parquet", None, db, operator,
    ))
    assert db.get(DatasetVersion, uuid.UUID(result["dataset_version_id"])) is not None


def test_freeze_failure_compensates_original_artifact_and_removes_normalized_temp(tmp_path, monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    path = tmp_path / "rows.csv"
    path.write_text("id,value\na,1\n", encoding="utf-8")
    table = read_dataset_upload(path, "csv", ParseOptions())
    table.project_id = uuid.uuid4()
    deleted = []

    class Storage:
        def delete(self, uri):
            deleted.append(uri)

    class FailingService:
        storage = Storage()
        calls = 0
        def create_from_file(self, *_args, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                return type("Artifact", (), {"storage_uri": "memory://original"})()
            raise RuntimeError("normalized artifact write failed")

    monkeypatch.setattr("app.services.data_import.build_artifact_service", lambda _db: FailingService())
    before = set(tmp_path.glob("*.csv"))
    with pytest.raises(RuntimeError, match="normalized artifact"):
        freeze_dataset_version(db, table, uuid.uuid4())
    assert deleted == ["memory://original"]
    assert set(tmp_path.glob("*.csv")) == before


def test_child_rows_reject_direct_update_and_delete(tmp_path):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    path = tmp_path / "rows.csv"
    path.write_text("id,value\na,1\n", encoding="utf-8")
    table = read_dataset_upload(path, "csv", ParseOptions())
    table.project_id = uuid.uuid4()
    version = freeze_dataset_version(db, table, uuid.uuid4())
    column = db.query(DatasetSchemaColumn).filter_by(dataset_version_id=version.id).first()
    sample = db.query(DatasetSample).filter_by(dataset_version_id=version.id).one()
    imported = db.query(DatasetImport).filter_by(dataset_version_id=version.id).one()
    for row, attribute, value in ((column, "name", "changed"), (sample, "sample_id", "changed"), (imported, "source_format", "changed")):
        setattr(row, attribute, value)
        with pytest.raises(ValueError, match="immutable"):
            db.commit()
        db.rollback()
    db.delete(db.query(DatasetSample).filter_by(dataset_version_id=version.id).one())
    with pytest.raises(ValueError, match="immutable"):
        db.commit()


def test_parser_enforces_elapsed_time_and_xml_path_and_column_compatibility(tmp_path, monkeypatch):
    path = tmp_path / "rows.json"
    path.write_text('[{"id": 1}]', encoding="utf-8")
    ticks = iter((0.0, 2.0))
    monkeypatch.setattr("app.services.data_import.time.monotonic", lambda: next(ticks))
    with pytest.raises(DataImportError) as elapsed:
        read_dataset_upload(path, "json", ParseOptions(max_time_seconds=1))
    assert elapsed.value.code == "DATA_LIMIT_TIME"
    monkeypatch.undo()

    xml = tmp_path / "rows.xml"
    xml.write_text("<root><record><a>1</a></record><record><b>2</b></record></root>", encoding="utf-8")
    with pytest.raises(DataImportError) as unsafe_path:
        read_dataset_upload(xml, "xml", ParseOptions(record_path=".//record/../secret"))
    with pytest.raises(DataImportError) as incompatible_columns:
        read_dataset_upload(xml, "xml", ParseOptions(record_path=".//record"))
    assert unsafe_path.value.code == "DATA_PARSE_UNSAFE_PATH"
    assert incompatible_columns.value.code == "DATA_PARSE_DUPLICATE_COLUMN"
