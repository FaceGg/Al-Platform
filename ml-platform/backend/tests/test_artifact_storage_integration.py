import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

import pandas as pd

from app.engine.operator_contract import OperatorContext
from app.operators.io_operators import CSVExport, CSVImport, WriteCSV
from app.operators.processing import SpotWeldFeatureEngineering
from app.services.spot_weld_quality import build_demo_report_frame


class MaterializingArtifactService:
    def __init__(self, path: Path):
        self.path = path
        self.requests: list[tuple[str, str | None, str | None]] = []

    @contextmanager
    def materialize(self, artifact_id, project_id, expected_type=None):
        self.requests.append((str(artifact_id), str(project_id), expected_type))
        yield self.path


class RecordingLogger:
    def info(self, *_args, **_kwargs):
        return None


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
                logger=RecordingLogger(),
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

    def test_csv_export_operators_declare_the_written_file_as_a_dataset_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            context = OperatorContext(
                run_id="run",
                node_id="node",
                project_id="project",
                artifact_service=None,
                cancel_requested=lambda: False,
                logger=RecordingLogger(),
                workspace_dir=workspace,
            )

            source_rows = [{
                "current": 8,
                "force": 3,
                "cvei": "current-waveform",
                "cvev": "voltage-waveform",
                "cver": "resistance-waveform",
                "cvep": "power-waveform",
            }]
            results = [
                operator.execute(
                    context,
                    {"data": source_rows},
                    {
                        "file_path": "",
                        "file_name": operator.id,
                        "format": "csv",
                        "separator": ",",
                        "include_header": True,
                        "encoding": "utf-8",
                    },
                )
                for operator in (CSVExport, WriteCSV)
            ]

            for result in results:
                self.assertEqual(result.outputs["data"], source_rows)
                self.assertEqual(len(result.artifacts), 1)
                draft = result.artifacts[0]
                self.assertEqual(draft.type, "dataset")
                self.assertEqual(draft.format, "csv")
                self.assertTrue(Path(draft.data).is_file())
                exported = pd.read_csv(draft.data)
                self.assertEqual(exported.to_dict(orient="records"), source_rows)

    def test_spot_weld_feature_output_and_csv_artifact_drop_raw_waveforms(self):
        with tempfile.TemporaryDirectory() as directory:
            context = OperatorContext(
                run_id="run",
                node_id="node",
                project_id="project",
                artifact_service=None,
                cancel_requested=lambda: False,
                logger=RecordingLogger(),
                workspace_dir=Path(directory),
            )
            source = build_demo_report_frame(12)
            source["Fault"] = [0 if index < 6 else 1 for index in range(len(source))]
            engineered = SpotWeldFeatureEngineering.execute(
                context, {"data": source}, {},
            ).outputs["features"]

            self.assertNotIn("cvei", engineered[0])
            self.assertNotIn("cvev", engineered[0])
            self.assertNotIn("cver", engineered[0])
            self.assertNotIn("cvep", engineered[0])
            self.assertEqual([row["Fault"] for row in engineered], source["Fault"].tolist())

            for operator in (CSVExport, WriteCSV):
                result = operator.execute(
                    context,
                    {"data": engineered},
                    {
                        "file_path": "",
                        "file_name": operator.id,
                        "format": "csv",
                        "separator": ",",
                        "include_header": True,
                        "encoding": "utf-8",
                    },
                )
                exported = pd.read_csv(result.artifacts[0].data)
                for field in ("cvei", "cvev", "cver", "cvep"):
                    self.assertNotIn(field, exported.columns)
                self.assertEqual(exported["Fault"].tolist(), source["Fault"].tolist())


if __name__ == "__main__":
    unittest.main()
