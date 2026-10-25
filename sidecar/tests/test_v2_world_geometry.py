"""Grouped camera and arrow geometry follows the same nested SVG transforms."""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from copy import deepcopy

import pytest
from atme.render.v2_state import V2FrameError, evaluate_frame
from atme.render.v2_svg import (
    UnsupportedVisualObject,
    compose_png_frame,
    compose_svg_frame,
)
from atme.render.v2_world import UnsupportedWorldGeometry, world_anchor, world_bounds
from atme.store.contracts_v2 import ExecutableLayoutV2
from test_v2_camera_action import append_camera
from test_v2_connector_svg import connector_documents
from test_v2_group_hierarchy import grouped_documents
from v2_fixtures import common_action, digest


def _object(root, object_id):
    return next(node for node in root.iter() if node.attrib.get("data-object-id") == object_id)


def _arrow_path(svg):
    arrow = _object(ET.fromstring(svg), "object-arrow")
    return next(node.attrib["d"] for node in arrow if node.tag.endswith("path"))


def test_nested_world_matrix_matches_authored_svg_order_and_fractional_pivot():
    layout, timeline = grouped_documents()
    inner = layout["objects"][3]
    inner["transform"].update({"position": {"x": 17.123456, "y": -3.456789},
                               "scale_x": 1.25, "scale_y": 0.75,
                               "rotation_degrees": 30,
                               "origin": {"x": 0.25, "y": 0.75}})
    outer = deepcopy(inner)
    outer["object_id"] = "object-outer"
    outer["child_ids"] = ["object-group"]
    outer["transform"].update({"position": {"x": 40, "y": 12},
                               "scale_x": 0.8, "scale_y": 1.1,
                               "rotation_degrees": -20,
                               "origin": {"x": 0.5, "y": 0.5}})
    inner["parent_id"] = "object-outer"
    layout["objects"].append(outer)
    layout["boards"][0]["object_ids"].append("object-outer")
    timeline["initial_object_states"].append(
        {"object_id": "object-outer", "state": "visible", "state_version": 1,
         "visible": True}
    )
    timeline["layout_sha256"] = digest(layout)
    typed = ExecutableLayoutV2.model_validate(layout)
    objects = {obj.object_id: obj for obj in typed.objects}
    transforms = {obj.object_id: obj.transform for obj in typed.objects}
    target = objects["object-system"]
    actual = world_anchor(target, "center", objects, transforms)

    def authored_local(point, obj):
        transform = obj.transform
        bounds = obj.geometry.bounds
        origin = (round(bounds.x + bounds.width * transform.origin.x, 4),
                  round(bounds.y + bounds.height * transform.origin.y, 4))
        angle = math.radians(round(transform.rotation_degrees, 4))
        dx = (point[0] - origin[0]) * round(transform.scale_x, 4)
        dy = (point[1] - origin[1]) * round(transform.scale_y, 4)
        return (origin[0] + dx * math.cos(angle) - dy * math.sin(angle)
                + round(transform.position.x, 4),
                origin[1] + dx * math.sin(angle) + dy * math.cos(angle)
                + round(transform.position.y, 4))

    bounds = target.geometry.bounds
    expected = (bounds.x + bounds.width / 2, bounds.y + bounds.height / 2)
    for object_id in ("object-system", "object-group", "object-outer"):
        expected = authored_local(expected, objects[object_id])
    assert actual == pytest.approx(expected, abs=1e-6)
    rect = world_bounds(target, objects, transforms)
    assert rect[0] < actual[0] < rect[2]
    assert rect[1] < actual[1] < rect[3]
    svg = compose_svg_frame(layout, timeline, 5000).svg
    root = ET.fromstring(svg)
    assert _object(root, "object-outer").attrib["transform"].startswith("translate(40 12)")
    assert _object(root, "object-group").attrib["transform"].startswith(
        "translate(17.1235 -3.4568)"
    )
    assert compose_svg_frame(layout, timeline, 5000).svg == svg
    assert compose_png_frame(layout, timeline, 5000).png == (
        compose_png_frame(layout, timeline, 5000).png
    )


