"""Generic AutoML algorithm-family catalog contract tests."""

import unittest
from unittest.mock import patch

from app.services.automl_catalog import (
    AUTOML_FAMILY_IDS,
    AlgorithmUnavailable,
    family_for_strength,
    get_algorithm_family,
    list_algorithm_families,
    resolve_algorithm_families,
)


class TestAutoMLCatalog(unittest.TestCase):
    def test_catalog_contains_exactly_eight_unique_families(self):
        self.assertEqual(AUTOML_FAMILY_IDS, (
            "lightgbm", "xgboost", "catboost", "gbdt",
            "random_forest", "extra_trees", "hist_gradient_boosting", "mlp",
        ))
        self.assertEqual(len(list_algorithm_families()), 8)
        self.assertEqual(len(set(AUTOML_FAMILY_IDS)), 8)

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


class TestFamilyForStrength(unittest.TestCase):
    """搜索强度按族收窄搜索空间:资源预算 + 连续区间 + 离散候选。"""

    def setUp(self):
        self.mlp = get_algorithm_family("mlp")

    def test_ultra_is_identity(self):
        narrowed = family_for_strength(self.mlp, "ultra")
        self.assertEqual(narrowed.search_space, self.mlp.search_space)
        self.assertEqual(narrowed.grid, self.mlp.grid)
        self.assertEqual(narrowed.max_resource, self.mlp.max_resource)

    def test_strength_monotonically_narrows_space(self):
        highs = {}
        for strength in ("light", "medium", "high", "ultra"):
            f = family_for_strength(self.mlp, strength)
            hidden = f.search_space["hidden_layers"].choices
            lr_high = f.search_space["learning_rate_init"].high
            iter_high = f.search_space["max_iter"].high
            # 隐藏层候选随强度单调增加,且都保留推荐前缀(含最小网络)
            self.assertTrue(hidden[0] == "64")
            highs[strength] = (len(hidden), lr_high, iter_high)
        self.assertLess(highs["light"][0], highs["medium"][0])
        self.assertLess(highs["medium"][0], highs["high"][0])
        self.assertEqual(highs["ultra"][0], 4)
        # 学习率与训练轮数上限单调放宽,ultra 等于全区间
        self.assertLess(highs["light"][1], highs["ultra"][1])
        self.assertLess(highs["light"][2], highs["ultra"][2])
        self.assertEqual(highs["ultra"][2], 600)

    def test_light_keeps_conservative_prefix_and_resource_budget(self):
        light = family_for_strength(self.mlp, "light")
        hidden = light.search_space["hidden_layers"].choices
        self.assertIn("64", hidden)
        self.assertNotIn("256,128,64", hidden)
        lr = light.search_space["learning_rate_init"]
        self.assertEqual(lr.low, 0.0001)
        self.assertLess(lr.high, 0.1)
        alpha = light.search_space["alpha"]
        self.assertLess(alpha.high, 0.1)
        max_iter = light.search_space["max_iter"]
        self.assertEqual(max_iter.low, 80)
        self.assertLess(max_iter.high, 600)
        # 资源上限收窄同步到家族 max_resource(multi_fidelity 阶梯随之收窄)
        self.assertEqual(light.max_resource, max_iter.high)
        self.assertEqual(light.min_resource, self.mlp.min_resource)

    def test_grid_candidates_follow_same_narrowing_rule(self):
        light = family_for_strength(self.mlp, "light")
        for name, values in light.grid.items():
            self.assertLessEqual(len(values), len(self.mlp.grid[name]))

    def test_invalid_strength_rejected(self):
        with self.assertRaises(ValueError):
            family_for_strength(self.mlp, "extreme")

    def test_narrowed_family_still_builds_estimator(self):
        light = family_for_strength(self.mlp, "light")
        estimator = light.build("classification", dict(light.default_params))
        self.assertIsNotNone(estimator)


if __name__ == "__main__":
    unittest.main()
