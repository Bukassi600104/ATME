"""Truthful native chart geometry/ink; no registry substitution or data inference."""

import io
import math
import xml.etree.ElementTree as ET
from copy import deepcopy
from importlib import import_module, util

import pytest
import resvg_py
from PIL import Image
from test_v2_chart_contract import authored_payload, chart_documents

from atme.render.style_bundle import load_bundle
from atme.store.contracts_v2 import Bounds, ChartPayload, VisualObject


def native():
    name = "atme.render.v2_chart"
    assert util.find_spec(name) is not None, "owning data-bound chart primitive is missing"
    return import_module(name)


def plot():
    return Bounds(x=100., y=200., width=400., height=200.)


def chart(kind="bars"):
    obj = chart_documents(kind)[1]["objects"][0]
    obj["style"] = {"stroke": "ink", "fill": None, "text": None, "effect": None}
    return VisualObject.model_validate(obj)


def bundle():
    style, _, root = load_bundle()
    return style, {font.file: (root / font.file).read_bytes() for font in style.fonts}


def rgba(markup, width=720, height=720):
    wrapper = f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">{markup}</svg>'
    raw = bytes(resvg_py.svg_to_bytes(svg_string=wrapper, width=width, height=height, skip_system_fonts=True))
    with Image.open(io.BytesIO(raw)) as image:
        return image.convert("RGBA")


@pytest.mark.parametrize("kind", ["bars", "line"])
def test_literal_linear_data_geometry_preserves_coordinates_and_order(kind):
    payload = ChartPayload.model_validate(authored_payload(kind))
    before = payload.model_dump(mode="json")
    geometry = native().chart_data_geometry(payload, plot())
    expected = (("observed", "first", 200., 340., 175., 225., 400.),
                ("observed", "second", 300., 260., 275., 325., 400.)) if kind == "bars" else (
        ("observed", "first", 200., 340., None, None, None),
        ("observed", "second", 300., 260., None, None, None))
    assert geometry == expected
    assert payload.model_dump(mode="json") == before


@pytest.mark.parametrize("axis", ["x_axis", "y_axis"])
@pytest.mark.parametrize("kind", ["bars", "line"])
def test_log_coordinates_use_declared_domain_and_actual_axis_units(kind, axis):
    raw = authored_payload(kind)
    raw[axis].update(domain=[1., 100.], scale="log",
                     ticks=[{"value": 1., "label": "one"}, {"value": 100., "label": "hundred"}])
    for index, point in enumerate(raw["series"][0]["points"]):
        point["x" if axis == "x_axis" else "y"] = 10. ** (index + 1)
    if kind == "bars":
        raw["bar"].update(width=2., baseline=1.)
        if axis == "x_axis":
            raw["series"][0]["points"][1]["x"] = 90.
    rows = native().chart_data_geometry(ChartPayload.model_validate(raw), plot())
    if axis == "x_axis":
        assert rows[0][2] == 300.
        if kind == "bars":
            assert rows[0][4] == pytest.approx(100 + 200 * math.log10(9))
            assert rows[0][5] == pytest.approx(100 + 200 * math.log10(11))
    else:
        assert [row[3] for row in rows] == [300., 200.]
        if kind == "bars":
            assert rows[0][6] == 400.


@pytest.mark.parametrize("portrait", [False, True])
def test_actual_bar_ink_matches_independent_literal_data_pixels(portrait):
    width, height = (720, 1280) if portrait else (1280, 720)
    payload = ChartPayload.model_validate(authored_payload())
    colors = bundle()[0].colors
    actual = native().chart_series_svg(payload, plot(), colors, 2.)
    # Literal input values/domain -> x=[175,225]/[275,325], y=[340,400]/[260,400].
    expected = ('<rect x="175" y="340" width="50" height="60" fill="#2457D6"/>'
                '<rect x="275" y="260" width="50" height="140" fill="#2457D6" '
                'stroke="#B93838" stroke-width="2"/>')
    assert rgba(actual, width, height).tobytes() == rgba(expected, width, height).tobytes()


