"""A Count changes captured text, not narrative meaning, hierarchy or visibility."""

import xml.etree.ElementTree as ET
from copy import deepcopy

import pytest
from test_v2_count_contract import count_action, count_policy
from test_v2_group_annotation import consumer_clock
from test_v2_isolate_action import isolate_documents
from v2_fixtures import digest

from atme.render.v2_state import V2FrameError, evaluate_frame
from atme.render.v2_svg import compose_png_frame, compose_svg_frame


def count_documents(policy=None):
    policy = policy or count_policy()
    layout, timeline = isolate_documents("text")
    layout["objects"][2]["text"] = policy["start_text"]
    timeline["actions"][2]["action"] = count_action(policy)
    timeline["layout_sha256"] = digest(layout)
    return layout, timeline


def test_count_persists_formatted_text_without_new_semantic_state_and_seeks_exactly():
    layout, timeline = count_documents()
    original = deepcopy((layout, timeline))
    _, replay, _ = consumer_clock(layout, timeline)
    times = (3999, 4000, 4450, 4899, 4900, 6000)
    frames = [evaluate_frame(layout, timeline, time) for time in times]
    target = [frame.object("object-evidence") for frame in frames]
    assert [getattr(obj, "display_text", None) for obj in target] == [None, "0 widgets", "5 widgets", "9 widgets", "10 widgets", "10 widgets"]
    assert all(obj.visible and obj.state == "visible" and obj.opacity == 1 for obj in target)
    assert dict(replay.at(4899).state_versions)["object-evidence"] == 1
    assert dict(replay.at(4900).state_versions)["object-evidence"] == 2
    for time, expected in zip(times, ("0 widgets", "0 widgets", "5 widgets", "9 widgets", "10 widgets", "10 widgets"), strict=True):
        root = ET.fromstring(compose_svg_frame(layout, timeline, time).svg)
        node = root.find(".//{*}g[@data-object-id='object-evidence']")
        assert expected in "".join(node.itertext())
    assert compose_png_frame(layout, timeline, 3999).png != compose_png_frame(layout, timeline, 4450).png
    assert compose_png_frame(layout, timeline, 4900).png == compose_png_frame(layout, timeline, 6000).png
    assert evaluate_frame(layout, timeline, 4450) == frames[2]
    assert (layout, timeline) == original


def test_count_uses_exact_integer_clock_at_non_binary_step_boundaries():
    layout, timeline = count_documents(count_policy(end_value="3", end_text="3 widgets", step_count=3))
    row = timeline["actions"][2]
    row["end_ms"] = 7000
    assert evaluate_frame(layout, timeline, 4999).object("object-evidence").display_text == "0 widgets"
    assert evaluate_frame(layout, timeline, 5000).object("object-evidence").display_text == "1 widgets"
    assert evaluate_frame(layout, timeline, 6000).object("object-evidence").display_text == "2 widgets"
    assert evaluate_frame(layout, timeline, 7000).object("object-evidence").display_text == "3 widgets"


@pytest.mark.parametrize("stale", [False, True])
def test_sequential_count_binds_captured_previous_display(stale):
    layout, timeline = count_documents()
    second = deepcopy(timeline["actions"][2])
    second["action"] = count_action(count_policy(start_value="9" if stale else "10", end_value="20",
        start_text="9 widgets" if stale else "10 widgets", end_text="20 widgets"))
    second["action"].update(action_id="count-2", trigger={"kind": "absolute", "at_ms": 4900})
    second.update(start_ms=4900, end_ms=5800)
    second["resolved_trigger"].update(source=second["action"]["trigger"], alignment_anchor_ms=4900,
                                     resolved_at_ms=4900, matched_text=None, matched_occurrence=None)
    timeline["actions"].append(second)
    timeline["coverage"][2]["action_ids"].append("count-2")
    if stale:
        with pytest.raises(V2FrameError, match="captured.*text"):
            evaluate_frame(layout, timeline, 0)
    else:
        _, replay, _ = consumer_clock(layout, timeline)
        assert replay.at(4900).object("object-evidence").display_text == "10 widgets"
        assert replay.at(5350).object("object-evidence").display_text == "15 widgets"
        assert replay.at(5800).object("object-evidence").display_text == "20 widgets"
        assert dict(replay.at(5800).state_versions)["object-evidence"] == 3


