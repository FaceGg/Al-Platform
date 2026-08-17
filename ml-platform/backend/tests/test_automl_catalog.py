"""Generic AutoML algorithm-family catalog contract tests."""

import unittest
from unittest.mock import patch

from app.services.automl_catalog import (
    AUTOML_FAMILY_IDS,
    AlgorithmUnavailable,
    get_algorithm_family,
    list_algorithm_families,
    resolve_algorithm_families,
)


class TestAutoMLCatalog(unittest.TestCase):
    def test_catalog_contains_exactly_seven_unique_families(self):
        self.assertEqual(AUTOML_FAMILY_IDS, (
            "lightgbm", "xgboost", "catboost", "gbdt",
            "random_forest", "extra_trees", "hist_gradient_boosting",
        ))
        self.assertEqual(len(list_algorithm_families()), 7)
        self.assertEqual(len(set(AUTOML_FAMILY_IDS)), 7)

    def test_every_family_defines_both_tasks_and_resource(self):
        for family in list_algorithm_families():
            self.assertTrue(family.grid)
            self.assertTrue(family.search_space)
            self.assertIn(family.resource_parameter, family.search_space)
            classifier = family.build("classification", family.default_params)
            regressor = family.build("regression", family.default_params)
            self.assertTrue(callable(getattr(classifier, "fit", None)))
            self.assertTrue(callable(getattr(classifier, "predict", None)))
            self.assertTrue(callable(getattr(classifier, "predict_proba", None)))
            self.assertTrue(callable(getattr(regressor, "fit", None)))
            self.assertTrue(callable(getattr(regressor, "predict", None)))

    def test_optional_family_never_falls_back_to_another_algorithm(self):
        family = get_algorithm_family("lightgbm")
        with patch("app.services.automl_catalog.import_module", side_effect=ImportError):
            with self.assertRaises(AlgorithmUnavailable) as raised:
                family.build("classification", family.default_params)
        self.assertEqual(raised.exception.code, "AUTOML_ALGORITHM_UNAVAILABLE")

    def test_unknown_and_duplicate_family_ids_are_rejected(self):
        with self.assertRaises(ValueError):
            get_algorithm_family("unknown")
        with self.assertRaises(ValueError):
            resolve_algorithm_families(["gbdt", "gbdt"])


if __name__ == "__main__":
    unittest.main()