def test_world_point_rejects_non_finite_and_out_of_range():
    from atme.render.v2_world import Affine

    with pytest.raises(UnsupportedWorldGeometry, match="outside the supported range"):
        Affine(e=1_000_001).point(0, 0)
    with pytest.raises(UnsupportedWorldGeometry, match="outside the supported range"):
        Affine(e=float("inf")).point(0, 0)
    layout, _ = grouped_documents()
    typed = ExecutableLayoutV2.model_validate(layout)
    target = typed.objects[0]
    objects = {obj.object_id: obj for obj in typed.objects}
    transforms = {obj.object_id: obj.transform for obj in typed.objects}
    transforms[target.object_id] = target.transform.model_copy(update={"scale_x": 0.00001})
    with pytest.raises(UnsupportedWorldGeometry, match="collapsed"):
        world_bounds(target, objects, transforms)


def test_world_bounds_uses_exact_four_decimal_geometry_emitted_by_svg():
    layout, timeline = grouped_documents()
    layout["objects"][0]["geometry"]["bounds"] = {
        "x": 80.123456, "y": 160.654321,
        "width": 480.123456, "height": 340.654321,
    }
    timeline["layout_sha256"] = digest(layout)
    typed = ExecutableLayoutV2.model_validate(layout)
    objects = {obj.object_id: obj for obj in typed.objects}
    transforms = {obj.object_id: obj.transform for obj in typed.objects}
    expected = (80.1235, 160.6543, 560.2470, 501.3086)
    assert world_bounds(objects["object-system"], objects, transforms) == pytest.approx(expected)
    svg = ET.fromstring(compose_svg_frame(layout, timeline, 5000).svg)
    rect = next(node for node in _object(svg, "object-system")
                if node.tag.endswith("rect"))
    assert (float(rect.attrib["x"]), float(rect.attrib["y"]),
            float(rect.attrib["x"]) + float(rect.attrib["width"]),
            float(rect.attrib["y"]) + float(rect.attrib["height"])) == pytest.approx(expected)

    # Fractional bounds inside a transformed group use the emitted corners,
    # not the unrounded source geometry.
    layout["objects"][3]["transform"].update({
        "position": {"x": 19.123456, "y": -2.654321},
        "scale_x": 1.125678, "scale_y": 0.876543,
        "rotation_degrees": 11.234567,
    })
    timeline["layout_sha256"] = digest(layout)
    typed = ExecutableLayoutV2.model_validate(layout)
    objects = {obj.object_id: obj for obj in typed.objects}
    transforms = {obj.object_id: obj.transform for obj in typed.objects}
    actual = world_bounds(objects["object-system"], objects, transforms)
    group = objects["object-group"]
    gb = group.geometry.bounds
    gt = group.transform
    origin_x = round(gb.x + gb.width * gt.origin.x, 4)
    origin_y = round(gb.y + gb.height * gt.origin.y, 4)
    angle = math.radians(round(gt.rotation_degrees, 4))
    points = []
    for x in (expected[0], expected[2]):
        for y in (expected[1], expected[3]):
            dx = (x - origin_x) * round(gt.scale_x, 4)
            dy = (y - origin_y) * round(gt.scale_y, 4)
            points.append((origin_x + dx * math.cos(angle) - dy * math.sin(angle)
                           + round(gt.position.x, 4),
                           origin_y + dx * math.sin(angle) + dy * math.cos(angle)
                           + round(gt.position.y, 4)))
    assert actual == pytest.approx((min(x for x, _ in points), min(y for _, y in points),
                                    max(x for x, _ in points), max(y for _, y in points)),
                                   abs=1e-5)
    append_camera(timeline, "camera-fractional", "camera_cut", 6000, 6500,
                  target="object-system", framing="medium")
    camera = evaluate_frame(layout, timeline, 6000).camera
    assert camera.x <= actual[0] and camera.y <= actual[1]
    assert actual[2] <= camera.x + camera.width
    assert actual[3] <= camera.y + camera.height


