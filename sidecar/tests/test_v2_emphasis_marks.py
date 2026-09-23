"""Authored Paper & Ink emphasis marks remain bounded, drawn strokes."""

from __future__ import annotations

import io
import xml.etree.ElementTree as ET

import pytest
from atme.render.v2_svg import (
    UnsupportedVisualObject,
    compose_png_frame,
    compose_svg_frame,
)
from PIL import Image, ImageChops
from test_v2_svg import primitive_documents
from v2_fixtures import digest


def emphasis_documents(kind: str):
    layout, timeline = primitive_documents()
    mark = layout["objects"][2]
    mark["object_type"] = kind
    mark["geometry"]["corner_radius"] = None
    mark["style"]["stroke"] = None
    mark["style"]["fill"] = None
    timeline["actions"][2]["action"]["verb"] = "draw"
    timeline["layout_sha256"] = digest(layout)
    return layout, timeline


@pytest.mark.parametrize("kind,color", [
    ("underline", "#2457D6"),
    ("highlight", "#B93838"),
])
def test_authored_emphasis_has_nonrectangular_deterministic_draw(kind, color):
    layout, timeline = emphasis_documents(kind)
    start = compose_svg_frame(layout, timeline, 4000).svg
    partial = compose_svg_frame(layout, timeline, 4450).svg
    complete = compose_svg_frame(layout, timeline, 4900).svg
    assert 'data-object-id="object-evidence"' not in start
    group = next(node for node in ET.fromstring(partial).iter()
                 if node.attrib.get("data-object-id") == "object-evidence")
    path = next(node for node in group if node.tag.endswith("path"))
    assert path.attrib["fill"] == "none"
    assert path.attrib["stroke"] == color
    assert "stroke-dasharray" in path.attrib
    assert (" Q " if kind == "underline" else " C ") in path.attrib["d"]
    assert 'clip-path="url(#' not in partial
    assert 'stroke-dasharray=' not in complete
    initial_png = Image.open(io.BytesIO(compose_png_frame(layout, timeline, 4000).png)).convert("RGB")
    partial_png = Image.open(io.BytesIO(compose_png_frame(layout, timeline, 4450).png)).convert("RGB")
    complete_png = Image.open(io.BytesIO(compose_png_frame(layout, timeline, 4900).png)).convert("RGB")
    assert ImageChops.difference(initial_png, partial_png).getbbox()
    assert ImageChops.difference(partial_png, complete_png).getbbox()
    assert compose_svg_frame(layout, timeline, 4450).svg == partial


@pytest.mark.parametrize("change,match", [
    ({"path_data": "M 0 0 L 1 1"}, "unimplemented path"),
    ({"style": {"stroke": None, "fill": "surface.accent", "text": None, "effect": None}}, "cannot use a fill"),
    ({"geometry": {"bounds": {"x": 680, "y": 130, "width": 500, "height": 420},
                   "points": [{"x": 700, "y": 150}], "corner_radius": None}}, "ignored geometry points"),
])
@pytest.mark.parametrize("kind", ["underline", "highlight"])
def test_emphasis_rejects_ignored_authoring_fields_even_while_hidden(kind, change, match):
    layout, timeline = emphasis_documents(kind)
    layout["objects"][2].update(change)
    timeline["layout_sha256"] = digest(layout)
    with pytest.raises(UnsupportedVisualObject, match=match):
        compose_svg_frame(layout, timeline, 0)


@pytest.mark.parametrize("kind", ["underline", "highlight"])
def test_emphasis_rejects_unknown_stroke_token(kind):
    layout, timeline = emphasis_documents(kind)
    layout["objects"][2]["style"]["stroke"] = "unknown.color"
    timeline["layout_sha256"] = digest(layout)
    with pytest.raises(UnsupportedVisualObject, match="unknown Paper & Ink style token"):
        compose_svg_frame(layout, timeline, 0)