@pytest.mark.parametrize("portrait", [False, True])
def test_actual_line_ink_matches_independent_literal_data_pixels(portrait):
    width, height = (720, 1280) if portrait else (1280, 720)
    payload = ChartPayload.model_validate(authored_payload("line"))
    actual = native().chart_series_svg(payload, plot(), bundle()[0].colors, 2.)
    expected = ('<circle cx="200" cy="340" r="3" fill="#2457D6"/>'
                '<path d="M200 340L300 260" fill="none" stroke="#2457D6" stroke-width="2" '
                'stroke-linecap="round" stroke-linejoin="round"/>'
                '<circle cx="300" cy="260" r="3" fill="#2457D6" stroke="#B93838" stroke-width="2"/>')
    assert rgba(actual, width, height).tobytes() == rgba(expected, width, height).tobytes()


@pytest.mark.parametrize("kind", ["bars", "line"])
@pytest.mark.parametrize("fraction,ids", [(0., []), (.1, []), (.3, ["first"]),
    (.5, ["first"]), (.7, ["first", "second"]), (.9, ["first", "second"]), (1., ["first", "second"])])
def test_every_datum_uses_its_exact_authored_clock(kind, fraction, ids):
    payload = ChartPayload.model_validate(authored_payload(kind))
    result = native().chart_series_svg(payload, plot(), bundle()[0].colors, 2., draw_fraction=fraction)
    tree = ET.fromstring("<g>" + result + "</g>")
    assert [node.attrib["data-chart-point"] for node in tree if "data-chart-point" in node.attrib] == ids
    if kind == "bars" and fraction == .3:
        bar = next(tree.iter("rect"))
        assert float(bar.attrib["y"]) == 370.
        assert float(bar.attrib["height"]) == 30.
    if kind == "line" and fraction == .7:
        path = next(tree.iter("path"))
        assert path.attrib["d"] == "M200 340L250 300"
    assert native().chart_series_svg(payload, plot(), bundle()[0].colors, 2.) == (
        native().chart_series_svg(payload, plot(), bundle()[0].colors, 2., draw_fraction=1.))


@pytest.mark.parametrize("kind", ["bars", "line"])
def test_authored_overlap_pause_and_order_are_not_retimed(kind):
    raw = authored_payload(kind)
    raw["construction"][0].update(start_fraction=.6, end_fraction=.8)
    raw["construction"][1].update(start_fraction=.1, end_fraction=.3)
    payload = ChartPayload.model_validate(raw)
    result = native().chart_series_svg(payload, plot(), bundle()[0].colors, 2., draw_fraction=.4)
    assert 'data-chart-point="first"' not in result
    assert 'data-chart-point="second"' in result


@pytest.mark.parametrize("portrait", [False, True])
def test_line_segment_cannot_leak_an_entirely_unconstructed_predecessor(portrait):
    raw = authored_payload("line")
    raw["construction"][0].update(start_fraction=.6, end_fraction=.8)
    raw["construction"][1].update(start_fraction=.1, end_fraction=.3)
    payload, colors = ChartPayload.model_validate(raw), bundle()[0].colors
    before = native().chart_series_svg(payload, plot(), colors, 2., draw_fraction=.4)
    expected_before = '<circle cx="300" cy="260" r="3" fill="#2457D6" stroke="#B93838" stroke-width="2"/>'
    width, height = (720, 1280) if portrait else (1280, 720)
    assert "<path" not in before
    assert rgba(before, width, height).tobytes() == rgba(expected_before, width, height).tobytes()
    # Point windows stay authored: second is already complete, first half built.
    # Their connecting segment uses min(endpoint construction fractions).
    during = native().chart_series_svg(payload, plot(), colors, 2., draw_fraction=.7)
    expected_during = ('<circle cx="200" cy="340" r="1.5" fill="#2457D6"/>'
        '<path d="M200 340L250 300" fill="none" stroke="#2457D6" stroke-width="2" '
        'stroke-linecap="round" stroke-linejoin="round"/>'
        '<circle cx="300" cy="260" r="3" fill="#2457D6" stroke="#B93838" stroke-width="2"/>')
    assert rgba(during, width, height).tobytes() == rgba(expected_during, width, height).tobytes()
    assert native().chart_series_svg(payload, plot(), colors, 2., draw_fraction=.8) == (
        native().chart_series_svg(payload, plot(), colors, 2.))


