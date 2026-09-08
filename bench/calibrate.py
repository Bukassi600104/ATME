"""ATME M0 calibration harness.

Measures what THIS machine can actually do and appends a timestamped run to docs/CALIBRATION.md.
Kill-switch gates from the plan:
  - Kokoro RTF > 3.0  -> pivot to VO-upload-first defaults
  - render < 4 fps @ 720p30 -> pivot to 720p24 (checked in M1 when the animator exists)

Today this measures FFmpeg encode throughput (the assembly floor). ML benches activate as their
optional extras get installed; until then they are reported as SKIPPED so nothing silently passes.

Usage:
    python bench/calibrate.py [--seconds N]
"""

from __future__ import annotations

import argparse
import ctypes
import datetime as dt
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DOC = REPO / "docs" / "CALIBRATION.md"

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

def system_line() -> str:
    ram = "?"
    try:
        stat = MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
            ram = str(round(stat.ullTotalPhys / (1024 ** 3))) + "GB (" + str(stat.dwMemoryLoad) + "% load)"
    except Exception:
        pass
    return platform.machine() + " | " + str(os.cpu_count()) + " threads | RAM " + ram + " | " + platform.release()

def find_ffmpeg() -> str | None:
    exe = os.environ.get("ATME_FFMPEG") or shutil.which("ffmpeg")
    if exe:
        return exe
    root = os.environ.get("LOCALAPPDATA", "")
    if root:
        for candidate in sorted(Path(root).glob("Microsoft/WinGet/Packages/Gyan.FFmpeg*")):
            hits = list(candidate.rglob("bin/ffmpeg.exe")) or list(candidate.rglob("ffmpeg.exe"))
            if hits:
                return str(hits[0])
    return None

def encode_fps(ffmpeg: str, width: int, height: int, fps: int, seconds: int) -> float | None:
    cmd = [
        ffmpeg, "-hide_banner", "-v", "error",
        "-f", "lavfi", "-i", "testsrc2=size=%dx%d:rate=%d" % (width, height, fps),
        "-t", str(seconds),
        "-c:v", "libx264", "-preset", "fast", "-crf", "21",
        "-f", "null", "-",
    ]
    start = time.perf_counter()
    proc = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    elapsed = time.perf_counter() - start
    if proc.returncode != 0:
        print("ffmpeg failed: " + proc.stderr[:400], file=sys.stderr)
        return None
    return round((seconds * fps) / elapsed, 1)

def ml_bench_status() -> dict:
    out = {}
    for label, module in [
        ("Kokoro TTS", "kokoro"),
        ("onnxruntime", "onnxruntime"),
        ("faster-whisper", "faster_whisper"),
        ("cairosvg", "cairosvg"),
        ("noisereduce", "noisereduce"),
        ("pedalboard", "pedalboard"),
    ]:
        try:
            __import__(module)
            out[label] = "installed (bench lands with its milestone)"
        except Exception:
            out[label] = "SKIPPED - extra not installed"
    return out

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=int, default=10)
    args = parser.parse_args()

    ffmpeg = find_ffmpeg()
    print("ffmpeg: " + (ffmpeg or "NOT FOUND"))
    print("system: " + system_line())
    if not ffmpeg:
        return 2

    enc720 = encode_fps(ffmpeg, 1280, 720, 30, args.seconds)
    enc1080 = encode_fps(ffmpeg, 1920, 1080, 30, args.seconds)

    stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    note720 = "floor >= 60 fps: " + ("PASS" if (enc720 or 0) >= 60 else "BELOW floor")
    lines = [
        "",
        "## Run " + stamp,
        "",
        "- ffmpeg: " + str(ffmpeg),
        "- system: " + system_line(),
        "",
        "| Metric | Result | Note |",
        "|---|---|---|",
        "| libx264 encode 720p30 fast CRF21 | " + str(enc720) + " fps | " + note720 + " |",
        "| libx264 encode 1080p30 fast CRF21 | " + str(enc1080) + " fps | floor >= 20 fps |",
    ]
    for label, status in ml_bench_status().items():
        lines.append("| " + label + " | - | " + status + " |")

    DOC.parent.mkdir(parents=True, exist_ok=True)
    with DOC.open("a", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")

    print("\n".join(lines))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
