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
from app.services.artifact_service import ArtifactAccessError, build_artifact_service

router = APIRouter(prefix="/api", tags=["datasets"])

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)


def _store_uploaded_dataset(db: Session, project_id, file: UploadFile) -> Artifact:
    safe_name = Path(file.filename or "uploaded_file").name
    staging_path = Path(UPLOAD_DIR) / f"{uuid.uuid4()}_{safe_name}"
    staging_path.write_bytes(file.file.read())
    try:
        return _create_dataset_artifact(
            build_artifact_service(db), project_id, staging_path, safe_name,
        )
    finally:
        staging_path.unlink(missing_ok=True)


def _create_dataset_artifact(service, project_id, source: Path, name: str) -> Artifact:
    if source.suffix.lower() in {".csv", ".xls", ".xlsx"}:
        return service.create_dataset(project_id, source, name)
    return service.create_from_file(
        project_id,
        source,
        name,
        "dataset",
        metadata={"source": "upload"},
    )


def _read_dataset(path: Path):
    import pandas as pd

    if path.suffix.lower() in {".xls", ".xlsx"}:
        return pd.read_excel(path)
    return pd.read_csv(path)


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
        "name": artifact.name,
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
    artifact_service = build_artifact_service(db)
    all_dfs = []
    for artifact in artifacts:
        try:
            with artifact_service.materialize(
                artifact.id, artifact.project_id, expected_type="dataset",
            ) as path:
                all_dfs.append(_read_dataset(path))
        except (ArtifactAccessError, OSError, ValueError):
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
    artifact = db.query(Artifact).join(Project).filter(
        Artifact.id == UUID(dataset_id),
        Artifact.type == "dataset",
        Project.owner_id == current_user.id,
    ).first()
    if not artifact:
        raise HTTPException(404, "Dataset not found")

    try:
        with build_artifact_service(db).materialize(
            artifact.id, artifact.project_id, expected_type="dataset",
        ) as path:
            df = _read_dataset(path)
    except ArtifactAccessError as e:
        raise HTTPException(404, str(e)) from e
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
    artifact_service = build_artifact_service(db)
    for file in files:
        content = await file.read()
        safe_name = Path(file.filename or "uploaded_file").name
        staging_path = Path(UPLOAD_DIR) / f"{uuid.uuid4()}_{safe_name}"
        staging_path.write_bytes(content)
        ext = staging_path.suffix.lower()
        fmt_map = {".csv": "csv", ".xlsx": "xlsx", ".xls": "xls", ".txt": "txt",
                   ".json": "json", ".png": "png", ".jpg": "jpg"}
        try:
            artifact = _create_dataset_artifact(
                artifact_service, UUID(project_id), staging_path, safe_name,
            )
        finally:
            staging_path.unlink(missing_ok=True)
        artifacts.append({
            "artifact_id": str(artifact.id),
            "name": safe_name,
            "size": len(content),
            "format": fmt_map.get(ext, ""),
        })
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
    artifact_service = build_artifact_service(db)
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
                staging_path = Path(tmpdir) / f"{uuid.uuid4()}_{fname}"
                staging_path.write_bytes(extracted)
                ext = os.path.splitext(fname)[1].lower()
                artifact = _create_dataset_artifact(
                    artifact_service, UUID(project_id), staging_path, fname,
                )
                artifacts.append({
                    "artifact_id": str(artifact.id),
                    "name": fname,
                    "size": len(extracted),
                })
    return {"message": f"Imported {len(artifacts)} files from ZIP", "files": artifacts}
@router.get("/datasets/{dataset_id}/preview")
def preview_dataset(
    dataset_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    artifact = db.query(Artifact).join(Project).filter(
        Artifact.id == UUID(dataset_id),
        Artifact.type == "dataset",
        Project.owner_id == current_user.id,
    ).first()
    if not artifact:
        raise HTTPException(404, "Dataset not found")

    try:
        with build_artifact_service(db).materialize(
            artifact.id, artifact.project_id, expected_type="dataset",
        ) as path:
            df = _read_dataset(path)
        return {
            "columns": list(df.columns),
            "preview": df.head(10).to_dict(orient="records"),
            "total_rows": len(df),
            "dtypes": {str(k): str(v) for k, v in df.dtypes.items()},
        }
    except ArtifactAccessError as e:
        raise HTTPException(404, str(e)) from e
    except Exception as e:
        raise HTTPException(400, f"Failed to read file: {e}")

