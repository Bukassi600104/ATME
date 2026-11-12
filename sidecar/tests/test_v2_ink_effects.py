"""Bounded ink references: pure admission/token proof and a finite native handoff."""
from __future__ import annotations

import builtins
import io
import socket
import subprocess
import xml.etree.ElementTree as ET
from dataclasses import replace
from types import SimpleNamespace

import pytest
from atme.render import v2_svg
from atme.render.style_bundle import load_bundle
from atme.render.v2_connector import UnsupportedConnector, connector_geometry
from atme.render.v2_state import FrameObject
from atme.store.contracts_v2 import ExecutableLayoutV2
from PIL import Image, ImageFont
from test_v2_connector_svg import connector_documents
from test_v2_svg import primitive_documents


@pytest.fixture
def pure_guard(monkeypatch):
    import resvg_py

    def denied(*args, **kwargs):
        raise AssertionError("pure ink test attempted native/font/network execution")

    original_import = builtins.__import__
    def guarded_import(name, *args, **kwargs):
        if name.split(".")[0] in {"soundfile", "pydub", "av", "noisereduce", "pedalboard"}:
            raise AssertionError("pure ink test attempted audio execution")
        return original_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", guarded_import)
    monkeypatch.setattr(subprocess, "Popen", denied)
    monkeypatch.setattr(resvg_py, "svg_to_bytes", denied)
    monkeypatch.setattr(ImageFont, "truetype", denied)
    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(socket.socket, "connect", denied)


def ink_objects(effect, *, connector=False):
    raw, _ = connector_documents() if connector else primitive_documents()
    key = "object-arrow" if connector else "object-system"
    next(obj for obj in raw["objects"] if obj["object_id"] == key)["style"]["effect"] = effect
    layout = ExecutableLayoutV2.model_validate(raw)
    objects = {obj.object_id: obj for obj in layout.objects}
    return objects[key], objects


def state_for(obj, *, fraction=1):
    return FrameObject(obj.object_id, obj.board_id, "visible", True, 1., fraction, obj.transform)


def paint(obj, objects, style, scale, *, verb=None, fraction=1):
    states = {key: state_for(value) for key, value in objects.items()}
    state = replace(states[obj.object_id], reveal_fraction=fraction)
    states[obj.object_id] = state
    return v2_svg._object_markup(obj, state, style, None, scale, verb, objects, states, {}, {})


@pytest.mark.parametrize("connector", [False, True], ids=["mark", "connector"])
@pytest.mark.parametrize("effect,token", [("ink_fine", "fine_px"), ("ink_emphasis", "emphasis_px")])
@pytest.mark.parametrize("scale", [2 / 3, 1.])
def test_pure_ink_selected_width_color_fill_and_centerline(pure_guard, connector, effect, token, scale):
    style, _, root = load_bundle()
    obj, objects = ink_objects(effect, connector=connector)
    v2_svg._preflight_object(obj, style, root, scale, objects)
    result = paint(obj, objects, style, scale)
    expected = v2_svg._n(getattr(style.strokes, token) * scale)
    assert f'stroke-width="{expected}"' in result
    assert 'stroke="#2457D6"' in result
    null = obj.model_copy(update={"style": obj.style.model_copy(update={"effect": None})})
    baseline = paint(null, {**objects, obj.object_id: null}, style, scale)
    a, b = ET.fromstring(f"<g>{result}</g>"), ET.fromstring(f"<g>{baseline}</g>")
    route = "d" if connector else "x"
    assert next(a.iter("path" if connector else "rect")).attrib[route] == next(
        b.iter("path" if connector else "rect")).attrib[route]
    if not connector:
        assert next(a.iter("rect")).attrib["fill"] == next(b.iter("rect")).attrib["fill"]
    else:
        assert next(a.iter("polygon")).attrib["points"] != next(b.iter("polygon")).attrib["points"]


@pytest.mark.parametrize("effect", ["", "shadow", "ink_regular"])
def test_pure_ink_unknown_even_hidden_rejects(pure_guard, effect):
    style, _, root = load_bundle()
    obj, objects = ink_objects(effect)
    assert obj.visible is False
    with pytest.raises(v2_svg.UnsupportedVisualObject):
        v2_svg._preflight_object(obj, style, root, 2 / 3, objects)


