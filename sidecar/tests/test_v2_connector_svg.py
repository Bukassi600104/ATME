"""Bounded semantic arrows bind to live object anchors, not flat page coordinates."""

from __future__ import annotations

import io
import math
import xml.etree.ElementTree as ET
from copy import deepcopy

import pytest
from atme.render.v2_svg import (
    UnsupportedVisualObject,
    compose_png_frame,
    compose_svg_frame,
)
from PIL import Image
from test_v2_svg import primitive_documents
from v2_fixtures import common_action, digest


def connector_documents(routing="straight"):
    layout, timeline = primitive_documents()
    arrow = deepcopy(layout["objects"][0])
    arrow.pop("path_data")
    arrow.update({
        "object_id": "object-arrow", "object_type": "arrow", "z_index": 4,
        "semantic_role": "System-to-label relationship",
        "geometry": {"bounds": {"x": 255, "y": 205, "width": 110, "height": 150},
                     "points": [], "corner_radius": None},
        "anchors": [], "style": {"stroke": "ink.accent", "fill": None,
                                "text": None, "effect": None},
        "source_object_id": "object-system", "source_anchor_id": "center",
        "destination_object_id": "object-label", "destination_anchor_id": "center",
        "role": "semantic_connector", "routing": routing, "allow_self_loop": False,
        "description": "Relationship from system to label", "coverage_ids": ["coverage-3"],
    })
    layout["objects"].append(arrow)
    layout["boards"][0]["object_ids"].append("object-arrow")
    timeline["initial_object_states"].append(
        {"object_id": "object-arrow", "state": "hidden", "state_version": 1, "visible": False}
    )
    timeline["actions"][2]["action"]["verb"] = "draw"
    timeline["actions"][2]["action"]["target_ids"] = ["object-arrow"]
    timeline["layout_sha256"] = digest(layout)
    return layout, timeline


@pytest.mark.parametrize("routing", ["straight", "elbow", "curve"])
def test_arrow_routes_are_real_and_draw_progressively(routing):
    layout, timeline = connector_documents(routing)
    partial = compose_svg_frame(layout, timeline, 4450).svg
    complete = compose_svg_frame(layout, timeline, 4900).svg
    root = ET.fromstring(partial)
    arrow = next(node for node in root.iter() if node.attrib.get("data-object-id") == "object-arrow")
    path = next(node for node in arrow if node.tag.endswith("path"))
    assert "stroke-dasharray" in path.attrib
    assert not any(node.tag.endswith("polygon") for node in arrow)
    if routing == "curve":
        assert " Q " in path.attrib["d"]
    if routing == "elbow":
        assert path.attrib["d"].count(" L ") == 2
    assert 'data-object-id="object-arrow"' in complete
    assert "<polygon points=" in complete
    partial_png = compose_png_frame(layout, timeline, 4450).png
    complete_png = compose_png_frame(layout, timeline, 4900).png
    assert partial_png != complete_png
    image = Image.open(io.BytesIO(complete_png)).convert("RGB")
    assert image.getpixel((300, 250)) != (250, 248, 241)
    compose_png_frame(layout, timeline, 4900)
    assert compose_png_frame(layout, timeline, 4450).png == partial_png


def test_arrow_rejects_missing_or_unnormalized_endpoints_even_while_hidden():
    layout, timeline = connector_documents()
    layout["objects"][3]["source_object_id"] = None
    layout["objects"][3]["source_anchor_id"] = None
    timeline["layout_sha256"] = digest(layout)
    with pytest.raises((UnsupportedVisualObject, ValueError), match="source"):
        compose_svg_frame(layout, timeline, 0)
    layout, timeline = connector_documents()
    layout["objects"][1]["anchors"][0]["point"]["x"] = 1.5
    timeline["layout_sha256"] = digest(layout)
    with pytest.raises(UnsupportedVisualObject, match="normalized"):
        compose_svg_frame(layout, timeline, 0)


@pytest.mark.parametrize("change,match", [
    ({"routing": "straight", "object_type": "network"}, "no SVG implementation"),
    ({"source_object_id": "object-label", "destination_object_id": "object-label",
      "allow_self_loop": True}, "loop back"),
    ({"geometry": {"bounds": {"x": 300, "y": 240, "width": 5, "height": 5},
                   "points": [], "corner_radius": None}}, "authored bounds"),
])
def test_unsupported_connector_forms_fail_closed(change, match):
    layout, timeline = connector_documents()
    layout["objects"][3].update(change)
    timeline["layout_sha256"] = digest(layout)
    with pytest.raises(UnsupportedVisualObject, match=match):
        compose_svg_frame(layout, timeline, 4450)


def test_arrow_tracks_endpoint_move_at_random_access_times():
    layout, timeline = connector_documents()
    label = layout["objects"][1]
    label["visible"] = True
    label["initial_state"] = "visible"
    timeline["initial_object_states"][1].update(state="visible", visible=True)
    arrow = layout["objects"][3]
    arrow["visible"] = True
    arrow["initial_state"] = "visible"
    timeline["initial_object_states"][3].update(state="visible", visible=True)
    timeline["actions"][2]["action"].update(verb="reveal", target_ids=["object-evidence"])
    destination = deepcopy(label["transform"])
    destination["position"] = {"x": 40, "y": 0}
    timeline["actions"][1]["action"] = {
        **common_action("action-2", "instruction-2"),
        "verb": "move", "target_ids": ["object-label"],
        "expected_state": "visible", "destination": destination, "opacity": None,
    }
    timeline["layout_sha256"] = digest(layout)
    before = compose_svg_frame(layout, timeline, 1000).svg
    after = compose_svg_frame(layout, timeline, 3000).svg
    def arrow_path(svg):
        root = ET.fromstring(svg)
        arrow_group = next(node for node in root.iter()
                           if node.attrib.get("data-object-id") == "object-arrow")
        return next(node.attrib["d"] for node in arrow_group if node.tag.endswith("path"))
    assert arrow_path(before) != arrow_path(after)
    assert "L 300 250" in arrow_path(before)
    assert "L 340 250" in arrow_path(after)
    assert compose_svg_frame(layout, timeline, 1000).svg == before


