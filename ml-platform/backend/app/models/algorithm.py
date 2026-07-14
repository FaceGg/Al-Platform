"""Algorithm catalog model for built-in algorithm management."""
import uuid
from sqlalchemy import Column, String, Text, Float, DateTime, JSON, Boolean, func
from sqlalchemy.dialects.postgresql import UUID
from app.database import Base


class Algorithm(Base):
    __tablename__ = "algorithms"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(128), nullable=False)
    display_name = Column(String(256), default="")
    category = Column(String(64), nullable=False)  # computer_vision, ocr, speech, ml, composite
    sub_category = Column(String(64), default="")  # classification, detection, segmentation, etc.
    description = Column(Text, default="")
    framework = Column(String(64), default="")  # pytorch, tensorflow, sklearn
    backbone = Column(String(128), default="")  # resnet, yolo, mobilenet, etc.
    params_config = Column(JSON, default=dict)  # configurable parameters schema
    default_params = Column(JSON, default=dict)  # default values
    benchmark_mAP = Column(Float, default=0.0)  # benchmark performance
    benchmark_speed = Column(Float, default=0.0)  # inference speed (ms)
    tags = Column(JSON, default=list)  # search tags
    is_active = Column(Boolean, default=True)
    version = Column(String(32), default="1.0")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())
