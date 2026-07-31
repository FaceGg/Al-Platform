import unittest
import tempfile
import uuid
import warnings
from collections import Counter
from pathlib import Path
from unittest.mock import patch

import numpy as np
from openpyxl import load_workbook
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.project import Project
from app.models.spot_weld_quality import SpotWeldLabelSnapshot, SpotWeldQualityRun, SpotWeldQualitySample
from app.models.user import User
from app.services.artifact_service import ArtifactService
from app.services.spot_weld_quality import (
    AUTOML_CONFIGS,
    CandidateResult,
    apply_report_v1_rules,
    build_demo_report_frame,
    claim_quality_run,
    create_demo_quality_dataset,
    create_quality_run_record,
    execute_quality_run,
    read_report_dataset,
    run_automl,
    run_clustering,
    select_automl_configs,
    select_best_candidate,
    train_label_snapshot,
    validate_report_frame,
    warning_level,
)
from app.services.spot_weld_features import QualityPipelineError, build_feature_frame
from app.storage.local import LocalStorage


class TestSpotWeldQualityService(unittest.TestCase):
    def test_report_candidate_selection_preserves_order_and_rejects_invalid_sets(self):
        selected = select_automl_configs(["RF_v1", "GBDT_v1"])
        self.assertEqual([item["name"] for item in selected], ["RF_v1", "GBDT_v1"])
        self.assertEqual(select_automl_configs([]), AUTOML_CONFIGS)
        for candidate_ids in (["RF_v1", "RF_v1"], ["does-not-exist"]):
            with self.subTest(candidate_ids=candidate_ids):
                with self.assertRaises(QualityPipelineError) as raised:
                    select_automl_configs(candidate_ids)
                self.assertEqual(raised.exception.code, "QUALITY_AUTOML_CONFIG_INVALID")

    def test_candidate_selection_orders_auc_then_f1_then_index(self):
        results = [
            CandidateResult("lgb", "lgb", auc=0.91, f1=0.80, config_index=0),
            CandidateResult("cat", "cat", auc=0.91, f1=0.82, config_index=1),
            CandidateResult("rf", "rf", auc=0.91, f1=0.82, config_index=2),
        ]
        self.assertEqual(select_best_candidate(results).name, "cat")

    def test_report_rules_keep_all_hits_in_table_order(self):
        result = apply_report_v1_rules(
            {"wld_spatter_strength": 3, "power_std": 99, "spotdiameter": 5},
            thresholds={"power_std_p95": 1},
        )
        self.assertEqual(result.primary_label, "strong_splatter")
        self.assertEqual([hit.code for hit in result.hits], ["strong_splatter", "power_fluctuation"])

    def test_zero_spot_diameter_is_not_virtual_weld(self):
        result = apply_report_v1_rules({"spotdiameter": 0}, thresholds={})
        self.assertNotIn("spot_too_small", result.hit_codes)

    def test_warning_probability_maps_to_four_levels(self):
        self.assertEqual(warning_level(0.8), "critical")
        self.assertEqual(warning_level(0.6), "warning")
        self.assertEqual(warning_level(0.3), "notice")
        self.assertEqual(warning_level(0.299), "none")

    def test_clustering_searches_k_and_returns_pca_coordinates(self):
        features = np.vstack([
            np.random.default_rng(42).normal(0, 0.2, (8, 3)),
            np.random.default_rng(7).normal(4, 0.2, (8, 3)),
        ])
        result = run_clustering(
            features,
            feature_names=["power_std", "energy_dev", "spatter_total"],
            feature_importance=np.array([3.0, 1.0, 2.0]),
        )
        self.assertIn(result.best_k, range(2, 9))
        self.assertEqual(len(result.cluster_ids), len(features))
        self.assertEqual(result.pca_coordinates.shape, (16, 2))

    def test_demo_dataset_is_report_compatible_and_has_multiple_label_groups(self):
        frame = build_demo_report_frame(24)
        features, schema, _ = build_feature_frame(frame)
        labels = [
            apply_report_v1_rules(record, thresholds={}).primary_label
            for record in features.to_dict(orient="records")
        ]

        self.assertEqual(len(frame), 24)
        self.assertEqual(len(schema), 73)
        self.assertGreaterEqual(sum(label == "normal" for label in labels), 3)
        self.assertGreaterEqual(sum(label != "normal" for label in labels), 3)

    def test_validation_counts_only_rows_that_fail_feature_extraction(self):
        frame = build_demo_report_frame(12)
        frame.loc[1, "cvei"] = "not-a-waveform"

        validation = validate_report_frame(frame)

        self.assertEqual(validation["row_count"], 12)
        self.assertEqual(validation["valid_rows"], 11)
        self.assertEqual(validation["invalid_rows"], 1)
        self.assertEqual(validation["errors"][0]["code"], "QUALITY_WAVEFORM_INVALID_BASE64")
        self.assertEqual(validation["errors"][0]["row_index"], 1)

    def test_automl_uses_matching_feature_names_for_lightgbm_prediction(self):
        features, _, _ = build_feature_frame(build_demo_report_frame(12))
        labels = np.asarray([
            apply_report_v1_rules(record, thresholds={}).primary_label != "normal"
            for record in features.to_dict(orient="records")
        ], dtype=int)

        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter("always")
            run_automl(features.to_numpy(dtype=np.float64), labels, configs=(AUTOML_CONFIGS[0],))

        self.assertFalse(any("does not have valid feature names" in str(item.message) for item in captured))

    def test_legacy_xls_parser_errors_are_stable_quality_errors(self):
        with tempfile.TemporaryDirectory(prefix="quality-xls-test-") as directory:
            path = Path(directory) / "report.xls"
            path.write_bytes(b"not-a-spreadsheet")
            with patch("app.services.spot_weld_quality.pd.read_excel", side_effect=ImportError("xlrd missing")):
                with self.assertRaises(QualityPipelineError) as raised:
                    read_report_dataset(path)

        self.assertEqual(raised.exception.code, "QUALITY_DATASET_INVALID")

    def test_atomic_claim_allows_only_one_worker_to_start_a_quality_run(self):
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Session = sessionmaker(bind=engine)
        Base.metadata.create_all(engine)
        db = Session()
        try:
            run = SpotWeldQualityRun(
                project_id=uuid.uuid4(),
                dataset_artifact_id=uuid.uuid4(),
                created_by_id=uuid.uuid4(),
                status="queued",
            )
            db.add(run)
            db.commit()

            first = claim_quality_run(db, run.id, worker_id="worker-a", task_id="task-a")
            second = claim_quality_run(db, run.id, worker_id="worker-b", task_id="task-b")

            self.assertIsNotNone(first)
            self.assertIsNone(second)
            db.refresh(run)
            self.assertEqual(run.status, "running")
            self.assertEqual(run.worker_id, "worker-a")
            self.assertEqual(run.task_id, "task-a")
        finally:
            db.close()
            engine.dispose()

    def test_demo_quality_run_persists_samples_and_generated_artifacts(self):
        with tempfile.TemporaryDirectory(prefix="quality-service-test-") as directory:
            engine = create_engine(
                "sqlite://",
                connect_args={"check_same_thread": False},
                poolclass=StaticPool,
            )
            Session = sessionmaker(bind=engine)
            Base.metadata.create_all(engine)
            db = Session()
            try:
                owner = User(username=f"quality-service-{uuid.uuid4().hex}", password_hash="hash")
                db.add(owner)
                db.flush()
                project = Project(name="Quality service", owner_id=owner.id)
                db.add(project)
                db.commit()
                artifacts = ArtifactService(db, LocalStorage(Path(directory) / "artifacts"))
                dataset = create_demo_quality_dataset(
                    db,
                    project_id=project.id,
                    row_count=24,
                    artifact_service=artifacts,
                )
                db.commit()
                run = create_quality_run_record(
                    db,
                    project_id=project.id,
                    user_id=owner.id,
                    dataset_artifact_id=dataset.id,
                    artifact_service=artifacts,
                )
                db.commit()

                outcome = execute_quality_run(db, run.id, artifact_service=artifacts)
                db.refresh(run)

                self.assertEqual(outcome.status, "completed")
                self.assertEqual(run.status, "completed")
                self.assertEqual(
                    db.query(SpotWeldQualitySample).filter(SpotWeldQualitySample.run_id == run.id).count(),
                    24,
                )
                self.assertEqual(len(run.automl_results), 10)
                self.assertFalse(any(result["error_code"] for result in run.automl_results))
                self.assertEqual(set(run.output_artifacts), {"features", "results"})
            finally:
                db.close()
                engine.dispose()

    def test_quality_run_persists_selected_report_candidates(self):
        with tempfile.TemporaryDirectory(prefix="quality-candidate-test-") as directory:
            engine = create_engine(
                "sqlite://",
                connect_args={"check_same_thread": False},
                poolclass=StaticPool,
            )
            Session = sessionmaker(bind=engine)
            Base.metadata.create_all(engine)
            db = Session()
            try:
                owner = User(username=f"quality-candidates-{uuid.uuid4().hex}", password_hash="hash")
                db.add(owner)
                db.flush()
                project = Project(name="Quality candidates", owner_id=owner.id)
                db.add(project)
                db.commit()
                artifacts = ArtifactService(db, LocalStorage(Path(directory) / "artifacts"))
                dataset = create_demo_quality_dataset(
                    db,
                    project_id=project.id,
                    row_count=24,
                    artifact_service=artifacts,
                )
                db.commit()

                run = create_quality_run_record(
                    db,
                    project_id=project.id,
                    user_id=owner.id,
                    dataset_artifact_id=dataset.id,
                    candidate_ids=["RF_v1", "GBDT_v1"],
                    artifact_service=artifacts,
                )
                db.commit()

                self.assertEqual(run.input_fingerprint["selected_candidate_ids"], ["RF_v1", "GBDT_v1"])
                self.assertEqual(execute_quality_run(db, run.id, artifact_service=artifacts).status, "completed")
                db.refresh(run)
                self.assertEqual([item["name"] for item in run.automl_results], ["RF_v1", "GBDT_v1"])
            finally:
                db.close()
                engine.dispose()

    def test_approved_snapshot_trains_a_quality_model_and_writes_report_workbook(self):
        with tempfile.TemporaryDirectory(prefix="quality-training-test-") as directory:
            engine = create_engine(
                "sqlite://",
                connect_args={"check_same_thread": False},
                poolclass=StaticPool,
            )
            Session = sessionmaker(bind=engine)
            Base.metadata.create_all(engine)
            db = Session()
            try:
                owner = User(username=f"quality-training-{uuid.uuid4().hex}", password_hash="hash")
                db.add(owner)
                db.flush()
                project = Project(name="Quality training", owner_id=owner.id)
                db.add(project)
                db.commit()
                artifacts = ArtifactService(db, LocalStorage(Path(directory) / "artifacts"))
                dataset = create_demo_quality_dataset(
                    db,
                    project_id=project.id,
                    row_count=24,
                    artifact_service=artifacts,
                )
                db.commit()
                run = create_quality_run_record(
                    db,
                    project_id=project.id,
                    user_id=owner.id,
                    dataset_artifact_id=dataset.id,
                    artifact_service=artifacts,
                )
                db.commit()
                self.assertEqual(execute_quality_run(db, run.id, artifact_service=artifacts).status, "completed")
                samples = db.query(SpotWeldQualitySample).filter(SpotWeldQualitySample.run_id == run.id).all()
                labels = []
                for sample in samples:
                    sample.current_label = sample.automatic_label
                    sample.review_status = "approved"
                    labels.append({"sample_id": str(sample.id), "label": sample.current_label, "revision_id": None, "source": "approved"})
                counts = Counter(item["label"] for item in labels)
                self.assertGreaterEqual(min(counts.values()), 5)
                snapshot = SpotWeldLabelSnapshot(
                    project_id=project.id,
                    run_id=run.id,
                    created_by_id=owner.id,
                    name="approved-for-training",
                    labels=labels,
                    label_counts=dict(counts),
                )
                db.add(snapshot)
                db.commit()

                outcome = train_label_snapshot(db, snapshot.id, artifact_service=artifacts)

                self.assertEqual(outcome.model_library.params["label_snapshot_id"], str(snapshot.id))
                self.assertEqual(outcome.model_library.params["feature_version"], "report_v1")
                self.assertEqual(outcome.model_library.params["quality_run_id"], str(run.id))
                self.assertEqual(outcome.model_library.params["label_source"], "approved")
                self.assertIn("report", outcome.output_artifacts)
                with artifacts.materialize(outcome.output_artifacts["report"], project.id, expected_type="quality_report") as report_path:
                    workbook = load_workbook(report_path, read_only=True)
                    try:
                        self.assertEqual(workbook.sheetnames, [
                            "总览", "AutoML选型", "深度学习对比", "缺陷标签",
                            "聚类画像", "特征重要性", "推理结果", "多分类评估",
                        ])
                        summary = dict(workbook["总览"].iter_rows(min_row=2, values_only=True))
                        self.assertEqual(summary["标签来源"], "approved")
                    finally:
                        workbook.close()
            finally:
                db.close()
                engine.dispose()


if __name__ == "__main__":
    unittest.main()
