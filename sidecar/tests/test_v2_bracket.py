"""P3-26: authored bracket points must survive native construction exactly."""

import io
from copy import deepcopy

import pytest
import resvg_py
from atme.render.v2_svg import UnsupportedVisualObject, _shape
from atme.store.contracts_v2 import MarkObject
from PIL import Image
from test_v2_split_capture import geometry_boundary

BRACKET_POINTS = {
    "left": [(90, 10), (10, 10), (10, 130), (90, 130)],
    "right": [(10, 10), (90, 10), (90, 130), (10, 130)],
    "top": [(10, 130), (10, 10), (90, 10), (90, 130)],
    "bottom": [(10, 10), (10, 130), (90, 130), (90, 10)],
}


def bracket_object(direction="left", *, reverse=False):
    layout, _, _ = geometry_boundary()
    raw = next(obj for obj in layout.objects if obj.object_id == "source").model_dump(mode="json")
    points = BRACKET_POINTS[direction]
    if reverse:
        points = list(reversed(points))
    raw.update(object_type="bracket", path_data=None)
    raw["geometry"] = {"bounds": {"x": 10, "y": 10, "width": 80, "height": 120},
                       "points": [{"x": x, "y": y} for x, y in points], "corner_radius": None}
    raw["style"]["fill"] = None
    return MarkObject.model_validate(raw)


@pytest.mark.parametrize("direction", BRACKET_POINTS)
@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("fraction", [.5, 1])
def test_bracket_native_pixels_preserve_orientation_and_authored_draw_order(direction, reverse, fraction):
    obj = bracket_object(direction, reverse=reverse)
    before = obj.model_dump(mode="json")
    actual = _shape(obj, "#172033", "none", 4, draw_fraction=fraction)
    points = BRACKET_POINTS[direction]
    if reverse:
        points = list(reversed(points))
    coordinates = " ".join(f"{x},{y}" for x, y in points)
    length = 280 if direction in {"left", "right"} else 320
    dash = f' stroke-dasharray="{length} {length}" stroke-dashoffset="{length//2}"' if fraction == .5 else ""
    expected = (f'<polyline points="{coordinates}" fill="none" stroke="#172033" stroke-width="4" '
                f'stroke-linecap="round" stroke-linejoin="round"{dash}/>')
    def pixels(markup):
        svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="160" height="180">{markup}</svg>'
        with Image.open(io.BytesIO(resvg_py.svg_to_bytes(svg_string=svg, skip_system_fonts=True))) as image:
            return image.convert("RGBA")
    actual_image = pixels(actual)
    assert actual_image.tobytes() == pixels(expected).tobytes()
    assert actual_image.getchannel("A").getbbox() is not None
    assert obj.model_dump(mode="json") == before


@pytest.mark.parametrize("fault", ["missing", "three", "five", "diagonal", "zigzag", "collapsed",
    "quantized_zero", "fill", "path", "corner", "outside"])
def test_bracket_rejects_unfaithful_or_ignored_authored_payload(fault):
    obj = bracket_object()
    raw = deepcopy(obj.model_dump(mode="json"))
    fill = "none"
    if fault == "missing":
        raw["geometry"]["points"] = []
    elif fault == "three":
        raw["geometry"]["points"].pop()
    elif fault == "five":
        raw["geometry"]["points"].append({"x": 90, "y": 10})
    elif fault == "diagonal":
        raw["geometry"]["points"][1]["y"] += 1
    elif fault == "zigzag":
        raw["geometry"]["points"] = [{"x": x, "y": y} for x, y in [(90, 10), (50, 10), (50, 130), (10, 130)]]
    elif fault == "collapsed":
        raw["geometry"]["points"][0] = dict(raw["geometry"]["points"][1])
    elif fault == "quantized_zero":
        raw["geometry"]["points"][0]["x"] = 10.000001
    elif fault == "fill":
        fill = "#ffffff"
    elif fault == "corner":
        raw["geometry"]["corner_radius"] = 2
    elif fault == "outside":
        raw["geometry"]["points"][0]["x"] = 91
    else:
        raw["path_data"] = "M10 10 L90 10"
    with pytest.raises(UnsupportedVisualObject, match="points exceed authored bounds" if fault == "outside" else "bracket"):
        _shape(MarkObject.model_validate(raw), "#172033", fill, 4, draw_fraction=.5)


