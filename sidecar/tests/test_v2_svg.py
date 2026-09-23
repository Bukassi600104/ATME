"""The v2 SVG slice renders only faithful, explicitly supported primitives."""

from __future__ import annotations

import hashlib
import io
import xml.etree.ElementTree as ET

import pytest
from atme.render.v2_state import V2FrameError
from atme.render.v2_svg import (
    UnsupportedVisualObject,
    compose_png_frame,
    compose_svg_frame,
)
from PIL import Image
from test_v2_frame_state import supported_documents
from v2_fixtures import digest


def primitive_documents():
    layout, timeline = supported_documents()
    timeline["actions"][0]["action"]["verb"] = "reveal"
    timeline["actions"][1]["action"]["verb"] = "reveal"
    evidence = layout["objects"][2]
    evidence["object_type"] = "ellipse"
    evidence.pop("variant")
    evidence["asset_id"] = None
    evidence["style"]["fill"] = "surface.accent"
    evidence["style"]["stroke"] = "ink.accent"
    evidence["geometry"]["corner_radius"] = None
    evidence["path_data"] = None
    timeline["layout_sha256"] = digest(layout)
    return layout, timeline


def test_draws_styled_marks_and_text_at_random_access_frame():
    layout, timeline = primitive_documents()
    frame = compose_svg_frame(layout, timeline, 5000)
    root = ET.fromstring(frame.svg)
    assert root.attrib["viewBox"] == "0 0 1280 720"
    ids = [node.attrib["data-object-id"] for node in root.iter()
           if "data-object-id" in node.attrib]
    assert ids == ["object-system", "object-label", "object-evidence"]
    assert "THE SYSTEM" in frame.svg
    assert "Kalam" in frame.svg
    assert "#2457D6" in frame.svg
    assert compose_svg_frame(layout, timeline, 5000).svg == frame.svg


def test_reveal_is_clipped_then_unclipped():
    layout, timeline = primitive_documents()
    during = compose_svg_frame(layout, timeline, 450)
    complete = compose_svg_frame(layout, timeline, 900)
    clip_id = "clip-" + hashlib.sha256(b"object-system").hexdigest()
    assert f'clip-path="url(#{clip_id})"' in during.svg
    assert f'clip-path="url(#{clip_id})"' not in complete.svg
    assert 'data-object-id="object-label"' not in during.svg


def test_unsupported_hidden_object_rejects_full_layout():
    layout, timeline = supported_documents()
    timeline["actions"][0]["action"]["verb"] = "reveal"
    timeline["actions"][1]["action"]["verb"] = "reveal"
    with pytest.raises(UnsupportedVisualObject, match="object-evidence uses evidence"):
        compose_svg_frame(layout, timeline, 100)


def test_unknown_token_and_unhandled_effect_reject():
    layout, timeline = primitive_documents()
    layout["objects"][0]["style"]["fill"] = "invented.token"
    timeline["layout_sha256"] = digest(layout)
    with pytest.raises(UnsupportedVisualObject, match="unknown Paper & Ink style token"):
        compose_svg_frame(layout, timeline, 1000)
    layout["objects"][0]["style"]["fill"] = "surface.paper"
    layout["objects"][0]["style"]["effect"] = "shadow"
    timeline["layout_sha256"] = digest(layout)
    with pytest.raises(UnsupportedVisualObject, match="unimplemented hierarchy, clip, effect, or asset"):
        compose_svg_frame(layout, timeline, 1000)


def test_progressive_reveal_requires_ordered_list_items():
    layout, timeline = primitive_documents()
    timeline["actions"][0]["action"]["verb"] = "progressive_reveal"
    with pytest.raises(V2FrameError, match="ordered-child list"):
        compose_svg_frame(layout, timeline, 100)


@pytest.mark.parametrize("action_index,verb", [(0, "write"), (1, "draw")])
def test_draw_and_write_reject_incompatible_object_types(action_index, verb):
    layout, timeline = primitive_documents()
    timeline["actions"][action_index]["action"]["verb"] = verb
    with pytest.raises(UnsupportedVisualObject, match="incompatible object type"):
        compose_svg_frame(layout, timeline, 100)


def test_draw_raster_constructs_real_stroke_without_rectangular_wipe():
    layout, timeline = primitive_documents()
    timeline["actions"][0]["action"]["verb"] = "draw"
    mid = compose_png_frame(layout, timeline, 450)
    end = compose_png_frame(layout, timeline, 900)

    def stroke_count(frame):
        image = Image.open(io.BytesIO(frame.png)).convert("RGB")
        return sum(pixel == (36, 87, 214)
                   for pixel in image.crop((78, 158, 562, 502)).get_flattened_data())

    assert 0 < stroke_count(mid) < stroke_count(end)
    mid_svg = compose_svg_frame(layout, timeline, 450).svg
    assert "stroke-dasharray=" in mid_svg
    assert 'clip-path="url(#' not in mid_svg


