"""MLflow-backed experiment tracking contract and adapter."""

import math
import time
from contextlib import contextmanager
from dataclasses import dataclass
from numbers import Real
from pathlib import Path
from types import MappingProxyType
from typing import Iterator, Mapping, Protocol, Sequence

from mlflow.entities import Metric, Param, RunTag
from mlflow.exceptions import MlflowException


class TrackingError(RuntimeError):
    """Base error for stable experiment tracking failures."""


class TrackingUnavailable(TrackingError):
    """Raised when the tracking service cannot complete an operation."""


class TrackingNotFound(TrackingError):
    """Raised when a requested tracking resource does not exist."""


def resolve_tracking_configuration(settings) -> tuple[str, str]:
    """Return configured tracking locations or managed local file locations.

    Production always requires explicit MLflow infrastructure. Local development
    uses a project-managed file backend so experiment creation and training work
    without manually starting an MLflow service.
    """
    tracking_uri = str(getattr(settings, "mlflow_tracking_uri", "") or "").strip()
    artifact_root = str(getattr(settings, "mlflow_artifact_root", "") or "").strip()

    if tracking_uri and artifact_root:
        return tracking_uri, artifact_root.rstrip("/")
    if tracking_uri or artifact_root:
        raise TrackingUnavailable(
            "MLflow tracking URI and artifact root must be configured together"
        )
    if getattr(settings, "app_mode", "local") != "local":
        raise TrackingUnavailable("Experiment tracking is not configured")

    root = Path(getattr(settings, "artifact_storage_dir", "./artifact_store")).resolve()
    tracking_path = root / "mlflow" / "tracking"
    artifact_path = root / "mlflow" / "artifacts"
    tracking_path.mkdir(parents=True, exist_ok=True)
    artifact_path.mkdir(parents=True, exist_ok=True)
    return tracking_path.as_uri(), artifact_path.as_uri()


@dataclass(frozen=True)
class TrackedMetric:
    key: str
    value: float
    timestamp: int
    step: int


@dataclass(frozen=True)
class TrackedArtifact:
    path: str
    is_dir: bool
    file_size: int | None


@dataclass(frozen=True)
class TrackedRun:
    run_id: str
    experiment_id: str
    run_name: str | None
    status: str
    start_time: int | None
    end_time: int | None
    artifact_uri: str | None
    params: Mapping[str, str]
    metrics: Mapping[str, float]
    tags: Mapping[str, str]
    parent_run_id: str | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "params", MappingProxyType(dict(self.params)))
        object.__setattr__(self, "metrics", MappingProxyType(dict(self.metrics)))
        object.__setattr__(self, "tags", MappingProxyType(dict(self.tags)))


class ExperimentTracking(Protocol):
    def ensure_experiment(self, name: str) -> str: ...

    def start_run(
        self,
        experiment_id: str,
        *,
        run_name: str,
        tags: Mapping[str, object],
        parent_run_id: str | None = None,
    ) -> TrackedRun: ...

    def log_params(self, run_id: str, params: Mapping[str, object]) -> None: ...

    def log_metrics(
        self,
        run_id: str,
        metrics: Mapping[str, Real],
        *,
        step: int,
    ) -> None: ...

    def set_tags(self, run_id: str, tags: Mapping[str, object]) -> None: ...

    def get_run(self, run_id: str) -> TrackedRun: ...

    def search_runs(
        self,
        experiment_ids: Sequence[str],
        *,
        filter_string: str = "",
        max_results: int = 1000,
    ) -> tuple[TrackedRun, ...]: ...

    def compare_runs(self, run_ids: Sequence[str]) -> tuple[TrackedRun, ...]: ...

    def get_metric_history(self, run_id: str, key: str) -> tuple[TrackedMetric, ...]: ...

    def log_artifact(
        self,
        run_id: str,
        local_path: str | Path,
        artifact_path: str | None = None,
    ) -> None: ...

    def list_artifacts(
        self,
        run_id: str,
        path: str | None = None,
    ) -> tuple[TrackedArtifact, ...]: ...

    def download_artifact(
        self,
        run_id: str,
        path: str,
        destination: str | Path,
    ) -> Path: ...

    def end_run(self, run_id: str, status: str) -> None: ...