@pytest.mark.parametrize("kind", ["highlight", "underline"])
def test_pure_ink_attention_carriers_reject(pure_guard, kind):
    style, _, root = load_bundle()
    obj, objects = ink_objects("ink_fine")
    raw = obj.model_dump(mode="json")
    raw.update(object_type=kind)
    raw["geometry"]["corner_radius"] = None
    raw["style"]["fill"] = None
    obj = type(obj).model_validate(raw)
    with pytest.raises(v2_svg.UnsupportedVisualObject):
        v2_svg._preflight_object(obj, style, root, 2 / 3, {**objects, obj.object_id: obj})


def test_pure_ink_owned_pointer_rejects(pure_guard):
    style, _, root = load_bundle()
    obj, objects = ink_objects("ink_emphasis", connector=True)
    obj = obj.model_copy(update={"role": "pointer"})
    with pytest.raises(v2_svg.UnsupportedVisualObject):
        v2_svg._preflight_object(obj, style, root, 2 / 3, objects, annotation_pointer=True)


def test_pure_ink_connector_halfstroke_immediate_invalid(pure_guard):
    obj, _ = ink_objects("ink_emphasis", connector=True)
    bounds = obj.geometry.bounds.model_copy(update={"x": 0., "y": 0., "width": 100., "height": 100.})
    obj = obj.model_copy(update={"geometry": obj.geometry.model_copy(update={"bounds": bounds})})
    width = 7.
    accepted = connector_geometry(obj, (3.5, 50.), (90., 50.), width)
    assert accepted.points[0] == (3.5, 50.)
    with pytest.raises(UnsupportedConnector, match="bounds|footprint"):
        connector_geometry(obj, (3.4999, 50.), (90., 50.), width)
    null = obj.model_copy(update={"style": obj.style.model_copy(update={"effect": None})})
    assert connector_geometry(null, (0., 50.), (90., 50.), 4.).points[0] == (0., 50.)


def test_pure_ink_null_serialization_and_default_width(pure_guard):
    style, _, root = load_bundle()
    obj, objects = ink_objects(None)
    before = obj.model_dump_json()
    v2_svg._preflight_object(obj, style, root, 2 / 3, objects)
    assert 'stroke-width="2.6667"' in paint(obj, objects, style, 2 / 3)
    assert obj.model_dump_json() == before
    assert '"effect":null' in before


@pytest.mark.parametrize("scale", [2 / 3, 1.])
def test_pure_evidence_declared_tokens_and_authored_darkening(pure_guard, monkeypatch, scale):
    from v2_fixtures import executable_layout_v2

    layout = ExecutableLayoutV2.model_validate(executable_layout_v2())
    obj = layout.objects[2]
    treatment = layout.evidence_treatments[0]
    treatment = treatment.model_copy(update={"intent": treatment.intent.model_copy(update={"darkening": .37})})
    style, _, root = load_bundle()
    monkeypatch.setattr(v2_svg, "_evidence_crop_png", lambda payload, crop: b"unchanged-crop")
    monkeypatch.setattr(v2_svg, "_evidence_text", lambda value, *args: value)
    result = v2_svg._evidence_markup(obj, state_for(obj), style, root, scale,
        SimpleNamespace(payload=b"source-bytes"), treatment)
    nodes = list(ET.fromstring(f"<g>{result}</g>").iter())
    dark = [node for node in nodes if "data-evidence-darkening" in node.attrib]
    assert dark and all(node.attrib["fill"] == style.colors[style.evidence.mask_color_token]
                        and node.attrib["opacity"] == "0.37" for node in dark)
    for key in ("data-evidence-focus", "data-evidence-annotation"):
        node = next(node for node in nodes if node.attrib.get(key) in {treatment.intent.claim_id, "pointer"})
        assert node.attrib["stroke"] == style.colors[style.evidence.highlight_color_token]
        assert node.attrib["stroke-width"] == v2_svg._n(style.strokes.fine_px * scale)
    label = next(node for node in nodes if "data-evidence-source-label" in node.attrib)
    assert label.attrib["fill"] == style.colors[style.evidence.source_label_color_token]
    assert "dW5jaGFuZ2VkLWNyb3A=" in result

