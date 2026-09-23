"""Deterministic project truth and externally authored artifact revisions.

No creative providers, semantic transcription, research or factual verification.
Shares the existing job database so adapters do not maintain competing project stores.
"""
from __future__ import annotations

import hashlib
import json
import time
from copy import deepcopy

from jsonschema import Draft202012Validator

from atme.resources import resource_path

PROFILES = ("LONG_FORM_16_9", "SHORT_FORM_9_16")
INPUT_KINDS = ("idea-first", "script-first", "script+audio", "script+video", "audio-only", "video-only")
BRIEF_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["description"],
    "properties": {"description": {"type": "string", "minLength": 1, "maxLength": 20000},
                   "audience": {"type": "string", "maxLength": 2000},
                   "constraints": {"type": "array", "maxItems": 100,
                                   "items": {"type": "string", "maxLength": 2000}}},
}


class ProjectError(ValueError):
    def __init__(self, code, message, errors=None):
        super().__init__(message)
        self.code = code
        self.errors = errors or []

    def detail(self):
        return {"code": self.code, "message": str(self), "errors": self.errors}


class ProjectService:
    def __init__(self, store):
        self.store = store
        with store._lock:
            store.conn.executescript("""
                CREATE TABLE IF NOT EXISTS project_state (
                    job_id INTEGER PRIMARY KEY REFERENCES jobs(id),
                    revision INTEGER NOT NULL DEFAULT 0,
                    profile TEXT NOT NULL,
                    input_kind TEXT NOT NULL,
                    approved_script_revision INTEGER);
                CREATE TABLE IF NOT EXISTS project_artifact_versions (
                    job_id INTEGER NOT NULL REFERENCES jobs(id),
                    kind TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    document TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    PRIMARY KEY(job_id,kind,revision));
                CREATE TABLE IF NOT EXISTS project_approval_events (
                    job_id INTEGER NOT NULL REFERENCES jobs(id),
                    project_revision INTEGER NOT NULL,
                    script_revision INTEGER NOT NULL,
                    approved_at REAL NOT NULL,
                    PRIMARY KEY(job_id,project_revision));
                CREATE TABLE IF NOT EXISTS project_artifact_dependencies (
                    job_id INTEGER NOT NULL,
                    kind TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    script_revision INTEGER NOT NULL,
                    PRIMARY KEY(job_id,kind,revision));
                CREATE TABLE IF NOT EXISTS project_artifact_contract_metadata (
                    job_id INTEGER NOT NULL,
                    kind TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    contract_version TEXT NOT NULL,
                    migration_report TEXT,
                    PRIMARY KEY(job_id,kind,revision));
                CREATE TABLE IF NOT EXISTS project_source_media (
                    job_id INTEGER NOT NULL,
                    media_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    relative_path TEXT NOT NULL,
                    metadata TEXT NOT NULL,
                    PRIMARY KEY(job_id,media_id));
                CREATE TABLE IF NOT EXISTS project_media_derivatives (
                    job_id INTEGER NOT NULL,
                    media_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    relative_path TEXT NOT NULL,
                    metadata TEXT NOT NULL,
                    PRIMARY KEY(job_id,media_id,kind));
                CREATE TABLE IF NOT EXISTS project_assets (
                    job_id INTEGER NOT NULL,
                    asset_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    relative_path TEXT NOT NULL,
                    metadata TEXT NOT NULL,
                    PRIMARY KEY(job_id,asset_id));
                CREATE TABLE IF NOT EXISTS project_edit_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id INTEGER NOT NULL REFERENCES jobs(id),
                    operation TEXT NOT NULL,
                    artifact_kind TEXT NOT NULL,
                    before_document TEXT NOT NULL,
                    after_document TEXT NOT NULL,
                    applied_revision INTEGER NOT NULL,
                    undone INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS project_archives (
                    job_id INTEGER PRIMARY KEY REFERENCES jobs(id),
                    archived_at REAL NOT NULL);
            """)
            store.conn.commit()
        from atme.source_timeline import SourceTimeline
        self.source_timeline = SourceTimeline(self)
        from atme.project_runner import ProjectRunner
        self.runner = ProjectRunner(self)
        from atme.project_timing import ProjectTiming
        self.timing = ProjectTiming(self)
        from atme.revision_requests import RevisionRequests
        self.revisions = RevisionRequests(self)

    @staticmethod
    def capabilities():
        return {"schema_version": "1", "api_keys_required": False,
                "visual_contracts": {
                    "authoring_versions": ["1", "2.0.0"],
                    "renderer_versions": ["1"],
                    "active_renderer_version": "1",
                    "v2_render_status": "implementation_pending",
                },
                "artifact_kinds": ["brief", "script", "storyboard", "layout"],
                "output_profiles": list(PROFILES),
                "operations": ["create_project", "open_project", "list_projects", "duplicate_project", "archive_project",
                               "get_schema", "write_artifact", "get_artifact", "approve_script",
                               "migrate_visual_contracts_v1",
                               "list_media", "get_narrative_source", "validate_project", "preview_project",
                               "prepare_timing", "get_timing_status", "create_revision_request",
                               "list_revision_requests", "apply_revision_request", "submit_revision_proposal", "decide_revision_proposal",
                               "set_output_profile", "list_assets", "read_asset",
                               "get_source_timeline", "edit_source_timeline", "remove_source",
                               "get_media_analysis", "get_video_thumbnail", "create_playback_ticket",
                               "render_project", "get_render_status"],
                "collaboration": {"bounded_revision_requests": True,
                                  "user_request_can_apply_directly": True,
                                  "optional_proposal_review": True},
                "local_upload": {"formats": ["pcm_wav", "mp4", "mov", "mkv", "webm"],
                                 "audio_max_bytes": 67108864, "video_max_bytes": 1073741824,
                                 "transport": "authenticated_http"},
                "supporting_assets": {"max_bytes": 268435456, "narrative_authority": False},
                "semantic_authority": {
                    "script_authority": "approved_external_script",
                    "recording_authority": "user_recording",
                    "derived_recording_transcript": "connected_ai_non_authoritative_index"},
                "technical_timing": {"provider": "local_acoustic_alignment",
                                     "pre_layout_operation": True},
                "render_available": True, "mcp_available": True,
                "mcp_transport": "stdio", "mcp_connection_status": "live_desktop_bridge",
                "optional_decision_service": {
                    "provider": "typesafe_jev", "required": False,
                    "operations": ["visual_treatment", "revision_route", "scene_density"],
                    "writes_project": False,
                }}

    def change_version(self):
        """Small deterministic fingerprint used by the studio sync poll."""
        with self.store._lock:
            rows = self.store.conn.execute(
                "SELECT job_id,revision FROM project_state ORDER BY job_id").fetchall()
        return "|".join(f"{row['job_id']}:{row['revision']}" for row in rows)

    @staticmethod
    def schema(kind, version="1"):
        if kind == "brief":
            if version != "1":
                raise ProjectError("unsupported_schema_version", "Brief supports schema version 1")
            return deepcopy(BRIEF_SCHEMA)
        files = {
            ("script", "1"): "script-scenes",
            ("storyboard", "1"): "visual-plan",
            ("layout", "1"): "excalidraw-layout",
            ("storyboard", "2.0.0"): "visual-plan-v2",
            ("layout", "2.0.0"): "executable-layout-v2",
            ("resolved_timeline", "2.0.0"): "resolved-visual-timeline-v2",
            ("migration_report", "2.0.0"): "migration-report-v2",
        }
        if (kind, version) in files:
            return json.loads(resource_path("schemas", files[(kind, version)] + ".schema.json").read_text(encoding="utf-8"))
        raise ProjectError("unsupported_schema_version",
                           f"No {kind!r} contract is available for version {version!r}")

    def _row(self, project_id):
        row = self.store.conn.execute("SELECT * FROM project_state WHERE job_id=?", (project_id,)).fetchone()
        if row is None:
            raise ProjectError("not_found", "Project does not exist in the project service")
        return row

    @staticmethod
    def _expected(row, expected_revision):
        if type(expected_revision) is not int or row["revision"] != expected_revision:
            raise ProjectError("revision_conflict", "Project changed; reload before writing")

    def create(self, title, profile, input_kind):
        if not isinstance(title, str) or not title.strip() or len(title) > 300:
            raise ProjectError("invalid_project", "A title of 1–300 characters is required")
        if profile not in PROFILES or input_kind not in INPUT_KINDS:
            raise ProjectError("invalid_project", "Unsupported output profile or input kind")
        with self.store._lock:
            conn = self.store.conn
            try:
                # Transitional renderer safety: unfinished projects must never fall into
                # the old fake cognitive branch while the service replaces orchestration.
                settings = {"provider": "external", "voice": "upload", "review_gate": True,
                            "project_service": True}
                cur = conn.execute(
                    "INSERT INTO jobs(created_at,topic,title,status,settings_json) VALUES(?,?,?,?,?)",
                    (time.time(), title.strip(), title.strip(), "draft", json.dumps(settings)))
                project_id = cur.lastrowid
                conn.execute("INSERT INTO project_state(job_id,profile,input_kind) VALUES(?,?,?)",
                             (project_id, profile, input_kind))
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            return self.open(project_id)

    def open(self, project_id):
        with self.store._lock:
            row = self._row(project_id)
            artifacts = self.store.conn.execute(
                "SELECT kind,MAX(revision) AS revision FROM project_artifact_versions "
                "WHERE job_id=? GROUP BY kind", (project_id,)).fetchall()
            job = self.store.get_job(project_id)
            from atme.narrative_source import describe
            source = describe(self, project_id)
            result = {"project_id": project_id, "title": job["title"], "revision": row["revision"],
                    "profile": row["profile"], "input_kind": row["input_kind"],
                    "approved_script_revision": row["approved_script_revision"],
                    "artifacts": {a["kind"]: a["revision"] for a in artifacts},
                    "status": ("narrative_ready" if source["ready_for_planning"] else
                               "script_approved" if row["approved_script_revision"] is not None else "draft"),
                    "authoritative_narrative_source": source,
                    "source_timeline": {key: value for key, value in self.source_timeline.get(project_id).items()
                                        if key != "document"},
                    "render_ready": False}
            result["render_ready"] = self.runner.validate(project_id)["ready"]
            return result

    def list(self, limit=50, before_id=None):
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ProjectError("invalid_request", "Limit must be between 1 and 100")
        if before_id is not None and (type(before_id) is not int or before_id < 1):
            raise ProjectError("invalid_request", "before_id must be a positive integer")
        with self.store._lock:
            ids = self.store.conn.execute(
                "SELECT s.job_id FROM project_state s LEFT JOIN project_archives a ON a.job_id=s.job_id "
                "WHERE a.job_id IS NULL AND (? IS NULL OR s.job_id < ?) ORDER BY s.job_id DESC LIMIT ?",
                (before_id, before_id, limit)).fetchall()
            return [self.open(row["job_id"]) for row in ids]

    def archive(self, project_id, expected_revision, confirmed):
        if confirmed is not True:
            raise ProjectError("confirmation_required", "Confirm that you want to remove this project from ATME")
        with self.store._lock:
            conn = self.store.conn
            try:
                conn.execute("BEGIN IMMEDIATE")
                row = self._row(project_id); self._expected(row, expected_revision)
                conn.execute("INSERT OR REPLACE INTO project_archives(job_id,archived_at) VALUES(?,?)",
                             (project_id, time.time()))
                conn.commit()
            except Exception:
                conn.rollback(); raise
        return {"project_id": project_id, "archived": True, "files_retained": True}

    def duplicate(self, project_id):
        """Clone project metadata and immutable production inputs, never source bytes.

        Managed media and asset paths are immutable and may safely be shared by two
        project records.  Later revisions are keyed by the new project ID, so the
        copy immediately diverges without modifying the original.
        """
        with self.store._lock:
            conn = self.store.conn
            try:
                conn.execute("BEGIN IMMEDIATE")
                state = self._row(project_id)
                job = conn.execute("SELECT * FROM jobs WHERE id=?", (project_id,)).fetchone()
                title = (job["title"] or "Untitled project") + " copy"
                cursor = conn.execute(
                    "INSERT INTO jobs(created_at,topic,title,status,settings_json) VALUES(?,?,?,?,?)",
                    (time.time(), job["topic"], title, "draft", job["settings_json"]),
                )
                copy_id = cursor.lastrowid
                conn.execute(
                    "INSERT INTO project_state(job_id,revision,profile,input_kind,approved_script_revision) "
                    "VALUES(?,?,?,?,?)",
                    (copy_id, state["revision"], state["profile"], state["input_kind"],
                     state["approved_script_revision"]),
                )
                copies = (
                    ("project_artifact_versions", "kind,revision,document,created_at"),
                    ("project_approval_events", "project_revision,script_revision,approved_at"),
                    ("project_artifact_dependencies", "kind,revision,script_revision"),
                    ("project_artifact_contract_metadata", "kind,revision,contract_version,migration_report"),
                    ("project_source_media", "media_id,revision,relative_path,metadata"),
                    ("project_media_derivatives", "media_id,kind,relative_path,metadata"),
                    ("project_assets", "asset_id,revision,relative_path,metadata"),
                    ("project_source_timeline_versions", "timeline_revision,project_revision,document,operation,created_at"),
                    ("project_source_timeline_state", "current_timeline_revision"),
                    ("project_media_removals", "media_id,project_revision,created_at"),
                    ("project_timeline_dependencies", "kind,artifact_revision,timeline_revision"),
                )
                for table, columns in copies:
                    conn.execute(
                        f"INSERT INTO {table}(job_id,{columns}) "
                        f"SELECT ?,{columns} FROM {table} WHERE job_id=?",
                        (copy_id, project_id),
                    )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return self.open(copy_id)

    def _serialized_artifact(self, kind, document):
        version = document.get("contract_version", "1") if isinstance(document, dict) else "1"
        schema = self.schema(kind, version)
        try:
            serialized = json.dumps(document, ensure_ascii=False, allow_nan=False)
        except (ValueError, TypeError) as exc:
            raise ProjectError("invalid_artifact", "Artifact must be finite JSON") from exc
        if len(serialized.encode("utf-8")) > 1024 * 1024:
            raise ProjectError("too_large", "Artifact exceeds 1 MiB")
        errors = [{"path": "/" + "/".join(map(str, e.absolute_path)), "message": e.message}
                  for e in Draft202012Validator(schema).iter_errors(document)]
        if not errors and kind == "script":
            ids = [s["scene_id"] for s in document["scenes"]]
            if len(ids) != len(set(ids)):
                errors.append({"path": "/scenes", "message": "scene_id values must be unique"})
        if not errors and version == "2.0.0":
            try:
                if kind == "storyboard":
                    from atme.store.contracts_v2 import VisualPlanV2
                    VisualPlanV2.model_validate(document)
                elif kind == "layout":
                    from atme.store.contracts_v2 import ExecutableLayoutV2
                    ExecutableLayoutV2.model_validate(document)
            except ValueError as exc:
                errors.append({"path": "/", "message": str(exc)})
        if errors:
            raise ProjectError("invalid_artifact", "Schema validation failed", errors[:50])
        return serialized

    def _write_transaction(self, conn, project_id, kind, document, serialized, row):
        revision = row["revision"] + 1
        if kind in ("storyboard", "layout"):
            script = self.artifact(project_id, "script")
            version = document.get("contract_version", "1")
            if version == "2.0.0":
                if document["project_id"] != project_id or document["project_revision"] != row["revision"]:
                    raise ProjectError("stale_contract_basis",
                                       "V2 artifact project identity/revision does not match the write basis")
                expected_profile = {
                    "LONG_FORM_16_9": {"profile_id": "LONG_FORM_16_9", "width": 1280, "height": 720, "fps": 30},
                    "SHORT_FORM_9_16": {"profile_id": "SHORT_FORM_9_16", "width": 720, "height": 1280, "fps": 30},
                }[row["profile"]]
                if document["output_profile"] != expected_profile:
                    raise ProjectError("stale_contract_basis", "V2 artifact output profile is stale")
                from atme.narrative_source import describe
                source = describe(self, project_id)
                media_info = source["timing_authority"].get("media")
                timeline = self.source_timeline.get(project_id)
                timeline_fingerprint = hashlib.sha256(json.dumps(
                    timeline["document"], sort_keys=True, separators=(",", ":"),
                    ensure_ascii=False).encode()).hexdigest()
                authority = (document["narrative_authority"] if kind == "storyboard"
                             else self.artifact(project_id, "storyboard")["document"]["narrative_authority"])
                if (not media_info or authority["timing_media_id"] != media_info["media_id"]
                        or authority["timing_media_sha256"] != media_info["sha256"]
                        or authority["cleaned_timeline_revision"] != timeline["timeline_revision"]
                        or authority["cleaned_timeline_fingerprint"] != timeline_fingerprint):
                    raise ProjectError("stale_contract_basis",
                                       "V2 artifact must reference the current cleaned authoritative timing source")
                if kind == "layout":
                    storyboard = self.artifact(project_id, "storyboard")
                    plan = storyboard["document"]
                    if (plan.get("contract_version") != "2.0.0"
                            or document["plan_id"] != plan["plan_id"]
                            or document["plan_revision"] != storyboard["revision"]):
                        raise ProjectError("stale_contract_basis",
                                           "Executable layout must reference the current v2 visual plan")
                    digest = hashlib.sha256(json.dumps(plan, sort_keys=True,
                        separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
                    if document["plan_sha256"] != digest:
                        raise ProjectError("stale_contract_basis", "Executable layout plan hash is stale")
                    if (document["output_profile"] != plan["output_profile"]
                            or document["style_system_version"] != plan["style_system_version"]
                            or document["asset_registry_version"] != plan["asset_registry_version"]):
                        raise ProjectError("stale_contract_basis",
                                           "Executable layout profile/style/asset basis differs from its plan")
                    from atme.store.contracts_v2 import validate_plan_layout
                    try:
                        validate_plan_layout(plan, document)
                    except ValueError as exc:
                        raise ProjectError("invalid_artifact",
                                           "Executable layout does not preserve semantic-plan intent",
                                           [{"path": "/", "message": str(exc)}]) from exc
            elif kind == "layout":
                from atme.external_inputs import validate_external_inputs
                try:
                    validate_external_inputs(script["document"], document)
                except (ValueError, TypeError, KeyError) as exc:
                    raise ProjectError("invalid_artifact", "Layout fails script/board validation",
                                       [{"path": "/", "message": str(exc)}]) from exc
            elif kind == "storyboard":
                scenes = {s["scene_id"]: s["spoken_text"] for s in script["document"]["scenes"]}
                if ({b["scene_id"] for b in document["beats"]} != set(scenes)
                        or any(b["narration"] != scenes[b["scene_id"]] for b in document["beats"])):
                    raise ProjectError("invalid_artifact", "Storyboard must reference every current script scene and preserve its narration")
            conn.execute("INSERT INTO project_artifact_dependencies VALUES(?,?,?,?)",
                         (project_id, kind, revision, script["revision"]))
            timeline_revision = self.source_timeline.get(project_id)["timeline_revision"]
            conn.execute("INSERT INTO project_timeline_dependencies VALUES(?,?,?,?)",
                         (project_id, kind, revision, timeline_revision))
        conn.execute("INSERT INTO project_artifact_versions VALUES(?,?,?,?,?)",
                     (project_id, kind, revision, serialized, time.time()))
        conn.execute("INSERT INTO project_artifact_contract_metadata VALUES(?,?,?,?,NULL)",
                     (project_id, kind, revision, document.get("contract_version", "1")))
        if kind in ("brief", "script"):
            conn.execute("UPDATE project_state SET revision=?,approved_script_revision=NULL WHERE job_id=?",
                         (revision, project_id))
        else:
            conn.execute("UPDATE project_state SET revision=? WHERE job_id=?", (revision, project_id))
        return revision

    def write(self, project_id, kind, document, expected_revision):
        serialized = self._serialized_artifact(kind, document)
        with self.store._lock:
            conn = self.store.conn
            try:
                conn.execute("BEGIN IMMEDIATE")
                row = self._row(project_id)
                self._expected(row, expected_revision)
                self._write_transaction(conn, project_id, kind, document, serialized, row)
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            return self.open(project_id)

    def migrate_visual_contracts_v1(self, project_id, expected_revision):
        """Create immutable v2 storyboard/layout revisions while retaining v1 history."""
        with self.store._lock:
            conn = self.store.conn
            try:
                conn.execute("BEGIN IMMEDIATE")
                row = self._row(project_id)
                self._expected(row, expected_revision)
                visual = self.artifact(project_id, "storyboard")
                layout = self.artifact(project_id, "layout")
                if (visual["document"].get("contract_version") != "1"
                        or layout["document"].get("contract_version") != "1"):
                    raise ProjectError("migration_not_applicable", "Only v1 visual artifacts can be migrated")
                from atme.narrative_source import describe
                source = describe(self, project_id)
                timing = source["timing_authority"]
                media_info = timing.get("media")
                if not media_info or not media_info.get("sha256"):
                    raise ProjectError("migration_basis_missing",
                                       "A cleaned authoritative timing source is required before migration")
                profile = {"LONG_FORM_16_9": (1280, 720), "SHORT_FORM_9_16": (720, 1280)}[row["profile"]]
                timeline = self.source_timeline.get(project_id)
                timeline_fingerprint = hashlib.sha256(json.dumps(
                    timeline["document"], sort_keys=True, separators=(",", ":"),
                    ensure_ascii=False).encode()).hexdigest()
                authority = {
                    "mode": "approved_script_plus_recording" if source["mode"] == "script_authority" else "recording_only",
                    "authority_id": (f"script-revision-{source['semantic_structure']['revision']}"
                                     if source["mode"] == "script_authority" else media_info["media_id"]),
                    "timing_media_id": media_info["media_id"],
                    "timing_media_sha256": media_info["sha256"],
                    "cleaned_timeline_revision": timeline["timeline_revision"],
                    "cleaned_timeline_fingerprint": timeline_fingerprint,
                }
                from atme.store.migrate_visual_v1 import migrate_visual_bundle_v1
                migrated = migrate_visual_bundle_v1(
                    visual["document"], layout["document"], project_id=project_id,
                    project_revision=row["revision"], plan_revision=visual["revision"],
                    layout_revision=layout["revision"], narrative_authority=authority,
                    output_profile={"profile_id": row["profile"], "width": profile[0],
                                    "height": profile[1], "fps": 30})
                plan_doc = migrated["visual_plan"]
                plan_serialized = self._serialized_artifact("storyboard", plan_doc)
                plan_revision = self._write_transaction(conn, project_id, "storyboard", plan_doc,
                                                        plan_serialized, row)
                next_row = self._row(project_id)
                layout_doc = migrated["executable_layout"]
                if layout_doc["plan_revision"] != plan_revision:
                    raise ProjectError("migration_failed", "Migration revision calculation was not deterministic")
                layout_serialized = self._serialized_artifact("layout", layout_doc)
                layout_revision = self._write_transaction(conn, project_id, "layout", layout_doc,
                                                          layout_serialized, next_row)
                report_json = json.dumps(migrated["migration_report"], ensure_ascii=False, allow_nan=False)
                conn.execute("UPDATE project_artifact_contract_metadata SET migration_report=? "
                             "WHERE job_id=? AND ((kind='storyboard' AND revision=?) OR "
                             "(kind='layout' AND revision=?))",
                             (report_json, project_id, plan_revision, layout_revision))
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return {"project": self.open(project_id), "storyboard_revision": plan_revision,
                "layout_revision": layout_revision, "migration_report": migrated["migration_report"]}

    def edit(self, project_id, operation, kind, document, expected_revision):
        if operation not in ("cut", "delete", "move", "trim", "edit"):
            raise ProjectError("invalid_edit", "Unsupported editor operation")
        if kind not in ("script", "layout"):
            raise ProjectError("invalid_edit", "Editor changes support script and layout artifacts")
        serialized = self._serialized_artifact(kind, document)
        with self.store._lock:
            conn = self.store.conn
            try:
                conn.execute("BEGIN IMMEDIATE")
                row = self._row(project_id)
                self._expected(row, expected_revision)
                before = self.artifact(project_id, kind)["document"]
                before_serialized = json.dumps(before, ensure_ascii=False, allow_nan=False)
                revision = self._write_transaction(conn, project_id, kind, document, serialized, row)
                conn.execute("DELETE FROM project_edit_events WHERE job_id=? AND undone=1", (project_id,))
                conn.execute("INSERT INTO project_edit_events(job_id,operation,artifact_kind,before_document,"
                             "after_document,applied_revision,created_at) VALUES(?,?,?,?,?,?,?)",
                             (project_id, operation, kind, before_serialized, serialized, revision, time.time()))
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return {"project": self.open(project_id), "history": self.edit_state(project_id)}

    def edit_state(self, project_id):
        with self.store._lock:
            self._row(project_id)
            undo = self.store.conn.execute(
                "SELECT operation FROM project_edit_events WHERE job_id=? AND undone=0 ORDER BY event_id DESC LIMIT 1",
                (project_id,)).fetchone()
            redo = self.store.conn.execute(
                "SELECT operation FROM project_edit_events WHERE job_id=? AND undone=1 ORDER BY event_id ASC LIMIT 1",
                (project_id,)).fetchone()
        return {"can_undo": undo is not None, "can_redo": redo is not None,
                "undo_label": undo["operation"] if undo else None,
                "redo_label": redo["operation"] if redo else None}

    def _history_action(self, project_id, expected_revision, redo):
        order = "ASC" if redo else "DESC"
        undone = 1 if redo else 0
        with self.store._lock:
            conn = self.store.conn
            try:
                conn.execute("BEGIN IMMEDIATE")
                row = self._row(project_id)
                self._expected(row, expected_revision)
                event = conn.execute(
                    f"SELECT * FROM project_edit_events WHERE job_id=? AND undone=? ORDER BY event_id {order} LIMIT 1",
                    (project_id, undone)).fetchone()
                if event is None:
                    raise ProjectError("edit_history_empty", "Nothing to redo" if redo else "Nothing to undo")
                document = json.loads(event["after_document"] if redo else event["before_document"])
                serialized = self._serialized_artifact(event["artifact_kind"], document)
                self._write_transaction(conn, project_id, event["artifact_kind"], document, serialized, row)
                conn.execute("UPDATE project_edit_events SET undone=? WHERE event_id=?",
                             (0 if redo else 1, event["event_id"]))
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return {"project": self.open(project_id), "history": self.edit_state(project_id)}

    def undo(self, project_id, expected_revision):
        return self._history_action(project_id, expected_revision, False)

    def redo(self, project_id, expected_revision):
        return self._history_action(project_id, expected_revision, True)

    def artifact(self, project_id, kind, revision=None):
        if kind not in ("brief", "script", "storyboard", "layout"):
            raise ProjectError("unsupported_artifact", "Supported artifacts: brief, script, storyboard, layout")
        with self.store._lock:
            self._row(project_id)
            query = "SELECT revision,document FROM project_artifact_versions WHERE job_id=? AND kind=?"
            params = [project_id, kind]
            if revision is not None:
                query += " AND revision=?"
                params.append(revision)
            row = self.store.conn.execute(query + " ORDER BY revision DESC LIMIT 1", params).fetchone()
            if row is None:
                raise ProjectError("not_found", "Artifact revision does not exist")
            result = {"kind": kind, "revision": row["revision"], "document": json.loads(row["document"])}
            metadata = self.store.conn.execute(
                "SELECT contract_version,migration_report FROM project_artifact_contract_metadata "
                "WHERE job_id=? AND kind=? AND revision=?", (project_id, kind, row["revision"])).fetchone()
            result["contract_version"] = (metadata["contract_version"] if metadata else
                                          result["document"].get("contract_version", "1"))
            if metadata and metadata["migration_report"]:
                result["migration_report"] = json.loads(metadata["migration_report"])
            dependency = self.store.conn.execute(
                "SELECT script_revision FROM project_artifact_dependencies WHERE job_id=? AND kind=? AND revision=?",
                (project_id, kind, row["revision"])).fetchone()
            if dependency is not None:
                result["basis_script_revision"] = dependency["script_revision"]
                latest = self.store.conn.execute(
                    "SELECT MAX(revision) FROM project_artifact_versions WHERE job_id=? AND kind='script'",
                    (project_id,)).fetchone()[0]
                result["stale"] = latest != dependency["script_revision"]
            timeline_dependency = self.store.conn.execute(
                "SELECT timeline_revision FROM project_timeline_dependencies WHERE job_id=? AND kind=? AND artifact_revision=?",
                (project_id, kind, row["revision"])).fetchone()
            if timeline_dependency is not None:
                result["basis_timeline_revision"] = timeline_dependency["timeline_revision"]
                # Timeline edits are normal editor state. Artifact timings remain
                # attached to the project and are transformed at preview/render
                # time; moving or trimming a clip must not invalidate the edit.
            return result

    def list_media(self, project_id):
        with self.store._lock:
            self._row(project_id)
            rows = self.store.conn.execute(
                "SELECT m.metadata,m.revision FROM project_source_media m LEFT JOIN project_media_removals r "
                "ON r.job_id=m.job_id AND r.media_id=m.media_id WHERE m.job_id=? AND r.media_id IS NULL ORDER BY m.revision",
                (project_id,)).fetchall()
            return [{**json.loads(row["metadata"]), "revision": row["revision"]} for row in rows]

    def source_timeline_state(self, project_id):
        return self.source_timeline.get(project_id)

    def edit_source_timeline(self, project_id, operation, arguments, expected_revision,
                             expected_timeline_revision):
        return self.source_timeline.command(project_id, operation, arguments, expected_revision,
                                            expected_timeline_revision)

    def undo_source_timeline(self, project_id, expected_revision):
        return self.source_timeline.history_action(project_id, expected_revision, False)

    def redo_source_timeline(self, project_id, expected_revision):
        return self.source_timeline.history_action(project_id, expected_revision, True)

    def source_removal_impact(self, project_id, media_id):
        return self.source_timeline.removal_impact(project_id, media_id)

    def remove_source(self, project_id, media_id, expected_revision, confirmed):
        return self.source_timeline.remove_source(project_id, media_id, expected_revision, confirmed)

    def media_waveform(self, project_id, media_id, resolution_ms):
        from atme.media_analysis import waveform
        return waveform(self, project_id, media_id, resolution_ms)

    def video_thumbnail(self, project_id, media_id, at_ms, width):
        from atme.media_analysis import thumbnail
        return thumbnail(self, project_id, media_id, at_ms, width)

    def playback_ticket(self, project_id, expected_revision, media_id=None, cleaned=False):
        from atme.media_delivery import create_ticket
        return create_ticket(self, project_id, expected_revision, media_id, cleaned)

    def attach_wav(self, project_id, payload, expected_revision, filename="Narration.wav"):
        from atme.project_media import attach_wav
        return attach_wav(self, project_id, payload, expected_revision, filename)

    def attach_video_file(self, project_id, staged_file, filename, expected_revision):
        from atme.project_media import attach_video_file
        return attach_video_file(self, project_id, staged_file, filename, expected_revision)

    def attach_asset_file(self, project_id, staged_file, filename, expected_revision):
        from atme.project_assets import attach_asset_file
        return attach_asset_file(self, project_id, staged_file, filename, expected_revision)

    def list_assets(self, project_id):
        from atme.project_assets import list_assets
        return list_assets(self, project_id)

    def asset(self, project_id, asset_id, max_bytes=None):
        from atme.project_assets import read_asset
        return read_asset(self, project_id, asset_id, max_bytes)

    def approve_script(self, project_id, script_revision, expected_revision, approved):
        if approved is not True:
            raise ProjectError("approval_required", "Explicit user approval is required")
        from atme.narrative_source import RECORDING_AUTHORITY_KINDS
        with self.store._lock:
            if self._row(project_id)["input_kind"] in RECORDING_AUTHORITY_KINDS:
                raise ProjectError("approval_not_applicable",
                                   "Recording-authority projects do not promote a derived transcript to narrative authority")
        with self.store._lock:
            conn = self.store.conn
            try:
                conn.execute("BEGIN IMMEDIATE")
                row = self._row(project_id)
                self._expected(row, expected_revision)
                current = self.artifact(project_id, "script")
                if type(script_revision) is not int or current["revision"] != script_revision:
                    raise ProjectError("revision_conflict", "Only the current script revision can be approved")
                conn.execute("UPDATE project_state SET revision=revision+1,approved_script_revision=? WHERE job_id=?",
                             (script_revision, project_id))
                conn.execute("INSERT INTO project_approval_events VALUES(?,?,?,?)",
                             (project_id, row["revision"] + 1, script_revision, time.time()))
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            return self.open(project_id)

    def validate_project(self, project_id):
        return self.runner.validate(project_id)

    def set_profile(self, project_id, profile, expected_revision):
        if profile not in PROFILES:
            raise ProjectError("invalid_project", "Unsupported output profile")
        with self.store._lock:
            conn = self.store.conn
            try:
                conn.execute("BEGIN IMMEDIATE")
                row = self._row(project_id)
                self._expected(row, expected_revision)
                conn.execute("UPDATE project_state SET profile=?,revision=revision+1 WHERE job_id=?",
                             (profile, project_id))
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return self.open(project_id)

    def narrative_source(self, project_id):
        from atme.narrative_source import describe
        return describe(self, project_id)

    def authoritative_media(self, project_id, max_bytes=None):
        from atme.narrative_source import read_authoritative_media
        return read_authoritative_media(self, project_id, max_bytes)

    def authoritative_audio(self, project_id):
        from atme.narrative_source import read_authoritative_audio
        return read_authoritative_audio(self, project_id)

    def render_project(self, project_id, expected_revision, confirmed):
        return self.runner.request_render(project_id, expected_revision, confirmed)

    def preview_project(self, project_id, expected_revision, at_ms):
        return self.runner.preview(project_id, expected_revision, at_ms)

    def prepare_timing(self, project_id, expected_revision):
        return self.timing.request(project_id, expected_revision)

    def timing_status(self, project_id, run_id):
        return self.timing.status(project_id, run_id)

    def render_status(self, project_id, run_id):
        return self.runner.status(project_id, run_id)

    def list_render_runs(self, project_id):
        return self.runner.list_runs(project_id)

    def create_revision_request(self, project_id, expected_revision, selection, instruction):
        return self.revisions.create(project_id, expected_revision, selection, instruction)

    def list_revision_requests(self, project_id, status=None):
        return self.revisions.list(project_id, status)

    def submit_revision_proposal(self, project_id, request_id, expected_revision,
                                 artifact_kind, document, summary):
        return self.revisions.propose(project_id, request_id, expected_revision,
                                      artifact_kind, document, summary)

    def apply_revision_request(self, project_id, request_id, expected_revision,
                               artifact_kind, document, summary):
        return self.revisions.apply_requested(project_id, request_id, expected_revision,
                                              artifact_kind, document, summary)

    def decide_revision_proposal(self, project_id, request_id, expected_revision, accepted):
        return self.revisions.decide(project_id, request_id, expected_revision, accepted)

    def preview_revision_proposal(self, project_id, request_id, expected_revision, at_ms):
        return self.revisions.preview(project_id, request_id, expected_revision, at_ms)
