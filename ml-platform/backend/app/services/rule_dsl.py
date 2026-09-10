"""Small, typed rule expression evaluator for automatic annotation."""

from __future__ import annotations

from collections.abc import Mapping


class RuleEvaluationError(ValueError):
    pass


def _compare(operator: str, actual: object, expected: object) -> bool:
    if operator in {"eq", "=="}:
        return actual == expected
    if operator in {"neq", "!=", "ne"}:
        return actual != expected
    if operator in {"gt", ">"}:
        return actual is not None and actual > expected
    if operator in {"gte", ">="}:
        return actual is not None and actual >= expected
    if operator in {"lt", "<"}:
        return actual is not None and actual < expected
    if operator in {"lte", "<="}:
        return actual is not None and actual <= expected
    if operator == "in":
        if not isinstance(expected, (list, tuple, set, frozenset)):
            raise RuleEvaluationError("in expects a sequence")
        return actual in expected
    if operator == "not_in":
        if not isinstance(expected, (list, tuple, set, frozenset)):
            raise RuleEvaluationError("not_in expects a sequence")
        return actual not in expected
    if operator == "is_null":
        return actual is None
    if operator == "not_null":
        return actual is not None
    raise RuleEvaluationError(f"unsupported operator: {operator}")


def evaluate_rule(expression: Mapping[str, object], row: Mapping[str, object]) -> bool:
    """Evaluate a JSON-compatible expression against one flat row.

    A mapping of column -> {operator: value} is implicitly ANDed. ``all`` and
    ``any`` accept lists of nested expressions; ``not`` accepts one expression.
    """
    if not isinstance(expression, Mapping):
        raise RuleEvaluationError("rule expression must be an object")
    if "all" in expression:
        items = expression["all"]
        if not isinstance(items, (list, tuple)):
            raise RuleEvaluationError("all expects a list")
        return all(evaluate_rule(item, row) for item in items)
    if "any" in expression:
        items = expression["any"]
        if not isinstance(items, (list, tuple)):
            raise RuleEvaluationError("any expects a list")
        return any(evaluate_rule(item, row) for item in items)
    if "not" in expression:
        return not evaluate_rule(expression["not"], row)

    for column, condition in expression.items():
        if not isinstance(condition, Mapping):
            condition = {"eq": condition}
        actual = row.get(column)
        for operator, expected in condition.items():
            if not _compare(str(operator), actual, expected):
                return False
    return True
