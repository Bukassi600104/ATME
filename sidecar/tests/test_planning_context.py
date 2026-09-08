from copy import deepcopy
import json

import pytest

from atme.planning_context import build_planning_context


def inputs():
    script = {"scenes": [{"scene_id": 1, "spoken_text": "A queue grows.",
                           "visual_directive": "draw queue"},
                          {"scene_id": 2, "spoken_text": "Then it drains."}]}
    words = [{"word": "queue", "scene_id": 1, "start_ms": 100, "end_ms": 400, "confidence": 0.9},
             {"word": "drains", "scene_id": 2, "start_ms": 900, "end_ms": 1200, "confidence": 0.8}]
    return script, words


def test_final_audio_context_preserves_actual_bounds_and_inputs():
    script, words = inputs()
    before = deepcopy((script, words))
    result = build_planning_context(script, words, 1500, "a" * 64)
    assert result["status"] == "ready"
    assert result["timebase"] == "final_audio_ms"
    assert result["scenes"][0]["start_ms"] == 100
    assert result["scenes"][1]["end_ms"] == 1200
    assert result["scenes"][0]["narration"] == "A queue grows."
    assert (script, words) == before
    result["scenes"][0]["words"][0]["word"] = "changed"
    assert words == before[1]


@pytest.mark.parametrize("score", [None, False, float("nan"), 0.4, 2])
def test_uncertain_alignment_is_not_planning_ready(score):
    script, words = inputs()
    words[0]["confidence"] = score
    result = build_planning_context(script, words, 1500, "a" * 64)
    assert result["status"] == "needs_review"
    assert result["issues"][0]["code"] == "uncertain_word"


def test_missing_scene_has_no_invented_timestamp():
    script, words = inputs()
    result = build_planning_context(script, words[:1], 1500, "a" * 64)
    assert result["scenes"][1]["start_ms"] is None
    assert result["status"] == "needs_review"


@pytest.mark.parametrize("problem", ["unknown_scene", "out_of_bounds", "reverse", "overlap", "flagged"])
def test_bad_word_evidence_requires_review(problem):
    script, words = inputs()
    if problem == "unknown_scene":
        words[0]["scene_id"] = 99
    elif problem == "out_of_bounds":
        words[0]["end_ms"] = 1600
    elif problem == "reverse":
        words.reverse()
    elif problem == "overlap":
        words[1]["start_ms"] = 300
    else:
        words[0]["flagged"] = True
    assert build_planning_context(script, words, 1500, "a" * 64)["status"] == "needs_review"


def test_source_identity_changes_with_script():
    script, words = inputs()
    first = build_planning_context(script, words, 1500, "a" * 64)
    script["scenes"][0]["spoken_text"] = "A different approved narration."
    second = build_planning_context(script, words, 1500, "b" * 64)
    assert first["script_sha256"] != second["script_sha256"]
    assert first["audio_sha256"] != second["audio_sha256"]


@pytest.mark.parametrize("blocked", [False, True])
def test_alignment_stage_saves_context_before_visual_trigger_review(tmp_path, monkeypatch, blocked):
    import numpy as np
    from atme import pipeline
    from atme.narration_events import TriggerResolutionError
    from test_board_continuity import board_doc

    script, words = inputs()
    script["scenes"][1]["visual_directive"] = "draw evidence"
    words[1].update(start_ms=2100, end_ms=2400)
    monkeypatch.setattr(pipeline.sf, "read", lambda *a, **k: (np.zeros(10), 16000))
    monkeypatch.setattr(pipeline, "align_words", lambda *a, **k: words)
    audio = {"final_wav": "unused.wav", "scene_starts_ms": [0, 2000],
             "duration_ms": 6000, "sha256": "a" * 64, "edl": []}
    layout = board_doc()
    if blocked:
        layout["elements"][0]["narration_trigger"] = {"phrase": "missing phrase"}
        with pytest.raises(TriggerResolutionError):
            pipeline.align_stage(tmp_path, script, audio, "segments", layout_dict=layout)
        assert not (tmp_path / "align_state.json").exists()
    else:
        state = pipeline.align_stage(tmp_path, script, audio, "segments", layout_dict=layout)
        assert state["planning_context_file"] == str(tmp_path / "planning_context.json")
    saved = json.loads((tmp_path / "planning_context.json").read_text())
    assert saved["scenes"][1]["start_ms"] == 2100
    assert saved["audio_sha256"] == audio["sha256"]
