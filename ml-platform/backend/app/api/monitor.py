"""
Resource monitoring API - collects CPU, memory, disk, and GPU usage data.
"""
import os
import subprocess
import shutil
import threading
import time
from pathlib import Path, PureWindowsPath
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


def resolve_nvidia_smi_executable() -> str | None:
    """Resolve NVIDIA's command on PATH and common Windows installations."""
    executable = shutil.which("nvidia-smi")
    if executable:
        return executable
    if os.name != "nt":
        return None

    candidates = [
        os.getenv("NVIDIA_SMI_PATH"),
        str(PureWindowsPath(os.getenv("ProgramW6432", r"C:\\Program Files")) / "NVIDIA Corporation" / "NVSMI" / "nvidia-smi.exe"),
        str(PureWindowsPath(os.getenv("ProgramFiles", r"C:\\Program Files")) / "NVIDIA Corporation" / "NVSMI" / "nvidia-smi.exe"),
    ]
    for candidate in candidates:
        if candidate and os.path.isfile(candidate):
            return candidate
    return None


def get_gpu_usage():
    """Get GPU usage via nvidia-smi if available."""
    executable = resolve_nvidia_smi_executable()
    if executable is None:
        return []
    try:
        result = subprocess.run(
            [
                executable,
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
                def numeric(value: str) -> float:
                    try:
                        return float(value)
                    except (TypeError, ValueError):
                        return 0.0

                gpus.append({
                    "gpu_util": numeric(parts[0]),
                    "memory_used_mb": numeric(parts[1]),
                    "memory_total_mb": numeric(parts[2]),
                    "temperature_c": numeric(parts[3]),
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
        "load": get_load_average(),
        "net": get_network_io(),
        "disk_io": get_disk_io(),
        "uptime_seconds": get_uptime_seconds(),
    }


def get_load_average() -> dict:
    """System load averages; psutil emulates them where getloadavg is absent."""
    try:
        import psutil

        load1, load5, load15 = psutil.getloadavg()
    except Exception:
        try:
            load1, load5, load15 = os.getloadavg()
        except (AttributeError, OSError):
            load1 = load5 = load15 = 0.0
    return {
        "load1": round(float(load1), 2),
        "load5": round(float(load5), 2),
        "load15": round(float(load15), 2),
        "cpu_cores": os.cpu_count() or 1,
    }


def get_network_io() -> dict:
    """Cumulative network bytes across non-loopback interfaces."""
    try:
        import psutil

        counters = psutil.net_io_counters()
        return {"rx_bytes": int(counters.bytes_recv), "tx_bytes": int(counters.bytes_sent)}
    except Exception:
        pass
    try:
        rx = tx = 0
        with open("/proc/net/dev", "r", encoding="utf-8") as handle:
            for line in handle.readlines()[2:]:
                name, _, columns = line.partition(":")
                if name.strip() == "lo":
                    continue
                fields = columns.split()
                rx += int(fields[0])
                tx += int(fields[8])
        return {"rx_bytes": rx, "tx_bytes": tx}
    except Exception:
        return {"rx_bytes": 0, "tx_bytes": 0}


def get_disk_io() -> dict:
    """Cumulative disk read/write bytes across physical devices."""
    try:
        import psutil

        counters = psutil.disk_io_counters()
        if counters is None:
            raise OSError("disk io counters unavailable")
        return {"read_bytes": int(counters.read_bytes), "write_bytes": int(counters.write_bytes)}
    except Exception:
        pass
    try:
        read = written = 0
        with open("/proc/diskstats", "r", encoding="utf-8") as handle:
            for line in handle:
                fields = line.split()
                if len(fields) < 10 or fields[2].startswith(("loop", "ram", "dm-", "sr")):
                    continue
                read += int(fields[5]) * 512
                written += int(fields[9]) * 512
        return {"read_bytes": read, "write_bytes": written}
    except Exception:
        return {"read_bytes": 0, "write_bytes": 0}


def get_uptime_seconds() -> int:
    """Seconds since the host booted."""
    try:
        import psutil

        return max(0, int(time.time() - psutil.boot_time()))
    except Exception:
        pass
    if os.name != "nt":
        try:
            with open("/proc/uptime", "r", encoding="utf-8") as handle:
                return int(float(handle.read().split()[0]))
        except Exception:
            return 0
    try:
        import ctypes

        return int(ctypes.windll.kernel32.GetTickCount64() / 1000)
    except Exception:
        return 0


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
