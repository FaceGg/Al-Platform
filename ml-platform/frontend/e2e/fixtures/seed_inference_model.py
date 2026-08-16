"""Seed one real platform training model for browser acceptance."""

import json
from pathlib import Path
import sys
import tempfile
import uuid

import joblib
import numpy as np
from sklearn.linear_model import LogisticRegression


BACKEND_ROOT = Path(__file__).resolve().parents[3] / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

import app.main  # noqa: E402,F401 (load complete ORM graph)
from app.database import SessionLocal  # noqa: E402
from app.models.model_library import ModelLibrary  # noqa: E402
from app.models.project import Project  # noqa: E402
from app.models.training import TrainingJob  # noqa: E402
from app.services.artifact_service import build_artifact_service  # noqa: E402


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("project ID is required")
    project_id = uuid.UUID(sys.argv[1])
    features = [
        {"name": "current", "dtype": "float64"},
        {"name": "voltage", "dtype": "float64"},
    ]
    target = {"name": "fault", "dtype": "int64", "task": "classification"}
    estimator = LogisticRegression(random_state=0).fit(
        np.asarray([[0.0, 0.0], [0.0, 1.0], [1.0, 0.0], [9.0, 9.0]]),
        np.asarray([0, 0, 0, 1]),
    )
    with tempfile.TemporaryDirectory(prefix="inference-e2e-") as directory, SessionLocal() as db:
        project = db.query(Project).filter(Project.id == project_id).one()
        model_library_ids = []
        for version in (1, 2):
            job = TrainingJob(
                project_id=project.id,
                user_id=project.owner_id,
                name=f"browser-source-v{version}-{uuid.uuid4().hex[:8]}",
                status="completed",
                feature_schema=features,
                target_schema=target,
            )
            db.add(job)
            db.flush()
            source = Path(directory) / f"browser-source-v{version}.joblib"
            joblib.dump(
                {"model": estimator, "feature_schema": features, "target_schema": target},
                source,
            )
            artifact = build_artifact_service(db).create_from_file(
                project.id,
                source,
                source.name,
                "model",
                metadata={"source": "training", "training_job_id": str(job.id)},
                commit=False,
            )
            library = ModelLibrary(
                name=job.name,
                project_id=project.id,
                owner_id=project.owner_id,
                status="completed",
                framework="scikit-learn",
                backbone="LogisticRegression",
                metrics={"accuracy": 1.0},
                format="joblib",
                training_job_id=job.id,
                model_artifact_id=artifact.id,
            )
            db.add(library)
            db.flush()
            job.model_artifact_id = artifact.id
            job.model_library_id = library.id
            model_library_ids.append(str(library.id))
        db.commit()
        print(json.dumps({
            "model_library_id": model_library_ids[0],
            "model_library_ids": model_library_ids,
        }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
