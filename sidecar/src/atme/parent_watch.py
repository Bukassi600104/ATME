"""Terminate the sidecar if its trusted desktop supervisor disappears."""

from __future__ import annotations

import os
import threading

_started = False


def start_parent_watchdog() -> bool:
    """Start a daemon watcher when ATME_PARENT_PID is supplied by the desktop host."""
    global _started
    if _started:
        return False
    raw_pid = os.environ.get("ATME_PARENT_PID", "").strip()
    try:
        parent_pid = int(raw_pid)
    except ValueError:
        return False
    if parent_pid <= 0 or parent_pid == os.getpid():
        return False

    if os.name == "nt":
        target = lambda: _watch_windows(parent_pid)
    else:
        target = lambda: _watch_posix(parent_pid)
    _started = True
    threading.Thread(target=target, name="atme-parent-watchdog", daemon=True).start()
    return True


def _watch_windows(parent_pid: int) -> None:
    import ctypes

    synchronize = 0x0010_0000
    infinite = 0xFFFF_FFFF
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel32.WaitForSingleObject.restype = ctypes.c_uint32
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]

    handle = kernel32.OpenProcess(synchronize, False, parent_pid)
    if not handle:
        os._exit(0)
    try:
        kernel32.WaitForSingleObject(handle, infinite)
    finally:
        kernel32.CloseHandle(handle)
    os._exit(0)


def _watch_posix(parent_pid: int) -> None:
    import time

    while True:
        try:
            os.kill(parent_pid, 0)
        except ProcessLookupError:
            os._exit(0)
        except PermissionError:
            pass
        time.sleep(1)
