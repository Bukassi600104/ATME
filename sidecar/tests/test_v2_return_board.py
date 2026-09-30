"""A return cut resumes an exact prior board activation and retained state."""

from __future__ import annotations

from copy import deepcopy

import pytest
from test_v2_svg import primitive_documents
from v2_fixtures import digest, executable_layout_v2, visual_plan_v2

from atme.render.v2_state import UnsupportedVisualAction, V2FrameError, evaluate_frame
from atme.render.v2_svg import compose_png_frame, compose_svg_frame
from atme.store.contracts_v2 import (
    ResolvedVisualTimelineV2,
    validate_plan_evidence_completeness,
    validate_plan_layout,
)


def return_documents():
    layout, timeline = primitive_documents()
    layout["boards"][0]["expected_prior_state"] = "system_established"
    layout["activations"] = [
        {**layout["activations"][0], "end_ms": 3500},
        {**layout["activations"][0], "activation_id": "activation-return",
         "start_ms": 5000, "reason": "Revisit the established model"},
    ]
    timeline["layout_sha256"] = digest(layout)
    last = timeline["actions"][2]
    last["start_ms"] = 6000
    last["end_ms"] = 6900
    last["resolved_trigger"]["alignment_anchor_ms"] = 6000
    last["resolved_trigger"]["resolved_at_ms"] = 6000
    trigger = {"kind": "absolute", "at_ms": 5000}
    timeline["actions"].insert(2, {
        "action": {
            "action_id": "return-1", "source_instruction_id": "instruction-3",
            "board_id": "board-main", "semantic_reason": "Return to the developed explanation",
            "trigger": trigger, "easing": "step", "expected_state": "system_established",
            "post_state": "system_developed", "fallback": {"fallback_id": "fallback-3",
                                                      "on_failure": "block"},
            "coverage_id": "coverage-3", "verb": "return_board",
            "destination_board_id": "board-main", "destination_state": "system_developed",
            "source_board_id": "board-main", "source_activation_id": "activation-1",
            "prior_destination_activation_id": "activation-1",
            "destination_activation_id": "activation-return",
            "expected_object_states": {"object-system": "visible", "object-label": "visible",
                                       "object-evidence": "hidden"},
            "expected_object_state_versions": {"object-system": 2, "object-label": 2,
                                               "object-evidence": 1},
        },
        "start_ms": 5000, "end_ms": 5001,
        "resolved_trigger": {"source": trigger, "alignment_anchor_ms": 5000,
                             "matched_text": None, "matched_occurrence": None,
                             "resolved_at_ms": 5000, "confidence": 1, "exact": True},
    })
    timeline["coverage"][2]["action_ids"].append("return-1")
    return layout, timeline


def test_return_cuts_to_same_developed_board_without_resetting_its_objects():
    layout, timeline = return_documents()
    before = evaluate_frame(layout, timeline, 3499)
    gap = evaluate_frame(layout, timeline, 4500)
    returned = evaluate_frame(layout, timeline, 5000)
    assert gap.active_board_id is None
    assert returned.active_board_id == "board-main"
    assert before.object("object-system").state == returned.object("object-system").state
    assert before.object("object-label").state == returned.object("object-label").state
    assert returned.object("object-evidence").state == "hidden"
    assert evaluate_frame(layout, timeline, 6500).object("object-evidence").state == "hidden"
    assert evaluate_frame(layout, timeline, 6900).object("object-evidence").state == "visible"
    assert compose_svg_frame(layout, timeline, 5000).svg == compose_svg_frame(
        layout, timeline, 5000,
    ).svg
    assert compose_png_frame(layout, timeline, 5000).png != compose_png_frame(
        layout, timeline, 4500,
    ).png


