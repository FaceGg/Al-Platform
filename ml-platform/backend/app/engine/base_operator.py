from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.engine.operator_contract import OperatorContext, OperatorResult


@dataclass
class PortSpec:
    name: str
    type: str
    label: str
    required_columns: tuple[str, ...] = ()


@dataclass
class ParamSpec:
    name: str
    type: str
    default: Any = None
    label: str = ""
    options: list[str] | None = None
    range_min: float | None = None
    range_max: float | None = None
    required: bool = False
    required_when: dict[str, Any] | None = None


class BaseOperator(ABC):
    id: str = ""
    name: str = ""
    category: str = ""
    description: str = ""
    version: str = "1.0"
    inputs: list[PortSpec] = []
    outputs: list[PortSpec] = []
    parameters: list[ParamSpec] = []

    @abstractmethod
    def validate(self, inputs: dict) -> bool:
        ...

    @abstractmethod
    def execute(
        self, context: "OperatorContext", inputs: dict, params: dict,
    ) -> "OperatorResult":
        ...

    def get_preview(self, outputs: dict) -> dict:
        return {}