def test_write_reveals_whole_graphemes_not_clipped_letter_fragments():
    layout, timeline = primitive_documents()
    timeline["actions"][1]["action"]["verb"] = "write"
    partial = compose_svg_frame(layout, timeline, 2450).svg
    assert "THE SYS" in partial
    assert "THE SYSTEM" not in partial
    assert "stroke-dasharray=" not in partial
    assert 'clip-path="url(#' not in partial
    partial_png = compose_png_frame(layout, timeline, 2450).png
    full_png = compose_png_frame(layout, timeline, 2900).png
    assert partial_png != full_png
    assert compose_png_frame(layout, timeline, 2450).png == partial_png
    layout["objects"][1]["text"] = "A\u0301B"
    timeline["layout_sha256"] = digest(layout)
    combined = compose_svg_frame(layout, timeline, 2450).svg
    assert "A\u0301" in combined
    assert "A\u0301B" not in combined


@pytest.mark.parametrize("kind", ["line", "rectangle", "rounded_rectangle", "ellipse", "polygon"])
def test_draw_each_supported_path_at_random_access_time(kind):
    layout, timeline = primitive_documents()
    mark = layout["objects"][0]
    mark["object_type"] = kind
    mark["geometry"]["corner_radius"] = 24 if kind == "rounded_rectangle" else None
    mark["geometry"]["points"] = (
        [{"x": 80, "y": 160}, {"x": 400, "y": 160}, {"x": 400, "y": 400}]
        if kind == "polygon" else []
    )
    mark["style"]["fill"] = None if kind == "line" else "surface.raised"
    timeline["actions"][0]["action"]["verb"] = "draw"
    timeline["layout_sha256"] = digest(layout)
    first = compose_png_frame(layout, timeline, 450).png
    compose_png_frame(layout, timeline, 899)
    complete = compose_png_frame(layout, timeline, 900).png
    assert compose_png_frame(layout, timeline, 450).png == first
    assert b"PNG" in first[:8]
    def blue_pixels(png):
        image = Image.open(io.BytesIO(png)).convert("RGB")
        return sum(pixel == (36, 87, 214)
                   for pixel in image.crop((78, 158, 562, 502)).get_flattened_data())

    assert 0 < blue_pixels(first) < blue_pixels(complete)
    assert "stroke-dasharray=" in compose_svg_frame(layout, timeline, 450).svg


def test_draw_rejects_future_zero_length_path_before_first_frame():
    layout, timeline = primitive_documents()
    mark = layout["objects"][0]
    mark["object_type"] = "line"
    mark["geometry"]["corner_radius"] = None
    mark["geometry"]["points"] = [{"x": 80, "y": 160}, {"x": 80, "y": 160}]
    mark["style"]["fill"] = None
    timeline["actions"][0]["action"]["verb"] = "draw"
    timeline["layout_sha256"] = digest(layout)
    with pytest.raises(UnsupportedVisualObject, match="zero length"):
        compose_svg_frame(layout, timeline, 0)


@pytest.mark.parametrize("kind,tag", [
    ("rectangle", "rect"), ("rounded_rectangle", "rect"),
    ("ellipse", "ellipse"), ("line", "line"), ("polygon", "polygon"),
])
def test_supported_mark_shapes_have_real_svg_geometry(kind, tag):
    layout, timeline = primitive_documents()
    target = layout["objects"][0]
    target["object_type"] = kind
    target["geometry"]["corner_radius"] = 24 if kind == "rounded_rectangle" else None
    target["style"]["fill"] = None if kind == "line" else "surface.accent"
    target["geometry"]["points"] = (
        [{"x": 80, "y": 160}, {"x": 200, "y": 200}, {"x": 400, "y": 300}]
        if kind == "polygon" else []
    )
    timeline["layout_sha256"] = digest(layout)
    root = ET.fromstring(compose_svg_frame(layout, timeline, 1000).svg)
    object_group = next(node for node in root.iter()
                        if node.attrib.get("data-object-id") == "object-system")
    assert any(child.tag.endswith(tag) for child in object_group)


def test_hidden_invalid_object_still_rejects_the_whole_frame():
    layout, timeline = primitive_documents()
    layout["objects"][2]["style"]["stroke"] = "not.a.token"
    timeline["layout_sha256"] = digest(layout)
    with pytest.raises(UnsupportedVisualObject, match="unknown Paper & Ink style token"):
        compose_svg_frame(layout, timeline, 100)


