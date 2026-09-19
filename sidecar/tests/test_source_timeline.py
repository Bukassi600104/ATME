import io
import struct
import wave

import numpy as np
import pytest
import soundfile as sf
from atme.project_service import ProjectError, ProjectService
from atme.store.db import JobStore
from test_project_timing import video_file
from test_server_controls import _client


def silence_wav(sample_rate=16000):
    tone = (np.sin(np.arange(sample_rate // 5) * 2 * np.pi * 220 / sample_rate) * 9000).astype("<i2")
    samples = np.concatenate([tone, np.zeros(sample_rate, dtype="<i2"), tone])
    output = io.BytesIO()
    with wave.open(output, "wb") as recording:
        recording.setnchannels(1); recording.setsampwidth(2); recording.setframerate(sample_rate)
        recording.writeframes(b"".join(struct.pack("<h", int(value)) for value in samples))
    return output.getvalue()


def place(core, pid, uploaded, at_ms=0):
    timeline = core.source_timeline_state(pid)
    return core.edit_source_timeline(
        pid, "insert", {"media_id": uploaded["media"]["media_id"], "at_ms": at_ms},
        uploaded["project"]["revision"], timeline["timeline_revision"])


def test_source_cleanup_is_immutable_undoable_and_authoritative(tmp_path):
    core = ProjectService(JobStore(tmp_path / "timeline.db"))
    project = core.create("Cleanup", "LONG_FORM_16_9", "audio-only")
    uploaded = core.attach_wav(project["project_id"], silence_wav(), 0)
    pid = project["project_id"]
    assert core.source_timeline_state(pid)["document"]["clips"] == []
    placed = place(core, pid, uploaded)
    first = placed["timeline"]
    assert first["timeline_revision"] == 1 and len(first["document"]["clips"]) == 1
    clip = first["document"]["clips"][0]
    split = core.edit_source_timeline(pid, "split", {"clip_id": clip["clip_id"], "at_ms": 500},
                                      placed["project"]["revision"], first["timeline_revision"])
    assert len(split["timeline"]["document"]["clips"]) == 2
    cut = core.edit_source_timeline(pid, "ripple_delete", {"start_ms": 500, "end_ms": 1100},
                                    split["project"]["revision"], split["timeline"]["timeline_revision"])
    assert cut["timeline"]["document"]["duration_ms"] == first["document"]["duration_ms"] - 600
    from atme.narrative_source import timing_audio
    cleaned, metadata, _ = timing_audio(core, pid)
    samples, rate = sf.read(cleaned)
    assert round(len(samples) * 1000 / rate) == cut["timeline"]["document"]["duration_ms"]
    assert metadata["timeline_revision"] == cut["timeline"]["timeline_revision"]
    original = next((tmp_path / "project-media").rglob("*.wav"))
    assert original.read_bytes() == silence_wav()
    restored = core.undo_source_timeline(pid, cut["project"]["revision"])
    assert restored["timeline"]["document"] == split["timeline"]["document"]
    assert restored["timeline"]["history"]["can_redo"] is True
    core.store.close()


def test_waveform_levels_silence_and_safe_source_removal(tmp_path):
    core = ProjectService(JobStore(tmp_path / "analysis.db"))
    project = core.create("Evidence", "LONG_FORM_16_9", "audio-only")
    uploaded = core.attach_wav(project["project_id"], silence_wav(), 0)
    pid, media_id = project["project_id"], uploaded["media"]["media_id"]
    placed = place(core, pid, uploaded)
    fine = core.media_waveform(pid, media_id, 10)
    coarse = core.media_waveform(pid, media_id, 640)
    assert len(fine["peaks"]) > len(coarse["peaks"])
    assert fine["silences"] and fine["silences"][0]["duration_ms"] >= 700
    impact = core.source_removal_impact(pid, media_id)
    assert impact["timeline_clips"] == 1
    with pytest.raises(ProjectError) as error:
        core.remove_source(pid, media_id, placed["project"]["revision"], False)
    assert error.value.code == "confirmation_required"
    managed = next((tmp_path / "project-media").rglob("*.wav"))
    result = core.remove_source(pid, media_id, placed["project"]["revision"], True)
    assert result["managed_copy_retained"] is True and managed.is_file()
    assert core.list_media(pid) == [] and core.source_timeline_state(pid)["document"]["clips"] == []
    core.store.close()


def test_trim_move_crossfade_and_persisted_redo(tmp_path):
    core = ProjectService(JobStore(tmp_path / "editor.db"))
    project = core.create("Editor", "LONG_FORM_16_9", "audio-only")
    pid = project["project_id"]
    first_upload = core.attach_wav(pid, silence_wav(), 0)
    first_place = place(core, pid, first_upload)
    second_upload = core.attach_wav(pid, silence_wav(), first_place["project"]["revision"])
    second_place = place(core, pid, second_upload, first_upload["media"]["duration_ms"])
    timeline = second_place["timeline"]; first = timeline["document"]["clips"][0]
    trimmed = core.edit_source_timeline(pid, "trim", {"clip_id": first["clip_id"], "start_ms": 100, "end_ms": 1300}, second_place["project"]["revision"], timeline["timeline_revision"])
    moved = core.edit_source_timeline(pid, "move", {"clip_id": first["clip_id"], "to_index": 1}, trimmed["project"]["revision"], trimmed["timeline"]["timeline_revision"])
    faded = core.edit_source_timeline(pid, "crossfade", {"clip_id": first["clip_id"], "crossfade_ms": 250}, moved["project"]["revision"], moved["timeline"]["timeline_revision"])
    assert faded["timeline"]["document"]["clips"][1]["crossfade_ms"] == 250
    undone = core.undo_source_timeline(pid, faded["project"]["revision"])
    redone = core.redo_source_timeline(pid, undone["project"]["revision"])
    assert redone["timeline"]["document"] == faded["timeline"]["document"]
    core.store.close()


def test_repeated_timeline_moves_keep_one_project_and_do_not_stale_artifacts(tmp_path):
    core = ProjectService(JobStore(tmp_path / "one-project.db"))
    project = core.create("One project", "LONG_FORM_16_9", "audio-only")
    pid = project["project_id"]
    first = core.attach_wav(pid, silence_wav(), project["revision"])
    placed = place(core, pid, first)
    second = core.attach_wav(pid, silence_wav(), placed["project"]["revision"])
    placed = place(core, pid, second, first["media"]["duration_ms"])
    for index in range(10):
        timeline = placed["timeline"]
        clip_id = timeline["document"]["clips"][0]["clip_id"]
        placed = core.edit_source_timeline(
            pid, "move", {"clip_id": clip_id, "to_index": 1},
            placed["project"]["revision"], timeline["timeline_revision"])
        assert placed["project"]["project_id"] == pid
    assert len(core.list()) == 1
    core.store.close()


def test_http_cleanup_contract_and_revision_conflicts(tmp_path):
    client, orch, headers = _client(tmp_path)
    project = client.post("/projects", headers=headers, json={"title": "HTTP cleanup", "profile": "LONG_FORM_16_9", "input_kind": "audio-only"}).json()
    attached = client.post(f"/projects/{project['project_id']}/media/wav?expected_revision=0", headers=headers, content=silence_wav()).json()
    timeline = client.get(f"/projects/{project['project_id']}/source-timeline", headers=headers).json()
    insert = {"operation":"insert","arguments":{"media_id":attached["media"]["media_id"],"at_ms":0},"expected_revision":attached["project"]["revision"],"expected_timeline_revision":timeline["timeline_revision"]}
    placed = client.post(f"/projects/{project['project_id']}/source-timeline/commands", headers=headers, json=insert).json()
    timeline = placed["timeline"]
    payload = {"operation": "split", "arguments": {"clip_id": timeline["document"]["clips"][0]["clip_id"], "at_ms": 500}, "expected_revision": placed["project"]["revision"], "expected_timeline_revision": timeline["timeline_revision"]}
    assert client.post(f"/projects/{project['project_id']}/source-timeline/commands", headers=headers, json=payload).status_code == 200
    assert client.post(f"/projects/{project['project_id']}/source-timeline/commands", headers=headers, json=payload).status_code == 409
    orch.store.close()


def test_video_ticket_range_thumbnail_and_linked_audio(tmp_path):
    client, orch, headers = _client(tmp_path)
    project = client.post("/projects", headers=headers, json={"title": "Video cleanup", "profile": "LONG_FORM_16_9", "input_kind": "video-only"}).json()
    source = video_file(tmp_path)
    attached = client.post(f"/projects/{project['project_id']}/media/video?expected_revision=0",
                           headers={**headers, "X-Filename": "talking-head.mp4"}, content=source.read_bytes()).json()
    media = attached["media"]
    timeline = client.get(f"/projects/{project['project_id']}/source-timeline", headers=headers).json()
    placed = client.post(f"/projects/{project['project_id']}/source-timeline/commands", headers=headers, json={"operation":"insert","arguments":{"media_id":media["media_id"],"at_ms":0},"expected_revision":attached["project"]["revision"],"expected_timeline_revision":timeline["timeline_revision"]}).json()
    timeline = placed["timeline"]
    clip = timeline["document"]["clips"][0]
    assert clip["kind"] == "video" and clip["stream"] == "linked_av" and clip["link_group_id"]
    ticket = client.post(f"/projects/{project['project_id']}/playback-ticket", headers=headers,
                         json={"expected_revision": placed["project"]["revision"], "media_id": None, "cleaned": True}).json()
    chunk = client.get(ticket["path"], headers={"Range": "bytes=0-127"})
    assert chunk.status_code == 206 and len(chunk.content) == 128 and chunk.headers["accept-ranges"] == "bytes"
    first = client.get(f"/projects/{project['project_id']}/media/{media['media_id']}/thumbnail?at_ms=1000&width=160", headers=headers)
    second = client.get(f"/projects/{project['project_id']}/media/{media['media_id']}/thumbnail?at_ms=1000&width=160", headers=headers)
    assert first.status_code == 200 and first.content == second.content and first.headers["content-type"].startswith("image/jpeg")
    orch.store.close()


def test_media_bin_is_independent_and_detached_av_moves_independently(tmp_path):
    core = ProjectService(JobStore(tmp_path / "detach.db"))
    project = core.create("Detach", "LONG_FORM_16_9", "video-only")
    uploaded_path = video_file(tmp_path)
    from atme.project_media import attach_video_file
    uploaded = attach_video_file(core, project["project_id"], uploaded_path, "source.mp4", 0)
    assert core.source_timeline_state(project["project_id"])["document"]["clips"] == []
    placed = place(core, project["project_id"], uploaded)
    clip = placed["timeline"]["document"]["clips"][0]
    detached = core.edit_source_timeline(project["project_id"], "detach_audio", {"clip_id": clip["clip_id"]},
        placed["project"]["revision"], placed["timeline"]["timeline_revision"])
    video = next(c for c in detached["timeline"]["document"]["clips"] if c["kind"] == "video")
    audio = next(c for c in detached["timeline"]["document"]["clips"] if c["kind"] == "audio")
    assert {video["kind"], audio["kind"]} == {"video", "audio"}
    assert video["link_group_id"] != audio["link_group_id"]
    moved = core.edit_source_timeline(project["project_id"], "move_position", {"clip_id": audio["clip_id"], "timeline_start_ms": 250},
        detached["project"]["revision"], detached["timeline"]["timeline_revision"])
    assert next(c for c in moved["timeline"]["document"]["clips"] if c["kind"] == "video")["timeline_start_ms"] == 0
    from atme.timeline_media import materialize_video
    preview, metadata, _ = materialize_video(core, project["project_id"])
    assert preview.is_file() and metadata["duration_ms"] == moved["timeline"]["document"]["duration_ms"]
    core.store.close()
