import os
import glob
import json
import uuid
import threading
from datetime import datetime, timezone
from typing import Optional, List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Body, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.training import TrainingJob
from app.models.project import Project
from app.models.artifact import Artifact
from app.models.user import User
from app.api.auth import get_current_user
from app.services.artifact_service import ArtifactAccessError, build_artifact_service
from app.services.training_service import TrainingService

router = APIRouter(prefix="/api/training", tags=["training"])

# --------------------------------------------------------------------------
# Pydantic-ish request models (inline dicts accepted)
# --------------------------------------------------------------------------

# --------------------------------------------------------------------------
# Training Job CRUD
# --------------------------------------------------------------------------


@router.post("/run")
def start_training(
    data: dict = Body(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project_id = data.get("project_id")
    if not project_id:
        raise HTTPException(400, "project_id is required")

    project = db.query(Project).filter(
        Project.id == UUID(project_id),
        Project.owner_id == current_user.id,
    ).first()
    if not project:
        raise HTTPException(404, "Project not found")

    dataset_artifact_id = data.get("dataset_artifact_id")
    if not dataset_artifact_id:
        raise HTTPException(400, {
            "code": "DATASET_ARTIFACT_REQUIRED",
            "message": "dataset_artifact_id is required",
        })
    artifact_service = build_artifact_service(db)
    try:
        dataset = artifact_service.resolve(
            UUID(dataset_artifact_id), UUID(project_id), expected_type="dataset",
        )
    except (ValueError, ArtifactAccessError) as exc:
        raise HTTPException(400, {
            "code": "DATASET_ARTIFACT_INVALID", "message": str(exc),
        }) from exc

    job = TrainingJob(
        project_id=UUID(project_id),
        user_id=current_user.id,
        name=data.get("name", "training_job"),
        operator_id=data.get("operator_id"),
        params=data.get("params", {}),
        dataset_artifact_id=dataset.id,
        dataset_path=artifact_service.storage_reference(dataset),
        status="pending",
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    # Start background training thread
    thread = threading.Thread(target=_run_training_artifact, args=(str(job.id),), daemon=True)
    thread.start()

    return {"job_id": str(job.id), "status": "started"}


@router.get("/jobs")
def list_training_jobs(
    project_id: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = db.query(TrainingJob).filter(TrainingJob.user_id == current_user.id)
    if project_id:
        q = q.filter(TrainingJob.project_id == UUID(project_id))
    jobs = q.order_by(TrainingJob.created_at.desc()).all()
    return [_job_to_dict(j) for j in jobs]


@router.get("/jobs/{job_id}")
def get_training_job(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    job = db.query(TrainingJob).filter(
        TrainingJob.id == UUID(job_id),
        TrainingJob.user_id == current_user.id,
    ).first()
    if not job:
        raise HTTPException(404, "Training job not found")
    return _job_to_dict(job)


# --------------------------------------------------------------------------
# AutoML
# --------------------------------------------------------------------------


@router.post("/automl/run")
def automl_start(
    data: dict = Body(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project_id = data.get("project_id")
    dataset_path = data.get("dataset_path")
    target_column = data.get("target_column")
    task = data.get("task", "classification")
    time_budget = data.get("time_budget", 60)

    if not project_id or not dataset_path or not target_column:
        raise HTTPException(400, "project_id, dataset_path, and target_column are required")

    project = db.query(Project).filter(
        Project.id == UUID(project_id),
        Project.owner_id == current_user.id,
    ).first()
    if not project:
        raise HTTPException(404, "Project not found")

    job = TrainingJob(
        project_id=UUID(project_id),
        user_id=current_user.id,
        name=data.get("name", f"automl_{task}"),
        operator_id="automl",
        params={
            "target_column": target_column,
            "task": task,
            "time_budget": time_budget,
        },
        dataset_path=dataset_path,
        status="pending",
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    thread = threading.Thread(
        target=_run_automl,
        args=(str(job.id), dataset_path, target_column, task, time_budget),
        daemon=True,
    )
    thread.start()

    return {"job_id": str(job.id), "status": "started"}


@router.get("/automl/jobs")
def list_automl_jobs(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    jobs = (
        db.query(TrainingJob)
        .filter(
            TrainingJob.user_id == current_user.id,
            TrainingJob.operator_id == "automl",
        )
        .order_by(TrainingJob.created_at.desc())
        .all()
    )
    return [_job_to_dict(j) for j in jobs]



# --------------------------------------------------------------------------
# Checkpoints & Model Versions
# --------------------------------------------------------------------------


@router.get("/checkpoints")
def list_checkpoints(training_job_id: str, db=Depends(get_db)):
    """列出训练的检查点"""
    ckpt_dir = os.path.join("checkpoints", training_job_id)
    if not os.path.exists(ckpt_dir):
        return {"checkpoints": []}
    files = sorted(glob.glob(os.path.join(ckpt_dir, "*.pkl")), key=os.path.getmtime, reverse=True)
    return {"checkpoints": [{"name": os.path.basename(f), "size": os.path.getsize(f)} for f in files]}


@router.get("/models/versions")
def list_model_versions(project_id: str, db=Depends(get_db)):
    """列出项目的模型版本历史"""
    jobs = (
        db.query(TrainingJob)
        .filter(
            TrainingJob.project_id == uuid.UUID(project_id),
            TrainingJob.status == "completed",
        )
        .order_by(TrainingJob.finished_at.desc())
        .all()
    )
    return {
        "versions": [
            {
                "version": j.model_version,
                "id": str(j.id),
                "metrics": j.metrics,
                "finished_at": j.finished_at.isoformat() if j.finished_at else None,
            }
            for j in jobs
        ]
    }


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _job_to_dict(job: TrainingJob) -> dict:
    return {
        "id": str(job.id),
        "project_id": str(job.project_id),
        "user_id": str(job.user_id),
        "name": job.name,
        "operator_id": job.operator_id,
        "params": job.params,
        "dataset_path": job.dataset_path,
        "dataset_artifact_id": str(job.dataset_artifact_id) if job.dataset_artifact_id else None,
        "status": job.status,
        "metrics": job.metrics,
        "model_path": job.model_path,
        "model_artifact_id": str(job.model_artifact_id) if job.model_artifact_id else None,
        "model_library_id": str(job.model_library_id) if job.model_library_id else None,
        "feature_schema": job.feature_schema or [],
        "target_schema": job.target_schema or {},
        "preprocessing": job.preprocessing or {},
        "error_code": job.error_code,
        "error_details": job.error_details,
        "logs": job.logs or [],
        "error_message": job.error_message,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "created_at": job.created_at.isoformat() if job.created_at else None,
    }


def _get_db_session() -> Session:
    from app.database import SessionLocal
    return SessionLocal()


def _run_training_artifact(job_id: str):
    db = _get_db_session()
    try:
        artifact_service = build_artifact_service(db)
        TrainingService(db, artifact_service).run(UUID(job_id))
    finally:
        db.close()


def _run_training(job_id: str):
    db = _get_db_session()
    try:
        job = db.query(TrainingJob).filter(TrainingJob.id == UUID(job_id)).first()
        if not job:
            return

        job.status = "running"
        job.started_at = datetime.now(timezone.utc)
        db.commit()

        import pandas as pd
        from sklearn.model_selection import train_test_split, cross_val_score
        from sklearn.ensemble import RandomForestRegressor, RandomForestClassifier
        from sklearn.linear_model import LinearRegression, LogisticRegression
        from sklearn.metrics import accuracy_score, r2_score, mean_squared_error

        dataset_path = job.dataset_path

        if not os.path.exists(dataset_path):
            # Try resolving from uploads directory
            uploads_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "uploads")
            alt_path = os.path.join(uploads_dir, os.path.basename(dataset_path))
            if os.path.exists(alt_path):
                dataset_path = alt_path
            else:
                raise FileNotFoundError(f"Dataset not found: {job.dataset_path}")

        if dataset_path.endswith((".xls", ".xlsx")):
            df = pd.read_excel(dataset_path)
        else:
            df = pd.read_csv(dataset_path)

        params = job.params or {}

        df = df.dropna()
        X = df.select_dtypes(include=["number"])
        target_col = params.get("target_column")
        if target_col and target_col in df.columns:
            y = df[target_col]
        else:
            target_col = X.columns[-1]
            y = X[target_col]
            X = X.drop(columns=[target_col])

        X = X.select_dtypes(include=["number"])
        X = X.loc[:, (X != X.iloc[0]).any()]

        if X.empty or len(y) == 0:
            raise ValueError("No valid numeric features or target found")

        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

        unique_vals = y.nunique()
        if unique_vals <= 10 and unique_vals >= 2:
            model = RandomForestClassifier(n_estimators=100, random_state=42)
            model.fit(X_train, y_train)
            y_pred = model.predict(X_test)
            score = float(accuracy_score(y_test, y_pred))
            score_name = "accuracy"
        else:
            model = RandomForestRegressor(n_estimators=100, random_state=42)
            model.fit(X_train, y_train)
            y_pred = model.predict(X_test)
            score = float(r2_score(y_test, y_pred))
            score_name = "r2"
            rmse = float(mean_squared_error(y_test, y_pred, squared=False))

        import joblib as jl
        model_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "models_saved")
        os.makedirs(model_dir, exist_ok=True)
        model_path = os.path.join(model_dir, f"model_{job_id}.joblib")
        jl.dump(model, model_path)

        metrics = {score_name: score}
        if score_name == "r2":
            metrics["rmse"] = rmse

        job.model_path = model_path
        job.metrics = metrics
        job.status = "completed"
        job.finished_at = datetime.now(timezone.utc)
        db.commit()
    except Exception as e:
        db = _get_db_session()
        job = db.query(TrainingJob).filter(TrainingJob.id == UUID(job_id)).first()
        if job:
            job.status = "failed"
            job.error_message = str(e)
            job.finished_at = datetime.now(timezone.utc)
            db.commit()
    finally:
        db.close()


def _run_automl(job_id: str, dataset_path: str, target_column: str, task: str, time_budget: int):
    db = _get_db_session()
    try:
        job = db.query(TrainingJob).filter(TrainingJob.id == UUID(job_id)).first()
        if not job:
            return

        job.status = "running"
        job.started_at = datetime.now(timezone.utc)
        db.commit()

        import pandas as pd
        import numpy as np
        from sklearn.model_selection import cross_val_score, train_test_split
        from sklearn.preprocessing import LabelEncoder, StandardScaler
        from sklearn.impute import SimpleImputer

        if not os.path.exists(dataset_path):
            uploads_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "uploads")
            alt_path = os.path.join(uploads_dir, os.path.basename(dataset_path))
            if os.path.exists(alt_path):
                dataset_path = alt_path
            else:
                raise FileNotFoundError(f"Dataset not found: {dataset_path}")

        if dataset_path.endswith((".xls", ".xlsx")):
            df = pd.read_excel(dataset_path)
        else:
            df = pd.read_csv(dataset_path)

        if target_column not in df.columns:
            raise ValueError(f"Target column '{target_column}' not found in dataset")

        y = df[target_column].copy()
        X = df.drop(columns=[target_column])

        for col in X.select_dtypes(include=["object"]).columns:
            if X[col].nunique() < 50:
                X[col] = X[col].fillna("missing")
                le = LabelEncoder()
                X[col] = le.fit_transform(X[col].astype(str))
            else:
                X = X.drop(columns=[col])

        X = X.select_dtypes(include=["number"])
        imputer = SimpleImputer(strategy="mean")
        X = pd.DataFrame(imputer.fit_transform(X), columns=X.columns)

        # Encode target for classification
        is_classification = task == "classification" or y.nunique() <= 20
        if is_classification:
            if y.dtype == "object":
                y_le = LabelEncoder()
                y = pd.Series(y_le.fit_transform(y), name=target_column)

        scaler = StandardScaler()
        X_scaled = pd.DataFrame(scaler.fit_transform(X), columns=X.columns)

        all_results = []
        best_model = None
        best_score = -float("inf")
        best_model_obj = None

        if is_classification:
            from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
            from sklearn.linear_model import LogisticRegression
            from sklearn.svm import SVC

            candidates = [
                ("RandomForest", RandomForestClassifier(n_estimators=100, random_state=42)),
                ("GradientBoosting", GradientBoostingClassifier(n_estimators=100, random_state=42)),
                ("LogisticRegression", LogisticRegression(max_iter=1000, random_state=42)),
                ("SVM", SVC(kernel="rbf", random_state=42)),
            ]
            scoring = "accuracy"
        else:
            from sklearn.ensemble import RandomForestRegressor, GradientBoostingRegressor
            from sklearn.linear_model import LinearRegression

            candidates = [
                ("RandomForest", RandomForestRegressor(n_estimators=100, random_state=42)),
                ("GradientBoosting", GradientBoostingRegressor(n_estimators=100, random_state=42)),
                ("LinearRegression", LinearRegression()),
            ]
            scoring = "r2"

        for name, model in candidates:
            try:
                scores = cross_val_score(model, X_scaled, y, cv=5, scoring=scoring)
                mean_score = float(scores.mean())
                all_results.append({"model": name, "score": mean_score})
                if mean_score > best_score:
                    best_score = mean_score
                    best_model = name
                    best_model_obj = model
            except Exception:
                all_results.append({"model": name, "score": None, "error": "failed"})

        if best_model_obj is None:
            raise ValueError("All models failed during cross-validation")

        # Full training of best model
        X_train, X_test, y_train, y_test = train_test_split(X_scaled, y, test_size=0.2, random_state=42)
        best_model_obj.fit(X_train, y_train)

        import joblib as jl
        model_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "models_saved")
        os.makedirs(model_dir, exist_ok=True)
        model_path = os.path.join(model_dir, f"automl_{job_id}.joblib")
        jl.dump(best_model_obj, model_path)

        # Feature importance
        feature_importance = []
        if hasattr(best_model_obj, "feature_importances_"):
            importances = best_model_obj.feature_importances_
            feature_importance = sorted(
                zip(X.columns.tolist(), importances.tolist()),
                key=lambda x: x[1],
                reverse=True,
            )[:10]

        metrics = {
            "best_model": best_model,
            "best_score": best_score,
            "all_results": all_results,
            "feature_importance": [{"feature": f, "importance": i} for f, i in feature_importance],
        }

        job.model_path = model_path
        job.metrics = metrics
        job.status = "completed"
        job.finished_at = datetime.now(timezone.utc)
        db.commit()
    except Exception as e:
        db = _get_db_session()
        job = db.query(TrainingJob).filter(TrainingJob.id == UUID(job_id)).first()
        if job:
            job.status = "failed"
            job.error_message = str(e)
            job.finished_at = datetime.now(timezone.utc)
            db.commit()
    finally:
        db.close()


from pydantic import BaseModel
from typing import List

class BatchDeleteRequest(BaseModel):
    ids: List[str]

@router.post("/batch-delete", status_code=200)
def batch_delete_training_jobs(
    data: BatchDeleteRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    deleted = 0
    for tid_str in data.ids:
        try:
            uid = uuid.UUID(tid_str)
        except ValueError:
            continue
        job = db.query(TrainingJob).filter(
            TrainingJob.id == uid, TrainingJob.user_id == current_user.id
        ).first()
        if not job:
            continue
        db.delete(job)
        deleted += 1
    db.commit()
    return {"deleted": deleted}
