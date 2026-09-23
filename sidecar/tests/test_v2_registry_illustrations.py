"""Original Paper & Ink registry illustrations enter the v2 compositor faithfully."""

from __future__ import annotations

import hashlib
import io
import xml.etree.ElementTree as ET

import pytest
from atme.render.style_bundle import StyleBundleError, _validate_svg, load_bundle
from atme.render.v2_svg import (
    UnsupportedVisualObject,
    compose_png_frame,
    compose_svg_frame,
)
from PIL import Image
from test_v2_svg import primitive_documents
from v2_fixtures import digest


def illustration_documents(variant="person-presenter", object_type="character"):
    layout, timeline = primitive_documents()
    visual = layout["objects"][2]
    visual["object_type"] = object_type
    visual.pop("path_data")
    visual["variant"] = variant
    visual["style"] = {"stroke": None, "fill": None, "text": None, "effect": None}
    timeline["layout_sha256"] = digest(layout)
    return layout, timeline


def test_original_character_raster_is_compact_and_visible():
    layout, timeline = illustration_documents()
    frame = compose_png_frame(layout, timeline, 5000)
    image = Image.open(io.BytesIO(frame.png)).convert("RGB")
    paper = (250, 248, 241)
    assert image.getpixel((600, 350)) == paper  # outside authored 500x420 bounds
    crop = image.crop((680, 130, 1180, 550))
    assert any(pixel != paper for pixel in crop.get_flattened_data())
    assert Image.open(io.BytesIO(compose_png_frame(layout, timeline, 100).png)).convert("RGB").getpixel((900, 350)) == paper


def test_illustration_mid_reveal_changes_visible_raster_area():
    layout, timeline = illustration_documents()

    def colored_pixels(at_ms):
        frame = compose_png_frame(layout, timeline, at_ms)
        image = Image.open(io.BytesIO(frame.png)).convert("RGB")
        return sum(pixel != (250, 248, 241)
                   for pixel in image.crop((680, 130, 1180, 550)).get_flattened_data())

    assert 0 < colored_pixels(4250) < colored_pixels(4900)


def test_portrait_registry_png_is_repeatable_and_bounded():
    layout, timeline = illustration_documents("metaphor-bridge", "pictogram")
    layout["output_profile"] = {"profile_id": "SHORT_FORM_9_16", "width": 720,
                                "height": 1280, "fps": 30}
    layout["canvas"] = {"x": 0, "y": 0, "width": 720, "height": 1280}
    layout["objects"][2]["geometry"]["bounds"] = {"x": 100, "y": 350,
                                                  "width": 500, "height": 420}
    timeline["output_profile"] = layout["output_profile"]
    timeline["layout_sha256"] = digest(layout)
    first = compose_png_frame(layout, timeline, 5000)
    second = compose_png_frame(layout, timeline, 5000)
    assert (first.width, first.height) == (720, 1280)
    assert hashlib.sha256(first.png).digest() == hashlib.sha256(second.png).digest()
    image = Image.open(io.BytesIO(first.png)).convert("RGB")
    assert image.getpixel((650, 800)) == (250, 248, 241)
    assert any(pixel != (250, 248, 241)
               for pixel in image.crop((100, 350, 600, 770)).get_flattened_data())


@pytest.mark.parametrize("asset_id", [asset.id for asset in load_bundle()[1].assets])
def test_every_pinned_original_asset_is_svg_and_png_composable(asset_id):
    _, registry, _ = load_bundle()
    asset = next(item for item in registry.assets if item.id == asset_id)
    layout, timeline = illustration_documents(asset.id, "icon")
    markup = compose_svg_frame(layout, timeline, 5000).svg
    root = ET.fromstring(markup)
    nested = [node for node in root.iter() if node.tag.endswith("svg")]
    assert len(nested) == 2
    assert f'viewBox="0 0 {asset.view_box[2]} {asset.view_box[3]}"' in markup
    frame = compose_png_frame(layout, timeline, 5000)
    image = Image.open(io.BytesIO(frame.png)).convert("RGB")
    assert any(pixel != (250, 248, 241)
               for pixel in image.crop((680, 130, 1180, 550)).get_flattened_data())


