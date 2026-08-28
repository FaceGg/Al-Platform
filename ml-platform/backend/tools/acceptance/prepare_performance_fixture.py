"""Prepare isolated production objects for fixed-load Week 11 evidence.

The only generated secrets remain in /tmp inside the acceptance backend.
"""

from __future__ import annotations

import json
import tempfile
import uuid
from pathlib import Path

import joblib
import numpy as np
from fastapi.testclient import TestClient
from sklearn.linear_model import LogisticRegression

import app.main
from app.api.auth import create_access_token
from app.database import SessionLocal
from app.models.model_library import ModelLibrary
from app.models.project import Project
from app.models.training import TrainingJob
from app.models.user import User
from app.models.workflow import Workflow, WorkflowNode
from app.services.artifact_service import build_artifact_service


def expect(response, status: int) -> dict:
    if response.status_code != status:
        raise RuntimeError(f"Expected HTTP {status}, got {response.status_code}: {response.text}")
    data = response.json()
    if not isinstance(data, dict):
        raise RuntimeError("Fixture endpoint returned a non-object response")
    return data


def main() -> None:
    unique = uuid.uuid4().hex
    with tempfile.TemporaryDirectory() as directory, SessionLocal() as db:
        owner = User(
            username=f"week11-performance-{unique}",
            password_hash="acceptance-only-hash",
        )
        db.add(owner)
        db.flush()
        project = Project(name=f"Week 11 performance {unique}", owner_id=owner.id)
        db.add(project)
        db.flush()

        features = [
            {"name": "current", "dtype": "float64"},
            {"name": "force", "dtype": "float64"},
        ]
        target = {"name": "fault", "dtype": "int64", "task": "classification"}
        estimator = LogisticRegression(random_state=0).fit(
            np.asarray([[0.0, 0.0], [0.0, 1.0], [1.0, 0.0], [2.0, 2.0]]),
            np.asarray([0, 0, 0, 1]),
        )
        source_path = Path(directory) / "week11-performance-model.joblib"
        joblib.dump(
            {
                "model": estimator,
                "feature_schema": features,
                "target_schema": target,
            },
            source_path,
        )
        artifacts = build_artifact_service(db)
        job = TrainingJob(
            project_id=project.id,
            user_id=owner.id,
            name="week11-performance-model",
            status="completed",
            feature_schema=features,
            target_schema=target,
        )
        db.add(job)
        db.flush()
        source = artifacts.create_from_file(
            project.id,
            source_path,
            source_path.name,
            "model",
            metadata={"source": "training", "training_job_id": str(job.id)},
            commit=False,
        )
        library = ModelLibrary(
            name=job.name,
            project_id=project.id,
            owner_id=owner.id,
            status="completed",
            framework="scikit-learn",
            backbone="LogisticRegression",
            metrics={"accuracy": 1.0},
            format="joblib",
            training_job_id=job.id,
            model_artifact_id=source.id,
        )
        workflow = Workflow(
            project_id=project.id,
            name=f"Week 11 welding workflow {unique}",
            created_by=owner.id,
        )
        db.add_all((library, workflow))
        db.flush()
        db.add(
            WorkflowNode(
                workflow_id=workflow.id,
                operator_id="mechanism_thermal",
                label="Thermal validation",
                position_x=0.0,
                position_y=0.0,
                params={},
            )
        )
        job.model_artifact_id = source.id
        job.model_library_id = library.id
        db.commit()
        project_id = str(project.id)
        library_id = str(library.id)
        workflow_id = str(workflow.id)
        owner_id = str(owner.id)

    bearer = create_access_token({"sub": owner_id})
    client = TestClient(app.main.app)
    headers = {"Authorization": f"Bearer {bearer}"}
    try:
        model = expect(
            client.post(
                f"/api/projects/{project_id}/registered-models",
                headers=headers,
                json={"name": f"Week 11 model {unique}", "description": "Acceptance"},
            ),
            201,
        )
        version = expect(
            client.post(
                f"/api/registered-models/{model['id']}/versions",
                headers=headers,
                json={"source_kind": "platform_joblib", "source_model_library_id": library_id},
            ),
            201,
        )
        expect(
            client.post(
                f"/api/model-versions/{version['id']}/approve",
                headers=headers,
                json={"comment": "Week 11 performance acceptance"},
            ),
            200,
        )
        deployment = expect(
            client.post(
                f"/api/projects/{project_id}/inference-deployments",
                headers=headers,
                json={"name": f"week11-runtime-{unique}", "model_version_id": version["id"]},
            ),
            201,
        )
        deployment_id = deployment["id"]
        expect(
            client.post(
                f"/api/inference-deployments/{deployment_id}/start",
                headers=headers,
            ),
            200,
        )
        key = expect(
            client.post(
                f"/api/inference-deployments/{deployment_id}/api-keys",
                headers=headers,
                json={"scopes": ["inference.predict"]},
            ),
            201,
        )
    finally:
        client.close()

    context_path = Path("/tmp/week11-perf-context.json")
    body_path = Path("/tmp/week11-inference-body.json")
    context_path.write_text(
        json.dumps(
            {
                "api_key": key["plaintext"],
                "bearer": bearer,
                "deployment_id": deployment_id,
                "workflow_id": workflow_id,
            }
        ),
        encoding="utf-8",
    )
    body_path.write_text(
        json.dumps({"records": [{"current": 1234.567, "force": 7654.321}]}),
        encoding="utf-8",
    )
    context_path.chmod(0o600)
    body_path.chmod(0o600)
    print(json.dumps({"status": "prepared", "fixture": "week11-performance"}))


if __name__ == "__main__":
    main()
