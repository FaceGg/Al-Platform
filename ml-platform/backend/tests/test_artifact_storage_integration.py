import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

from app.engine.operator_contract import OperatorContext
from app.operators.io_operators import CSVImport


class MaterializingArtifactService:
    def __init__(self, path: Path):
        self.path = path
        self.requests: list[tuple[str, str | None, str | None]] = []

    @contextmanager
    def materialize(self, artifact_id, project_id, expected_type=None):
        self.requests.append((str(artifact_id), str(project_id), expected_type))
        yield self.path


class TestArtifactStorageIntegration(unittest.TestCase):
    def test_csv_import_materializes_dataset_artifact_at_execution_time(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "weld.csv"
            source.write_text("current,force\n8,3\n9,4\n", encoding="utf-8")
            service = MaterializingArtifactService(source)
            context = OperatorContext(
                run_id="run",
                node_id="node",
                project_id="project",
                artifact_service=service,
                cancel_requested=lambda: False,
                logger=None,
            )

            result = CSVImport.execute(
                context,
                {},
                {
                    "source": "artifact",
                    "dataset_artifact_id": "artifact-id",
                    "delimiter": ",",
                    "has_header": True,
                },
            )

        self.assertEqual(len(result.outputs["data"]), 2)
        self.assertEqual(
            service.requests,
            [("artifact-id", "project", "dataset")],
        )


if __name__ == "__main__":
    unittest.main()
