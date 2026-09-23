"""Real bounded freehand geometry and progressive stroke rendering."""

from __future__ import annotations

import io
import xml.etree.ElementTree as ET

import pytest
from atme.render.v2_path import InvalidFreehandPath, parse_freehand_path
from atme.render.v2_svg import (
    UnsupportedVisualObject,
    compose_png_frame,
    compose_svg_frame,
)
from atme.store.contracts_v2 import Bounds
from PIL import Image
from test_v2_svg import primitive_documents
from v2_fixtures import digest

BOUNDS = Bounds(x=80, y=160, width=480, height=340)


@pytest.mark.parametrize("source", [
    "M 80 160 L 200 210 L 300 280",
    "M 80 160 Q 200 210 300 280",
    "M 80 160 C 130 400 250 190 400 300",
])
def test_safe_curves_have_real_nonzero_length(source):
    path = parse_freehand_path(source, BOUNDS)
    assert path.length > 0
    assert path.svg_d.startswith("M 80 160 ")


@pytest.mark.parametrize("source", [
    '<script>alert(1)</script>',
    'M 80 160 A 20 20 0 0 1 200 200',
    'm 80 160 l 200 200',
    'M 80 160 L 200',
    'M 80 160 M 200 200 L 300 300',
    'M 80 160 L 200 200 Z',
    'M 80 160 L 999 300',
    'M 80 160 L 80 160',
    'M 80 160 L 80.0000001 160',
    'M 80 160 Q 1e999 200 300 300',
])
def test_unsupported_or_malformed_paths_fail_closed(source):
    with pytest.raises(InvalidFreehandPath):
        parse_freehand_path(source, BOUNDS)


@pytest.mark.parametrize("use_path", [False, True])
def test_freehand_is_rendered_and_drawn_as_a_real_stroke(use_path):
    layout, timeline = primitive_documents()
    target = layout["objects"][0]
    target["object_type"] = "freehand"
    target["geometry"]["corner_radius"] = None
    target["style"]["fill"] = None
    if use_path:
        target["path_data"] = "M 80 160 C 150 480 300 180 450 400"
    else:
        target["geometry"]["points"] = [
            {"x": 80, "y": 160}, {"x": 200, "y": 300}, {"x": 450, "y": 400},
        ]
    timeline["actions"][0]["action"]["verb"] = "draw"
    timeline["layout_sha256"] = digest(layout)
    midpoint = compose_svg_frame(layout, timeline, 450).svg
    root = ET.fromstring(midpoint)
    assert any(node.tag.endswith("path" if use_path else "polyline") for node in root.iter())
    assert "stroke-dasharray=" in midpoint
    assert 'clip-path="url(#' not in midpoint
    mid_png = compose_png_frame(layout, timeline, 450).png
    end_png = compose_png_frame(layout, timeline, 900).png
    def blue(png):
        image = Image.open(io.BytesIO(png)).convert("RGB")
        return sum(pixel == (36, 87, 214)
                   for pixel in image.crop((78, 158, 562, 502)).get_flattened_data())
    assert 0 < blue(mid_png) < blue(end_png)
    compose_png_frame(layout, timeline, 900)
    assert compose_png_frame(layout, timeline, 450).png == mid_png


def test_invalid_freehand_blocks_even_before_its_action_starts():
    layout, timeline = primitive_documents()
    target = layout["objects"][0]
    target["object_type"] = "freehand"
    target["geometry"]["corner_radius"] = None
    target["style"]["fill"] = None
    target["path_data"] = 'M 80 160 L 200 200" onload="alert(1)'
    timeline["actions"][0]["action"]["verb"] = "draw"
    timeline["layout_sha256"] = digest(layout)
    with pytest.raises(UnsupportedVisualObject, match="freehand path"):
        compose_svg_frame(layout, timeline, 0)


def test_freehand_rejects_ambiguous_dual_geometry():
    layout, timeline = primitive_documents()
    target = layout["objects"][0]
    target["object_type"] = "freehand"
    target["geometry"]["corner_radius"] = None
    target["style"]["fill"] = None
    target["path_data"] = "M 80 160 L 200 200"
    target["geometry"]["points"] = [{"x": 80, "y": 160}, {"x": 200, "y": 200}]
    timeline["layout_sha256"] = digest(layout)
    with pytest.raises(UnsupportedVisualObject, match="cannot mix path data and points"):
        compose_svg_frame(layout, timeline, 0)


def test_freehand_rejects_unbounded_point_inventory():
    layout, timeline = primitive_documents()
    target = layout["objects"][0]
    target["object_type"] = "freehand"
    target["geometry"]["corner_radius"] = None
    target["style"]["fill"] = None
    target["geometry"]["points"] = [{"x": 80 + index, "y": 160} for index in range(258)]
    timeline["layout_sha256"] = digest(layout)
    with pytest.raises(UnsupportedVisualObject, match="exceeds 256 line segments"):
        compose_svg_frame(layout, timeline, 0)


def test_freehand_path_rejects_extreme_finite_coordinates():
    enormous = Bounds(x=-8.9e307, y=-8.9e307, width=1.78e308, height=1.78e308)
    with pytest.raises(InvalidFreehandPath, match="supported range"):
        parse_freehand_path("M -8.9e307 -8.9e307 L 8.9e307 8.9e307", enormous)


def test_freehand_points_reject_visual_zero_length_after_svg_rounding():
    layout, timeline = primitive_documents()
    target = layout["objects"][0]
    target["object_type"] = "freehand"
    target["geometry"]["corner_radius"] = None
    target["style"]["fill"] = None
    target["geometry"]["points"] = [
        {"x": 80, "y": 160}, {"x": 80.000001, "y": 160},
    ]
    timeline["layout_sha256"] = digest(layout)
    with pytest.raises(UnsupportedVisualObject, match="zero length"):
        compose_svg_frame(layout, timeline, 0)
