import copy
import unittest

from app.main import app
from app.engine.base_operator import BaseOperator, PortSpec
from app.engine.operator_contract import (
    ArtifactDraft,
    OperatorContractError,
    OperatorResult,
    validate_operator_result,
)
from app.engine.registry import OperatorRegistry, register_operator
from tests.operator_test_utils import operator_context


@register_operator
class _RawOutputMetadataOperator(BaseOperator):
    id = "__test_raw_output_metadata"
    name = "Raw Output Metadata Test"
    category = "processing"
    inputs = [PortSpec("data", "DataTable", "Input Data")]
    outputs = [PortSpec("data", "DataTable", "Processed Data")]

    def validate(self, inputs):
        return True

    def execute(self, context, inputs, params):
        inputs["data"][0]["value"] = "mutated internally"
        return OperatorResult(
            outputs={"data": inputs["data"]},
            metrics={"score": 1.0},
            artifacts=[ArtifactDraft(name="test", type="data", data=b"data")],
            logs=[{"level": "info", "message": "test"}],
        )


@register_operator
class _InvalidRawOutputOperator(BaseOperator):
    id = "__test_invalid_raw_output"
    name = "Invalid Raw Output Test"
    category = "processing"
    inputs = [PortSpec("data", "DataTable", "Input Data")]
    outputs = [PortSpec("data", "DataTable", "Processed Data")]

    def validate(self, inputs):
        return True

    def execute(self, context, inputs, params):
        return None


class TestOperatorRawOutputs(unittest.TestCase):
    def test_processing_and_blending_metadata_exposes_raw_ports(self):
        processing = OperatorRegistry.get("missing_value_handler")
        join = OperatorRegistry.get("join")
        union = OperatorRegistry.get("union")

        self.assertIn("raw_data", {port.name for port in processing.outputs})
        self.assertTrue({"raw_left", "raw_right"}.issubset({port.name for port in join.outputs}))
        self.assertTrue({"raw_data1", "raw_data2"}.issubset({port.name for port in union.outputs}))

    def test_processing_result_preserves_input_before_transform(self):
        operator = OperatorRegistry.get("missing_value_handler")
        inputs = {"data": [{"x": None}, {"x": 1}]}
        original = copy.deepcopy(inputs)

        result = operator.execute(
            operator_context(), inputs, {"strategy": "drop"},
        )

        self.assertEqual(result.outputs["raw_data"], original["data"])
        self.assertEqual(result.outputs["data"], [{"x": 1}])
        self.assertEqual(inputs, original)
        self.assertIsNot(result.outputs["raw_data"], inputs["data"])
        validate_operator_result(operator.outputs, result)

    def test_join_returns_untouched_copy_for_each_input(self):
        operator = OperatorRegistry.get("join")
        inputs = {
            "left": [{"id": 1, "left_value": "left"}],
            "right": [{"id": 1, "right_value": "right"}],
        }
        original = copy.deepcopy(inputs)

        result = operator.execute(
            operator_context(), inputs, {"left_keys": "id", "right_keys": "id"},
        )

        self.assertEqual(result.outputs["raw_left"], original["left"])
        self.assertEqual(result.outputs["raw_right"], original["right"])
        self.assertEqual(result.outputs["data"][0]["left_value"], "left")
        self.assertEqual(result.outputs["data"][0]["right_value"], "right")
        self.assertEqual(inputs, original)
        validate_operator_result(operator.outputs, result)

    def test_union_returns_untouched_copy_for_each_input(self):
        operator = OperatorRegistry.get("union")
        inputs = {
            "data1": [{"id": 1, "value": "first"}],
            "data2": [{"id": 2, "value": "second"}],
        }
        original = copy.deepcopy(inputs)

        result = operator.execute(operator_context(), inputs, {})

        self.assertEqual(result.outputs["raw_data1"], original["data1"])
        self.assertEqual(result.outputs["raw_data2"], original["data2"])
        self.assertEqual(len(result.outputs["data"]), 2)
        self.assertEqual(inputs, original)
        validate_operator_result(operator.outputs, result)

    def test_wrapper_deep_copies_inputs_and_preserves_result_metadata(self):
        operator = OperatorRegistry.get("__test_raw_output_metadata")
        inputs = {"data": [{"value": "original"}]}

        result = operator.execute(operator_context(), inputs, {})

        self.assertEqual(inputs, {"data": [{"value": "original"}]})
        self.assertEqual(result.outputs["raw_data"], [{"value": "original"}])
        self.assertEqual(result.metrics, {"score": 1.0})
        self.assertEqual(result.artifacts[0].name, "test")
        self.assertEqual(result.logs, [{"level": "info", "message": "test"}])
        validate_operator_result(operator.outputs, result)

    def test_invalid_result_reaches_contract_validator(self):
        operator = OperatorRegistry.get("__test_invalid_raw_output")

        with self.assertRaisesRegex(OperatorContractError, "OPERATOR_RESULT_INVALID"):
            result = operator.execute(operator_context(), {"data": []}, {})
            validate_operator_result(operator.outputs, result)


if __name__ == "__main__":
    unittest.main()
