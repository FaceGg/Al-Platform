import os
import io
from typing import List, Optional
from uuid import UUID
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.project import Project
from app.models.artifact import Artifact
from app.models.user import User
from app.api.auth import get_current_user
from app.services.artifact_service import ArtifactService

router = APIRouter(prefix="/api", tags=["datasets"])

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "uploads")
ARTIFACT_DIR = os.getenv(
    "ARTIFACT_STORAGE_DIR",
    os.path.join(os.path.dirname(os.path.dirname(__file__)), "artifact_store"),
)
os.makedirs(UPLOAD_DIR, exist_ok=True)


def _store_uploaded_dataset(db: Session, project_id, file: UploadFile) -> Artifact:
    safe_name = Path(file.filename or "uploaded_file").name
    staging_path = Path(UPLOAD_DIR) / f"{uuid.uuid4()}_{safe_name}"
    staging_path.write_bytes(file.file.read())
    try:
        return ArtifactService(db, ARTIFACT_DIR).create_dataset(project_id, staging_path, safe_name)
    finally:
        staging_path.unlink(missing_ok=True)


@router.get("/projects/{project_id}/datasets")
def list_project_datasets(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = db.query(Project).filter(
        Project.id == UUID(project_id), Project.owner_id == current_user.id,
    ).first()
    if not project:
        raise HTTPException(404, "Project not found")

    artifacts = db.query(Artifact).filter(
        Artifact.project_id == project.id, Artifact.type == "dataset",
    ).order_by(Artifact.created_at.desc()).all()
    items = []
    for artifact in artifacts:
        metadata = artifact.metadata_ or {}
        items.append({
            "id": str(artifact.id),
            "artifact_id": str(artifact.id),
            "project_id": str(artifact.project_id),
            "name": artifact.name,
            "type": artifact.type,
            "format": artifact.format,
            "file_size": artifact.file_size,
            "row_count": metadata.get("row_count", 0),
            "schema": metadata.get("schema", []),
            "created_at": artifact.created_at,
        })
    return {"items": items, "total": len(items)}


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

    artifact = _store_uploaded_dataset(db, UUID(project_id), file)
    metadata = artifact.metadata_ or {}
    return {
        "id": str(artifact.id), "artifact_id": str(artifact.id),
        "name": artifact.name, "storage_path": artifact.storage_path,
        "row_count": metadata.get("row_count", 0),
        "schema": metadata.get("schema", []),
        "sha256": metadata.get("sha256", ""),
    }


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
            artifact = _store_uploaded_dataset(db, UUID(project_id), file)
            metadata = artifact.metadata_ or {}

            results.append({
                "id": str(artifact.id),
                "name": artifact.name,
                "format": artifact.format,
                "rows": metadata.get("row_count", 0),
                "schema": metadata.get("schema", []),
                "sha256": metadata.get("sha256", ""),
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



@router.post("/projects/{project_id}/datasets/batch-upload")
async def batch_upload_dataset(
    project_id: str,
    files: List[UploadFile] = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Batch upload multiple files or a folder to a project."""
    project = db.query(Project).filter(
        Project.id == UUID(project_id), Project.owner_id == current_user.id
    ).first()
    if not project:
        raise HTTPException(404, "Project not found")
    artifacts = []
    for file in files:
        content = await file.read()
        storage_path = os.path.join(UPLOAD_DIR, str(uuid.uuid4()), file.filename)
        os.makedirs(os.path.dirname(storage_path), exist_ok=True)
        with open(storage_path, "wb") as f:
            f.write(content)
        ext = os.path.splitext(file.filename)[1].lower()
        fmt_map = {".csv": "csv", ".xlsx": "xlsx", ".xls": "xls", ".txt": "txt",
                   ".json": "json", ".png": "png", ".jpg": "jpg"}
        artifact = Artifact(
            project_id=UUID(project_id), name=file.filename, type="dataset",
            storage_path=storage_path, file_size=len(content),
            format=fmt_map.get(ext, ext.lstrip(".")),
        )
        db.add(artifact)
        artifacts.append({"name": file.filename, "size": len(content), "format": fmt_map.get(ext, "")})
    db.commit()
    return {"message": f"Uploaded {len(artifacts)} files", "files": artifacts}


@router.post("/projects/{project_id}/datasets/import-zip")
async def import_zip_dataset(
    project_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Import a ZIP-compressed dataset. Extracts and processes all files inside."""
    import zipfile, tempfile
    project = db.query(Project).filter(
        Project.id == UUID(project_id), Project.owner_id == current_user.id
    ).first()
    if not project:
        raise HTTPException(404, "Project not found")
    content = await file.read()
    artifacts = []
    with tempfile.TemporaryDirectory() as tmpdir:
        zip_path = os.path.join(tmpdir, file.filename)
        with open(zip_path, "wb") as f:
            f.write(content)
        with zipfile.ZipFile(zip_path, "r") as zf:
            for member in zf.namelist():
                if member.endswith("/"):
                    continue
                extracted = zf.read(member)
                fname = os.path.basename(member)
                storage_path = os.path.join(UPLOAD_DIR, str(uuid.uuid4()), fname)
                os.makedirs(os.path.dirname(storage_path), exist_ok=True)
                with open(storage_path, "wb") as f:
                    f.write(extracted)
                ext = os.path.splitext(fname)[1].lower()
                fmt_map = {".csv": "csv", ".xlsx": "xlsx", ".xls": "xls",
                           ".txt": "txt", ".json": "json", ".png": "png", ".jpg": "jpg"}
                artifact = Artifact(
                    project_id=UUID(project_id), name=fname, type="dataset",
                    storage_path=storage_path, file_size=len(extracted),
                    format=fmt_map.get(ext, ext.lstrip(".")),
                )
                db.add(artifact)
                artifacts.append({"name": fname, "size": len(extracted)})
        db.commit()
    return {"message": f"Imported {len(artifacts)} files from ZIP", "files": artifacts}
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

