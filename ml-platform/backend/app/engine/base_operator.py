from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class PortSpec:
    name: str
    type: str
    label: str


@dataclass
class ParamSpec:
    name: str
    type: str
    default: Any = None
    label: str = ""
    options: list[str] | None = None
    range_min: float | None = None
    range_max: float | None = None


class BaseOperator(ABC):
    id: str = ""
    name: str = ""
    category: str = ""
    description: str = ""
    version: str = "1.0"
    inputs: list[PortSpec] = field(default_factory=list)
    outputs: list[PortSpec] = field(default_factory=list)
    parameters: list[ParamSpec] = field(default_factory=list)

    @abstractmethod
    def validate(self, inputs: dict) -> bool:
        ...

    @abstractmethod
    def execute(self, inputs: dict, params: dict) -> dict:
        ...

    def get_preview(self, outputs: dict) -> dict:
        return {}