def test_arrow_uses_rotated_off_center_anchor():
    layout, timeline = connector_documents()
    label = layout["objects"][1]
    label["anchors"][0]["point"] = {"x": 0, "y": 0.5}
    label["transform"]["rotation_degrees"] = 90
    layout["objects"][3]["geometry"]["bounds"] = {
        "x": 120, "y": 70, "width": 250, "height": 290,
    }
    timeline["layout_sha256"] = digest(layout)
    svg = compose_svg_frame(layout, timeline, 4450).svg
    root = ET.fromstring(svg)
    group = next(node for node in root.iter()
                 if node.attrib.get("data-object-id") == "object-arrow")
    path = next(node.attrib["d"] for node in group if node.tag.endswith("path"))
    assert "L 300 90" in path


def test_arrow_anchor_matches_emitted_fractional_transform():
    layout, timeline = connector_documents()
    label = layout["objects"][1]
    label["anchors"][0]["point"] = {"x": 0.123456, "y": 0.654321}
    label["transform"] = {
        "position": {"x": 15.1234567, "y": -7.7654321},
        "scale_x": 1.234567, "scale_y": 0.876543,
        "rotation_degrees": 17.123456,
        "origin": {"x": 0.234567, "y": 0.765432},
    }
    layout["objects"][3]["geometry"]["bounds"] = {
        "x": 100, "y": 150, "width": 300, "height": 250,
    }
    timeline["layout_sha256"] = digest(layout)
    svg = compose_svg_frame(layout, timeline, 4450).svg
    root = ET.fromstring(svg)
    group = next(node for node in root.iter()
                 if node.attrib.get("data-object-id") == "object-arrow")
    path = next(node.attrib["d"] for node in group if node.tag.endswith("path"))
    _, actual_x, actual_y = path.rsplit(" ", 2)

    def emitted(value):
        return float(f"{value:.4f}")

    bounds = label["geometry"]["bounds"]
    transform = label["transform"]
    anchor = label["anchors"][0]["point"]
    x = emitted(bounds["x"]) + emitted(bounds["width"]) * anchor["x"]
    y = emitted(bounds["y"]) + emitted(bounds["height"]) * anchor["y"]
    origin_x = emitted(bounds["x"] + bounds["width"] * transform["origin"]["x"])
    origin_y = emitted(bounds["y"] + bounds["height"] * transform["origin"]["y"])
    dx = (x - origin_x) * emitted(transform["scale_x"])
    dy = (y - origin_y) * emitted(transform["scale_y"])
    angle = math.radians(emitted(transform["rotation_degrees"]))
    expected_x = origin_x + dx * math.cos(angle) - dy * math.sin(angle) + emitted(transform["position"]["x"])
    expected_y = origin_y + dx * math.sin(angle) + dy * math.cos(angle) + emitted(transform["position"]["y"])
    assert float(actual_x) == pytest.approx(expected_x, abs=0.0001)
    assert float(actual_y) == pytest.approx(expected_y, abs=0.0001)


def test_visible_arrow_with_hidden_endpoint_fails_instead_of_floating():
    layout, timeline = connector_documents()
    label = layout["objects"][1]
    label["visible"] = True
    label["initial_state"] = "visible"
    timeline["initial_object_states"][1].update(state="visible", visible=True)
    timeline["actions"][1]["action"].update(
        verb="exit", expected_state="visible", post_state="removed",
    )
    timeline["layout_sha256"] = digest(layout)
    with pytest.raises(UnsupportedVisualObject, match="hidden endpoint"):
        compose_svg_frame(layout, timeline, 4450)


def test_visible_arrow_rejects_faded_out_endpoint():
    layout, timeline = connector_documents()
    label = layout["objects"][1]
    label["visible"] = True
    label["initial_state"] = "visible"
    timeline["initial_object_states"][1].update(state="visible", visible=True)
    timeline["actions"][1]["action"] = {
        **common_action("action-2", "instruction-2"),
        "verb": "fade", "target_ids": ["object-label"],
        "expected_state": "visible", "destination": None, "opacity": 0,
    }
    timeline["layout_sha256"] = digest(layout)
    with pytest.raises(UnsupportedVisualObject, match="hidden endpoint"):
        compose_svg_frame(layout, timeline, 4450)


def test_visible_arrow_rejects_zero_progress_endpoint_reveal():
    layout, timeline = connector_documents()
    arrow = layout["objects"][3]
    arrow["visible"] = True
    arrow["initial_state"] = "visible"
    timeline["initial_object_states"][3].update(state="visible", visible=True)
    timeline["actions"][2]["action"]["expected_state"] = "visible"
    timeline["layout_sha256"] = digest(layout)
    with pytest.raises(UnsupportedVisualObject, match="hidden endpoint"):
        compose_svg_frame(layout, timeline, 2000)
