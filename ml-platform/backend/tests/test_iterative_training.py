import io
import math
import unittest

import joblib
import numpy as np
import pandas as pd

from app.services.iterative_training import (
    IncompatibleCheckpoint,
    IterativeTrainer,
    TrainingCheckpoint,
    TrainingConfig,
)


def classification_frame(rows=120):
    rng = np.random.default_rng(42)
    current = rng.normal(8.0, 1.0, rows)
    force = rng.normal(3.0, 0.5, rows)
    quality = (current + force * 0.8 > 10.3).astype(int)
    return pd.DataFrame({"current": current, "force": force, "quality": quality})


def regression_frame(rows=120):
    rng = np.random.default_rng(7)
    current = rng.normal(8.0, 1.0, rows)
    force = rng.normal(3.0, 0.5, rows)
    strength = current * 1.7 + force * 2.3 + rng.normal(0, 0.05, rows)
    return pd.DataFrame({"current": current, "force": force, "strength": strength})


class TestIterativeTrainer(unittest.TestCase):
    def setUp(self):
        self.trainer = IterativeTrainer()

    def test_classification_records_finite_epoch_metrics_and_early_stops(self):
        metrics = []
        checkpoints = []
        result = self.trainer.fit(
            classification_frame(),
            target_column="quality",
            config=TrainingConfig(
                task="classification",
                total_epochs=20,
                monitor="val_accuracy",
                mode="max",
                patience=2,
                min_delta=1.0,
                checkpoint_interval=5,
            ),
            metric_callback=metrics.append,
            checkpoint_callback=checkpoints.append,
            cancel_requested=lambda: False,
        )

        self.assertGreaterEqual(len(metrics), 2)
        self.assertLess(result.epochs_completed, 20)
        self.assertTrue(result.stopped_early)
        self.assertFalse(result.cancelled)
        self.assertEqual(result.model_state.epoch, result.epochs_completed)
        for epoch in metrics:
            self.assertEqual(
                set(epoch.values),
                {"train_loss", "val_loss", "val_accuracy"},
            )
            self.assertTrue(all(math.isfinite(value) for value in epoch.values.values()))
        restored = TrainingCheckpoint.loads(checkpoints[-1].payload)
        self.assertEqual(restored.format_version, 1)

    def test_regression_records_r2_rmse_and_losses(self):
        metrics = []
        result = self.trainer.fit(
            regression_frame(),
            target_column="strength",
            config=TrainingConfig(
                task="regression",
                total_epochs=3,
                monitor="val_r2",
                mode="max",
                patience=10,
            ),
            metric_callback=metrics.append,
        )

        self.assertEqual(result.epochs_completed, 3)
        self.assertEqual(
            set(metrics[-1].values),
            {"train_loss", "val_loss", "val_r2", "val_rmse"},
        )
        self.assertTrue(all(math.isfinite(value) for value in metrics[-1].values.values()))

    def test_restore_best_uses_model_from_best_checkpoint(self):
        checkpoints = []
        result = self.trainer.fit(
            classification_frame(),
            target_column="quality",
            config=TrainingConfig(
                task="classification",
                total_epochs=5,
                monitor="val_accuracy",
                mode="max",
                patience=3,
                min_delta=1.0,
                restore_best=True,
            ),
            checkpoint_callback=checkpoints.append,
        )
        best = TrainingCheckpoint.loads(
            next(item.payload for item in checkpoints if item.is_best)
        )

        np.testing.assert_allclose(result.model.coef_, best.model.coef_)
        self.assertEqual(result.best_epoch, best.epoch)

    def test_cancellation_emits_final_checkpoint_and_stops_after_metrics(self):
        metrics = []
        checkpoints = []
        result = self.trainer.fit(
            classification_frame(),
            target_column="quality",
            config=TrainingConfig(
                task="classification",
                total_epochs=10,
                monitor="val_accuracy",
                mode="max",
                patience=10,
                checkpoint_interval=4,
            ),
            metric_callback=metrics.append,
            checkpoint_callback=checkpoints.append,
            cancel_requested=lambda: len(metrics) >= 2,
        )

        self.assertTrue(result.cancelled)
        self.assertEqual(result.epochs_completed, 2)
        self.assertEqual(checkpoints[-1].epoch, 2)

    def test_checkpoint_interval_always_includes_best_and_final_epochs(self):
        checkpoints = []
        result = self.trainer.fit(
            classification_frame(),
            target_column="quality",
            config=TrainingConfig(
                task="classification",
                total_epochs=5,
                monitor="val_accuracy",
                mode="max",
                patience=10,
                min_delta=1.0,
                checkpoint_interval=2,
                restore_best=False,
            ),
            checkpoint_callback=checkpoints.append,
        )

        self.assertEqual(result.epochs_completed, 5)
        self.assertEqual([item.epoch for item in checkpoints], [1, 2, 4, 5])
        self.assertTrue(checkpoints[0].is_best)
        self.assertFalse(checkpoints[-1].is_best)

    def test_checkpoint_serialization_preserves_schema_and_lineage(self):
        checkpoints = []
        self.trainer.fit(
            classification_frame(),
            target_column="quality",
            config=TrainingConfig(
                task="classification",
                total_epochs=1,
                monitor="val_accuracy",
                mode="max",
                patience=2,
            ),
            checkpoint_callback=checkpoints.append,
            dataset_artifact_id="dataset-1",
            source_job_id="job-1",
            source_run_id="run-1",
        )
        restored = TrainingCheckpoint.loads(checkpoints[-1].payload)

        self.assertEqual(restored.dataset_artifact_id, "dataset-1")
        self.assertEqual(restored.source_job_id, "job-1")
        self.assertEqual(restored.source_run_id, "run-1")
        self.assertEqual([item[0] for item in restored.feature_schema], ["current", "force"])
        self.assertEqual(restored.target_schema["name"], "quality")

    def test_incompatible_checkpoint_version_is_rejected(self):
        stream = io.BytesIO()
        joblib.dump({"format_version": 999}, stream)

        with self.assertRaises(IncompatibleCheckpoint):
            TrainingCheckpoint.loads(stream.getvalue())

    def test_resume_preserves_no_improvement_patience(self):
        checkpoints = []
        config = TrainingConfig(
            task="classification",
            total_epochs=2,
            monitor="val_accuracy",
            mode="max",
            patience=2,
            min_delta=1.0,
            checkpoint_interval=1,
        )
        self.trainer.fit(
            classification_frame(),
            target_column="quality",
            config=config,
            checkpoint_callback=checkpoints.append,
        )
        checkpoint = TrainingCheckpoint.loads(checkpoints[-1].payload)
        self.assertEqual(checkpoint.no_improvement_count, 1)

        resumed = self.trainer.fit(
            classification_frame(),
            target_column="quality",
            config=TrainingConfig(
                task="classification",
                total_epochs=5,
                monitor="val_accuracy",
                mode="max",
                patience=2,
                min_delta=1.0,
                checkpoint_interval=1,
            ),
            resume_from=checkpoint,
        )
        self.assertTrue(resumed.stopped_early)
        self.assertEqual(resumed.epochs_completed, 3)


if __name__ == "__main__":
    unittest.main()
