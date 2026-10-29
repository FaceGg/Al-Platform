"""AST-whitelist evaluator for operator row expressions.

`generate_attributes` 之类算子历史上把用户可控表达式交给 Python 动态执行
（仅清空 builtins）——这并不是沙箱：`().__class__.__mro__` 链可取回
open/exec（2026-10-28 审计 A-01 实证容器内任意命令执行）。这里改为自写
递归求值器：只认字面量、`row` 名字、下标、算术/比较/逻辑/条件运算；
属性访问、调用、推导式、lambda 等节点一概拒绝，无任何名字解析回退。
"""

from __future__ import annotations

import ast


class UnsafeExpressionError(ValueError):
    """表达式命中白名单之外的 AST 节点或名字。"""


# 序列重复（str * n / list * n）的次数上限，防 'a' * 10**9 内存炸弹
_MAX_SEQUENCE_REPEAT = 4096
# 幂运算指数上限（禁止 9**9**9**9 塔式大整数 DoS）
_MAX_POWER_EXPONENT = 1_000_000


def evaluate_row_expression(expression: str, row: dict):
    """在白名单语义下对单行 dict 求值表达式（表达式以 `row` 引用行数据）。"""
    try:
        tree = ast.parse(expression, mode="eval")
    except (SyntaxError, ValueError) as error:
        raise UnsafeExpressionError(f"syntax_error: {error}") from error
    return _eval_node(tree.body, row)


def _eval_node(node: ast.AST, row: dict):
    if isinstance(node, ast.Constant):
        return node.value

    if isinstance(node, ast.Name):
        if node.id == "row":
            return row
        raise UnsafeExpressionError(f"unknown_name: {node.id}")

    if isinstance(node, ast.Subscript):
        target = _eval_node(node.value, row)
        if isinstance(node.slice, ast.Slice):
            lower = _eval_node(node.lower, row) if node.lower is not None else None
            upper = _eval_node(node.upper, row) if node.upper is not None else None
            step = _eval_node(node.step, row) if node.step is not None else None
            return target[lower:upper:step]
        return target[_eval_node(node.slice, row)]

    if isinstance(node, ast.BinOp):
        left = _eval_node(node.left, row)
        right = _eval_node(node.right, row)
        return _apply_binop(type(node.op).__name__, left, right)

    if isinstance(node, ast.UnaryOp):
        operand = _eval_node(node.operand, row)
        op = type(node.op).__name__
        if op == "Not":
            return not operand
        if op == "USub":
            return -operand
        if op == "UAdd":
            return +operand
        raise UnsafeExpressionError(f"forbidden_unary_op: {op}")

    if isinstance(node, ast.BoolOp):
        is_and = isinstance(node.op, ast.And)
        result = _eval_node(node.values[0], row)
        for value_node in node.values[1:]:
            if is_and and not result:
                return result
            if not is_and and result:
                return result
            result = _eval_node(value_node, row)
        return result

    if isinstance(node, ast.Compare):
        left = _eval_node(node.left, row)
        for op_node, comparator in zip(node.ops, node.comparators):
            right = _eval_node(comparator, row)
            if not _apply_compare(type(op_node).__name__, left, right):
                return False
            left = right
        return True

    if isinstance(node, ast.IfExp):
        condition = _eval_node(node.test, row)
        branch = node.body if condition else node.orelse
        return _eval_node(branch, row)

    raise UnsafeExpressionError(f"forbidden_node: {type(node).__name__}")


def _apply_binop(op: str, left, right):
    if op == "Add":
        return left + right
    if op == "Sub":
        return left - right
    if op == "Mult":
        if isinstance(left, (str, bytes, list, tuple)) or isinstance(right, (str, bytes, list, tuple)):
            repeat = right if isinstance(left, (str, bytes, list, tuple)) else left
            if not isinstance(repeat, int) or abs(repeat) > _MAX_SEQUENCE_REPEAT:
                raise UnsafeExpressionError("sequence_repeat_limit")
        return left * right
    if op == "Div":
        return left / right
    if op == "FloorDiv":
        return left // right
    if op == "Mod":
        return left % right
    if op == "Pow":
        if not isinstance(right, (int, float)) or abs(right) > _MAX_POWER_EXPONENT:
            raise UnsafeExpressionError("power_exponent_limit")
        return left ** right
    raise UnsafeExpressionError(f"forbidden_binop: {op}")


def _apply_compare(op: str, left, right) -> bool:
    if op == "Eq":
        return left == right
    if op == "NotEq":
        return left != right
    if op == "Lt":
        return left < right
    if op == "LtE":
        return left <= right
    if op == "Gt":
        return left > right
    if op == "GtE":
        return left >= right
    if op == "In":
        return left in right
    if op == "NotIn":
        return left not in right
    raise UnsafeExpressionError(f"forbidden_compare: {op}")