@pytest.mark.parametrize("kind", ["freehand_polyline", "line", "rectangle", "rounded_rectangle", "ellipse", "polygon", "bracket"])
def test_pure_ink_closed_mark_map(pure_guard, kind):
    from test_v2_split_families import authored_geometry

    style, _, root = load_bundle()
    obj, objects = ink_objects("ink_fine")
    raw = obj.model_dump(mode="json")
    object_type, geometry, path, _, _ = authored_geometry(kind, (80., 160., 200., 200.))
    raw.update(object_type=object_type, geometry=geometry, path_data=path)
    raw["style"]["fill"] = None
    obj = type(obj).model_validate(raw)
    objects[obj.object_id] = obj
    v2_svg._preflight_object(obj, style, root, 2 / 3, objects)
    assert 'stroke-width="1.3333"' in paint(obj, objects, style, 2 / 3)


def test_pure_ink_text_carrier_rejects(pure_guard):
    style, _, root = load_bundle()
    _, objects = ink_objects(None)
    obj = objects["object-label"]
    obj = obj.model_copy(update={"style": obj.style.model_copy(update={"effect": "ink_fine"})})
    with pytest.raises(v2_svg.UnsupportedVisualObject):
        v2_svg._preflight_object(obj, style, root, 2 / 3, {**objects, obj.object_id: obj})


def test_pure_ink_connector_selected_head_immediate_invalid(pure_guard):
    obj, _ = ink_objects("ink_emphasis", connector=True)
    width = 7.
    wing = float(f"{6 * width / 2.6667:.4f}")
    bounds = obj.geometry.bounds.model_copy(update={"x": 0., "y": 50. - wing, "width": 100., "height": 2 * wing})
    obj = obj.model_copy(update={"geometry": obj.geometry.model_copy(update={"bounds": bounds})})
    assert connector_geometry(obj, (30., 50.), (90., 50.), width).head[1][1] == 50. - wing
    changed = bounds.model_copy(update={"y": bounds.y + .0001, "height": bounds.height - .0001})
    obj = obj.model_copy(update={"geometry": obj.geometry.model_copy(update={"bounds": changed})})
    with pytest.raises(UnsupportedConnector, match="bounds|head|footprint"):
        connector_geometry(obj, (30., 50.), (90., 50.), width)


def _native_svg(body, portrait=False, defs=""):
    width, height = (720, 1280) if portrait else (1280, 720)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">'
            f'<defs>{defs}</defs><rect width="{width}" height="{height}" fill="#FAF8F1"/>{body}</svg>')


def _native_png(svg):
    import resvg_py
    return resvg_py.svg_to_bytes(svg_string=svg, skip_system_fonts=True)


def _retain_pair(directory, stem, svg, expected_svg):
    actual, expected = _native_png(svg), _native_png(expected_svg)
    for kind, text, png in (("actual", svg, actual), ("expected", expected_svg, expected)):
        (directory / f"{stem}-{kind}.svg").write_text(text, encoding="utf-8")
        (directory / f"{stem}-{kind}.png").write_bytes(png)
    with Image.open(io.BytesIO(actual)) as a, Image.open(io.BytesIO(expected)) as b:
        assert a.convert("RGBA").tobytes() == b.convert("RGBA").tobytes()
    return actual


def _native_line_object(effect, connector):
    obj, objects = ink_objects(effect, connector=connector)
    geometry = obj.geometry.model_dump(mode="json")
    geometry.update(bounds={"x": 80., "y": 80., "width": 240., "height": 80.}, corner_radius=None,
                    points=[] if connector else [{"x": 100., "y": 100.}, {"x": 300., "y": 100.}])
    raw = obj.model_dump(mode="json")
    raw.update(geometry=geometry)
    if not connector:
        raw.update(object_type="line", path_data=None)
        raw["style"]["fill"] = None
    obj = type(obj).model_validate(raw)
    objects[obj.object_id] = obj
    if connector:
        for key, x in ((obj.source_object_id, 80.), (obj.destination_object_id, 280.)):
            endpoint = objects[key]
            box = endpoint.geometry.bounds.model_copy(update={"x": x, "y": 80., "width": 40., "height": 40.})
            objects[key] = endpoint.model_copy(update={"geometry": endpoint.geometry.model_copy(update={"bounds": box})})
    return obj, objects


