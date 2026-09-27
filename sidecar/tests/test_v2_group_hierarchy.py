"""Static groups are nested paint contexts, never implicit flat box substitutes."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from copy import deepcopy

import pytest
from atme.render.v2_state import UnsupportedVisualAction, V2FrameError, evaluate_frame
from atme.render.v2_svg import (
    compose_png_frame,
    compose_svg_frame,
)
from atme.store.contracts_v2 import (
    ExecutableLayoutV2,
    ResolvedVisualTimelineV2,
    VisualPlanV2,
)
from pydantic import ValidationError
from test_v2_camera_action import append_camera
from test_v2_connector_svg import connector_documents
from test_v2_svg import primitive_documents
from v2_fixtures import digest, visual_plan_v2


def grouped_documents():
    layout, timeline = primitive_documents()
    group = {
        "object_id": "object-group", "board_id": "board-main", "beat_id": "beat-001",
        "semantic_role": "One persistent explanatory model", "z_index": 0,
        "geometry": {"bounds": {"x": 50, "y": 100, "width": 560, "height": 450},
                     "points": [], "corner_radius": None},
        "transform": {"position": {"x": 0, "y": 0}, "scale_x": 1,
                      "scale_y": 1, "rotation_degrees": 0,
                      "origin": {"x": 0.5, "y": 0.5}},
        "opacity": 1, "visible": True,
        "style": {"stroke": None, "fill": None, "text": None, "effect": None},
        "anchors": [], "parent_id": None, "clip_id": None,
        "initial_state": "visible", "asset_id": None,
        "description": "Authored grouping of the boundary and its label",
        "coverage_ids": ["coverage-1"], "object_type": "group",
        "child_ids": ["object-system", "object-label"],
    }
    layout["objects"].append(group)
    layout["objects"][0]["parent_id"] = "object-group"
    layout["objects"][1]["parent_id"] = "object-group"
    layout["boards"][0]["object_ids"].append("object-group")
    timeline["initial_object_states"].append(
        {"object_id": "object-group", "state": "visible", "state_version": 1,
         "visible": True}
    )
    timeline["layout_sha256"] = digest(layout)
    return layout, timeline


def object_node(root, object_id):
    return next(node for node in root.iter()
                if node.attrib.get("data-object-id") == object_id)


def test_group_paints_children_once_in_local_order_with_external_sibling():
    layout, timeline = grouped_documents()
    root = ET.fromstring(compose_svg_frame(layout, timeline, 5000).svg)
    group = object_node(root, "object-group")
    assert [child.attrib.get("data-object-id") for child in group] == [
        "object-system", "object-label",
    ]
    assert [node.attrib.get("data-object-id") for node in root.iter()
            if node.attrib.get("data-object-id")] == [
                "object-group", "object-system", "object-label", "object-evidence",
            ]
    layout["objects"][0]["z_index"] = 8
    timeline["layout_sha256"] = digest(layout)
    reordered = ET.fromstring(compose_svg_frame(layout, timeline, 5000).svg)
    assert [child.attrib.get("data-object-id")
            for child in object_node(reordered, "object-group")] == [
                "object-label", "object-system",
            ]


def test_parent_and_child_transforms_compose_and_raster_changes():
    layout, timeline = grouped_documents()
    before = compose_png_frame(layout, timeline, 5000).png
    group = layout["objects"][3]
    group["transform"].update({"position": {"x": 100, "y": 30},
                                "scale_x": 1.1, "scale_y": 1.1,
                                "rotation_degrees": 12})
    layout["objects"][1]["transform"]["position"] = {"x": 12, "y": 8}
    timeline["layout_sha256"] = digest(layout)
    svg = compose_svg_frame(layout, timeline, 5000).svg
    outer = object_node(ET.fromstring(svg), "object-group")
    child = object_node(outer, "object-label")
    assert outer.attrib["transform"].startswith("translate(100 30)")
    assert "rotate(12) scale(1.1 1.1)" in outer.attrib["transform"]
    assert child.attrib["transform"].startswith("translate(12 8)")
    after = compose_png_frame(layout, timeline, 5000).png
    assert before != after
    assert compose_png_frame(layout, timeline, 5000).png == after


def test_nested_group_visibility_opacity_and_random_seek():
    layout, timeline = grouped_documents()
    outer = deepcopy(layout["objects"][3])
    outer["object_id"] = "object-outer"
    outer["child_ids"] = ["object-group"]
    outer["z_index"] = -1
    outer["opacity"] = 0.5
    layout["objects"][3]["parent_id"] = "object-outer"
    layout["objects"][3]["opacity"] = 0.5
    layout["objects"].append(outer)
    layout["boards"][0]["object_ids"].append("object-outer")
    timeline["initial_object_states"].append(
        {"object_id": "object-outer", "state": "visible", "state_version": 1,
         "visible": True}
    )
    timeline["layout_sha256"] = digest(layout)
    frame = compose_svg_frame(layout, timeline, 5000)
    root = ET.fromstring(frame.svg)
    assert object_node(root, "object-outer").attrib["opacity"] == "0.5"
    assert object_node(root, "object-group").attrib["opacity"] == "0.5"
    assert object_node(object_node(root, "object-outer"), "object-label") is not None
    compose_svg_frame(layout, timeline, 9000)
    assert compose_svg_frame(layout, timeline, 5000).svg == frame.svg
    layout["objects"][4]["visible"] = False
    layout["objects"][4]["initial_state"] = "hidden"
    timeline["initial_object_states"][4].update({"visible": False, "state": "hidden"})
    timeline["layout_sha256"] = digest(layout)
    hidden = evaluate_frame(layout, timeline, 5000)
    assert not hidden.object("object-label").visible
    assert 'data-object-id="object-label"' not in compose_svg_frame(layout, timeline, 5000).svg


def test_group_wrapper_transform_and_fade_are_supported_without_membership_changes():
    layout, timeline = grouped_documents()
    action = timeline["actions"][2]["action"]
    action.update({"verb": "fade", "target_ids": ["object-group"],
                   "expected_state": "visible", "post_state": "visible",
                   "destination": None, "opacity": 0.4})
    action.pop("annotation")
    middle = ET.fromstring(compose_svg_frame(layout, timeline, 4450).svg)
    assert float(object_node(middle, "object-group").attrib["opacity"]) == pytest.approx(0.55)
    end = ET.fromstring(compose_svg_frame(layout, timeline, 4900).svg)
    assert float(object_node(end, "object-group").attrib["opacity"]) == pytest.approx(0.4)
    layout, timeline = grouped_documents()
    action = timeline["actions"][2]["action"]
    action.update({"verb": "move", "target_ids": ["object-group"],
                   "expected_state": "visible", "post_state": "visible",
                   "destination": {"position": {"x": 100, "y": 20},
                                   "scale_x": 1, "scale_y": 1,
                                   "rotation_degrees": 0,
                                   "origin": {"x": 0.5, "y": 0.5}},
                   "opacity": None})
    action.pop("annotation")
    middle = object_node(ET.fromstring(compose_svg_frame(layout, timeline, 4450).svg),
                         "object-group")
    assert middle.attrib["transform"].startswith("translate(75 15)")
    compose_svg_frame(layout, timeline, 9000)
    assert object_node(ET.fromstring(compose_svg_frame(layout, timeline, 4450).svg),
                       "object-group").attrib["transform"] == middle.attrib["transform"]


def test_group_target_actions_and_dynamic_membership_fail_before_sampling():
    layout, timeline = grouped_documents()
    action = timeline["actions"][2]["action"]
    action.update({"verb": "reveal", "target_ids": ["object-group"],
                   "expected_state": "visible"})
    with pytest.raises(V2FrameError, match="descendant semantics"):
        evaluate_frame(layout, timeline, 100)
    layout, timeline = grouped_documents()
    trigger = {"kind": "absolute", "at_ms": 6000}
    timeline["actions"].append({
        "action": {"action_id": "group-action", "source_instruction_id": "instruction-1",
                   "board_id": "board-main", "semantic_reason": "Regroup the model",
                   "trigger": trigger, "easing": "step", "expected_state": None,
                   "post_state": "grouped", "fallback": {"fallback_id": "fallback-1",
                                                          "on_failure": "block"},
                   "coverage_id": "coverage-1", "verb": "group",
                   "target_ids": ["object-system", "object-label"],
                   "container_id": "object-group"},
        "start_ms": 6000, "end_ms": 6500,
        "resolved_trigger": {"source": trigger, "alignment_anchor_ms": 6000,
                             "matched_text": None, "matched_occurrence": None,
                             "resolved_at_ms": 6000, "confidence": 1, "exact": True},
    })
    timeline["coverage"][0]["action_ids"].append("group-action")
    with pytest.raises(UnsupportedVisualAction, match="no frame implementation"):
        evaluate_frame(layout, timeline, 100)


def test_unsupported_mask_container_is_never_silently_flattened():
    layout, timeline = grouped_documents()
    layout["objects"][3]["object_type"] = "mask"
    timeline["layout_sha256"] = digest(layout)
    for render in (evaluate_frame, compose_svg_frame):
        with pytest.raises(ValidationError, match="mask_mode"):
            render(layout, timeline, 100)


def test_clip_id_fails_but_grouped_camera_and_root_connector_use_world_geometry():
    layout, timeline = grouped_documents()
    layout["objects"][3]["object_type"] = "clip"
    layout["objects"][0]["clip_id"] = "object-group"
    timeline["layout_sha256"] = digest(layout)
    ExecutableLayoutV2.model_validate(layout)  # Structurally valid clip reference.
    for render in (evaluate_frame, compose_svg_frame):
        with pytest.raises(V2FrameError, match="clip_id"):
            render(layout, timeline, 100)
    layout, timeline = grouped_documents()
    append_camera(timeline, "camera-1", "camera_cut", 6000, 6500,
                  target="object-system")
    assert evaluate_frame(layout, timeline, 6000).camera.width < layout["canvas"]["width"]
    layout, timeline = connector_documents()
    group_layout, _ = grouped_documents()
    layout["objects"].append(group_layout["objects"][3])
    layout["objects"][0]["parent_id"] = "object-group"
    layout["objects"][1]["parent_id"] = "object-group"
    layout["boards"][0]["object_ids"].append("object-group")
    timeline["initial_object_states"].append(
        {"object_id": "object-group", "state": "visible", "state_version": 1,
         "visible": True}
    )
    timeline["layout_sha256"] = digest(layout)
    assert evaluate_frame(layout, timeline, 5000).object("object-arrow").visible
    assert 'data-object-id="object-arrow"' in compose_svg_frame(layout, timeline, 5000).svg


def test_cross_board_duplicate_membership_and_cycle_reject_at_contract_boundary():
    layout, timeline = grouped_documents()
    layout["objects"][3]["board_id"] = "other-board"
    other_board = deepcopy(layout["boards"][0])
    other_board["board_id"] = "other-board"
    other_board["object_ids"] = ["object-group"]
    layout["boards"][0]["object_ids"].remove("object-group")
    layout["boards"].append(other_board)
    with pytest.raises(ValidationError, match="cross boards"):
        evaluate_frame(layout, timeline, 5000)
    layout, timeline = grouped_documents()
    layout["objects"][3]["child_ids"].append("object-system")
    with pytest.raises(ValidationError, match="repeats a child"):
        evaluate_frame(layout, timeline, 5000)
    layout, timeline = grouped_documents()
    layout["objects"][3]["parent_id"] = "object-group"
    layout["objects"][3]["child_ids"].append("object-group")
    with pytest.raises(ValidationError, match="acyclic"):
        evaluate_frame(layout, timeline, 5000)


def test_orphan_and_painted_group_fail_closed():
    layout, timeline = grouped_documents()
    layout["objects"][0]["parent_id"] = None
    with pytest.raises(ValidationError, match="disagree on parentage"):
        evaluate_frame(layout, timeline, 5000)
    layout, timeline = grouped_documents()
    layout["objects"][3]["style"]["fill"] = "surface.raised"
    timeline["layout_sha256"] = digest(layout)
    for render in (evaluate_frame, compose_svg_frame):
        with pytest.raises(V2FrameError, match="non-painting stacking context"):
            render(layout, timeline, 100)


def test_group_container_reference_rejects_unknown_non_group_and_cross_board():
    layout, timeline = grouped_documents()
    trigger = {"kind": "absolute", "at_ms": 6000}
    action = {"action_id": "group-action", "source_instruction_id": "instruction-1",
              "board_id": "board-main", "semantic_reason": "Regroup the model",
              "trigger": trigger, "easing": "step", "expected_state": None,
              "post_state": "grouped", "fallback": {"fallback_id": "fallback-1",
                                                    "on_failure": "block"},
              "coverage_id": "coverage-1", "verb": "group",
              "target_ids": ["object-system"], "container_id": "missing-container"}
    timeline["actions"].append({
        "action": action, "start_ms": 6000, "end_ms": 6500,
        "resolved_trigger": {"source": trigger, "alignment_anchor_ms": 6000,
                             "matched_text": None, "matched_occurrence": None,
                             "resolved_at_ms": 6000, "confidence": 1, "exact": True},
    })
    timeline["coverage"][0]["action_ids"].append("group-action")
    with pytest.raises(ValidationError, match="without initial state"):
        ResolvedVisualTimelineV2.model_validate(timeline)
    action["container_id"] = "object-label"
    with pytest.raises(V2FrameError, match="same-board group container"):
        evaluate_frame(layout, timeline, 100)
    action["container_id"] = "object-group"
    other_board = deepcopy(layout["boards"][0])
    other_board["board_id"] = "other-board"
    other_board["object_ids"] = []
    layout["boards"].append(other_board)
    action["board_id"] = "other-board"
    timeline["layout_sha256"] = digest(layout)
    with pytest.raises(V2FrameError, match="same-board group container"):
        evaluate_frame(layout, timeline, 100)


def test_visual_plan_group_container_reference_rejects_unknown_and_non_group():
    plan = visual_plan_v2()
    action = plan["actions"][0]
    action.pop("annotation")
    action.update({"verb": "group", "target_ids": ["object-system"],
                   "container_id": "missing-container", "expected_state": None,
                   "post_state": "grouped"})
    with pytest.raises(ValidationError, match="reference unknown IDs"):
        VisualPlanV2.model_validate(plan)
    action["container_id"] = "object-label"
    with pytest.raises(ValidationError, match="same-board group container"):
        VisualPlanV2.model_validate(plan)


def test_excessive_group_depth_rejects_before_composition():
    layout, timeline = grouped_documents()
    layout["boards"][0]["density_limit"] = 12
    previous = layout["objects"][3]
    for index in range(1, 9):
        outer = deepcopy(previous)
        outer["object_id"] = f"outer-{index}"
        outer["parent_id"] = None
        outer["child_ids"] = [previous["object_id"]]
        previous["parent_id"] = outer["object_id"]
        layout["objects"].append(outer)
        layout["boards"][0]["object_ids"].append(outer["object_id"])
        timeline["initial_object_states"].append(
            {"object_id": outer["object_id"], "state": "visible",
             "state_version": 1, "visible": True}
        )
        previous = outer
    with pytest.raises(ValidationError, match="nesting exceeds eight"):
        evaluate_frame(layout, timeline, 5000)
