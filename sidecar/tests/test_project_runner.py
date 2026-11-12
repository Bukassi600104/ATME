import hashlib
import io
import json
import shutil
import subprocess
import wave
from copy import deepcopy
from pathlib import Path
from threading import Event

import pytest
from test_board_continuity import board_doc
from test_external_inputs import external_payload

from atme.project_service import ProjectError, ProjectService
from atme.store.db import JobStore


def test_talking_head_export_uses_mastered_audio_and_final_manifest(tmp_path, monkeypatch):
    from PIL import Image

    from atme import pipeline
    from atme.render.animator import find_ffmpeg

    ffmpeg = find_ffmpeg()
    source, overlay, master, frame = (tmp_path / name for name in
        ("source.mp4", "overlay.mp4", "master.wav", "frame.png"))
    subprocess.run([ffmpeg, "-y", "-hide_banner", "-v", "error", "-f", "lavfi",
                    "-i", "color=c=blue:s=320x180:d=7", "-f", "lavfi", "-i", "sine=frequency=220:duration=7",
                    "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(source)], check=True)
    subprocess.run([ffmpeg, "-y", "-hide_banner", "-v", "error", "-f", "lavfi",
                    "-i", "color=c=0xFAF9F5:s=320x180:d=7",
                    "-vf", "drawbox=x=130:y=60:w=60:h=60:color=red:t=fill",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(overlay)], check=True)
    subprocess.run([ffmpeg, "-v", "error", "-f", "lavfi", "-i", "sine=frequency=880:duration=7.011",
                    "-c:a", "pcm_s16le", str(master)], check=True)

    def audio_packets(video):
        return subprocess.check_output([ffmpeg, "-v", "error", "-i", str(video), "-map", "0:a:0",
                                        "-c:a", "copy", "-f", "adts", "pipe:1"])

    expected_audio = subprocess.check_output([ffmpeg, "-v", "error", "-i", str(master), "-map", "0:a:0",
                                              "-c:a", "aac", "-b:a", "160k", "-f", "adts", "pipe:1"])
    assert expected_audio and audio_packets(source) != expected_audio
    core, state = ready_project(tmp_path, source_video=source)
    pid = state["project_id"]

    def polish(work, **_):
        wav = work / "audio" / "final.wav"
        shutil.copyfile(master, wav)
        return {"final_wav": str(wav), "duration_ms": 7011, "edl": [],
                "sha256": hashlib.sha256(wav.read_bytes()).hexdigest()}

    def render(work, aligned, **_):
        (work / "out").mkdir()
        return {"silent_video": str(overlay), "render": {}, "segments": []}

    monkeypatch.setattr(pipeline, "polish_stage", polish)
    monkeypatch.setattr(pipeline, "align_stage", lambda *a, **k: {
        "layout_file": "layout.json", "cues_file": "cues.json", "visual_plan_file": "visual_plan.json", "words": 0})
    monkeypatch.setattr(pipeline, "render_stage", render)
    queued = core.render_project(pid, state["revision"], True)
    run_id = queued["run_id"]
    core.runner._workers[run_id].join(60)
    finished = core.runner.status(pid, run_id)
    assert finished["status"] == "done", finished.get("error")
    output = core.runner.output_path(pid, run_id)
    assert audio_packets(output) == expected_audio
    frame_hashes = subprocess.check_output([ffmpeg, "-v", "error", "-i", str(output), "-map", "0:v:0",
                                            "-c:v", "copy", "-f", "framehash", "pipe:1"])
    assert sum(not line.startswith(b"#") for line in frame_hashes.splitlines()) == 211
    stored = json.loads((output.parents[1] / "manifest.json").read_text(encoding="utf-8"))
    actual_video = {"sha256": hashlib.sha256(output.read_bytes()).hexdigest(), "bytes": output.stat().st_size}
    assert finished["manifest"]["video"] == actual_video
    assert stored["artifacts"]["video"] == {"path": str(output), **actual_video}
    assert stored["composition_mode"] == "talking_head_with_caleb_overlays"
    subprocess.run([ffmpeg, "-y", "-hide_banner", "-v", "error", "-ss", "0.5",
                    "-i", str(output), "-frames:v", "1", str(frame)], check=True)
    image = Image.open(frame).convert("RGB")
    corner, centre = image.getpixel((20, 20)), image.getpixel((image.width // 2, image.height // 2))
    assert corner[2] > corner[0] * 2  # talking-head/base picture remains visible
    assert centre[0] > centre[2] * 2  # Caleb overlay remains visible
    core.store.close()


def test_ordinary_mux_and_long_ink_preserve_partial_final_frame(tmp_path):
    import av
    from atme import pipeline
    from atme.project_runner import _compose_talking_head
    from atme.render.animator import find_ffmpeg

    ffmpeg = find_ffmpeg()
    master, camera, ink = (tmp_path / name for name in ("master.wav", "camera.mp4", "ink.mp4"))
    subprocess.run([ffmpeg, "-v", "error", "-f", "lavfi", "-i", "sine=frequency=880:duration=0.217",
                    "-c:a", "pcm_s16le", str(master)], check=True)
    for path, duration in [(camera, "0.16"), (ink, "0.4")]:
        subprocess.run([ffmpeg, "-v", "error", "-f", "lavfi", "-i", f"color=blue:s=160x90:r=30:d={duration}",
                        "-c:v", "libx264", str(path)], check=True)
    expected = subprocess.check_output([ffmpeg, "-v", "error", "-i", str(master), "-c:a", "aac",
                                        "-b:a", "160k", "-f", "adts", "pipe:1"])
    outputs = [tmp_path / name for name in ("short.mp4", "long.mp4", "camera-ink.mp4", "copy.mp4")]
    pipeline._mux(camera, master, outputs[0])
    pipeline._mux(ink, master, outputs[1])
    _compose_talking_head(camera, ink, master, outputs[2], {"fps": 30, "width": 160, "height": 90})
    pipeline._mux(outputs[0], master, outputs[3])
    for output in outputs:
        with av.open(str(output)) as movie:
            video = movie.streams.video[0]
            assert video.frames == 7 and video.duration * video.time_base == 7 / video.average_rate
        actual = subprocess.check_output([ffmpeg, "-v", "error", "-i", str(output), "-map", "0:a:0",
                                          "-c:a", "copy", "-f", "adts", "pipe:1"])
        assert actual == expected
    def compressed_frames(output):
        with av.open(str(output)) as movie:
            return [bytes(packet) for packet in movie.demux(video=0) if packet.size]
    assert compressed_frames(outputs[0]) == compressed_frames(outputs[3])


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


def ready_project(tmp_path, profile="LONG_FORM_16_9", *, source_video=None):
    core = ProjectService(JobStore(tmp_path / "projects.db"))
    project = core.create("Ready external production", profile, "script+video" if source_video else "script+audio")
    pid = project["project_id"]
    script = external_payload()["script"]
    core.write(pid, "script", script, 0)
    core.approve_script(pid, 1, 1, True)
    if source_video:
        uploaded = core.attach_video_file(pid, source_video, source_video.name, 2)
        placed = core.edit_source_timeline(pid, "insert", {"media_id": uploaded["media"]["media_id"], "at_ms": 0},
                                           uploaded["project"]["revision"], 0)
        revision = placed["project"]["revision"]
    else:
        revision = core.attach_wav(pid, wav_bytes(), 2)["project"]["revision"]
    core.write(pid, "storyboard", storyboard(script), revision)
    layout = board_doc()
    layout["canvas"] = ({"width": 1280, "height": 720} if profile == "LONG_FORM_16_9"
                        else {"width": 720, "height": 1280})
    state = core.write(pid, "layout", layout, revision + 1)
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


def test_draft_layout_preview_is_available_before_export_validation(tmp_path):
    """Studio review is not the same gate as a final deterministic export."""
    core = ProjectService(JobStore(tmp_path / "draft-preview.db"))
    pid = core.create("Reviewable draft", "LONG_FORM_16_9", "script+audio")["project_id"]
    script = external_payload()["script"]
    core.write(pid, "script", script, 0)
    core.approve_script(pid, 1, 1, True)
    core.attach_wav(pid, wav_bytes(), 2)
    layout = board_doc()
    layout["canvas"] = {"width": 1280, "height": 720}
    state = core.write(pid, "layout", layout, 3)

    assert state["render_ready"] is False  # storyboard is still absent
    preview = core.preview_project(pid, state["revision"], 2500)
    assert preview["png"].startswith(b"\x89PNG\r\n\x1a\n")
    assert (preview["width"], preview["height"]) == (960, 540)
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
