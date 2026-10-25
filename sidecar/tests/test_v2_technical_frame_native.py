"""Original native chrome has explicit regions/anchors and distinct state ink."""

import io
from importlib import import_module, util

import pytest
import resvg_py
from PIL import Image
from test_v2_technical_frame_contract import CASES, documents

from atme.store.contracts_v2 import VisualObject


def native():
    name = "atme.render.v2_technical_frame"
    assert util.find_spec(name) is not None, "shared native technical-frame geometry/paint is missing"
    return import_module(name)


def chrome(kind="browser", state="ready", roles=None):
    obj = documents(kind, state, roles)[1]["objects"][2]
    obj["geometry"]["bounds"] = {"x": 100.0, "y": 200.0, "width": 500.0, "height": 300.0}
    # Native browser's top edge is y=10/600, not the enclosing viewport edge.
    top = {"browser": 10, "application": 10, "server": 10, "database": 25, "folder": 120, "comparison": 100}
    obj["anchors"][0]["point"] = {"x": .5, "y": top[kind]/600}
    obj["style"] = {"stroke": "ink", "fill": None, "text": None, "effect": None}
    return VisualObject.model_validate(obj)


def rgba(svg, width=1280, height=720):
    wrapper = f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">{svg}</svg>'
    raw = bytes(resvg_py.svg_to_bytes(svg_string=wrapper, width=width, height=height, skip_system_fonts=True))
    with Image.open(io.BytesIO(raw)) as image:
        return image.convert("RGBA")


def test_browser_geometry_has_literal_fit_regions_and_physical_anchors():
    geometry = native().technical_frame_geometry(chrome())
    assert geometry.viewport == (100.0, 200.0, 500.0, 300.0)
    assert geometry.fitted == (100.0, 200.0, 500.0, 300.0)
    assert geometry.regions == (("title", 185.0, 210.0, 395.0, 30.0),
        ("address", 140.0, 262.5, 440.0, 25.0), ("content", 120.0, 310.0, 460.0, 170.0))
    assert geometry.anchors == (("top", 350.0, 205.0), ("right", 595.0, 350.0),
        ("bottom", 350.0, 495.0), ("left", 105.0, 350.0))


def test_meet_fit_uses_serialized_viewport_without_rounding_implicit_scale():
    obj = chrome()
    obj.geometry.bounds.height = 500.0
    geometry = native().technical_frame_geometry(obj)
    assert geometry.viewport == (100.0, 200.0, 500.0, 500.0)
    assert geometry.fitted == (100.0, 300.0, 500.0, 300.0)
    assert geometry.anchors[0] == ("top", 350.0, 305.0)
    # Same local normalized viewport anchor is now wrong: no inferred center.
    with pytest.raises(ValueError, match="native anchor"):
        native().validate_technical_frame_local(obj)
    obj.anchors[0].point.y = .21
    assert native().validate_technical_frame_local(obj) == geometry


@pytest.mark.parametrize("kind,states,roles", CASES)
def test_every_admitted_native_state_changes_actual_ink_not_metadata(kind, states, roles):
    pixels = []
    for state in states:
        obj = chrome(kind, state, roles)
        before = obj.model_dump(mode="json")
        markup = native().technical_frame_svg(obj, stroke="#121212", fill="none", stroke_width=4.0)
        image = rgba(markup)
        assert image.getchannel("A").getbbox() is not None
        pixels.append(image.tobytes())
        assert "<text" not in markup and "Authored" not in markup
        assert obj.model_dump(mode="json") == before
    assert len(set(pixels)) == len(states)


@pytest.mark.parametrize("portrait", [False, True])
def test_browser_ready_matches_independent_literal_native_pixels(portrait):
    width, height = (720, 1280) if portrait else (1280, 720)
    obj = chrome()
    actual = native().technical_frame_svg(obj, stroke="#121212", fill="none", stroke_width=4.0)
    expected = ('<svg x="100" y="200" width="500" height="300" viewBox="0 0 1000 600" '
        'preserveAspectRatio="xMidYMid meet" overflow="visible">'
        '<g fill="none" stroke="#121212" stroke-width="8" stroke-linecap="round" stroke-linejoin="round">'
        '<rect x="10" y="10" width="980" height="580" rx="20"/>'
        '<path d="M10 100H990"/>'
        '<circle cx="45" cy="50" r="9"/><circle cx="80" cy="50" r="9"/><circle cx="115" cy="50" r="9"/>'
        '<rect x="24" y="125" width="952" height="52" rx="12"/>'
        '<path d="M29 150L40 161L57 139"/></g></svg>')
    assert rgba(actual, width, height).tobytes() == rgba(expected, width, height).tobytes()


@pytest.mark.parametrize("fault", ["bare", "points", "radius", "asset", "text_style", "effect",
    "zero_viewport", "unknown_payload", "wrong_anchor"])
def test_native_paint_and_geometry_refuse_ignored_or_unproven_inputs(fault):
    module = native()
    obj = chrome()
    if fault == "bare":
        obj.technical_frame = None
    elif fault == "points":
        obj.geometry.points = [obj.anchors[0].point]
    elif fault == "radius":
        obj.geometry.corner_radius = 12
    elif fault == "asset":
        obj.asset_id = "invented-original"
    elif fault == "text_style":
        obj.style.text = "text.body"
    elif fault == "effect":
        obj.style.effect = "glow"
    elif fault == "zero_viewport":
        obj.geometry.bounds.width = .000001
    elif fault == "unknown_payload":
        obj.__dict__["unapproved"] = "discarded"
    else:
        obj.anchors[0].point.y = 0.0
    with pytest.raises(ValueError):
        module.validate_technical_frame_local(obj)


@pytest.mark.parametrize("stroke,fill,width", [("url(file:///bad)", "none", 4),
    ("#121212", "url(https://bad)", 4), ("#121212", "none", 0), ("#121212", "none", float("nan"))])
def test_paint_has_no_external_css_or_invalid_stroke_fallback(stroke, fill, width):
    with pytest.raises(ValueError):
        native().technical_frame_svg(chrome(), stroke=stroke, fill=fill, stroke_width=width)
