"""Owning chart data and lifecycle use the existing chronological consumers."""

import math
import re
import xml.etree.ElementTree as ET
from copy import deepcopy
from io import BytesIO

import pytest
from PIL import Image
from test_v2_camera_action import append_camera
from test_v2_chart_compositor import nested_documents, runtime_documents
from test_v2_group_annotation import consumer_clock, private_svg
from test_v2_group_replacement import grouped_replacement_documents
from v2_fixtures import digest

from atme.render.v2_state import evaluate_frame
from atme.render.v2_svg import (
    _rasterize_svg_frame,
    compose_png_frame,
    compose_svg_frame,
)


def chart_node(svg):
    return ET.fromstring(svg).find(".//{*}g[@data-object-id='object-system']")


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("kind", ["bars", "line"])
@pytest.mark.parametrize("axis", ["x_axis", "y_axis"])
def test_actual_compositor_log_values_follow_explicit_domains(kind, axis, portrait):
    layout, timeline = runtime_documents(kind, portrait=portrait)
    payload = layout["objects"][0]["chart_payload"]
    payload[axis].update(domain=[0.1, 100.], scale="log",
        ticks=[{"value": 1., "label": "1"}, {"value": 10., "label": "10"}])
    if kind == "bars" and axis == "y_axis":
        payload["bar"]["baseline"] = 1.
    timeline["layout_sha256"] = digest(layout)
    original = deepcopy((layout, timeline))
    node = chart_node(compose_svg_frame(layout, timeline, 1000).svg)
    axes = next(item.attrib["d"] for item in node.findall("{*}path")
                if "V" in item.attrib["d"] and "H" in item.attrib["d"])
    left, top, bottom, right = map(float, re.findall(r"-?\d+(?:\.\d+)?", axes))

    def ratio(name, value):
        lo, hi = payload[name]["domain"]
        return ((math.log(value)-math.log(lo))/(math.log(hi)-math.log(lo))
                if name == axis else (value-lo)/(hi-lo))

    for point in payload["series"][0]["points"]:
        data = node.find(f"{{*}}g[@data-chart-point='{point['point_id']}']")
        expected_y = bottom-(bottom-top)*ratio("y_axis", point["y"])
        if kind == "line":
            circle = data.find("{*}circle")
            assert float(circle.attrib["cx"]) == pytest.approx(left+(right-left)*ratio("x_axis", point["x"]), abs=.0002)
            assert float(circle.attrib["cy"]) == pytest.approx(expected_y, abs=.0002)
        else:
            bar = data.find("{*}rect")
            half = payload["bar"]["width"]/2
            expected_left = left+(right-left)*ratio("x_axis", point["x"]-half)
            expected_right = left+(right-left)*ratio("x_axis", point["x"]+half)
            baseline = bottom-(bottom-top)*ratio("y_axis", payload["bar"]["baseline"])
            assert float(bar.attrib["x"]) == pytest.approx(expected_left, abs=.0002)
            assert float(bar.attrib["width"]) == pytest.approx(expected_right-expected_left, abs=.0002)
            assert float(bar.attrib["y"]) == pytest.approx(min(expected_y, baseline), abs=.0002)
            assert float(bar.attrib["height"]) == pytest.approx(abs(expected_y-baseline), abs=.0002)
    expected = compose_png_frame(layout, timeline, 1000).png
    compose_png_frame(layout, timeline, 350)
    assert compose_png_frame(layout, timeline, 1000).png == expected
    assert (layout, timeline) == original


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("kind", ["bars", "line"])
def test_actual_multiseries_out_of_order_construction_preserves_pause_and_data(kind, portrait):
    layout, timeline = runtime_documents(kind, portrait=portrait)
    payload = layout["objects"][0]["chart_payload"]
    payload["series"].append({"series_id": "projection", "label": "Projected", "color": "success",
        "points": [{"point_id": "one", "x": 3., "y": 1., "label": "A"},
                   {"point_id": "two", "x": 3.7, "y": 9., "label": "B"}]})
    payload["construction"] = [
        {"series_id": "projection", "point_id": "two", "start_fraction": .7, "end_fraction": 1.},
        {"series_id": "observed", "point_id": "second", "start_fraction": .1, "end_fraction": .3},
        {"series_id": "projection", "point_id": "one", "start_fraction": .2, "end_fraction": .5},
        {"series_id": "observed", "point_id": "first", "start_fraction": .6, "end_fraction": .9}]
    timeline["layout_sha256"] = digest(layout)
    original = deepcopy((layout, timeline))
    mid = chart_node(compose_svg_frame(layout, timeline, 400).svg)
    data = [item for item in mid.findall("{*}g") if "data-chart-point" in item.attrib]
    assert [(item.attrib["data-chart-series"], item.attrib["data-chart-point"]) for item in data] == [
        ("observed", "second"), ("projection", "one")]
    if kind == "line":
        assert all(item.find("{*}path") is None for item in data)  # no hidden predecessor leak
    pixels = {at: compose_png_frame(layout, timeline, at).png for at in (400, 500, 599, 800, 1000)}
    assert pixels[500] == pixels[599]  # preserve the authored pause; never retime it
    assert pixels[400] != pixels[500] != pixels[800] != pixels[1000]
    for at in (1000, 599, 400, 800, 500):
        assert compose_png_frame(layout, timeline, at).png == pixels[at]
    assert (layout, timeline) == original


