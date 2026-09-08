"""Windows SAPI draft voice: instant, zero-download local TTS for drafts and CI.

Positioning per calibration decisions: Kokoro stays the bundled "final" voice (experimental,
slow on this CPU); VO upload is the quality path; SAPI gives an INSTANT robotic-but-clear draft
so users can preview pacing seconds after typing a topic. Uses PowerShell + System.Speech -
present on every Windows 11 install. Parameters pass via ENV VARS to dodge nested quoting.
"""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)

_PS = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$s.SetOutputToWaveFile($env:ATME_SAPI_WAV)
$s.Rate = [int]$env:ATME_SAPI_RATE
$s.Speak($env:ATME_SAPI_TEXT)
$s.Dispose()
"""


def sapi_synthesize(text: str, out_wav: Path, rate: int = 1, timeout_s: int = 120) -> Path:
    """Synthesize one phrase to 24 kHz mono WAV. Raises RuntimeError on failure."""
    out_wav = Path(out_wav)
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    native_wav = out_wav.with_suffix(".sapi.wav")
    native_wav.unlink(missing_ok=True)

    env = dict(os.environ)
    env["ATME_SAPI_WAV"] = str(native_wav.resolve())
    env["ATME_SAPI_RATE"] = str(int(rate))
    env["ATME_SAPI_TEXT"] = text

    proc = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", _PS],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
        timeout=timeout_s, env=env)
    if proc.returncode != 0 or not native_wav.exists():
        raise RuntimeError("SAPI synthesis failed: %s" % (proc.stderr or "no output file"))
    from atme.render.animator import find_ffmpeg

    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        native_wav.unlink(missing_ok=True)
        raise RuntimeError("FFmpeg is unavailable; repair the ATME installation")
    converted = subprocess.run(
        [ffmpeg, "-y", "-hide_banner", "-v", "error", "-i", str(native_wav),
         "-ac", "1", "-ar", "24000", "-c:a", "pcm_s16le", str(out_wav)],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
        timeout=timeout_s)
    native_wav.unlink(missing_ok=True)
    if converted.returncode != 0 or not out_wav.exists():
        raise RuntimeError("SAPI audio conversion failed: %s" %
                           (converted.stderr or "no output file"))
    return out_wav


def synthesize_scenes(scenes: list[dict], segments_dir: Path, rate: int = 1) -> list[Path]:
    """One wav per scene: scene01.wav, scene02.wav... Returns paths in order."""
    seg_dir = Path(segments_dir)
    paths = []
    for i, scene in enumerate(scenes, start=1):
        p = sapi_synthesize(scene["spoken_text"], seg_dir / ("scene%02d.wav" % i), rate=rate)
        log.info("sapi: scene %02d -> %s", i, p.name)
        paths.append(p)
    return paths