@pytest.mark.parametrize("fault", ["dense_x_ticks", "dense_y_ticks", "nearby_points", "tick_point"])
@pytest.mark.parametrize("fraction", [None, 0.])
def test_measured_label_collisions_reject_without_dropping_or_reformatting(fault, fraction):
    obj, (style, fonts) = chart(), bundle()
    if fault == "dense_x_ticks":
        obj.chart_payload.x_axis.ticks[1].value = 1.001
    elif fault == "dense_y_ticks":
        obj.chart_payload.y_axis.ticks[1].value = .001
    elif fault == "nearby_points":
        obj.chart_payload.series[0].points[1].x = 1.01
        obj.chart_payload.series[0].points[1].y = 3.
    else:
        # A high-value point label can occupy the same physical space as the
        # authored y-axis unit header, despite fitting the outer viewport.
        obj.chart_payload.series[0].points[0].x = .25
        obj.chart_payload.series[0].points[0].y = 10.
    with pytest.raises(ValueError, match="label.*overlap"):
        native().chart_svg(obj, style, 2/3, fonts, draw_fraction=fraction)


@pytest.mark.parametrize("kind", ["bars", "line"])
def test_native_chart_paints_exact_title_labels_units_ticks_series_and_point_labels(kind):
    obj, (style, fonts) = chart(kind), bundle()
    before = obj.model_dump(mode="json")
    result = native().chart_svg(obj, style, 2/3, fonts)
    tree = ET.fromstring("<g>" + result + "</g>")
    texts = ["".join(node.itertext()) for node in tree.iter("text")]
    assert texts == ["Measured output", "Observed", "Output", "items", "0", "10",
                     "First", "Second", "Stage", "3 items", "7 items"]
    assert "Kalam" in result and "#2457D6" in result and "#B93838" in result
    assert "href=" not in result and "<image" not in result
    assert obj.model_dump(mode="json") == before


@pytest.mark.parametrize("fault", ["bare", "points", "radius", "effect", "tiny", "bad_series_color",
    "bad_highlight_color", "bad_stroke", "bad_fill", "bad_text", "long_title", "long_tick",
    "long_point", "missing_font", "font_tamper", "unknown_nested", "bool_point"])
def test_native_chart_refuses_unfaithful_inputs_instead_of_falling_back(fault):
    obj, (style, fonts) = chart(), bundle()
    if fault == "bare":
        obj.chart_payload = None
    elif fault == "points":
        obj.geometry.points = [obj.transform.position]
    elif fault == "radius":
        obj.geometry.corner_radius = 1.
    elif fault == "effect":
        obj.style.effect = "glow"
    elif fault == "tiny":
        obj.geometry.bounds.width = 1.
    elif fault == "bad_series_color":
        obj.chart_payload.series[0].color = "url(https://bad)"
    elif fault == "bad_highlight_color":
        obj.chart_payload.highlights[0].color = "invented"
    elif fault.startswith("bad_"):
        setattr(obj.style, fault[4:], "invented")
    elif fault == "long_title":
        obj.chart_payload.title = "W" * 200
    elif fault == "long_tick":
        obj.chart_payload.y_axis.ticks[0].label = "W" * 200
    elif fault == "long_point":
        obj.chart_payload.series[0].points[0].label = "W" * 200
    elif fault == "missing_font":
        fonts.pop(style.fonts[0].file)
        fonts.pop(next(font.file for font in style.fonts if font.id == style.typography.title.font_id), None)
    elif fault == "font_tamper":
        fonts[next(font.file for font in style.fonts if font.id == style.typography.label.font_id)] += b"tampered"
    elif fault == "unknown_nested":
        obj.chart_payload.series[0].__dict__["ignored"] = True
    else:
        obj.chart_payload.series[0].points[0].x = True
    with pytest.raises(ValueError):
        native().chart_svg(obj, style, 2/3, fonts)


@pytest.mark.parametrize("fraction", [True, "0.5", -.1, 1.1, float("nan"), float("inf")])
def test_fraction_requires_finite_non_boolean_bounded_number(fraction):
    with pytest.raises(ValueError):
        native().chart_series_svg(ChartPayload.model_validate(authored_payload()), plot(),
                                  bundle()[0].colors, 2., draw_fraction=fraction)


def test_zero_value_bar_is_exactly_a_baseline_marker_not_omitted_or_invented_height():
    raw = deepcopy(authored_payload())
    raw["series"][0]["points"][0]["y"] = 0.
    result = native().chart_series_svg(ChartPayload.model_validate(raw), plot(), bundle()[0].colors, 2.)
    tree = ET.fromstring("<g>" + result + "</g>")
    first = next(iter(tree))
    assert first.attrib["data-chart-point"] == "first"
    assert next(first.iter("path")).attrib["d"] == "M175 400L225 400"