@pytest.mark.parametrize("points,length", [
    ([(80, 20), (20, 20), (20, 120), (65, 120)], 205),
    ([(20, 20), (80, 20), (80, 120), (35, 120)], 205),
    ([(20, 120), (20, 20), (80, 20), (80, 95)], 235),
    ([(20, 20), (20, 120), (80, 120), (80, 45)], 235),
])
@pytest.mark.parametrize("reverse", [False, True])
def test_bracket_preserves_asymmetric_arms_and_padded_bounds(points, length, reverse):
    raw = bracket_object().model_dump(mode="json")
    if reverse:
        points = list(reversed(points))
    raw["geometry"]["bounds"].update(width=100, height=140)
    raw["geometry"]["points"] = [{"x": x, "y": y} for x, y in points]
    actual = _shape(MarkObject.model_validate(raw), "#172033", "none", 4, draw_fraction=.5)
    coordinates = " ".join(f"{x},{y}" for x, y in points)
    expected = (f'<polyline points="{coordinates}" fill="none" stroke="#172033" stroke-width="4" '
                f'stroke-linecap="round" stroke-linejoin="round" stroke-dasharray="{length} {length}" '
                f'stroke-dashoffset="{length/2}"/>')
    def pixels(markup):
        svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="160" height="180">{markup}</svg>'
        with Image.open(io.BytesIO(resvg_py.svg_to_bytes(svg_string=svg, skip_system_fonts=True))) as image:
            return image.convert("RGBA").tobytes()
    assert pixels(actual) == pixels(expected)


@pytest.mark.parametrize("direction", BRACKET_POINTS)
@pytest.mark.parametrize("portrait", [False, True])
def test_bracket_public_playback_pixels_and_random_seek_in_both_profiles(direction, portrait):
    from atme.render.v2_svg import compose_png_frame
    from test_v2_svg import primitive_documents
    from v2_fixtures import digest
    from v2_split_fixtures import split_documents

    layout, timeline = primitive_documents()
    obj = layout["objects"][0]
    authored = bracket_object(direction).model_dump(mode="json")
    obj.update(object_type="bracket", geometry=authored["geometry"], path_data=None)
    obj["style"].update(stroke="ink.primary", fill=None)
    timeline["actions"][0]["action"]["verb"] = "draw"
    timeline["actions"][0]["action"]["easing"] = "linear"
    _, _, profile_timeline = split_documents("SHORT_FORM_9_16" if portrait else "LONG_FORM_16_9")
    layout["output_profile"] = timeline["output_profile"] = profile_timeline["output_profile"]
    layout["canvas"] = {"x": 0, "y": 0, "width": 720 if portrait else 1280,
                         "height": 1280 if portrait else 720}
    timeline["layout_sha256"] = digest(layout)
    frames = {}
    for at_ms in (450, 0, 900, 450):
        png = compose_png_frame(layout, timeline, at_ms).png
        if at_ms in frames:
            assert png == frames[at_ms]
        frames[at_ms] = png
    for at_ms in (0, 450, 900):
        with Image.open(io.BytesIO(frames[at_ms])) as image:
            actual = image.convert("RGB").crop((0, 0, 160, 180))
        coordinates = " ".join(f"{x},{y}" for x, y in BRACKET_POINTS[direction])
        length = 280 if direction in {"left", "right"} else 320
        dash = f' stroke-dasharray="{length} {length}" stroke-dashoffset="{length//2}"' if at_ms == 450 else ""
        mark = (f'<polyline points="{coordinates}" fill="none" stroke="#172033" stroke-width="2.6667" '
                f'stroke-linecap="round" stroke-linejoin="round"{dash}/>') if at_ms else ""
        svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="160" height="180"><rect width="160" height="180" fill="#FAF8F1"/>{mark}</svg>'
        with Image.open(io.BytesIO(resvg_py.svg_to_bytes(svg_string=svg, skip_system_fonts=True))) as image:
            expected = image.convert("RGB")
        assert actual.tobytes() == expected.tobytes()