def _literal_line(width, connector, fraction):
    if fraction == 0:
        return ""
    n = lambda value: f"{value:.4f}".rstrip("0").rstrip(".") if value else "0"
    dash = (' stroke-dasharray="200 200" stroke-dashoffset="100"' if fraction == .5 else "")
    tag = 'path d="M 100 100 L 300 100"' if connector else 'line x1="100" y1="100" x2="300" y2="100"'
    body = (f'<{tag} fill="none" stroke="#2457D6" stroke-width="{n(width)}" '
            f'stroke-linecap="round" stroke-linejoin="round"{dash}/>')
    if connector and fraction == 1:
        wing, depth = 6 * width / 2.6667, 14 * width / 2.6667
        body += (f'<polygon points="300,100 {n(300-depth)},{n(100+wing)} '
                 f'{n(300-depth)},{n(100-wing)}" fill="#2457D6"/>')
    return body


@pytest.mark.parametrize("portrait", [False, True], ids=["landscape", "portrait"])
@pytest.mark.parametrize("effect,width", [("ink_fine", 2.), ("ink_emphasis", 7.)])
@pytest.mark.parametrize("connector", [False, True], ids=["mark", "connector"])
def test_native_ink_literal_weights_null_and_draw_connect(tmp_path, portrait, effect, width, connector):
    style, _, root = load_bundle()
    scale = 2 / 3
    obj, objects = _native_line_object(effect, connector)
    v2_svg._preflight_object(obj, style, root, scale, objects)
    outputs = {}
    for fraction in (0., .5, 1., .5, 0.):
        body = paint(obj, objects, style, scale, verb="connect" if connector else "draw", fraction=fraction)
        actual = _native_svg(body, portrait)
        expected = _native_svg(_literal_line(width * scale, connector, fraction), portrait)
        png = _retain_pair(tmp_path, f"phase-{fraction:g}", actual, expected)
        if fraction in outputs:
            assert png == outputs[fraction]
        outputs[fraction] = png
    null = obj.model_copy(update={"style": obj.style.model_copy(update={"effect": None})})
    actual = _native_svg(paint(null, {**objects, obj.object_id: null}, style, scale), portrait)
    expected = _native_svg(_literal_line(4 * scale, connector, 1.), portrait)
    baseline = _retain_pair(tmp_path, "null", actual, expected)
    assert baseline != outputs[1.]
    with Image.open(io.BytesIO(outputs[1.])) as image:
        assert image.convert("RGB").getpixel((200, 100)) != (250, 248, 241)


@pytest.mark.parametrize("portrait", [False, True], ids=["landscape", "portrait"])
def test_native_ink_reveal_transform_opacity_clip_mask(tmp_path, portrait):
    style, _, root = load_bundle()
    layout, objects, states, key = _hierarchy_ink_fixture(portrait)
    definitions, body = v2_svg._compose_object_tree(objects, states,
        {obj.object_id: index for index, obj in enumerate(layout.objects)}, style, root, 2 / 3,
        {key: "reveal"}, {}, {}, {}, None, included_ids=set(objects),
        active_board_id=layout.boards[0].board_id, paint_canvas=layout.canvas)
    clip = v2_svg._clip_id(key)
    defs = (f'<clipPath id="{clip}"><rect x="80" y="80" width="120" height="80"/></clipPath>'
            '<clipPath id="outer"><rect x="110" y="80" width="160" height="80"/></clipPath>'
            '<mask id="mask" maskUnits="userSpaceOnUse" maskContentUnits="userSpaceOnUse" '
            'x="130" y="80" width="70" height="80" style="mask-type:alpha">'
            '<rect x="130" y="80" width="70" height="80" fill="white"/></mask>')
    expected = (f'<g clip-path="url(#outer)"><g mask="url(#mask)"><g transform="translate(12 8)" '
                f'opacity="0.5" clip-path="url(#{clip})">'
                f'{_literal_line(7 * 2 / 3, False, 1.)}</g></g></g>')
    _retain_pair(tmp_path, "reveal-transform-opacity-clip-mask", _native_svg(body, portrait, definitions),
                 _native_svg(expected, portrait, defs))

