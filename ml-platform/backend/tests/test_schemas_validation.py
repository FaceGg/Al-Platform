"""Validation tests for Pydantic schemas in app.schemas.

Previously schemas only had import/static-scan coverage. Here we exercise
field constraints, defaults, round-tripping, and forbidden extras.
"""
import sys
import unittest
import uuid

from pydantic import ValidationError

sys.path.insert(0, ".")

from app.schemas.access import MemberCreate, MemberUpdate
from app.schemas.experiment import ExperimentCreate, RunCompareRequest
from app.schemas.model_registry import (
    FeatureField,
    LifecycleComment,
    OnnxVersionCreate,
    OutputSchema,
    PlatformVersionCreate,
    RegisteredModelCreate,
)
from app.schemas.operator import OperatorSchema, ParamSpecSchema, PortSpecSchema
from app.schemas.project import ProjectCreate, ProjectUpdate
from app.schemas.run import NodeRunResponse, RunResponse
from app.schemas.schedule import RetryPolicy, ScheduleCreate, ScheduleUpdate
from app.schemas.workflow import (
    EdgeCreate,
    NodeCreate,
    NodePosition,
    WorkflowCreate,
    WorkflowSave,
)


class TestAccessSchemas(unittest.TestCase):
    def test_member_create_accepts_valid_role(self):
        m = MemberCreate(username="alice", role="editor")
        self.assertEqual(m.role, "editor")

    def test_member_create_rejects_invalid_role(self):
        with self.assertRaises(ValidationError):
            MemberCreate(username="alice", role="admin")

    def test_member_create_rejects_extra_fields(self):
        with self.assertRaises(ValidationError):
            MemberCreate(username="alice", role="viewer", extra="x")

    def test_member_create_requires_username(self):
        with self.assertRaises(ValidationError):
            MemberCreate(role="viewer")

    def test_member_update_rejects_invalid_role(self):
        with self.assertRaises(ValidationError):
            MemberUpdate(role="superuser")


class TestExperimentSchemas(unittest.TestCase):
    def test_experiment_create_strips_name(self):
        e = ExperimentCreate(project_id=uuid.uuid4(), name="  My Experiment  ")
        self.assertEqual(e.name, "My Experiment")

    def test_experiment_create_rejects_blank_name(self):
        with self.assertRaises(ValidationError):
            ExperimentCreate(project_id=uuid.uuid4(), name="   ")

    def test_experiment_create_rejects_oversized_description(self):
        with self.assertRaises(ValidationError):
            ExperimentCreate(project_id=uuid.uuid4(), name="x", description="y" * 4097)

    def test_run_compare_requires_two_unique_ids(self):
        RunCompareRequest(run_ids=["a", "b"])

    def test_run_compare_rejects_single_id(self):
        with self.assertRaises(ValidationError):
            RunCompareRequest(run_ids=["a"])

    def test_run_compare_rejects_duplicates(self):
        with self.assertRaises(ValidationError):
            RunCompareRequest(run_ids=["a", "a"])

    def test_run_compare_rejects_blank_id(self):
        with self.assertRaises(ValidationError):
            RunCompareRequest(run_ids=["a", " "])


class TestModelRegistrySchemas(unittest.TestCase):
    def test_registered_model_create_minimum(self):
        m = RegisteredModelCreate(name="rf-model")
        self.assertEqual(m.description, "")

    def test_registered_model_create_rejects_blank_name(self):
        with self.assertRaises(ValidationError):
            RegisteredModelCreate(name="")

    def test_platform_version_create_valid(self):
        v = PlatformVersionCreate(
            source_kind="platform_joblib",
            source_model_library_id=uuid.uuid4(),
        )
        self.assertEqual(v.source_kind, "platform_joblib")

    def test_platform_version_create_rejects_wrong_source_kind(self):
        with self.assertRaises(ValidationError):
            PlatformVersionCreate(
                source_kind="onnx_artifact",
                source_model_library_id=uuid.uuid4(),
            )

    def test_onnx_version_create_valid(self):
        v = OnnxVersionCreate(
            source_kind="onnx_artifact",
            source_artifact_id=uuid.uuid4(),
            feature_schema=[FeatureField(name="f1", dtype="float")],
            output_schema=OutputSchema(name="prob", dtype="float", task="classification"),
        )
        self.assertEqual(v.output_schema.task, "classification")

    def test_onnx_version_create_requires_feature_schema(self):
        with self.assertRaises(ValidationError):
            OnnxVersionCreate(
                source_kind="onnx_artifact",
                source_artifact_id=uuid.uuid4(),
                feature_schema=[],
                output_schema=OutputSchema(name="prob", dtype="float", task="classification"),
            )

    def test_output_schema_rejects_invalid_task(self):
        with self.assertRaises(ValidationError):
            OutputSchema(name="prob", dtype="float", task="clustering")

    def test_lifecycle_comment_default(self):
        c = LifecycleComment()
        self.assertEqual(c.comment, "")