@pytest.mark.parametrize("component,value", [
    ("scale_x", 1e308), ("position", 1e308), ("origin", 1e308),
])
def test_extreme_finite_group_transform_rejects_before_svg(component, value):
    layout, timeline = grouped_documents()
    transform = layout["objects"][3]["transform"]
    if component in ("position", "origin"):
        transform[component]["x"] = value
    else:
        transform[component] = value
    timeline["layout_sha256"] = digest(layout)
    with pytest.raises(V2FrameError, match="outside the supported range"):
        evaluate_frame(layout, timeline, 5000)
    with pytest.raises(V2FrameError, match="outside the supported range"):
        compose_svg_frame(layout, timeline, 5000)


def test_nested_world_affine_overflow_rejects_but_reasonable_scale_renders():
    layout, timeline = grouped_documents()
    outer = deepcopy(layout["objects"][3])
    outer["object_id"] = "object-outer"
    outer["child_ids"] = ["object-group"]
    layout["objects"][3]["parent_id"] = "object-outer"
    layout["objects"].append(outer)
    layout["boards"][0]["object_ids"].append("object-outer")
    timeline["initial_object_states"].append(
        {"object_id": "object-outer", "state": "visible", "state_version": 1,
         "visible": True}
    )
    for obj in layout["objects"][3:5]:
        obj["transform"]["scale_x"] = 100
        obj["transform"]["scale_y"] = 100
    timeline["layout_sha256"] = digest(layout)
    with pytest.raises(V2FrameError, match="outside the supported range"):
        compose_svg_frame(layout, timeline, 5000)
    for obj in layout["objects"][3:5]:
        obj["transform"]["scale_x"] = 1.2
        obj["transform"]["scale_y"] = 1.2
    timeline["layout_sha256"] = digest(layout)
    assert 'data-object-id="object-system"' in compose_svg_frame(layout, timeline, 5000).svg


def test_grouped_camera_uses_world_bounds_and_completed_parent_transform():
    layout, timeline = grouped_documents()
    append_camera(timeline, "camera-group", "camera_cut", 6000, 6500,
                  target="object-system", framing="medium")
    original = evaluate_frame(layout, timeline, 6000).camera
    layout["objects"][3]["transform"]["position"] = {"x": 300, "y": 0}
    timeline["layout_sha256"] = digest(layout)
    moved = evaluate_frame(layout, timeline, 6000).camera
    assert moved.x > original.x
    assert moved.width == pytest.approx(original.width)
    assert 'viewBox="' in compose_svg_frame(layout, timeline, 6000).svg

    # A completed parent move changes focus geometry at the camera boundary.
    layout, timeline = grouped_documents()
    action = timeline["actions"][2]["action"]
    action.update({"verb": "move", "target_ids": ["object-group"],
                   "expected_state": "visible", "post_state": "visible",
                   "destination": {"position": {"x": 300, "y": 0}, "scale_x": 1,
                                   "scale_y": 1, "rotation_degrees": 0,
                                   "origin": {"x": 0.5, "y": 0.5}}, "opacity": None})
    action.pop("annotation")
    append_camera(timeline, "camera-group", "camera_cut", 6000, 6500,
                  target="object-system", framing="medium")
    completed = evaluate_frame(layout, timeline, 6000).camera
    assert completed.x == pytest.approx(moved.x)


def test_grouped_camera_rejects_ancestor_edits_and_invisible_ancestors():
    layout, timeline = grouped_documents()
    action = timeline["actions"][2]["action"]
    action.update({"verb": "move", "target_ids": ["object-group"],
                   "expected_state": "visible", "post_state": "visible",
                   "destination": {"position": {"x": 70, "y": 0}, "scale_x": 1,
                                   "scale_y": 1, "rotation_degrees": 0,
                                   "origin": {"x": 0.5, "y": 0.5}}, "opacity": None})
    action.pop("annotation")
    append_camera(timeline, "camera-group", "camera_cut", 4500, 4700,
                  target="object-system")
    with pytest.raises(V2FrameError, match="overlaps a focus-object edit"):
        evaluate_frame(layout, timeline, 100)
    layout, timeline = grouped_documents()
    layout["objects"][3]["opacity"] = 0
    timeline["layout_sha256"] = digest(layout)
    append_camera(timeline, "camera-group", "camera_cut", 6000, 6500,
                  target="object-system")
    with pytest.raises(V2FrameError, match="revealed visible focus"):
        evaluate_frame(layout, timeline, 100)


