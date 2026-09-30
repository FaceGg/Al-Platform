"""Annotation package payload resolution over the model training-data lineage."""

import json
import uuid
import zipfile

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.artifact import Artifact
from app.models.data_version import DatasetVersion
from app.models.labeling import AnnotationStrategyArtifact, AnnotationStrategyDecision
from app.models.model_library import ModelLibrary
from app.models.model_registry import ModelVersion, RegisteredModel
from app.models.operation import DurableOperation
from app.models.platform_models import GenericAnnotationTask
from app.models.project import Project
from app.models.user import User
from app.services.model_export import resolve_annotation_payload


STRATEGY_CONFIGURATION = {
    "clustering": True,
    "strategy": "cluster",
    "selected_clusters": ["0", "1"],
    "cluster_labels": {"0": {"label": "accept"}, "1": {"label": "reject"}},
    "other_values": {"label": "other"},
}


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    session = Session()
    yield session
    session.close()
    engine.dispose()


def _artifact(db, project, name, artifact_type, storage_path=None):
    artifact = Artifact(
        project_id=project.id,
        name=name,
        type=artifact_type,
        storage_path=storage_path or f"/tmp/{name}",
        file_size=10,
        format="joblib" if artifact_type == "model" else "csv",
        metadata_={},
    )
    db.add(artifact)
    db.flush()
    return artifact


def _lineage(db, *, configuration=STRATEGY_CONFIGURATION, with_library=True, model_path=None):
    owner = User(username=f"lineage-owner-{uuid.uuid4().hex}", password_hash="hash")
    db.add(owner)
    db.flush()
    project = Project(name=f"Lineage project {uuid.uuid4().hex}", owner_id=owner.id)
    db.add(project)
    db.flush()
    dataset_artifact = _artifact(db, project, "annotated-dataset", "dataset")
    model_artifact = _artifact(
        db,
        project,
        "candidate-model",
        "model",
        storage_path=str(model_path) if model_path is not None else None,
    )
    scope_version = DatasetVersion(
        project_id=project.id,
        operator_id=owner.id,
        version=1,
        row_count=3,
        column_count=1,
        content_hash="sha256:lineage-data",
        schema_hash="sha256:lineage-schema",
        parse_contract={"source_format": "upload"},
    )
    db.add(scope_version)
    db.flush()
    task = GenericAnnotationTask(
        project_id=project.id,
        dataset_version_id=scope_version.id,
        label_schema_id=uuid.uuid4(),
        owner_id=owner.id,
        name="弱监督标注任务",
        mode="automatic",
        status="completed",
        task_revision=1,
        sample_scope={"kind": "all"},
        task_snapshot={
            "label_schema": {"columns": [{"machine_key": "label", "display_name": "Label", "value_type": "string", "required": True, "enum_values": ["accept", "reject"]}]},
            "configuration": configuration,
        },
    )
    db.add(task)
    db.flush()
    # The annotation return export publishes a ready dataset version whose
    # parse contract stamps the owning task; its original artifact is what a
    # later AutoML job selects for training.
    dataset_version = DatasetVersion(
        project_id=project.id,
        operator_id=owner.id,
        version=2,
        row_count=3,
        column_count=1,
        content_hash="sha256:lineage-export",
        schema_hash="sha256:lineage-schema",
        parse_contract={
            "source_format": "annotation_return_export",
            "task_id": str(task.id),
            "return_batch_id": str(uuid.uuid4()),
        },
        original_artifact_id=dataset_artifact.id,
    )
    db.add(dataset_version)
    db.flush()
    artifact = AnnotationStrategyArtifact(
        task_id=task.id,
        task_revision=1,
        config_hash="sha256:lineage-config",
        strategy=configuration.get("strategy", "cluster"),
        artifact={"configuration_complete": True, "cluster_artifact": {"selected_k": 2, "method": "weighted_kmeans"}},
        created_by=owner.id,
    )
    db.add(artifact)
    db.flush()
    for sample_id, cluster_id in [("sample-1", 0), ("sample-2", 1), ("sample-3", 0)]:
        db.add(AnnotationStrategyDecision(
            strategy_artifact_id=artifact.id,
            sample_id=sample_id,
            row_index=0,
            status="ready",
            values={"label": "accept"},
            provenance={"label": {"source": "cluster"}},
            model_output={},
            cluster_id=cluster_id,
            matched_rule_ids=[],
            decision_hash="sha256:decision",
        ))
    registered = RegisteredModel(project_id=project.id, name="Lineage model", created_by_id=owner.id)
    db.add(registered)
    db.flush()
    version = ModelVersion(
        registered_model_id=registered.id,
        version_number=1,
        # Without a model-library lineage the registration is artifact-only
        # (ONNX); the check constraint forbids platform_joblib without a
        # source library.
        source_kind="platform_joblib" if with_library else "onnx_artifact",
        source_artifact_id=model_artifact.id,
        onnx_artifact_id=model_artifact.id,
        framework="sklearn",
        algorithm="LogisticRegression",
        conversion_metadata={"input_contract": {}},
        approval_status="approved",
        lifecycle_state="enabled",
    )
    if with_library:
        library = ModelLibrary(
            name="lineage-library",
            project_id=project.id,
            owner_id=owner.id,
            status="completed",
            format="joblib",
            dataset_artifact_id=dataset_artifact.id,
            model_artifact_id=model_artifact.id,
        )
        db.add(library)
        db.flush()
        version.source_model_library_id = library.id
    db.add(version)
    db.commit()
    return version, task


