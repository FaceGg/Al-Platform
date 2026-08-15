import unittest
import time
from unittest.mock import patch
from sqlalchemy import create_engine, inspect, text

from app.engine.base_operator import BaseOperator, ParamSpec, PortSpec
from app.engine.dag_executor import DAGExecutor
from app.engine.registry import OperatorRegistry
from app.engine.run_control import RunCancelled, RunControl
from app.engine.operator_contract import OperatorResult
from app.engine.run_state import (
    ExecutionPolicy,
    InvalidStateTransition,
    transition_run_status,
)
from app.database_migrations import ensure_schema_compatibility
from app.api.runs import _broadcast_from_thread
from app.websocket.manager import manager


class TestRunState(unittest.TestCase):
    def test_run_state_allows_cooperative_cancel(self):
        self.assertEqual(transition_run_status("running", "cancel_requested"), "cancel_requested")
        self.assertEqual(transition_run_status("cancel_requested", "cancelled"), "cancelled")

    def test_run_terminal_state_cannot_change(self):
        with self.assertRaises(InvalidStateTransition):
            transition_run_status("completed", "running")

    def test_execution_policy_uses_platform_defaults(self):
        policy = ExecutionPolicy.from_params({})
        self.assertEqual(policy.timeout_seconds, 300)
        self.assertEqual(policy.max_retries, 0)
        self.assertEqual(policy.retry_delay_seconds, 0)

    def test_execution_policy_allows_node_overrides(self):
        policy = ExecutionPolicy.from_params({
            "timeout_seconds": 10,
            "max_retries": 2,
            "retry_delay_seconds": 1.5,
        })
        self.assertEqual(policy.timeout_seconds, 10)
        self.assertEqual(policy.max_retries, 2)
        self.assertEqual(policy.retry_delay_seconds, 1.5)

    def test_execution_policy_rejects_negative_values(self):
        with self.assertRaises(ValueError):
            ExecutionPolicy.from_params({"max_retries": -1})


class TestSchemaCompatibility(unittest.TestCase):
    def test_existing_sqlite_run_tables_receive_new_columns(self):
        migration_engine = create_engine("sqlite:///:memory:")
        with migration_engine.begin() as connection:
            connection.execute(text("CREATE TABLE workflow_runs (id VARCHAR PRIMARY KEY, status VARCHAR)"))
            connection.execute(text("CREATE TABLE node_runs (id VARCHAR PRIMARY KEY, status VARCHAR)"))

        ensure_schema_compatibility(migration_engine)

        inspector = inspect(migration_engine)
        run_columns = {column["name"] for column in inspector.get_columns("workflow_runs")}
        node_columns = {column["name"] for column in inspector.get_columns("node_runs")}
        self.assertIn("error_code", run_columns)
        self.assertIn("cancel_requested_at", run_columns)
        self.assertIn("timeout_seconds", run_columns)
        self.assertIn("attempt", node_columns)
        self.assertIn("duration_ms", node_columns)


class TestRunBroadcast(unittest.TestCase):
    def test_missing_event_loop_does_not_create_coroutine(self):
        with patch.object(manager, "broadcast") as broadcast:
            _broadcast_from_thread(None, "run", {"type": "run_status"})
        broadcast.assert_not_called()


class _RetryOperator(BaseOperator):
    id = "test_retry_operator"
    inputs = []
    outputs = [PortSpec("data", "JSON", "Data")]

    def __init__(self):
        self.calls = 0

    def validate(self, inputs):
        return True

    def execute(self, context, inputs, params):
        self.calls += 1
        if self.calls == 1:
            raise ValueError("first attempt fails")
        return OperatorResult(outputs={"data": {"ok": True}})


class _SlowOperator(BaseOperator):
    id = "test_slow_operator"
    inputs = []
    outputs = [PortSpec("data", "JSON", "Data")]

    def validate(self, inputs):
        return True

    def execute(self, context, inputs, params):
        time.sleep(0.1)
        return OperatorResult(outputs={"data": {"late": True}})


class _ContextOperator(BaseOperator):
    id = "test_context_operator"
    inputs = []
    outputs = [PortSpec("data", "JSON", "Data")]

    def __init__(self):
        self.context = None

    def validate(self, inputs):
        return True

    def execute(self, context, inputs, params):
        self.context = context
        return OperatorResult(outputs={"data": {"ok": True}}, metrics={"rows": 1})


