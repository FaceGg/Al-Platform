import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace

from app.engine.dag_executor import DAGExecutor
from app.engine.operator_contract import ArtifactDraft, OperatorResult
from app.engine.registry import register_operator, OperatorRegistry
from app.engine.base_operator import BaseOperator, PortSpec


@register_operator
class DraftArtifactOperator(BaseOperator):
    id = "test_draft_artifact_operator"
    name = "Test Draft Artifact"
    category = "test"
    inputs = []
    outputs = [PortSpec("data", "JSON", "Data")]
    parameters = []

    def validate(self, inputs):
        return True

    def execute(self, context, inputs, params):
        return OperatorResult(
            outputs={"data": {"ok": True}},
            artifacts=[ArtifactDraft(
                name="result.bin",
                type="model",
                data=b"artifact-payload",
                metadata={"kind": "test"},
            )],
        )


class RecordingArtifactService:
    def __init__(self):
        self.calls = []

    def create_from_draft(self, draft, project_id, run_id, node_id):
        self.calls.append((draft, project_id, run_id, node_id))
        return SimpleNamespace(
            id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
            name=draft.name,
            format=draft.format,
            storage_uri="file:///artifacts/result.bin",
            file_size=len(draft.data),
        )


class TestOperatorArtifactPersistence(unittest.TestCase):
    def test_executor_persists_drafts_and_returns_references(self):
        service = RecordingArtifactService()
        executor = DAGExecutor(
            nodes=[{"id": "node-1", "operator_id": DraftArtifactOperator.id, "params": {}}],
            edges=[],
            artifact_service=service,
            project_id="project-1",
        )

        events = []
        result = executor.execute(
            "run-1",
            lambda run_id, node_id, status, payload, metadata: events.append(
                (run_id, node_id, status, payload, metadata)
            ),
        )

        self.assertEqual(len(service.calls), 1)
        draft, project_id, run_id, node_id = service.calls[0]
        self.assertEqual(draft.metadata, {"kind": "test"})
        self.assertEqual(project_id, "project-1")
        self.assertEqual(run_id, "run-1")
        self.assertEqual(node_id, "node-1")
        self.assertEqual(
            result["node-1"]["artifacts"],
            [{
                "artifact_id": "11111111-1111-1111-1111-111111111111",
                "name": "result.bin",
                "format": None,
                "uri": "file:///artifacts/result.bin",
                "size": len(b"artifact-payload"),
            }],
        )
        completed = next(event for event in events if event[2] == "completed")
        self.assertEqual(completed[3]["artifacts"], result["node-1"]["artifacts"])


if __name__ == "__main__":
    unittest.main()
