"""Compute resource and edge device management API."""
import uuid
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.compute import ComputeNode, EdgeDevice
from app.models.user import User
from app.api.auth import get_current_user

router = APIRouter(prefix="/api/compute", tags=["compute"])


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
            {
                "id": str(n.id),
                "name": n.name,
                "node_number": n.node_number,
                "ip_address": n.ip_address,
                "node_type": n.node_type,
                "status": n.status,
                "purpose": n.purpose,
                "cpu_cores": n.cpu_cores,
                "gpu_count": n.gpu_count,
                "memory_gb": n.memory_gb,
                "disk_gb": n.disk_gb,
                "current_load": n.current_load,
                "tags": n.tags or [],
            }
            for n in nodes
        ],
        "total": len(nodes),
    }


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
    node = db.query(ComputeNode).filter(ComputeNode.id == uuid.UUID(node_id)).first()
    if not node:
        raise HTTPException(404)
    for key in ["name", "status", "purpose", "ip_address", "description", "tags"]:
        if key in data:
            setattr(node, key, data[key])
    db.commit()
    return {"status": "ok"}


@router.delete("/nodes/{node_id}")
def delete_node(node_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    node = db.query(ComputeNode).filter(ComputeNode.id == uuid.UUID(node_id)).first()
    if not node:
        raise HTTPException(404)
    db.delete(node)
    db.commit()
    return {"status": "deleted"}


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
            {
                "id": str(d.id),
                "name": d.name,
                "group_id": d.group_id,
                "ip_address": d.ip_address,
                "device_type": d.device_type,
                "status": d.status,
                "model_deployed": d.model_deployed,
                "version": d.version,
                "last_heartbeat": d.last_heartbeat.isoformat() if d.last_heartbeat else None,
            }
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
