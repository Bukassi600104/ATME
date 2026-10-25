"""Data-bound charts use the normal and frozen production compositor tree."""

import io
import socket
import xml.etree.ElementTree as ET
from copy import deepcopy
from pathlib import Path

import pytest
from PIL import Image
from test_v2_chart_contract import chart_documents
from v2_fixtures import digest, resolved_timeline_v2

from atme.render import v2_state
from atme.render.style_bundle import registry_endpoint_inputs_for_objects
from atme.render.v2_split_paint import _split_primitive_paint, verify_split_paint_inputs
from atme.render.v2_svg import (
    _compose_validated_svg_frame,
    _rasterize_svg_frame,
    compose_png_frame,
    compose_svg_frame,
)
from atme.store.contracts_v2 import ExecutableLayoutV2, ResolvedVisualTimelineV2


def runtime_documents(kind="bars", *, portrait=False, verb="draw"):
    plan, layout = chart_documents(kind)
    for key in ("actions", "coverage", "fallbacks"):
        plan[key] = plan[key][:1]
    plan["beats"][0]["action_ids"] = [plan["actions"][0]["action_id"]]
    plan["actions"][0].update(verb=verb, easing="linear")
    layout["objects"][0]["style"] = {"stroke": "ink", "fill": None, "text": None, "effect": None}
    if portrait:
        profile = {"profile_id": "SHORT_FORM_9_16", "width": 720, "height": 1280, "fps": 30}
        plan["output_profile"] = deepcopy(profile)
        layout.update(output_profile=deepcopy(profile), canvas={"x": 0, "y": 0, "width": 720, "height": 1280})
    layout["plan_sha256"] = digest(plan)
    timeline = resolved_timeline_v2(plan, layout)
    timeline.update(output_profile=deepcopy(layout["output_profile"]), resolved_assets=[])
    timeline["actions"][0]["end_ms"] = 1000
    ExecutableLayoutV2.model_validate(layout)
    ResolvedVisualTimelineV2.model_validate(timeline)
    return layout, timeline


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("kind", ["bars", "line"])
def test_actual_draw_uses_data_construction_on_one_preview_path(kind, portrait, tmp_path):
    layout, timeline = runtime_documents(kind, portrait=portrait)
    before = deepcopy((layout, timeline))
    pixels = {at: compose_png_frame(layout, timeline, at).png for at in (0, 100, 300, 500, 700, 900, 1000)}
    assert pixels[0] != pixels[100] != pixels[300] != pixels[500] != pixels[700]
    assert pixels[900] == pixels[1000]
    mid = compose_svg_frame(layout, timeline, 300).svg
    tree = ET.fromstring(mid)
    chart = next(node for node in tree.iter() if node.attrib.get("data-object-id") == "object-system")
    assert "clip-path" not in chart.attrib  # actual data construction, not a chart-wide wipe
    assert [node.attrib["data-chart-point"] for node in chart.iter() if "data-chart-point" in node.attrib] == ["first"]
    assert "Measured output" in mid and "3 items" in mid and "7 items" not in mid
    for at in (1000, 100, 700, 0, 300, 500, 900):
        assert compose_png_frame(layout, timeline, at).png == pixels[at]
    (tmp_path / (kind + "-production.png")).write_bytes(pixels[1000])
    assert (layout, timeline) == before


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("verb", ["reveal", "enter"])
def test_other_existing_construction_modes_keep_native_chart_content(portrait, verb):
    layout, timeline = runtime_documents(portrait=portrait, verb=verb)
    mid = compose_svg_frame(layout, timeline, 500).svg
    assert 'data-chart-point="first"' in mid and 'data-chart-point="second"' in mid
    assert "Measured output" in mid
    assert compose_png_frame(layout, timeline, 500).png != compose_png_frame(layout, timeline, 1000).png


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("kind", ["bars", "line"])
def test_same_chart_history_frozen_offline_and_shuffled_matches_normal(kind, portrait, monkeypatch):
    layout, timeline = runtime_documents(kind, portrait=portrait)
    expected = {at: compose_png_frame(layout, timeline, at).png for at in (0, 300, 700, 1000)}
    typed, resolved = ExecutableLayoutV2.model_validate(layout), ResolvedVisualTimelineV2.model_validate(timeline)
    inputs = verify_split_paint_inputs(typed, {})
    registry = registry_endpoint_inputs_for_objects({obj.object_id: obj for obj in typed.objects},
        frozen_files={name: raw for name, _, raw in inputs.bundle_bytes})
    def forbidden(*args, **kwargs):
        raise AssertionError("frozen chart attempted a live source or network read")
    monkeypatch.setattr(Path, "read_bytes", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    for at in (1000, 0, 700, 300, 1000):
        sample = v2_state._evaluate_frame_with_registry_inputs(layout, timeline, at, registry)
        svg = _compose_validated_svg_frame(typed, resolved, sample, {}, split_inputs=inputs)
        assert _rasterize_svg_frame(typed, svg, split_inputs=inputs).png == expected[at]


@pytest.mark.parametrize("mode", ["draw", "reveal", "enter"])
def test_inline_chart_uses_explicit_data_adapter_not_registry_split_construction(mode):
    layout, _ = runtime_documents()
    chart = ExecutableLayoutV2.model_validate(layout).objects[0]
    adapter = _split_primitive_paint(chart, mode)
    assert adapter.family == "data chart"
    assert adapter.proof_kind == "native_data_chart_alpha_v1"


def nested_documents(*, portrait=False, aperture="clip"):
    layout, timeline = runtime_documents(portrait=portrait)
    chart = layout["objects"][0]
    root = deepcopy(chart)
    root.pop("chart_payload")
    root.pop("variant")
    root.update(object_id="chart-root", object_type="group", child_ids=[chart["object_id"]],
        anchors=[], visible=True, initial_state="visible")
    root["geometry"]["bounds"] = {"x": 0., "y": 0., "width": 720., "height": 720.}
    root["style"] = {"stroke": None, "fill": None, "text": None, "effect": None}
    root["transform"].update(position={"x": 10., "y": 5.}, scale_x=1.05, scale_y=1.05,
                             rotation_degrees=3., origin={"x": 0., "y": 0.})
    chart["parent_id"] = root["object_id"]
    outer = deepcopy(root)
    outer.update(object_id="chart-aperture", object_type=aperture, child_ids=[root["object_id"]])
    outer["transform"] = deepcopy(chart["transform"])
    outer["geometry"]["bounds"] = {"x": 80., "y": 160., "width": 240., "height": 340.}
    root["parent_id"] = outer["object_id"]
    layout["objects"] += [root, outer]
    if aperture == "mask":
        source = deepcopy(outer)
        source.pop("child_ids")
        source.update(object_id="chart-mask", object_type="rectangle", path_data=None)
        outer.update(mask_mode="alpha", mask_source_object_id="chart-mask",
            mask_coordinate_space="parent_local", invert=False, feather_px=0)
        layout["objects"].append(source)
    layout["boards"][0]["object_ids"] = [obj["object_id"] for obj in layout["objects"]]
    layout["boards"][0]["density_limit"] = len(layout["objects"])
    timeline["initial_object_states"] = [{"object_id": obj["object_id"], "state": obj["initial_state"],
        "visible": obj["visible"], "state_version": 1} for obj in layout["objects"]]
    timeline["layout_sha256"] = digest(layout)
    return layout, timeline


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("aperture", ["clip", "mask"])
def test_actual_nonidentity_group_and_shared_aperture_clip_the_same_chart(portrait, aperture):
    layout, timeline = nested_documents(portrait=portrait, aperture=aperture)
    pixels = compose_png_frame(layout, timeline, 1000).png
    with Image.open(io.BytesIO(pixels)) as image:
        image = image.convert("RGB")
        right = image.crop((322, 0, image.width, image.height))
        assert right.tobytes() == bytes((250, 248, 241)) * (right.width * right.height)
        left = image.crop((80, 160, 320, 500))
        assert left.tobytes() != bytes((250, 248, 241)) * (left.width * left.height)
    svg = compose_svg_frame(layout, timeline, 500).svg
    assert 'data-object-id="chart-root"' in svg and 'data-object-id="chart-aperture"' in svg
    assert 'data-object-id="chart-mask"' not in svg
    assert compose_png_frame(layout, timeline, 1000).png == pixels


@pytest.mark.parametrize("fault", ["series_color", "overlapping_labels"])
def test_invalid_native_chart_rejects_even_before_its_hidden_action_starts(fault):
    layout, timeline = runtime_documents()
    chart = layout["objects"][0]["chart_payload"]
    if fault == "series_color":
        chart["series"][0]["color"] = "invented"
    else:
        chart["x_axis"]["ticks"][1]["value"] = 1.001
    timeline["layout_sha256"] = digest(layout)
    with pytest.raises(ValueError, match="unknown Paper.*token|label.*overlap"):
        compose_svg_frame(layout, timeline, 0)
