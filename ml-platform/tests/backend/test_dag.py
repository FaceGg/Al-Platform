"""Tests for the DAG Executor."""

import shutil

import pytest

from app.engine.base_operator import BaseOperator, PortSpec, ParamSpec
from app.engine.dag_executor import DAGExecutor
from app.engine.data_bus import DataBus
from app.engine.registry import OperatorRegistry


class SourceOp(BaseOperator):
    id = "test_source"
    name = "Source"
    category = "test"
    description = "Test source"
    inputs = []
    outputs = [PortSpec("out", "int", "Output")]
    parameters = [ParamSpec("value", "int", 0, "Value")]

    def validate(self, inputs):
        return True

    def execute(self, inputs, params):
        return {"out": {"value": params.get("value", 0)}}


class AddOneOp(BaseOperator):
    id = "test_add_one"
    name = "AddOne"
    category = "test"
    description = "Adds one"
    inputs = [PortSpec("in", "int", "Input")]
    outputs = [PortSpec("out", "int", "Output")]
    parameters = []

    def validate(self, inputs):
        return "in" in inputs

    def execute(self, inputs, params):
        val = inputs["in"]["value"] + 1
        return {"out": {"value": val}}


@pytest.fixture(autouse=True)
def register_ops():
    OperatorRegistry.register(SourceOp())
    OperatorRegistry.register(AddOneOp())
    yield
    DataBus._base_dir = None


def test_linear_dag():
    nodes = [
        {"id": "n1", "operator_id": "test_source", "params": {"value": 5}},
        {"id": "n2", "operator_id": "test_add_one", "params": {}},
    ]
    edges = [
        {"id": "e1", "source": "n1", "source_port": "out", "target": "n2", "target_port": "in"},
    ]

    executor = DAGExecutor(nodes, edges)
    errors = executor.validate()
    assert errors == [], f"Validation errors: {errors}"

    run_id = "test-run-linear"
    results = executor.execute(run_id)
    assert "n1" in results
    assert "n2" in results


def test_cycle_detection():
    nodes = [
        {"id": "n1", "operator_id": "test_source", "params": {}},
        {"id": "n2", "operator_id": "test_add_one", "params": {}},
    ]
    edges = [
        {"id": "e1", "source": "n1", "source_port": "out", "target": "n2", "target_port": "in"},
        {"id": "e2", "source": "n2", "source_port": "out", "target": "n1", "target_port": "in"},
    ]

    executor = DAGExecutor(nodes, edges)
    errors = executor.validate()
    assert len(errors) > 0
    assert any("Cycle" in e for e in errors)


def test_missing_operator():
    nodes = [
        {"id": "n1", "operator_id": "nonexistent_op", "params": {}},
    ]
    edges = []

    executor = DAGExecutor(nodes, edges)
    errors = executor.validate()
    assert len(errors) > 0
    assert any("not registered" in e for e in errors)