def append_transform(timeline, verb, start, end, **parameters):
    row = deepcopy(timeline["actions"][0])
    action = row["action"]
    action.pop("annotation", None)
    action.update(action_id=f"chart-{verb}", verb=verb, trigger={"kind": "absolute", "at_ms": start},
        expected_state="visible", post_state="visible", **parameters)
    row.update(start_ms=start, end_ms=end)
    row["resolved_trigger"].update(source=action["trigger"], alignment_anchor_ms=start,
        resolved_at_ms=start, matched_text=None, matched_occurrence=None)
    timeline["actions"].append(row)
    timeline["coverage"][0]["action_ids"].append(action["action_id"])


@pytest.mark.parametrize("portrait", [False, True])
def test_chart_draw_then_move_fade_camera_preserves_clock_versions_and_seek(portrait):
    layout, timeline = runtime_documents(portrait=portrait)
    destination = deepcopy(layout["objects"][0]["transform"])
    destination["position"] = {"x": 60., "y": 20.}
    append_transform(timeline, "move", 1200, 1600, destination=destination, opacity=None)
    append_transform(timeline, "fade", 1800, 2200, destination=None, opacity=.4)
    append_camera(timeline, "chart-camera", "camera_cut", 2400, 2500, framing="detail")
    original = deepcopy((layout, timeline))
    _, replay, _ = consumer_clock(layout, timeline)
    assert [dict(replay.at(at).state_versions)["object-system"] for at in
            (999, 1000, 1599, 1600, 2199, 2200, 2500)] == [1, 2, 2, 3, 3, 4, 4]
    assert replay.at(1400).object("object-system").transform.position.x == pytest.approx(30.)
    assert replay.at(2000).object("object-system").opacity == pytest.approx(.7)
    assert replay.at(2500).object("object-system").state == "visible"
    assert evaluate_frame(layout, timeline, 2500).camera.width < layout["canvas"]["width"]
    frames = {at: compose_png_frame(layout, timeline, at).png for at in (1000, 1400, 1600, 2000, 2500)}
    assert len(set(frames.values())) == len(frames)
    for at in (2500, 1400, 1000, 2000, 1600):
        assert compose_png_frame(layout, timeline, at).png == frames[at]
    assert (layout, timeline) == original


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("regroup", [False, True])
def test_chart_paints_actual_post_group_history_without_rewriting_hierarchy(portrait, regroup):
    layout, timeline = grouped_replacement_documents(portrait=portrait, regroup=regroup)
    source = next(item for item in layout["objects"] if item["object_id"] == "object-system")
    chart = runtime_documents(portrait=portrait)[0]["objects"][0]
    source.pop("path_data", None)
    for key in ("object_type", "chart_payload", "variant", "geometry", "style"):
        source[key] = deepcopy(chart[key])
    row = next(item for item in timeline["actions"] if item["action"]["verb"] == "replace")
    base = deepcopy(timeline["actions"][0]["action"])
    base.pop("annotation", None)
    for key in ("action_id", "source_instruction_id", "board_id", "coverage_id", "fallback", "trigger"):
        base[key] = deepcopy(row["action"][key])
    base.update(verb="fade", target_ids=["object-system"], expected_state="visible", post_state="visible",
        destination=None, opacity=.4)
    row["action"] = base
    timeline["layout_sha256"] = digest(layout)
    original = deepcopy((layout, timeline))
    context, replay, camera = consumer_clock(layout, timeline)
    captured = replay.before_action(base["action_id"])
    final = replay.at(row["end_ms"])
    assert final.hierarchy == captured.hierarchy
    expected_ancestors = (("replacement-pair", "replacement-shell", "replacement-outer") if regroup
                          else ("replacement-pair", "replacement-outer"))
    assert final.hierarchy.ancestors("object-system") == expected_ancestors
    assert final.object("object-system").transform == captured.object("object-system").transform
    assert dict(final.state_versions) == {key: version+(key == "object-system")
                                          for key, version in captured.state_versions}
    svg = private_svg(context, replay, camera, row["end_ms"])
    assert "Measured output" in svg.svg and 'data-chart-point="second"' in svg.svg
    expected = _rasterize_svg_frame(context.layout, svg).png
    private_svg(context, replay, camera, row["start_ms"])
    assert _rasterize_svg_frame(context.layout, private_svg(context, replay, camera, row["end_ms"])).png == expected
    assert (layout, timeline) == original


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("aperture", ["clip", "mask"])
def test_moving_chart_ancestor_preserves_the_fixed_shared_aperture(portrait, aperture):
    layout, timeline = nested_documents(portrait=portrait, aperture=aperture)
    root = next(item for item in layout["objects"] if item["object_id"] == "chart-root")
    destination = deepcopy(root["transform"])
    destination["position"]["x"] += 60.
    append_transform(timeline, "move", 1200, 1600, destination=destination, opacity=None)
    timeline["actions"][-1]["action"]["target_ids"] = [root["object_id"]]
    original = deepcopy((layout, timeline))
    _, replay, _ = consumer_clock(layout, timeline)
    assert replay.at(1000).hierarchy == replay.at(1600).hierarchy
    assert replay.at(1000).object("object-system").transform == replay.at(1600).object("object-system").transform
    assert dict(replay.at(1600).state_versions)["chart-root"] == 2
    assert dict(replay.at(1600).state_versions)["object-system"] == 2
    frames = {at: compose_png_frame(layout, timeline, at).png for at in (1000, 1400, 1600)}
    assert len(set(frames.values())) == len(frames)
    for at in (1600, 1000, 1400):
        assert compose_png_frame(layout, timeline, at).png == frames[at]
        with Image.open(BytesIO(frames[at])) as image:
            right = image.convert("RGB").crop((322, 0, image.width, image.height))
            assert right.tobytes() == bytes((250, 248, 241)) * (right.width * right.height)
    assert (layout, timeline) == original


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("verb,match", [("write", "incompatible object type"),
                                       ("progressive_reveal", "ordered-child list")])
def test_incompatible_chart_construction_refuses_before_any_frame(portrait, verb, match):
    layout, timeline = runtime_documents(portrait=portrait, verb=verb)
    with pytest.raises(ValueError, match=match):
        compose_svg_frame(layout, timeline, 0)