def test_grouped_camera_uses_nested_rotated_world_aabb_and_multi_target_union():
    layout, timeline = grouped_documents()
    outer = deepcopy(layout["objects"][3])
    outer["object_id"] = "object-outer"
    outer["child_ids"] = ["object-group"]
    outer["transform"].update({"position": {"x": 90, "y": 30},
                               "scale_x": 0.85, "scale_y": 1.1,
                               "rotation_degrees": 8})
    layout["objects"][3]["parent_id"] = "object-outer"
    layout["objects"][3]["transform"].update({"scale_x": 0.9, "scale_y": 0.8,
                                               "rotation_degrees": -6})
    layout["objects"].append(outer)
    layout["boards"][0]["object_ids"].append("object-outer")
    timeline["initial_object_states"].append(
        {"object_id": "object-outer", "state": "visible", "state_version": 1,
         "visible": True}
    )
    timeline["layout_sha256"] = digest(layout)
    append_camera(timeline, "camera-group", "camera_cut", 6000, 6500,
                  target="object-system", framing="safe_area")
    timeline["actions"][-1]["action"]["target_ids"] = ["object-system", "object-label"]
    camera = evaluate_frame(layout, timeline, 6000).camera
    typed = ExecutableLayoutV2.model_validate(layout)
    objects = {obj.object_id: obj for obj in typed.objects}
    transforms = {obj.object_id: obj.transform for obj in typed.objects}
    for target_id in ("object-system", "object-label"):
        x1, y1, x2, y2 = world_bounds(objects[target_id], objects, transforms)
        assert camera.x + camera.width * 0.08 <= x1
        assert camera.y + camera.height * 0.08 <= y1
        assert x2 <= camera.x + camera.width * 0.92
        assert y2 <= camera.y + camera.height * 0.92
    assert compose_svg_frame(layout, timeline, 6000).svg == (
        compose_svg_frame(layout, timeline, 6000).svg
    )


def test_root_arrow_follows_grouped_endpoints_and_parent_motion():
    layout, timeline = connector_documents()
    group, _ = grouped_documents()
    container = deepcopy(group["objects"][3])
    container["transform"]["position"] = {"x": 75, "y": 0}
    layout["objects"].append(container)
    for obj in layout["objects"][:2]:
        obj["parent_id"] = "object-group"
    layout["boards"][0]["object_ids"].append("object-group")
    timeline["initial_object_states"].append(
        {"object_id": "object-group", "state": "visible", "state_version": 1,
         "visible": True}
    )
    layout["objects"][3]["geometry"]["bounds"] = {
        "x": 330, "y": 205, "width": 110, "height": 150,
    }
    timeline["layout_sha256"] = digest(layout)
    svg = compose_svg_frame(layout, timeline, 5000).svg
    path = _arrow_path(svg)
    typed = ExecutableLayoutV2.model_validate(layout)
    objects = {obj.object_id: obj for obj in typed.objects}
    states = {obj.object_id: obj.transform for obj in typed.objects}
    source = world_anchor(objects["object-system"], "center", objects, states)
    dest = world_anchor(objects["object-label"], "center", objects, states)
    assert path.startswith(f"M {source[0]:.0f} {source[1]:.0f}")
    assert f"L {dest[0]:.0f} {dest[1]:.0f}" in path
    assert compose_svg_frame(layout, timeline, 5000).svg == svg

    layout["objects"][3]["parent_id"] = "object-group"
    layout["objects"][4]["child_ids"].append("object-arrow")
    timeline["layout_sha256"] = digest(layout)
    with pytest.raises(V2FrameError, match="inverse parent geometry"):
        evaluate_frame(layout, timeline, 100)


