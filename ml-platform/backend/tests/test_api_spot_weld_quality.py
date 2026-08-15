import base64
from io import BytesIO
import json
import unittest
import uuid
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import PropertyMock, patch

import numpy as np
import pandas as pd
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import spot_weld_quality as quality_api
from app.database import Base, get_db
from app.main import app
from app.models.access import AuditEvent, ProjectMember
from app.models.project import Project
from app.models.user import User
from app.models.artifact import Artifact
from app.models.spot_weld_quality import (
    SpotWeldLabelRevision,
    SpotWeldLabelSnapshot,
    SpotWeldQualityRun,
    SpotWeldQualitySample,
)
from app.api.auth import get_current_user
from app.services.artifact_service import ArtifactService
from app.services.spot_weld_features import FEATURE_SCHEMA
from app.services import spot_weld_quality as quality_service
from app.services.spot_weld_quality import execute_quality_run
from app.storage.local import LocalStorage


def waveform(offset: int = 0) -> str:
    values = (np.arange(870, dtype=np.int32) + offset).astype(">i2")
    return base64.b64encode(values.tobytes()).decode("ascii")


def report_frame(rows=2):
    row = {
        "wld1c": 8.0, "wld2c": 10.0, "tipv1": 2.0, "tipv2": 2.5,
        "wres": 0.3, "energy": 100.0, "wld_spatter_strength": 1.0,
        "wld1_spatter_strength": 1.0, "wld2_spatter_strength": 0.5,
        "spatterpos_wld": 0.0, "spatterpos_pre": 0.0, "spotdiameter": 5.0,
        "spotposition": 1.0, "spattercode": 0.0,
        "cvei": waveform(), "cvev": waveform(1), "cver": waveform(2), "cvep": waveform(3),
    }
    return pd.DataFrame([{**row, "cvei": waveform(index)} for index in range(rows)])


