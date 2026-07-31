import base64
import unittest
import uuid
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pandas as pd
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models.access import AuditEvent, ProjectMember
from app.models.project import Project
from app.models.user import User
from app.models.artifact import Artifact
from app.models.spot_weld_quality import (
    SpotWeldLabelSnapshot,
    SpotWeldQualityRun,
    SpotWeldQualitySample,
)
from app.api.auth import get_current_user
from app.services.artifact_service import ArtifactService
from app.services.spot_weld_features import FEATURE_SCHEMA
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
            samples.append(sample)
            labels.append({"sample_id": str(sample.id), "label": label, "revision_id": None})
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
