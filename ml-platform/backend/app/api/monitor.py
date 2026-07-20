"""
Resource monitoring API - collects CPU, memory, disk, and GPU usage data.
"""
import os
import subprocess
import shutil
import threading
import time
from pathlib import Path
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
    """Return CPU usage without depending on the removed Windows WMIC tool."""
    if os.name == "nt":
        try:
            import ctypes

            class FILETIME(ctypes.Structure):
                _fields_ = [("dwLowDateTime", ctypes.c_ulong), ("dwHighDateTime", ctypes.c_ulong)]

            idle, kernel, user = FILETIME(), FILETIME(), FILETIME()
            if ctypes.windll.kernel32.GetSystemTimes(
                ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user),
            ):
                def value(filetime):
                    return (filetime.dwHighDateTime << 32) + filetime.dwLowDateTime

                first = (value(idle), value(kernel), value(user))
                time.sleep(0.1)
                if ctypes.windll.kernel32.GetSystemTimes(
                    ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user),
                ):
                    second = (value(idle), value(kernel), value(user))
                    total = (second[1] - first[1]) + (second[2] - first[2])
                    idle_delta = second[0] - first[0]
                    if total > 0:
                        return round(max(0.0, min(100.0, (total - idle_delta) * 100 / total)), 1)
        except Exception:
            pass
    try:
        load_1, _, _ = os.getloadavg()
        return round(max(0.0, min(100.0, load_1 * 100 / max(1, os.cpu_count() or 1))), 1)
    except Exception:
        return 0.0


def get_memory_usage():
    """Return memory usage without depending on the removed Windows WMIC tool."""
    if os.name == "nt":
        try:
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            state = MEMORYSTATUSEX()
            state.dwLength = ctypes.sizeof(state)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(state)):
                total = int(state.ullTotalPhys)
                free = int(state.ullAvailPhys)
                used = total - free
                return {"total_bytes": total, "used_bytes": used, "free_bytes": free,
                        "percent": round(used * 100 / total, 1) if total else 0.0}
        except Exception:
            pass
    try:
        page_size = os.sysconf("SC_PAGE_SIZE")
        total = int(page_size * os.sysconf("SC_PHYS_PAGES"))
        available_pages = os.sysconf("SC_AVPHYS_PAGES")
        free = int(page_size * available_pages)
        used = total - free
        return {"total_bytes": total, "used_bytes": used, "free_bytes": free,
                "percent": round(used * 100 / total, 1) if total else 0.0}
    except Exception:
        return {"total_bytes": 0, "used_bytes": 0, "free_bytes": 0, "percent": 0.0}


def get_disk_usage():
    """Get disk usage for the root partition."""
    try:
        root = Path.cwd().anchor or "/"
        usage = shutil.disk_usage(root)
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
