import math
import unittest
import ast
import inspect
import textwrap

from app.engine.base_operator import ParamSpec, PortSpec
from app.engine.operator_contract import (
    ArtifactDraft,
    OperatorContext,
    OperatorContractError,
    OperatorResult,
    validate_operator_params,
    validate_operator_result,
)
from app.main import app
from app.engine.registry import OperatorRegistry
from app.engine import dag_executor


class _Logger:
    def info(self, message, **details):
        pass


class TestOperatorContract(unittest.TestCase):
    def test_context_exposes_execution_identity(self):
        context = OperatorContext(
            run_id="run", node_id="node", project_id="project",
            artifact_service=object(), cancel_requested=lambda: False, logger=_Logger(),
        )
        self.assertEqual(context.run_id, "run")
        self.assertFalse(context.cancel_requested())

    def test_parameter_validation_applies_type_options_and_range(self):
        specs = [
            ParamSpec("count", "int", 2, range_min=1, range_max=5),
            ParamSpec("mode", "select", "a", options=["a", "b"]),
        ]
        params = validate_operator_params(specs, {"count": "3", "mode": "b"})
        self.assertEqual(params, {"count": 3, "mode": "b"})
        with self.assertRaisesRegex(OperatorContractError, "OPERATOR_PARAM_INVALID"):
            validate_operator_params(specs, {"count": 0, "mode": "a"})

    def test_required_parameter_rejects_missing_and_whitespace(self):
        spec = ParamSpec("dataset", "str", "", required=True)

        for params in ({}, {"dataset": "   "}):
            with self.assertRaisesRegex(OperatorContractError, "OPERATOR_PARAM_REQUIRED"):
                validate_operator_params([spec], params)

    def test_required_string_parameter_rejects_none(self):
        spec = ParamSpec("dataset", "str", "", required=True)

        with self.assertRaisesRegex(OperatorContractError, "OPERATOR_PARAM_REQUIRED"):
            validate_operator_params([spec], {"dataset": None})

    def test_required_select_parameter_rejects_none(self):
        spec = ParamSpec("source", "select", "local", options=["local", "url"], required=True)

        with self.assertRaisesRegex(OperatorContractError, "OPERATOR_PARAM_REQUIRED"):
            validate_operator_params([spec], {"source": None})

    def test_conditionally_required_parameter_only_applies_for_selected_source(self):
        source = ParamSpec("source", "select", "local", options=["local", "url"])
        spec = ParamSpec(
            "file_path", "file", "", required=True,
            required_when={"source": "local"},
        )

        self.assertEqual(
            validate_operator_params([source, spec], {"file_path": "", "source": "url"}),
            {"source": "url", "file_path": ""},
        )
        with self.assertRaisesRegex(OperatorContractError, "OPERATOR_PARAM_REQUIRED"):
            validate_operator_params([source, spec], {"file_path": "", "source": "local"})

    def test_result_validation_rejects_unknown_output(self):
        result = OperatorResult(outputs={"other": 1})
        with self.assertRaisesRegex(OperatorContractError, "OPERATOR_RESULT_INVALID"):
            validate_operator_result([PortSpec("data", "JSON", "Data")], result)

    def test_result_validation_rejects_non_finite_metric(self):
        result = OperatorResult(outputs={"data": 1}, metrics={"loss": math.inf})
        with self.assertRaisesRegex(OperatorContractError, "OPERATOR_RESULT_INVALID"):
            validate_operator_result([PortSpec("data", "JSON", "Data")], result)

    def test_artifact_draft_requires_name_and_type(self):
        with self.assertRaises(ValueError):
            ArtifactDraft(name="", type="model", data=b"model")


class TestRegisteredOperatorProtocol(unittest.TestCase):
    def test_all_registered_operators_use_new_signature(self):
        invalid = []
        for operator in OperatorRegistry.list_all():
            names = list(inspect.signature(operator.execute).parameters)
            if names != ["context", "inputs", "params"]:
                invalid.append((operator.id, names))
        self.assertEqual(invalid, [])

    def test_registered_execute_methods_do_not_return_bare_dicts(self):
        invalid = []
        for operator in OperatorRegistry.list_all():
            tree = ast.parse(textwrap.dedent(inspect.getsource(operator.execute)))
            if any(isinstance(node, ast.Return) and isinstance(node.value, ast.Dict) for node in ast.walk(tree)):
                invalid.append(operator.id)
        self.assertEqual(invalid, [])

    def test_dag_executor_has_no_legacy_two_argument_operator_calls(self):
        tree = ast.parse(inspect.getsource(dag_executor.DAGExecutor))
        legacy_calls = [
            node.lineno for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "execute"
            and len(node.args) == 2
        ]
        self.assertEqual(legacy_calls, [])


if __name__ == "__main__":
    unittest.main()
