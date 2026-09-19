"""Immutable local PCM WAV ingress; technical metadata only, no semantic inference."""
import hashlib
import io
import json
import os
import subprocess
import threading
import wave
from pathlib import Path
from uuid import uuid4

from atme.project_service import ProjectError

MAX_MEDIA_BYTES = 64 * 1024 * 1024
MAX_VIDEO_BYTES = 1024 * 1024 * 1024
VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm"}
_verification_lock = threading.Lock()
_verified_paths = {}


def attach_wav(service, project_id, payload, expected_revision, filename="Narration.wav"):
    if not payload or len(payload) > MAX_MEDIA_BYTES:
        raise ProjectError("too_large", "WAV must be nonempty and at most 64 MiB")
    try:
        with wave.open(io.BytesIO(payload), "rb") as recording:
            frames, rate = recording.getnframes(), recording.getframerate()
            channels, width = recording.getnchannels(), recording.getsampwidth()
            if (recording.getcomptype() != "NONE" or channels not in (1, 2)
                    or width not in (2, 3, 4) or not 8000 <= rate <= 192000
                    or not 0 < frames / rate <= 3600
                    or len(recording.readframes(frames)) != frames * channels * width):
                raise ValueError("Unsupported or truncated PCM")
    except (wave.Error, EOFError, ValueError, ZeroDivisionError) as exc:
        raise ProjectError("invalid_media", "A complete uncompressed PCM WAV recording is required") from exc
    media_id = uuid4().hex
    metadata = {"media_id": media_id, "name": Path(filename or "Narration.wav").name,
                "kind": "audio", "format": "wav", "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(), "sample_rate": rate,
                "channels": channels, "sample_width": width, "frames": frames,
                "duration_ms": round(frames * 1000 / rate), "semantic_transcript": None}
    with service.store._lock:
        conn = service.store.conn
        destination = None
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = service._row(project_id)
            service._expected(row, expected_revision)
            if conn.execute("SELECT COUNT(*) FROM project_source_media WHERE job_id=?", (project_id,)).fetchone()[0] >= 100:
                raise ProjectError("too_large", "This project already contains 100 source recordings")
            parent = service.store.db_path.resolve().parent
            directory = parent / "project-media" / str(project_id)
            if not directory.resolve().is_relative_to(parent):
                raise ProjectError("invalid_media", "Media storage must stay within the project data directory")
            directory.mkdir(parents=True, exist_ok=True)
            target = directory / (media_id + ".wav")
            with target.open("xb") as output:
                destination = target
                output.write(payload)
                output.flush()
                os.fsync(output.fileno())
            revision = row["revision"] + 1
            conn.execute("INSERT INTO project_source_media VALUES(?,?,?,?,?)",
                         (project_id, media_id, revision, str(target.relative_to(parent)), json.dumps(metadata)))
            conn.execute("UPDATE project_state SET revision=? WHERE job_id=?", (revision, project_id))
            conn.commit()
        except Exception:
            conn.rollback()
            if destination is not None:
                destination.unlink(missing_ok=True)  # Only this operation's newly created file.
            raise
        return {"project": service.open(project_id), "media": metadata}


