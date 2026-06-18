"""Tests for the operator system (BaseOperator + OperatorRegistry)."""

from app.engine.base_operator import BaseOperator, PortSpec, ParamSpec
from app.engine.registry import OperatorRegistry


class DummyOp(BaseOperator):
    id = "test_dummy"
    name = "Dummy"
    category = "test"
    description = "Test"
    inputs = [PortSpec("data", "DataTable", "Input")]
    outputs = [PortSpec("result", "DataTable", "Output")]
    parameters = [ParamSpec("value", "int", 42, "Value")]

    def validate(self, inputs):
        return "data" in inputs

    def execute(self, inputs, params):
        return {"result": [{"value": params.get("value", 42)}]}


def test_registration():
    op = DummyOp()
    OperatorRegistry.register(op)
    assert OperatorRegistry.get("test_dummy") is op


def test_execution():
    op = DummyOp()
    result = op.execute({"data": []}, {"value": 100})
    assert result["result"][0]["value"] == 100


def test_list_all():
    count_before = len(OperatorRegistry.list_all())
    op = DummyOp()
    op.id = "test_list_all_dummy"
    OperatorRegistry.register(op)
    assert len(OperatorRegistry.list_all()) == count_before + 1


def test_list_by_category():
    ops = OperatorRegistry.list_by_category("test")
    assert all(o.category == "test" for o in ops)


def test_get_preview_default():
    op = DummyOp()
    assert op.get_preview({}) == {}
