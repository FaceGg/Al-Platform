"""Optuna-backed generic AutoML search service tests."""

import unittest

import numpy as np
from optuna.pruners import HyperbandPruner, NopPruner
from optuna.samplers import GridSampler, NSGAIISampler, RandomSampler, TPESampler

from app.services.automl_catalog import get_algorithm_family
from app.services.automl_search import (
    FamilySearchResult,
    SearchConfig,
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

    def test_winner_selection_is_score_then_catalog_order(self):
        winner = choose_family_winner([
            FamilySearchResult(
                algorithm_id="random_forest", display_name="Random Forest",
                catalog_index=4, status="completed", best_score=0.9,
            ),
            FamilySearchResult(
                algorithm_id="gbdt", display_name="GBDT",
                catalog_index=3, status="completed", best_score=0.9,
            ),
        ])
        self.assertEqual(winner.algorithm_id, "gbdt")

    def test_invalid_search_configuration_is_rejected(self):
        with self.assertRaises(ValueError):
            SearchConfig(method="unknown", max_trials=5, timeout_seconds=1)
        with self.assertRaises(ValueError):
            SearchConfig(method="random", max_trials=0, timeout_seconds=1)


if __name__ == "__main__":
    unittest.main()