class TestOperatorSchemas(unittest.TestCase):
    def test_port_spec_schema(self):
        p = PortSpecSchema(name="data", type="DataTable", label="Input")
        self.assertEqual(p.name, "data")

    def test_param_spec_schema_with_options(self):
        p = ParamSpecSchema(name="model", type="select", default="rf", label="Model",
                            options=["rf", "xgb"])
        self.assertEqual(p.options, ["rf", "xgb"])

    def test_operator_schema_round_trip(self):
        op = OperatorSchema(
            id="csv_import",
            name="CSV Import",
            category="data_io",
            description="read csv",
            inputs=[PortSpecSchema(name="data", type="DataTable", label="out")],
            outputs=[],
            parameters=[],
        )
        self.assertEqual(op.id, "csv_import")
        self.assertEqual(op.version, "1.0")


class TestProjectSchemas(unittest.TestCase):
    def test_project_create_defaults_description(self):
        p = ProjectCreate(name="P")
        self.assertEqual(p.description, "")

    def test_project_update_all_optional(self):
        p = ProjectUpdate()
        self.assertIsNone(p.name)
        self.assertIsNone(p.description)


class TestRunSchemas(unittest.TestCase):
    def test_node_run_response_defaults(self):
        nr = NodeRunResponse(id=uuid.uuid4(), node_id=uuid.uuid4(), status="completed")
        self.assertEqual(nr.attempt, 1)
        self.assertEqual(nr.logs, [])

    def test_run_response_defaults(self):
        r = RunResponse(id=uuid.uuid4(), workflow_id=uuid.uuid4(), status="running")
        self.assertEqual(r.node_runs, [])
        self.assertEqual(r.logs, [])


class TestScheduleSchemas(unittest.TestCase):
    def test_retry_policy_defaults(self):
        r = RetryPolicy()
        self.assertEqual(r.max_attempts, 1)
        self.assertEqual(r.backoff_seconds, 0)

    def test_retry_policy_rejects_zero_attempts(self):
        with self.assertRaises(ValidationError):
            RetryPolicy(max_attempts=0)

    def test_retry_policy_rejects_oversized_attempts(self):
        with self.assertRaises(ValidationError):
            RetryPolicy(max_attempts=11)

    def test_schedule_create_minimum(self):
        s = ScheduleCreate(
            name="Hourly",
            workflow_id=uuid.uuid4(),
            cron_expression="0 * * * *",
        )
        self.assertEqual(s.timezone, "UTC")
        self.assertEqual(s.max_concurrency, 1)

    def test_schedule_create_rejects_blank_name(self):
        with self.assertRaises(ValidationError):
            ScheduleCreate(name="", workflow_id=uuid.uuid4(), cron_expression="0 * * * *")

    def test_schedule_create_rejects_extra_fields(self):
        with self.assertRaises(ValidationError):
            ScheduleCreate(
                name="x",
                workflow_id=uuid.uuid4(),
                cron_expression="0 * * * *",
                unexpected=True,
            )

    def test_schedule_update_all_optional(self):
        s = ScheduleUpdate()
        self.assertIsNone(s.name)
        self.assertIsNone(s.enabled)


class TestWorkflowSchemas(unittest.TestCase):
    def test_node_position(self):
        p = NodePosition(x=1.0, y=2.0)
        self.assertEqual(p.x, 1.0)

    def test_node_create_defaults(self):
        n = NodeCreate(id="n1", operator_id="csv_import", position=NodePosition(x=0, y=0))
        self.assertEqual(n.label, "")
        self.assertEqual(n.params, {})

    def test_edge_create_requires_source_and_target(self):
        with self.assertRaises(ValidationError):
            EdgeCreate(id="e1", source_port="a", target_port="b")

    def test_workflow_create_defaults(self):
        w = WorkflowCreate(name="WF")
        self.assertEqual(w.nodes, [])
        self.assertEqual(w.edges, [])
        self.assertEqual(w.description, "")

    def test_workflow_save_all_optional_name(self):
        w = WorkflowSave()
        self.assertIsNone(w.name)
        self.assertEqual(w.nodes, [])


if __name__ == "__main__":
    unittest.main()