def test_negative_bars_use_explicit_baseline_without_absolute_value_reinterpretation():
    raw = authored_payload()
    raw["bar"]["baseline"] = 5.
    actual = native().chart_series_svg(ChartPayload.model_validate(raw), plot(), bundle()[0].colors, 2.)
    expected = ('<rect x="175" y="300" width="50" height="40" fill="#2457D6"/>'
                '<rect x="275" y="260" width="50" height="40" fill="#2457D6" '
                'stroke="#B93838" stroke-width="2"/>')
    assert rgba(actual).tobytes() == rgba(expected).tobytes()


@pytest.mark.parametrize("kind", ["bars", "line"])
def test_multiple_series_keep_authored_order_data_and_highlight_ownership(kind):
    raw = authored_payload(kind)
    second = deepcopy(raw["series"][0])
    second.update(series_id="other", label="Other", color="success")
    for point in second["points"]:
        point["y"] += 1.
    raw["series"].insert(0, second)
    raw["construction"] += [{**row, "series_id": "other"} for row in raw["construction"]]
    payload = ChartPayload.model_validate(raw)
    actual = native().chart_series_svg(payload, plot(), bundle()[0].colors, 2.)
    tree = ET.fromstring("<g>" + actual + "</g>")
    assert [(row.attrib["data-chart-series"], row.attrib["data-chart-point"]) for row in tree] == [
        ("other", "first"), ("other", "second"), ("observed", "first"), ("observed", "second")]
    assert '#B93838' not in ET.tostring(list(tree)[1], encoding="unicode")
    assert '#237252' in ET.tostring(next(iter(tree)), encoding="unicode")


@pytest.mark.parametrize("axis,domain,scale,values,expected", [
    ("y_axis", [-1e308, 1e308], "linear", [0., 5e307], [300., 250.]),
    ("y_axis", [1e-300, 1e300], "log", [1., 1e150], [300., 250.]),
    ("x_axis", [1., 1.0000000000000004], "log", [1., 1.0000000000000004], [100., 500.]),
])
def test_finite_extreme_or_close_domains_are_not_overflowed_or_collapsed(axis, domain, scale, values, expected):
    raw = authored_payload("line")
    raw[axis].update(domain=domain, scale=scale,
        ticks=[{"value": domain[0], "label": "lower"}, {"value": domain[1], "label": "upper"}])
    for point, value in zip(raw["series"][0]["points"], values, strict=True):
        point["x" if axis == "x_axis" else "y"] = value
    rows = native().chart_data_geometry(ChartPayload.model_validate(raw), plot())
    assert [row[2 if axis == "x_axis" else 3] for row in rows] == pytest.approx(expected)


@pytest.mark.parametrize("fault", ["bool_bounds", "collapsed_world_span", "unsafe_palette"])
def test_direct_native_geometry_and_palette_cannot_ignore_invalid_values(fault):
    bounds, colors = plot(), deepcopy(bundle()[0].colors)
    if fault == "bool_bounds":
        bounds.width = True
    elif fault == "collapsed_world_span":
        bounds.x = 1e20
    else:
        colors["accent"] = 'url(https://bad)'
    with pytest.raises(ValueError):
        native().chart_series_svg(ChartPayload.model_validate(authored_payload()), bounds, colors, 2.)


def test_native_exact_unicode_xml_labels_and_pinned_font_pixels(tmp_path):
    obj, (style, fonts) = chart(), bundle()
    obj.chart_payload.title = "Café & <measured>"
    obj.chart_payload.x_axis.unit = "µs"
    markup = native().chart_svg(obj, style, 2/3, fonts)
    tree = ET.fromstring("<g>" + markup + "</g>")
    assert "Café & <measured>" in list(tree.itertext())
    assert "µs" in list(tree.itertext())
    font_paths = []
    for name, raw in fonts.items():
        path = tmp_path / name.rsplit("/", 1)[-1]
        path.write_bytes(raw)
        font_paths.append(str(path))
    wrapper = f'<svg xmlns="http://www.w3.org/2000/svg" width="720" height="720">{markup}</svg>'
    image = bytes(resvg_py.svg_to_bytes(svg_string=wrapper, width=720, height=720,
                                       font_files=font_paths, skip_system_fonts=True))
    with Image.open(io.BytesIO(image)) as actual:
        assert actual.convert("RGBA").getchannel("A").getbbox() is not None
    (tmp_path / "native-chart.png").write_bytes(image)
