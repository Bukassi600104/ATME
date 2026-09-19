"""Immutable, non-destructive source-cleanup timeline.

Timeline clips reference immutable managed recordings. Editing writes a new timeline
snapshot; it never rewrites or removes source bytes. A video clip is one logical A/V
item, so every timing operation inherently preserves synchronization.
"""
from __future__ import annotations

import json
import time
from copy import deepcopy
from uuid import uuid4

from jsonschema import Draft202012Validator

from atme.project_service import ProjectError
from atme.resources import resource_path


class SourceTimeline:
    def __init__(self, service):
        self.service = service
        with service.store._lock:
            service.store.conn.executescript("""
                CREATE TABLE IF NOT EXISTS project_source_timeline_versions (
                    job_id INTEGER NOT NULL REFERENCES jobs(id),
                    timeline_revision INTEGER NOT NULL,
                    project_revision INTEGER NOT NULL,
                    document TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    PRIMARY KEY(job_id,timeline_revision));
                CREATE TABLE IF NOT EXISTS project_source_timeline_state (
                    job_id INTEGER PRIMARY KEY REFERENCES jobs(id),
                    current_timeline_revision INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS project_source_timeline_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id INTEGER NOT NULL REFERENCES jobs(id),
                    operation TEXT NOT NULL,
                    before_document TEXT NOT NULL,
                    after_document TEXT NOT NULL,
                    applied_timeline_revision INTEGER NOT NULL,
                    undone INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS project_media_removals (
                    job_id INTEGER NOT NULL REFERENCES jobs(id),
                    media_id TEXT NOT NULL,
                    project_revision INTEGER NOT NULL,
                    created_at REAL NOT NULL,
                    PRIMARY KEY(job_id,media_id));
                CREATE TABLE IF NOT EXISTS project_timeline_dependencies (
                    job_id INTEGER NOT NULL,
                    kind TEXT NOT NULL,
                    artifact_revision INTEGER NOT NULL,
                    timeline_revision INTEGER NOT NULL,
                    PRIMARY KEY(job_id,kind,artifact_revision));
                INSERT OR IGNORE INTO project_timeline_dependencies(job_id,kind,artifact_revision,timeline_revision)
                    SELECT job_id,kind,revision,0 FROM project_artifact_versions
                    WHERE kind IN ('storyboard','layout');
            """)
            service.store.conn.commit()
        self._schema = json.loads(resource_path("schemas", "source-timeline.schema.json").read_text(encoding="utf-8"))

    @staticmethod
    def _duration(clip):
        return clip["source_end_ms"] - clip["source_start_ms"]

    @classmethod
    def _normalize(cls, document):
        doc = deepcopy(document)
        doc["clips"] = sorted(doc.get("clips", []), key=lambda item: (item["timeline_start_ms"], item["clip_id"]))
        doc["duration_ms"] = max((c["timeline_start_ms"] + cls._duration(c) for c in doc["clips"]), default=0)
        return doc

    def _validate(self, document, media_rows=None):
        doc = self._normalize(document)
        errors = [{"path": "/" + "/".join(map(str, error.absolute_path)), "message": error.message}
                  for error in Draft202012Validator(self._schema).iter_errors(doc)]
        if not errors:
            ids = [clip["clip_id"] for clip in doc["clips"]]
            if len(ids) != len(set(ids)):
                errors.append({"path": "/clips", "message": "clip_id values must be unique"})
            rows = media_rows if media_rows is not None else self._active_media()
            metadata = {row["media_id"]: json.loads(row["metadata"]) for row in rows}
            for index, clip in enumerate(doc["clips"]):
                media = metadata.get(clip["media_id"])
                if clip["source_end_ms"] <= clip["source_start_ms"]:
                    errors.append({"path": f"/clips/{index}", "message": "clip must have positive source duration"})
                elif media is None:
                    errors.append({"path": f"/clips/{index}/media_id", "message": "source is not active in this project"})
                elif clip["kind"] != media["kind"] and not (media["kind"] == "video" and clip["kind"] == "audio"):
                    errors.append({"path": f"/clips/{index}/kind", "message": "clip kind does not match source"})
                elif clip["source_end_ms"] > media["duration_ms"]:
                    errors.append({"path": f"/clips/{index}/source_end_ms", "message": "clip exceeds source duration"})
        if errors:
            raise ProjectError("invalid_timeline", "Source timeline validation failed", errors[:50])
        return doc

    def _active_media(self, project_id=None):
        if project_id is None:
            raise ValueError("project_id is required")
        return self.service.store.conn.execute(
            "SELECT m.* FROM project_source_media m LEFT JOIN project_media_removals r "
            "ON r.job_id=m.job_id AND r.media_id=m.media_id WHERE m.job_id=? AND r.media_id IS NULL "
            "ORDER BY m.revision", (project_id,)).fetchall()

    def _virtual(self, project_id):
        # The media bin and edit sequence are intentionally independent. Importing
        # a source never edits the timeline; placement is always an explicit action.
        return {"contract_version": "1", "duration_ms": 0, "clips": []}

    def get(self, project_id):
        with self.service.store._lock:
            self.service._row(project_id)
            row = self.service.store.conn.execute(
                "SELECT v.timeline_revision,v.project_revision,v.document,v.operation FROM project_source_timeline_state s "
                "JOIN project_source_timeline_versions v ON v.job_id=s.job_id AND v.timeline_revision=s.current_timeline_revision "
                "WHERE s.job_id=?", (project_id,)).fetchone()
            if row is None:
                document = self._virtual(project_id)
                return {"timeline_revision": 0, "project_revision": 0, "operation": "virtual_import", "document": document,
                        "history": self.history(project_id)}
            return {"timeline_revision": row["timeline_revision"], "project_revision": row["project_revision"],
                    "operation": row["operation"], "document": json.loads(row["document"]),
                    "history": self.history(project_id)}

    def _insert_version(self, conn, project_id, project_revision, document, operation):
        next_revision = conn.execute(
            "SELECT COALESCE(MAX(timeline_revision),0)+1 FROM project_source_timeline_versions WHERE job_id=?",
            (project_id,)).fetchone()[0]
        serialized = json.dumps(document, ensure_ascii=False, separators=(",", ":"))
        conn.execute("INSERT INTO project_source_timeline_versions VALUES(?,?,?,?,?,?)",
                     (project_id, next_revision, project_revision, serialized, operation, time.time()))
        conn.execute("INSERT INTO project_source_timeline_state VALUES(?,?) "
                     "ON CONFLICT(job_id) DO UPDATE SET current_timeline_revision=excluded.current_timeline_revision",
                     (project_id, next_revision))
        return next_revision, serialized

    def history(self, project_id):
        with self.service.store._lock:
            undo = self.service.store.conn.execute(
                "SELECT operation FROM project_source_timeline_events WHERE job_id=? AND undone=0 ORDER BY event_id DESC LIMIT 1",
                (project_id,)).fetchone()
            redo = self.service.store.conn.execute(
                "SELECT operation FROM project_source_timeline_events WHERE job_id=? AND undone=1 ORDER BY event_id ASC LIMIT 1",
                (project_id,)).fetchone()
        return {"can_undo": undo is not None, "can_redo": redo is not None,
                "undo_label": undo["operation"] if undo else None,
                "redo_label": redo["operation"] if redo else None}

    def command(self, project_id, operation, arguments, expected_revision, expected_timeline_revision):
        allowed = {"insert", "split", "trim", "delete_range", "ripple_delete", "remove_clip",
                   "move", "move_position", "detach_audio", "create_compound", "crossfade"}
        if operation not in allowed or not isinstance(arguments, dict):
            raise ProjectError("invalid_edit", "Unsupported source timeline operation")
        with self.service.store._lock:
            conn = self.service.store.conn
            try:
                conn.execute("BEGIN IMMEDIATE")
                row = self.service._row(project_id)
                self.service._expected(row, expected_revision)
                current = self.get(project_id)
                if current["timeline_revision"] != expected_timeline_revision:
                    raise ProjectError("revision_conflict", "Source timeline changed; reload before editing")
                before = current["document"]
                after = self._apply(before, operation, {**arguments, "project_id": project_id})
                after = self._validate(after, self._active_media(project_id))
                project_revision = row["revision"] + 1
                timeline_revision, serialized = self._insert_version(conn, project_id, project_revision, after, operation)
                conn.execute("DELETE FROM project_source_timeline_events WHERE job_id=? AND undone=1", (project_id,))
                conn.execute("INSERT INTO project_source_timeline_events(job_id,operation,before_document,after_document,"
                             "applied_timeline_revision,created_at) VALUES(?,?,?,?,?,?)",
                             (project_id, operation, json.dumps(before, separators=(",", ":")), serialized,
                              timeline_revision, time.time()))
                conn.execute("UPDATE project_state SET revision=? WHERE job_id=?", (project_revision, project_id))
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return {"project": self.service.open(project_id), "timeline": self.get(project_id)}

    def _clip(self, clips, clip_id):
        clip = next((item for item in clips if item["clip_id"] == clip_id), None)
        if clip is None:
            raise ProjectError("invalid_edit", "Selected source clip no longer exists")
        return clip

    def _apply(self, document, operation, args):
        doc = deepcopy(document)
        clips = doc["clips"]
        if operation == "insert":
            media_id, at = args.get("media_id"), args.get("at_ms")
            if type(at) is not int or at < 0:
                raise ProjectError("invalid_edit", "Choose a valid playhead position")
            row = next((r for r in self._active_media(args.get("project_id")) if r["media_id"] == media_id), None)
            if row is None:
                raise ProjectError("invalid_edit", "That source is no longer in this project")
            metadata = json.loads(row["metadata"]); kind = metadata["kind"]
            occupied = [int(c.get("track_index", 0)) for c in clips if c["kind"] == kind and
                        c["timeline_start_ms"] < at + metadata["duration_ms"] and
                        c["timeline_start_ms"] + self._duration(c) > at]
            track = args.get("track_index")
            if type(track) is not int or track < 0:
                track = 0
                while track in occupied: track += 1
            group = uuid4().hex
            clips.append({"clip_id": uuid4().hex, "media_id": media_id, "kind": kind,
                          "stream": "linked_av" if kind == "video" else "audio",
                          "track_index": track, "audio_enabled": kind == "video",
                          "source_start_ms": 0, "source_end_ms": metadata["duration_ms"],
                          "timeline_start_ms": at, "link_group_id": group, "crossfade_ms": 0})
        elif operation == "split":
            clip = self._clip(clips, args.get("clip_id"))
            at = args.get("at_ms")
            end = clip["timeline_start_ms"] + self._duration(clip)
            if type(at) is not int or not clip["timeline_start_ms"] + 40 <= at <= end - 40:
                raise ProjectError("invalid_edit", "Split must be at least 40 ms from the clip edge")
            source_at = clip["source_start_ms"] + at - clip["timeline_start_ms"]
            right = {**clip, "clip_id": uuid4().hex, "source_start_ms": source_at,
                     "timeline_start_ms": at, "crossfade_ms": 0}
            clip["source_end_ms"] = source_at
            clips.insert(clips.index(clip) + 1, right)
        elif operation == "trim":
            clip = self._clip(clips, args.get("clip_id"))
            start, end = args.get("start_ms"), args.get("end_ms")
            old_start = clip["timeline_start_ms"]
            old_end = old_start + self._duration(clip)
            if type(start) is not int or type(end) is not int or start < old_start or end > old_end or end - start < 40:
                raise ProjectError("invalid_edit", "Trim bounds must stay within the clip and retain at least 40 ms")
            clip["source_start_ms"] += start - old_start
            clip["source_end_ms"] -= old_end - end
            clip["timeline_start_ms"] = start
        elif operation == "remove_clip":
            clip = self._clip(clips, args.get("clip_id"))
            group = clip.get("link_group_id")
            doc["clips"] = [c for c in clips if c["clip_id"] != clip["clip_id"] and
                            not (args.get("linked", True) and group and c.get("link_group_id") == group)]
        elif operation == "detach_audio":
            clip = self._clip(clips, args.get("clip_id"))
            if clip["kind"] != "video" or clip.get("stream", "linked_av") != "linked_av":
                raise ProjectError("invalid_edit", "Select a video clip with attached audio")
            audio = {**clip, "clip_id": uuid4().hex, "kind": "audio", "stream": "audio",
                     "link_group_id": uuid4().hex,
                     "track_index": int(args.get("audio_track_index", 0)), "audio_enabled": False}
            clip["stream"] = "video"; clip["audio_enabled"] = False; clip["link_group_id"] = uuid4().hex
            clips.append(audio)
        elif operation in ("delete_range", "ripple_delete"):
            start, end = args.get("start_ms"), args.get("end_ms")
            if type(start) is not int or type(end) is not int or start < 0 or end <= start or end > doc["duration_ms"]:
                raise ProjectError("invalid_edit", "Select a valid timeline range to delete")
            updated = []
            for clip in clips:
                clip_start = clip["timeline_start_ms"]
                clip_end = clip_start + self._duration(clip)
                if clip_end <= start or clip_start >= end:
                    updated.append(clip)
                    continue
                if clip_start < start:
                    left = deepcopy(clip)
                    left["source_end_ms"] = left["source_start_ms"] + start - clip_start
                    updated.append(left)
                if clip_end > end:
                    right = deepcopy(clip)
                    right["clip_id"] = uuid4().hex
                    right["source_start_ms"] = clip["source_end_ms"] - (clip_end - end)
                    right["timeline_start_ms"] = end
                    right["crossfade_ms"] = 0
                    updated.append(right)
            if operation == "ripple_delete":
                delta = end - start
                for clip in updated:
                    if clip["timeline_start_ms"] >= end:
                        clip["timeline_start_ms"] -= delta
            doc["clips"] = updated
        elif operation == "move_position":
            clip = self._clip(clips, args.get("clip_id")); at = args.get("timeline_start_ms")
            if type(at) is not int or at < 0:
                raise ProjectError("invalid_edit", "Clip position must be on the timeline")
            requested = set(args.get("clip_ids") or [])
            linked = [c for c in clips if c["clip_id"] in requested or c.get("link_group_id") == clip.get("link_group_id") or
                      (clip.get("compound_group_id") and c.get("compound_group_id") == clip.get("compound_group_id"))]
            delta = at - clip["timeline_start_ms"]
            for item in linked:
                item["timeline_start_ms"] = max(0, item["timeline_start_ms"] + delta)
            track = args.get("track_index")
            if type(track) is int and track >= 0: clip["track_index"] = track
        elif operation == "create_compound":
            ids = args.get("clip_ids")
            if not isinstance(ids, list) or len(set(ids)) < 2:
                raise ProjectError("invalid_edit", "Select at least two clips to create a compound clip")
            selected = [c for c in clips if c["clip_id"] in set(ids)]
            if len(selected) != len(set(ids)):
                raise ProjectError("invalid_edit", "One or more selected clips no longer exist")
            group = uuid4().hex
            for item in selected: item["compound_group_id"] = group
        elif operation == "move":
            clip = self._clip(clips, args.get("clip_id"))
            target = args.get("to_index")
            if type(target) is not int or not 0 <= target < len(clips):
                raise ProjectError("invalid_edit", "Move destination is outside the cleanup sequence")
            ordered = sorted(clips, key=lambda item: (item["timeline_start_ms"], item["clip_id"]))
            ordered.remove(clip); ordered.insert(target, clip)
            cursor = 0
            for item in ordered:
                item["timeline_start_ms"] = cursor
                cursor += self._duration(item)
            doc["clips"] = ordered
        else:
            clip = self._clip(clips, args.get("clip_id"))
            value = args.get("crossfade_ms")
            if type(value) is not int or not 0 <= value <= 500:
                raise ProjectError("invalid_edit", "Crossfade must be between 0 and 500 ms")
            clip["crossfade_ms"] = min(value, max(0, self._duration(clip) // 2))
        return self._normalize(doc)

    def history_action(self, project_id, expected_revision, redo):
        order, undone = ("ASC", 1) if redo else ("DESC", 0)
        with self.service.store._lock:
            conn = self.service.store.conn
            try:
                conn.execute("BEGIN IMMEDIATE")
                row = self.service._row(project_id); self.service._expected(row, expected_revision)
                event = conn.execute(
                    f"SELECT * FROM project_source_timeline_events WHERE job_id=? AND undone=? ORDER BY event_id {order} LIMIT 1",
                    (project_id, undone)).fetchone()
                if event is None:
                    raise ProjectError("edit_history_empty", "Nothing to redo" if redo else "Nothing to undo")
                document = json.loads(event["after_document"] if redo else event["before_document"])
                document = self._validate(document, self._active_media(project_id))
                project_revision = row["revision"] + 1
                self._insert_version(conn, project_id, project_revision, document, "redo" if redo else "undo")
                conn.execute("UPDATE project_source_timeline_events SET undone=? WHERE event_id=?",
                             (0 if redo else 1, event["event_id"]))
                conn.execute("UPDATE project_state SET revision=? WHERE job_id=?", (project_revision, project_id))
                conn.commit()
            except Exception:
                conn.rollback(); raise
        return {"project": self.service.open(project_id), "timeline": self.get(project_id)}

    def remove_source(self, project_id, media_id, expected_revision, confirmed):
        impact = self.removal_impact(project_id, media_id)
        if confirmed is not True:
            raise ProjectError("confirmation_required", "Confirm removal after reviewing its impact", [impact])
        with self.service.store._lock:
            conn = self.service.store.conn
            try:
                conn.execute("BEGIN IMMEDIATE")
                row = self.service._row(project_id); self.service._expected(row, expected_revision)
                project_revision = row["revision"] + 1
                current = self.get(project_id)["document"]
                remaining = [clip for clip in current["clips"] if clip["media_id"] != media_id]
                current["clips"] = remaining
                current = self._normalize(current)
                self._insert_version(conn, project_id, project_revision, current, "remove_source")
                conn.execute("INSERT INTO project_media_removals VALUES(?,?,?,?)",
                             (project_id, media_id, project_revision, time.time()))
                conn.execute("DELETE FROM project_source_timeline_events WHERE job_id=?", (project_id,))
                conn.execute("UPDATE project_state SET revision=? WHERE job_id=?", (project_revision, project_id))
                conn.commit()
            except Exception:
                conn.rollback(); raise
        return {"project": self.service.open(project_id), "impact": impact, "managed_copy_retained": True}

    def removal_impact(self, project_id, media_id):
        with self.service.store._lock:
            row = self.service.store.conn.execute(
                "SELECT metadata FROM project_source_media WHERE job_id=? AND media_id=?", (project_id, media_id)).fetchone()
            removed = self.service.store.conn.execute(
                "SELECT 1 FROM project_media_removals WHERE job_id=? AND media_id=?", (project_id, media_id)).fetchone()
            if row is None or removed:
                raise ProjectError("not_found", "Source is not active in this project")
            timeline = self.get(project_id)
            clip_count = sum(clip["media_id"] == media_id for clip in timeline["document"]["clips"])
            artifacts = []
            for kind in ("storyboard", "layout"):
                try:
                    artifact = self.service.artifact(project_id, kind)
                    artifacts.append({"kind": kind, "revision": artifact["revision"]})
                except ProjectError:
                    pass
            renders = self.service.store.conn.execute(
                "SELECT COUNT(*) FROM project_render_runs WHERE job_id=?", (project_id,)).fetchone()[0]
            timings = self.service.store.conn.execute(
                "SELECT COUNT(*) FROM project_timing_runs WHERE job_id=?", (project_id,)).fetchone()[0]
            return {"media_id": media_id, "timeline_clips": clip_count, "artifacts": artifacts,
                    "render_runs": renders, "timing_runs": timings,
                    "warning": "Removing this source also removes its timeline clips. Existing project history and other media are preserved.",
                    "original_external_file_deleted": False, "managed_copy_deleted": False}
