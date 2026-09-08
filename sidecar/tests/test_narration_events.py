from copy import deepcopy

import pytest

from atme.narration_events import resolve_narration_events, TriggerResolutionError
from atme.pipeline import _retime_layout
from test_board_continuity import board_doc


def inputs():
    doc = board_doc()
    doc["elements"][0]["narration_trigger"] = {"phrase": "Queue grows"}
    words = [{"word": token, "start_ms": 100 + i * 200, "end_ms": 250 + i * 200,
              "scene_id": 1, "confidence": .9} for i, token in enumerate(
                  ["Queue,", "grows", "service", "slows"])]
    return doc, words


def test_multiple_actions_in_one_scene_get_distinct_word_times():
    doc, words = inputs()
    doc["elements"][1]["narration_trigger"] = {"phrase": "service slows"}
    result, report = resolve_narration_events(doc, words, 6000)
    assert [e["appear_at_ms"] for e in result["elements"][:2]] == [100, 500]
    assert all(r["status"] == "resolved" for r in report)
    assert doc["elements"][0]["appear_at_ms"] == 0
    assert _retime_layout(result, [], [], words, 6000) == result


@pytest.mark.parametrize("problem,status", [
    ("missing", "missing"), ("repeat", "ambiguous"),
    ("confidence", "low_confidence"), ("unknown", "confidence_unavailable"),
    ("offset", "out_of_bounds"), ("board", "inactive_board"),
])
def test_uncertainty_blocks_instead_of_guessing(problem, status):
    doc, words = inputs()
    trigger = doc["elements"][0]["narration_trigger"]
    if problem == "missing":
        trigger["phrase"] = "not spoken"
    elif problem == "repeat":
        words += [{**w, "start_ms": w["start_ms"] + 1000} for w in words[:2]]
    elif problem == "confidence":
        words[0]["confidence"] = .2
    elif problem == "unknown":
        words[0].pop("confidence")
    elif problem == "offset":
        trigger["offset_ms"] = -200
    else:
        trigger["offset_ms"] = 2500
    before = deepcopy(doc)
    with pytest.raises(TriggerResolutionError) as error:
        resolve_narration_events(doc, words, 6000)
    assert error.value.report[0]["status"] == status
    assert doc == before


def test_explicit_occurrence_disambiguates_repeated_phrase():
    doc, words = inputs()
    words += [{**w, "start_ms": w["start_ms"] + 1000} for w in words[:2]]
    doc["elements"][0]["narration_trigger"]["occurrence"] = 2
    result, report = resolve_narration_events(doc, words, 6000)
    assert result["elements"][0]["appear_at_ms"] == 1100
    assert report[0]["match_count"] == 2


def test_scene_scope_prevents_matching_another_scene():
    doc, words = inputs()
    for word in words:
        word["scene_id"] = 2
    with pytest.raises(TriggerResolutionError):
        resolve_narration_events(doc, words, 6000)
