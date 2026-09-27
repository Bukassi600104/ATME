"""Static clip containers crop their child subtree without painting a box."""

from __future__ import annotations

import hashlib
import io
import xml.etree.ElementTree as ET
from copy import deepcopy

import pytest
from atme.render.v2_state import V2FrameError, evaluate_frame
from atme.render.v2_svg import compose_png_frame, compose_svg_frame
from PIL import Image
from pydantic import ValidationError
from test_v2_camera_action import append_camera
from test_v2_connector_svg import connector_documents
from test_v2_group_hierarchy import grouped_documents
from v2_fixtures import digest


def clipped_documents():
    layout, timeline = grouped_documents()
    clip = layout["objects"][3]
    clip["object_type"] = "clip"
    clip["geometry"]["bounds"] = {
        "x": 80, "y": 160, "width": 240, "height": 340,
    }
    timeline["layout_sha256"] = digest(layout)
    return layout, timeline


def _pixel(layout, timeline, at_ms, xy):
    png = compose_png_frame(layout, timeline, at_ms).png
    return Image.open(io.BytesIO(png)).convert("RGB").getpixel(xy)


def test_static_clip_crops_children_with_distinct_hashed_namespace():
    layout, timeline = clipped_documents()
    root = ET.fromstring(compose_svg_frame(layout, timeline, 5000).svg)
    clip = next(node for node in root.iter()
                if node.attrib.get("data-object-id") == "object-group")
    clip_id = "clip-container-" + hashlib.sha256(b"object-group").hexdigest()
    assert clip.attrib["clip-path"] == f"url(#{clip_id})"
    definition = next(node for node in root.iter()
                      if node.attrib.get("id") == clip_id)
    assert definition.attrib["clipPathUnits"] == "userSpaceOnUse"
    assert [child.attrib.get("data-object-id") for child in clip] == [
        "object-system", "object-label",
    ]
    assert _pixel(layout, timeline, 5000, (200, 350)) != _pixel(
        layout, timeline, 5000, (400, 350)
    )
    assert _pixel(layout, timeline, 5000, (400, 350)) == _pixel(
        layout, timeline, 5000, (50, 350)
    )
    assert compose_png_frame(layout, timeline, 5000).png == (
        compose_png_frame(layout, timeline, 5000).png
    )
    partial = ET.fromstring(compose_svg_frame(layout, timeline, 450).svg)
    clip_paths = [node.attrib["id"] for node in partial.iter()
                  if node.tag.endswith("clipPath")]
    reveal_id = "clip-" + hashlib.sha256(b"object-system").hexdigest()
    assert set(clip_paths) == {clip_id, reveal_id}


def test_nested_clips_intersect_and_group_order_is_preserved():
    layout, timeline = clipped_documents()
    outer = deepcopy(layout["objects"][3])
    outer["object_id"] = "outer-clip"
    outer["child_ids"] = ["object-group"]
    outer["geometry"]["bounds"] = {
        "x": 160, "y": 160, "width": 240, "height": 340,
    }
    layout["objects"][3]["parent_id"] = "outer-clip"
    layout["objects"].append(outer)
    layout["boards"][0]["object_ids"].append("outer-clip")
    timeline["initial_object_states"].append(
        {"object_id": "outer-clip", "state": "visible", "state_version": 1,
         "visible": True}
    )
    timeline["layout_sha256"] = digest(layout)
    assert _pixel(layout, timeline, 5000, (200, 350)) != _pixel(
        layout, timeline, 5000, (120, 350)
    )
    assert _pixel(layout, timeline, 5000, (120, 350)) == _pixel(
        layout, timeline, 5000, (360, 350)
    )
    root = ET.fromstring(compose_svg_frame(layout, timeline, 5000).svg)
    clips = [node for node in root.iter() if node.tag.endswith("clipPath")]
    assert len(clips) == 2
    assert len({node.attrib["id"] for node in clips}) == 2


