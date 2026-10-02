"""Bounded authored-object replacement remains a deterministic paint crossfade."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from copy import deepcopy
from io import BytesIO

import pytest
from PIL import Image
from pydantic import ValidationError
from test_v2_camera_action import append_camera
from test_v2_connector_svg import connector_documents
from test_v2_svg import primitive_documents
from v2_fixtures import digest, visual_plan_v2

from atme.render.v2_state import V2FrameError, evaluate_frame
from atme.render.v2_svg import compose_png_frame, compose_svg_frame
from atme.store.contracts_v2 import VisualPlanV2


def documents():
    layout, timeline = primitive_documents()
    destination = deepcopy(layout["objects"][0])
    destination["object_id"] = "object-replacement"
    destination["style"]["fill"] = "surface.paper"
    destination["style"]["stroke"] = "ink.accent"
    layout["objects"].append(destination)
    layout["boards"][0]["object_ids"].append(destination["object_id"])
    timeline["initial_object_states"].append({
        "object_id": destination["object_id"], "state": "hidden",
        "state_version": 1, "visible": False,
    })
    start, end = 6000, 7000
    trigger = {"kind": "absolute", "at_ms": start}
    timeline["actions"].append({
        "action": {
            "action_id": "replace-1", "source_instruction_id": "instruction-1",
            "board_id": "board-main", "semantic_reason": "Develop the existing model",
            "trigger": trigger, "easing": "linear", "expected_state": "visible",
            "post_state": "visible",
            "fallback": {"fallback_id": "fallback-1", "on_failure": "block"},
            "coverage_id": "coverage-1", "verb": "replace",
            "from_object_id": "object-system", "to_object_id": "object-replacement",
        },
        "start_ms": start, "end_ms": end,
        "resolved_trigger": {
            "source": trigger, "alignment_anchor_ms": start,
            "matched_text": None, "matched_occurrence": None,
            "resolved_at_ms": start, "confidence": 1, "exact": True,
        },
    })
    timeline["coverage"][0]["action_ids"].append("replace-1")
    timeline["layout_sha256"] = digest(layout)
    return layout, timeline


def test_replace_start_middle_end_and_random_seek():
    layout, timeline = documents()
    before = evaluate_frame(layout, timeline, 5999)
    start = evaluate_frame(layout, timeline, 6000)
    middle = evaluate_frame(layout, timeline, 6500)
    end = evaluate_frame(layout, timeline, 7000)
    assert before.object("object-system").visible
    assert not before.object("object-replacement").visible
    assert start.object("object-system").opacity == 1
    assert not start.object("object-replacement").visible
    assert middle.object("object-system").opacity == pytest.approx(0.5)
    assert middle.object("object-replacement").opacity == pytest.approx(0.5)
    assert middle.object("object-replacement").visible
    assert not end.object("object-system").visible
    assert end.object("object-system").state == "removed"
    assert end.object("object-replacement").state == "visible"
    assert end.object("object-replacement").opacity == 1
    assert evaluate_frame(layout, timeline, 6500) == middle
    assert compose_svg_frame(layout, timeline, 6500).svg == compose_svg_frame(layout, timeline, 6500).svg
    first = compose_png_frame(layout, timeline, 6500).png
    compose_png_frame(layout, timeline, 8000)
    assert compose_png_frame(layout, timeline, 6500).png == first
    assert Image.open(BytesIO(first)).size == (1280, 720)


def test_replace_changes_real_pixels_without_mutating_documents():
    layout, timeline = documents()
    original = deepcopy((layout, timeline))
    before = compose_png_frame(layout, timeline, 5999).png
    during = compose_png_frame(layout, timeline, 6500).png
    after = compose_png_frame(layout, timeline, 7000).png
    assert before != during != after
    before_pixel = Image.open(BytesIO(before)).convert("RGB").getpixel((300, 300))
    during_pixel = Image.open(BytesIO(during)).convert("RGB").getpixel((300, 300))
    after_pixel = Image.open(BytesIO(after)).convert("RGB").getpixel((300, 300))
    assert before_pixel != during_pixel != after_pixel
    before_svg = ET.fromstring(compose_svg_frame(layout, timeline, 5999).svg)
    during_svg = ET.fromstring(compose_svg_frame(layout, timeline, 6500).svg)
    after_svg = ET.fromstring(compose_svg_frame(layout, timeline, 7000).svg)
    def painted(root):
        return {node.attrib["data-object-id"]: node.attrib["opacity"]
                for node in root.iter() if "data-object-id" in node.attrib}
    assert "object-replacement" not in painted(before_svg)
    assert painted(during_svg)["object-system"] == "0.5"
    assert painted(during_svg)["object-replacement"] == "0.5"
    assert "object-system" not in painted(after_svg)
    assert painted(after_svg)["object-replacement"] == "1"
    assert (layout, timeline) == original


@pytest.mark.parametrize("change,match", [
    (lambda l, t: t["actions"][-1]["action"].update(to_object_id="object-system"), "distinct"),
    (lambda l, t: l["objects"][-1]["geometry"]["bounds"].update(x=100), "co-located"),
    (lambda l, t: l["objects"][-1].update(z_index=9), "co-located"),
    (lambda l, t: l["objects"][-1]["transform"]["position"].update(x=12), "co-located"),
    (lambda l, t: l["objects"][-1].update(visible=True, initial_state="visible"), "hidden-to-visible|hidden destination"),
    (lambda l, t: t["actions"][-1]["action"].update(post_state="changed"), "post_state must be visible"),
    (lambda l, t: t["actions"][-1]["action"].update(expected_state="hidden"), "precondition"),
    (lambda l, t: l["objects"][-1].update(opacity=0), "hidden destination"),
])
def test_invalid_future_replacement_fails_before_sampling(change, match):
    layout, timeline = documents()
    change(layout, timeline)
    if layout["objects"][-1]["visible"]:
        timeline["initial_object_states"][-1].update(state="visible", visible=True)
    timeline["layout_sha256"] = digest(layout)
    with pytest.raises((V2FrameError, ValidationError), match=match):
        evaluate_frame(layout, timeline, 100)


def test_legacy_morph_without_correspondence_still_fails_closed():
    layout, timeline = documents()
    timeline["actions"][-1]["action"]["verb"] = "morph"
    from atme.store.contracts_v2 import ResolvedVisualTimelineV2

    assert ResolvedVisualTimelineV2.model_validate(timeline).actions[-1].action.expected_state == "visible"
    with pytest.raises(V2FrameError, match="correspondence"):
        evaluate_frame(layout, timeline, 100)


def test_replacement_chain_and_board_return_keep_developed_state():
    layout, timeline = documents()
    another = deepcopy(layout["objects"][-1])
    another["object_id"] = "object-third"
    another["style"]["fill"] = "surface.accent"
    layout["objects"].append(another)
    layout["boards"][0]["object_ids"].append("object-third")
    timeline["initial_object_states"].append({
        "object_id": "object-third", "state": "hidden", "state_version": 1,
        "visible": False,
    })
    second = deepcopy(timeline["actions"][-1])
    second["action"].update(action_id="replace-2", from_object_id="object-replacement",
                            to_object_id="object-third")
    second["action"]["trigger"] = {"kind": "absolute", "at_ms": 8000}
    second.update(start_ms=8000, end_ms=8500)
    second["resolved_trigger"].update(source=second["action"]["trigger"],
                                      alignment_anchor_ms=8000, resolved_at_ms=8000)
    timeline["actions"].append(second)
    timeline["coverage"][0]["action_ids"].append("replace-2")
    layout["activations"][0]["end_ms"] = 9000
    layout["activations"].append({"activation_id": "activation-return",
                                  "board_id": "board-main", "start_ms": 9200,
                                  "end_ms": 10000, "reason": "Return to developed model"})
    timeline["layout_sha256"] = digest(layout)
    before_second = evaluate_frame(layout, timeline, 7999)
    assert before_second.object("object-replacement").visible
    assert not before_second.object("object-third").visible
    after_second = evaluate_frame(layout, timeline, 8500)
    assert not after_second.object("object-replacement").visible
    assert after_second.object("object-third").visible
    gap = evaluate_frame(layout, timeline, 9100)
    assert not gap.object("object-third").visible
    assert evaluate_frame(layout, timeline, 9300).object("object-third").visible


def test_camera_can_follow_destination_but_not_focus_during_replacement():
    layout, timeline = documents()
    append_camera(timeline, "camera-after", "camera_cut", 7500, 7700,
                  target="object-replacement")
    assert evaluate_frame(layout, timeline, 7600).camera.width < 1280
    layout, timeline = documents()
    append_camera(timeline, "camera-overlap", "camera_cut", 6500, 6700,
                  target="object-replacement")
    with pytest.raises(V2FrameError, match="overlaps a focus-object edit"):
        evaluate_frame(layout, timeline, 100)
    layout, timeline = documents()
    append_camera(timeline, "camera-source-after", "camera_cut", 7500, 7700,
                  target="object-system")
    with pytest.raises((V2FrameError, ValidationError),
                       match="revealed visible focus|resurrects removed object"):
        evaluate_frame(layout, timeline, 100)


@pytest.mark.parametrize("easing", ["linear", "ease_in", "ease_out", "ease_in_out", "step"])
def test_replacement_easing_and_exact_boundary(easing):
    layout, timeline = documents()
    timeline["actions"][-1]["action"]["easing"] = easing
    assert evaluate_frame(layout, timeline, 6000).object("object-system").opacity == 1
    assert evaluate_frame(layout, timeline, 6999).object("object-system").visible
    assert not evaluate_frame(layout, timeline, 7000).object("object-system").visible
    half = evaluate_frame(layout, timeline, 6500)
    if easing == "step":
        assert half.object("object-system").opacity == 1
        assert not half.object("object-replacement").visible
    else:
        assert 0 < half.object("object-system").opacity < 1
        assert 0 < half.object("object-replacement").opacity < 1


def test_replacement_cannot_overlap_either_participant_or_leave_activation():
    layout, timeline = documents()
    timeline["actions"][-1].update(start_ms=8500, end_ms=10500)
    timeline["actions"][-1]["action"]["trigger"]["at_ms"] = 8500
    timeline["actions"][-1]["resolved_trigger"].update(
        source=timeline["actions"][-1]["action"]["trigger"],
        alignment_anchor_ms=8500, resolved_at_ms=8500,
    )
    timeline["duration_ms"] = 11000
    with pytest.raises(V2FrameError, match="active board"):
        evaluate_frame(layout, timeline, 100)
    layout, timeline = documents()
    # The source's first reveal occupies [0,900); replacement cannot overlap it.
    timeline["actions"][-1].update(start_ms=500, end_ms=800)
    timeline["actions"][-1]["action"]["trigger"]["at_ms"] = 500
    timeline["actions"][-1]["resolved_trigger"].update(
        source=timeline["actions"][-1]["action"]["trigger"],
        alignment_anchor_ms=500, resolved_at_ms=500,
    )
    timeline["actions"].sort(key=lambda item: item["start_ms"])
    with pytest.raises(V2FrameError, match="overlaps a participant action"):
        evaluate_frame(layout, timeline, 100)


def test_replace_plan_boundary_rejects_noncanonical_authoring():
    plan = visual_plan_v2()
    plan["beats"][1]["evidence"] = None
    plan["actions"][2] = {
        "action_id": "action-3", "source_instruction_id": "instruction-3",
        "board_id": "board-main", "semantic_reason": "Develop the model",
        "trigger": plan["actions"][2]["trigger"], "easing": "linear",
        "expected_state": "visible", "post_state": "visible",
        "fallback": {"fallback_id": "fallback-3", "on_failure": "block"},
        "coverage_id": "coverage-3", "verb": "replace",
        "from_object_id": "object-system", "to_object_id": "object-evidence",
    }
    VisualPlanV2.model_validate(plan)
    for change in ({"to_object_id": "object-system"},
                   {"expected_state": None}, {"post_state": "changed"}):
        altered = deepcopy(plan)
        altered["actions"][2].update(change)
        with pytest.raises(ValidationError, match="replace"):
            VisualPlanV2.model_validate(altered)


@pytest.mark.parametrize("ancestor_visible,ancestor_opacity", [
    (False, 1), (True, 0),
])
def test_hidden_or_transparent_ancestor_cannot_make_noop_replacement(
    ancestor_visible, ancestor_opacity,
):
    layout, timeline = documents()
    group = {
        "object_id": "replace-group", "board_id": "board-main", "beat_id": "beat-001",
        "semantic_role": "Shared replacement context", "z_index": 0,
        "geometry": {"bounds": {"x": 50, "y": 100, "width": 560, "height": 450},
                     "points": [], "corner_radius": None},
        "transform": deepcopy(layout["objects"][0]["transform"]),
        "opacity": ancestor_opacity, "visible": ancestor_visible,
        "style": {"stroke": None, "fill": None, "text": None, "effect": None},
        "anchors": [], "parent_id": None, "clip_id": None,
        "initial_state": "visible" if ancestor_visible else "hidden", "asset_id": None,
        "description": "Shared static group", "coverage_ids": ["coverage-1"],
        "object_type": "group", "child_ids": ["object-system", "object-replacement"],
    }
    layout["objects"].append(group)
    layout["boards"][0]["object_ids"].append("replace-group")
    layout["objects"][0]["parent_id"] = "replace-group"
    layout["objects"][3]["parent_id"] = "replace-group"
    timeline["initial_object_states"].append({
        "object_id": "replace-group", "state": group["initial_state"],
        "state_version": 1, "visible": ancestor_visible,
    })
    timeline["layout_sha256"] = digest(layout)
    with pytest.raises(V2FrameError, match="fully visible source"):
        evaluate_frame(layout, timeline, 100)


def test_visible_group_replacement_composes_and_ancestor_edit_cannot_overlap():
    layout, timeline = documents()
    group = {
        "object_id": "replace-group", "board_id": "board-main", "beat_id": "beat-001",
        "semantic_role": "Shared replacement context", "z_index": 0,
        "geometry": {"bounds": {"x": 50, "y": 100, "width": 560, "height": 450},
                     "points": [], "corner_radius": None},
        "transform": deepcopy(layout["objects"][0]["transform"]),
        "opacity": 1, "visible": True,
        "style": {"stroke": None, "fill": None, "text": None, "effect": None},
        "anchors": [], "parent_id": None, "clip_id": None,
        "initial_state": "visible", "asset_id": None,
        "description": "Shared static group", "coverage_ids": ["coverage-1"],
        "object_type": "group", "child_ids": ["object-system", "object-replacement"],
    }
    layout["objects"].append(group)
    layout["boards"][0]["object_ids"].append("replace-group")
    layout["objects"][0]["parent_id"] = "replace-group"
    layout["objects"][3]["parent_id"] = "replace-group"
    timeline["initial_object_states"].append({
        "object_id": "replace-group", "state": "visible",
        "state_version": 1, "visible": True,
    })
    timeline["layout_sha256"] = digest(layout)
    assert evaluate_frame(layout, timeline, 6500).object("object-replacement").visible
    assert 'data-object-id="replace-group"' in compose_svg_frame(layout, timeline, 6500).svg
    fade = deepcopy(timeline["actions"][-1])
    fade["action"].update(action_id="fade-group", verb="fade", target_ids=["replace-group"],
                          expected_state="visible", post_state="visible", opacity=0.5)
    fade["action"].pop("from_object_id")
    fade["action"].pop("to_object_id")
    fade["action"]["trigger"] = {"kind": "absolute", "at_ms": 6400}
    fade.update(start_ms=6400, end_ms=6800)
    fade["resolved_trigger"].update(source=fade["action"]["trigger"],
                                    alignment_anchor_ms=6400, resolved_at_ms=6400)
    timeline["actions"].append(fade)
    timeline["actions"].sort(key=lambda item: item["start_ms"])
    timeline["coverage"][0]["action_ids"].append("fade-group")
    with pytest.raises(V2FrameError, match="overlaps an ancestor edit"):
        evaluate_frame(layout, timeline, 100)


def test_replaced_source_cannot_be_reused_and_destination_cannot_overlap():
    layout, timeline = documents()
    late = deepcopy(timeline["actions"][-1])
    late["action"].update(action_id="late-source-edit", verb="fade",
                          target_ids=["object-system"], expected_state=None,
                          post_state="visible", opacity=0.5)
    late["action"].pop("from_object_id")
    late["action"].pop("to_object_id")
    late["action"]["trigger"] = {"kind": "absolute", "at_ms": 8000}
    late.update(start_ms=8000, end_ms=8500)
    late["resolved_trigger"].update(source=late["action"]["trigger"],
                                    alignment_anchor_ms=8000, resolved_at_ms=8000)
    timeline["actions"].append(late)
    timeline["coverage"][0]["action_ids"].append("late-source-edit")
    with pytest.raises(ValidationError, match="resurrects removed object"):
        evaluate_frame(layout, timeline, 100)
    layout, timeline = documents()
    late["action"].update(action_id="early-destination-edit",
                          target_ids=["object-replacement"])
    late["action"]["trigger"] = {"kind": "absolute", "at_ms": 6500}
    late.update(start_ms=6500, end_ms=6800)
    late["resolved_trigger"].update(source=late["action"]["trigger"],
                                    alignment_anchor_ms=6500, resolved_at_ms=6500)
    timeline["actions"].append(late)
    timeline["coverage"][0]["action_ids"].append("early-destination-edit")
    with pytest.raises(V2FrameError, match="overlapping actions"):
        evaluate_frame(layout, timeline, 100)


def test_destination_can_receive_later_manual_transform():
    layout, timeline = documents()
    later = deepcopy(timeline["actions"][-1])
    later["action"].update(action_id="move-after-replace", verb="move",
                           target_ids=["object-replacement"],
                           expected_state="visible", post_state="visible",
                           destination=deepcopy(layout["objects"][-1]["transform"]))
    later["action"]["destination"]["position"] = {"x": 100, "y": 20}
    later["action"].pop("from_object_id")
    later["action"].pop("to_object_id")
    later["action"]["trigger"] = {"kind": "absolute", "at_ms": 8000}
    later.update(start_ms=8000, end_ms=8500)
    later["resolved_trigger"].update(source=later["action"]["trigger"],
                                     alignment_anchor_ms=8000, resolved_at_ms=8000)
    timeline["actions"].append(later)
    timeline["coverage"][0]["action_ids"].append("move-after-replace")
    assert evaluate_frame(layout, timeline, 8500).object(
        "object-replacement").transform.position.x == 100
    assert evaluate_frame(layout, timeline, 7500).object(
        "object-replacement").transform.position.x == 0


def test_replacement_across_parents_fails_before_first_frame():
    layout, timeline = documents()
    group = {
        "object_id": "destination-group", "board_id": "board-main", "beat_id": "beat-001",
        "semantic_role": "Separate stacking context", "z_index": 0,
        "geometry": {"bounds": {"x": 50, "y": 100, "width": 560, "height": 450},
                     "points": [], "corner_radius": None},
        "transform": deepcopy(layout["objects"][0]["transform"]),
        "opacity": 1, "visible": True,
        "style": {"stroke": None, "fill": None, "text": None, "effect": None},
        "anchors": [], "parent_id": None, "clip_id": None,
        "initial_state": "visible", "asset_id": None,
        "description": "Separate group", "coverage_ids": ["coverage-1"],
        "object_type": "group", "child_ids": ["object-replacement"],
    }
    layout["objects"].append(group)
    layout["objects"][3]["parent_id"] = "destination-group"
    layout["boards"][0]["object_ids"].append("destination-group")
    timeline["initial_object_states"].append({
        "object_id": "destination-group", "state": "visible",
        "state_version": 1, "visible": True,
    })
    timeline["layout_sha256"] = digest(layout)
    with pytest.raises(V2FrameError, match="co-located"):
        evaluate_frame(layout, timeline, 100)


def test_portrait_replacement_uses_same_crossfade_contract():
    layout, timeline = documents()
    portrait = {"profile_id": "SHORT_FORM_9_16", "width": 720,
                "height": 1280, "fps": 30}
    layout["output_profile"] = deepcopy(portrait)
    timeline["output_profile"] = deepcopy(portrait)
    layout["canvas"].update(width=720, height=1280)
    timeline["layout_sha256"] = digest(layout)
    frame = evaluate_frame(layout, timeline, 6500)
    assert frame.object("object-system").opacity == pytest.approx(0.5)
    assert frame.object("object-replacement").opacity == pytest.approx(0.5)
    assert Image.open(BytesIO(compose_png_frame(layout, timeline, 6500).png)).size == (720, 1280)


def test_connector_endpoint_cannot_be_replaced_without_rebinding():
    layout, timeline = documents()
    arrow = deepcopy(connector_documents()[0]["objects"][-1])
    layout["objects"].append(arrow)
    layout["boards"][0]["object_ids"].append(arrow["object_id"])
    timeline["initial_object_states"].append({
        "object_id": arrow["object_id"], "state": "hidden",
        "state_version": 1, "visible": False,
    })
    timeline["layout_sha256"] = digest(layout)
    with pytest.raises(V2FrameError, match="distinct paintable objects"):
        evaluate_frame(layout, timeline, 100)
