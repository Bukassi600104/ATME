"""Owning Callout body pixel proof; pointer/lifecycle admission is separate."""

import importlib
import importlib.util
import io
from copy import deepcopy

import pytest
import resvg_py
from atme.render.style_bundle import load_bundle
from atme.render.v2_svg import SVGFrame, _rasterize_frozen_svg
from atme.store.contracts_v2 import TextObject
from PIL import Image
from test_v2_callout_contract import callout_documents


def primitive():
    name = "atme.render.v2_callout"
    assert importlib.util.find_spec(name) is not None, "owning native Callout primitive is missing"
    return importlib.import_module(name).callout_body_svg


def native_inputs(portrait=False, boxed=False):
    _, layout, _ = callout_documents()
    raw = deepcopy(next(obj for obj in layout["objects"] if obj["object_id"] == "annotation-note"))
    raw.update(text="A\u0301B", items=[], style={"stroke": "ink.primary" if boxed else None,
        "fill": "surface.paper" if boxed else None, "text": "text.body", "effect": None})
    raw["geometry"] = {"bounds": {"x": 90. if portrait else 80., "y": 280. if portrait else 200.,
        "width": 320., "height": 100.}, "points": [], "corner_radius": 8. if boxed else None}
    obj = TextObject.model_validate(raw)
    style, _, root = load_bundle()
    font = next(font for font in style.fonts if font.id == "atkinson-regular")
    files = {font.file: (root / font.file).read_bytes() for font in style.fonts}
    width, height = (720, 1280) if portrait else (1280, 720)
    return obj, style, root, font, files, width, height


def rgba(raw):
    with Image.open(io.BytesIO(raw)) as image:
        return image.convert("RGBA").tobytes()


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("boxed", [False, True])
@pytest.mark.parametrize("fraction,text", [(0., ""), (.5, "A\u0301"), (1., "A\u0301B")])
def test_native_callout_box_and_unboxed_write_have_literal_profile_pixels(portrait, boxed, fraction, text):
    obj, style, root, font, files, width, height = native_inputs(portrait, boxed)
    before = obj.model_dump(mode="json")
    inner = primitive()(obj, style, 2/3, files[font.file], write_fraction=fraction)
    actual = _rasterize_frozen_svg(SVGFrame(0, width, height,
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">{inner}</svg>'), style, files)
    x, y = (90, 280) if portrait else (80, 200)
    box = (f'<rect x="{x}" y="{y}" width="320" height="100" rx="8" '
           f'fill="{style.colors["paper"]}" stroke="{style.colors["ink"]}" stroke-width="2.6667" '
           f'stroke-linecap="round" stroke-linejoin="round"/>') if boxed else ""
    # Pinned sm=16, scale=2/3: fixed inset10.6667 and body size21.3333.
    text_x = f"{x + (32/3 if boxed else 0):.4f}"
    baseline = f"{y + (32 if boxed else 64/3):.4f}"
    literal = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">{box}'
        f'<text x="{text_x}" y="{baseline}" fill="{style.colors["ink"]}" font-family="{font.family}" '
        f'font-size="21.3333" font-weight="400" xml:space="preserve">{text}</text></svg>')
    expected = bytes(resvg_py.svg_to_bytes(svg_string=literal,
        font_files=[str(root / font.file)], skip_system_fonts=True))
    assert rgba(actual.png) == rgba(expected)
    assert obj.model_dump(mode="json") == before


def test_unboxed_callout_preserves_the_existing_text_primitive_exactly():
    from atme.render.v2_svg import _text

    obj, style, _, font, files, _, _ = native_inputs()
    expected = _text(obj, style.colors["ink"], font.family, font.weight, 64/3, 1.35, 52, files[font.file])
    assert primitive()(obj, style, 2/3, files[font.file]) == expected


@pytest.mark.parametrize("fault", ["empty_inner", "width_overflow", "height_overflow", "radius_without_box",
                                   "oversized_radius", "points", "effect", "unknown_stroke"])
def test_native_callout_rejects_ignored_or_out_of_inset_geometry(fault):
    render = primitive()
    obj, style, _, font, files, _, _ = native_inputs(boxed=fault != "radius_without_box")
    raw = obj.model_dump(mode="json")
    if fault == "empty_inner":
        raw["geometry"]["bounds"]["width"] = 20
    elif fault == "width_overflow":
        raw["geometry"]["bounds"]["width"] = 25
    elif fault == "height_overflow":
        raw["text"] = "First\nSecond\nThird"
        raw["geometry"]["bounds"]["height"] = 60
    elif fault == "radius_without_box":
        raw["geometry"]["corner_radius"] = 8
    elif fault == "oversized_radius":
        raw["geometry"]["corner_radius"] = 100
    elif fault == "points":
        raw["geometry"]["points"] = [{"x": 0, "y": 0}]
    elif fault == "effect":
        raw["style"]["effect"] = "invented-shadow"
    else:
        raw["style"]["stroke"] = "invented-stroke"
    with pytest.raises(ValueError):
        render(TextObject.model_validate(raw), style, 2/3, files[font.file])


def test_native_callout_bounds_inset_is_exact_and_does_not_move_outer_anchor():
    obj, style, _, font, files, _, _ = native_inputs(boxed=True)
    before = obj.geometry.model_dump(mode="json")
    inner = primitive()(obj, style, 2/3, files[font.file])
    assert 'x="90.6667"' in inner and 'y="232"' in inner
    assert 'width="320"' in inner and 'height="100"' in inner
    assert obj.geometry.model_dump(mode="json") == before


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("boxed", [False, True])
def test_callout_native_original_and_frozen_font_inputs_match_without_reopening(portrait, boxed, monkeypatch):
    from pathlib import Path

    obj, style, root, font, files, _, _ = native_inputs(portrait, boxed)
    render = primitive()
    expected = render(obj, style, 2/3, root / font.file)

    def no_original(path):
        raise AssertionError(f"frozen body reopened {path}")

    monkeypatch.setattr(Path, "read_bytes", no_original)
    assert render(obj, style, 2/3, files[font.file]) == expected


@pytest.mark.parametrize("scale,fraction", [(0, None), (True, None), (float("nan"), None),
                                            (2/3, -.1), (2/3, 1.1), (2/3, True)])
def test_callout_native_invalid_scale_or_write_clock_cannot_paint(scale, fraction):
    render = primitive()
    obj, style, _, font, files, _, _ = native_inputs(boxed=True)
    with pytest.raises(ValueError, match="scale/write"):
        render(obj, style, scale, files[font.file], write_fraction=fraction)
