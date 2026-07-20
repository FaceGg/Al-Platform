"""Pure, resumable scikit-learn iterative training core."""

import copy
import io
import math
from dataclasses import dataclass
from types import MappingProxyType
from typing import Callable, Mapping

import joblib
import numpy as np
import pandas as pd
from sklearn.linear_model import SGDClassifier, SGDRegressor
from sklearn.metrics import accuracy_score, log_loss, mean_squared_error, r2_score
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler


class IncompatibleCheckpoint(ValueError):
    pass


@dataclass(frozen=True)
class TrainingConfig:
    task: str = "auto"
    total_epochs: int = 20
    monitor: str = "val_accuracy"
    mode: str = "max"
    patience: int = 5
    min_delta: float = 0.0
    restore_best: bool = True
    checkpoint_interval: int = 5
    validation_size: float = 0.25
    random_state: int = 42

    def __post_init__(self) -> None:
        if self.task not in {"auto", "classification", "regression"}:
            raise ValueError("Task must be auto, classification, or regression")
        if self.total_epochs < 1:
            raise ValueError("Total epochs must be at least one")
        if self.mode not in {"min", "max"}:
            raise ValueError("Monitor mode must be min or max")
        if self.patience < 1:
            raise ValueError("Early stopping patience must be at least one")
        if self.min_delta < 0 or not math.isfinite(self.min_delta):
            raise ValueError("Minimum delta must be a finite non-negative value")
        if self.checkpoint_interval < 1:
            raise ValueError("Checkpoint interval must be at least one")
        if not 0 < self.validation_size < 1:
            raise ValueError("Validation size must be between zero and one")


@dataclass(frozen=True)
class EpochMetrics:
    epoch: int
    values: Mapping[str, float]

    def __post_init__(self) -> None:
        normalized = {str(key): float(value) for key, value in self.values.items()}
        if not all(math.isfinite(value) for value in normalized.values()):
            raise ValueError("Epoch metrics must be finite")
        object.__setattr__(self, "values", MappingProxyType(normalized))


@dataclass
class TrainingCheckpoint:
    format_version: int
    model: object
    best_model: object
    scaler: StandardScaler
    epoch: int
    best_epoch: int
    best_metric: float
    no_improvement_count: int
    classes: tuple | None
    feature_schema: tuple[tuple[str, str], ...]
    target_schema: dict
    config: TrainingConfig
    dataset_artifact_id: str | None = None
    source_job_id: str | None = None
    source_run_id: str | None = None

    CURRENT_FORMAT_VERSION = 1

    def dumps(self) -> bytes:
        stream = io.BytesIO()
        joblib.dump(self, stream)
        return stream.getvalue()

    @classmethod
    def loads(cls, payload: bytes) -> "TrainingCheckpoint":
        try:
            value = joblib.load(io.BytesIO(payload))
        except Exception as error:
            raise IncompatibleCheckpoint("Checkpoint payload is invalid") from error
        version = (
            value.get("format_version")
            if isinstance(value, dict)
            else getattr(value, "format_version", None)
        )
        if version != cls.CURRENT_FORMAT_VERSION:
            raise IncompatibleCheckpoint("Checkpoint format version is unsupported")
        if not isinstance(value, cls):
            raise IncompatibleCheckpoint("Checkpoint payload has an invalid structure")
        return value


@dataclass(frozen=True)
class CheckpointEnvelope:
    epoch: int
    payload: bytes
    is_best: bool


@dataclass(frozen=True)
class TrainingResult:
    model: object
    scaler: StandardScaler
    metrics: Mapping[str, float]
    history: tuple[EpochMetrics, ...]
    epochs_completed: int
    best_epoch: int
    best_metric: float
    stopped_early: bool
    cancelled: bool
    model_state: TrainingCheckpoint

    def __post_init__(self) -> None:
        object.__setattr__(self, "metrics", MappingProxyType(dict(self.metrics)))


