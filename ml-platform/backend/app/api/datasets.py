import os
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.project import Project
from app.models.artifact import Artifact
from app.models.user import User
from app.api.auth import get_current_user

router = APIRouter(prefix="/api", tags=["datasets"])

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)


@router.post("/projects/{project_id}/datasets/upload")
def upload_dataset(
    project_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = db.query(Project).filter(Project.id == project_id, Project.owner_id == current_user.id).first()
    if not project:
        raise HTTPException(404, "Project not found")

    file_path = os.path.join(UPLOAD_DIR, f"{UUID(project_id)}_{file.filename}")
    content = file.file.read()
    with open(file_path, "wb") as f:
        f.write(content)

    artifact = Artifact(
        project_id=UUID(project_id),
        name=file.filename or "uploaded_file",
        type="dataset",
        storage_path=file_path,
        file_size=len(content),
        format=file.filename.split(".")[-1] if file.filename else None,
    )
    db.add(artifact)
    db.commit()
    db.refresh(artifact)
    return {"id": str(artifact.id), "name": artifact.name, "storage_path": artifact.storage_path}


@router.get("/datasets/{dataset_id}/preview")
def preview_dataset(
    dataset_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    artifact = db.query(Artifact).filter(Artifact.id == dataset_id).first()
    if not artifact:
        raise HTTPException(404, "Dataset not found")

    import pandas as pd
    file_path = artifact.storage_path
    if not os.path.exists(file_path):
        raise HTTPException(404, "File not found on disk")

    try:
        if file_path.endswith((".xls", ".xlsx")):
            df = pd.read_excel(file_path)
        else:
            df = pd.read_csv(file_path)
        return {
            "columns": list(df.columns),
            "preview": df.head(10).to_dict(orient="records"),
            "total_rows": len(df),
            "dtypes": {str(k): str(v) for k, v in df.dtypes.items()},
        }
    except Exception as e:
        raise HTTPException(400, f"Failed to read file: {e}")