@pytest.mark.parametrize("object_type,variant", [
    ("character", "gesture-point"),
    ("character", "chart-bars"),
    ("chart", "person-presenter"),
    ("device", "document-stack"),
])
def test_semantically_wrong_family_is_rejected(object_type, variant):
    layout, timeline = illustration_documents(variant, object_type)
    with pytest.raises(UnsupportedVisualObject, match="cannot use"):
        compose_svg_frame(layout, timeline, 5000)


@pytest.mark.parametrize("object_type,variant", [
    ("pictogram", "gesture-point"),
    ("character", "person-presenter"),
    ("device", "device-laptop"),
    ("document", "document-stack"),
    ("chart", "chart-bars"),
    ("terminal", "frame-terminal"),
])
def test_supported_semantic_object_families_render(object_type, variant):
    layout, timeline = illustration_documents(variant, object_type)
    assert 'data-object-id="object-evidence"' in compose_svg_frame(layout, timeline, 5000).svg


def test_missing_variant_and_overridden_style_fail_even_while_hidden():
    layout, timeline = illustration_documents()
    layout["objects"][2]["variant"] = "not-in-registry"
    timeline["layout_sha256"] = digest(layout)
    with pytest.raises(StyleBundleError, match="unknown Paper & Ink asset"):
        compose_svg_frame(layout, timeline, 100)
    layout["objects"][2]["variant"] = "person-presenter"
    layout["objects"][2]["style"]["fill"] = "surface.accent"
    timeline["layout_sha256"] = digest(layout)
    with pytest.raises(UnsupportedVisualObject, match="cannot override pinned illustration"):
        compose_svg_frame(layout, timeline, 100)


def test_verified_asset_bytes_are_checked_at_composition_time(monkeypatch):
    from atme.render import style_bundle

    layout, timeline = illustration_documents()
    original = style_bundle._verified_file

    def reject_asset(root, relative, expected):
        if relative == "assets/person-presenter.svg":
            raise StyleBundleError("resource checksum mismatch: asset")
        return original(root, relative, expected)

    monkeypatch.setattr(style_bundle, "_verified_file", reject_asset)
    with pytest.raises(StyleBundleError, match="checksum mismatch"):
        compose_svg_frame(layout, timeline, 5000)


@pytest.mark.parametrize("markup", [
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10" onload="alert(1)"/>',
    ('<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
     'viewBox="0 0 10 10"><use xlink:href="data:image/svg+xml;base64,AA"/></svg>'),
    ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
     '<style>@import url(https://invalid.example/a.css)</style></svg>'),
    ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
     '<a href="file:///C:/secret"><path d="M0 0L1 1"/></a></svg>'),
    ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
     '<path d="M0 0L1 1" stroke="#ff00ff"/></svg>'),
    ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
     '<svg viewBox="0 0 100000 100000"><path d="M0 0L1 1"/></svg></svg>'),
])
def test_svg_sanitizer_rejects_script_links_styles_and_unapproved_paint(tmp_path, markup):
    candidate = tmp_path / "hostile.svg"
    candidate.write_text(markup, encoding="utf-8")
    with pytest.raises(StyleBundleError):
        _validate_svg(candidate, (0, 0, 10, 10))


def test_illustration_move_has_distinct_raster_positions():
    layout, timeline = illustration_documents()
    layout["objects"][2]["visible"] = True
    layout["objects"][2]["initial_state"] = "visible"
    timeline["initial_object_states"][2]["visible"] = True
    timeline["initial_object_states"][2]["state"] = "visible"
    action = timeline["actions"][2]["action"]
    action.update({
        "verb": "move", "expected_state": "visible", "post_state": "visible",
        "destination": {"position": {"x": 120, "y": 0}, "scale_x": 1,
                        "scale_y": 1, "rotation_degrees": 0,
                        "origin": {"x": 0.5, "y": 0.5}},
        "opacity": None,
    })
    action.pop("annotation")
    timeline["layout_sha256"] = digest(layout)

    def leftmost(at_ms):
        frame = compose_png_frame(layout, timeline, at_ms)
        image = Image.open(io.BytesIO(frame.png)).convert("RGB")
        for x in range(640, 1260):
            if any(image.getpixel((x, y)) != (250, 248, 241)
                   for y in range(150, 520, 4)):
                return x
        raise AssertionError("illustration not visible")

    assert leftmost(3900) < leftmost(4450) < leftmost(4900)
