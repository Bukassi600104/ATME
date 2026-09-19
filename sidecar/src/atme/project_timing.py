"""Pre-layout technical speech timing for authoritative narrative recordings."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading
import time
from pathlib import Path
from uuid import uuid4

import numpy as np
import soundfile as sf

from atme.project_service import ProjectError


class ProjectTiming:
    def __init__(self, service):
        self.service = service
        self._workers = {}
        with service.store._lock:
            service.store.conn.executescript("""
                CREATE TABLE IF NOT EXISTS project_timing_runs (
                    job_id INTEGER NOT NULL,
                    run_id TEXT NOT NULL,
                    project_revision INTEGER NOT NULL,
                    source_fingerprint TEXT NOT NULL,
                    status TEXT NOT NULL,
                    document TEXT,
                    error TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY(job_id,run_id));
            """)
            service.store.conn.commit()

    def _snapshot(self, project_id, expected_revision):
        from atme.narrative_source import (
            authoritative_media_row,
            describe,
            timing_audio,
        )

        with self.service.store._lock:
            row = self.service._row(project_id)
            self.service._expected(row, expected_revision)
            source = describe(self.service, project_id)
            if not source["ready_for_timing"]:
                errors = []
                if source["timing_authority"]["media"] is None:
                    errors.append({"code": "narrative_recording_missing",
                                   "message": "Upload the authoritative narrative recording"})
                elif not source["media_compatible"]:
                    errors.append({"code": "narrative_media_mismatch",
                                   "message": f"This project requires {source['expected_media_kind']} media"})
                if source["script_approval_required"]:
                    errors.append({"code": "script_not_approved",
                                   "message": "Approve the current external script before timing"})
                raise ProjectError("timing_not_ready", "Narrative source is not ready for timing", errors)
            media = authoritative_media_row(self.service, project_id)
            try:
                script = self.service.artifact(project_id, "script")
            except ProjectError:
                script = None
            media_metadata = json.loads(media["metadata"])
            parent = self.service.store.db_path.resolve().parent
            media_path, timing_metadata, _ = timing_audio(self.service, project_id)
            identity = {"contract_version": "1", "project_id": project_id,
                        "project_revision": expected_revision, "mode": source["mode"],
                        "media_revision": media["revision"], "media_id": media["media_id"],
                        "media_sha256": media_metadata["sha256"],
                        "timing_audio_sha256": timing_metadata["sha256"],
                        "source_timeline_revision": timing_metadata["timeline_revision"],
                        "source_timeline_fingerprint": timing_metadata["timeline_fingerprint"],
                        "structure_revision": script["revision"] if script else None}
            fingerprint = hashlib.sha256(json.dumps(identity, sort_keys=True,
                separators=(",", ":")).encode("utf-8")).hexdigest()
            root = (parent / "project-timing" / str(project_id) / fingerprint).resolve()
            if not root.is_relative_to(parent):
                raise ProjectError("timing_failed", "Timing storage escaped project data")
            manifest = root / "source.json"
            if not manifest.exists():
                pending = root.parent / ("." + fingerprint + "." + uuid4().hex + ".pending")
                try:
                    inputs = pending / "inputs"
                    inputs.mkdir(parents=True, exist_ok=False)
                    shutil.copyfile(media_path, inputs / "narration.wav")
                    if script:
                        _write_json(inputs / "semantic_structure.json", script["document"])
                    _write_json(pending / "source.json", {**identity, "source_fingerprint": fingerprint})
                    root.parent.mkdir(parents=True, exist_ok=True)
                    try:
                        os.replace(pending, root)
                    except FileExistsError:
                        shutil.rmtree(pending)
                except Exception:
                    if pending.exists():
                        shutil.rmtree(pending)
                    raise
            return {**identity, "source_fingerprint": fingerprint, "runtime_dir": str(root),
                    "semantic_role": source["semantic_structure"]["role"]}

    def request(self, project_id, expected_revision):
        snapshot = self._snapshot(project_id, expected_revision)
        run_id = snapshot["source_fingerprint"][:24]
        now = time.time()
        with self.service.store._lock:
            conn = self.service.store.conn
            try:
                conn.execute("BEGIN IMMEDIATE")
                existing = conn.execute(
                    "SELECT status FROM project_timing_runs WHERE job_id=? AND run_id=?",
                    (project_id, run_id)).fetchone()
                if existing and existing["status"] in ("queued", "running", "done"):
                    conn.commit()
                    return self.status(project_id, run_id)
                conn.execute(
                    "INSERT INTO project_timing_runs VALUES(?,?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(job_id,run_id) DO UPDATE SET status='queued',document=NULL,error=NULL,updated_at=excluded.updated_at",
                    (project_id, run_id, expected_revision, snapshot["source_fingerprint"],
                     "queued", None, None, now, now))
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        worker = threading.Thread(target=_background_prepare,
            args=(self.service.store.db_path, project_id, expected_revision, snapshot),
            name=f"atme-timing-{project_id}-{run_id}", daemon=False)
        self._workers[run_id] = worker
        worker.start()
        return self.status(project_id, run_id)

    def prepare(self, project_id, expected_revision):
        snapshot = self._snapshot(project_id, expected_revision)
        run_id = snapshot["source_fingerprint"][:24]
        now = time.time()
        with self.service.store._lock:
            self.service.store.conn.execute(
                "INSERT INTO project_timing_runs VALUES(?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(job_id,run_id) DO UPDATE SET status='running',document=NULL,error=NULL,updated_at=excluded.updated_at",
                (project_id, run_id, expected_revision, snapshot["source_fingerprint"],
                 "running", None, None, now, now))
            self.service.store.conn.commit()
        return self._execute(snapshot, project_id, expected_revision, run_id)

    def _execute(self, snapshot, project_id, expected_revision, run_id):
        root = Path(snapshot["runtime_dir"])
        work = root / "work"
        (work / "audio").mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / "inputs" / "narration.wav", work / "audio" / "upload.wav")
        try:
            from atme import pipeline
            from atme.audio.voice_upload import reconcile_words
            from atme.planning_context import build_planning_context

            audio = pipeline.polish_stage(work, voice_mode="upload", remove_silence=False)
            samples, rate = sf.read(audio["final_wav"], dtype="float32", always_2d=True)
            mono = np.asarray(samples, dtype=np.float32).mean(axis=1)
            observed = _acoustic_words(mono, int(rate), [0])
            structure_file = root / "inputs" / "semantic_structure.json"
            if structure_file.exists():
                script = json.loads(structure_file.read_text(encoding="utf-8"))
                role = snapshot["semantic_role"]
                words, starts, report = reconcile_words(
                    observed, script["scenes"], int(audio["duration_ms"]), semantic_source=role)
                context = build_planning_context(script, words, int(audio["duration_ms"]),
                                                 audio["sha256"], semantic_authority=role)
                semantic = {"role": role, "structure_revision": snapshot["structure_revision"],
                            "alignment_report": report, "planning_context": context,
                            "scene_starts_ms": starts}
                status = "ready" if context["status"] == "ready" else "needs_review"
                units = None
            else:
                units = [{"unit_index": index, "start_ms": int(word["start_ms"]),
                          "end_ms": int(word["end_ms"]), "confidence": word.get("confidence"),
                          "flagged": bool(word.get("flagged", False))}
                         for index, word in enumerate(observed)]
                semantic = {"role": "none", "structure_revision": None,
                            "instruction": "Connected AI must derive transcript and scene structure from the authoritative recording"}
                status = "needs_semantic_structure"
            document = {"contract_version": "1", "status": status,
                        "project_id": project_id, "project_revision": expected_revision,
                        "source_fingerprint": snapshot["source_fingerprint"],
                        "authority_mode": snapshot["mode"],
                        "source_media": {"media_id": snapshot["media_id"],
                                         "revision": snapshot["media_revision"],
                                         "sha256": snapshot["media_sha256"]},
                        "final_audio": {"duration_ms": int(audio["duration_ms"]),
                                        "sha256": audio["sha256"], "timebase": "final_audio_ms"},
                        "semantic_structure": semantic}
            if units is not None:
                document["speech_units"] = units
            _write_json(root / "timing.json", document)
            self._finish(project_id, run_id, "done", document, None)
        except Exception as exc:
            self._finish(project_id, run_id, "failed", None, str(exc)[:2000])
            raise ProjectError("timing_failed", "Technical speech timing failed",
                               [{"message": str(exc)[:500]}]) from exc
        return self.status(project_id, run_id)

    def _finish(self, project_id, run_id, status, document, error):
        with self.service.store._lock:
            self.service.store.conn.execute(
                "UPDATE project_timing_runs SET status=?,document=?,error=?,updated_at=? "
                "WHERE job_id=? AND run_id=?",
                (status, json.dumps(document) if document else None, error, time.time(), project_id, run_id))
            self.service.store.conn.commit()

    def status(self, project_id, run_id):
        if not isinstance(run_id, str) or len(run_id) != 24 or any(c not in "0123456789abcdef" for c in run_id):
            raise ProjectError("invalid_request", "run_id must be a 24-character hexadecimal ID")
        with self.service.store._lock:
            current = self.service._row(project_id)
            row = self.service.store.conn.execute(
                "SELECT project_revision,status,document,error,created_at,updated_at "
                "FROM project_timing_runs WHERE job_id=? AND run_id=?", (project_id, run_id)).fetchone()
            if row is None:
                raise ProjectError("not_found", "Timing run does not exist")
            result = {"project_id": project_id, "run_id": run_id,
                      "project_revision": row["project_revision"], "status": row["status"],
                      "current_project_revision": current["revision"],
                      "stale": row["project_revision"] != current["revision"],
                      "created_at": row["created_at"], "updated_at": row["updated_at"]}
            if row["document"]:
                result["timing"] = json.loads(row["document"])
            if row["error"]:
                result["error"] = row["error"]
            return result


def _acoustic_words(samples, sample_rate, scene_starts_ms):
    from atme.audio.align import align_words
    return align_words(samples, sample_rate, scene_starts_ms)


def _background_prepare(database, project_id, expected_revision, snapshot):
    from atme.store.db import JobStore

    store = JobStore(database)
    try:
        from atme.project_service import ProjectService

        timing = ProjectService(store).timing
        run_id = snapshot["source_fingerprint"][:24]
        with store._lock:
            store.conn.execute("UPDATE project_timing_runs SET status='running',updated_at=? "
                               "WHERE job_id=? AND run_id=?", (time.time(), project_id, run_id))
            store.conn.commit()
        try:
            timing._execute(snapshot, project_id, expected_revision, run_id)
        except ProjectError:
            pass
    finally:
        store.close()


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False),
                          encoding="utf-8")
