"""Optuna-backed generic AutoML search service tests."""

import unittest
from datetime import timedelta
from types import SimpleNamespace

import numpy as np
from optuna.pruners import HyperbandPruner, NopPruner
from optuna.samplers import GridSampler, NSGAIISampler, RandomSampler, TPESampler

from app.services.automl_catalog import get_algorithm_family
from app.services.automl_search import (
    FamilySearchResult,
    SearchConfig,
    automl_metric_order_key,
    trial_metric_sort_key,
    build_optuna_components,
    choose_family_winner,
    run_family_search,
)


class TestAutoMLSearch(unittest.TestCase):
    def setUp(self):
        self.features = np.asarray([
            [index % 11, (index * 3) % 7, index % 5]
            for index in range(80)
        ], dtype=float)
        self.classification_target = np.asarray([
            int((index % 11) + ((index * 3) % 7) > 8)
            for index in range(80)
        ])

    def test_five_methods_map_to_expected_optuna_components(self):
        cases = {
            "grid": (GridSampler, NopPruner),
            "random": (RandomSampler, NopPruner),
            "bayesian": (TPESampler, NopPruner),
            "evolutionary": (NSGAIISampler, NopPruner),
            "multi_fidelity": (TPESampler, HyperbandPruner),
        }
        for method, expected in cases.items():
            sampler, pruner = build_optuna_components(
                method, {"max_depth": (2, 3)}, 10, 100, 5,
            )
            self.assertIsInstance(sampler, expected[0])
            self.assertIsInstance(pruner, expected[1])

    def test_family_search_reports_every_terminal_trial(self):
        progress = []
        result = run_family_search(
            family=get_algorithm_family("random_forest"),
            task="classification",
            features=self.features,
            target=self.classification_target,
            evaluation={"cross_validation_enabled": False, "cross_validation_folds": None},
            config=SearchConfig(method="random", max_trials=5, timeout_seconds=30),
            catalog_index=4,
            progress_callback=progress.append,
        )
        self.assertEqual(
            result.completed_trials + result.pruned_trials + result.failed_trials,
            5,
        )
        self.assertEqual(len(progress), 5)
        self.assertIsNotNone(result.best_estimator)
        self.assertIsNotNone(result.best_score)

    def test_multi_fidelity_records_resource_rungs(self):
        result = run_family_search(
            family=get_algorithm_family("hist_gradient_boosting"),
            task="classification",
            features=self.features,
            target=self.classification_target,
            evaluation={"cross_validation_enabled": False, "cross_validation_folds": None},
            config=SearchConfig(method="multi_fidelity", max_trials=5, timeout_seconds=30),
            catalog_index=6,
        )
        self.assertGreater(result.completed_trials + result.pruned_trials, 0)
        self.assertTrue(any(summary.intermediate_scores for summary in result.trials))

    def test_winner_selection_is_metrics_then_duration_then_catalog_order(self):
        winner = choose_family_winner([
            FamilySearchResult(
                algorithm_id="random_forest", display_name="Random Forest",
                catalog_index=4, status="completed", best_score=0.99, auc=0.90, f1=0.95,
                training_time_seconds=1.0,
            ),
            FamilySearchResult(
                algorithm_id="gbdt", display_name="GBDT",
                catalog_index=3, status="completed", best_score=0.80, auc=0.92, f1=0.70,
                training_time_seconds=9.0,
            ),
        ])
        self.assertEqual(winner.algorithm_id, "gbdt")
        winner = choose_family_winner([
            FamilySearchResult("slow", "Slow", 0, "completed", best_score=0.90, auc=0.92, f1=0.85, training_time_seconds=8.0),
            FamilySearchResult("fast", "Fast", 1, "completed", best_score=0.90, auc=0.92, f1=0.85, training_time_seconds=2.0),
        ])
        self.assertEqual(winner.algorithm_id, "fast")

        winner = choose_family_winner([
            FamilySearchResult("slightly_slow", "Slightly slow", 0, "completed", best_score=0.90004, auc=0.92004, f1=0.85004, training_time_seconds=8.0),
            FamilySearchResult("slightly_fast", "Slightly fast", 1, "completed", best_score=0.90003, auc=0.92003, f1=0.85003, training_time_seconds=2.0),
        ])
        self.assertEqual(winner.algorithm_id, "slightly_fast")

    def test_result_order_is_auc_f1_accuracy_descending_then_duration_ascending(self):
        rows = [
            {"name": "slower", "auc": 0.92, "f1": 0.85, "accuracy": 0.90, "duration": 8.0, "index": 0},
            {"name": "lower_accuracy", "auc": 0.92, "f1": 0.85, "accuracy": 0.89, "duration": 1.0, "index": 1},
            {"name": "faster", "auc": 0.92, "f1": 0.85, "accuracy": 0.90, "duration": 2.0, "index": 2},
            {"name": "lower_f1", "auc": 0.92, "f1": 0.84, "accuracy": 0.99, "duration": 1.0, "index": 3},
            {"name": "lower_auc", "auc": 0.91, "f1": 0.99, "accuracy": 0.99, "duration": 1.0, "index": 4},
        ]
        ordered = sorted(rows, key=lambda item: automl_metric_order_key(
            auc=item["auc"], f1=item["f1"], accuracy=item["accuracy"],
            duration=item["duration"], catalog_index=item["index"],
        ))
        self.assertEqual(
            [item["name"] for item in ordered],
            ["faster", "slower", "lower_accuracy", "lower_f1", "lower_auc"],
        )

    def test_trial_selection_uses_auc_f1_accuracy_then_duration(self):
        def trial(number, *, auc, f1, accuracy, duration):
            return SimpleNamespace(
                number=number,
                value=accuracy,
                duration=timedelta(seconds=duration),
                user_attrs={"auc": auc, "f1": f1, "accuracy": accuracy},
            )

        trials = [
            trial(0, auc=1.0, f1=1.0, accuracy=1.0, duration=8.0),
            trial(1, auc=1.0, f1=1.0, accuracy=1.0, duration=2.0),
            trial(2, auc=0.99, f1=1.0, accuracy=1.0, duration=1.0),
        ]
        self.assertEqual(max(trials, key=trial_metric_sort_key).number, 1)

    def test_classification_trials_record_auc_f1_and_accuracy(self):
        result = run_family_search(
            family=get_algorithm_family("random_forest"), task="classification",
            features=self.features, target=self.classification_target,
            evaluation={"cross_validation_enabled": False, "cross_validation_folds": None},
            config=SearchConfig(method="random", max_trials=2, timeout_seconds=30), catalog_index=0,
        )
        completed = [trial for trial in result.trials if trial.state == "complete"]
        self.assertTrue(completed)
        self.assertTrue(all(trial.auc is not None for trial in completed))
        self.assertTrue(all(trial.f1 is not None for trial in completed))
        self.assertTrue(all(trial.accuracy is not None for trial in completed))
        self.assertTrue(all(trial.accuracy == trial.score for trial in completed))

    def test_invalid_search_configuration_is_rejected(self):
        with self.assertRaises(ValueError):
            SearchConfig(method="unknown", max_trials=5, timeout_seconds=1)
        with self.assertRaises(ValueError):
            SearchConfig(method="random", max_trials=0, timeout_seconds=1)


if __name__ == "__main__":
    unittest.main()
