"""Static alpha masks crop authored content in parent-local coordinates."""

from __future__ import annotations

import hashlib
import io
import xml.etree.ElementTree as ET
from copy import deepcopy

import pytest
from atme.render.v2_state import V2FrameError, evaluate_frame
from atme.render.v2_svg import compose_png_frame, compose_svg_frame
from PIL import Image
from test_v2_camera_action import append_camera
from test_v2_connector_svg import connector_documents
from test_v2_mask_contract import masked_documents
from v2_fixtures import digest


def _masked_scene():
    _, layout, timeline = masked_documents()
    layout["objects"][0]["style"]["fill"] = "surface.accent"
    layout["objects"][4]["geometry"]["bounds"] = {
        "x": 80, "y": 160, "width": 240, "height": 340,
    }
    timeline["layout_sha256"] = digest(layout)
    return layout, timeline


def _pixel(layout, timeline, at_ms, point):
    png = compose_png_frame(layout, timeline, at_ms).png
    return Image.open(io.BytesIO(png)).convert("RGB").getpixel(point)


def test_static_mask_aperture_is_rendered_and_source_is_not_painted():
    layout, timeline = _masked_scene()
    svg = compose_svg_frame(layout, timeline, 5000).svg
    root = ET.fromstring(svg)
    mask_id = "mask-container-" + hashlib.sha256(b"object-group").hexdigest()
    definition = next(node for node in root.iter() if node.attrib.get("id") == mask_id)
    assert definition.attrib["maskUnits"] == "userSpaceOnUse"
    assert definition.attrib["maskContentUnits"] == "userSpaceOnUse"
    assert definition.attrib["style"] == "mask-type:alpha"
    assert f'mask="url(#{mask_id})"' in svg
    assert 'data-object-id="mask-source"' not in svg
    assert _pixel(layout, timeline, 5000, (200, 350)) != _pixel(
        layout, timeline, 5000, (400, 350)
    )
    assert _pixel(layout, timeline, 5000, (400, 350)) == _pixel(
        layout, timeline, 5000, (50, 350)
    )


@pytest.mark.parametrize("shape", ["rectangle", "rounded_rectangle", "ellipse", "polygon"])
def test_all_contract_source_shapes_produce_a_raster_aperture(shape):
    layout, timeline = _masked_scene()
    source = layout["objects"][4]
    source["object_type"] = shape
    if shape != "rounded_rectangle":
        source["geometry"]["corner_radius"] = None
    if shape == "polygon":
        source["geometry"]["points"] = [
            {"x": 80, "y": 160}, {"x": 320, "y": 160}, {"x": 200, "y": 500},
        ]
    timeline["layout_sha256"] = digest(layout)
    assert _pixel(layout, timeline, 5000, (200, 320)) != _pixel(
        layout, timeline, 5000, (400, 320)
    )


def test_mask_aperture_stays_still_when_container_content_moves():
    layout, timeline = _masked_scene()
    before = compose_png_frame(layout, timeline, 5000).png
    layout["objects"][3]["transform"]["position"] = {"x": 100, "y": 0}
    timeline["layout_sha256"] = digest(layout)
    after = compose_png_frame(layout, timeline, 5000).png
    assert after != before
    assert _pixel(layout, timeline, 5000, (150, 350)) == _pixel(
        layout, timeline, 5000, (50, 350)
    )
    assert _pixel(layout, timeline, 5000, (275, 350)) != _pixel(
        layout, timeline, 5000, (50, 350)
    )
    svg = compose_svg_frame(layout, timeline, 5000).svg
    mask = ET.fromstring(svg).find(".//{*}g[@data-object-id='object-group']")
    assert mask is not None and "transform" not in mask.attrib
    assert mask[0].attrib["transform"].startswith("translate(100 0)")


def test_mask_source_transform_moves_only_the_aperture():
    layout, timeline = _masked_scene()
    layout["objects"][4]["transform"]["position"] = {"x": 100, "y": 0}
    timeline["layout_sha256"] = digest(layout)
    assert _pixel(layout, timeline, 5000, (120, 350)) == _pixel(
        layout, timeline, 5000, (50, 350)
    )
    assert _pixel(layout, timeline, 5000, (380, 350)) != _pixel(
        layout, timeline, 5000, (50, 350)
    )
    root = ET.fromstring(compose_svg_frame(layout, timeline, 5000).svg)
    definition = next(node for node in root.iter() if node.tag.endswith("mask"))
    assert definition[0].attrib["transform"].startswith("translate(100 0)")


