"""Materialize cached cleaned media from immutable source-timeline decisions."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf

from atme.project_media import managed_audio_path, managed_media_path
from atme.project_service import ProjectError

TARGET_RATE = 24000


def fingerprint(service, project_id, timeline):
    sources = []
    for media_id in sorted({clip["media_id"] for clip in timeline["document"]["clips"]}):
        _, metadata, _ = managed_media_path(service, project_id, media_id)
        sources.append({"media_id": media_id, "sha256": metadata["sha256"]})
    payload = {"timeline_revision": timeline["timeline_revision"], "document": timeline["document"], "sources": sources,
               "materializer": "1"}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _root(service, project_id, digest):
    parent = service.store.db_path.resolve().parent
    root = (parent / "project-timeline-cache" / str(project_id) / digest).resolve()
    if not root.is_relative_to(parent):
        raise ProjectError("storage_error", "Timeline cache escaped project storage")
    root.mkdir(parents=True, exist_ok=True)
    return root


def materialize_audio(service, project_id):
    timeline = service.source_timeline.get(project_id)
    document = timeline["document"]
    if not document["clips"]:
        raise ProjectError("narrative_recording_missing", "The source timeline contains no recording")
    digest = fingerprint(service, project_id, timeline)
    path = _root(service, project_id, digest) / "cleaned-audio.wav"
    if not path.is_file():
        total = max(1, round(document["duration_ms"] * TARGET_RATE / 1000))
        output = np.zeros(total, dtype=np.float32)
        weights = np.zeros(total, dtype=np.float32)
        for clip in document["clips"]:
            if clip["kind"] == "video" and clip.get("audio_enabled", True) is False:
                continue
            audio_path, _, _ = managed_audio_path(service, project_id, clip["media_id"])
            samples, rate = sf.read(str(audio_path), dtype="float32", always_2d=True)
            mono = np.mean(samples, axis=1, dtype=np.float32)
            if rate != TARGET_RATE:
                source_points = np.arange(len(mono), dtype=np.float64)
                target_length = round(len(mono) * TARGET_RATE / rate)
                target_points = np.arange(target_length, dtype=np.float64) * rate / TARGET_RATE
                mono = np.interp(target_points, source_points, mono).astype(np.float32)
            start = round(clip["source_start_ms"] * TARGET_RATE / 1000)
            end = round(clip["source_end_ms"] * TARGET_RATE / 1000)
            segment = mono[start:end]
            destination = round(clip["timeline_start_ms"] * TARGET_RATE / 1000)
            limit = min(total, destination + len(segment))
            segment = segment[:max(0, limit - destination)]
            if not len(segment):
                continue
            fade_ms = max(5, clip.get("crossfade_ms", 0))
            fade = min(len(segment) // 2, round(fade_ms * TARGET_RATE / 1000))
            envelope = np.ones(len(segment), dtype=np.float32)
            if fade:
                envelope[:fade] = np.linspace(0, 1, fade, endpoint=False)
                envelope[-fade:] = np.linspace(1, 0, fade, endpoint=False)
            output[destination:limit] += segment * envelope
            weights[destination:limit] += envelope
        mask = weights > 1
        output[mask] /= weights[mask]
        pending = path.with_suffix(".pending.wav")
        sf.write(str(pending), output, TARGET_RATE, subtype="PCM_16")
        os.replace(pending, path)
    metadata = {"format": "wav", "sample_rate": TARGET_RATE, "channels": 1,
                "duration_ms": document["duration_ms"], "sha256": _sha256(path),
                "timeline_revision": timeline["timeline_revision"], "timeline_fingerprint": digest}
    return path, metadata, timeline


def materialize_video(service, project_id):
    timeline = service.source_timeline.get(project_id)
    document = timeline["document"]
    clips = [clip for clip in document["clips"] if clip["kind"] == "video"]
    if not clips:
        raise ProjectError("video_unavailable", "The active source timeline is not a video sequence")
    digest = fingerprint(service, project_id, timeline)
    root = _root(service, project_id, digest)
    path = root / "cleaned-preview.mp4"
    detached_audio = any(c["kind"] == "audio" or (c["kind"] == "video" and c.get("audio_enabled", True) is False)
                         for c in document["clips"])
    if len(clips) == 1 and not detached_audio:
        clip = clips[0]
        source, metadata, _ = managed_media_path(service, project_id, clip["media_id"])
        if (clip["source_start_ms"] == 0 and clip["source_end_ms"] == metadata["duration_ms"]
                and clip["timeline_start_ms"] == 0):
            return source, metadata, timeline
    if not path.is_file():
        from atme.project_runner import PROFILE_SETTINGS
        from atme.render.animator import find_ffmpeg
        with service.store._lock:
            profile = PROFILE_SETTINGS[service._row(project_id)["profile"]]
        size = f"{profile['width']}x{profile['height']}"
        total = max(.04, document["duration_ms"] / 1000)
        command = [find_ffmpeg(), "-y", "-hide_banner", "-v", "error", "-f", "lavfi", "-t", f"{total:.3f}",
                   "-i", f"color=c=black:s={size}:r=30"]
        filters = []
        ordered = sorted(clips, key=lambda item: (item.get("track_index", 0), item["timeline_start_ms"], item["clip_id"]))
        for index, clip in enumerate(ordered, 1):
            source, _, _ = managed_media_path(service, project_id, clip["media_id"])
            duration = (clip["source_end_ms"] - clip["source_start_ms"]) / 1000
            command += ["-ss", f"{clip['source_start_ms'] / 1000:.3f}", "-t", f"{duration:.3f}", "-i", str(source)]
            offset = clip["timeline_start_ms"] / 1000
            filters.append(f"[{index}:v]scale={profile['width']}:{profile['height']}:force_original_aspect_ratio=decrease,pad={profile['width']}:{profile['height']}:(ow-iw)/2:(oh-ih)/2,setpts=PTS-STARTPTS+{offset:.3f}/TB[v{index}]")
        previous = "[0:v]"
        for index, clip in enumerate(ordered, 1):
            end = (clip["timeline_start_ms"] + clip["source_end_ms"] - clip["source_start_ms"]) / 1000
            out = "[vout]" if index == len(ordered) else f"[base{index}]"
            filters.append(f"{previous}[v{index}]overlay=eof_action=pass:enable='between(t,{clip['timeline_start_ms']/1000:.3f},{end:.3f})'{out}")
            previous = out
        audio_path, _, _ = materialize_audio(service, project_id)
        command += ["-i", str(audio_path)]
        pending = path.with_suffix(".pending.mp4")
        command += ["-filter_complex", ";".join(filters), "-map", "[vout]", "-map", f"{len(ordered)+1}:a:0",
                    "-t", f"{total:.3f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                    "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(pending)]
        result = subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, check=False)
        if result.returncode or not pending.is_file():
            pending.unlink(missing_ok=True)
            raise ProjectError("preview_failed", "Could not materialize cleaned source-video preview",
                               [{"message": result.stderr[-500:]}])
        os.replace(pending, path)
    return path, {"kind": "video", "format": "mp4", "duration_ms": document["duration_ms"],
                  "sha256": _sha256(path), "timeline_fingerprint": digest}, timeline


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
