import platform
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import joblib
import pandas as pd
import sklearn
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.metrics import accuracy_score, mean_squared_error, r2_score
from sklearn.model_selection import train_test_split
from sqlalchemy.orm import Session

from app.models.model_library import ModelLibrary
from app.models.training import TrainingJob
from app.services.artifact_service import ArtifactService


class TrainingService:
    def __init__(self, db: Session, artifact_service: ArtifactService):
        self.db = db
        self.artifact_service = artifact_service

    def run(self, job_id) -> TrainingJob:
        job = self.db.query(TrainingJob).filter(TrainingJob.id == job_id).one()
        job.status = "running"
        job.started_at = datetime.now(timezone.utc)
        job.logs = [{"level": "info", "message": "Training started"}]
        self.db.commit()
        try:
            dataset = self.artifact_service.resolve(
                job.dataset_artifact_id, job.project_id, expected_type="dataset",
            )
            with self.artifact_service.materialize(
                dataset.id, job.project_id, expected_type="dataset",
            ) as path:
                frame = (
                    pd.read_excel(path)
                    if path.suffix.lower() in {".xls", ".xlsx"}
                    else pd.read_csv(path)
                )
            params = job.params or {}
            target_column = params.get("target_column")
            if not target_column or target_column not in frame.columns:
                raise ValueError(f"Target column '{target_column}' not found in dataset")

            target = frame[target_column]
            features = frame.drop(columns=[target_column]).select_dtypes(include=["number"])
            features = features.dropna(axis=0)
            target = target.loc[features.index]
            if features.empty or len(features) < 5:
                raise ValueError("No valid numeric features or insufficient rows")
            feature_schema = [{"name": str(name), "dtype": str(features[name].dtype)} for name in features.columns]
            classification = target.nunique() <= 20
            x_train, x_test, y_train, y_test = train_test_split(
                features, target, test_size=0.25, random_state=42,
                stratify=target if classification and target.value_counts().min() >= 2 else None,
            )
            if classification:
                model = RandomForestClassifier(
                    n_estimators=int(params.get("n_estimators", 100)), random_state=42,
                )
                model.fit(x_train, y_train)
                predictions = model.predict(x_test)
                metrics = {"accuracy": float(accuracy_score(y_test, predictions))}
                task_type = "classification"
            else:
                model = RandomForestRegressor(
                    n_estimators=int(params.get("n_estimators", 100)), random_state=42,
                )
                model.fit(x_train, y_train)
                predictions = model.predict(x_test)
                metrics = {
                    "r2": float(r2_score(y_test, predictions)),
                    "rmse": float(mean_squared_error(y_test, predictions) ** 0.5),
                }
                task_type = "regression"

            target_schema = {"name": target_column, "dtype": str(target.dtype), "task": task_type}
            preprocessing = {"numeric_features_only": True, "drop_missing_rows": True}
            with tempfile.TemporaryDirectory() as temporary:
                model_path = Path(temporary) / f"{job.id}.joblib"
                joblib.dump({
                    "model": model,
                    "feature_schema": feature_schema,
                    "target_schema": target_schema,
                    "preprocessing": preprocessing,
                }, model_path)
                artifact = self.artifact_service.create_from_file(
                    job.project_id, model_path, f"{job.name}.joblib", "model",
                    metadata={
                        "source": "training",
                        "training_job_id": str(job.id),
                        "dataset_artifact_id": str(dataset.id),
                        "feature_schema": feature_schema,
                        "target_schema": target_schema,
                        "preprocessing": preprocessing,
                        "metrics": metrics,
                        "python_version": platform.python_version(),
                        "sklearn_version": sklearn.__version__,
                    },
                )

            model_entry = ModelLibrary(
                name=job.name,
                project_id=job.project_id,
                owner_id=job.user_id,
                status="completed",
                framework="scikit-learn",
                backbone=type(model).__name__,
                metrics=metrics,
                params=params,
                model_path=self.artifact_service.storage_reference(artifact),
                file_size=artifact.file_size or 0,
                format="joblib",
                training_job_id=job.id,
                dataset_artifact_id=dataset.id,
                model_artifact_id=artifact.id,
            )
            self.db.add(model_entry)
            self.db.flush()
            job.dataset_path = self.artifact_service.storage_reference(dataset)
            job.model_path = self.artifact_service.storage_reference(artifact)
            job.model_artifact_id = artifact.id
            job.model_library_id = model_entry.id
            job.feature_schema = feature_schema
            job.target_schema = target_schema
            job.preprocessing = preprocessing
            job.metrics = metrics
            job.status = "completed"
            job.finished_at = datetime.now(timezone.utc)
            job.logs = [*(job.logs or []), {"level": "info", "message": "Training completed"}]
            self.db.commit()
            return job
        except Exception as exc:
            self.db.rollback()
            job = self.db.query(TrainingJob).filter(TrainingJob.id == job_id).one()
            job.status = "failed"
            job.error_code = "TRAINING_FAILED"
            job.error_message = str(exc)
            job.error_details = {"exception_type": type(exc).__name__}
            job.finished_at = datetime.now(timezone.utc)
            job.logs = [*(job.logs or []), {"level": "error", "message": str(exc)}]
            self.db.commit()
            return job