def test_source_and_content_transforms_compose_independently():
    layout, timeline = _masked_scene()
    layout["objects"][4]["transform"]["position"] = {"x": 30, "y": 0}
    layout["objects"][3]["transform"]["position"] = {"x": 100, "y": 0}
    timeline["layout_sha256"] = digest(layout)
    background = _pixel(layout, timeline, 5000, (50, 350))
    assert _pixel(layout, timeline, 5000, (200, 350)) != background
    assert _pixel(layout, timeline, 5000, (120, 350)) == background
    assert _pixel(layout, timeline, 5000, (370, 350)) == background


def test_nested_group_and_mask_transform_both_source_and_content():
    layout, timeline = _masked_scene()
    outer = deepcopy(layout["objects"][3])
    outer["object_id"] = "outer-group"
    outer["object_type"] = "group"
    for field in ("mask_mode", "mask_source_object_id", "mask_coordinate_space",
                  "invert", "feather_px"):
        outer.pop(field)
    outer["child_ids"] = ["object-group", "mask-source"]
    outer["transform"]["position"] = {"x": 100, "y": 0}
    layout["objects"].append(outer)
    layout["objects"][3]["parent_id"] = "outer-group"
    layout["objects"][4]["parent_id"] = "outer-group"
    layout["boards"][0]["object_ids"].append("outer-group")
    layout["boards"][0]["density_limit"] = 6
    timeline["initial_object_states"].append(
        {"object_id": "outer-group", "state": "visible", "state_version": 1,
         "visible": True})
    timeline["layout_sha256"] = digest(layout)
    assert _pixel(layout, timeline, 5000, (200, 350)) != _pixel(
        layout, timeline, 5000, (120, 350)
    )
    assert _pixel(layout, timeline, 5000, (450, 350)) == _pixel(
        layout, timeline, 5000, (50, 350)
    )


@pytest.mark.parametrize("outer_type", ["clip", "mask"])
def test_nested_clip_or_mask_intersects_inner_mask(outer_type):
    layout, timeline = _masked_scene()
    outer = deepcopy(layout["objects"][3])
    outer["object_id"] = "outer-container"
    outer["object_type"] = outer_type
    outer["child_ids"] = ["object-group", "mask-source"]
    outer["geometry"]["bounds"] = {
        "x": 160, "y": 160, "width": 240, "height": 340,
    }
    layout["objects"][3]["parent_id"] = "outer-container"
    layout["objects"][4]["parent_id"] = "outer-container"
    if outer_type == "clip":
        for field in ("mask_mode", "mask_source_object_id", "mask_coordinate_space",
                      "invert", "feather_px"):
            outer.pop(field)
    else:
        outer["mask_source_object_id"] = "outer-source"
        outer_source = deepcopy(layout["objects"][4])
        outer_source["object_id"] = "outer-source"
        outer_source["parent_id"] = None
        outer_source["geometry"]["bounds"] = deepcopy(outer["geometry"]["bounds"])
        layout["objects"].append(outer_source)
        layout["boards"][0]["object_ids"].append("outer-source")
        timeline["initial_object_states"].append(
            {"object_id": "outer-source", "state": "visible", "state_version": 1,
             "visible": True})
    layout["objects"].append(outer)
    layout["boards"][0]["object_ids"].append("outer-container")
    layout["boards"][0]["density_limit"] = 7
    timeline["initial_object_states"].append(
        {"object_id": "outer-container", "state": "visible", "state_version": 1,
         "visible": True})
    timeline["layout_sha256"] = digest(layout)
    background = _pixel(layout, timeline, 5000, (50, 350))
    assert _pixel(layout, timeline, 5000, (200, 350)) != background
    assert _pixel(layout, timeline, 5000, (120, 350)) == background
    assert _pixel(layout, timeline, 5000, (350, 350)) == background
    svg = compose_svg_frame(layout, timeline, 5000).svg
    assert 'data-object-id="mask-source"' not in svg
    assert 'data-object-id="outer-source"' not in svg