def test_text_is_xml_escaped_without_changing_authored_content():
    layout, timeline = primitive_documents()
    layout["objects"][1]["text"] = "A & B < C"
    timeline["layout_sha256"] = digest(layout)
    svg = compose_svg_frame(layout, timeline, 3000).svg
    assert "A &amp; B &lt; C" in svg
    ET.fromstring(svg)


def test_heading_and_label_use_explicit_pinned_font_weights():
    layout, timeline = primitive_documents()
    heading = compose_svg_frame(layout, timeline, 3000).svg
    assert 'font-family="Kalam" font-weight="700"' in heading
    layout["objects"][1]["style"]["text"] = "text.label"
    timeline["layout_sha256"] = digest(layout)
    label = compose_svg_frame(layout, timeline, 3000).svg
    assert 'font-family="Kalam" font-weight="700"' in label
    assert 'font-size="17.3333"' in label


def test_xml_forbidden_character_fails_before_emitting_svg():
    layout, timeline = primitive_documents()
    layout["objects"][1]["text"] = "Invalid\x01text"
    timeline["layout_sha256"] = digest(layout)
    with pytest.raises(UnsupportedVisualObject, match="invalid XML character"):
        compose_svg_frame(layout, timeline, 3000)


def test_text_width_is_measured_with_pinned_font():
    layout, timeline = primitive_documents()
    layout["objects"][1]["geometry"]["bounds"]["width"] = 24
    timeline["layout_sha256"] = digest(layout)
    with pytest.raises(UnsupportedVisualObject, match="exceeds authored width"):
        compose_svg_frame(layout, timeline, 3000)


def test_unusual_object_id_is_a_safe_svg_fragment():
    layout, timeline = primitive_documents()
    unusual = 'quote " ) # é'
    layout["objects"][0]["object_id"] = unusual
    layout["boards"][0]["object_ids"][0] = unusual
    timeline["initial_object_states"][0]["object_id"] = unusual
    timeline["actions"][0]["action"]["target_ids"] = [unusual]
    timeline["layout_sha256"] = digest(layout)
    svg = compose_svg_frame(layout, timeline, 450).svg
    clip_id = "clip-" + hashlib.sha256(unusual.encode("utf-8")).hexdigest()
    assert f'clip-path="url(#{clip_id})"' in svg
    ET.fromstring(svg)


def test_canvas_origin_is_preserved_and_profile_tokens_scale():
    layout, timeline = primitive_documents()
    layout["canvas"]["x"] = 50
    layout["canvas"]["y"] = 25
    timeline["layout_sha256"] = digest(layout)
    shifted = compose_svg_frame(layout, timeline, 3000)
    assert ET.fromstring(shifted.svg).attrib["viewBox"] == "50 25 1280 720"
    assert '<rect x="50" y="25" width="1280" height="720" fill="#FAF8F1"' in shifted.svg
    layout["canvas"] = {"x": 0, "y": 0, "width": 720, "height": 1280}
    layout["output_profile"] = {"profile_id": "SHORT_FORM_9_16", "width": 720,
                                "height": 1280, "fps": 30}
    timeline["output_profile"] = layout["output_profile"]
    timeline["layout_sha256"] = digest(layout)
    portrait = compose_svg_frame(layout, timeline, 3000)
    assert portrait.width == 720 and portrait.height == 1280
    assert ET.fromstring(portrait.svg).attrib["viewBox"] == "0 0 720 1280"


def test_raster_frame_shows_actual_ellipse_only_after_reveal():
    layout, timeline = primitive_documents()
    before = compose_png_frame(layout, timeline, 100)
    after = compose_png_frame(layout, timeline, 5000)
    assert Image.open(io.BytesIO(before.png)).convert("RGB").getpixel((930, 340)) == (250, 248, 241)
    assert Image.open(io.BytesIO(after.png)).convert("RGB").getpixel((930, 340)) == (220, 230, 255)


def test_embedded_text_raster_is_deterministic_without_system_fonts():
    layout, timeline = primitive_documents()
    first = compose_png_frame(layout, timeline, 3000).png
    second = compose_png_frame(layout, timeline, 3000).png
    assert hashlib.sha256(first).hexdigest() == hashlib.sha256(second).hexdigest()
    image = Image.open(io.BytesIO(first)).convert("RGB")
    text_region = image.crop((140, 210, 460, 290))
    assert any(pixel != (250, 248, 241) for pixel in text_region.get_flattened_data())
