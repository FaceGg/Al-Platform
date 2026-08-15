import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from mlflow.entities import Experiment, FileInfo, Metric, Run, RunData, RunInfo, RunTag
from mlflow.exceptions import MlflowException
from mlflow.protos.databricks_pb2 import INTERNAL_ERROR, RESOURCE_DOES_NOT_EXIST

from app.services.experiment_tracking import (
    MlflowExperimentTracking,
    TrackingNotFound,
    TrackingUnavailable,
    resolve_tracking_configuration,
)


class InMemoryMlflowClient:
    def __init__(self):
        self.experiments = {}
        self.runs = {}
        self.metric_history = {}
        self.artifacts = {}
        self.next_experiment = 1
        self.next_run = 1
        self.failure_code = None

    def _raise_if_failed(self):
        if self.failure_code is not None:
            raise MlflowException("tracking failure", error_code=self.failure_code)

    def get_experiment_by_name(self, name):
        self._raise_if_failed()
        return next((item for item in self.experiments.values() if item.name == name), None)

    def create_experiment(self, name, artifact_location=None, tags=None):
        self._raise_if_failed()
        experiment_id = str(self.next_experiment)
        self.next_experiment += 1
        self.experiments[experiment_id] = Experiment(
            experiment_id=experiment_id,
            name=name,
            artifact_location=artifact_location,
            lifecycle_stage="active",
            tags=tags or {},
            creation_time=1,
            last_update_time=1,
        )
        return experiment_id

    def create_run(self, experiment_id, start_time=None, tags=None, run_name=None):
        self._raise_if_failed()
        run_id = f"run-{self.next_run}"
        self.next_run += 1
        info = RunInfo(
            run_id=run_id,
            experiment_id=experiment_id,
            user_id="platform",
            status="RUNNING",
            start_time=start_time or self.next_run,
            end_time=None,
            lifecycle_stage="active",
            artifact_uri=f"s3://artifacts/{experiment_id}/{run_id}",
            run_name=run_name,
        )
        run = Run(info, RunData(
            metrics=[],
            params=[],
            tags=[RunTag(key, value) for key, value in (tags or {}).items()],
        ))
        self.runs[run_id] = run
        return run

    def log_batch(self, run_id, metrics=(), params=(), tags=(), synchronous=None):
        self._raise_if_failed()
        run = self._required_run(run_id)
        for param in params:
            run.data._params[param.key] = param.value
        for tag in tags:
            run.data._tags[tag.key] = tag.value
        for metric in metrics:
            run.data._metrics[metric.key] = metric.value
            self.metric_history.setdefault((run_id, metric.key), []).append(metric)

    def get_run(self, run_id):
        self._raise_if_failed()
        return self._required_run(run_id)

    def search_runs(
        self,
        experiment_ids,
        filter_string="",
        run_view_type=1,
        max_results=1000,
        order_by=None,
        page_token=None,
    ):
        self._raise_if_failed()
        matches = [
            run for run in self.runs.values()
            if run.info.experiment_id in experiment_ids
        ]
        if filter_string:
            key, expected = filter_string.split(" = ", maxsplit=1)
            tag_key = key.removeprefix("tags.")
            expected = expected.strip("'")
            matches = [run for run in matches if run.data.tags.get(tag_key) == expected]
        return matches[:max_results]

    def get_metric_history(self, run_id, key):
        self._raise_if_failed()
        self._required_run(run_id)
        return list(self.metric_history.get((run_id, key), []))

    def log_artifact(self, run_id, local_path, artifact_path=None):
        self._raise_if_failed()
        self._required_run(run_id)
        source = Path(local_path)
        relative = Path(artifact_path or "") / source.name
        self.artifacts.setdefault(run_id, {})[relative.as_posix()] = source.read_bytes()

    def list_artifacts(self, run_id, path=None):
        self._raise_if_failed()
        self._required_run(run_id)
        prefix = f"{path.rstrip('/')}/" if path else ""
        return [
            FileInfo(name, False, len(payload))
            for name, payload in self.artifacts.get(run_id, {}).items()
            if name.startswith(prefix)
        ]

    def download_artifacts(self, run_id, path, dst_path=None):
        self._raise_if_failed()
        self._required_run(run_id)
        try:
            payload = self.artifacts[run_id][path]
        except KeyError as error:
            raise MlflowException(
                "artifact not found",
                error_code=RESOURCE_DOES_NOT_EXIST,
            ) from error
        destination = Path(dst_path) / Path(path).name
        destination.write_bytes(payload)
        return str(destination)

    def set_terminated(self, run_id, status=None, end_time=None):
        self._raise_if_failed()
        run = self._required_run(run_id)
        run.info._status = status
        run.info._end_time = end_time or 1

    def _required_run(self, run_id):
        try:
            return self.runs[run_id]
        except KeyError as error:
            raise MlflowException(
                "run not found",
                error_code=RESOURCE_DOES_NOT_EXIST,
            ) from error


