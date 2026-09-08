"""Resource guardrails (plan M4): disk space + RAM commit-charge preflight."""

from __future__ import annotations

import ctypes
import os
import shutil
from pathlib import Path


class GuardrailError(RuntimeError):
    """Raised when the machine cannot safely take another render job."""


def _thresholds():
    return (float(os.environ.get("ATME_MIN_FREE_GB", "10")),
            float(os.environ.get("ATME_MAX_MEM_LOAD", "85")))


def disk_free_gb(path: Path) -> float:
    usage = shutil.disk_usage(str(Path(path).anchor or "."))
    return float(usage.free / (1024 ** 3))


def mem_status():
    import ctypes

    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_uint64),
            ("ullAvailPhys", ctypes.c_uint64),
            ("ullTotalPageFile", ctypes.c_uint64),
            ("ullAvailPageFile", ctypes.c_uint64),
            ("ullTotalVirtual", ctypes.c_uint64),
            ("ullAvailVirtual", ctypes.c_uint64),
            ("ullAvailExtendedVirtual", ctypes.c_uint64),
        ]

    stat = MEMORYSTATUSEX()
    stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
        return (-1, -1)
    return int(stat.dwMemoryLoad), int(stat.ullTotalPhys // (1024 ** 3))


def preflight(job_dir: Path) -> dict:
    """Raise GuardrailError when resources are insufficient; returns measured stats."""
    min_free_gb, max_mem_load = _thresholds()
    job_dir = Path(job_dir)
    job_dir.mkdir(parents=True, exist_ok=True)

    free_gb = disk_free_gb(job_dir)
    if free_gb < min_free_gb:
        raise GuardrailError(
            "disk preflight failed: %.1f GB free < %s GB minimum" % (free_gb, min_free_gb))

    load, total_gb = mem_status()
    if load >= 0 and load > max_mem_load:
        raise GuardrailError(
            "memory preflight failed: %d%% load > %s%% ceiling - close other apps" 
            % (load, max_mem_load))
    return {"free_gb": round(free_gb, 1), "mem_load": load, "ram_gb": total_gb}