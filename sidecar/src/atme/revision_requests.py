"""Bounded UI-to-MCP revision requests; proposals never apply without user confirmation."""
from __future__ import annotations

import json
import time
from uuid import uuid4

from jsonschema import Draft202012Validator

from atme.project_service import ProjectError

TARGETS = frozenset({"scene", "script", "illustration", "caption", "audio", "video", "style", "timeline"})
ARTIFACTS = frozenset({"script", "storyboard", "layout"})


class RevisionRequests:
    def __init__(self, service):
        self.service = service
        with service.store._lock:
            service.store.conn.executescript("""
                CREATE TABLE IF NOT EXISTS project_revision_requests (
                    job_id INTEGER NOT NULL,
                    request_id TEXT NOT NULL,
                    project_revision INTEGER NOT NULL,
                    selection TEXT NOT NULL,
                    instruction TEXT NOT NULL,
                    status TEXT NOT NULL,
                    proposal TEXT,
                    result_revision INTEGER,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY(job_id,request_id));
            """)
            service.store.conn.commit()

    def create(self, project_id, expected_revision, selection, instruction):
        if (not isinstance(selection, dict) or set(selection) != {"kind", "id", "start_ms", "end_ms"}
                or selection.get("kind") not in TARGETS or not isinstance(selection.get("id"), str)
                or not selection["id"] or len(selection["id"]) > 300
                or type(selection.get("start_ms")) is not int or type(selection.get("end_ms")) is not int
                or selection["start_ms"] < 0 or selection["end_ms"] <= selection["start_ms"]):
            raise ProjectError("invalid_revision_request", "Select one valid scene, element, clip, or time range")
        if not isinstance(instruction, str) or not instruction.strip() or len(instruction.strip()) > 500:
            raise ProjectError("invalid_revision_request", "A revision instruction of 1–500 characters is required")
        request_id = uuid4().hex
        now = time.time()
        with self.service.store._lock:
            row = self.service._row(project_id)
            self.service._expected(row, expected_revision)
            media = self.service.list_media(project_id)
            duration = media[-1]["duration_ms"] if media else None
            if duration is not None and selection["end_ms"] > duration:
                raise ProjectError("invalid_revision_request", "Selection exceeds the current project duration")
            self.service.store.conn.execute(
                "INSERT INTO project_revision_requests VALUES(?,?,?,?,?,?,?,?,?,?)",
                (project_id, request_id, expected_revision, json.dumps(selection), instruction.strip(),
                 "pending", None, None, now, now))
            self.service.store.conn.commit()
        return self.get(project_id, request_id)

    def list(self, project_id, status=None):
        if status is not None and status not in ("pending", "proposed", "applied", "rejected", "superseded"):
            raise ProjectError("invalid_request", "Unsupported revision-request status")
        with self.service.store._lock:
            self.service._row(project_id)
            rows = self.service.store.conn.execute(
                "SELECT * FROM project_revision_requests WHERE job_id=? AND (? IS NULL OR status=?) "
                "ORDER BY created_at DESC LIMIT 100", (project_id, status, status)).fetchall()
            return [self._value(row) for row in rows]

    def get(self, project_id, request_id):
        if not isinstance(request_id, str) or len(request_id) != 32:
            raise ProjectError("invalid_request", "Invalid revision request ID")
        with self.service.store._lock:
            self.service._row(project_id)
            row = self.service.store.conn.execute(
                "SELECT * FROM project_revision_requests WHERE job_id=? AND request_id=?",
                (project_id, request_id)).fetchone()
            if row is None:
                raise ProjectError("not_found", "Revision request does not exist")
            return self._value(row)

    def propose(self, project_id, request_id, expected_revision, artifact_kind, document, summary):
        if artifact_kind not in ARTIFACTS:
            raise ProjectError("invalid_proposal", "Proposal artifact must be script, storyboard, or layout")
        if not isinstance(summary, str) or not summary.strip() or len(summary.strip()) > 500:
            raise ProjectError("invalid_proposal", "A proposal summary of 1–500 characters is required")
        try:
            serialized = json.dumps(document, ensure_ascii=False, allow_nan=False)
        except (ValueError, TypeError) as exc:
            raise ProjectError("invalid_proposal", "Proposal must contain finite JSON") from exc
        if len(serialized.encode("utf-8")) > 1024 * 1024:
            raise ProjectError("too_large", "Revision proposal exceeds 1 MiB")
        errors = [{"path": "/" + "/".join(map(str, error.absolute_path)), "message": error.message}
                  for error in Draft202012Validator(self.service.schema(artifact_kind)).iter_errors(document)]
        if not errors and artifact_kind == "layout":
            from atme.external_inputs import validate_external_inputs
            try:
                script = self.service.artifact(project_id, "script")["document"]
                validate_external_inputs(script, document)
            except (ProjectError, ValueError, TypeError, KeyError) as exc:
                errors.append({"path": "/", "message": str(exc)})
        if not errors and artifact_kind == "storyboard":
            try:
                scenes = {scene["scene_id"]: scene["spoken_text"]
                          for scene in self.service.artifact(project_id, "script")["document"]["scenes"]}
                if ({beat["scene_id"] for beat in document["beats"]} != set(scenes)
                        or any(beat["narration"] != scenes[beat["scene_id"]] for beat in document["beats"])):
                    raise ValueError("Storyboard must preserve every current scene narration")
            except (ProjectError, ValueError, TypeError, KeyError) as exc:
                errors.append({"path": "/", "message": str(exc)})
        if errors:
            raise ProjectError("invalid_proposal", "Proposal schema validation failed", errors[:50])
        proposal = {"artifact_kind": artifact_kind, "document": document, "summary": summary.strip()}
        with self.service.store._lock:
            row = self.service._row(project_id)
            self.service._expected(row, expected_revision)
            request = self.get(project_id, request_id)
            if request["status"] != "pending" or request["project_revision"] != expected_revision:
                raise ProjectError("revision_conflict", "Revision request is no longer pending for this project revision")
            self.service.store.conn.execute(
                "UPDATE project_revision_requests SET status='proposed',proposal=?,updated_at=? "
                "WHERE job_id=? AND request_id=?", (json.dumps(proposal), time.time(), project_id, request_id))
            self.service.store.conn.commit()
        return self.get(project_id, request_id)

    def decide(self, project_id, request_id, expected_revision, accepted):
        if type(accepted) is not bool:
            raise ProjectError("invalid_request", "accepted must be true or false")
        request = self.get(project_id, request_id)
        if request["status"] != "proposed":
            raise ProjectError("revision_conflict", "Only a proposed revision can be decided")
        if not accepted:
            with self.service.store._lock:
                row = self.service._row(project_id)
                self.service._expected(row, expected_revision)
                self.service.store.conn.execute(
                    "UPDATE project_revision_requests SET status='rejected',updated_at=? WHERE job_id=? AND request_id=?",
                    (time.time(), project_id, request_id))
                self.service.store.conn.commit()
            return self.get(project_id, request_id)
        proposal = request["proposal"]
        project = self.service.write(project_id, proposal["artifact_kind"], proposal["document"], expected_revision)
        with self.service.store._lock:
            self.service.store.conn.execute(
                "UPDATE project_revision_requests SET status='applied',result_revision=?,updated_at=? "
                "WHERE job_id=? AND request_id=?", (project["revision"], time.time(), project_id, request_id))
            self.service.store.conn.commit()
        return {"request": self.get(project_id, request_id), "project": project}

    def apply_requested(self, project_id, request_id, expected_revision,
                        artifact_kind, document, summary):
        """Apply an edit that answers an explicit user-authored bounded request.

        The request itself is the user's authorization, so requiring a second
        approval would only add a redundant production gate.  The same schema,
        revision and dependency validation used by proposals and normal writes
        still applies.
        """
        self.propose(project_id, request_id, expected_revision,
                     artifact_kind, document, summary)
        return self.decide(project_id, request_id, expected_revision, True)

    def preview(self, project_id, request_id, expected_revision, at_ms):
        request = self.get(project_id, request_id)
        if request["status"] != "proposed" or request["project_revision"] != expected_revision:
            raise ProjectError("revision_conflict", "Proposal is not current enough to preview")
        proposal = request["proposal"]
        if proposal["artifact_kind"] == "layout":
            return self.service.runner.preview_layout(project_id, expected_revision,
                                                      proposal["document"], at_ms)
        return self.service.preview_project(project_id, expected_revision, at_ms)

    @staticmethod
    def _value(row):
        value = {"project_id": row["job_id"], "request_id": row["request_id"],
                 "project_revision": row["project_revision"], "selection": json.loads(row["selection"]),
                 "instruction": row["instruction"], "status": row["status"],
                 "result_revision": row["result_revision"], "created_at": row["created_at"],
                 "updated_at": row["updated_at"]}
        if row["proposal"]:
            value["proposal"] = json.loads(row["proposal"])
        return value
