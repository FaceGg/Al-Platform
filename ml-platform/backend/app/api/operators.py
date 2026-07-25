from app.engine.base_operator import BaseOperator, PortSpec, ParamSpec
from app.engine.registry import OperatorRegistry
from app.schemas.operator import OperatorSchema, PortSpecSchema, ParamSpecSchema
from fastapi import APIRouter, UploadFile, File, Depends
from app.api.auth import get_current_user
from app.models.user import User
import os
import shutil

router = APIRouter(prefix="/api", tags=["operators"])

UPLOAD_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "uploads"))
os.makedirs(UPLOAD_DIR, exist_ok=True)


@router.get("/operators")
def list_operators():
    operators = OperatorRegistry.list_all()
    result = []
    for op in operators:
        result.append(OperatorSchema(
            id=op.id,
            name=op.name,
            category=op.category,
            description=op.description,
            version=op.version,
            inputs=[PortSpecSchema(name=p.name, type=p.type, label=p.label) for p in op.inputs],
            outputs=[PortSpecSchema(name=p.name, type=p.type, label=p.label) for p in op.outputs],
            parameters=[ParamSpecSchema(
                name=p.name,
                type=p.type,
                default=p.default,
                label=p.label,
                options=p.options,
                range_min=p.range_min,
                range_max=p.range_max,
                required=p.required,
                required_when=p.required_when,
            ) for p in op.parameters],
        ))
    return result


@router.post("/upload")
def upload_file(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    """Upload a file for use in workflow operators."""
    safe_name = file.filename.replace("\\", "_").replace("/", "_")
    dest = os.path.join(UPLOAD_DIR, safe_name)
    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)
    return {"file_path": os.path.abspath(dest), "filename": safe_name, "message": "Upload successful"}
