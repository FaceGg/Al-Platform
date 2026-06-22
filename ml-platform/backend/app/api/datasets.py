import os
import io
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from fastapi.responses import StreamingResponse
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
    project = db.query(Project).filter(Project.id == UUID(project_id), Project.owner_id == current_user.id).first()
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


@router.post("/projects/{project_id}/datasets/batch")
def batch_import(
    project_id: str,
    files: List[UploadFile] = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = db.query(Project).filter(Project.id == UUID(project_id), Project.owner_id == current_user.id).first()
    if not project:
        raise HTTPException(404, "Project not found")

    results = []
    success_count = 0
    failed_count = 0

    for file in files:
        try:
            file_path = os.path.join(UPLOAD_DIR, f"{UUID(project_id)}_{file.filename}")
            content = file.file.read()
            with open(file_path, "wb") as f:
                f.write(content)

            fmt = file.filename.split(".")[-1] if file.filename else None
            artifact = Artifact(
                project_id=UUID(project_id),
                name=file.filename or "uploaded_file",
                type="dataset",
                storage_path=file_path,
                file_size=len(content),
                format=fmt,
            )
            db.add(artifact)
            db.commit()
            db.refresh(artifact)

            import pandas as pd
            rows = 0
            try:
                if file_path.endswith((".xls", ".xlsx")):
                    df = pd.read_excel(file_path)
                else:
                    df = pd.read_csv(file_path)
                rows = len(df)
            except Exception:
                rows = 0

            results.append({
                "id": str(artifact.id),
                "name": artifact.name,
                "format": artifact.format,
                "rows": rows,
            })
            success_count += 1
        except Exception as e:
            failed_count += 1
            results.append({
                "name": file.filename,
                "error": str(e),
            })

    db.commit()
    return {
        "total": len(files),
        "success": success_count,
        "failed": failed_count,
        "items": results,
    }


@router.get("/projects/{project_id}/datasets/export")
def export_dataset(
    project_id: str,
    format: str = Query(default="csv"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = db.query(Project).filter(Project.id == UUID(project_id), Project.owner_id == current_user.id).first()
    if not project:
        raise HTTPException(404, "Project not found")

    artifacts = db.query(Artifact).filter(Artifact.project_id == UUID(project_id)).all()
    if not artifacts:
        raise HTTPException(404, "No datasets found in project")

    import pandas as pd
    all_dfs = []
    for artifact in artifacts:
        file_path = artifact.storage_path
        if not os.path.exists(file_path):
            continue
        try:
            if file_path.endswith((".xls", ".xlsx")):
                df = pd.read_excel(file_path)
            else:
                df = pd.read_csv(file_path)
            all_dfs.append(df)
        except Exception:
            continue

    if not all_dfs:
        raise HTTPException(404, "No readable datasets found")

    combined = pd.concat(all_dfs, ignore_index=True)

    output = io.BytesIO()
    media_type = ""
    filename = ""
    if format == "json":
        combined.to_json(output, orient="records")
        media_type = "application/json"
        filename = "export.json"
    elif format == "excel":
        combined.to_excel(output, index=False, engine="openpyxl")
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        filename = "export.xlsx"
    elif format == "parquet":
        combined.to_parquet(output, index=False)
        media_type = "application/octet-stream"
        filename = "export.parquet"
    else:
        combined.to_csv(output, index=False)
        media_type = "text/csv"
        filename = "export.csv"

    output.seek(0)
    return StreamingResponse(
        output,
        media_type=media_type,
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/datasets/{dataset_id}/export")
def export_single_dataset(
    dataset_id: str,
    format: str = Query(default="csv"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    artifact = db.query(Artifact).filter(Artifact.id == UUID(dataset_id)).first()
    if not artifact:
        raise HTTPException(404, "Dataset not found")

    file_path = artifact.storage_path
    if not os.path.exists(file_path):
        raise HTTPException(404, "File not found on disk")

    import pandas as pd
    try:
        if file_path.endswith((".xls", ".xlsx")):
            df = pd.read_excel(file_path)
        else:
            df = pd.read_csv(file_path)
    except Exception as e:
        raise HTTPException(400, f"Failed to read file: {e}")

    output = io.BytesIO()
    media_type = ""
    filename = f"{artifact.name or 'dataset'}"
    if format == "json":
        df.to_json(output, orient="records")
        media_type = "application/json"
        filename += ".json"
    elif format == "excel":
        df.to_excel(output, index=False, engine="openpyxl")
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        filename += ".xlsx"
    elif format == "parquet":
        df.to_parquet(output, index=False)
        media_type = "application/octet-stream"
        filename += ".parquet"
    else:
        df.to_csv(output, index=False)
        media_type = "text/csv"
        filename += ".csv"

    output.seek(0)
    return StreamingResponse(
        output,
        media_type=media_type,
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/datasets/{dataset_id}/preview")
def preview_dataset(
    dataset_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    artifact = db.query(Artifact).filter(Artifact.id == UUID(dataset_id)).first()
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
