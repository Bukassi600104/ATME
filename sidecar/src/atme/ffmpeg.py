"""Resolve the same FFmpeg binary for source runs and Windows packaging."""

import os
import re
import shutil
import sys
from pathlib import Path


def _binary(path: str | Path) -> str:
    executable = Path(path)
    shim = executable.with_suffix(".shim")
    if shim.is_file():
        # A Scoop launcher needs its adjacent .shim file and cannot be shipped alone.
        match = re.fullmatch(r'path\s*=\s*"([^"\r\n]+)"', shim.read_text(encoding="utf-8-sig").strip())
        if not match or not Path(match[1]).is_absolute() or not Path(match[1]).is_file():
            raise ValueError("FFmpeg launcher has no standalone target; set ATME_FFMPEG to the real executable")
        executable = Path(match[1])
    return str(executable.resolve())


def find_ffmpeg() -> str | None:
    override = os.environ.get("ATME_FFMPEG")
    if override:
        return _binary(shutil.which(override) or override)
    if getattr(sys, "frozen", False):
        directory = Path(sys.executable).parent
        for relative in ("_internal/ffmpeg/ffmpeg.exe", "ffmpeg/ffmpeg.exe", "ffmpeg.exe"):
            candidate = directory / relative
            if candidate.is_file():
                return _binary(candidate)
    command = shutil.which("ffmpeg")
    if command:
        return _binary(command)
    local = os.environ.get("LOCALAPPDATA")
    if local:
        for package in sorted(Path(local).glob("Microsoft/WinGet/Packages/Gyan.FFmpeg*")):
            candidate = next(package.rglob("ffmpeg.exe"), None)
            if candidate:
                return _binary(candidate)
    return None
