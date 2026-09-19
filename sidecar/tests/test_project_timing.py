import hashlib
import json
import shutil
import subprocess
from copy import deepcopy
from threading import Event

from atme.project_service import ProjectService
from atme.store.db import JobStore
from test_external_inputs import external_payload
from test_project_runner import wav_bytes


def fake_polish(work, voice_mode, **kwargs):
    assert kwargs.get("remove_silence") is False
    source = work / "audio" / "upload.wav"
    final = work / "audio" / "final.wav"
    shutil.copyfile(source, final)
    return {"final_wav": str(final), "duration_ms": 7000, "sample_rate": 8000,
            "scene_starts_ms": [0], "edl": [],
            "sha256": hashlib.sha256(final.read_bytes()).hexdigest(), "wall_s": 0}


def observed_words(*args, **kwargs):
    return [
        {"word": "Queue", "start_ms": 100, "end_ms": 350, "scene_id": 1,
         "confidence": .99, "flagged": False},
        {"word": "pointer", "start_ms": 400, "end_ms": 700, "scene_id": 1,
         "confidence": .99, "flagged": False},
        {"word": "Evidence", "start_ms": 1100, "end_ms": 1450, "scene_id": 1,
         "confidence": .99, "flagged": False},
        {"word": "return", "start_ms": 1500, "end_ms": 1800, "scene_id": 1,
         "confidence": .99, "flagged": False}]


def video_file(tmp_path):
    audio = tmp_path / "source.wav"
    audio.write_bytes(wav_bytes())
    video = tmp_path / "source.mp4"
    from atme.render.animator import find_ffmpeg
    subprocess.run([find_ffmpeg(), "-y", "-hide_banner", "-v", "error",
                    "-f", "lavfi", "-i", "color=c=black:s=160x90:r=1:d=7",
                    "-i", str(audio), "-shortest", "-c:v", "mpeg4", "-c:a", "aac", str(video)],
                   check=True, timeout=30)
    return video


def test_script_authority_timing_uses_only_approved_script_semantics(tmp_path, monkeypatch):
    core = ProjectService(JobStore(tmp_path / "script.db"))
    pid = core.create("Script timing", "LONG_FORM_16_9", "script+audio")["project_id"]
    script = external_payload()["script"]
    core.write(pid, "script", script, 0)
    core.approve_script(pid, 1, 1, True)
    core.attach_wav(pid, wav_bytes(), 2)
    from atme import pipeline, project_timing
    monkeypatch.setattr(pipeline, "polish_stage", fake_polish)
    monkeypatch.setattr(project_timing, "_acoustic_words", observed_words)
    result = core.timing.prepare(pid, 3)
    timing = result["timing"]
    assert timing["status"] == "ready"
    assert timing["authority_mode"] == "script_authority"
    context = timing["semantic_structure"]["planning_context"]
    assert context["semantic_authority"] == "authoritative_external_script"
    assert [word["word"] for scene in context["scenes"] for word in scene["words"]] == [
        "queue", "pointer", "evidence", "return"]
    core.store.close()


def test_recording_only_timing_exposes_units_not_local_recognized_text(tmp_path, monkeypatch):
    core = ProjectService(JobStore(tmp_path / "recording.db"))
    pid = core.create("Recording timing", "LONG_FORM_16_9", "audio-only")["project_id"]
    core.attach_wav(pid, wav_bytes(), 0)
    from atme import pipeline, project_timing
    monkeypatch.setattr(pipeline, "polish_stage", fake_polish)
    monkeypatch.setattr(project_timing, "_acoustic_words", observed_words)
    result = core.timing.prepare(pid, 1)
    timing = result["timing"]
    assert timing["status"] == "needs_semantic_structure"
    assert timing["authority_mode"] == "recording_authority"
    assert timing["semantic_structure"]["role"] == "none"
    assert len(timing["speech_units"]) == 4
    assert all(set(unit) == {"unit_index", "start_ms", "end_ms", "confidence", "flagged"}
               for unit in timing["speech_units"])
    serialized = json.dumps(timing).lower()
    assert not any(word in serialized for word in ("queue", "pointer", "evidence", "return"))
    core.store.close()