class IterativeTrainer:
    def fit(
        self,
        frame: pd.DataFrame,
        *,
        target_column: str,
        config: TrainingConfig,
        metric_callback: Callable[[EpochMetrics], None] | None = None,
        checkpoint_callback: Callable[[CheckpointEnvelope], None] | None = None,
        cancel_requested: Callable[[], bool] | None = None,
        resume_from: TrainingCheckpoint | None = None,
        dataset_artifact_id: str | None = None,
        source_job_id: str | None = None,
        source_run_id: str | None = None,
    ) -> TrainingResult:
        metric_callback = metric_callback or (lambda _metrics: None)
        checkpoint_callback = checkpoint_callback or (lambda _checkpoint: None)
        cancel_requested = cancel_requested or (lambda: False)

        prepared = self._prepare_data(frame, target_column, config)
        (
            x_train,
            x_validation,
            y_train,
            y_validation,
            task,
            feature_schema,
            target_schema,
        ) = prepared

        if resume_from is None:
            scaler = StandardScaler().fit(x_train)
            model, classes = self._new_model(task, y_train, config.random_state)
            best_model = None
            best_epoch = 0
            best_metric = None
            no_improvement_count = 0
            start_epoch = 1
        else:
            self._validate_resume(
                resume_from,
                config,
                feature_schema,
                target_schema,
                task,
            )
            scaler = resume_from.scaler
            model = resume_from.model
            best_model = resume_from.best_model
            best_epoch = resume_from.best_epoch
            best_metric = resume_from.best_metric
            no_improvement_count = resume_from.no_improvement_count
            classes = np.asarray(resume_from.classes) if resume_from.classes is not None else None
            start_epoch = resume_from.epoch + 1
            dataset_artifact_id = dataset_artifact_id or resume_from.dataset_artifact_id
            source_job_id = source_job_id or resume_from.source_job_id
            source_run_id = source_run_id or resume_from.source_run_id

        if start_epoch > config.total_epochs:
            raise ValueError("Total epochs must exceed the checkpoint epoch")

        x_train_scaled = scaler.transform(x_train)
        x_validation_scaled = scaler.transform(x_validation)
        history = []
        cancelled = False
        stopped_early = False
        latest_state = None

        for epoch in range(start_epoch, config.total_epochs + 1):
            if task == "classification":
                if epoch == 1 and resume_from is None:
                    model.partial_fit(x_train_scaled, y_train, classes=classes)
                else:
                    model.partial_fit(x_train_scaled, y_train)
                values = self._classification_metrics(
                    model,
                    x_train_scaled,
                    x_validation_scaled,
                    y_train,
                    y_validation,
                    classes,
                )
            else:
                model.partial_fit(x_train_scaled, y_train)
                values = self._regression_metrics(
                    model,
                    x_train_scaled,
                    x_validation_scaled,
                    y_train,
                    y_validation,
                )

            if config.monitor not in values:
                raise ValueError(f"Unsupported monitor metric '{config.monitor}'")
            epoch_metrics = EpochMetrics(epoch=epoch, values=values)
            history.append(epoch_metrics)
            metric_callback(epoch_metrics)

            monitored = epoch_metrics.values[config.monitor]
            improved = self._is_improved(monitored, best_metric, config)
            if improved:
                best_metric = monitored
                best_epoch = epoch
                best_model = copy.deepcopy(model)
                no_improvement_count = 0
            else:
                no_improvement_count += 1

            latest_state = TrainingCheckpoint(
                format_version=TrainingCheckpoint.CURRENT_FORMAT_VERSION,
                model=copy.deepcopy(model),
                best_model=copy.deepcopy(best_model),
                scaler=copy.deepcopy(scaler),
                epoch=epoch,
                best_epoch=best_epoch,
                best_metric=float(best_metric),
                no_improvement_count=no_improvement_count,
                classes=tuple(classes.tolist()) if classes is not None else None,
                feature_schema=feature_schema,
                target_schema=dict(target_schema),
                config=config,
                dataset_artifact_id=dataset_artifact_id,
                source_job_id=source_job_id,
                source_run_id=source_run_id,
            )

            cancelled = bool(cancel_requested())
            stopped_early = no_improvement_count >= config.patience
            final_epoch = epoch == config.total_epochs
            if improved or epoch % config.checkpoint_interval == 0 or cancelled or stopped_early or final_epoch:
                checkpoint_callback(CheckpointEnvelope(
                    epoch=epoch,
                    payload=latest_state.dumps(),
                    is_best=improved,
                ))
            if cancelled or stopped_early:
                break

        if latest_state is None:
            raise RuntimeError("Training produced no model state")
        result_model = (
            copy.deepcopy(best_model)
            if config.restore_best and best_model is not None
            else model
        )
        final_state = copy.deepcopy(latest_state)
        final_state.model = copy.deepcopy(result_model)
        return TrainingResult(
            model=result_model,
            scaler=scaler,
            metrics=history[-1].values,
            history=tuple(history),
            epochs_completed=latest_state.epoch,
            best_epoch=best_epoch,
            best_metric=float(best_metric),
            stopped_early=stopped_early,
            cancelled=cancelled,
            model_state=final_state,
        )

    @staticmethod
    def _prepare_data(frame, target_column, config):
        if target_column not in frame.columns:
            raise ValueError(f"Target column '{target_column}' not found")
        features = frame.drop(columns=[target_column]).select_dtypes(include=["number"])
        combined = features.copy()
        combined[target_column] = frame[target_column]
        combined = combined.dropna()
        features = combined.drop(columns=[target_column])
        target = combined[target_column]
        if features.empty or len(features) < 8:
            raise ValueError("Training requires numeric features and at least eight rows")
        task = config.task
        if task == "auto":
            task = "classification" if target.nunique() <= 20 else "regression"
        if task == "classification" and target.nunique() < 2:
            raise ValueError("Classification requires at least two target classes")
        stratify = None
        if task == "classification" and target.value_counts().min() >= 2:
            stratify = target
        x_train, x_validation, y_train, y_validation = train_test_split(
            features,
            target,
            test_size=config.validation_size,
            random_state=config.random_state,
            stratify=stratify,
        )
        feature_schema = tuple(
            (str(name), str(features[name].dtype)) for name in features.columns
        )
        target_schema = {
            "name": target_column,
            "dtype": str(target.dtype),
            "task": task,
        }
        return (
            x_train,
            x_validation,
            y_train,
            y_validation,
            task,
            feature_schema,
            target_schema,
        )

    @staticmethod
    def _new_model(task, target, random_state):
        if task == "classification":
            classes = np.unique(target)
            return (
                SGDClassifier(
                    loss="log_loss",
                    random_state=random_state,
                    learning_rate="constant",
                    eta0=0.01,
                ),
                classes,
            )
        return (
            SGDRegressor(
                random_state=random_state,
                learning_rate="constant",
                eta0=0.001,
            ),
            None,
        )

    @staticmethod
    def _classification_metrics(model, x_train, x_validation, y_train, y_validation, classes):
        train_probabilities = model.predict_proba(x_train)
        validation_probabilities = model.predict_proba(x_validation)
        validation_predictions = model.predict(x_validation)
        return {
            "train_loss": float(log_loss(y_train, train_probabilities, labels=classes)),
            "val_loss": float(log_loss(y_validation, validation_probabilities, labels=classes)),
            "val_accuracy": float(accuracy_score(y_validation, validation_predictions)),
        }

    @staticmethod
    def _regression_metrics(model, x_train, x_validation, y_train, y_validation):
        train_predictions = model.predict(x_train)
        validation_predictions = model.predict(x_validation)
        validation_loss = float(mean_squared_error(y_validation, validation_predictions))
        return {
            "train_loss": float(mean_squared_error(y_train, train_predictions)),
            "val_loss": validation_loss,
            "val_r2": float(r2_score(y_validation, validation_predictions)),
            "val_rmse": float(validation_loss ** 0.5),
        }

    @staticmethod
    def _is_improved(value, best, config):
        if best is None:
            return True
        if config.mode == "max":
            return value > best + config.min_delta
        return value < best - config.min_delta

    @staticmethod
    def _validate_resume(checkpoint, config, feature_schema, target_schema, task):
        if checkpoint.format_version != TrainingCheckpoint.CURRENT_FORMAT_VERSION:
            raise IncompatibleCheckpoint("Checkpoint format version is unsupported")
        if checkpoint.feature_schema != feature_schema or checkpoint.target_schema != target_schema:
            raise IncompatibleCheckpoint("Checkpoint schema does not match the dataset")
        previous = checkpoint.config
        compatible = (
            previous.task == config.task
            and previous.monitor == config.monitor
            and previous.mode == config.mode
            and previous.patience == config.patience
            and previous.min_delta == config.min_delta
            and previous.validation_size == config.validation_size
            and previous.random_state == config.random_state
            and target_schema["task"] == task
        )
        if not compatible:
            raise IncompatibleCheckpoint("Checkpoint training configuration is incompatible")
