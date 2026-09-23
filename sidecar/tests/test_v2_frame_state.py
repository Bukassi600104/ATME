"""Deterministic first slice of the v2 action runtime."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import FrozenInstanceError
from math import inf, nan

import pytest
from atme.render.v2_state import UnsupportedVisualAction, V2FrameError, evaluate_frame
from atme.store.contracts_v2 import Point, TargetAction
from pydantic import ValidationError
from v2_fixtures import (
    common_action,
    digest,
    executable_layout_v2,
    resolved_timeline_v2,
    visual_plan_v2,
)


def supported_documents(third_action="reveal"):
    plan = visual_plan_v2()
    target_action = third_action in {
        "reveal", "write", "draw", "enter", "exit", "progressive_reveal",
    }
    if third_action in ("exit", "fade"):
        plan["objects"][2]["initial_state"] = "visible"
    plan["actions"][2] = {
        **common_action("action-3", "instruction-3"),
        "verb": third_action,
        "target_ids": ["object-evidence"],
        **({"annotation": None} if target_action else {
            "destination": None if third_action == "fade" else {
                "position": {"x": 120 if third_action == "move" else 0,
                             "y": 40 if third_action == "move" else 0},
                "scale_x": 1.2 if third_action == "scale" else 1,
                "scale_y": 1.2 if third_action == "scale" else 1,
                "rotation_degrees": 30 if third_action == "rotate" else 0,
                "origin": {"x": 0.5, "y": 0.5},
            },
            "opacity": 0.2 if third_action == "fade" else None,
        }),
    }
    if third_action in ("exit", "fade"):
        plan["actions"][2]["expected_state"] = "visible"
    if third_action == "exit":
        plan["actions"][2]["post_state"] = "removed"
    layout = executable_layout_v2(plan)
    if third_action in ("exit", "fade"):
        layout["objects"][2]["visible"] = True
        layout["objects"][2]["initial_state"] = "visible"
    timeline = resolved_timeline_v2(plan, layout)
    if third_action in ("exit", "fade"):
        timeline["initial_object_states"][2]["state"] = "visible"
        timeline["initial_object_states"][2]["visible"] = True
    return layout, timeline


def test_seeking_backward_and_forward_is_byte_identical():
    layout, timeline = supported_documents()
    first = evaluate_frame(layout, timeline, 450)
    evaluate_frame(layout, timeline, 5500)
    evaluate_frame(layout, timeline, 2200)
    assert evaluate_frame(layout, timeline, 450) == first
    assert first.object("object-system").visible
    assert 0 < first.object("object-system").reveal_fraction < 1
    assert not first.object("object-label").visible
    assert evaluate_frame(layout, timeline, 900).object("object-system").reveal_fraction == 1


def test_each_reveal_uses_its_own_timing_window_and_board():
    layout, timeline = supported_documents()
    before = evaluate_frame(layout, timeline, 1999)
    during = evaluate_frame(layout, timeline, 2450)
    after = evaluate_frame(layout, timeline, 5000)
    assert before.active_board_id == "board-main"
    assert not before.object("object-label").visible
    assert during.object("object-label").visible
    assert 0 < during.object("object-label").reveal_fraction < 1
    assert after.object("object-evidence").reveal_fraction == 1
    layout["activations"][0]["end_ms"] = 9000
    timeline["layout_sha256"] = digest(layout)
    assert all(not item.visible for item in evaluate_frame(layout, timeline, 9500).objects)


@pytest.mark.parametrize("verb", ["reveal", "write", "draw", "progressive_reveal"])
def test_reveal_family_has_exact_start_middle_and_end(verb):
    layout, timeline = supported_documents(verb)
    assert not evaluate_frame(layout, timeline, 3999).object("object-evidence").visible
    start = evaluate_frame(layout, timeline, 4000).object("object-evidence")
    middle = evaluate_frame(layout, timeline, 4450).object("object-evidence")
    end = evaluate_frame(layout, timeline, 4900).object("object-evidence")
    assert start.visible and start.reveal_fraction == 0
    assert middle.visible and middle.reveal_fraction == pytest.approx(0.75)
    assert end.visible and end.reveal_fraction == 1 and end.state == "visible"


def test_enter_exit_and_fade_have_distinct_visibility_semantics():
    enter_layout, enter_timeline = supported_documents("enter")
    assert evaluate_frame(enter_layout, enter_timeline, 4000).object("object-evidence").opacity == 0
    assert evaluate_frame(enter_layout, enter_timeline, 4450).object("object-evidence").opacity == 0.75
    exit_layout, exit_timeline = supported_documents("exit")
    assert evaluate_frame(exit_layout, exit_timeline, 3999).object("object-evidence").visible
    assert evaluate_frame(exit_layout, exit_timeline, 4450).object("object-evidence").opacity == 0.25
    assert not evaluate_frame(exit_layout, exit_timeline, 4900).object("object-evidence").visible
    assert evaluate_frame(exit_layout, exit_timeline, 4900).object("object-evidence").state == "removed"
    fade_layout, fade_timeline = supported_documents("fade")
    assert evaluate_frame(fade_layout, fade_timeline, 4450).object("object-evidence").opacity == pytest.approx(0.4)
    assert evaluate_frame(fade_layout, fade_timeline, 4900).object("object-evidence").opacity == pytest.approx(0.2)


@pytest.mark.parametrize("verb", ["move", "scale", "rotate"])
def test_transform_interpolation_is_pure_and_channel_specific(verb):
    layout, timeline = supported_documents(verb)
    midway = evaluate_frame(layout, timeline, 4450).object("object-evidence")
    assert midway.transform.position.x == pytest.approx(90 if verb == "move" else 0)
    assert midway.transform.position.y == pytest.approx(30 if verb == "move" else 0)
    assert midway.transform.scale_x == pytest.approx(1.15 if verb == "scale" else 1)
    assert midway.transform.rotation_degrees == pytest.approx(22.5 if verb == "rotate" else 0)
    assert (evaluate_frame(layout, timeline, 4900).object("object-evidence")
            .transform.position.x) == (120 if verb == "move" else 0)
    assert evaluate_frame(layout, timeline, 100).object("object-evidence").transform.position.x == 0


def test_unimplemented_authored_action_fails_before_any_frame_is_shown():
    plan = visual_plan_v2()
    layout = executable_layout_v2(plan)
    timeline = resolved_timeline_v2(plan, layout)
    with pytest.raises(UnsupportedVisualAction, match="insert_evidence"):
        evaluate_frame(layout, timeline, 0)


@pytest.mark.parametrize("time", [-1, 10000, 1.5, True])
def test_invalid_frame_time_is_rejected(time):
    layout, timeline = supported_documents()
    with pytest.raises(V2FrameError, match="frame time"):
        evaluate_frame(layout, timeline, time)


def test_layout_and_timeline_identity_must_match():
    layout, timeline = supported_documents()
    altered = deepcopy(timeline)
    altered["layout_id"] = "a-different-layout"
    with pytest.raises(V2FrameError, match="same composition"):
        evaluate_frame(layout, altered, 0)
    altered = deepcopy(layout)
    altered["objects"][0]["geometry"]["bounds"]["width"] += 1
    with pytest.raises(V2FrameError, match="same composition"):
        evaluate_frame(altered, timeline, 0)


def test_frame_state_is_deeply_immutable():
    layout, timeline = supported_documents()
    frame = evaluate_frame(layout, timeline, 450)
    with pytest.raises(FrozenInstanceError):
        frame.object("object-system").visible = False
    with pytest.raises(FrozenInstanceError):
        frame.object("object-system").transform.position.x = 999
    assert evaluate_frame(layout, timeline, 450) == frame


def test_unrelated_transform_channels_and_silent_fade_destination_are_rejected():
    layout, timeline = supported_documents("move")
    timeline["actions"][2]["action"]["destination"]["scale_x"] = 1.2
    with pytest.raises(V2FrameError, match="unrelated transform channel"):
        evaluate_frame(layout, timeline, 0)
    layout, timeline = supported_documents("fade")
    timeline["actions"][2]["action"]["destination"] = {
        "position": {"x": 1, "y": 0}, "scale_x": 1, "scale_y": 1,
        "rotation_degrees": 0, "origin": {"x": 0.5, "y": 0.5},
    }
    with pytest.raises(V2FrameError, match="ignored transform destination"):
        evaluate_frame(layout, timeline, 0)


def test_overlapping_actions_on_one_object_require_an_explicit_rule():
    layout, timeline = supported_documents()
    second = timeline["actions"][1]
    second["action"]["target_ids"] = ["object-system"]
    second["action"]["expected_state"] = "visible"
    second["start_ms"] = 500
    second["end_ms"] = 1400
    second["resolved_trigger"]["alignment_anchor_ms"] = 500
    second["resolved_trigger"]["resolved_at_ms"] = 500
    with pytest.raises(V2FrameError, match="overlapping actions"):
        evaluate_frame(layout, timeline, 0)


@pytest.mark.parametrize("easing,expected", [
    ("linear", 0.5), ("ease_in", 0.25), ("ease_out", 0.75),
    ("ease_in_out", 0.5), ("step", 0.0),
])
def test_all_easings_have_exact_midpoint_and_completion(easing, expected):
    layout, timeline = supported_documents()
    timeline["actions"][2]["action"]["easing"] = easing
    assert evaluate_frame(layout, timeline, 4450).object("object-evidence").reveal_fraction == pytest.approx(expected)
    assert evaluate_frame(layout, timeline, 4900).object("object-evidence").reveal_fraction == 1


def test_chained_transforms_preserve_completed_prior_channels():
    layout, timeline = supported_documents("scale")
    second = timeline["actions"][1]["action"]
    second.pop("annotation")
    second.update({
        "verb": "move", "target_ids": ["object-evidence"],
        "destination": {"position": {"x": 100, "y": 0}, "scale_x": 1, "scale_y": 1,
                        "rotation_degrees": 0, "origin": {"x": 0.5, "y": 0.5}},
        "opacity": None,
    })
    timeline["actions"][2]["action"]["expected_state"] = "visible"
    timeline["actions"][2]["action"]["destination"]["position"]["x"] = 100
    middle = evaluate_frame(layout, timeline, 4450).object("object-evidence")
    assert middle.transform.position.x == 100
    assert middle.transform.scale_x == pytest.approx(1.15)
    assert evaluate_frame(layout, timeline, 2450).object("object-evidence").transform.position.x == 75


def test_board_gap_and_return_preserve_underlying_object_state():
    layout, timeline = supported_documents()
    layout["activations"] = [
        {**layout["activations"][0], "end_ms": 4000},
        {**layout["activations"][0], "activation_id": "activation-return",
         "start_ms": 5000, "reason": "Return to the established model"},
    ]
    timeline["layout_sha256"] = digest(layout)
    assert evaluate_frame(layout, timeline, 4500).active_board_id is None
    assert not evaluate_frame(layout, timeline, 4500).object("object-system").visible
    returned = evaluate_frame(layout, timeline, 5500)
    assert returned.active_board_id == "board-main"
    assert returned.object("object-system").visible
    assert returned.object("object-system").reveal_fraction == 1


@pytest.mark.parametrize("bad", [nan, inf, -inf])
def test_nonfinite_geometry_or_transform_is_rejected_before_frame_output(bad):
    with pytest.raises(ValidationError):
        Point.model_validate({"x": bad, "y": 0})
    layout, timeline = supported_documents()
    layout["objects"][0]["transform"]["position"]["x"] = bad
    with pytest.raises(V2FrameError, match="finite, canonical JSON"):
        evaluate_frame(layout, timeline, 0)
    layout, timeline = supported_documents()
    layout["objects"][0]["geometry"]["bounds"]["width"] = bad
    with pytest.raises(V2FrameError, match="finite, canonical JSON"):
        evaluate_frame(layout, timeline, 0)
    layout, timeline = supported_documents()
    layout["objects"][0]["opacity"] = bad
    with pytest.raises(V2FrameError, match="finite, canonical JSON"):
        evaluate_frame(layout, timeline, 0)
    layout, timeline = supported_documents()
    timeline["actions"][2]["resolved_trigger"]["confidence"] = bad
    with pytest.raises(ValidationError):
        evaluate_frame(layout, timeline, 0)


def test_exit_declares_permanent_removed_state_and_inputs_are_not_mutated():
    action = {**common_action("action-x", "instruction-x"),
              "verb": "exit", "target_ids": ["object-evidence"], "annotation": None}
    with pytest.raises(ValidationError, match="canonical removed"):
        TargetAction.model_validate(action)
    layout, timeline = supported_documents()
    original_layout, original_timeline = deepcopy(layout), deepcopy(timeline)
    evaluate_frame(layout, timeline, 450)
    assert layout == original_layout and timeline == original_timeline
