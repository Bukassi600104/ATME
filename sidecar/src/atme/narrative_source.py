"""Authoritative narrative-source rules shared by project and timing services."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from atme.project_service import ProjectError

RECORDING_AUTHORITY_KINDS = frozenset({"audio-only", "video-only"})


def describe(service, project_id):
    """Describe authority without confusing a derived transcript with its source."""
    with service.store._lock:
        row = service._row(project_id)
        recording_authority = row["input_kind"] in RECORDING_AUTHORITY_KINDS
        media = service.store.conn.execute(
            "SELECT m.media_id,m.revision,m.metadata FROM project_source_media m "
            "LEFT JOIN project_media_removals r ON r.job_id=m.job_id AND r.media_id=m.media_id "
            "WHERE m.job_id=? AND r.media_id IS NULL ORDER BY m.revision DESC LIMIT 1", (project_id,)).fetchone()
        try:
            script = service.artifact(project_id, "script")
        except ProjectError:
            script = None
        media_value = None
        if media is not None:
            metadata = json.loads(media["metadata"])
            media_value = {**metadata, "revision": media["revision"]}
            media_value["resource_uri"] = f"atme://projects/{project_id}/authoritative-narrative"
        expected_media_kind = "video" if row["input_kind"] in ("video-only", "script+video") else "audio"
        media_compatible = bool(media_value and media_value["kind"] == expected_media_kind)
        if row["input_kind"] in ("idea-first", "script-first") and media_value:
            media_compatible = media_value["kind"] in ("audio", "video")
        script_current_and_approved = bool(
            script and row["approved_script_revision"] == script["revision"])
        timing_ready = media_compatible and (recording_authority or script_current_and_approved)
        structure_ready = script is not None
        timeline = service.source_timeline.get(project_id)
        timing_duration = timeline["document"]["duration_ms"]
        # A declared narration source remains usable before the editor places it
        # on the timeline. Idea-first imports remain supporting media.
        if timing_duration == 0 and row["input_kind"] not in ("idea-first", "script-first") and media_value:
            timing_duration = media_value["duration_ms"]
        return {
            "mode": "recording_authority" if recording_authority else "script_authority",
            "narrative_authority": ({"type": "recording", "media": media_value}
                                    if recording_authority else
                                    {"type": "approved_external_script",
                                     "script_revision": script["revision"] if script else None}),
            "timing_authority": {"type": "cleaned_source_timeline", "media": media_value,
                                 "timeline_revision": timeline["timeline_revision"],
                                 "duration_ms": timing_duration},
            "semantic_structure": {
                "kind": "script", "revision": script["revision"] if script else None,
                "role": ("connected_ai_derivative_of_recording" if recording_authority
                         else "authoritative_external_script"),
                "required_for_render": True, "ready": structure_ready},
            "expected_media_kind": expected_media_kind,
            "media_compatible": media_compatible,
            "ready_for_timing": timing_ready,
            "ready_for_planning": timing_ready and structure_ready,
            "script_approval_required": not recording_authority,
        }


def authoritative_media_row(service, project_id):
    """Return the current compatible recording row without exposing its path."""
    source = describe(service, project_id)
    media = source["timing_authority"]["media"]
    if media is None:
        raise ProjectError("narrative_recording_missing", "An authoritative narrative recording is required")
    if not source["media_compatible"]:
        raise ProjectError("narrative_media_mismatch",
                           f"This project requires {source['expected_media_kind']} narrative media")
    with service.store._lock:
        return service.store.conn.execute(
            "SELECT media_id,revision,relative_path,metadata FROM project_source_media "
            "WHERE job_id=? AND media_id=?", (project_id, media["media_id"])).fetchone()


def read_authoritative_media(service, project_id, max_bytes=None):
    row = authoritative_media_row(service, project_id)
    metadata = json.loads(row["metadata"])
    parent = service.store.db_path.resolve().parent
    path = (parent / row["relative_path"]).resolve()
    if not path.is_relative_to(parent) or not path.is_file():
        raise ProjectError("media_unavailable", "The authoritative narrative recording is unavailable")
    if max_bytes is not None and path.stat().st_size > max_bytes:
        raise ProjectError("too_large", "Original recording is too large for one MCP resource; use authoritative audio")
    payload = Path(path).read_bytes()
    if hashlib.sha256(payload).hexdigest() != metadata["sha256"]:
        raise ProjectError("media_changed", "The authoritative narrative recording failed integrity verification")
    return payload, {**metadata, "revision": row["revision"],
                     "resource_uri": f"atme://projects/{project_id}/authoritative-narrative"}


def timing_audio(service, project_id):
    """Resolve the canonical local PCM timebase for either audio or video authority."""
    row = authoritative_media_row(service, project_id)
    timeline = service.source_timeline.get(project_id)
    if not timeline["document"]["clips"]:
        from atme.project_media import managed_audio_path
        path, metadata, _ = managed_audio_path(service, project_id, row["media_id"])
        metadata = {**metadata, "timeline_revision": timeline["timeline_revision"],
                    "timeline_fingerprint": "unplaced-authoritative-media"}
        return path, metadata, row
    from atme.timeline_media import materialize_audio
    path, metadata, _ = materialize_audio(service, project_id)
    return path, metadata, row


def read_authoritative_audio(service, project_id):
    """Read canonical audio while preserving the original recording as authority."""
    path, metadata, row = timing_audio(service, project_id)
    original = json.loads(row["metadata"])
    payload = path.read_bytes()
    return payload, {"media_id": row["media_id"], "revision": row["revision"],
                     "authority_kind": original["kind"], "format": "wav",
                     "bytes": len(payload), "sha256": metadata["sha256"],
                     "duration_ms": metadata["duration_ms"],
                     "source_timeline_revision": metadata["timeline_revision"],
                     "source_timeline_fingerprint": metadata["timeline_fingerprint"],
                     "semantic_authority": "user_recording"}


def _path_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