def test_root_arrow_rejects_hidden_grouped_endpoint_and_world_bounds_escape():
    layout, timeline = connector_documents()
    group, _ = grouped_documents()
    container = deepcopy(group["objects"][3])
    layout["objects"].append(container)
    for obj in layout["objects"][:2]:
        obj["parent_id"] = "object-group"
    layout["boards"][0]["object_ids"].append("object-group")
    timeline["initial_object_states"].append(
        {"object_id": "object-group", "state": "visible", "state_version": 1,
         "visible": True}
    )
    container["opacity"] = 0
    timeline["layout_sha256"] = digest(layout)
    with pytest.raises(UnsupportedVisualObject, match="hidden endpoint"):
        compose_svg_frame(layout, timeline, 5000)
    container["opacity"] = 1
    container["transform"]["position"] = {"x": 400, "y": 0}
    timeline["layout_sha256"] = digest(layout)
    with pytest.raises(UnsupportedVisualObject, match="authored bounds"):
        compose_svg_frame(layout, timeline, 5000)


def test_fractional_grouped_connector_path_matches_world_anchors():
    layout, timeline = connector_documents()
    group, _ = grouped_documents()
    container = deepcopy(group["objects"][3])
    container["transform"].update({
        "position": {"x": 12.345678, "y": 6.543219},
        "scale_x": 1.021234, "scale_y": 0.987654,
        "rotation_degrees": 1.234567,
    })
    layout["objects"].append(container)
    for obj in layout["objects"][:2]:
        obj["parent_id"] = "object-group"
    layout["boards"][0]["object_ids"].append("object-group")
    timeline["initial_object_states"].append(
        {"object_id": "object-group", "state": "visible", "state_version": 1,
         "visible": True}
    )
    layout["objects"][3]["geometry"]["bounds"] = {
        "x": 200, "y": 160, "width": 200, "height": 220,
    }
    timeline["layout_sha256"] = digest(layout)
    typed = ExecutableLayoutV2.model_validate(layout)
    objects = {obj.object_id: obj for obj in typed.objects}
    transforms = {obj.object_id: obj.transform for obj in typed.objects}
    start = world_anchor(objects["object-system"], "center", objects, transforms)
    end = world_anchor(objects["object-label"], "center", objects, transforms)
    path = _arrow_path(compose_svg_frame(layout, timeline, 5000).svg)
    assert path.startswith(f"M {start[0]:.4f}".rstrip("0").rstrip("."))
    assert f"L {end[0]:.4f}".rstrip("0").rstrip(".") in path
    assert compose_svg_frame(layout, timeline, 5000).svg == (
        compose_svg_frame(layout, timeline, 5000).svg
    )


def test_root_arrow_tracks_parent_animation_at_random_access_times():
    layout, timeline = connector_documents()
    group, _ = grouped_documents()
    container = deepcopy(group["objects"][3])
    layout["objects"].append(container)
    for obj in layout["objects"][:2]:
        obj["parent_id"] = "object-group"
    layout["boards"][0]["object_ids"].append("object-group")
    timeline["initial_object_states"].append(
        {"object_id": "object-group", "state": "visible", "state_version": 1,
         "visible": True}
    )
    label = layout["objects"][1]
    label["visible"] = True
    label["initial_state"] = "visible"
    timeline["initial_object_states"][1].update({"state": "visible", "visible": True})
    arrow = layout["objects"][3]
    arrow["visible"] = True
    arrow["initial_state"] = "visible"
    timeline["initial_object_states"][3].update({"state": "visible", "visible": True})
    timeline["actions"][1]["action"] = {
        **common_action("action-2", "instruction-2"), "verb": "move",
        "target_ids": ["object-group"], "expected_state": "visible",
        "post_state": "visible", "destination": {
            "position": {"x": 35, "y": 0}, "scale_x": 1, "scale_y": 1,
            "rotation_degrees": 0, "origin": {"x": 0.5, "y": 0.5},
        }, "opacity": None,
    }
    timeline["actions"][2]["action"].update({"verb": "reveal",
                                               "target_ids": ["object-evidence"]})
    timeline["layout_sha256"] = digest(layout)
    before = _arrow_path(compose_svg_frame(layout, timeline, 1000).svg)
    middle = _arrow_path(compose_svg_frame(layout, timeline, 2500).svg)
    after = _arrow_path(compose_svg_frame(layout, timeline, 3500).svg)
    assert len({before, middle, after}) == 3
    assert _arrow_path(compose_svg_frame(layout, timeline, 2500).svg) == middle