def test_queued_timing_stays_bound_to_original_authority_revision(tmp_path, monkeypatch):
    core = ProjectService(JobStore(tmp_path / "queued.db"))
    pid = core.create("Queued timing", "LONG_FORM_16_9", "script+audio")["project_id"]
    script = external_payload()["script"]
    core.write(pid, "script", script, 0)
    core.approve_script(pid, 1, 1, True)
    core.attach_wav(pid, wav_bytes(), 2)
    from atme import pipeline, project_timing
    started, release = Event(), Event()

    def blocking_polish(work, voice_mode, **kwargs):
        started.set()
        assert release.wait(timeout=10)
        return fake_polish(work, voice_mode, **kwargs)

    monkeypatch.setattr(pipeline, "polish_stage", blocking_polish)
    monkeypatch.setattr(project_timing, "_acoustic_words", observed_words)
    queued = core.prepare_timing(pid, 3)
    assert started.wait(timeout=10)
    revised = deepcopy(script)
    revised["scenes"][0]["spoken_text"] = "A later script revision."
    core.write(pid, "script", revised, 3)
    release.set()
    core.timing._workers[queued["run_id"]].join(timeout=10)
    result = core.timing_status(pid, queued["run_id"])
    assert result["status"] == "done" and result["project_revision"] == 3
    assert result["timing"]["semantic_structure"]["planning_context"]["scenes"][0][
        "narration"] == "Queue pointer."
    assert core.open(pid)["revision"] == 4
    core.store.close()


def test_recording_authority_can_bind_connected_ai_derived_structure(tmp_path, monkeypatch):
    core = ProjectService(JobStore(tmp_path / "derived.db"))
    pid = core.create("Derived structure", "LONG_FORM_16_9", "audio-only")["project_id"]
    core.attach_wav(pid, wav_bytes(), 0)
    core.write(pid, "script", external_payload()["script"], 1)
    from atme import pipeline, project_timing
    monkeypatch.setattr(pipeline, "polish_stage", fake_polish)
    monkeypatch.setattr(project_timing, "_acoustic_words", observed_words)
    timing = core.timing.prepare(pid, 2)["timing"]
    assert timing["authority_mode"] == "recording_authority"
    assert timing["semantic_structure"]["role"] == "connected_ai_derivative_of_recording"
    assert timing["semantic_structure"]["planning_context"]["semantic_authority"] == (
        "connected_ai_derivative_of_recording")
    assert core.open(pid)["approved_script_revision"] is None
    core.store.close()


def test_video_only_authority_extracts_local_timing_audio_without_semantic_text(tmp_path, monkeypatch):
    core = ProjectService(JobStore(tmp_path / "video.db"))
    pid = core.create("Video timing", "SHORT_FORM_9_16", "video-only")["project_id"]
    attached = core.attach_video_file(pid, video_file(tmp_path), "narration.mp4", 0)
    assert attached["media"]["kind"] == "video"
    source = core.narrative_source(pid)
    assert source["ready_for_timing"] and source["narrative_authority"]["type"] == "recording"
    audio_payload, audio_metadata = core.authoritative_audio(pid)
    assert audio_payload.startswith(b"RIFF") and audio_metadata["authority_kind"] == "video"
    from atme import pipeline, project_timing
    monkeypatch.setattr(pipeline, "polish_stage", fake_polish)
    monkeypatch.setattr(project_timing, "_acoustic_words", observed_words)
    timing = core.timing.prepare(pid, 1)["timing"]
    assert timing["authority_mode"] == "recording_authority"
    assert timing["status"] == "needs_semantic_structure"
    assert "speech_units" in timing and "planning_context" not in timing["semantic_structure"]
    core.store.close()
