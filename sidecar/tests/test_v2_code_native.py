"""Native code pixels from authored text and the same verified mono bytes."""

import base64
import io
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
import resvg_py
from atme.render import v2_code
from atme.render.code_font_bundle import load_code_font_bundle
from atme.render.style_bundle import _font_css as font_css
from atme.render.style_bundle import load_bundle
from atme.render.v2_svg import SVGFrame, _rasterize_frozen_svg
from atme.store.contracts_v2 import TextObject
from PIL import Image
from test_v2_code_glyphs import authored_code


def native_inputs(text, portrait=False, *, spans=None):
    obj = authored_code(text)
    raw = obj.model_dump(mode="json")
    raw["style"] = {"stroke": None, "fill": None, "text": "text.code", "effect": None}
    raw["geometry"] = {"bounds": {"x": 90 if portrait else 80, "y": 280 if portrait else 200,
                                  "width": 500, "height": 160}, "points": [], "corner_radius": None}
    if spans is not None:
        raw["code_payload"]["mode"] = "tokens"
        raw["code_payload"]["lines"][0]["spans"] = spans
    obj = TextObject.model_validate(raw)
    style, _, root = load_bundle()
    bundle = load_code_font_bundle()
    files = {font.file: (root / font.file).read_bytes() for font in style.fonts}
    files.update({name: payload for name, _, payload in bundle.files})
    width, height = (720, 1280) if portrait else (1280, 720)
    return obj, style, bundle, files, root, width, height


def rendered(inner, style, files, width, height):
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">{inner}</svg>'
    return _rasterize_frozen_svg(SVGFrame(0, width, height, svg), style, files).png


def literal_pixels(inner, root, width, height):
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">{inner}</svg>'
    return bytes(resvg_py.svg_to_bytes(svg_string=svg, width=width, height=height,
        font_files=[str(root / "code-font-v1/fonts/JetBrainsMono-Regular.ttf")], skip_system_fonts=True))


def rgba(raw):
    with Image.open(io.BytesIO(raw)) as image:
        return image.convert("RGBA").tobytes()


def renderer():
    assert hasattr(v2_code, "code_svg"), "owning native code renderer is missing"
    return v2_code.code_svg


@pytest.mark.parametrize("portrait", [False, True])
def test_native_plain_code_tabs_blank_lines_and_trailing_spaces_have_literal_pixels(portrait):
    obj, style, bundle, files, root, width, height = native_inputs("\tx=1  \n\nΩé", portrait)
    before = obj.model_dump(mode="json")
    actual = renderer()(obj, style, 2/3, bundle)
    x, first_y, last_y = ("134.8", "298.6667", "349.0667") if portrait else ("124.8", "218.6667", "269.0667")
    left = "90" if portrait else "80"
    expected = (f'<g font-family="JetBrains Mono" font-size="18.6667" font-weight="400" '
        f'fill="{style.colors["ink"]}" xml:space="preserve">'
        f'<text x="{x}" y="{first_y}">x=1  </text>'
        f'<text x="{left}" y="{last_y}">Ωé</text></g>')
    pixels = rendered(actual, style, files, width, height)
    assert rgba(pixels) == rgba(literal_pixels(expected, root, width, height))
    assert obj.model_dump(mode="json") == before
    assert "\t" not in actual
    assert "x=1  " in actual
    with Image.open(io.BytesIO(pixels)) as image:
        assert image.getchannel("A").getbbox() is not None


@pytest.mark.parametrize("portrait", [False, True])
def test_native_authored_operator_tokens_have_exact_colors_and_positions(portrait):
    spans = [{"span_id": "name", "role": "identifier", "text": "x"},
             {"span_id": "op", "role": "operator", "text": "="},
             {"span_id": "value", "role": "literal", "text": "1"}]
    obj, style, bundle, files, root, width, height = native_inputs("x=1", portrait, spans=spans)
    actual = renderer()(obj, style, 2/3, bundle)
    positions, y = (("90", "101.2", "112.4"), "298.6667") if portrait else (("80", "91.2", "102.4"), "218.6667")
    expected = (f'<g font-family="JetBrains Mono" font-size="18.6667" font-weight="400" xml:space="preserve">'
        f'<text x="{positions[0]}" y="{y}" fill="{style.colors["ink"]}">x</text>'
        f'<text x="{positions[1]}" y="{y}" fill="{style.colors["accent"]}">=</text>'
        f'<text x="{positions[2]}" y="{y}" fill="{style.colors["success"]}">1</text></g>')
    assert rgba(rendered(actual, style, files, width, height)) == rgba(literal_pixels(expected, root, width, height))
    parsed = ET.fromstring(f"<g>{actual}</g>")
    assert "".join(parsed.itertext()) == obj.text


