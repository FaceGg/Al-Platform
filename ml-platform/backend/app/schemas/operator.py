from pydantic import BaseModel

class PortSpecSchema(BaseModel):
    name: str
    type: str
    label: str

class ParamSpecSchema(BaseModel):
    name: str
    type: str
    default: str | int | float | bool | None = None
    label: str = ""
    options: list[str] | None = None
    range_min: float | None = None
    range_max: float | None = None

class OperatorSchema(BaseModel):
    id: str
    name: str
    category: str
    description: str
    version: str = "1.0"
    inputs: list[PortSpecSchema]
    outputs: list[PortSpecSchema]
    parameters: list[ParamSpecSchema]
