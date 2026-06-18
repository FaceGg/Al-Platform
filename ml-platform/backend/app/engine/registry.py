from __future__ import annotations

from typing import Any

from app.engine.base_operator import BaseOperator


class OperatorRegistry:
    _operators: dict[str, BaseOperator] = {}

    @classmethod
    def register(cls, op: BaseOperator) -> None:
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
