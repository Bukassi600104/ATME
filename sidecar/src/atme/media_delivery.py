"""Short-lived, project-bound playback tickets with HTTP Range delivery."""
from __future__ import annotations

import mimetypes
import secrets
import threading
import time
from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.responses import StreamingResponse

from atme.project_media import managed_media_path
from atme.project_service import ProjectError
from atme.timeline_media import materialize_video

_lock = threading.Lock()
_tickets = {}
TICKET_TTL_SECONDS = 300


def create_ticket(service, project_id, expected_revision, media_id=None, cleaned=False):
    with service.store._lock:
        row = service._row(project_id); service._expected(row, expected_revision)
    if cleaned:
        path, metadata, timeline = materialize_video(service, project_id)
        timeline_revision = timeline["timeline_revision"]
    else:
        if not isinstance(media_id, str):
            raise ProjectError("invalid_request", "A source media ID is required")
        path, metadata, _ = managed_media_path(service, project_id, media_id)
        if metadata["kind"] != "video":
            raise ProjectError("invalid_request", "Playback tickets require video media")
        timeline_revision = None
    token = secrets.token_urlsafe(32)
    expires = time.time() + TICKET_TTL_SECONDS
    with _lock:
        now = time.time()
        for key in [key for key, value in _tickets.items() if value["expires_at"] < now]:
            _tickets.pop(key, None)
        _tickets[token] = {"path": str(path), "project_id": project_id, "project_revision": expected_revision,
                           "timeline_revision": timeline_revision, "expires_at": expires,
                           "media_type": mimetypes.guess_type(path.name)[0] or "video/mp4"}
    return {"ticket": token, "expires_at": expires, "project_revision": expected_revision,
            "timeline_revision": timeline_revision, "path": f"/media-playback/{token}"}


def ticket_response(token, request: Request):
    with _lock:
        ticket = _tickets.get(token)
    if ticket is None or ticket["expires_at"] < time.time():
        raise HTTPException(404, "Playback ticket expired")
    path = Path(ticket["path"])
    if not path.is_file():
        raise HTTPException(404, "Playback media unavailable")
    size = path.stat().st_size
    start, end, status = 0, size - 1, 200
    value = request.headers.get("range")
    if value:
        try:
            unit, span = value.split("=", 1)
            if unit != "bytes" or "," in span:
                raise ValueError
            first, last = span.split("-", 1)
            if first:
                start = int(first); end = int(last) if last else size - 1
            else:
                length = int(last); start = max(0, size - length)
            end = min(size - 1, end)
            if start < 0 or start > end:
                raise ValueError
            status = 206
        except ValueError as exc:
            raise HTTPException(416, "Invalid byte range", headers={"Content-Range": f"bytes */{size}"}) from exc
    length = end - start + 1

    def chunks():
        with path.open("rb") as handle:
            handle.seek(start); remaining = length
            while remaining:
                block = handle.read(min(1024 * 1024, remaining))
                if not block:
                    break
                remaining -= len(block); yield block

    headers = {"Accept-Ranges": "bytes", "Content-Length": str(length), "Cache-Control": "private, no-store"}
    if status == 206:
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    return StreamingResponse(chunks(), status_code=status, media_type=ticket["media_type"], headers=headers)