def _treated_split(portrait, connector, effect):
    from atme.render.v2_split import _observed_split_placements
    from atme.render.v2_split_identity import split_content_receipts
    from atme.store.contracts_v2 import (
        ResolvedAction,
        ResolvedVisualTimelineV2,
        SplitPolicy,
        _split_expected_completion,
    )
    from test_v2_split_connector_family import connector_split_family
    from test_v2_split_families import geometry_split_family
    from test_v2_split_identity import sample_for_layout
    from v2_fixtures import digest

    fixture = connector_split_family(portrait, "arrow", "draw") if connector else geometry_split_family(portrait, "rectangle", "draw")
    layout, _, resolved, clock = fixture[:4]
    raw = layout.model_dump(mode="json")
    for row in raw["objects"]:
        if row["object_id"] in {"source", "part-1", "part-2"}:
            row["style"]["effect"] = effect
    layout = ExecutableLayoutV2.model_validate(raw)
    before = sample_for_layout(layout)
    receipts = {row.object_id: row for row in split_content_receipts(layout, before, {})}
    action = resolved.model_dump(mode="json")
    policy = action["action"]["split_policy"]
    objects = {obj.object_id: obj for obj in layout.objects}
    policy["source_basis"]["placements"] = [row.model_dump(mode="json") for row in
        _observed_split_placements(before, objects, set(receipts), receipts)]
    for row in policy["correspondences"]:
        row.update(source_content_sha256=receipts["source"].content_sha256,
                   result_content_sha256=receipts[row["result_object_id"]].content_sha256)
    policy["source_basis_sha256"] = digest(policy["source_basis"])
    completion = _split_expected_completion(SplitPolicy.model_validate(policy))
    completion["completion_sha256"] = digest(completion)
    action["split_completion_receipt"] = completion
    resolved = ResolvedAction.model_validate(action)
    raw_clock = clock.model_dump(mode="json")
    raw_clock.update(layout_sha256=digest(raw), actions=[action])
    return layout, before, resolved, ResolvedVisualTimelineV2.model_validate(raw_clock)


@pytest.mark.parametrize("connector", [False, True], ids=["mark", "connector"])
def test_native_ink_retained_split_ordinary_frozen_pair(tmp_path, connector):
    from atme.render.v2_camera import camera_segments
    from atme.render.v2_split_paint import verify_split_paint_inputs
    from atme.render.v2_state import _sample_validated_frame
    from test_v2_split_action import replay_split

    layout, before, resolved, clock = _treated_split(False, connector, "ink_emphasis")
    assert (layout.output_profile.width, layout.output_profile.height) == (1280, 720)
    inputs = verify_split_paint_inputs(layout, {})
    replay = replay_split(layout, before, (resolved,), clock.duration_ms)
    cameras = camera_segments(layout, clock, replay, split_inputs=inputs)
    style, _, _ = load_bundle()
    objects = {obj.object_id: obj for obj in layout.objects}
    result = {}
    for at in (0, 12, 40, 12, 0):
        snapshot = _sample_validated_frame(layout, clock, replay, cameras, at)
        svg = v2_svg._compose_validated_svg_frame(layout, clock, snapshot, {}, None, split_inputs=inputs)
        png = v2_svg._rasterize_svg_frame(layout, svg, split_inputs=inputs).png
        (tmp_path / f"frozen-{at}.svg").write_text(svg.svg, encoding="utf-8")
        (tmp_path / f"frozen-{at}.png").write_bytes(png)
        if at in result:
            assert (svg.svg, png) == result[at]
        result[at] = svg.svg, png
    for at, keys in ((0, ("source",)), (40, ("part-1", "part-2"))):
        ordinary_ids = {obj.object_id for obj in layout.objects if obj.object_id.startswith("endpoint-")} | set(keys)
        body = "".join(paint(obj, objects, style, 2 / 3) for obj in sorted(layout.objects, key=lambda row: row.z_index)
                       if obj.object_id in ordinary_ids)
        ordinary = _native_svg(body)
        (tmp_path / f"ordinary-{at}.svg").write_text(ordinary, encoding="utf-8")
        ordinary_png = _native_png(ordinary)
        (tmp_path / f"ordinary-{at}.png").write_bytes(ordinary_png)
        with Image.open(io.BytesIO(result[at][1])) as a, Image.open(io.BytesIO(ordinary_png)) as b:
            assert a.convert("RGBA").tobytes() == b.convert("RGBA").tobytes()
        assert 'stroke-width="4.6667"' in result[at][0]
    assert layout.model_dump(mode="json")["objects"][0]["style"]["effect"] == "ink_emphasis"