class TestSpotWeldQualityAPI(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.owner = User(username=f"quality-owner-{uuid.uuid4().hex}", password_hash="hash", role="engineer")
        self.viewer = User(username=f"quality-viewer-{uuid.uuid4().hex}", password_hash="hash", role="engineer")
        self.db.add_all([self.owner, self.viewer]); self.db.flush()
        self.project = Project(name="Quality project", owner_id=self.owner.id)
        self.other = Project(name="Other project", owner_id=self.viewer.id)
        self.db.add_all([self.project, self.other]); self.db.flush()
        self.db.add(ProjectMember(project_id=self.project.id, user_id=self.viewer.id, role="viewer", created_by=self.owner.id))
        self.db.commit()
        path = Path(self.directory.name) / "weld.csv"
        report_frame().to_csv(path, index=False)
        self.artifact = Artifact(
            project_id=self.project.id, name="weld.csv", type="dataset", storage_path=str(path),
            format="csv", file_size=path.stat().st_size,
            metadata_={"sha256": "fixture", "row_count": 2},
        )
        self.db.add(self.artifact); self.db.commit(); self.db.refresh(self.artifact)
        self.artifact_service = ArtifactService(
            self.db,
            LocalStorage(Path(self.directory.name) / "artifacts"),
        )
        app.dependency_overrides[get_db] = lambda: self.db
        app.dependency_overrides[get_current_user] = lambda: self.owner
        app.state.quality_artifact_service_factory = lambda _db: self.artifact_service
        self.dispatcher = type("QualityDispatcher", (), {
            "enqueued": [],
            "enqueue": lambda dispatcher, run_id: dispatcher.enqueued.append(str(run_id)) or "quality-task-1",
        })()
        app.state.quality_dispatcher = self.dispatcher
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()
        if hasattr(app.state, "quality_dispatcher"):
            delattr(app.state, "quality_dispatcher")
        if hasattr(app.state, "quality_artifact_service_factory"):
            delattr(app.state, "quality_artifact_service_factory")
        self.db.close(); self.engine.dispose(); self.directory.cleanup()

    def _create_dataset_artifact(self, name: str, frame: pd.DataFrame) -> Artifact:
        path = Path(self.directory.name) / name
        frame.to_csv(path, index=False)
        artifact = Artifact(
            project_id=self.project.id,
            name=name,
            type="dataset",
            storage_path=str(path),
            format="csv",
            file_size=path.stat().st_size,
            metadata_={"sha256": f"fixture-{name}", "row_count": len(frame)},
        )
        self.db.add(artifact)
        self.db.commit()
        self.db.refresh(artifact)
        return artifact

    def _create_approved_snapshot(self):
        run = SpotWeldQualityRun(
            project_id=self.project.id,
            dataset_artifact_id=self.artifact.id,
            created_by_id=self.owner.id,
            status="completed",
            feature_schema=list(FEATURE_SCHEMA),
            rule_set_version="report_v1",
        )
        self.db.add(run)
        self.db.flush()
        samples = []
        labels = []
        for index in range(10):
            label = "normal" if index < 5 else "strong_splatter"
            sample = SpotWeldQualitySample(
                run_id=run.id,
                source_row_index=index,
                display_id=f"W-{index + 1:04d}",
                feature_values={name: float(index + position + 1) for position, name in enumerate(FEATURE_SCHEMA)},
                automatic_label=label,
                current_label=label,
                review_status="approved",
                warning_level="none",
            )
            self.db.add(sample)
            self.db.flush()
            revision = SpotWeldLabelRevision(
                project_id=self.project.id,
                run_id=run.id,
                sample_id=sample.id,
                author_id=self.owner.id,
                label=label,
                note=f"fixture note {index}",
                action="submitted",
                decision="approved",
                review_comment=f"fixture review {index}",
            )
            self.db.add(revision)
            self.db.flush()
            sample.current_revision_id = revision.id
            samples.append(sample)
            labels.append({"sample_id": str(sample.id), "label": label, "revision_id": str(revision.id), "source": "approved"})
        snapshot = SpotWeldLabelSnapshot(
            project_id=self.project.id,
            run_id=run.id,
            created_by_id=self.owner.id,
            name="approved-quality-fixture",
            labels=labels,
            label_counts={"normal": 5, "strong_splatter": 5},
        )
        self.db.add(snapshot)
        self.db.commit()
        return run, snapshot

    def test_annotation_export_xlsx_contains_samples_revisions_and_snapshots(self):
        run, snapshot = self._create_approved_snapshot()

        response = self.client.get(
            f"/api/projects/{self.project.id}/spot-weld/runs/{run.id}/annotations/export?format=xlsx",
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            response.headers["content-type"].split(";", 1)[0],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        self.assertIn("attachment;", response.headers["content-disposition"])
        workbook = pd.ExcelFile(BytesIO(response.content), engine="openpyxl")
        self.assertEqual(workbook.sheet_names, ["标注样本", "标签修订", "标签快照"])
        sample_frame = pd.read_excel(BytesIO(response.content), sheet_name="标注样本", engine="openpyxl")
        self.assertIn("current_label", sample_frame.columns)
        self.assertEqual(sample_frame.iloc[0]["current_label"], "normal")
        revision_frame = pd.read_excel(BytesIO(response.content), sheet_name="标签修订", engine="openpyxl")
        self.assertEqual(len(revision_frame), 10)
        self.assertEqual(set(revision_frame["label"]), {"normal", "strong_splatter"})
        snapshot_frame = pd.read_excel(BytesIO(response.content), sheet_name="标签快照", engine="openpyxl")
        self.assertEqual(snapshot_frame.iloc[0]["snapshot_id"], str(snapshot.id))
        self.assertEqual(snapshot_frame.iloc[0]["label_source"], "approved")

    def test_annotation_export_is_project_scoped(self):
        run, _snapshot = self._create_approved_snapshot()

        response = self.client.get(
            f"/api/projects/{self.other.id}/spot-weld/runs/{run.id}/annotations/export?format=xlsx",
        )

        self.assertEqual(response.status_code, 404)

    def test_annotation_export_rejects_invalid_format(self):
        run, _snapshot = self._create_approved_snapshot()

        response = self.client.get(
            f"/api/projects/{self.project.id}/spot-weld/runs/{run.id}/annotations/export?format=pdf",
        )

        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(response.json()["detail"]["code"], "QUALITY_ANNOTATION_EXPORT_FORMAT_INVALID")

    def test_save_labeled_dataset_creates_project_dataset_with_label_column(self):
        run = SpotWeldQualityRun(
            project_id=self.project.id,
            dataset_artifact_id=self.artifact.id,
            created_by_id=self.owner.id,
            status="completed",
        )
        self.db.add(run)
        self.db.flush()
        self.db.add_all([
            SpotWeldQualitySample(
                run_id=run.id,
                source_row_index=0,
                display_id="W-0001",
                automatic_label="normal",
                current_label="normal",
                review_status="approved",
            ),
            SpotWeldQualitySample(
                run_id=run.id,
                source_row_index=1,
                display_id="W-0002",
                automatic_label="strong_splatter",
                current_label="spot_too_small",
                review_status="approved",
            ),
        ])
        self.db.commit()

        response = self.client.post(
            f"/api/projects/{self.project.id}/spot-weld/runs/{run.id}/save-labeled-dataset",
            json={"label_source": "current"},
        )

        self.assertEqual(response.status_code, 201, response.text)
        artifact_id = response.json()["artifact_id"]
        saved = self.db.query(Artifact).filter(Artifact.id == uuid.UUID(artifact_id)).one()
        with self.artifact_service.materialize(saved.id, self.project.id, expected_type="dataset") as path:
            frame = pd.read_csv(path)
        self.assertEqual(list(frame.columns)[-1], "label")
        self.assertEqual(frame["label"].tolist(), ["normal", "spot_too_small"])

    def test_validate_and_create_run_are_project_scoped(self):
        payload = {"dataset_artifact_id": str(self.artifact.id), "field_mapping": {}, "candidate_ids": ["RF_v1", "GBDT_v1"]}
        response = self.client.post(f"/api/projects/{self.project.id}/spot-weld/validate", json=payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["valid_rows"], 2)
        created = self.client.post(f"/api/projects/{self.project.id}/spot-weld/runs", json=payload)
        self.assertEqual(created.status_code, 202)
        self.assertEqual(created.json()["status"], "queued")
        self.assertEqual(created.json()["task_id"], "quality-task-1")
        self.assertEqual(created.json()["selected_candidate_ids"], ["RF_v1", "GBDT_v1"])
        self.assertEqual(self.dispatcher.enqueued, [created.json()["id"]])
        hidden = self.client.post(f"/api/projects/{self.other.id}/spot-weld/runs", json=payload)
        self.assertEqual(hidden.status_code, 404)
        self.assertEqual(hidden.json()["detail"]["code"], "PROJECT_NOT_FOUND")

    def test_create_run_persists_label_mode_and_rule_configuration(self):
        response = self.client.post(
            f"/api/projects/{self.project.id}/spot-weld/runs",
            json={
                "dataset_artifact_id": str(self.artifact.id),
                "field_mapping": {},
                "candidate_ids": [],
                "label_mode": "manual",
                "rule_config": {"strong_splatter_min": 4},
            },
        )

        self.assertEqual(response.status_code, 202, response.text)
        payload = response.json()
        self.assertEqual(payload.get("label_mode"), "manual")
        self.assertEqual(payload.get("rule_config", {}).get("strong_splatter_min"), 4)

    def test_annotation_modes_accept_bom_and_whitespace_padded_headers(self):
        frame = report_frame(2)
        frame.columns = [f"\ufeff  {column}  " for column in frame.columns]
        artifact = self._create_dataset_artifact("padded-weld.csv", frame)
        url = f"/api/projects/{self.project.id}/spot-weld/runs"

        for mode in ("automatic", "manual"):
            with self.subTest(mode=mode):
                response = self.client.post(url, json={
                    "dataset_artifact_id": str(artifact.id),
                    "field_mapping": {},
                    "label_mode": mode,
                })
                self.assertEqual(response.status_code, 202, response.text)

    def test_quality_run_persists_supervised_input_target_and_evaluation_configuration(self):
        frame = report_frame(15)
        frame["label"] = ["normal", "strong_splatter", "spot_too_small"] * 5
        artifact = self._create_dataset_artifact("labeled-weld.csv", frame)
        input_columns = [column for column in frame.columns if column != "label"]

        response = self.client.post(
            f"/api/projects/{self.project.id}/spot-weld/runs",
            json={
                "dataset_artifact_id": str(artifact.id),
                "field_mapping": {},
                "candidate_ids": ["RF_v1"],
                "target_column": "label",
                "input_columns": input_columns,
                "cross_validation_enabled": True,
                "cross_validation_folds": 4,
            },
        )

        self.assertEqual(response.status_code, 202, response.text)
        payload = response.json()
        self.assertEqual(payload["target_column"], "label")
        self.assertEqual(payload["input_columns"], input_columns)
        self.assertEqual(payload["evaluation"], {
            "cross_validation_enabled": True,
            "cross_validation_folds": 4,
        })
        self.assertEqual(payload["statistics"]["target_schema"]["name"], "label")
        self.assertEqual(payload["statistics"]["target_schema"]["classes"], [
            "normal", "spot_too_small", "strong_splatter",
        ])

    def test_quality_run_identifies_omitted_required_input_column(self):
        selected_columns = [column for column in report_frame().columns if column != "wld1c"]

        response = self.client.post(
            f"/api/projects/{self.project.id}/spot-weld/runs",
            json={
                "dataset_artifact_id": str(self.artifact.id),
                "field_mapping": {},
                "input_columns": selected_columns,
            },
        )

        self.assertEqual(response.status_code, 400, response.text)
        detail = response.json()["detail"]
        self.assertEqual(detail["code"], "QUALITY_INPUT_COLUMNS_INVALID")
        self.assertIn("wld1c", detail["message"])

    def test_quality_run_rejects_missing_target_and_invalid_enabled_fold_settings(self):
        frame = report_frame(15)
        frame["label"] = ["normal", "strong_splatter", "spot_too_small"] * 5
        artifact = self._create_dataset_artifact("quality-invalid-evaluation.csv", frame)
        input_columns = [column for column in frame.columns if column != "label"]
        url = f"/api/projects/{self.project.id}/spot-weld/runs"

        missing_target = self.client.post(url, json={
            "dataset_artifact_id": str(artifact.id),
            "field_mapping": {},
            "target_column": "missing_label",
            "input_columns": input_columns,
        })
        self.assertEqual(missing_target.status_code, 400, missing_target.text)
        self.assertEqual(missing_target.json()["detail"]["code"], "QUALITY_TARGET_COLUMN_INVALID")

        for folds in (None, 2, 6):
            with self.subTest(folds=folds):
                response = self.client.post(url, json={
                    "dataset_artifact_id": str(artifact.id),
                    "field_mapping": {},
                    "target_column": "label",
                    "input_columns": input_columns,
                    "cross_validation_enabled": True,
                    "cross_validation_folds": folds,
                })
                self.assertEqual(response.status_code, 400, response.text)
                self.assertEqual(response.json()["detail"]["code"], "QUALITY_EVALUATION_CONFIG_INVALID")

    def test_quality_run_uses_selected_multiclass_label_for_supervised_metrics(self):
        frame = report_frame(15)
        frame["wld_spatter_strength"] = [3.0 if index % 2 else 0.0 for index in range(len(frame))]
        frame["label"] = ["normal", "strong_splatter", "spot_too_small"] * 5
        artifact = self._create_dataset_artifact("quality-supervised-labels.csv", frame)
        input_columns = [column for column in frame.columns if column != "label"]
        response = self.client.post(
            f"/api/projects/{self.project.id}/spot-weld/runs",
            json={
                "dataset_artifact_id": str(artifact.id),
                "field_mapping": {},
                "candidate_ids": ["RF_v1"],
                "target_column": "label",
                "input_columns": input_columns,
                "cross_validation_enabled": True,
                "cross_validation_folds": 3,
            },
        )
        self.assertEqual(response.status_code, 202, response.text)

        with patch(
            "app.services.spot_weld_quality.run_automl",
            wraps=quality_service.run_automl,
        ) as run_automl:
            outcome = execute_quality_run(
                self.db,
                response.json()["id"],
                artifact_service=self.artifact_service,
            )

        self.assertEqual(outcome.status, "completed")
        self.assertEqual(run_automl.call_args.args[1].tolist(), frame["label"].tolist())
        run = self.db.query(SpotWeldQualityRun).filter(
            SpotWeldQualityRun.id == uuid.UUID(response.json()["id"]),
        ).one()
        self.assertEqual(run.statistics["target_schema"]["classes"], [
            "normal", "spot_too_small", "strong_splatter",
        ])
        self.assertEqual(run.statistics["evaluation"], {
            "cross_validation_enabled": True,
            "cross_validation_folds": 3,
        })
        samples = self.db.query(SpotWeldQualitySample).filter(
            SpotWeldQualitySample.run_id == run.id,
        ).order_by(SpotWeldQualitySample.source_row_index).all()
        self.assertEqual(len(samples), len(frame))
        self.assertTrue(all(sample.automatic_label for sample in samples))
        self.assertTrue(all(sample.rule_hits for sample in samples))
        run_detail = self.client.get(
            f"/api/projects/{self.project.id}/spot-weld/runs/{run.id}",
        )
        self.assertEqual(run_detail.status_code, 200, run_detail.text)
        self.assertEqual(run_detail.json()["annotation_progress"], {
            "annotated_count": len(frame),
            "total_count": len(frame),
            "percent": 100.0,
        })
        self.assertIsNotNone(run.automl_results[0]["auc"])
        self.assertIsNotNone(run.automl_results[0]["f1"])
        with self.artifact_service.materialize(
            uuid.UUID(run.output_artifacts["results"]),
            self.project.id,
            expected_type="quality_results",
        ) as path:
            result_payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(result_payload["target_schema"]["name"], "label")
        self.assertEqual(result_payload["evaluation"], run.statistics["evaluation"])
        report = self.client.get(
            f"/api/projects/{self.project.id}/spot-weld/runs/{run.id}/artifacts/report/download",
        )
        self.assertEqual(report.status_code, 200, report.text)
        self.assertEqual(
            report.headers["content-type"].split(";", 1)[0],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        self.assertGreater(len(report.content), 0)

    def test_run_exposes_annotation_progress_for_automatic_and_manual_labels(self):
        for label_mode, automatic_labels, current_labels in (
            ("automatic", ["normal", "strong_splatter", None, None], [None, None, None, None]),
            ("manual", [None, None, None, None], ["normal", "strong_splatter", None, None]),
        ):
            with self.subTest(label_mode=label_mode):
                run = SpotWeldQualityRun(
                    project_id=self.project.id,
                    dataset_artifact_id=self.artifact.id,
                    created_by_id=self.owner.id,
                    status="running",
                    input_fingerprint={"label_mode": label_mode, "row_count": 4},
                    statistics={"row_count": 4},
                )
                self.db.add(run)
                self.db.flush()
                for index, (automatic_label, current_label) in enumerate(zip(automatic_labels, current_labels)):
                    self.db.add(SpotWeldQualitySample(
                        run_id=run.id,
                        source_row_index=index,
                        display_id=f"W-{index + 1:04d}",
                        automatic_label=automatic_label,
                        current_label=current_label,
                        review_status="pending_review",
                    ))
                self.db.commit()

                response = self.client.get(
                    f"/api/projects/{self.project.id}/spot-weld/runs/{run.id}",
                )

                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(
                    response.json()["annotation_progress"],
                    {"annotated_count": 2, "total_count": 4, "percent": 50.0},
                )

    def test_run_uses_persisted_progress_without_loading_large_sample_rows(self):
        run = SpotWeldQualityRun(
            id=uuid.uuid4(),
            project_id=self.project.id,
            dataset_artifact_id=self.artifact.id,
            created_by_id=self.owner.id,
            status="running",
            input_fingerprint={"label_mode": "automatic"},
            statistics={"annotation_progress": {"annotated_count": 10, "total_count": 20}},
        )

        with patch.object(SpotWeldQualityRun, "samples", new_callable=PropertyMock) as samples:
            samples.side_effect = AssertionError("run detail must not load every sample")
            payload = quality_api._serialize_run(run, include_results=False)

        self.assertEqual(payload["sample_count"], 20)
        self.assertEqual(payload["annotation_progress"], {
            "annotated_count": 10,
            "total_count": 20,
            "percent": 50.0,
        })

    def test_sample_queue_omits_large_detail_payloads(self):
        run = SpotWeldQualityRun(
            project_id=self.project.id,
            dataset_artifact_id=self.artifact.id,
            created_by_id=self.owner.id,
            status="completed",
        )
        self.db.add(run)
        self.db.flush()
        sample = SpotWeldQualitySample(
            run_id=run.id,
            source_row_index=0,
            display_id="W-0001",
            table_values={"cvei": "large-source-waveform"},
            feature_values={"current_mean": 1.0},
            waveforms={"current": [1, 2, 3]},
            automatic_label="normal",
            rule_hits=[{"code": "normal"}],
            review_status="pending_review",
        )
        self.db.add(sample)
        self.db.commit()

        response = self.client.get(
            f"/api/projects/{self.project.id}/spot-weld/runs/{run.id}/samples",
        )

        self.assertEqual(response.status_code, 200, response.text)
        item = response.json()["items"][0]
        self.assertNotIn("table_values", item)
        self.assertNotIn("feature_values", item)
        self.assertNotIn("waveforms", item)
        detail = self.client.get(
            f"/api/projects/{self.project.id}/spot-weld/runs/{run.id}/samples/{sample.id}",
        )
        self.assertEqual(detail.status_code, 200, detail.text)
        self.assertEqual(detail.json()["table_values"], {"cvei": "large-source-waveform"})

    def test_manual_override_keeps_automatic_annotation_progress_complete(self):
        run = SpotWeldQualityRun(
            project_id=self.project.id,
            dataset_artifact_id=self.artifact.id,
            created_by_id=self.owner.id,
            status="completed",
            input_fingerprint={"label_mode": "automatic"},
            statistics={"annotation_progress": {"annotated_count": 2, "total_count": 2, "percent": 100.0}},
        )
        self.db.add(run)
        self.db.flush()
        samples = [
            SpotWeldQualitySample(
                run_id=run.id,
                source_row_index=index,
                display_id=f"W-{index + 1:04d}",
                automatic_label=label,
                review_status="pending_review",
            )
            for index, label in enumerate(("normal", "strong_splatter"))
        ]
        self.db.add_all(samples)
        self.db.commit()

        response = self.client.post(
            f"/api/projects/{self.project.id}/spot-weld/runs/{run.id}/samples/{samples[0].id}/labels",
            json={"label": "spot_too_small", "note": "manual override"},
        )

        self.assertEqual(response.status_code, 201, response.text)
        detail = self.client.get(
            f"/api/projects/{self.project.id}/spot-weld/runs/{run.id}",
        )
        self.assertEqual(detail.status_code, 200, detail.text)
        self.assertEqual(detail.json()["annotation_progress"], {
            "annotated_count": 2,
            "total_count": 2,
            "percent": 100.0,
        })

    def test_submit_run_for_review_updates_only_labeled_samples(self):
        run = SpotWeldQualityRun(
            project_id=self.project.id,
            dataset_artifact_id=self.artifact.id,
            created_by_id=self.owner.id,
            status="running",
        )
        self.db.add(run)
        self.db.flush()
        labeled_pending = SpotWeldQualitySample(
            run_id=run.id,
            source_row_index=0,
            display_id="W-0001",
            current_label="normal",
            review_status="pending_review",
        )
        labeled_submitted = SpotWeldQualitySample(
            run_id=run.id,
            source_row_index=1,
            display_id="W-0002",
            current_label="strong_splatter",
            review_status="submitted",
        )
        unlabeled = SpotWeldQualitySample(
            run_id=run.id,
            source_row_index=2,
            display_id="W-0003",
            current_label=None,
            review_status="pending_review",
        )
        self.db.add_all([labeled_pending, labeled_submitted, unlabeled])
        self.db.commit()

        response = self.client.post(
            f"/api/projects/{self.project.id}/spot-weld/runs/{run.id}/submit-review",
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            response.json(),
            {
                "run_id": str(run.id),
                "submitted_count": 1,
                "labeled_count": 2,
            },
        )
        self.db.expire_all()
        self.assertEqual(self.db.get(SpotWeldQualitySample, labeled_pending.id).review_status, "submitted")
        self.assertEqual(self.db.get(SpotWeldQualitySample, labeled_submitted.id).review_status, "submitted")
        self.assertEqual(self.db.get(SpotWeldQualitySample, unlabeled.id).review_status, "pending_review")

    def test_terminal_quality_run_can_be_deleted(self):
        run = SpotWeldQualityRun(
            project_id=self.project.id,
            dataset_artifact_id=self.artifact.id,
            created_by_id=self.owner.id,
            status="completed",
        )
        self.db.add(run)
        self.db.flush()
        sample = SpotWeldQualitySample(
            run_id=run.id,
            source_row_index=0,
            display_id="W-0001",
            current_label="normal",
        )
        self.db.add(sample)
        self.db.commit()
        run_id = run.id
        sample_id = sample.id

        response = self.client.delete(
            f"/api/projects/{self.project.id}/spot-weld/runs/{run_id}",
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {"deleted": 1, "run_id": str(run_id)})
        self.assertIsNone(self.db.get(SpotWeldQualityRun, run_id))
        self.assertIsNone(self.db.get(SpotWeldQualitySample, sample_id))

    def test_active_quality_run_cannot_be_deleted(self):
        run = SpotWeldQualityRun(
            project_id=self.project.id,
            dataset_artifact_id=self.artifact.id,
            created_by_id=self.owner.id,
            status="running",
        )
        self.db.add(run)
        self.db.commit()

        response = self.client.delete(
            f"/api/projects/{self.project.id}/spot-weld/runs/{run.id}",
        )

        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()["detail"]["code"], "QUALITY_RUN_ACTIVE")
        self.assertIsNotNone(self.db.get(SpotWeldQualityRun, run.id))

    def test_completed_run_rules_can_be_updated(self):
        run = SpotWeldQualityRun(
            project_id=self.project.id,
            dataset_artifact_id=self.artifact.id,
            created_by_id=self.owner.id,
            status="completed",
            input_fingerprint={"label_mode": "manual", "rule_config": {}},
            statistics={},
        )
        self.db.add(run); self.db.commit()

        response = self.client.put(
            f"/api/projects/{self.project.id}/spot-weld/runs/{run.id}/rules",
            json={"rule_config": {"strong_splatter_min": 4}},
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["rule_config"]["strong_splatter_min"], 4)
        self.db.refresh(run)
        self.assertEqual(run.input_fingerprint["rule_config"]["strong_splatter_min"], 4)

    def test_quality_run_rejects_unknown_or_duplicate_report_candidates(self):
        url = f"/api/projects/{self.project.id}/spot-weld/runs"
        for candidate_ids in (["unknown"], ["RF_v1", "RF_v1"], [f"unknown-{index}" for index in range(256)]):
            with self.subTest(candidate_ids=candidate_ids):
                audit_count = self.db.query(AuditEvent).filter(
                    AuditEvent.action == "spot_weld_quality.run.create",
                ).count()
                response = self.client.post(url, json={
                    "dataset_artifact_id": str(self.artifact.id),
                    "field_mapping": {},
                    "candidate_ids": candidate_ids,
                })
                self.assertEqual(response.status_code, 400, response.text)
                self.assertEqual(response.json()["detail"]["code"], "QUALITY_AUTOML_CONFIG_INVALID")
                self.assertEqual(
                    self.db.query(AuditEvent).filter(
                        AuditEvent.action == "spot_weld_quality.run.create",
                    ).count(),
                    audit_count,
                )

    def test_quality_validation_rejects_invalid_report_candidates(self):
        response = self.client.post(
            f"/api/projects/{self.project.id}/spot-weld/validate",
            json={
                "dataset_artifact_id": str(self.artifact.id),
                "field_mapping": {},
                "candidate_ids": ["unknown"],
            },
        )

        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(response.json()["detail"]["code"], "QUALITY_AUTOML_CONFIG_INVALID")

    def test_invalid_waveform_returns_stable_quality_code(self):
        frame = report_frame(1)
        frame.loc[0, "cvei"] = base64.b64encode(b"bad").decode("ascii")
        path = Path(self.directory.name) / "bad.csv"; frame.to_csv(path, index=False)
        bad = Artifact(project_id=self.project.id, name="bad.csv", type="dataset", storage_path=str(path), format="csv", file_size=path.stat().st_size, metadata_={})
        self.db.add(bad); self.db.commit(); self.db.refresh(bad)
        response = self.client.post(f"/api/projects/{self.project.id}/spot-weld/validate", json={"dataset_artifact_id": str(bad.id), "field_mapping": {}})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["errors"][0]["code"], "QUALITY_WAVEFORM_LENGTH_INVALID")

    def test_validation_reports_valid_and_invalid_rows_separately(self):
        frame = report_frame(2)
        frame.loc[1, "cvei"] = base64.b64encode(b"bad").decode("ascii")
        path = Path(self.directory.name) / "partially-bad.csv"; frame.to_csv(path, index=False)
        artifact = Artifact(project_id=self.project.id, name="partially-bad.csv", type="dataset", storage_path=str(path), format="csv", file_size=path.stat().st_size, metadata_={})
        self.db.add(artifact); self.db.commit(); self.db.refresh(artifact)

        response = self.client.post(f"/api/projects/{self.project.id}/spot-weld/validate", json={"dataset_artifact_id": str(artifact.id), "field_mapping": {}})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["valid_rows"], 1)
        self.assertEqual(response.json()["invalid_rows"], 1)
        self.assertEqual(response.json()["errors"][0]["row_index"], 1)

    def test_invalid_legacy_xls_returns_a_stable_validation_error(self):
        path = Path(self.directory.name) / "broken.xls"; path.write_bytes(b"not-an-xls")
        artifact = Artifact(project_id=self.project.id, name="broken.xls", type="dataset", storage_path=str(path), format="xls", file_size=path.stat().st_size, metadata_={})
        self.db.add(artifact); self.db.commit(); self.db.refresh(artifact)

        response = self.client.post(f"/api/projects/{self.project.id}/spot-weld/validate", json={"dataset_artifact_id": str(artifact.id), "field_mapping": {}})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"]["code"], "QUALITY_DATASET_INVALID")

    def test_demo_dataset_is_project_scoped_and_returns_a_dataset_artifact(self):
        artifact = SimpleNamespace(
            id=uuid.uuid4(),
            name="spot-weld-demo.csv",
            metadata_={"row_count": 24, "sha256": "demo-sha"},
        )
        with patch("app.api.spot_weld_quality.create_demo_quality_dataset", return_value=artifact) as create_demo:
            response = self.client.post(
                f"/api/projects/{self.project.id}/spot-weld/demo-dataset",
                json={"row_count": 24},
            )

        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["artifact_id"], str(artifact.id))
        self.assertEqual(response.json()["row_count"], 24)
        create_demo.assert_called_once()

    def test_approved_snapshot_trains_and_exposes_model_and_report(self):
        run, snapshot = self._create_approved_snapshot()
        training = self.client.post(
            f"/api/projects/{self.project.id}/spot-weld/runs/{run.id}/label-snapshots/{snapshot.id}/train",
        )

        self.assertEqual(training.status_code, 200, training.text)
        payload = training.json()
        self.assertEqual(payload["snapshot_id"], str(snapshot.id))
        self.assertEqual(payload["model"]["params"]["quality_run_id"], str(run.id))
        self.assertIn("report", payload["output_artifacts"])

        model = self.client.get(
            f"/api/projects/{self.project.id}/spot-weld/runs/{run.id}/quality-model",
        )
        self.assertEqual(model.status_code, 200, model.text)
        self.assertEqual(model.json()["params"]["label_snapshot_id"], str(snapshot.id))

        report = self.client.get(
            f"/api/projects/{self.project.id}/spot-weld/runs/{run.id}/artifacts/report/download",
        )
        self.assertEqual(report.status_code, 200, report.text)
        self.assertEqual(
            report.headers["content-type"].split(";", 1)[0],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        self.assertGreater(len(report.content), 0)

    def test_quality_report_includes_run_schema_and_evaluation_configuration(self):
        run, snapshot = self._create_approved_snapshot()
        run.input_fingerprint = {
            "target_column": "label",
            "input_columns": ["wld1c", "cvei"],
            "evaluation": {
                "cross_validation_enabled": True,
                "cross_validation_folds": 4,
            },
        }
        run.statistics = {
            "input_schema": [
                {"name": "wld1c", "dtype": "float64"},
                {"name": "cvei", "dtype": "object"},
            ],
            "target_schema": {
                "name": "label",
                "dtype": "object",
                "classes": ["normal", "strong_splatter"],
            },
            "evaluation": {
                "cross_validation_enabled": True,
                "cross_validation_folds": 4,
            },
        }
        self.db.commit()

        training = self.client.post(
            f"/api/projects/{self.project.id}/spot-weld/runs/{run.id}/label-snapshots/{snapshot.id}/train",
        )
        self.assertEqual(training.status_code, 200, training.text)
        report = self.client.get(
            f"/api/projects/{self.project.id}/spot-weld/runs/{run.id}/artifacts/report/download",
        )
        self.assertEqual(report.status_code, 200, report.text)
        summary = pd.read_excel(
            BytesIO(report.content),
            sheet_name="总览",
            engine="openpyxl",
        )
        summary_values = dict(zip(summary["指标"], summary["值"]))
        self.assertEqual(summary_values["源数据目标列"], "label")
        self.assertEqual(summary_values["源数据输入列"], "wld1c, cvei")
        self.assertEqual(summary_values["质量运行评估配置"], "cross_validation: 4 folds")
        self.assertEqual(summary_values["快照训练评估配置"], "cross_validation: 5 folds")

    def test_automatic_snapshot_keeps_saved_rule_labels_distinct_from_human_labels(self):
        run = SpotWeldQualityRun(
            project_id=self.project.id,
            dataset_artifact_id=self.artifact.id,
            created_by_id=self.owner.id,
            status="completed",
            feature_schema=list(FEATURE_SCHEMA),
            rule_set_version="report_v1",
        )
        self.db.add(run)
        self.db.flush()
        for index, label in enumerate(("normal", "strong_splatter", None, "", "   ", "not-a-quality-label")):
            self.db.add(SpotWeldQualitySample(
                run_id=run.id,
                source_row_index=index,
                display_id=f"W-{index + 1:04d}",
                automatic_label=label,
                current_label="human-label",
                review_status="pending_review",
                warning_level="none",
            ))
        self.db.commit()

        response = self.client.post(
            f"/api/projects/{self.project.id}/spot-weld/runs/{run.id}/label-snapshots",
            json={"name": "report-v1-auto", "label_source": "automatic"},
        )

        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["label_source"], "automatic")
        snapshot = self.db.query(SpotWeldLabelSnapshot).filter_by(name="report-v1-auto").one()
        self.assertTrue(all(item["source"] == "automatic" for item in snapshot.labels))
        self.assertTrue(all(item["revision_id"] is None for item in snapshot.labels))
        self.assertEqual([item["label"] for item in snapshot.labels], ["normal", "strong_splatter"])
        audit = self.db.query(AuditEvent).filter(
            AuditEvent.action == "spot_weld_quality.snapshot.create",
            AuditEvent.resource_id == str(snapshot.id),
        ).one()
        self.assertEqual(audit.changes["label_source"], "automatic")

        listed = self.client.get(
            f"/api/projects/{self.project.id}/spot-weld/runs/{run.id}/label-snapshots",
        )
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertEqual(listed.json()["items"][0]["label_source"], "automatic")

    def test_automatic_snapshot_rejects_incomplete_runs_and_runs_without_valid_labels(self):
        url_template = f"/api/projects/{self.project.id}/spot-weld/runs/{{run_id}}/label-snapshots"
        cases = (("running", "normal"), ("completed", "   "))
        for index, (status, automatic_label) in enumerate(cases):
            with self.subTest(status=status, automatic_label=automatic_label):
                run = SpotWeldQualityRun(
                    project_id=self.project.id,
                    dataset_artifact_id=self.artifact.id,
                    created_by_id=self.owner.id,
                    status=status,
                    feature_schema=list(FEATURE_SCHEMA),
                    rule_set_version="report_v1",
                )
                self.db.add(run)
                self.db.flush()
                self.db.add(SpotWeldQualitySample(
                    run_id=run.id,
                    source_row_index=0,
                    display_id=f"W-EMPTY-{index}",
                    automatic_label=automatic_label,
                    review_status="pending_review",
                    warning_level="none",
                ))
                self.db.commit()
                audit_count = self.db.query(AuditEvent).filter(
                    AuditEvent.action == "spot_weld_quality.snapshot.create",
                ).count()

                response = self.client.post(
                    url_template.format(run_id=run.id),
                    json={"name": f"automatic-empty-{index}", "label_source": "automatic"},
                )

                self.assertEqual(response.status_code, 400, response.text)
                self.assertEqual(response.json()["detail"]["code"], "QUALITY_AUTOMATIC_LABELS_UNAVAILABLE")
                self.assertEqual(
                    self.db.query(SpotWeldLabelSnapshot).filter_by(run_id=run.id).count(),
                    0,
                )
                self.assertEqual(
                    self.db.query(AuditEvent).filter(
                        AuditEvent.action == "spot_weld_quality.snapshot.create",
                    ).count(),
                    audit_count,
                )

    def test_quality_model_listing_and_warning_targets_stay_project_scoped(self):
        run, snapshot = self._create_approved_snapshot()
        trained = self.client.post(
            f"/api/projects/{self.project.id}/spot-weld/runs/{run.id}/label-snapshots/{snapshot.id}/train",
        )
        self.assertEqual(trained.status_code, 200, trained.text)

        models = self.client.get(f"/api/projects/{self.project.id}/spot-weld/models")
        self.assertEqual(models.status_code, 200, models.text)
        self.assertEqual(models.json()["total"], 1)
        self.assertEqual(models.json()["items"][0]["params"]["quality_run_id"], str(run.id))
        hidden = self.client.get(f"/api/projects/{self.other.id}/spot-weld/models")
        self.assertEqual(hidden.status_code, 404)

        samples = self.db.query(SpotWeldQualitySample).filter(
            SpotWeldQualitySample.run_id == run.id,
        ).order_by(SpotWeldQualitySample.source_row_index).all()
        for sample in samples:
            sample.warning_level = "none"
            sample.defect_probability = 0.0
        samples[0].warning_level = "notice"
        samples[0].defect_probability = 0.4
        samples[1].warning_level = "critical"
        samples[1].defect_probability = 0.9
        self.db.commit()

        warnings = self.client.get(f"/api/projects/{self.project.id}/spot-weld/warnings")
        self.assertEqual(warnings.status_code, 200, warnings.text)
        self.assertEqual(warnings.json()["counts"]["critical"], 1)
        self.assertEqual(warnings.json()["items"][0]["id"], str(samples[1].id))
        self.assertEqual(warnings.json()["items"][0]["run_id"], str(run.id))


if __name__ == "__main__":
    unittest.main()
