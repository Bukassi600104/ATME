"""R09: reveal must be instantaneous, deterministic and retained in alignment output."""
from copy import deepcopy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from atme.render.animator import build_draw_windows
from atme.render.svg_builder import element_group, element_stroke_info
from atme.store.contracts import LayoutDoc, CueTimeline
from conftest import load_schema
from test_board_continuity import board_doc, renderer


@pytest.mark.parametrize("kind", ["rectangle", "text", "arrow"])
def test_reveal_is_complete_at_exact_start_in_svg_and_raster(kind):
    doc = board_doc()
    el = doc["elements"][0]
    if kind == "text":
        el = {"id": "el-title", "scene_id": 1, "board_id": "queue",
              "appear_at_ms": 0, "type": "text", "x": 50, "y": 50, "text": "Queue"}
    elif kind == "arrow":
        el = deepcopy(doc["elements"][1])
        el.pop("visibility_intervals")
    el.update(enter_action="reveal", appear_at_ms=100)
    doc["elements"] = [el]
    LayoutDoc.model_validate(doc)
    assert build_draw_windows([el])[el["id"]] == 0
    info = element_stroke_info(el, doc["seed"])
    assert element_group(el, info, 99, 700) == ""
    assert element_group(el, info, 100, 700) == element_group(el, info, 1000, 700)
    r = renderer(doc)
    before = r.frame(99).tobytes()
    at_start = r.frame(100).tobytes()
    assert before != at_start
    assert at_start == r.frame(1000).tobytes()
    assert at_start == r.frame(4000).tobytes()  # return does not replay reveal
    assert before == r.frame(99).tobytes()  # reverse seek
    assert r.overlay_frames == 0


def test_legacy_draw_is_unchanged():
    doc = board_doc()
    original = build_draw_windows(doc["elements"])
    for el in doc["elements"]:
        el["enter_action"] = "draw"
    assert build_draw_windows(doc["elements"]) == original
    r = renderer(doc)
    assert r.frame(10).tobytes() != r.frame(400).tobytes()


def test_unknown_action_rejected_without_board_metadata():
    doc = board_doc()
    doc.pop("board_timeline")
    for el in doc["elements"]:
        el.pop("board_id")
        el.pop("visibility_intervals", None)
    doc["elements"][0]["enter_action"] = "teleport"
    with pytest.raises(ValueError):
        LayoutDoc.model_validate(doc)
    with pytest.raises(ValueError, match="unsupported enter_action"):
        build_draw_windows(doc["elements"])


def test_alignment_preserves_reveal_directive(tmp_path, monkeypatch):
    import numpy as np
    import soundfile as sf
    from atme import pipeline

    wav = tmp_path / "final.wav"
    sf.write(wav, np.zeros(16000), 16000)
    monkeypatch.setattr(pipeline, "align_words", lambda *a, **k: [
        {"word": "Queue", "start_ms": 0, "end_ms": 500, "scene_id": 1, "confidence": .9}])
    doc = board_doc()
    doc["elements"][0]["enter_action"] = "reveal"
    doc["elements"][0]["narration_trigger"] = {"phrase": "Queue"}
    script = {"topic": "Queues", "scenes": [
        {"scene_id": 1, "spoken_text": "Queue", "visual_directive": "Show queue"}]}
    state = pipeline.align_stage(tmp_path, script, {
        "final_wav": str(wav), "scene_starts_ms": [0], "duration_ms": 6000,
        "sha256": "0" * 64, "edl": []}, "segments", layout_dict=doc)
    cues = json.loads(Path(state["cues_file"]).read_text(encoding="utf-8"))
    assert cues["directives"][0]["action"] == "reveal"
    assert cues["directives"][1]["action"] == "draw"
    CueTimeline.model_validate(cues)
    Draft202012Validator(load_schema("cue-timeline")).validate(cues)
    report = json.loads(Path(state["narration_events_file"]).read_text())
    assert report[0]["status"] == "resolved"
    assert report[0]["confidence"] == .9
