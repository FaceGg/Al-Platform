"""Tests for optimization operators (optimize_grid, optimize_evolutionary).

These operators had no dedicated tests previously. We verify existence,
metadata, happy-path execution on a small dataset, and error paths.
"""
import json
import sys
import unittest

sys.path.insert(0, ".")

# Import via app.main to trigger operator registration
from app.main import app  # noqa: F401
from app.engine.registry import OperatorRegistry
from tests.operator_test_utils import execute_operator


def _classification_records():
    """Build a small linearly separable classification dataset."""
    rows = []
    for index in range(40):
        rows.append({
            "feature": float(index),
            "target": 0 if index < 20 else 1,
        })
    return rows


class TestOptimizationOperatorRegistration(unittest.TestCase):
    """Verify the optimization operators are registered with correct metadata."""

    def test_optimize_grid_registered(self):
        op = OperatorRegistry.get("optimize_grid")
        self.assertIsNotNone(op)
        self.assertEqual(op.category, "optimization")

    def test_optimize_evolutionary_registered(self):
        op = OperatorRegistry.get("optimize_evolutionary")
        self.assertIsNotNone(op)
        self.assertEqual(op.category, "optimization")

    def test_optimize_grid_outputs(self):
        op = OperatorRegistry.get("optimize_grid")
        output_names = {port.name for port in op.outputs}
        self.assertEqual(output_names, {"best_params", "best_score"})

    def test_optimize_grid_parameters(self):
        op = OperatorRegistry.get("optimize_grid")
        param_names = {param.name for param in op.parameters}
        self.assertEqual(
            param_names,
            {"target_column", "model_type", "param_grid", "cv_folds", "scoring"},
        )


class TestGridSearchOptimizeExecution(unittest.TestCase):
    """Execution-path tests for GridSearchOptimize."""

    def test_execute_returns_best_params_and_score(self):
        op = OperatorRegistry.get("optimize_grid")
        params = {
            "target_column": "target",
            "model_type": "decision_tree",
            "param_grid": json.dumps({"max_depth": [3, 5, 10]}),
            "cv_folds": 3,
            "scoring": "accuracy",
        }
        outputs = execute_operator(op, {"data": _classification_records()}, params)

        self.assertIn("best_params", outputs)
        self.assertIn("best_score", outputs)
        self.assertIsInstance(outputs["best_params"], list)
        self.assertGreaterEqual(len(outputs["best_params"]), 1)
        best_score = outputs["best_score"][0]["score"]
        self.assertIsInstance(best_score, float)

    def test_execute_falls_back_when_param_grid_invalid(self):
        op = OperatorRegistry.get("optimize_grid")
        params = {
            "target_column": "target",
            "model_type": "decision_tree",
            "param_grid": "not-valid-json",
            "cv_folds": 3,
            "scoring": "accuracy",
        }
        outputs = execute_operator(op, {"data": _classification_records()}, params)
        # Falls back to a default grid, so still produces valid output.
        self.assertIsInstance(outputs["best_params"], list)

    def test_execute_raises_when_target_missing(self):
        op = OperatorRegistry.get("optimize_grid")
        with self.assertRaises(RuntimeError) as ctx:
            execute_operator(op, {"data": _classification_records()}, {
                "target_column": "nonexistent",
                "model_type": "decision_tree",
                "param_grid": "{}",
                "cv_folds": 3,
            })
        self.assertIn("Target column", str(ctx.exception))


class TestEvolutionaryOptimizeExecution(unittest.TestCase):
    """Execution-path tests for EvolutionaryOptimize."""

    def test_execute_returns_params_and_score(self):
        op = OperatorRegistry.get("optimize_evolutionary")
        params = {
            "target_column": "target",
            "model_type": "random_forest",
            "population_size": 5,
            "generations": 1,
            "mutation_rate": 0.1,
            "scoring": "accuracy",
        }
        outputs = execute_operator(op, {"data": _classification_records()}, params)
        self.assertIn("best_params", outputs)
        self.assertIn("best_score", outputs)
        self.assertIsInstance(outputs["best_score"], list)
        self.assertEqual(len(outputs["best_score"]), 1)

    def test_execute_raises_when_target_missing(self):
        op = OperatorRegistry.get("optimize_evolutionary")
        with self.assertRaises(RuntimeError):
            execute_operator(op, {"data": _classification_records()}, {
                "target_column": "missing_col",
                "model_type": "random_forest",
                "population_size": 5,
                "generations": 1,
            })


if __name__ == "__main__":
    unittest.main()