@pytest.mark.parametrize("portrait", [False, True], ids=["landscape", "portrait"])
def test_native_evidence_tokens_before_after_source_preserved(tmp_path, portrait):
    from test_v2_evidence_compositor import evidence_documents

    service, layout, clock, verified = evidence_documents(tmp_path, portrait=portrait, darkening=.37)
    try:
        payload = {verified.asset_id: verified}
        frame = v2_svg.compose_svg_frame(layout, clock, 4900, payload)
        actual_png = v2_svg.compose_png_frame(layout, clock, 4900, payload).png
        style, _, _ = load_bundle()
        before = ET.fromstring(frame.svg)
        for node in before.iter():
            if "data-evidence-darkening" in node.attrib:
                assert node.attrib["fill"] == style.colors[style.evidence.mask_color_token]
                assert node.attrib["opacity"] == "0.37"
                node.attrib["fill"] = style.colors["ink"]
            elif "data-evidence-focus" in node.attrib or node.attrib.get("data-evidence-annotation") == "pointer":
                assert node.attrib["stroke"] == style.colors[style.evidence.highlight_color_token]
                node.attrib["stroke"] = style.colors["attention"]
            elif "data-evidence-source-label" in node.attrib:
                assert node.attrib["fill"] == style.colors[style.evidence.source_label_color_token]
                node.attrib["fill"] = style.colors["ink"]
        before_svg = ET.tostring(before, encoding="unicode")
        before_png = v2_svg._rasterize_svg_frame(ExecutableLayoutV2.model_validate(layout),
            replace(frame, svg=before_svg)).png
        for name, svg, png in (("actual", frame.svg, actual_png), ("before", before_svg, before_png)):
            (tmp_path / f"evidence-{name}.svg").write_text(svg, encoding="utf-8")
            (tmp_path / f"evidence-{name}.png").write_bytes(png)
        with Image.open(io.BytesIO(actual_png)) as a, Image.open(io.BytesIO(before_png)) as b:
            assert a.convert("RGBA").tobytes() != b.convert("RGBA").tobytes()
            colors = set(a.convert("RGB").getdata())
            assert (244, 201, 93) in colors
            assert (25, 185, 50) in colors or (235, 30, 40) in colors
        actual_crop = next(node.attrib["href"] for node in ET.fromstring(frame.svg).iter()
                           if "data-evidence-crop" in node.attrib)
        before_crop = next(node.attrib["href"] for node in before.iter() if "data-evidence-crop" in node.attrib)
        assert actual_crop == before_crop
    finally:
        service.store.close()

@pytest.mark.parametrize("translated", [False, True], ids=["local", "transformed"])
def test_pure_ink_canvas_immediate_invalid(pure_guard, translated):
    from atme.store.contracts_v2 import Bounds

    obj, objects = ink_objects("ink_emphasis")
    box = obj.geometry.bounds.model_copy(update={"x": 3.5, "y": 20., "width": 100., "height": 100.})
    obj = obj.model_copy(update={"geometry": obj.geometry.model_copy(update={"bounds": box, "corner_radius": None}),
                                 "object_type": "rectangle"})
    objects[obj.object_id] = obj
    states = {key: state_for(value) for key, value in objects.items()}
    canvas = Bounds(x=0., y=0., width=1280., height=720.)
    v2_svg._validate_ink_canvas(obj, objects, states, canvas, 7.)
    if translated:
        transform = obj.transform.model_copy(update={"position": obj.transform.position.model_copy(update={"x": -.0001})})
        states[obj.object_id] = replace(states[obj.object_id], transform=transform)
    else:
        box = box.model_copy(update={"x": 3.4999})
        obj = obj.model_copy(update={"geometry": obj.geometry.model_copy(update={"bounds": box})})
        objects[obj.object_id] = obj
    with pytest.raises(v2_svg.UnsupportedVisualObject, match="canvas bounds"):
        v2_svg._validate_ink_canvas(obj, objects, states, canvas, 7.)