class MlflowExperimentTracking:
    _TERMINAL_STATUSES = frozenset({"FINISHED", "FAILED", "KILLED"})

    def __init__(self, client, artifact_root: str):
        self.client = client
        self.artifact_root = artifact_root.rstrip("/")

    def ensure_experiment(self, name: str) -> str:
        if not name.strip():
            raise ValueError("Experiment name must not be empty")
        with self._translate_errors():
            existing = self.client.get_experiment_by_name(name)
            if existing is not None:
                return str(existing.experiment_id)
            return str(self.client.create_experiment(
                name,
                artifact_location=f"{self.artifact_root}/{name.lstrip('/')}",
            ))

    def start_run(
        self,
        experiment_id: str,
        *,
        run_name: str,
        tags: Mapping[str, object],
        parent_run_id: str | None = None,
    ) -> TrackedRun:
        normalized_tags = self._string_mapping(tags)
        if parent_run_id is not None:
            normalized_tags["mlflow.parentRunId"] = str(parent_run_id)
        with self._translate_errors():
            run = self.client.create_run(
                str(experiment_id),
                tags=normalized_tags,
                run_name=run_name,
            )
        return self._tracked_run(run)

    def log_params(self, run_id: str, params: Mapping[str, object]) -> None:
        values = [Param(str(key), str(value)) for key, value in params.items()]
        with self._translate_errors():
            self.client.log_batch(str(run_id), params=values)

    def log_metrics(
        self,
        run_id: str,
        metrics: Mapping[str, Real],
        *,
        step: int,
    ) -> None:
        if isinstance(step, bool) or not isinstance(step, int):
            raise ValueError("Metric step must be an integer")
        timestamp = int(time.time() * 1000)
        values = []
        for key, value in metrics.items():
            if isinstance(value, bool) or not isinstance(value, Real):
                raise ValueError("Metrics must be numeric")
            numeric = float(value)
            if not math.isfinite(numeric):
                raise ValueError("Metrics must be finite")
            values.append(Metric(str(key), numeric, timestamp, step))
        with self._translate_errors():
            self.client.log_batch(str(run_id), metrics=values)

    def set_tags(self, run_id: str, tags: Mapping[str, object]) -> None:
        values = [
            RunTag(key, value)
            for key, value in self._string_mapping(tags).items()
        ]
        with self._translate_errors():
            self.client.log_batch(str(run_id), tags=values)

    def get_run(self, run_id: str) -> TrackedRun:
        with self._translate_errors():
            run = self.client.get_run(str(run_id))
        return self._tracked_run(run)

    def search_runs(
        self,
        experiment_ids: Sequence[str],
        *,
        filter_string: str = "",
        max_results: int = 1000,
    ) -> tuple[TrackedRun, ...]:
        with self._translate_errors():
            runs = self.client.search_runs(
                [str(item) for item in experiment_ids],
                filter_string=filter_string,
                max_results=max_results,
            )
        return tuple(self._tracked_run(run) for run in runs)

    def compare_runs(self, run_ids: Sequence[str]) -> tuple[TrackedRun, ...]:
        return tuple(self.get_run(run_id) for run_id in run_ids)

    def get_metric_history(self, run_id: str, key: str) -> tuple[TrackedMetric, ...]:
        with self._translate_errors():
            metrics = self.client.get_metric_history(str(run_id), str(key))
        return tuple(
            TrackedMetric(
                key=metric.key,
                value=float(metric.value),
                timestamp=int(metric.timestamp),
                step=int(metric.step),
            )
            for metric in metrics
        )

    def log_artifact(
        self,
        run_id: str,
        local_path: str | Path,
        artifact_path: str | None = None,
    ) -> None:
        source = Path(local_path)
        if not source.is_file():
            raise FileNotFoundError(str(source))
        with self._translate_errors():
            self.client.log_artifact(
                str(run_id),
                str(source),
                artifact_path=artifact_path,
            )

    def list_artifacts(
        self,
        run_id: str,
        path: str | None = None,
    ) -> tuple[TrackedArtifact, ...]:
        with self._translate_errors():
            artifacts = self.client.list_artifacts(str(run_id), path=path)
        return tuple(
            TrackedArtifact(
                path=item.path,
                is_dir=bool(item.is_dir),
                file_size=item.file_size,
            )
            for item in artifacts
        )

    def download_artifact(
        self,
        run_id: str,
        path: str,
        destination: str | Path,
    ) -> Path:
        target = Path(destination)
        target.mkdir(parents=True, exist_ok=True)
        with self._translate_errors():
            downloaded = self.client.download_artifacts(
                str(run_id),
                path,
                dst_path=str(target),
            )
        return Path(downloaded)

    def end_run(self, run_id: str, status: str) -> None:
        normalized = status.upper()
        if normalized not in self._TERMINAL_STATUSES:
            raise ValueError("Invalid terminal run status")
        with self._translate_errors():
            self.client.set_terminated(str(run_id), status=normalized)

    @staticmethod
    def _string_mapping(values: Mapping[str, object]) -> dict[str, str]:
        return {str(key): str(value) for key, value in values.items()}

    @staticmethod
    def _tracked_run(run) -> TrackedRun:
        tags = dict(run.data.tags or {})
        return TrackedRun(
            run_id=str(run.info.run_id),
            experiment_id=str(run.info.experiment_id),
            run_name=run.info.run_name,
            status=run.info.status,
            start_time=run.info.start_time,
            end_time=run.info.end_time,
            artifact_uri=run.info.artifact_uri,
            params=dict(run.data.params or {}),
            metrics={
                str(key): float(value)
                for key, value in (run.data.metrics or {}).items()
            },
            tags=tags,
            parent_run_id=tags.get("mlflow.parentRunId"),
        )

    @staticmethod
    @contextmanager
    def _translate_errors() -> Iterator[None]:
        try:
            yield
        except MlflowException as error:
            if error.error_code == "RESOURCE_DOES_NOT_EXIST":
                raise TrackingNotFound("Tracking resource not found") from error
            raise TrackingUnavailable("Experiment tracking is unavailable") from error
        except (ConnectionError, OSError, TimeoutError) as error:
            raise TrackingUnavailable("Experiment tracking is unavailable") from error