def attach_video_file(service, project_id, staged_file, filename, expected_revision):
    staged = Path(staged_file)
    extension = Path(filename or "video.mp4").suffix.lower()
    if extension not in VIDEO_EXTENSIONS:
        raise ProjectError("invalid_media", "Video must be MP4, MOV, MKV, or WebM")
    if not staged.is_file() or not 1024 <= staged.stat().st_size <= MAX_VIDEO_BYTES:
        raise ProjectError("invalid_media", "Video must be nonempty and at most 1 GiB")
    media_id = uuid4().hex
    parent = service.store.db_path.resolve().parent
    directory = (parent / "project-media" / str(project_id)).resolve()
    if not directory.is_relative_to(parent):
        raise ProjectError("invalid_media", "Media storage must stay within project data")
    directory.mkdir(parents=True, exist_ok=True)
    decoded_pending = directory / ("." + media_id + ".timing.pending.wav")
    from atme.render.animator import find_ffmpeg
    command = [find_ffmpeg(), "-y", "-hide_banner", "-v", "error", "-i", str(staged),
               "-vn", "-ac", "1", "-ar", "24000", "-c:a", "pcm_s16le", str(decoded_pending)]
    result = subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                            text=True, check=False)
    if result.returncode != 0 or not decoded_pending.is_file():
        decoded_pending.unlink(missing_ok=True)
        raise ProjectError("invalid_media", "Video must contain a decodable audio track")
    try:
        with wave.open(str(decoded_pending), "rb") as audio:
            frames, rate = audio.getnframes(), audio.getframerate()
            if not 0 < frames / rate <= 3600:
                raise ProjectError("invalid_media", "Video narration must be at most one hour")
        original_sha = _file_sha256(staged)
        audio_sha = _file_sha256(decoded_pending)
        metadata = {"media_id": media_id, "name": Path(filename or ("Source" + extension)).name,
                    "kind": "video", "format": extension[1:],
                    "bytes": staged.stat().st_size, "sha256": original_sha,
                    "duration_ms": round(frames * 1000 / rate),
                    "timing_audio": {"format": "wav", "sha256": audio_sha,
                                     "sample_rate": rate, "channels": 1},
                    "semantic_transcript": None}
        derivative_metadata = {"sha256": audio_sha, "bytes": decoded_pending.stat().st_size,
                               "sample_rate": rate, "channels": 1,
                               "duration_ms": metadata["duration_ms"]}
        target = directory / (media_id + extension)
        audio_target = directory / (media_id + ".timing.wav")
        with service.store._lock:
            conn = service.store.conn
            try:
                conn.execute("BEGIN IMMEDIATE")
                row = service._row(project_id)
                service._expected(row, expected_revision)
                if conn.execute("SELECT COUNT(*) FROM project_source_media WHERE job_id=?",
                                (project_id,)).fetchone()[0] >= 100:
                    raise ProjectError("too_large", "This project already contains 100 source recordings")
                os.replace(staged, target)
                os.replace(decoded_pending, audio_target)
                revision = row["revision"] + 1
                conn.execute("INSERT INTO project_source_media VALUES(?,?,?,?,?)",
                             (project_id, media_id, revision, str(target.relative_to(parent)),
                              json.dumps(metadata)))
                conn.execute("INSERT INTO project_media_derivatives VALUES(?,?,?,?,?)",
                             (project_id, media_id, "timing_audio",
                              str(audio_target.relative_to(parent)), json.dumps(derivative_metadata)))
                conn.execute("UPDATE project_state SET revision=? WHERE job_id=?", (revision, project_id))
                conn.commit()
            except Exception:
                conn.rollback()
                target.unlink(missing_ok=True)
                audio_target.unlink(missing_ok=True)
                raise
        return {"project": service.open(project_id), "media": metadata}
    finally:
        decoded_pending.unlink(missing_ok=True)


def _file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def active_media_row(service, project_id, media_id):
    """Resolve one active managed source without exposing its path to adapters."""
    with service.store._lock:
        row = service.store.conn.execute(
            "SELECT m.* FROM project_source_media m LEFT JOIN project_media_removals r "
            "ON r.job_id=m.job_id AND r.media_id=m.media_id "
            "WHERE m.job_id=? AND m.media_id=? AND r.media_id IS NULL",
            (project_id, media_id)).fetchone()
    if row is None:
        raise ProjectError("not_found", "Source is not active in this project")
    return row


def managed_media_path(service, project_id, media_id):
    row = active_media_row(service, project_id, media_id)
    metadata = json.loads(row["metadata"])
    parent = service.store.db_path.resolve().parent
    path = (parent / row["relative_path"]).resolve()
    if not path.is_relative_to(parent) or not _verified_file(path, metadata["sha256"]):
        raise ProjectError("media_changed", "Managed source failed integrity verification")
    return path, metadata, row


def managed_audio_path(service, project_id, media_id):
    path, metadata, row = managed_media_path(service, project_id, media_id)
    if metadata["kind"] == "audio":
        return path, metadata, row
    with service.store._lock:
        derivative = service.store.conn.execute(
            "SELECT relative_path,metadata FROM project_media_derivatives "
            "WHERE job_id=? AND media_id=? AND kind='timing_audio'",
            (project_id, media_id)).fetchone()
    if derivative is None:
        raise ProjectError("media_unavailable", "Video audio derivative is unavailable")
    derivative_metadata = json.loads(derivative["metadata"])
    parent = service.store.db_path.resolve().parent
    audio_path = (parent / derivative["relative_path"]).resolve()
    if (not audio_path.is_relative_to(parent)
            or not _verified_file(audio_path, derivative_metadata["sha256"])):
        raise ProjectError("media_changed", "Managed video audio failed integrity verification")
    return audio_path, derivative_metadata, row


def _verified_file(path, expected_sha256):
    try:
        stat = path.stat()
    except OSError:
        return False
    key = (str(path), expected_sha256, stat.st_size, stat.st_mtime_ns)
    with _verification_lock:
        if key in _verified_paths:
            return True
    if _file_sha256(path) != expected_sha256:
        return False
    with _verification_lock:
        _verified_paths[key] = True
        if len(_verified_paths) > 2048:
            _verified_paths.pop(next(iter(_verified_paths)))
    return True
