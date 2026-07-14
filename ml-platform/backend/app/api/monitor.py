"""
Resource monitoring API - collects CPU, memory, disk, and GPU usage data.
"""
import os
import subprocess
import shutil
import threading
import time
from collections import deque
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from app.models.user import User
from app.api.auth import get_current_user

router = APIRouter(prefix="/api/monitor", tags=["monitor"])

# ──────────────────────────────────────────
#  In-memory history buffer
# ──────────────────────────────────────────

MAX_RECORDS = 120
history = deque(maxlen=MAX_RECORDS)
_history_lock = threading.Lock()


# ──────────────────────────────────────────
#  Metric collectors
# ──────────────────────────────────────────

def get_cpu_usage():
    """Get CPU usage percentage via wmic on Windows."""
    try:
        result = subprocess.run(
            ["wmic", "cpu", "get", "loadpercentage"],
            capture_output=True, text=True, timeout=5,
        )
        lines = [l.strip() for l in result.stdout.strip().splitlines() if l.strip()]
        # Skip header line, get first number
        for line in lines:
            if line.replace(".", "").isdigit():
                return float(line)
        return 0.0
    except Exception:
        return 0.0


def get_memory_usage():
    """Get memory usage via wmic on Windows."""
    try:
        result = subprocess.run(
            ["wmic", "OS", "get", "TotalVisibleMemorySize,FreePhysicalMemory"],
            capture_output=True, text=True, timeout=5,
        )
        lines = [l.strip() for l in result.stdout.strip().splitlines() if l.strip()]
        if len(lines) >= 2:
            parts = lines[1].split()
            if len(parts) >= 2:
                total_kb = float(parts[0])
                free_kb = float(parts[1])
                used_kb = total_kb - free_kb
                return {
                    "total_bytes": int(total_kb * 1024),
                    "used_bytes": int(used_kb * 1024),
                    "free_bytes": int(free_kb * 1024),
                    "percent": round(used_kb / total_kb * 100, 1),
                }
        return {"total_bytes": 0, "used_bytes": 0, "free_bytes": 0, "percent": 0.0}
    except Exception:
        return {"total_bytes": 0, "used_bytes": 0, "free_bytes": 0, "percent": 0.0}


def get_disk_usage():
    """Get disk usage for the root partition."""
    try:
        usage = shutil.disk_usage("/")
        return {
            "total": usage.total,
            "used": usage.used,
            "free": usage.free,
            "percent": round(usage.used / usage.total * 100, 1),
        }
    except Exception:
        return {"total": 0, "used": 0, "free": 0, "percent": 0.0}


def get_gpu_usage():
    """Get GPU usage via nvidia-smi if available."""
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            return []
        gpus = []
        for line in result.stdout.strip().splitlines():
            if not line.strip():
                continue
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 4:
                gpus.append({
                    "gpu_util": float(parts[0]),
                    "memory_used_mb": float(parts[1]),
                    "memory_total_mb": float(parts[2]),
                    "temperature_c": float(parts[3]),
                })
            else:
                gpus.append({
                    "gpu_util": 0.0,
                    "memory_used_mb": 0.0,
                    "memory_total_mb": 0.0,
                    "temperature_c": 0.0,
                })
        return gpus
    except Exception:
        return []


def collect_metrics():
    """Collect all system metrics and return a snapshot dict."""
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "cpu": {"percent": get_cpu_usage()},
        "memory": get_memory_usage(),
        "disk": get_disk_usage(),
        "gpu": get_gpu_usage(),
    }


# ──────────────────────────────────────────
#  Background collector thread
# ──────────────────────────────────────────

_COLLECTOR_RUNNING = True


def _background_collect():
    """Collect metrics every 5 seconds and store in memory history."""
    global _COLLECTOR_RUNNING
    while _COLLECTOR_RUNNING:
        try:
            snapshot = collect_metrics()
            with _history_lock:
                history.append(snapshot)
        except Exception:
            pass
        time.sleep(5)


_collector_thread = threading.Thread(target=_background_collect, daemon=True)
_collector_thread.start()


# ──────────────────────────────────────────
#  API Endpoints
# ──────────────────────────────────────────

@router.get("/current")
def get_current_metrics(
    current_user: User = Depends(get_current_user),
):
    """Return current system resource usage."""
    return collect_metrics()


@router.get("/history")
def get_history_metrics(
    limit: int = Query(default=60, ge=1, le=MAX_RECORDS),
    current_user: User = Depends(get_current_user),
):
    """Return recent N metric records from the in-memory buffer."""
    with _history_lock:
        items = list(history)[-limit:]
    return items
