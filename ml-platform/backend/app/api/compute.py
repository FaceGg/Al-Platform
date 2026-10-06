"""Compute resource and edge device management API."""
import os
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.compute import ComputeNode, EdgeDevice
from app.models.user import User
from app.api.auth import get_current_user
from app.services.resource_access import ResourceAccessService

router = APIRouter(prefix="/api/compute", tags=["compute"])

# A node/device whose last reported heartbeat is older than this is surfaced
# as heartbeat_stale so the UI can flag manually registered entries.
HEARTBEAT_STALE_SECONDS = max(30, int(os.getenv("COMPUTE_HEARTBEAT_STALE_SECONDS", "180")))


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _heartbeat_stale(last_heartbeat: datetime | None) -> bool:
    if last_heartbeat is None:
        return True
    seen = last_heartbeat if last_heartbeat.tzinfo is None else last_heartbeat.replace(tzinfo=None)
    return (_utcnow() - seen).total_seconds() > HEARTBEAT_STALE_SECONDS


def _node_response(node: ComputeNode) -> dict:
    return {
        "id": str(node.id),
        "name": node.name,
        "node_number": node.node_number,
        "ip_address": node.ip_address,
        "node_type": node.node_type,
        "status": node.status,
        "purpose": node.purpose,
        "cpu_cores": node.cpu_cores,
        "gpu_count": node.gpu_count,
        "memory_gb": node.memory_gb,
        "disk_gb": node.disk_gb,
        "current_load": node.current_load,
        "tags": node.tags or [],
        "last_heartbeat": node.last_heartbeat.isoformat() if node.last_heartbeat else None,
        "heartbeat_stale": _heartbeat_stale(node.last_heartbeat),
    }


def _device_response(device: EdgeDevice) -> dict:
    return {
        "id": str(device.id),
        "name": device.name,
        "group_id": device.group_id,
        "ip_address": device.ip_address,
        "device_type": device.device_type,
        "status": device.status,
        "model_deployed": device.model_deployed,
        "version": device.version,
        "last_heartbeat": (
            device.last_heartbeat.isoformat() if device.last_heartbeat else None
        ),
        "heartbeat_stale": _heartbeat_stale(device.last_heartbeat),
    }


# ---- Compute Nodes ----
@router.get("/nodes")
def list_nodes(
    status: str = Query(None),
    purpose: str = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = db.query(ComputeNode).filter(ComputeNode.owner_id == current_user.id)
    if status:
        q = q.filter(ComputeNode.status == status)
    if purpose:
        q = q.filter(ComputeNode.purpose == purpose)
    nodes = q.all()
    return {
        "items": [
            _node_response(n)
            for n in nodes
        ],
        "total": len(nodes),
    }


@router.get("/nodes/{node_id}")
def get_node(
    node_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    node = ResourceAccessService().require_owned(
        db,
        ComputeNode,
        node_id,
        current_user.id,
    )
    return _node_response(node)


@router.post("/nodes")
def create_node(data: dict, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    node = ComputeNode(
        name=data["name"],
        node_number=data.get("node_number", str(uuid.uuid4())[:8]),
        ip_address=data.get("ip_address", ""),
        node_type=data.get("node_type", "gpu"),
        purpose=data.get("purpose", "training"),
        cpu_cores=data.get("cpu_cores", 0),
        gpu_count=data.get("gpu_count", 0),
        memory_gb=data.get("memory_gb", 0),
        disk_gb=data.get("disk_gb", 0),
        owner_id=current_user.id,
        description=data.get("description", ""),
        tags=data.get("tags", []),
    )
    db.add(node)
    db.commit()
    db.refresh(node)
    return {"id": str(node.id), "name": node.name}


@router.put("/nodes/{node_id}")
def update_node(node_id: str, data: dict, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    node = ResourceAccessService().require_owned(
        db,
        ComputeNode,
        node_id,
        current_user.id,
    )
    for key in ["name", "status", "purpose", "ip_address", "description", "tags"]:
        if key in data:
            setattr(node, key, data[key])
    db.commit()
    return {"status": "ok"}


@router.delete("/nodes/{node_id}")
def delete_node(node_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    node = ResourceAccessService().require_owned(
        db,
        ComputeNode,
        node_id,
        current_user.id,
    )
    db.delete(node)
    db.commit()
    return {"status": "deleted"}


@router.post("/nodes/{node_id}/heartbeat")
def node_heartbeat(node_id: str, data: dict, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Report node liveness; node agents call this to keep status/load current."""
    node = ResourceAccessService().require_owned(
        db,
        ComputeNode,
        node_id,
        current_user.id,
    )
    node.last_heartbeat = _utcnow()
    if "status" in data and data["status"]:
        node.status = str(data["status"])
    if "current_load" in data and data["current_load"] is not None:
        try:
            node.current_load = max(0.0, min(100.0, float(data["current_load"])))
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail="current_load must be a number")
    db.commit()
    db.refresh(node)
    return _node_response(node)


# ---- Edge Devices ----
@router.get("/devices")
def list_devices(
    group_id: str = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = db.query(EdgeDevice).filter(EdgeDevice.owner_id == current_user.id)
    if group_id:
        q = q.filter(EdgeDevice.group_id == group_id)
    devices = q.all()
    return {
        "items": [
            _device_response(d)
            for d in devices
        ],
        "total": len(devices),
    }


@router.post("/devices")
def create_device(data: dict, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    device = EdgeDevice(
        name=data["name"],
        group_id=data.get("group_id", "default"),
        ip_address=data.get("ip_address", ""),
        device_type=data.get("device_type", "box"),
        owner_id=current_user.id,
        description=data.get("description", ""),
        config=data.get("config", {}),
    )
    db.add(device)
    db.commit()
    db.refresh(device)
    return {"id": str(device.id), "name": device.name}


@router.get("/devices/{device_id}")
def get_device(
    device_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    device = ResourceAccessService().require_owned(
        db,
        EdgeDevice,
        device_id,
        current_user.id,
    )
    return _device_response(device)


@router.put("/devices/{device_id}")
def update_device(
    device_id: str,
    data: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    device = ResourceAccessService().require_owned(
        db,
        EdgeDevice,
        device_id,
        current_user.id,
    )
    for key in ["name", "group_id", "ip_address", "device_type", "status", "description", "config"]:
        if key in data:
            setattr(device, key, data[key])
    db.commit()
    return {"status": "ok"}


@router.delete("/devices/{device_id}")
def delete_device(
    device_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    device = ResourceAccessService().require_owned(
        db,
        EdgeDevice,
        device_id,
        current_user.id,
    )
    db.delete(device)
    db.commit()
    return {"status": "deleted"}


@router.post("/devices/{device_id}/heartbeat")
def device_heartbeat(
    device_id: str,
    data: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Report device liveness; edge agents also report what they currently run."""
    device = ResourceAccessService().require_owned(
        db,
        EdgeDevice,
        device_id,
        current_user.id,
    )
    device.last_heartbeat = _utcnow()
    if "status" in data and data["status"]:
        device.status = str(data["status"])
    if "model_deployed" in data and data["model_deployed"] is not None:
        device.model_deployed = str(data["model_deployed"])
    if "version" in data and data["version"] is not None:
        device.version = str(data["version"])
    db.commit()
    db.refresh(device)
    return _device_response(device)
