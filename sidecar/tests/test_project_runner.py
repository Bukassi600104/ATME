import io
import json
import wave
import subprocess
from copy import deepcopy
from pathlib import Path
from threading import Event

import pytest
from atme.project_service import ProjectError, ProjectService
from atme.store.db import JobStore
from test_board_continuity import board_doc
from test_external_inputs import external_payload


def test_talking_head_compositor_preserves_source_and_adds_caleb_ink(tmp_path):
    from PIL import Image
    from atme.project_runner import _compose_talking_head
    from atme.render.animator import find_ffmpeg

    ffmpeg = find_ffmpeg()
    source, overlay, output, frame = (tmp_path / name for name in
        ("source.mp4", "overlay.mp4", "result.mp4", "frame.png"))
    subprocess.run([ffmpeg, "-y", "-hide_banner", "-v", "error", "-f", "lavfi",
                    "-i", "color=c=blue:s=320x180:d=1", "-f", "lavfi", "-i", "anullsrc",
                    "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(source)], check=True)
    subprocess.run([ffmpeg, "-y", "-hide_banner", "-v", "error", "-f", "lavfi",
                    "-i", "color=c=0xFAF9F5:s=320x180:d=1",
                    "-vf", "drawbox=x=130:y=60:w=60:h=60:color=red:t=fill",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(overlay)], check=True)
    _compose_talking_head(source, overlay, output, {"width": 320, "height": 180, "fps": 30})
    subprocess.run([ffmpeg, "-y", "-hide_banner", "-v", "error", "-ss", "0.5",
                    "-i", str(output), "-frames:v", "1", str(frame)], check=True)
    image = Image.open(frame).convert("RGB")
    corner, centre = image.getpixel((20, 20)), image.getpixel((160, 90))
    assert corner[2] > corner[0] * 2  # talking-head/base picture remains visible
    assert centre[0] > centre[2] * 2  # Caleb overlay remains visible


def wav_bytes(seconds=7, rate=8000):
    output = io.BytesIO()
    with wave.open(output, "wb") as recording:
        recording.setnchannels(1)
        recording.setsampwidth(2)
        recording.setframerate(rate)
        recording.writeframes(b"\0\0" * rate * seconds)
    return output.getvalue()


def storyboard(script):
    purposes = ["identity", "emphasis"]
    return {"contract_version": "1", "topic": script["topic"], "beats": [
        {"beat_id": f"beat-{index:03d}", "scene_id": scene["scene_id"],
         "narration": scene["spoken_text"], "trigger_phrase": scene["spoken_text"].split()[0],
         "purpose": purposes[index - 1], "assets": ["diagram"], "actions": ["draw"],
         "layout": "Authored board composition", "camera": {"action": "hold", "subject": "diagram"},
         "continuity": {"keep": [], "remove": []}, "emphasis": "",
         "fallback": "Keep the authored board"}
        for index, scene in enumerate(script["scenes"], start=1)]}


def ready_project(tmp_path, profile="LONG_FORM_16_9"):
    core = ProjectService(JobStore(tmp_path / "projects.db"))
    project = core.create("Ready external production", profile, "script+audio")
    pid = project["project_id"]
    script = external_payload()["script"]
    core.write(pid, "script", script, 0)
    core.approve_script(pid, 1, 1, True)
    core.attach_wav(pid, wav_bytes(), 2)
    core.write(pid, "storyboard", storyboard(script), 3)
    layout = board_doc()
    layout["canvas"] = ({"width": 1280, "height": 720} if profile == "LONG_FORM_16_9"
                        else {"width": 720, "height": 1280})
    state = core.write(pid, "layout", layout, 4)
    return core, state


def test_validation_and_immutable_compilation(tmp_path):
    core, state = ready_project(tmp_path)
    pid = state["project_id"]
    assert state["render_ready"] is True
    report = core.validate_project(pid)
    assert report["ready"] and report["profile"] == {
        "id": "LONG_FORM_16_9", "width": 1280, "height": 720, "fps": 30}
    first = core.runner.compile(pid, 5)
    second = core.runner.compile(pid, 5)
    assert first["resumed"] is False and second["resumed"] is True
    runtime = Path(first["runtime_dir"])
    assert json.loads((runtime / "inputs" / "script.json").read_text()) == external_payload()["script"]
    assert (runtime / "inputs" / "narration.wav").is_file()
    preview = core.preview_project(pid, 5, 2500)
    assert preview["png"].startswith(b"\x89PNG\r\n\x1a\n")
    assert (preview["width"], preview["height"]) == (960, 540)
    changed = deepcopy(external_payload()["script"])
    changed["scenes"][0]["spoken_text"] = "A revised external narration."
    updated = core.write(pid, "script", changed, 5)
    assert updated["render_ready"] is False
    assert {issue["code"] for issue in core.validate_project(pid)["issues"]} >= {
        "script_not_approved", "storyboard_stale", "layout_stale"}
    core.store.close()


def test_profile_geometry_and_duration_are_hard_gates(tmp_path):
    core, state = ready_project(tmp_path, "SHORT_FORM_9_16")
    assert core.validate_project(state["project_id"])["ready"]
    layout = core.artifact(state["project_id"], "layout")["document"]
    layout["canvas"] = {"width": 1000, "height": 1000}
    changed = core.write(state["project_id"], "layout", layout, 5)
    report = core.validate_project(state["project_id"])
    assert changed["render_ready"] is False
    assert "layout_aspect_mismatch" in {issue["code"] for issue in report["issues"]}
    core.store.close()


def test_audio_only_project_compiles_from_recording_authority_without_approval(tmp_path):
    core = ProjectService(JobStore(tmp_path / "audio-only.db"))
    pid = core.create("Audio is authority", "LONG_FORM_16_9", "audio-only")["project_id"]
    core.attach_wav(pid, wav_bytes(), 0)
    script = external_payload()["script"]  # Connected-AI-derived semantic index.
    core.write(pid, "script", script, 1)
    core.write(pid, "storyboard", storyboard(script), 2)
    layout = board_doc()
    layout["canvas"] = {"width": 1280, "height": 720}
    state = core.write(pid, "layout", layout, 3)
    assert state["approved_script_revision"] is None and state["render_ready"] is True
    compiled = core.runner.compile(pid, 4)
    assert compiled["script_revision"] == 2 and compiled["media_revision"] == 1
    assert compiled["semantic_role"] == "connected_ai_derivative_of_recording"
    assert state["authoritative_narrative_source"]["narrative_authority"]["type"] == "recording"
    core.store.close()


def test_render_is_manual_durable_and_uses_existing_pipeline(tmp_path, monkeypatch):
    core, state = ready_project(tmp_path)
    pid = state["project_id"]
    with pytest.raises(ProjectError, match="explicitly"):
        core.render_project(pid, 5, False)
    calls = []
    from atme import pipeline
    runtime = Path(core.runner.compile(pid, 5)["runtime_dir"])
    work = runtime / "work"
    audio = {"final_wav": str(work / "audio" / "final.wav"), "duration_ms": 6000,
             "sha256": "a" * 64, "edl": [], "wall_s": 0}
    aligned = {"layout_file": str(work / "layout.json"), "duration_ms": 6000,
               "cues_file": str(work / "cue_timeline.json"),
               "visual_plan_file": str(work / "visual_plan.json"), "words": 10, "wall_s": 0}
    rendered = {"silent_video": str(work / "out" / "video.mp4"),
                "render": {}, "segments": [], "wall_s": 0}
    started, release = Event(), Event()

    def polish(*args, **kwargs):
        calls.append("polish")
        assert kwargs.get("remove_silence") is False
        started.set()
        assert release.wait(timeout=10)
        return audio

    monkeypatch.setattr(pipeline, "polish_stage", polish)
    monkeypatch.setattr(pipeline, "align_stage", lambda *a, **k: calls.append("align") or aligned)
    monkeypatch.setattr(pipeline, "render_stage", lambda *a, **k: calls.append(("render", k)) or rendered)
    monkeypatch.setattr(pipeline, "assemble_stage", lambda *a, **k: calls.append("assemble") or {
        "duration_ms": 6000, "artifacts": {"video": {"sha256": "b" * 64, "bytes": 12345}}})
    queued = core.render_project(pid, 5, True)
    assert queued["status"] in ("queued", "running", "done")
    assert started.wait(timeout=10)
    revised = deepcopy(external_payload()["script"])
    revised["scenes"][0]["spoken_text"] = "A later revision must not alter the queued snapshot."
    core.write(pid, "script", revised, 5)
    release.set()
    core.runner._workers[queued["run_id"]].join(timeout=10)
    assert not core.runner._workers[queued["run_id"]].is_alive()
    result = core.render_status(pid, queued["run_id"])
    assert result["status"] == "done"
    assert result["project_revision"] == 5 and core.open(pid)["revision"] == 6
    assert [item if isinstance(item, str) else item[0] for item in calls] == [
        "polish", "align", "render", "assemble"]
    assert calls[2][1] == {"width": 1280, "height": 720, "fps": 30}
    assert core.render_status(pid, result["run_id"])["manifest"]["video"]["bytes"] == 12345
    core.store.close()
