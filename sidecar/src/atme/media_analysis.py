"""Deterministic waveform, silence and thumbnail evidence for managed media."""
from __future__ import annotations

import json
import math
import os
import subprocess

import numpy as np
import soundfile as sf

from atme.project_media import managed_audio_path, managed_media_path
from atme.project_service import ProjectError

ANALYSIS_VERSION = "1"
LEVELS_MS = (10, 40, 160, 640)
SILENCE_THRESHOLD_DBFS = -42.0
SILENCE_MIN_MS = 700


def _cache_root(service, project_id, media_id, sha256):
    parent = service.store.db_path.resolve().parent
    root = (parent / "project-media-cache" / str(project_id) / media_id / sha256[:16]).resolve()
    if not root.is_relative_to(parent):
        raise ProjectError("storage_error", "Media cache escaped project storage")
    root.mkdir(parents=True, exist_ok=True)
    return root


def _atomic_json(path, value):
    pending = path.with_suffix(path.suffix + ".pending")
    pending.write_text(json.dumps(value, separators=(",", ":")), encoding="utf-8")
    os.replace(pending, path)


def waveform(service, project_id, media_id, resolution_ms):
    if type(resolution_ms) is not int:
        raise ProjectError("invalid_request", "Waveform resolution must be an integer")
    level = min(LEVELS_MS, key=lambda value: abs(value - resolution_ms))
    audio_path, audio_metadata, _ = managed_audio_path(service, project_id, media_id)
    root = _cache_root(service, project_id, media_id, audio_metadata["sha256"])
    path = root / f"waveform-v{ANALYSIS_VERSION}-{level}.json"
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    samples, rate = sf.read(str(audio_path), dtype="float32", always_2d=True)
    mono = np.mean(samples, axis=1, dtype=np.float32)
    frame = max(1, round(rate * level / 1000))
    count = math.ceil(len(mono) / frame)
    padded = np.pad(mono, (0, count * frame - len(mono))) if count else mono
    blocks = padded.reshape(count, frame) if count else np.empty((0, frame), dtype=np.float32)
    minimum = blocks.min(axis=1) if count else np.array([], dtype=np.float32)
    maximum = blocks.max(axis=1) if count else np.array([], dtype=np.float32)
    rms = np.sqrt(np.mean(blocks * blocks, axis=1)) if count else np.array([], dtype=np.float32)
    result = {"contract_version": "1", "analysis_version": ANALYSIS_VERSION,
              "media_id": media_id, "resolution_ms": level,
              "duration_ms": round(len(mono) * 1000 / rate),
              "peaks": [[round(float(lo), 4), round(float(hi), 4), round(float(power), 4)]
                        for lo, hi, power in zip(minimum, maximum, rms)],
              "silences": _silences(mono, rate)}
    _atomic_json(path, result)
    return result


def _silences(samples, rate):
    frame_ms = 20
    frame = max(1, round(rate * frame_ms / 1000))
    count = len(samples) // frame
    if not count:
        return []
    blocks = samples[:count * frame].reshape(count, frame)
    dbfs = 20 * np.log10(np.sqrt(np.mean(blocks * blocks, axis=1)) + 1e-9)
    quiet = dbfs < SILENCE_THRESHOLD_DBFS
    spans = []
    start = None
    for index, value in enumerate(np.append(quiet, False)):
        if value and start is None:
            start = index
        elif not value and start is not None:
            duration = (index - start) * frame_ms
            if duration >= SILENCE_MIN_MS:
                spans.append({"start_ms": start * frame_ms, "end_ms": index * frame_ms,
                              "duration_ms": duration, "kind": "likely_silence"})
            start = None
    return spans


def thumbnail(service, project_id, media_id, at_ms, width):
    if type(at_ms) is not int or at_ms < 0:
        raise ProjectError("invalid_request", "Thumbnail time must be nonnegative")
    widths = (96, 160, 240)
    target_width = min(widths, key=lambda value: abs(value - int(width or 160)))
    source, metadata, _ = managed_media_path(service, project_id, media_id)
    if metadata["kind"] != "video" or at_ms >= metadata["duration_ms"]:
        raise ProjectError("invalid_request", "Thumbnail must reference a time inside a video source")
    quantized = min(metadata["duration_ms"] - 1, max(0, round(at_ms / 250) * 250))
    root = _cache_root(service, project_id, media_id, metadata["sha256"])
    path = root / f"thumb-v1-{target_width}-{quantized}.jpg"
    if not path.is_file():
        pending = path.with_suffix(".pending.jpg")
        from atme.render.animator import find_ffmpeg
        command = [find_ffmpeg(), "-y", "-hide_banner", "-v", "error", "-ss", f"{quantized / 1000:.3f}",
                   "-i", str(source), "-frames:v", "1", "-vf", f"scale={target_width}:-2", "-q:v", "4", str(pending)]
        result = subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, check=False)
        if result.returncode or not pending.is_file():
            pending.unlink(missing_ok=True)
            raise ProjectError("thumbnail_failed", "Could not extract source-video thumbnail")
        os.replace(pending, path)
    return path
