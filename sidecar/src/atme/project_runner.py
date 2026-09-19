"""Compile and render approved project-service state without creative providers.

The connected AI authors semantic artifacts. This module only selects immutable
revisions, validates their dependencies, materializes a private runtime snapshot,
and invokes the existing deterministic Caleb-derived media pipeline.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading
import time
from pathlib import Path
from uuid import uuid4

from atme.project_service import ProjectError

PROFILE_SETTINGS = {
    "LONG_FORM_16_9": {"width": 1280, "height": 720, "fps": 30},
    "SHORT_FORM_9_16": {"width": 720, "height": 1280, "fps": 30},
}


class ProjectRunner:
    def __init__(self, service):
        self.service = service
        self._workers = {}
        with service.store._lock:
            service.store.conn.executescript("""
                CREATE TABLE IF NOT EXISTS project_render_runs (
                    job_id INTEGER NOT NULL,
                    run_id TEXT NOT NULL,
                    project_revision INTEGER NOT NULL,
                    fingerprint TEXT NOT NULL,
                    status TEXT NOT NULL,
                    manifest TEXT,
                    error TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY(job_id,run_id));
            """)
            service.store.conn.commit()

    def _latest_media_row(self, project_id):
        return self.service.store.conn.execute(
            "SELECT m.media_id,m.revision,m.relative_path,m.metadata FROM project_source_media m "
            "LEFT JOIN project_media_removals r ON r.job_id=m.job_id AND r.media_id=m.media_id "
            "WHERE m.job_id=? AND r.media_id IS NULL ORDER BY m.revision DESC LIMIT 1", (project_id,)).fetchone()

    def validate(self, project_id):
        with self.service.store._lock:
            from atme.narrative_source import describe
            row = self.service._row(project_id)
            state = {"revision": row["revision"], "profile": row["profile"],
                     "approved_script_revision": row["approved_script_revision"]}
            issues = []
            script = storyboard = layout = None
            source = describe(self.service, project_id)
            try:
                script = self.service.artifact(project_id, "script")
            except ProjectError:
                message = ("A connected-AI-derived semantic structure is required for rendering"
                           if source["mode"] == "recording_authority"
                           else "An externally authored script is required")
                issues.append({"code": "semantic_structure_missing", "message": message})
            if (source["script_approval_required"] and script is not None
                    and state["approved_script_revision"] != script["revision"]):
                issues.append({"code": "script_not_approved", "message": "The current script revision needs explicit user approval"})
            for kind in ("storyboard", "layout"):
                try:
                    value = self.service.artifact(project_id, kind)
                    if value.get("stale"):
                        issues.append({"code": kind + "_stale", "message": f"The {kind} must be revised for the current script and narration"})
                    if kind == "storyboard":
                        storyboard = value
                    else:
                        layout = value
                except ProjectError:
                    issues.append({"code": kind + "_missing", "message": f"An externally authored {kind} is required"})
            media = self._latest_media_row(project_id)
            if source["timing_authority"]["media"] is None:
                issues.append({"code": "narration_missing", "message": "Upload an original PCM WAV narration"})
            elif not source["media_compatible"]:
                issues.append({"code": "narrative_media_mismatch",
                               "message": f"This project requires {source['expected_media_kind']} narrative media"})
            if layout is not None:
                canvas = layout["document"].get("canvas", {})
                actual = float(canvas.get("width", 0)) / max(1.0, float(canvas.get("height", 0)))
                profile = PROFILE_SETTINGS[state["profile"]]
                expected = profile["width"] / profile["height"]
                if abs(actual - expected) > 0.01:
                    issues.append({"code": "layout_aspect_mismatch",
                                   "message": "Layout canvas must match the selected output profile aspect ratio"})
                if media is not None:
                    duration = source["timing_authority"]["duration_ms"]
                    doc = layout["document"]
                    bounds = [int(item.get("appear_at_ms", 0)) for item in doc.get("elements", [])]
                    bounds += [int(item["end_ms"]) for item in doc.get("board_timeline", {}).get("activations", [])]
                    bounds += [int(item["end_ms"]) for element in doc.get("elements", [])
                               for item in element.get("visibility_intervals", [])]
                    if max(bounds, default=0) > duration:
                        issues.append({"code": "layout_exceeds_narration",
                                       "message": "Layout timing exceeds the selected narration duration"})
            return {"project_id": project_id, "project_revision": state["revision"],
                    "ready": not issues, "issues": issues,
                    "authoritative_narrative_source": source,
                    "profile": {"id": state["profile"], **PROFILE_SETTINGS[state["profile"]]},
                    "selected_revisions": {
                        "script": script["revision"] if script else None,
                        "storyboard": storyboard["revision"] if storyboard else None,
                        "layout": layout["revision"] if layout else None,
                        "media": media["revision"] if media else None,
                        "source_timeline": self.service.source_timeline.get(project_id)["timeline_revision"]}}

    def _selection(self, project_id, expected_revision):
        report = self.validate(project_id)
        if report["project_revision"] != expected_revision:
            raise ProjectError("revision_conflict", "Project changed; reload before compiling")
        if not report["ready"]:
            raise ProjectError("project_not_ready", "Project cannot be compiled", report["issues"])
        with self.service.store._lock:
            state = self.service.open(project_id)
            script = self.service.artifact(project_id, "script")
            storyboard = self.service.artifact(project_id, "storyboard")
            layout = self.service.artifact(project_id, "layout")
            media = self._latest_media_row(project_id)
            return state, script, storyboard, layout, media

    def compile(self, project_id, expected_revision):
        state, script, storyboard, layout, media = self._selection(project_id, expected_revision)
        metadata = json.loads(media["metadata"])
        from atme.narrative_source import timing_audio
        from atme.timeline_media import materialize_video
        parent = self.service.store.db_path.resolve().parent
        source, timing_metadata, _ = timing_audio(self.service, project_id)
        selection = {"contract_version": "2", "project_id": project_id,
                     "project_revision": state["revision"], "profile": state["profile"],
                     "script_revision": script["revision"],
                     "storyboard_revision": storyboard["revision"],
                     "layout_revision": layout["revision"], "media_revision": media["revision"],
                     "media_id": media["media_id"], "media_sha256": metadata["sha256"],
                     "timing_audio_sha256": timing_metadata["sha256"],
                     "timing_duration_ms": timing_metadata["duration_ms"],
                     "source_timeline_revision": timing_metadata["timeline_revision"],
                     "source_timeline_fingerprint": timing_metadata["timeline_fingerprint"],
                     "semantic_role": state["authoritative_narrative_source"]["semantic_structure"]["role"]}
        timeline_document = self.service.source_timeline.get(project_id)["document"]
        source_video = None
        if any(clip["kind"] == "video" for clip in timeline_document["clips"]):
            source_video, source_video_metadata, _ = materialize_video(self.service, project_id)
            selection["source_video_sha256"] = source_video_metadata["sha256"]
        fingerprint = hashlib.sha256(json.dumps(selection, sort_keys=True,
            separators=(",", ":")).encode("utf-8")).hexdigest()
        runtime_root = (parent / "project-runs" / str(project_id)).resolve()
        if not runtime_root.is_relative_to(parent):
            raise ProjectError("compile_failed", "Runtime storage escaped the project data directory")
        destination = runtime_root / fingerprint
        manifest_file = destination / "compile_manifest.json"
        if manifest_file.exists():
            saved = json.loads(manifest_file.read_text(encoding="utf-8"))
            if saved.get("fingerprint") == fingerprint:
                return {**saved, "runtime_dir": str(destination), "resumed": True}
        pending = runtime_root / ("." + fingerprint + "." + uuid4().hex + ".pending")
        try:
            inputs = pending / "inputs"
            inputs.mkdir(parents=True, exist_ok=False)
            _write_json(inputs / "script.json", script["document"])
            _write_json(inputs / "visual_plan.json", storyboard["document"])
            _write_json(inputs / "layout.json", layout["document"])
            shutil.copyfile(source, inputs / "narration.wav")
            if source_video is not None:
                shutil.copyfile(source_video, inputs / "source-video.mp4")
            compiled = {**selection, "fingerprint": fingerprint,
                        "compiled_at": time.time(), "runtime_dir": str(destination),
                        "resumed": False}
            _write_json(pending / "compile_manifest.json", compiled)
            runtime_root.mkdir(parents=True, exist_ok=True)
            created = False
            try:
                os.replace(pending, destination)
                created = True
            except FileExistsError:
                shutil.rmtree(pending)
            return {**json.loads(manifest_file.read_text(encoding="utf-8")),
                    "runtime_dir": str(destination), "resumed": not created}
        except Exception:
            if pending.exists():
                shutil.rmtree(pending)
            raise

    def render(self, project_id, expected_revision, confirmed):
        if confirmed is not True:
            raise ProjectError("render_confirmation_required", "Rendering must be explicitly requested")
        compiled = self.compile(project_id, expected_revision)
        run_id = compiled["fingerprint"][:24]
        now = time.time()
        with self.service.store._lock:
            existing = self.service.store.conn.execute(
                "SELECT status,manifest,error FROM project_render_runs WHERE job_id=? AND run_id=?",
                (project_id, run_id)).fetchone()
            if existing and existing["status"] == "done" and existing["manifest"]:
                try:
                    self.output_path(project_id, run_id)
                    return self.status(project_id, run_id)
                except ProjectError:
                    pass  # Missing/corrupt derived output is rebuilt from the immutable snapshot.
            self.service.store.conn.execute(
                "INSERT INTO project_render_runs VALUES(?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(job_id,run_id) DO UPDATE SET status='running',error=NULL,updated_at=excluded.updated_at",
                (project_id, run_id, expected_revision, compiled["fingerprint"], "running", None, None, now, now))
            self.service.store.conn.commit()
        return self._execute_render(compiled, project_id, expected_revision, run_id)

    def _execute_render(self, compiled, project_id, expected_revision, run_id):
        snapshot = Path(compiled["runtime_dir"])
        inputs = snapshot / "inputs"
        directory = snapshot / "work"
        (directory / "audio").mkdir(parents=True, exist_ok=True)
        # Always restore authored inputs before a retry. Derived alignment/layout
        # mutations and render checkpoints remain confined to the work directory.
        for name in ("script.json", "visual_plan.json", "layout.json"):
            shutil.copyfile(inputs / name, directory / name)
        shutil.copyfile(inputs / "narration.wav", directory / "audio" / "upload.wav")
        try:
            from atme import pipeline
            profile = PROFILE_SETTINGS[compiled["profile"]]
            script = json.loads((directory / "script.json").read_text(encoding="utf-8"))
            layout = json.loads((directory / "layout.json").read_text(encoding="utf-8"))
            audio = pipeline.polish_stage(directory, voice_mode="upload", remove_silence=False)
            aligned = pipeline.align_stage(directory, script, audio, voice_mode="upload",
                                           layout_dict=layout,
                                           semantic_authority=compiled["semantic_role"])
            rendered = pipeline.render_stage(directory, aligned, **profile)
            manifest = pipeline.assemble_stage(directory, script, audio, aligned, rendered)
            source_video = inputs / "source-video.mp4"
            if source_video.is_file():
                _compose_talking_head(source_video, Path(manifest["artifacts"]["video"]["path"]),
                                      Path(manifest["artifacts"]["video"]["path"]), profile)
                final_path = Path(manifest["artifacts"]["video"]["path"])
                manifest["artifacts"]["video"].update(
                    sha256=_sha256(final_path), bytes=final_path.stat().st_size)
                manifest["composition_mode"] = "talking_head_with_caleb_overlays"
            public_manifest = {"run_id": run_id, "status": "done", "project_id": project_id,
                               "project_revision": expected_revision,
                               "duration_ms": manifest["duration_ms"],
                               "video": {"sha256": manifest["artifacts"]["video"]["sha256"],
                                         "bytes": manifest["artifacts"]["video"]["bytes"]}}
            self._finish(project_id, run_id, "done", public_manifest, None)
        except Exception as exc:
            self._finish(project_id, run_id, "failed", None, str(exc)[:2000])
            raise ProjectError("render_failed", "Rendering failed", [{"message": str(exc)[:500]}]) from exc
        return self.status(project_id, run_id)

    def request_render(self, project_id, expected_revision, confirmed):
        """Queue a fixed render so MCP/HTTP calls never wait for video encoding."""
        if confirmed is not True:
            raise ProjectError("render_confirmation_required", "Rendering must be explicitly requested")
        compiled = self.compile(project_id, expected_revision)
        run_id = compiled["fingerprint"][:24]
        now = time.time()
        # Integrity-check completed output before opening the short write transaction.
        try:
            existing = self.status(project_id, run_id)
            if existing["status"] == "done":
                self.output_path(project_id, run_id)
                return existing
        except ProjectError:
            pass
        with self.service.store._lock:
            conn = self.service.store.conn
            try:
                conn.execute("BEGIN IMMEDIATE")
                existing = conn.execute(
                    "SELECT status FROM project_render_runs WHERE job_id=? AND run_id=?",
                    (project_id, run_id)).fetchone()
                if existing and existing["status"] in ("queued", "running"):
                    conn.commit()
                    return self.status(project_id, run_id)
                conn.execute(
                    "INSERT INTO project_render_runs VALUES(?,?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(job_id,run_id) DO UPDATE SET status='queued',manifest=NULL,error=NULL,updated_at=excluded.updated_at",
                    (project_id, run_id, expected_revision, compiled["fingerprint"], "queued", None, None, now, now))
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        worker = threading.Thread(target=_background_render,
                                  args=(self.service.store.db_path, project_id, expected_revision, compiled),
                                  name=f"atme-render-{project_id}-{run_id}", daemon=False)
        self._workers[run_id] = worker
        worker.start()
        return self.status(project_id, run_id)

    def preview(self, project_id, expected_revision, at_ms):
        if type(at_ms) is not int or at_ms < 0:
            raise ProjectError("invalid_request", "Preview time must be a nonnegative integer")
        state, _, _, layout, _media = self._selection(project_id, expected_revision)
        duration = state["authoritative_narrative_source"]["timing_authority"]["duration_ms"]
        if at_ms >= duration:
            raise ProjectError("invalid_request", "Preview time must be within the selected narration")
        doc = layout["document"]
        profile = PROFILE_SETTINGS[state["profile"]]
        return self._preview_document(doc, profile, project_id, expected_revision, at_ms)

    def preview_layout(self, project_id, expected_revision, document, at_ms):
        if type(at_ms) is not int or at_ms < 0:
            raise ProjectError("invalid_request", "Preview time must be a nonnegative integer")
        with self.service.store._lock:
            row = self.service._row(project_id)
            self.service._expected(row, expected_revision)
            media = self._latest_media_row(project_id)
            if media is None:
                raise ProjectError("narration_missing", "A recording is required for proposal preview")
            duration = self.service.source_timeline.get(project_id)["document"]["duration_ms"]
            if at_ms >= duration:
                raise ProjectError("invalid_request", "Preview time must be within the narration")
            profile = PROFILE_SETTINGS[row["profile"]]
        return self._preview_document(document, profile, project_id, expected_revision, at_ms)

    @staticmethod
    def _preview_document(doc, profile, project_id, expected_revision, at_ms):
        import io

        from atme.render.animator import _FrameRenderer, build_draw_windows
        from atme.render.svg_builder import element_stroke_info
        scale = min(1.0, 960.0 / max(profile["width"], profile["height"]))
        width, height = round(profile["width"] * scale), round(profile["height"] * scale)
        infos = {element["id"]: element_stroke_info(element, doc["seed"])
                 for element in doc["elements"]}
        renderer = _FrameRenderer(doc, infos, build_draw_windows(doc["elements"]), width, height)
        buffer = io.BytesIO()
        renderer.frame(at_ms).save(buffer, format="PNG")
        return {"png": buffer.getvalue(), "at_ms": at_ms, "width": width, "height": height,
                "project_id": project_id, "project_revision": expected_revision}

    def _finish(self, project_id, run_id, status, manifest, error):
        with self.service.store._lock:
            self.service.store.conn.execute(
                "UPDATE project_render_runs SET status=?,manifest=?,error=?,updated_at=? WHERE job_id=? AND run_id=?",
                (status, json.dumps(manifest) if manifest else None, error, time.time(), project_id, run_id))
            self.service.store.conn.commit()

    def status(self, project_id, run_id):
        if not isinstance(run_id, str) or len(run_id) != 24 or any(c not in "0123456789abcdef" for c in run_id):
            raise ProjectError("invalid_request", "run_id must be a 24-character hexadecimal ID")
        with self.service.store._lock:
            current = self.service._row(project_id)
            row = self.service.store.conn.execute(
                "SELECT project_revision,status,manifest,error,created_at,updated_at FROM project_render_runs "
                "WHERE job_id=? AND run_id=?", (project_id, run_id)).fetchone()
            if row is None:
                raise ProjectError("not_found", "Render run does not exist")
            result = {"project_id": project_id, "run_id": run_id,
                      "project_revision": row["project_revision"], "status": row["status"],
                      "current_project_revision": current["revision"],
                      "stale": row["project_revision"] != current["revision"],
                      "created_at": row["created_at"], "updated_at": row["updated_at"]}
            if row["manifest"]:
                result["manifest"] = json.loads(row["manifest"])
            if row["error"]:
                result["error"] = row["error"]
            return result

    def output_path(self, project_id, run_id):
        status = self.status(project_id, run_id)
        if status["status"] != "done":
            raise ProjectError("render_not_ready", "Render output is not ready")
        with self.service.store._lock:
            row = self.service.store.conn.execute(
                "SELECT fingerprint FROM project_render_runs WHERE job_id=? AND run_id=?",
                (project_id, run_id)).fetchone()
        parent = self.service.store.db_path.resolve().parent
        output = (parent / "project-runs" / str(project_id) / row["fingerprint"]
                  / "work" / "out" / "final.mp4").resolve()
        if not output.is_relative_to(parent) or not output.is_file():
            raise ProjectError("render_not_ready", "Render output is unavailable")
        manifest = status["manifest"]["video"]
        if output.stat().st_size != manifest["bytes"] or _sha256(output) != manifest["sha256"]:
            raise ProjectError("render_changed", "Render output no longer matches its immutable record")
        return output

    def list_runs(self, project_id):
        with self.service.store._lock:
            self.service._row(project_id)
            rows = self.service.store.conn.execute(
                "SELECT run_id FROM project_render_runs WHERE job_id=? ORDER BY created_at DESC LIMIT 100",
                (project_id,)).fetchall()
        return [self.status(project_id, row["run_id"]) for row in rows]


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path, document):
    Path(path).write_text(json.dumps(document, ensure_ascii=False, indent=2,
                                    allow_nan=False), encoding="utf-8")


def _compose_talking_head(source_video, caleb_video, destination, profile):
    """Place Caleb ink over the edited talking-head sequence.

    The renderer's paper colour is keyed out, preserving the source picture as
    the visual base while retaining authored ink, captions and illustrations.
    """
    import subprocess
    from atme.render.animator import find_ffmpeg

    pending = Path(destination).with_name(Path(destination).stem + ".composite.pending.mp4")
    filter_graph = (
        f"[0:v]scale={profile['width']}:{profile['height']}:force_original_aspect_ratio=decrease,"
        f"pad={profile['width']}:{profile['height']}:(ow-iw)/2:(oh-ih)/2[base];"
        f"[1:v]scale={profile['width']}:{profile['height']},"
        "colorkey=0xFAF9F5:0.16:0.08[ink];[base][ink]overlay=shortest=1[v]"
    )
    command = [find_ffmpeg(), "-y", "-hide_banner", "-v", "error",
               "-i", str(source_video), "-i", str(caleb_video),
               "-filter_complex", filter_graph, "-map", "[v]", "-map", "0:a?",
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
               "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(pending)]
    result = subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                            text=True, check=False)
    if result.returncode or not pending.is_file():
        pending.unlink(missing_ok=True)
        raise RuntimeError("talking-head composition failed: " + result.stderr[-500:])
    os.replace(pending, destination)


def _background_render(database, project_id, expected_revision, compiled):
    """Own its database connection so a disconnected MCP client cannot corrupt the run."""
    from atme.store.db import JobStore

    store = JobStore(database)
    try:
        from atme.project_service import ProjectService

        runner = ProjectService(store).runner
        run_id = compiled["fingerprint"][:24]
        with store._lock:
            store.conn.execute(
                "UPDATE project_render_runs SET status='running',updated_at=? WHERE job_id=? AND run_id=?",
                (time.time(), project_id, run_id))
            store.conn.commit()
        try:
            runner._execute_render(compiled, project_id, expected_revision, run_id)
        except ProjectError:
            pass  # _execute_render already persisted the bounded failure status.
    finally:
        store.close()
