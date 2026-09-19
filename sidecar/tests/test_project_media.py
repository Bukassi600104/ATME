import hashlib
from copy import deepcopy

import pytest
from atme.project_service import ProjectError, ProjectService
from atme.store.db import JobStore
from test_external_inputs import external_payload
from test_server_controls import _client, _wav_bytes


def test_pcm_wav_is_retained_exactly_and_invalidates_old_plan(tmp_path):
    core = ProjectService(JobStore(tmp_path / "project.db"))
    pid = core.create("Original recording", "LONG_FORM_16_9", "script+audio")["project_id"]
    payload = external_payload()
    core.write(pid, "script", payload["script"], 0)
    core.approve_script(pid, 1, 1, True)
    core.write(pid, "layout", payload["layout"], 2)
    recording = _wav_bytes()
    result = core.attach_wav(pid, recording, 3)
    assert result["project"]["revision"] == 4
    assert result["project"]["approved_script_revision"] == 1
    assert result["media"]["semantic_transcript"] is None
    assert result["media"]["sha256"] == hashlib.sha256(recording).hexdigest()
    # Adding media to the bin is a normal project edit and must not invalidate
    # an existing creative plan. Timing is resolved when media reaches timeline.
    assert core.artifact(pid, "layout")["stale"] is False
    assert next((tmp_path / "project-media").rglob("*.wav")).read_bytes() == recording
    assert core.list_media(pid)[0]["duration_ms"] == 1200
    assert not set(core.list_media(pid)[0]) & {"path", "relative_path"}
    before = list((tmp_path / "project-media").rglob("*.wav"))
    with pytest.raises(ProjectError, match="changed"):
        core.attach_wav(pid, recording, 3)
    assert list((tmp_path / "project-media").rglob("*.wav")) == before
    core.store.close()


@pytest.mark.parametrize("recording", [b"not audio", _wav_bytes()[:-100]], ids=["not-audio", "truncated-wav"])
def test_invalid_audio_never_changes_project_or_writes_media(tmp_path, recording):
    core = ProjectService(JobStore(tmp_path / "project.db"))
    project = core.create("Audio", "SHORT_FORM_9_16", "audio-only")
    with pytest.raises(ProjectError, match="PCM WAV"):
        core.attach_wav(project["project_id"], recording, 0)
    assert core.open(project["project_id"]) == project
    assert not (tmp_path / "project-media").exists()
    core.store.close()


def test_direct_http_upload_is_authenticated_and_bounded(tmp_path, monkeypatch):
    client, _orch, headers = _client(tmp_path)
    project = client.post("/projects", headers=headers, json={
        "title": "Local upload", "profile": "LONG_FORM_16_9", "input_kind": "audio-only"}).json()
    pid = project["project_id"]
    url = f"/projects/{pid}/media/wav?expected_revision=0"
    assert client.post(url, content=_wav_bytes()).status_code == 401
    import atme.project_media as media
    monkeypatch.setattr(media, "MAX_MEDIA_BYTES", 100)
    assert client.post(url, headers=headers, content=_wav_bytes()).status_code == 413
    monkeypatch.setattr(media, "MAX_MEDIA_BYTES", 64 * 1024 * 1024)
    assert client.post(url, headers=headers, content=_wav_bytes()).status_code == 200
    rows = client.get(f"/projects/{pid}/media", headers=headers).json()
    assert len(rows) == 1 and rows[0]["format"] == "wav"


def test_storyboard_preserves_external_narration_and_approval(tmp_path):
    import json

    from atme.resources import resource_path
    core = ProjectService(JobStore(tmp_path / "project.db"))
    pid = core.create("Storyboard", "LONG_FORM_16_9", "script-first")["project_id"]
    script = external_payload()["script"]
    core.write(pid, "script", script, 0)
    core.approve_script(pid, 1, 1, True)
    example = json.loads(resource_path("schemas", "examples", "visual-plan.example.json").read_text())
    beat = example["beats"][0]
    board = {"contract_version": "1", "topic": script["topic"], "beats": [
        {**deepcopy(beat), "beat_id": f"beat-{i:03d}", "scene_id": s["scene_id"], "narration": s["spoken_text"]}
        for i, s in enumerate(script["scenes"], 1)]}
    state = core.write(pid, "storyboard", board, 2)
    assert state["approved_script_revision"] == 1
    board["beats"][0]["narration"] = "Unapproved narration"
    with pytest.raises(ProjectError, match="preserve"):
        core.write(pid, "storyboard", board, 3)
    assert core.open(pid) == state
    core.store.close()


def test_direct_video_upload_streams_and_keeps_derivative_paths_private(tmp_path):
    from test_project_timing import video_file

    client, orch, headers = _client(tmp_path)
    project = client.post("/projects", headers=headers, json={
        "title": "Video authority", "profile": "SHORT_FORM_9_16", "input_kind": "video-only"}).json()
    video = video_file(tmp_path)
    payload = video.read_bytes()
    response = client.post(f"/projects/{project['project_id']}/media/video?expected_revision=0",
                           headers={**headers, "X-Filename": "narration.mp4"}, content=payload)
    assert response.status_code == 200, response.text
    media = client.get(f"/projects/{project['project_id']}/media", headers=headers).json()[0]
    assert media["kind"] == "video" and media["semantic_transcript"] is None
    assert not set(media) & {"path", "relative_path", "timing_audio_relative_path"}
    source = client.get(f"/projects/{project['project_id']}/narrative-source", headers=headers).json()
    assert source["mode"] == "recording_authority" and source["ready_for_timing"]
    orch.store.close()


def test_supporting_asset_is_immutable_and_never_becomes_narrative_authority(tmp_path):
    client, orch, headers = _client(tmp_path)
    project = client.post("/projects", headers=headers, json={
        "title": "Reference assets", "profile": "LONG_FORM_16_9", "input_kind": "idea-first"}).json()
    payload = b"reference notes for the connected AI"
    response = client.post(f"/projects/{project['project_id']}/assets?expected_revision=0",
                           headers={**headers, "X-Filename": "reference.txt",
                                    "Content-Type": "text/plain"}, content=payload)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["project"]["revision"] == 1 and result["asset"]["role"] == "supporting_asset"
    assets = client.get(f"/projects/{project['project_id']}/assets", headers=headers).json()["assets"]
    assert assets[0]["name"] == "reference.txt" and "relative_path" not in assets[0]
    content = client.get(
        f"/projects/{project['project_id']}/assets/{assets[0]['asset_id']}/content", headers=headers)
    assert content.content == payload
    source = client.get(f"/projects/{project['project_id']}/narrative-source", headers=headers).json()
    assert source["timing_authority"]["media"] is None
    orch.store.close()
