"""A-01 回归：算子行表达式的 AST 白名单求值器（审计 2026-10-28 批次九）。"""

import sys
import unittest

sys.path.insert(0, ".")

from app.engine.safe_expression import (
    UnsafeExpressionError,
    evaluate_row_expression,
)


class TestSafeExpression(unittest.TestCase):
    def test_supports_column_arithmetic_and_subscript(self):
        row = {"x": 2, "y": 3}
        self.assertEqual(evaluate_row_expression("row['x'] + row['y']", row), 5)
        self.assertEqual(evaluate_row_expression("row['x'] * 10 - 1", row), 19)

    def test_supports_compare_bool_and_conditional(self):
        row = {"x": 2}
        self.assertIs(evaluate_row_expression("row['x'] > 1", row), True)
        self.assertIs(
            evaluate_row_expression("row['x'] > 1 and row['x'] < 3", row), True,
        )
        self.assertEqual(
            evaluate_row_expression("'high' if row['x'] > 1 else 'low'", row), "high",
        )

    def test_rejects_attribute_escape_chains(self):
        # 审计 PoC 的逃逸链起点：任何属性访问都不可达
        for payload in (
            "row.__class__",
            "row['x'].__class__.__mro__",
            "().__class__.__mro__",
            "row.__class__.__init__.__globals__",
        ):
            with self.assertRaises(UnsafeExpressionError):
                evaluate_row_expression(payload, {"x": 1})

    def test_rejects_calls_imports_and_comprehensions(self):
        for payload in (
            "open('/etc/passwd')",
            "__import__('os')",
            "row.get('x')",
            "[v for v in row]",
            "(lambda: 1)()",
            "row['x'] is None",
        ):
            with self.assertRaises(UnsafeExpressionError):
                evaluate_row_expression(payload, {"x": 1})

    def test_rejects_unknown_names(self):
        with self.assertRaises(UnsafeExpressionError):
            evaluate_row_expression("__builtins__", {})
        with self.assertRaises(UnsafeExpressionError):
            evaluate_row_expression("globals()", {})

    def test_sequence_repeat_bomb_is_capped(self):
        with self.assertRaises(UnsafeExpressionError):
            evaluate_row_expression("'a' * (10 ** 9)", {})

    def test_power_tower_is_capped(self):
        with self.assertRaises(UnsafeExpressionError):
            evaluate_row_expression("9 ** 9 ** 9 ** 9", {})

    def test_syntax_error_is_reported_as_unsafe(self):
        with self.assertRaises(UnsafeExpressionError):
            evaluate_row_expression("row[", {})


class TestGenerateAttributesOperator(unittest.TestCase):
    def test_operator_rejects_escape_expression(self):
        from app.engine.registry import OperatorRegistry

        operator = OperatorRegistry.get("generate_attributes")
        with self.assertRaises(ValueError) as raised:
            operator.execute(
                None,
                {"data": [{"x": 1}]},
                {
                    "new_column_name": "z",
                    "expression": "row['x'].__class__.__mro__",
                },
            )
        self.assertIn("Expression evaluation failed", str(raised.exception))

    def test_operator_keeps_legitimate_expression(self):
        from app.engine.registry import OperatorRegistry

        operator = OperatorRegistry.get("generate_attributes")
        result = operator.execute(
            None,
            {"data": [{"x": 1, "y": 2}]},
            {"new_column_name": "z", "expression": "row['x'] + row['y']"},
        )
        self.assertEqual(result.outputs["data"][0]["z"], 3)


if __name__ == "__main__":
    unittest.main()
