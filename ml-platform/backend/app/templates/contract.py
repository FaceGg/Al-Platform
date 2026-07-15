from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.engine.operator_contract import OperatorContractError, validate_operator_params
from app.engine.registry import OperatorRegistry


class TemplateContractError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True)
class TemplateNode:
    key: str
    operator_id: str
    label: str
    position_x: float
    position_y: float
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TemplateEdge:
    source: str
    source_port: str
    target: str
    target_port: str


@dataclass(frozen=True)
class TemplateParameter:
    key: str
    label: str
    type: str
    default: Any
    node_params: tuple[tuple[str, str], ...]
    required: bool = False


@dataclass(frozen=True)
class TemplateExpectedOutput:
    node_key: str
    port: str


@dataclass(frozen=True)
class IndustrialTemplate:
    id: str
    name: str
    description: str
    scenario: str
    task_type: str
    target_column: str
    required_columns: tuple[str, ...]
    nodes: tuple[TemplateNode, ...]
    edges: tuple[TemplateEdge, ...]
    parameters: tuple[TemplateParameter, ...]
    expected_outputs: tuple[TemplateExpectedOutput, ...]


def validate_template(template: IndustrialTemplate) -> IndustrialTemplate:
    node_map: dict[str, TemplateNode] = {}
    operator_map = {}
    for node in template.nodes:
        if node.key in node_map:
            raise TemplateContractError(
                "TEMPLATE_NODE_DUPLICATE", f"Duplicate node key '{node.key}'",
            )
        operator = OperatorRegistry.get(node.operator_id)
        if operator is None:
            raise TemplateContractError(
                "TEMPLATE_OPERATOR_UNKNOWN", f"Unknown operator '{node.operator_id}'",
            )
        try:
            validate_operator_params(operator.parameters, node.params)
        except OperatorContractError as exc:
            raise TemplateContractError(
                "TEMPLATE_PARAM_INVALID", f"Node '{node.key}': {exc}",
            ) from exc
        node_map[node.key] = node
        operator_map[node.key] = operator

    incoming_ports: dict[str, set[str]] = {key: set() for key in node_map}
    for edge in template.edges:
        if edge.source not in node_map or edge.target not in node_map:
            raise TemplateContractError(
                "TEMPLATE_NODE_UNKNOWN", f"Edge references an unknown node: {edge}",
            )
        source_ports = {port.name for port in operator_map[edge.source].outputs}
        target_ports = {port.name for port in operator_map[edge.target].inputs}
        if edge.source_port not in source_ports or edge.target_port not in target_ports:
            raise TemplateContractError(
                "TEMPLATE_PORT_UNKNOWN", f"Edge references an unknown port: {edge}",
            )
        incoming_ports[edge.target].add(edge.target_port)

    for node_key, operator in operator_map.items():
        required = {port.name for port in operator.inputs}
        missing = required - incoming_ports[node_key]
        if missing:
            raise TemplateContractError(
                "TEMPLATE_INPUT_MISSING", f"Node '{node_key}' is missing inputs {sorted(missing)}",
            )

    parameter_keys = set()
    for parameter in template.parameters:
        if parameter.key in parameter_keys:
            raise TemplateContractError(
                "TEMPLATE_PARAMETER_DUPLICATE", f"Duplicate parameter '{parameter.key}'",
            )
        parameter_keys.add(parameter.key)
        for node_key, param_name in parameter.node_params:
            if node_key not in operator_map:
                raise TemplateContractError(
                    "TEMPLATE_NODE_UNKNOWN", f"Parameter references unknown node '{node_key}'",
                )
            known_params = {spec.name for spec in operator_map[node_key].parameters}
            if param_name not in known_params:
                raise TemplateContractError(
                    "TEMPLATE_PARAM_INVALID",
                    f"Parameter '{parameter.key}' references unknown field '{node_key}.{param_name}'",
                )

    for expected in template.expected_outputs:
        if expected.node_key not in operator_map:
            raise TemplateContractError(
                "TEMPLATE_OUTPUT_INVALID", f"Output references unknown node '{expected.node_key}'",
            )
        outputs = {port.name for port in operator_map[expected.node_key].outputs}
        if expected.port not in outputs:
            raise TemplateContractError(
                "TEMPLATE_OUTPUT_INVALID",
                f"Output references unknown port '{expected.node_key}.{expected.port}'",
            )
    return template