@pytest.mark.parametrize("portrait", [False, True])
def test_native_combining_run_and_grapheme_write_never_normalize_or_split_accent(portrait):
    obj, style, bundle, files, root, width, height = native_inputs("e\u0301x", portrait)
    x, y = ("90", "298.6667") if portrait else ("80", "218.6667")
    for fraction, literal in [(0.0, ""), (0.5, "e\u0301"), (1.0, "e\u0301x")]:
        actual = renderer()(obj, style, 2/3, bundle, write_fraction=fraction)
        expected = (f'<text x="{x}" y="{y}" fill="{style.colors["ink"]}" font-family="JetBrains Mono" '
            f'font-size="18.6667" font-weight="400" xml:space="preserve">{literal}</text>')
        assert rgba(rendered(actual, style, files, width, height)) == rgba(literal_pixels(expected, root, width, height))
        assert literal in actual
    assert obj.text == "e\u0301x"


@pytest.mark.parametrize("portrait", [False, True])
def test_whole_grapheme_write_crosses_authored_token_boundaries_without_partial_accent(portrait):
    spans = [{"span_id": "base", "role": "identifier", "text": "e"},
             {"span_id": "mark-next", "role": "identifier", "text": "\u0301x"}]
    obj, style, bundle, files, root, width, height = native_inputs("e\u0301x", portrait, spans=spans)
    actual = renderer()(obj, style, 2/3, bundle, write_fraction=.5)
    x, y = ("90", "298.6667") if portrait else ("80", "218.6667")
    expected = (f'<text x="{x}" y="{y}" fill="{style.colors["ink"]}" font-family="JetBrains Mono" '
        f'font-size="18.6667" font-weight="400" xml:space="preserve">e\u0301</text>')
    assert rgba(rendered(actual, style, files, width, height)) == rgba(literal_pixels(expected, root, width, height))
    parsed = ET.fromstring(f"<g>{actual}</g>")
    assert "".join(parsed.itertext()) == "e\u0301"


def test_frozen_native_code_uses_verified_bytes_without_reopening_sources(monkeypatch):
    obj, style, bundle, files, *_dimensions = native_inputs("Ωe\u0301")

    def no_source(path):
        raise AssertionError(f"native frozen code reopened {path}")

    monkeypatch.setattr(Path, "read_bytes", no_source)
    pixels = rendered(renderer()(obj, style, 2/3, bundle), style, files, 1280, 720)
    with Image.open(io.BytesIO(pixels)) as image:
        assert image.getchannel("A").getbbox() is not None


@pytest.mark.parametrize("fault", ["missing", "changed"])
def test_native_rasterizer_rejects_missing_or_changed_code_font_without_fallback(fault):
    obj, style, bundle, files, *_dimensions = native_inputs("x")
    inner = renderer()(obj, style, 2/3, bundle)
    path = "code-font-v1/fonts/JetBrainsMono-Regular.ttf"
    if fault == "missing":
        files.pop(path)
    else:
        files[path] = files[path] + b"changed"
    with pytest.raises(ValueError, match="code.font"):
        rendered(inner, style, files, 1280, 720)


def test_code_css_embeds_exact_verified_font_bytes_only_when_requested():
    _obj, style, bundle, files, root, *_dimensions = native_inputs("x")
    assert hasattr(v2_code, "code_font_css"), "owning code-font CSS consumer is missing"
    css = v2_code.code_font_css(bundle)
    payload = base64.b64decode(re.search(r"data:font/ttf;base64,([A-Za-z0-9+/=]+)", css)[1])
    expected = next(raw for name, _, raw in bundle.files if name.endswith(".ttf"))
    assert payload == expected
    assert "JetBrains Mono" in css
    plain_files = {name: raw for name, raw in files.items() if not name.startswith("code-font-v1/")}
    assert "JetBrains Mono" not in font_css(style, root, frozen_files=plain_files)
    assert css in font_css(style, root, frozen_files=files)


@pytest.mark.parametrize("fault", ["width", "height", "trailing_spaces", "ignored_fill", "typography", "scale", "fraction"])
def test_native_code_rejects_bounds_or_ignored_contract_instead_of_reflow(fault):
    obj, style, bundle, *_ = native_inputs("x  ")
    if fault == "width":
        obj.geometry.bounds.width = 1
    elif fault == "height":
        obj.geometry.bounds.height = 1
    elif fault == "trailing_spaces":
        obj.geometry.bounds.width = 12  # visible x fits; authored trailing spaces do not
    elif fault == "ignored_fill":
        obj.style.fill = "surface.raised"
    elif fault == "typography":
        obj.style.text = "text.body"
    with pytest.raises(ValueError, match="code"):
        renderer()(obj, style, float("nan") if fault == "scale" else 2/3, bundle,
                   write_fraction=1.1 if fault == "fraction" else None)
