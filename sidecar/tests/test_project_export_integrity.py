import hashlib
import io
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from PIL import Image

from atme.project_service import ProjectError, ProjectService
from atme.store.db import JobStore
from test_project_runner import ready_project
from test_source_timeline import place


def test_compile_rejects_project_edit_during_source_preparation(tmp_path, monkeypatch):
    from atme import narrative_source

    core, state = ready_project(tmp_path)
    other = ProjectService(JobStore(core.store.db_path))
    original = narrative_source.timing_audio
    pid = state["project_id"]

    def prepare_and_edit(service, project_id):
        result = original(service, project_id)
        other.set_profile(pid, "SHORT_FORM_9_16", state["revision"])
        return result

    monkeypatch.setattr(narrative_source, "timing_audio", prepare_and_edit)
    try:
        with pytest.raises(ProjectError) as error:
            core.runner.compile(pid, state["revision"])
        assert error.value.code == "revision_conflict"
        assert not list(tmp_path.rglob("compile_manifest.json"))
    finally:
        other.store.close()
        core.store.close()


def test_manual_export_converts_original_and_separates_profile_caches(tmp_path):
    from atme.render.animator import find_ffmpeg
    from atme.timeline_media import materialize_video

    ffmpeg = find_ffmpeg()
    source = tmp_path / "small.mkv"
    subprocess.run([ffmpeg, "-v", "error", "-f", "lavfi", "-i", "color=blue:s=160x90:r=10:d=0.4",
                    "-f", "lavfi", "-i", "sine=frequency=500:duration=0.4", "-c:v", "mpeg4",
                    "-c:a", "pcm_s16le", str(source)], check=True, timeout=60)
    core = ProjectService(JobStore(tmp_path / "projects.db"))
    pid = core.create("Manual edit", "LONG_FORM_16_9", "video-only")["project_id"]
    try:
        uploaded = core.attach_video_file(pid, source, source.name, 0)
        revision = place(core, pid, uploaded)["project"]["revision"]
        landscape, first, _ = materialize_video(core, pid, True)
        core.set_profile(pid, "SHORT_FORM_9_16", revision)
        portrait, second, _ = materialize_video(core, pid, True)
        assert landscape != portrait
        for path, metadata, dimensions in [(landscape, first, (1280, 720)), (portrait, second, (720, 1280))]:
            payload = path.read_bytes()
            assert payload[4:8] == b"ftyp" and hashlib.sha256(payload).hexdigest() == metadata["sha256"]
            frame = subprocess.check_output([ffmpeg, "-v", "error", "-i", str(path), "-frames:v", "1",
                                            "-c:v", "png", "-f", "image2pipe", "-"], timeout=60)
            assert Image.open(io.BytesIO(frame)).size == dimensions
        from atme.media_delivery import timeline_export
        current = core.open(pid)["revision"]
        ticket = timeline_export(core, pid, current, ticket=True)
        assert ticket["path"].startswith("/media-playback/")
        assert ticket["project_revision"] == current
        with pytest.raises(ProjectError) as error:
            timeline_export(core, pid, revision, ticket=True)
        assert error.value.code == "revision_conflict"
    finally:
        core.store.close()


def test_simultaneous_cache_publishers_leave_one_complete_file(tmp_path):
    from atme.timeline_media import _publish_media

    barrier = Barrier(2)
    destination = tmp_path / "converted.wav"

    def publish(content):
        with _publish_media(destination) as pending:
            pending.write_bytes(content)
            barrier.wait(timeout=10)

    with ThreadPoolExecutor(max_workers=2) as writers:
        list(writers.map(publish, [b"first complete file", b"second complete file"]))
    assert destination.read_bytes() in (b"first complete file", b"second complete file")
    assert list(tmp_path.iterdir()) == [destination]


def test_saved_render_download_is_authenticated_and_range_seekable(tmp_path):
    from test_server_controls import _client

    client, orchestrator, headers = _client(tmp_path)
    store = orchestrator.store
    try:
        project = client.post("/projects", headers=headers, json={
            "title": "Download", "input_kind": "audio-only", "profile": "LONG_FORM_16_9"}).json()
        pid = project["project_id"]
        digest = "a" * 64
        run_id = digest[:24]
        output = store.db_path.parent / "project-runs" / str(pid) / digest / "work" / "out" / "final.mp4"
        output.parent.mkdir(parents=True)
        content = b"verified file transport"
        output.write_bytes(content)
        manifest = {"video": {"bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()}}
        with store._lock, store.conn:
            store.conn.execute("INSERT INTO project_render_runs VALUES(?,?,?,?,?,?,?,?,?)",
                               (pid, run_id, 0, digest, "done", json.dumps(manifest), None, 1, 1))
        path = f"/projects/{pid}/renders/{run_id}/playback-ticket"
        assert client.post(path).status_code in (401, 403)
        url = client.post(path, headers=headers).json()["path"]
        playback = client.get(url, headers={"Range": "bytes=3-7"})
        assert playback.status_code == 206 and playback.content == content[3:8]
        download = client.get(url + "?download=1")
        assert download.content == content
        assert download.headers["content-disposition"] == f'attachment; filename="ATME-{pid}-{run_id}.mp4"'
        output.write_bytes(b"changed!")
        assert client.get(url + "?download=1").status_code == 409
        assert client.post(path, headers=headers).json()["detail"]["code"] == "render_changed"
    finally:
        store.close()