def test_return_from_an_intervening_board_restores_prior_model_without_recreation():
    layout, timeline = return_documents()
    interlude = deepcopy(layout["objects"][0])
    interlude.update(object_id="object-interlude", board_id="board-interlude",
                     object_type="rectangle", initial_state="visible", visible=True,
                     geometry={"bounds": {"x": 200, "y": 200, "width": 450, "height": 300},
                               "points": [], "corner_radius": None})
    layout["objects"].append(interlude)
    board = deepcopy(layout["boards"][0])
    board.update(board_id="board-interlude", object_ids=["object-interlude"],
                 density_limit=1, persistence_policy="single_beat",
                 activation_policy="once", expected_prior_state=None)
    layout["boards"].append(board)
    layout["activations"].insert(1, {
        "activation_id": "activation-interlude", "board_id": "board-interlude",
        "start_ms": 3500, "end_ms": 5000, "reason": "Inspect a second board",
    })
    timeline["initial_object_states"].append({
        "object_id": "object-interlude", "state": "visible", "state_version": 1,
        "visible": True,
    })
    returned = timeline["actions"][2]["action"]
    returned["source_board_id"] = "board-interlude"
    returned["source_activation_id"] = "activation-interlude"
    timeline["layout_sha256"] = digest(layout)
    interlude_frame = evaluate_frame(layout, timeline, 4000)
    return_frame = evaluate_frame(layout, timeline, 5000)
    assert interlude_frame.active_board_id == "board-interlude"
    assert return_frame.active_board_id == "board-main"
    assert not interlude_frame.object("object-system").visible
    assert return_frame.object("object-system").state == "visible"
    assert not return_frame.object("object-interlude").visible


@pytest.mark.parametrize("change,expected", [
    (lambda l, t: t["actions"][2]["action"].update(
        source_activation_id="activation-return"), "activation lineage"),
    (lambda l, t: t["actions"][2]["action"]["expected_object_states"].update(
        {"object-system": "hidden"}), "retained board state"),
    (lambda l, t: t["actions"][2]["action"]["expected_object_state_versions"].update(
        {"object-system": 3}), "retained board state"),
    (lambda l, t: t["actions"][2]["action"].update(
        destination_activation_id="activation-1"), "activation lineage"),
])
def test_return_rejects_wrong_activation_or_retained_state(change, expected):
    layout, timeline = return_documents()
    change(layout, timeline)
    with pytest.raises(V2FrameError, match=expected):
        evaluate_frame(layout, timeline, 5000)


def test_old_return_action_loads_but_cannot_execute():
    layout, timeline = return_documents()
    old = deepcopy(timeline)
    for key in ("source_board_id", "source_activation_id",
                "prior_destination_activation_id", "destination_activation_id",
                "expected_object_states", "expected_object_state_versions"):
        old["actions"][2]["action"].pop(key)
    ResolvedVisualTimelineV2.model_validate(old)
    with pytest.raises(UnsupportedVisualAction, match="complete activation"):
        evaluate_frame(layout, old, 5000)


def test_new_plan_write_requires_full_return_continuity_declaration():
    plan = visual_plan_v2()
    plan["boards"][0]["expected_prior_state"] = "system_established"
    plan["beats"][1]["continuity"]["developed_return_state"] = "system_developed"
    plan["beats"][1]["continuity"]["expected_state_versions"]["object-system"] = 2
    _, timeline = return_documents()
    action = deepcopy(timeline["actions"][2]["action"])
    plan["actions"].append(action)
    plan["beats"][1]["action_ids"].append("return-1")
    plan["coverage"][2]["action_ids"].append("return-1")
    validate_plan_evidence_completeness(plan)
    layout = executable_layout_v2(plan)
    layout["activations"] = [
        {**layout["activations"][0], "end_ms": 3500},
        {**layout["activations"][0], "activation_id": "activation-return",
         "start_ms": 5000, "reason": "Return to the developed board"},
    ]
    validate_plan_layout(plan, layout)
    wrong_layout = deepcopy(layout)
    wrong_layout["activations"][1]["activation_id"] = "unrelated-activation"
    with pytest.raises(ValueError, match="activation lineage"):
        validate_plan_layout(plan, wrong_layout)
    wrong_plan = deepcopy(plan)
    wrong_plan["beats"][1]["continuity"]["expected_state_versions"]["object-system"] = 99
    with pytest.raises(ValueError, match="continuity"):
        validate_plan_evidence_completeness(wrong_plan)
    wrong_plan = deepcopy(plan)
    wrong_plan["actions"][-1]["destination_board_id"] = "other-board"
    with pytest.raises(ValueError):
        validate_plan_evidence_completeness(wrong_plan)
    plan["actions"][-1].pop("prior_destination_activation_id")
    with pytest.raises(ValueError, match="complete activation"):
        validate_plan_evidence_completeness(plan)


def test_nonreturnable_board_policy_cannot_be_bypassed_at_frame_runtime():
    layout, timeline = return_documents()
    layout["boards"][0]["persistence_policy"] = "single_beat"
    layout["boards"][0]["activation_policy"] = "once"
    timeline["layout_sha256"] = digest(layout)
    with pytest.raises(V2FrameError, match="returnable policy"):
        evaluate_frame(layout, timeline, 5000)