def test_annotation_payload_resolves_from_training_data_lineage(db):
    version, _task = _lineage(db)

    payload = resolve_annotation_payload(db, version)

    assert payload is not None
    assert payload["strategy"] == {"strategy": "cluster", "other_values": {"label": "other"}}
    assert payload["rules"] == {"rules": []}
    assert payload["cluster_label_mappings"] == {"0": {"label": "accept"}, "1": {"label": "reject"}}
    assert payload["cluster_artifacts"] == {"assignments": {"sample-1": 0, "sample-2": 1, "sample-3": 0}}
    assert payload["cluster_method"] == {"selected_k": 2, "method": "weighted_kmeans"}


def test_annotation_payload_is_none_without_library_lineage(db):
    version, _task = _lineage(db, with_library=False)

    assert resolve_annotation_payload(db, version) is None


def test_annotation_payload_ignores_tasks_of_other_projects(db):
    version, task = _lineage(db)
    task.project_id = uuid.uuid4()
    db.commit()

    assert resolve_annotation_payload(db, version) is None


def test_annotation_payload_is_none_for_cluster_discovery_configuration(db):
    version, _task = _lineage(db, configuration={
        "clustering": True,
        "cluster_discovery": True,
    })

    assert resolve_annotation_payload(db, version) is None


def test_worker_export_embeds_resolved_annotation_payload(db, tmp_path, monkeypatch):
    from app.models.model_export import ModelExport
    from app.tasks.model_export_tasks import execute_model_export

    from app.config import settings

    model_file = tmp_path / "candidate-model.joblib"
    model_file.write_bytes(b"model-bytes")
    version, _task = _lineage(db, model_path=model_file)
    monkeypatch.setattr(settings, "artifact_storage_dir", str(tmp_path))
    monkeypatch.setenv("MODEL_EXPORT_SIGNING_KEY", "lineage-test-key")

    export = ModelExport(
        model_version_id=version.id,
        annotation_task_revision=0,
        idempotency_scope=f"model-version:{version.id}:task:none:revision:0",
        idempotency_key="lineage-key",
        request_hash="a" * 64,
        include_runtime=True,
        status="queued",
    )
    db.add(export)
    db.flush()
    operation = DurableOperation(
        resource_key=f"model-export:{export.id}",
        idempotency_key="lineage-key",
        state="queued",
        stage="queued",
    )
    db.add(operation)
    db.flush()
    export.operation_id = operation.id
    db.commit()

    monkeypatch.setattr("app.tasks.model_export_tasks.SessionLocal", lambda: db)
    result = execute_model_export.run(str(export.id))
    assert result["status"] == "completed", result

    db.expire_all()
    refreshed = db.query(ModelExport).filter(ModelExport.id == export.id).one()
    assert refreshed.status == "completed"
    with zipfile.ZipFile(refreshed.package_path) as archive:
        strategy = json.loads(archive.read("annotation/strategy.json"))
        assignments = json.loads(archive.read("annotation/cluster_artifacts.json"))
        mappings = json.loads(archive.read("annotation/cluster_label_mappings.json"))
    assert strategy == {"strategy": "cluster", "other_values": {"label": "other"}}
    assert assignments == {"assignments": {"sample-1": 0, "sample-2": 1, "sample-3": 0}}
    assert mappings == {"0": {"label": "accept"}, "1": {"label": "reject"}}