@pytest.mark.parametrize("start,valid", [("10.4", False), ("10.0", True)])
def test_repeated_count_cannot_hide_numeric_jump_behind_rounded_display(start, valid):
    layout, timeline = count_documents()
    second = deepcopy(timeline["actions"][2])
    second["action"] = count_action(count_policy(start_value=start, end_value="20", start_text="10 widgets",
                                               end_text="20 widgets"))
    second["action"].update(action_id="count-2", trigger={"kind": "absolute", "at_ms": 4900})
    second.update(start_ms=4900, end_ms=5800)
    second["resolved_trigger"].update(source=second["action"]["trigger"], alignment_anchor_ms=4900,
                                     resolved_at_ms=4900, matched_text=None, matched_occurrence=None)
    timeline["actions"].append(second)
    timeline["coverage"][2]["action_ids"].append("count-2")
    if valid:
        assert evaluate_frame(layout, timeline, 5800).object("object-evidence").display_text == "20 widgets"
    else:
        with pytest.raises(V2FrameError, match="captured.*numeric"):
            evaluate_frame(layout, timeline, 0)


@pytest.mark.parametrize("field,value,match", [
    ("text", "invented start", "captured.*text"),
    ("visible", False, "visible.*count"),
    ("opacity", 0, "visible.*count"),
    ("object_type", "list", "single-line.*text"),
])
def test_count_rejects_stale_text_or_unsupported_unready_target(field, value, match):
    layout, timeline = count_documents()
    layout["objects"][2][field] = value
    if field == "visible":
        timeline["initial_object_states"][2][field] = value
    timeline["layout_sha256"] = digest(layout)
    with pytest.raises(V2FrameError, match=match):
        evaluate_frame(layout, timeline, 0)


def test_bare_legacy_count_is_not_executable():
    layout, timeline = count_documents()
    timeline["actions"][2]["action"].pop("count_policy")
    with pytest.raises(V2FrameError, match="count.*explicit policy"):
        evaluate_frame(layout, timeline, 0)


@pytest.mark.parametrize("easing,value", [("linear", 4), ("ease_in", 2), ("ease_out", 6), ("ease_in_out", 4)])
def test_count_named_easing_preserves_exact_numeric_sampling(easing, value):
    layout, timeline = count_documents(count_policy(start_value="0", end_value="8", start_text="0",
        end_text="8", step_count=8, unit="", unit_placement="none", separator=""))
    timeline["actions"][2]["action"]["easing"] = easing
    frame = evaluate_frame(layout, timeline, 4450).object("object-evidence")
    assert frame.display_text == str(value)
    assert frame.count_value == (value, 1)
    assert evaluate_frame(layout, timeline, 4900).object("object-evidence").count_value == (8, 1)


def test_count_requires_active_board_and_uncomposed_target_writes():
    layout, timeline = count_documents()
    layout["activations"][0]["end_ms"] = 4800
    timeline["layout_sha256"] = digest(layout)
    with pytest.raises(V2FrameError, match="active board"):
        evaluate_frame(layout, timeline, 0)
    layout, timeline = count_documents()
    second = deepcopy(timeline["actions"][2])
    second["action"].update(action_id="overlap-count", trigger={"kind": "absolute", "at_ms": 4500})
    second.update(start_ms=4500, end_ms=5400)
    second["resolved_trigger"].update(source=second["action"]["trigger"], alignment_anchor_ms=4500,
                                      resolved_at_ms=4500, matched_text=None, matched_occurrence=None)
    timeline["actions"].append(second)
    timeline["coverage"][2]["action_ids"].append("overlap-count")
    with pytest.raises(V2FrameError, match="overlapping actions"):
        evaluate_frame(layout, timeline, 0)