@pytest.mark.parametrize("connector", [False, True], ids=["mark", "connector"])
def test_pure_native_split_fixture_contracts(pure_guard, connector):
    layout, before, resolved, clock = _treated_split(False, connector, "ink_emphasis")
    assert resolved == clock.actions[0]
    assert {obj.object_id for obj in before.objects} == {obj.object_id for obj in layout.objects}
    assert all(obj.style.effect == "ink_emphasis" for obj in layout.objects
               if obj.object_id in {"source", "part-1", "part-2"})


def _hierarchy_ink_fixture(portrait):
    from copy import deepcopy

    from test_v2_mask_contract import MASK_FIELDS, masked_documents

    _, raw, _ = masked_documents()
    obj, _ = _native_line_object("ink_emphasis", False)
    mark = obj.model_dump(mode="json")
    mark["parent_id"] = "object-group"
    mark["transform"]["position"] = {"x": 12., "y": 8.}
    mask = deepcopy(raw["objects"][3])
    mask.update(parent_id="outer-clip", child_ids=[obj.object_id])
    source = deepcopy(raw["objects"][4])
    source.update(object_type="rectangle", parent_id="outer-clip")
    source["geometry"].update(bounds={"x": 130., "y": 80., "width": 70., "height": 80.}, corner_radius=None)
    outer = deepcopy(mask)
    for key in MASK_FIELDS:
        outer.pop(key)
    outer.update(object_id="outer-clip", object_type="clip", parent_id=None, child_ids=["object-group", "mask-source"])
    outer["geometry"].update(bounds={"x": 110., "y": 80., "width": 160., "height": 80.})
    raw["objects"] = [mark, mask, source, outer]
    raw["boards"][0]["object_ids"] = [row["object_id"] for row in raw["objects"]]
    if portrait:
        raw["output_profile"] = {"profile_id": "SHORT_FORM_9_16", "width": 720, "height": 1280, "fps": 30}
        raw["canvas"] = {"x": 0., "y": 0., "width": 720., "height": 1280.}
    layout = ExecutableLayoutV2.model_validate(raw)
    objects = {obj.object_id: obj for obj in layout.objects}
    states = {key: state_for(value) for key, value in objects.items()}
    states[obj.object_id] = replace(states[obj.object_id], opacity=.5, reveal_fraction=.5)
    return layout, objects, states, obj.object_id


@pytest.mark.parametrize("portrait", [False, True], ids=["landscape", "portrait"])
def test_pure_native_hierarchy_fixture_contracts(pure_guard, portrait):
    layout, objects, states, key = _hierarchy_ink_fixture(portrait)
    assert objects[key].parent_id == "object-group"
    assert objects["object-group"].parent_id == "outer-clip"
    assert states[key].reveal_fraction == .5
    assert layout.canvas.height == (1280 if portrait else 720)


def test_pure_ink_managed_connect_validates_selected_weight_while_hidden(pure_guard):
    from atme.render.v2_state import V2FrameError, evaluate_frame
    from test_v2_connection_actions import relationship_documents
    from v2_fixtures import digest

    layout, clock = relationship_documents()
    arrow = layout["objects"][3]
    arrow["geometry"]["bounds"] = {"x": 297.5, "y": 245., "width": 35., "height": 90.}
    clock["layout_sha256"] = digest(layout)
    assert not evaluate_frame(layout, clock, 0).object("object-arrow").visible
    arrow["style"]["effect"] = "ink_emphasis"
    clock["layout_sha256"] = digest(layout)
    with pytest.raises(V2FrameError, match="bounds|head|footprint"):
        evaluate_frame(layout, clock, 0)


def test_pure_ink_filled_only_none_stroke_does_not_synthesize_ink(pure_guard):
    style, _, root = load_bundle()
    obj, objects = ink_objects("ink_fine")
    obj = obj.model_copy(update={"style": obj.style.model_copy(update={"stroke": "none", "fill": "surface.paper"})})
    with pytest.raises(v2_svg.UnsupportedVisualObject, match="unknown Paper & Ink style token: none"):
        v2_svg._preflight_object(obj, style, root, 2 / 3, {**objects, obj.object_id: obj})