def test_clip_inside_mask_intersects_the_outer_alpha_aperture():
    layout, timeline = _masked_scene()
    child_clip = deepcopy(layout["objects"][3])
    child_clip["object_id"] = "child-clip"
    child_clip["object_type"] = "clip"
    child_clip["parent_id"] = "object-group"
    child_clip["child_ids"] = ["object-system"]
    child_clip["geometry"]["bounds"] = {
        "x": 160, "y": 160, "width": 240, "height": 340,
    }
    for field in ("mask_mode", "mask_source_object_id", "mask_coordinate_space",
                  "invert", "feather_px"):
        child_clip.pop(field)
    layout["objects"][0]["parent_id"] = "child-clip"
    layout["objects"][3]["child_ids"] = ["child-clip", "object-label"]
    layout["objects"].append(child_clip)
    layout["boards"][0]["object_ids"].append("child-clip")
    layout["boards"][0]["density_limit"] = 6
    timeline["initial_object_states"].append(
        {"object_id": "child-clip", "state": "visible", "state_version": 1,
         "visible": True})
    timeline["layout_sha256"] = digest(layout)
    background = _pixel(layout, timeline, 5000, (50, 350))
    assert _pixel(layout, timeline, 5000, (200, 350)) != background
    assert _pixel(layout, timeline, 5000, (120, 350)) == background
    assert _pixel(layout, timeline, 5000, (350, 350)) == background


def test_mask_source_future_action_is_rejected_before_any_frame():
    layout, timeline = _masked_scene()
    action = timeline["actions"][0]["action"]
    action["target_ids"] = ["mask-source"]
    action["expected_state"] = "visible"
    with pytest.raises(V2FrameError, match="mask-only source"):
        evaluate_frame(layout, timeline, 100)


@pytest.mark.parametrize("field,value", [
    ("path_data", "M 80 160 L 320 500"),
    ("style", {"stroke": "ink.primary", "fill": None,
               "text": None, "effect": None}),
    ("anchors", [{"anchor_id": "center", "point": {"x": 0.5, "y": 0.5}}]),
])
def test_mask_only_source_cannot_carry_ignored_paint_or_path(field, value):
    layout, timeline = _masked_scene()
    layout["objects"][4][field] = value
    timeline["layout_sha256"] = digest(layout)
    with pytest.raises(V2FrameError, match="painted style or path data"):
        evaluate_frame(layout, timeline, 100)


def test_mask_source_collapsed_or_degenerate_geometry_fails_closed():
    layout, timeline = _masked_scene()
    layout["objects"][4]["transform"]["scale_x"] = 0.00000001
    timeline["layout_sha256"] = digest(layout)
    with pytest.raises(V2FrameError, match="collapsed|supported range"):
        evaluate_frame(layout, timeline, 100)
    layout, timeline = _masked_scene()
    source = layout["objects"][4]
    source["object_type"] = "polygon"
    source["geometry"]["corner_radius"] = None
    source["geometry"]["points"] = [
        {"x": 80, "y": 160}, {"x": 160, "y": 240}, {"x": 240, "y": 320},
    ]
    timeline["layout_sha256"] = digest(layout)
    with pytest.raises(V2FrameError, match="no area"):
        evaluate_frame(layout, timeline, 100)


def test_mask_source_must_be_visible_in_resolved_timeline():
    layout, timeline = _masked_scene()
    timeline["initial_object_states"][4].update(state="hidden", visible=False)
    with pytest.raises(V2FrameError, match="fully visible and static"):
        evaluate_frame(layout, timeline, 100)