class _ValidatedOperator(BaseOperator):
    id = "test_validated_operator"
    inputs = []
    outputs = [PortSpec("data", "JSON", "Data")]
    parameters = [ParamSpec("count", "int", 1, range_min=1, range_max=3)]

    def validate(self, inputs):
        return True

    def execute(self, context, inputs, params):
        return OperatorResult(outputs={"data": {"count": params["count"]}})


class _PreviewOperator(BaseOperator):
    id = "test_preview_operator"
    inputs = []
    outputs = [
        PortSpec("chart", "Image", "Chart"),
        PortSpec("image_payload", "Image", "Image payload"),
        PortSpec("long_text", "Text", "Long text"),
    ]

    def validate(self, inputs):
        return True

    def execute(self, context, inputs, params):
        return OperatorResult(outputs={
            "chart": "data:image/png;base64," + ("A" * 1000),
            "image_payload": "data:image/jpeg;base64," + ("C" * 1000),
            "long_text": "B" * 1000,
        })


class TestReliableExecutor(unittest.TestCase):
    def setUp(self):
        self.retry_operator = _RetryOperator()
        OperatorRegistry.register(self.retry_operator)
        OperatorRegistry.register(_SlowOperator())
        OperatorRegistry.register(_ValidatedOperator())

    def test_completion_preview_preserves_chart_and_bounds_ordinary_long_strings(self):
        operator = _PreviewOperator()
        OperatorRegistry.register(operator)
        events = []
        executor = DAGExecutor([{
            "id": "node", "operator_id": operator.id, "params": {},
        }], [])

        executor.execute("preview-run", lambda *args: events.append(args), RunControl())

        completed = [event for event in events if event[2] == "completed"][-1]
        preview = completed[3]
        self.assertEqual(preview["chart"], "data:image/png;base64," + ("A" * 1000))
        self.assertEqual(preview["image_payload"], "data:image/jpeg;base64," + ("C" * 1000))
        self.assertEqual(preview["long_text"], "B" * 200 + "...(1000 chars)")

    def test_failed_node_retries_and_records_attempts(self):
        events = []
        executor = DAGExecutor([{
            "id": "node", "operator_id": "test_retry_operator",
            "params": {"max_retries": 1},
        }], [])

        executor.execute("run", lambda *args: events.append(args), RunControl())

        self.assertEqual(self.retry_operator.calls, 2)
        attempts = [event[4]["attempt"] for event in events if len(event) == 5]
        self.assertIn(1, attempts)
        self.assertIn(2, attempts)
        completed = [event for event in events if event[2] == "completed"]
        self.assertEqual(completed[-1][4]["attempt"], 2)

    def test_node_timeout_is_reported(self):
        events = []
        executor = DAGExecutor([{
            "id": "node", "operator_id": "test_slow_operator",
            "params": {"timeout_seconds": 0.01},
        }], [])

        with self.assertRaisesRegex(RuntimeError, "timed out"):
            executor.execute("run", lambda *args: events.append(args), RunControl())

        self.assertTrue(any(event[2] == "timed_out" for event in events))

    def test_cancel_before_node_stops_execution(self):
        executor = DAGExecutor([{
            "id": "node", "operator_id": "test_retry_operator", "params": {},
        }], [])

        with self.assertRaises(RunCancelled):
            executor.execute("run", run_control=RunControl(lambda: True))

        self.assertEqual(self.retry_operator.calls, 0)

    def test_executor_supplies_operator_context(self):
        operator = _ContextOperator()
        OperatorRegistry.register(operator)
        executor = DAGExecutor([{
            "id": "node", "operator_id": operator.id, "params": {},
        }], [])

        executor.execute("run-123")

        self.assertEqual(operator.context.run_id, "run-123")
        self.assertEqual(operator.context.node_id, "node")

    def test_executor_validates_operator_parameters_before_execution(self):
        executor = DAGExecutor([{
            "id": "node", "operator_id": "test_validated_operator",
            "params": {"count": 4, "timeout_seconds": 1},
        }], [])

        with self.assertRaisesRegex(RuntimeError, "OPERATOR_PARAM_INVALID"):
            executor.execute("run")


if __name__ == "__main__":
    unittest.main()
