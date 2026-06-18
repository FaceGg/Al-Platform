from app.engine.base_operator import BaseOperator, PortSpec, ParamSpec
from app.engine.registry import OperatorRegistry
from app.schemas.operator import OperatorSchema, PortSpecSchema, ParamSpecSchema
from fastapi import APIRouter

router = APIRouter(prefix="/api", tags=["operators"])


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
            ) for p in op.parameters],
        ))
    return result