def test_clip_transform_visibility_opacity_and_random_seek():
    layout, timeline = clipped_documents()
    baseline = compose_png_frame(layout, timeline, 5000).png
    clip = layout["objects"][3]
    clip["transform"]["position"] = {"x": 100, "y": 0}
    timeline["layout_sha256"] = digest(layout)
    moved = compose_png_frame(layout, timeline, 5000).png
    assert moved != baseline
    assert _pixel(layout, timeline, 5000, (300, 350)) != _pixel(
        layout, timeline, 5000, (150, 350)
    )
    compose_svg_frame(layout, timeline, 9000)
    assert compose_png_frame(layout, timeline, 5000).png == moved
    clip["opacity"] = 0.5
    timeline["layout_sha256"] = digest(layout)
    assert compose_png_frame(layout, timeline, 5000).png != moved
    clip["visible"] = False
    clip["initial_state"] = "hidden"
    timeline["initial_object_states"][3].update({"state": "hidden", "visible": False})
    timeline["layout_sha256"] = digest(layout)
    assert not evaluate_frame(layout, timeline, 5000).object("object-system").visible
    assert _pixel(layout, timeline, 5000, (300, 350)) == _pixel(
        layout, timeline, 5000, (50, 350)
    )


def test_group_clip_and_clip_group_nesting_compose_once():
    layout, timeline = clipped_documents()
    outer = deepcopy(layout["objects"][3])
    outer["object_id"] = "outer-group"
    outer["object_type"] = "group"
    outer["child_ids"] = ["object-group"]
    outer["transform"]["position"] = {"x": 100, "y": 0}
    layout["objects"][3]["parent_id"] = "outer-group"
    layout["objects"].append(outer)
    layout["boards"][0]["object_ids"].append("outer-group")
    timeline["initial_object_states"].append(
        {"object_id": "outer-group", "state": "visible", "state_version": 1,
         "visible": True}
    )
    timeline["layout_sha256"] = digest(layout)
    assert _pixel(layout, timeline, 5000, (300, 350)) != _pixel(
        layout, timeline, 5000, (100, 350)
    )

    layout, timeline = clipped_documents()
    inner = deepcopy(layout["objects"][3])
    inner["object_id"] = "inner-group"
    inner["object_type"] = "group"
    inner["geometry"]["bounds"] = {
        "x": 50, "y": 100, "width": 560, "height": 450,
    }
    inner["parent_id"] = "object-group"
    layout["objects"][3]["child_ids"] = ["inner-group"]
    layout["objects"][0]["parent_id"] = "inner-group"
    layout["objects"][1]["parent_id"] = "inner-group"
    layout["objects"].append(inner)
    layout["boards"][0]["object_ids"].append("inner-group")
    timeline["initial_object_states"].append(
        {"object_id": "inner-group", "state": "visible", "state_version": 1,
         "visible": True}
    )
    timeline["layout_sha256"] = digest(layout)
    svg = compose_svg_frame(layout, timeline, 5000).svg
    ids = [node.attrib["data-object-id"] for node in ET.fromstring(svg).iter()
           if "data-object-id" in node.attrib]
    assert ids == ["object-group", "inner-group", "object-system",
                   "object-label", "object-evidence"]
    assert _pixel(layout, timeline, 5000, (200, 350)) != _pixel(
        layout, timeline, 5000, (400, 350)
    )


def test_animated_clip_and_child_crossing_edge_seek_deterministically():
    layout, timeline = clipped_documents()
    action = timeline["actions"][2]["action"]
    action.update({"verb": "move", "target_ids": ["object-group"],
                   "expected_state": "visible", "post_state": "visible",
                   "destination": {"position": {"x": 100, "y": 0},
                                   "scale_x": 1, "scale_y": 1,
                                   "rotation_degrees": 0,
                                   "origin": {"x": 0.5, "y": 0.5}},
                   "opacity": None})
    action.pop("annotation")
    start = compose_png_frame(layout, timeline, 4000).png
    middle = compose_png_frame(layout, timeline, 4450).png
    end = compose_png_frame(layout, timeline, 4900).png
    assert len({start, middle, end}) == 3
    compose_png_frame(layout, timeline, 8000)
    assert compose_png_frame(layout, timeline, 4450).png == middle

    layout, timeline = clipped_documents()
    action = timeline["actions"][2]["action"]
    action.update({"verb": "move", "target_ids": ["object-system"],
                   "expected_state": "visible", "post_state": "visible",
                   "destination": {"position": {"x": 200, "y": 0},
                                   "scale_x": 1, "scale_y": 1,
                                   "rotation_degrees": 0,
                                   "origin": {"x": 0.5, "y": 0.5}},
                   "opacity": None})
    action.pop("annotation")
    assert _pixel(layout, timeline, 3999, (200, 350)) != _pixel(
        layout, timeline, 4900, (200, 350)
    )
    assert _pixel(layout, timeline, 4900, (200, 350)) == _pixel(
        layout, timeline, 4900, (50, 350)
    )


