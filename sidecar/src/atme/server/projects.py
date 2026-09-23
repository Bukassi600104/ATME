"""Bounded HTTP adapter; project rules live in ProjectService, not transport code."""
import json
from uuid import uuid4

from fastapi import Depends, Header, HTTPException, Request, Response
from fastapi.responses import FileResponse

from atme.mcp_activity import McpActivity
from atme.media_delivery import ticket_response
from atme.project_service import ProjectError, ProjectService


def register_projects(app, store, auth):
    service = ProjectService(store)
    activity = McpActivity(store)

    def call(operation, *args):
        try:
            return operation(*args)
        except ProjectError as exc:
            status = {"not_found": 404, "revision_conflict": 409, "too_large": 413}.get(exc.code, 400)
            raise HTTPException(status, exc.detail()) from exc

    async def body(request, fields):
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > 1024 * 1024:
                raise HTTPException(413, {"code": "too_large", "message": "Request exceeds 1 MiB"})
        try:
            value = json.loads(raw)
        except (ValueError, UnicodeError):
            raise HTTPException(400, {"code": "invalid_json", "message": "JSON object required"})
        if not isinstance(value, dict) or set(value) != set(fields):
            raise HTTPException(400, {"code": "invalid_request", "message": "Required fields: " + ", ".join(fields)})
        return value

    @app.get("/projects/capabilities", dependencies=[Depends(auth)])
    def capabilities():
        return service.capabilities()

    @app.get("/studio/sync", dependencies=[Depends(auth)])
    def studio_sync():
        live = getattr(app.state, "live_mcp", None)
        return {"project_version": service.change_version(),
                "mcp": live.snapshot() if live is not None else activity.snapshot()}

    @app.get("/studio/mcp/wait", dependencies=[Depends(auth)])
    def wait_for_mcp(after: int = 0):
        live = getattr(app.state, "live_mcp", None)
        if live is None:
            return activity.snapshot()
        return live.wait(max(0, after))

    @app.get("/projects/schemas/{kind}", dependencies=[Depends(auth)])
    def schema(kind: str, version: str = "1"):
        return call(service.schema, kind, version)

    @app.get("/projects", dependencies=[Depends(auth)])
    def list_projects():
        return {"projects": service.list()}

    @app.post("/projects", dependencies=[Depends(auth)])
    async def create(request: Request):
        value = await body(request, ("title", "profile", "input_kind"))
        return call(service.create, value["title"], value["profile"], value["input_kind"])

    @app.get("/projects/{project_id}", dependencies=[Depends(auth)])
    def open_project(project_id: int):
        return call(service.open, project_id)

    @app.post("/projects/{project_id}/duplicate", dependencies=[Depends(auth)])
    def duplicate_project(project_id: int):
        return call(service.duplicate, project_id)

    @app.post("/projects/{project_id}/archive", dependencies=[Depends(auth)])
    async def archive_project(project_id: int, request: Request):
        value = await body(request, ("expected_revision", "confirmed"))
        return call(service.archive, project_id, value["expected_revision"], value["confirmed"])

    @app.post("/projects/{project_id}/migrate-visual-contracts-v1", dependencies=[Depends(auth)])
    async def migrate_visual_contracts_v1(project_id: int, request: Request):
        value = await body(request, ("expected_revision",))
        return call(service.migrate_visual_contracts_v1, project_id, value["expected_revision"])

    @app.put("/projects/{project_id}/profile", dependencies=[Depends(auth)])
    async def set_profile(project_id: int, request: Request):
        value = await body(request, ("profile", "expected_revision"))
        return call(service.set_profile, project_id, value["profile"], value["expected_revision"])

    @app.get("/projects/{project_id}/artifacts/{kind}", dependencies=[Depends(auth)])
    def get_artifact(project_id: int, kind: str, revision: int | None = None):
        return call(service.artifact, project_id, kind, revision)

    @app.put("/projects/{project_id}/artifacts/{kind}", dependencies=[Depends(auth)])
    async def write(project_id: int, kind: str, request: Request):
        value = await body(request, ("document", "expected_revision"))
        return call(service.write, project_id, kind, value["document"], value["expected_revision"])

    @app.get("/projects/{project_id}/edit-history", dependencies=[Depends(auth)])
    def edit_history(project_id: int):
        return call(service.edit_state, project_id)

    @app.post("/projects/{project_id}/edits", dependencies=[Depends(auth)])
    async def edit(project_id: int, request: Request):
        value = await body(request, ("operation", "artifact_kind", "document", "expected_revision"))
        return call(service.edit, project_id, value["operation"], value["artifact_kind"],
                    value["document"], value["expected_revision"])

    @app.post("/projects/{project_id}/undo", dependencies=[Depends(auth)])
    async def undo(project_id: int, request: Request):
        value = await body(request, ("expected_revision",))
        return call(service.undo, project_id, value["expected_revision"])

    @app.post("/projects/{project_id}/redo", dependencies=[Depends(auth)])
    async def redo(project_id: int, request: Request):
        value = await body(request, ("expected_revision",))
        return call(service.redo, project_id, value["expected_revision"])

    @app.post("/projects/{project_id}/script-approval", dependencies=[Depends(auth)])
    async def approve(project_id: int, request: Request):
        value = await body(request, ("script_revision", "expected_revision", "approved"))
        return call(service.approve_script, project_id, value["script_revision"],
                    value["expected_revision"], value["approved"])

    @app.get("/projects/{project_id}/media", dependencies=[Depends(auth)])
    def list_media(project_id: int):
        return call(service.list_media, project_id)

    @app.get("/projects/{project_id}/source-timeline", dependencies=[Depends(auth)])
    def source_timeline(project_id: int):
        return call(service.source_timeline_state, project_id)

    @app.post("/projects/{project_id}/source-timeline/commands", dependencies=[Depends(auth)])
    async def source_timeline_command(project_id: int, request: Request):
        value = await body(request, ("operation", "arguments", "expected_revision", "expected_timeline_revision"))
        return call(service.edit_source_timeline, project_id, value["operation"], value["arguments"],
                    value["expected_revision"], value["expected_timeline_revision"])

    @app.post("/projects/{project_id}/source-timeline/undo", dependencies=[Depends(auth)])
    async def source_timeline_undo(project_id: int, request: Request):
        value = await body(request, ("expected_revision",))
        return call(service.undo_source_timeline, project_id, value["expected_revision"])

    @app.post("/projects/{project_id}/source-timeline/redo", dependencies=[Depends(auth)])
    async def source_timeline_redo(project_id: int, request: Request):
        value = await body(request, ("expected_revision",))
        return call(service.redo_source_timeline, project_id, value["expected_revision"])

    @app.get("/projects/{project_id}/media/{media_id}/removal-impact", dependencies=[Depends(auth)])
    def source_removal_impact(project_id: int, media_id: str):
        return call(service.source_removal_impact, project_id, media_id)

    @app.post("/projects/{project_id}/media/{media_id}/remove", dependencies=[Depends(auth)])
    async def remove_source(project_id: int, media_id: str, request: Request):
        value = await body(request, ("expected_revision", "confirmed"))
        return call(service.remove_source, project_id, media_id, value["expected_revision"], value["confirmed"])

    @app.get("/projects/{project_id}/media/{media_id}/waveform", dependencies=[Depends(auth)])
    def source_waveform(project_id: int, media_id: str, resolution_ms: int = 40):
        return call(service.media_waveform, project_id, media_id, resolution_ms)

    @app.get("/projects/{project_id}/media/{media_id}/thumbnail", dependencies=[Depends(auth)])
    def source_thumbnail(project_id: int, media_id: str, at_ms: int, width: int = 160):
        path = call(service.video_thumbnail, project_id, media_id, at_ms, width)
        return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=31536000, immutable"})

    @app.post("/projects/{project_id}/playback-ticket", dependencies=[Depends(auth)])
    async def playback_ticket(project_id: int, request: Request):
        value = await body(request, ("expected_revision", "media_id", "cleaned"))
        return call(service.playback_ticket, project_id, value["expected_revision"],
                    value["media_id"], value["cleaned"])

    @app.get("/media-playback/{ticket}")
    def media_playback(ticket: str, request: Request):
        return ticket_response(ticket, request)

    @app.get("/projects/{project_id}/assets", dependencies=[Depends(auth)])
    def list_assets(project_id: int):
        return {"assets": call(service.list_assets, project_id)}

    @app.get("/projects/{project_id}/assets/{asset_id}/content", dependencies=[Depends(auth)])
    def asset_content(project_id: int, asset_id: str):
        path, metadata = call(service.asset, project_id, asset_id)
        return FileResponse(path, media_type=metadata["media_type"], filename=metadata["name"])

    @app.post("/projects/{project_id}/assets", dependencies=[Depends(auth)])
    async def attach_asset(project_id: int, expected_revision: int, request: Request,
                           x_filename: str = Header(default="asset")):
        from atme.project_assets import MAX_ASSET_BYTES
        length = request.headers.get("content-length")
        if length:
            try:
                if int(length) > MAX_ASSET_BYTES:
                    raise HTTPException(413, {"code": "too_large", "message": "Asset exceeds 256 MiB"})
            except ValueError as exc:
                raise HTTPException(400, {"code": "invalid_request", "message": "Invalid content-length"}) from exc
        parent = service.store.db_path.resolve().parent
        incoming = (parent / "project-assets" / ".incoming").resolve()
        if not incoming.is_relative_to(parent):
            raise HTTPException(500, {"code": "storage_error", "message": "Invalid asset storage"})
        incoming.mkdir(parents=True, exist_ok=True)
        staged = incoming / (uuid4().hex + ".part")
        received = 0
        try:
            with staged.open("xb") as output:
                async for chunk in request.stream():
                    received += len(chunk)
                    if received > MAX_ASSET_BYTES:
                        raise HTTPException(413, {"code": "too_large", "message": "Asset exceeds 256 MiB"})
                    output.write(chunk)
            return call(service.attach_asset_file, project_id, staged, x_filename, expected_revision)
        finally:
            staged.unlink(missing_ok=True)

    @app.get("/projects/{project_id}/narrative-source", dependencies=[Depends(auth)])
    def narrative_source(project_id: int):
        return call(service.narrative_source, project_id)

    @app.get("/projects/{project_id}/validate", dependencies=[Depends(auth)])
    def validate_project(project_id: int):
        return call(service.validate_project, project_id)

    @app.get("/projects/{project_id}/revision-requests", dependencies=[Depends(auth)])
    def revision_requests(project_id: int, status: str | None = None):
        return {"requests": call(service.list_revision_requests, project_id, status)}

    @app.post("/projects/{project_id}/revision-requests", dependencies=[Depends(auth)])
    async def create_revision_request(project_id: int, request: Request):
        value = await body(request, ("expected_revision", "selection", "instruction"))
        return call(service.create_revision_request, project_id, value["expected_revision"],
                    value["selection"], value["instruction"])

    @app.post("/projects/{project_id}/revision-requests/{request_id}/decision",
              dependencies=[Depends(auth)])
    async def decide_revision_request(project_id: int, request_id: str, request: Request):
        value = await body(request, ("expected_revision", "accepted"))
        return call(service.decide_revision_proposal, project_id, request_id,
                    value["expected_revision"], value["accepted"])

    @app.get("/projects/{project_id}/revision-requests/{request_id}/preview",
             dependencies=[Depends(auth)])
    def preview_revision_request(project_id: int, request_id: str, expected_revision: int, at_ms: int):
        value = call(service.preview_revision_proposal, project_id, request_id,
                     expected_revision, at_ms)
        return Response(value["png"], media_type="image/png", headers={"Cache-Control": "no-store"})

    @app.post("/projects/{project_id}/timing", dependencies=[Depends(auth)])
    async def prepare_timing(project_id: int, request: Request):
        value = await body(request, ("expected_revision",))
        return call(service.prepare_timing, project_id, value["expected_revision"])

    @app.get("/projects/{project_id}/timing/{run_id}", dependencies=[Depends(auth)])
    def timing_status(project_id: int, run_id: str):
        return call(service.timing_status, project_id, run_id)

    @app.get("/projects/{project_id}/preview", dependencies=[Depends(auth)])
    def preview(project_id: int, expected_revision: int, at_ms: int):
        value = call(service.preview_project, project_id, expected_revision, at_ms)
        return Response(value["png"], media_type="image/png", headers={
            "Cache-Control": "no-store", "X-ATME-Project-Revision": str(value["project_revision"])})

    @app.post("/projects/{project_id}/renders", dependencies=[Depends(auth)])
    async def render(project_id: int, request: Request):
        value = await body(request, ("expected_revision", "confirmed"))
        return call(service.render_project, project_id, value["expected_revision"], value["confirmed"])

    @app.get("/projects/{project_id}/renders", dependencies=[Depends(auth)])
    def list_renders(project_id: int):
        return {"renders": call(service.list_render_runs, project_id)}

    @app.get("/projects/{project_id}/renders/{run_id}", dependencies=[Depends(auth)])
    def render_status(project_id: int, run_id: str):
        return call(service.render_status, project_id, run_id)

    @app.get("/projects/{project_id}/renders/{run_id}/output", dependencies=[Depends(auth)])
    def render_output(project_id: int, run_id: str):
        return FileResponse(call(service.runner.output_path, project_id, run_id), media_type="video/mp4",
                            filename=f"ATME-{project_id}.mp4")

    @app.get("/projects/{project_id}/timeline-export", dependencies=[Depends(auth)])
    def timeline_export(project_id: int, expected_revision: int):
        state = call(service.open, project_id)
        if state["revision"] != expected_revision:
            raise HTTPException(409, {"code": "revision_conflict", "message": "Project changed; reload before exporting"})
        from atme.timeline_media import materialize_video
        path, _metadata, _timeline = materialize_video(service, project_id)
        return FileResponse(path, media_type="video/mp4", filename=f"ATME-project-{project_id}-timeline.mp4")

    @app.post("/projects/{project_id}/media/wav", dependencies=[Depends(auth)])
    async def attach_wav(project_id: int, expected_revision: int, request: Request,
                         x_filename: str = Header(default="Narration.wav")):
        from atme.project_media import MAX_MEDIA_BYTES
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > MAX_MEDIA_BYTES:
                raise HTTPException(413, {"code": "too_large", "message": "WAV exceeds 64 MiB"})
        return call(service.attach_wav, project_id, raw, expected_revision, x_filename)

    @app.post("/projects/{project_id}/media/video", dependencies=[Depends(auth)])
    async def attach_video(project_id: int, expected_revision: int, request: Request,
                           x_filename: str = Header(default="video.mp4")):
        from atme.project_media import MAX_VIDEO_BYTES
        length = request.headers.get("content-length")
        try:
            if length and int(length) > MAX_VIDEO_BYTES:
                raise HTTPException(413, {"code": "too_large", "message": "Video exceeds 1 GiB"})
        except ValueError as exc:
            raise HTTPException(400, {"code": "invalid_request", "message": "Invalid content-length"}) from exc
        parent = service.store.db_path.resolve().parent
        incoming = (parent / "project-media" / ".incoming").resolve()
        if not incoming.is_relative_to(parent):
            raise HTTPException(500, {"code": "storage_error", "message": "Invalid media storage"})
        incoming.mkdir(parents=True, exist_ok=True)
        staged = incoming / (uuid4().hex + ".part")
        received = 0
        try:
            with staged.open("xb") as output:
                async for chunk in request.stream():
                    received += len(chunk)
                    if received > MAX_VIDEO_BYTES:
                        raise HTTPException(413, {"code": "too_large", "message": "Video exceeds 1 GiB"})
                    output.write(chunk)
            return call(service.attach_video_file, project_id, staged, x_filename, expected_revision)
        finally:
            staged.unlink(missing_ok=True)

    return service
