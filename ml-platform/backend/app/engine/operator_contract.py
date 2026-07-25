from dataclasses import dataclass, field
from pathlib import Path
from collections.abc import Callable
from typing import Any
import math

from app.engine.base_operator import ParamSpec, PortSpec


class OperatorContractError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True)
class OperatorContext:
    run_id: str
    node_id: str
    project_id: str | None
    artifact_service: Any
    cancel_requested: Callable[[], bool]
    logger: Any
    workspace_dir: Path | None = None


@dataclass(frozen=True)
class ArtifactDraft:
    name: str
    type: str
    data: bytes | str | Path
    format: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.name.strip() or not self.type.strip():
            raise ValueError("Artifact name and type are required")


@dataclass
class OperatorResult:
    outputs: dict[str, Any]
    metrics: dict[str, float] = field(default_factory=dict)
    artifacts: list[ArtifactDraft] = field(default_factory=list)
    logs: list[dict[str, Any]] = field(default_factory=list)


def _coerce_value(spec: ParamSpec, value: Any) -> Any:
    try:
        if value is None and spec.type in {"str", "select"}:
            return None
        if spec.type == "int":
            return int(value)
        if spec.type == "float":
            return float(value)
        if spec.type == "boolean":
            if isinstance(value, str):
                return value.lower() in {"true", "1", "yes", "on"}
            return bool(value)
        if spec.type in {"str", "select"}:
            return str(value)
        return value
    except (TypeError, ValueError) as exc:
        raise OperatorContractError(
            "OPERATOR_PARAM_INVALID", f"Parameter '{spec.name}' has invalid type",
        ) from exc


def _is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _requirement_applies(spec: ParamSpec, params: dict[str, Any]) -> bool:
    if not spec.required:
        return False
    if not spec.required_when:
        return True
    for dependency, expected in spec.required_when.items():
        allowed = expected if isinstance(expected, (list, tuple, set)) else (expected,)
        if params.get(dependency) not in allowed:
            return False
    return True


def validate_operator_params(specs: list[ParamSpec], params: dict[str, Any]) -> dict[str, Any]:
    known = {spec.name for spec in specs}
    unknown = set(params) - known
    if unknown:
        raise OperatorContractError(
            "OPERATOR_PARAM_INVALID", f"Unknown parameters: {sorted(unknown)}",
        )
    validated = {}
    for spec in specs:
        value = _coerce_value(spec, params.get(spec.name, spec.default))
        validated[spec.name] = value

    for spec in specs:
        if _requirement_applies(spec, validated) and _is_blank(validated[spec.name]):
            raise OperatorContractError(
                "OPERATOR_PARAM_REQUIRED", f"Parameter '{spec.name}' is required",
            )

    for spec in specs:
        value = validated[spec.name]
        if spec.options is not None and value not in spec.options:
            raise OperatorContractError(
                "OPERATOR_PARAM_INVALID", f"Parameter '{spec.name}' is not an allowed option",
            )
        if spec.range_min is not None and value < spec.range_min:
            raise OperatorContractError(
                "OPERATOR_PARAM_INVALID", f"Parameter '{spec.name}' is below minimum",
            )
        if spec.range_max is not None and value > spec.range_max:
            raise OperatorContractError(
                "OPERATOR_PARAM_INVALID", f"Parameter '{spec.name}' is above maximum",
            )
    return validated


def validate_operator_result(outputs: list[PortSpec], result: OperatorResult) -> OperatorResult:
    if not isinstance(result, OperatorResult):
        raise OperatorContractError("OPERATOR_RESULT_INVALID", "Operator must return OperatorResult")
    declared = {port.name for port in outputs}
    actual = set(result.outputs)
    unknown = actual - declared
    if unknown:
        raise OperatorContractError(
            "OPERATOR_RESULT_INVALID", f"Unknown output ports: {sorted(unknown)}",
        )
    missing = declared - actual
    if missing:
        raise OperatorContractError(
            "OPERATOR_RESULT_INVALID", f"Missing output ports: {sorted(missing)}",
        )
    if any(not isinstance(value, (int, float)) or not math.isfinite(value) for value in result.metrics.values()):
        raise OperatorContractError("OPERATOR_RESULT_INVALID", "Metrics must be finite numbers")
    return result
