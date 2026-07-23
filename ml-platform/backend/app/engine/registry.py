from __future__ import annotations

import copy
from functools import wraps
from typing import Any

from app.engine.base_operator import BaseOperator, PortSpec


class OperatorRegistry:
    _operators: dict[str, BaseOperator] = {}

    @classmethod
    def register(cls, op: BaseOperator) -> None:
        op = _with_raw_outputs(op)
        cls._operators[op.id] = op

    @classmethod
    def get(cls, op_id: str) -> BaseOperator | None:
        return cls._operators.get(op_id)

    @classmethod
    def list_all(cls) -> list[BaseOperator]:
        return list(cls._operators.values())

    @classmethod
    def list_by_category(cls, category: str) -> list[BaseOperator]:
        return [op for op in cls._operators.values() if op.category == category]


def register_operator(op_cls: type[BaseOperator]) -> BaseOperator:
    instance = op_cls()
    OperatorRegistry.register(instance)
    return instance


def _with_raw_outputs(op: BaseOperator) -> BaseOperator:
    """Add raw input ports and snapshot them around processing/blending execution."""
    if op.category not in {"processing", "blending"}:
        return op
    if getattr(op, "_raw_outputs_wrapped", False):
        return op

    # Operators commonly keep metadata as class-level lists. Clone them before
    # extending so registration does not mutate a class or another instance.
    op.inputs = list(op.inputs)
    op.outputs = list(op.outputs)
    declared_names = {port.name for port in op.outputs}
    if op.category == "processing":
        raw_names = ["raw_data"]
    else:
        raw_names = [f"raw_{port.name}" for port in op.inputs]

    for name in raw_names:
        if name not in declared_names:
            op.outputs.append(PortSpec(name, "DataTable", "Raw input"))
            declared_names.add(name)

    original_execute = op.execute

    @wraps(original_execute)
    def execute(context, inputs, params):
        snapshot = copy.deepcopy(inputs)
        # Operators must not be able to mutate the caller's input while they
        # transform data. Keep a second copy for execution so the snapshot
        # remains untouched even when an operator mutates its argument.
        result = original_execute(context, copy.deepcopy(snapshot), params)
        if op.category == "processing":
            raw_outputs = {"raw_data": copy.deepcopy(snapshot.get("data", []))}
        else:
            raw_outputs = {
                f"raw_{port.name}": copy.deepcopy(snapshot.get(port.name, []))
                for port in op.inputs
            }
        result.outputs = {**result.outputs, **raw_outputs}
        return result

    op.execute = execute
    op._raw_outputs_wrapped = True
    return op