def test_masked_leaf_is_not_valid_camera_focus_or_connector_endpoint():
    layout, timeline = _masked_scene()
    append_camera(timeline, "camera-masked", "camera_cut", 6000, 6500,
                  target="object-system")
    with pytest.raises(V2FrameError, match="post-clip visible focus"):
        evaluate_frame(layout, timeline, 100)
    layout, timeline = _masked_scene()
    connector_layout, _ = connector_documents()
    arrow = connector_layout["objects"][3]
    layout["objects"].append(arrow)
    layout["boards"][0]["object_ids"].append("object-arrow")
    layout["boards"][0]["density_limit"] = 6
    timeline["initial_object_states"].append(
        {"object_id": "object-arrow", "state": "hidden", "state_version": 1,
         "visible": False})
    timeline["layout_sha256"] = digest(layout)
    with pytest.raises(V2FrameError, match="clipped-endpoint geometry"):
        evaluate_frame(layout, timeline, 100)


def test_target_action_on_mask_container_has_no_descendant_semantics():
    layout, timeline = _masked_scene()
    action = timeline["actions"][2]["action"]
    action.update({"verb": "reveal", "target_ids": ["object-group"],
                   "expected_state": "visible", "post_state": "visible"})
    with pytest.raises(V2FrameError, match="descendant semantics"):
        evaluate_frame(layout, timeline, 100)


def test_animated_mask_container_moves_content_beneath_stationary_aperture():
    layout, timeline = _masked_scene()
    action = timeline["actions"][2]["action"]
    action.update({"verb": "move", "target_ids": ["object-group"],
                   "expected_state": "visible", "post_state": "visible",
                   "destination": {"position": {"x": 100, "y": 0},
                                   "scale_x": 1, "scale_y": 1,
                                   "rotation_degrees": 0,
                                   "origin": {"x": 0.5, "y": 0.5}},
                   "opacity": None})
    action.pop("annotation")
    early = compose_png_frame(layout, timeline, 3999).png
    middle = compose_png_frame(layout, timeline, 4450).png
    late = compose_png_frame(layout, timeline, 9000).png
    assert early != middle != late
    assert _pixel(layout, timeline, 9000, (150, 350)) == _pixel(
        layout, timeline, 9000, (50, 350)
    )
    compose_png_frame(layout, timeline, 100)
    assert compose_png_frame(layout, timeline, 4450).png == middle


def test_hidden_mask_gates_content_without_painting_source():
    layout, timeline = _masked_scene()
    layout["objects"][3].update(visible=False, initial_state="hidden")
    timeline["initial_object_states"][3].update(state="hidden", visible=False)
    timeline["layout_sha256"] = digest(layout)
    assert _pixel(layout, timeline, 5000, (200, 350)) == _pixel(
        layout, timeline, 5000, (50, 350)
    )


def test_mask_container_opacity_blends_the_composed_content_once():
    layout, timeline = _masked_scene()
    full = _pixel(layout, timeline, 5000, (200, 350))
    background = _pixel(layout, timeline, 5000, (50, 350))
    layout["objects"][3]["opacity"] = 0.5
    timeline["layout_sha256"] = digest(layout)
    half = _pixel(layout, timeline, 5000, (200, 350))
    assert half != full and half != background
    assert _pixel(layout, timeline, 5000, (400, 350)) == background


def test_mask_pixel_and_svg_are_random_seek_deterministic():
    layout, timeline = _masked_scene()
    baseline = compose_png_frame(layout, timeline, 5000).png
    svg = compose_svg_frame(layout, timeline, 5000).svg
    compose_png_frame(layout, timeline, 9000)
    compose_svg_frame(layout, timeline, 100)
    assert compose_png_frame(layout, timeline, 5000).png == baseline
    assert compose_svg_frame(layout, timeline, 5000).svg == svg


def test_mask_raster_uses_portrait_profile_and_fractional_transforms():
    layout, timeline = _masked_scene()
    layout["canvas"] = {"x": 0, "y": 0, "width": 720, "height": 1280}
    profile = {"profile_id": "SHORT_FORM_9_16", "width": 720, "height": 1280,
               "fps": 30}
    layout["output_profile"] = profile
    timeline["output_profile"] = profile
    layout["objects"][4]["transform"].update(
        {"position": {"x": 12.125, "y": 8.375}, "rotation_degrees": 6.25})
    timeline["layout_sha256"] = digest(layout)
    frame = compose_png_frame(layout, timeline, 5000)
    assert Image.open(io.BytesIO(frame.png)).size == (720, 1280)
    assert frame.png == compose_png_frame(layout, timeline, 5000).png