class TestMlflowExperimentTracking(unittest.TestCase):
    def setUp(self):
        self.client = InMemoryMlflowClient()
        self.tracking = MlflowExperimentTracking(
            client=self.client,
            artifact_root="s3://artifacts/mlflow",
        )

    def test_ensure_experiment_is_idempotent_and_uses_artifact_namespace(self):
        first = self.tracking.ensure_experiment("project/p1/e1")
        second = self.tracking.ensure_experiment("project/p1/e1")

        self.assertEqual(first, second)
        self.assertEqual(
            self.client.experiments[first].artifact_location,
            "s3://artifacts/mlflow/project/p1/e1",
        )

    def test_run_params_metrics_and_history_have_stable_types(self):
        experiment_id = self.tracking.ensure_experiment("project/p1/e1")
        run = self.tracking.start_run(
            experiment_id,
            run_name="baseline",
            tags={"platform.project_id": "p1", "platform.job_id": "j1"},
        )
        self.tracking.log_params(run.run_id, {"epochs": 10, "restore_best": True})
        self.tracking.log_metrics(run.run_id, {"val_accuracy": 0.92}, step=3)
        self.tracking.set_tags(run.run_id, {"platform.model_artifact_id": "a1"})

        tracked = self.tracking.get_run(run.run_id)
        history = self.tracking.get_metric_history(run.run_id, "val_accuracy")
        self.assertEqual(tracked.params, {"epochs": "10", "restore_best": "True"})
        self.assertEqual(tracked.metrics, {"val_accuracy": 0.92})
        self.assertEqual(tracked.tags["platform.model_artifact_id"], "a1")
        self.assertEqual(history[0].step, 3)
        self.assertEqual(history[0].value, 0.92)
        with self.assertRaises(TypeError):
            tracked.params["epochs"] = "20"

    def test_child_run_search_and_compare_preserve_visible_behavior(self):
        experiment_id = self.tracking.ensure_experiment("project/p1/e1")
        parent = self.tracking.start_run(
            experiment_id,
            run_name="automl",
            tags={"platform.project_id": "p1"},
        )
        child = self.tracking.start_run(
            experiment_id,
            run_name="candidate",
            tags={"platform.project_id": "p1"},
            parent_run_id=parent.run_id,
        )
        self.tracking.log_metrics(child.run_id, {"score": 0.8}, step=1)

        matches = self.tracking.search_runs(
            [experiment_id],
            filter_string="tags.platform.project_id = 'p1'",
        )
        compared = self.tracking.compare_runs([child.run_id, parent.run_id])
        self.assertEqual({item.run_id for item in matches}, {parent.run_id, child.run_id})
        self.assertEqual(child.parent_run_id, parent.run_id)
        self.assertEqual([item.run_id for item in compared], [child.run_id, parent.run_id])

    def test_artifact_round_trip_and_terminal_status(self):
        experiment_id = self.tracking.ensure_experiment("project/p1/e1")
        run = self.tracking.start_run(experiment_id, run_name="checkpoint", tags={})
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "latest.joblib"
            source.write_bytes(b"checkpoint")
            self.tracking.log_artifact(run.run_id, source, "checkpoints")

            listed = self.tracking.list_artifacts(run.run_id, "checkpoints")
            downloaded = self.tracking.download_artifact(
                run.run_id,
                "checkpoints/latest.joblib",
                Path(directory) / "download",
            )
            self.assertEqual(listed[0].path, "checkpoints/latest.joblib")
            self.assertEqual(listed[0].file_size, len(b"checkpoint"))
            self.assertEqual(downloaded.read_bytes(), b"checkpoint")

        self.tracking.end_run(run.run_id, "FINISHED")
        self.assertEqual(self.tracking.get_run(run.run_id).status, "FINISHED")

    def test_non_finite_or_invalid_metrics_are_rejected(self):
        experiment_id = self.tracking.ensure_experiment("project/p1/e1")
        run = self.tracking.start_run(experiment_id, run_name="invalid", tags={})
        for value in (float("nan"), float("inf"), True, "0.9"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    self.tracking.log_metrics(run.run_id, {"score": value}, step=1)
        with self.assertRaises(ValueError):
            self.tracking.log_metrics(run.run_id, {"score": 0.9}, step=1.5)

    def test_mlflow_errors_map_to_stable_domain_errors(self):
        self.client.failure_code = RESOURCE_DOES_NOT_EXIST
        with self.assertRaises(TrackingNotFound):
            self.tracking.get_run("missing")

        self.client.failure_code = INTERNAL_ERROR
        with self.assertRaises(TrackingUnavailable):
            self.tracking.ensure_experiment("project/p1/e1")

    def test_unconfigured_local_tracking_uses_managed_file_locations(self):
        with tempfile.TemporaryDirectory() as directory:
            tracking_uri, artifact_root = resolve_tracking_configuration(
                SimpleNamespace(
                    app_mode="local",
                    mlflow_tracking_uri=None,
                    mlflow_artifact_root=None,
                    artifact_storage_dir=directory,
                )
            )

            self.assertEqual(tracking_uri, (Path(directory) / "mlflow" / "tracking").resolve().as_uri())
            self.assertEqual(artifact_root, (Path(directory) / "mlflow" / "artifacts").resolve().as_uri())

    def test_unconfigured_non_local_tracking_is_rejected(self):
        with self.assertRaises(TrackingUnavailable):
            resolve_tracking_configuration(
                SimpleNamespace(
                    app_mode="production",
                    mlflow_tracking_uri=None,
                    mlflow_artifact_root=None,
                    artifact_storage_dir="/unused",
                )
            )


if __name__ == "__main__":
    unittest.main()