def test_scaled_rotated_fractional_clip_and_portrait_output():
    layout, timeline = clipped_documents()
    clip = layout["objects"][3]
    clip["geometry"]["bounds"] = {
        "x": 80.123456, "y": 160.654321,
        "width": 240.123456, "height": 340.654321,
    }
    clip["transform"].update({"scale_x": 1.1, "scale_y": 0.9,
                              "rotation_degrees": 6.5})
    timeline["layout_sha256"] = digest(layout)
    svg = compose_svg_frame(layout, timeline, 5000).svg
    assert 'x="80.1235" y="160.6543" width="240.1235" height="340.6543"' in svg
    assert 'rotate(6.5) scale(1.1 0.9)' in svg
    assert compose_png_frame(layout, timeline, 5000).png != (
        compose_png_frame(*clipped_documents(), 5000).png
    )
    layout["canvas"] = {"x": 0, "y": 0, "width": 720, "height": 1280}
    layout["output_profile"] = {"profile_id": "SHORT_FORM_9_16",
                                "width": 720, "height": 1280, "fps": 30}
    timeline["output_profile"] = layout["output_profile"]
    timeline["layout_sha256"] = digest(layout)
    portrait = compose_png_frame(layout, timeline, 5000)
    assert Image.open(io.BytesIO(portrait.png)).size == (720, 1280)


def test_mask_and_external_clip_reference_remain_unsupported():
    layout, timeline = clipped_documents()
    layout["objects"][3]["object_type"] = "mask"
    timeline["layout_sha256"] = digest(layout)
    with pytest.raises(ValidationError, match="mask_mode"):
        evaluate_frame(layout, timeline, 100)
    layout, timeline = clipped_documents()
    layout["objects"][0]["clip_id"] = "object-group"
    timeline["layout_sha256"] = digest(layout)
    with pytest.raises(V2FrameError, match="unsupported clip_id"):
        evaluate_frame(layout, timeline, 100)


def test_clip_target_camera_and_connector_endpoint_fail_closed():
    layout, timeline = clipped_documents()
    action = timeline["actions"][2]["action"]
    action.update({"verb": "reveal", "target_ids": ["object-group"],
                   "expected_state": "visible"})
    with pytest.raises(V2FrameError, match="descendant semantics"):
        evaluate_frame(layout, timeline, 100)
    layout, timeline = clipped_documents()
    append_camera(timeline, "camera-clip", "camera_cut", 6000, 6500,
                  target="object-system")
    with pytest.raises(V2FrameError, match="post-clip visible focus"):
        evaluate_frame(layout, timeline, 100)
    layout, timeline = connector_documents()
    clip_layout, _ = clipped_documents()
    layout["objects"].append(clip_layout["objects"][3])
    layout["objects"][0]["parent_id"] = "object-group"
    layout["objects"][1]["parent_id"] = "object-group"
    layout["boards"][0]["object_ids"].append("object-group")
    timeline["initial_object_states"].append(
        {"object_id": "object-group", "state": "visible", "state_version": 1,
         "visible": True}
    )
    timeline["layout_sha256"] = digest(layout)
    with pytest.raises(V2FrameError, match="clipped-endpoint geometry"):
        evaluate_frame(layout, timeline, 100)


def test_clip_invalid_payload_membership_and_cross_board_fail_closed():
    layout, timeline = clipped_documents()
    layout["objects"][3]["style"]["fill"] = "surface.raised"
    timeline["layout_sha256"] = digest(layout)
    with pytest.raises(V2FrameError, match="non-painting stacking context"):
        evaluate_frame(layout, timeline, 100)
    layout, timeline = clipped_documents()
    layout["objects"][0]["parent_id"] = None
    with pytest.raises(ValidationError, match="disagree on parentage"):
        evaluate_frame(layout, timeline, 100)
    layout, timeline = clipped_documents()
    layout["objects"][3]["board_id"] = "other-board"
    other_board = deepcopy(layout["boards"][0])
    other_board["board_id"] = "other-board"
    other_board["object_ids"] = ["object-group"]
    layout["boards"][0]["object_ids"].remove("object-group")
    layout["boards"].append(other_board)
    with pytest.raises(ValidationError, match="cross boards"):
        evaluate_frame(layout, timeline, 100)
    layout, timeline = clipped_documents()
    layout["objects"][3]["geometry"]["bounds"]["width"] = 0.00001
    timeline["layout_sha256"] = digest(layout)
    with pytest.raises(V2FrameError, match="collapse to zero area"):
        compose_svg_frame(layout, timeline, 100)
