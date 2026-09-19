"""Network-isolation acceptance for the deterministic compile/render boundary.

The local acoustic aligner is represented by an already-available timing engine so
this test cannot download a model. Audio polish, visual rendering, mux, project
snapshotting and output integrity are real.
"""
import io
import math
import socket
import struct
import wave

import pytest
from test_external_inputs import external_payload
from test_project_runner import storyboard

from atme.project_service import ProjectService
from atme.store.db import JobStore


def narration_wav(seconds=3, rate=16000):
    output = io.BytesIO()
    with wave.open(output, "wb") as recording:
        recording.setnchannels(1)
        recording.setsampwidth(2)
        recording.setframerate(rate)
        frames = bytearray()
        for index in range(rate * seconds):
            frames.extend(struct.pack("<h", int(5000 * math.sin(2 * math.pi * 220 * index / rate))))
        recording.writeframes(frames)
    return output.getvalue()


def compact_layout(profile="LONG_FORM_16_9"):
    from test_board_continuity import board_doc
    doc = board_doc()
    doc["canvas"] = ({"width": 1280, "height": 720} if profile == "LONG_FORM_16_9"
                     else {"width": 720, "height": 1280})
    doc["board_timeline"]["activations"] = [
        {"activation_id": "queue-first", "board_id": "queue", "start_ms": 0, "end_ms": 1000},
        {"activation_id": "evidence-first", "board_id": "evidence", "start_ms": 1000, "end_ms": 2000},
        {"activation_id": "queue-return", "board_id": "queue", "start_ms": 2000, "end_ms": 2800}]
    doc["elements"][0]["appear_at_ms"] = 0
    doc["elements"][1]["appear_at_ms"] = 250
    doc["elements"][1]["visibility_intervals"] = [{"start_ms": 250, "end_ms": 750}]
    doc["elements"][2]["appear_at_ms"] = 1000
    return doc


@pytest.mark.parametrize("profile,dimensions", [
    ("LONG_FORM_16_9", (1280, 720)), ("SHORT_FORM_9_16", (720, 1280))])
def test_saved_project_renders_with_python_network_blocked(tmp_path, monkeypatch, profile, dimensions):
    core = ProjectService(JobStore(tmp_path / "projects.db"))
    pid = core.create("Offline accepted", profile, "script+audio")["project_id"]
    script = external_payload()["script"]
    core.write(pid, "script", script, 0)
    core.approve_script(pid, 1, 1, True)
    core.attach_wav(pid, narration_wav(), 2)
    core.write(pid, "storyboard", storyboard(script), 3)
    core.write(pid, "layout", compact_layout(profile), 4)

    from atme import pipeline
    from atme.audio import polish as polish_module
    observed = [
        {"word": "Queue", "start_ms": 100, "end_ms": 350, "scene_id": 1,
         "confidence": .99, "flagged": False},
        {"word": "pointer", "start_ms": 400, "end_ms": 700, "scene_id": 1,
         "confidence": .99, "flagged": False},
        {"word": "Evidence", "start_ms": 1100, "end_ms": 1450, "scene_id": 2,
         "confidence": .99, "flagged": False},
        {"word": "return", "start_ms": 1500, "end_ms": 1800, "scene_id": 2,
         "confidence": .99, "flagged": False}]
    monkeypatch.setattr(pipeline, "align_words", lambda *args, **kwargs: observed)
    # A stationary calibration tone is not speech and is intentionally removed by
    # the optional denoiser. Keep it intact while exercising every later real stage.
    monkeypatch.setattr(polish_module, "denoise", lambda samples, sample_rate: samples)

    def forbidden(*args, **kwargs):
        raise AssertionError("network access attempted during offline render")
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)

    result = core.runner.render(pid, 5, True)
    assert result["status"] == "done"
    output = core.runner.output_path(pid, result["run_id"])
    assert output.stat().st_size == result["manifest"]["video"]["bytes"]
    assert output.read_bytes()[4:8] == b"ftyp"
    assert core.validate_project(pid)["profile"]["width"] == dimensions[0]
    assert core.validate_project(pid)["profile"]["height"] == dimensions[1]
    assert not core.store.conn.execute("SELECT * FROM llm_usage").fetchall()
    core.store.close()
