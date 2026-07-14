"""Compute resource and edge device management models."""
import uuid
from sqlalchemy import Column, String, Text, Integer, Float, DateTime, JSON, Boolean, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from app.database import Base


class ComputeNode(Base):
    __tablename__ = "compute_nodes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(128), nullable=False)
    node_number = Column(String(64), unique=True)
    ip_address = Column(String(64), default="")
    node_type = Column(String(32), default="gpu")  # cpu, gpu
    status = Column(String(16), default="online")  # online, offline, busy
    purpose = Column(String(32), default="training")  # training, inference, hybrid
    cpu_cores = Column(Integer, default=0)
    gpu_count = Column(Integer, default=0)
    memory_gb = Column(Float, default=0.0)
    disk_gb = Column(Float, default=0.0)
    current_load = Column(Float, default=0.0)  # percentage
    owner_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    description = Column(Text, default="")
    tags = Column(JSON, default=list)
    created_at = Column(DateTime, server_default=func.now())


class EdgeDevice(Base):
    __tablename__ = "edge_devices"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(128), nullable=False)
    group_id = Column(String(64), default="default")
    ip_address = Column(String(64), default="")
    device_type = Column(String(64), default="box")
    status = Column(String(16), default="online")
    model_deployed = Column(String(256), default="")
    version = Column(String(32), default="")
    last_heartbeat = Column(DateTime)
    owner_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    description = Column(Text, default="")
    config = Column(JSON, default=dict)
    created_at = Column(DateTime, server_default=func.now())
