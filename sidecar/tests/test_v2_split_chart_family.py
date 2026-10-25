"""S3-F04: real authored data charts through the single Split paint path."""

import io
import json
import socket
import xml.etree.ElementTree as ET
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

import pytest
from PIL import Image
from test_v2_chart_contract import authored_payload
from test_v2_split_action import replay_split
from test_v2_split_families import geometry_split_family
from test_v2_split_identity import sample_for_layout
from v2_fixtures import digest

from atme.render.v2_split import _observed_split_placements, capture_split
from atme.render.v2_split_identity import SplitContentReceipt
from atme.render.v2_split_paint import (
    prove_split_coverage,
    split_family_admission,
    verify_split_paint_inputs,
)
from atme.render.v2_state import _sample_validated_frame, camera_segments
from atme.render.v2_svg import _compose_validated_svg_frame, _rasterize_svg_frame
from atme.store.contracts_v2 import (
    ExecutableLayoutV2,
    ResolvedAction,
    ResolvedVisualTimelineV2,
    SplitPolicy,
    _split_expected_completion,
)


def chart_split_family(portrait=False, kind="bars", mode="draw"):
    initial, _, resolved, timeline, _, _, _ = geometry_split_family(portrait, "rectangle", mode)
    raw, action = initial.model_dump(mode="json"), resolved.model_dump(mode="json")
    hashes, receipts = {}, {}
    for obj in raw["objects"]:
        key = obj["object_id"]
        index = ("source", "part-1", "part-2").index(key)
        obj.pop("path_data")
        payload = authored_payload(kind)
        payload["title"] = ("Source data", "First result", "Second result")[index]
        # Results are complete independent authored charts, not source fragments.
        payload["series"][0]["points"][0].update(y=3. + index, label=f"{3+index} items")
        obj.update(object_type="chart", variant=None, chart_payload=payload)
        obj["geometry"] = {"bounds": {"x": 80. + index * 40 if portrait else 80. + index * 230,
            "y": 140. if portrait else 110., "width": 500., "height": 420.},
            "points": [], "corner_radius": None}
        obj["style"] = {"stroke": "ink", "fill": None, "text": None, "effect": None}
        projection = {name: obj[name] for name in
            ("object_type", "geometry", "style", "anchors", "asset_id", "variant", "chart_payload")}
        canonical = json.dumps(projection, sort_keys=True, separators=(",", ":"))
        hashes[key] = sha256(canonical.encode()).hexdigest()
        receipts[key] = SplitContentReceipt(key, canonical, hashes[key])
    layout = ExecutableLayoutV2.model_validate(raw)
    before = sample_for_layout(layout)
    policy = action["action"]["split_policy"]
    policy["source_basis"]["placements"] = [row.model_dump(mode="json") for row in
        _observed_split_placements(before, {obj.object_id: obj for obj in layout.objects}, set(hashes), receipts)]
    for row in policy["correspondences"]:
        row.update(source_content_sha256=hashes["source"], result_content_sha256=hashes[row["result_object_id"]])
    policy["source_basis_sha256"] = digest(policy["source_basis"])
    completion = _split_expected_completion(SplitPolicy.model_validate(policy))
    completion["completion_sha256"] = digest(completion)
    action["split_completion_receipt"] = completion
    resolved = ResolvedAction.model_validate(action)
    raw_timeline = timeline.model_dump(mode="json")
    raw_timeline["actions"] = [action]
    raw_timeline["layout_sha256"] = digest(raw)
    raw_timeline["initial_object_states"] = [{"object_id": row.object_id, "state": row.state,
        "visible": row.visible, "state_version": dict(before.state_versions)[row.object_id]} for row in before.objects]
    return layout, before, resolved, ResolvedVisualTimelineV2.model_validate(raw_timeline), hashes


def chart_split_frames(layout, before, resolved, timeline, inputs, times):
    replay = replay_split(layout, before, (resolved,), duration=timeline.duration_ms)
    cameras = camera_segments(layout, timeline, replay)
    outputs = {}
    for at in times:
        snapshot = _sample_validated_frame(layout, timeline, replay, cameras, at)
        svg = _compose_validated_svg_frame(layout, timeline, snapshot, {}, split_inputs=inputs)
        png = _rasterize_svg_frame(layout, svg, split_inputs=inputs).png
        if at in outputs:
            assert outputs[at] == (svg.svg, png)
        outputs[at] = (svg.svg, png)
    return outputs


def pixels(raw):
    with Image.open(io.BytesIO(raw)) as image:
        return image.convert("RGBA").tobytes()


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("kind", ["bars", "line"])
@pytest.mark.parametrize("mode", ["draw", "reveal", "enter"])
def test_authored_chart_family_has_exact_identity_native_proof_and_mode(portrait, kind, mode):
    layout, before, resolved, _, hashes = chart_split_family(portrait, kind, mode)
    original = deepcopy(layout.model_dump(mode="json"))
    capture = capture_split(resolved, layout, before, {})
    inputs = verify_split_paint_inputs(layout, {})
    for key in ("source", "part-1", "part-2"):
        admission = split_family_admission(key, capture, layout, inputs)
        assert admission.family == "data chart"
        assert admission.proof_kind == "native_data_chart_alpha_v1"
        assert admission.content_sha256 == hashes[key]
        assert admission.mode == ("source_fade" if key == "source" else mode)
        assert admission.paint_inputs_sha256 == inputs.inputs_sha256
    assert len(set(hashes.values())) == 3
    assert layout.model_dump(mode="json") == original


def native_chart_oracle(layout, inputs, at, mode, *, dx=0.):
    """Owning painter oracle; literal Split phase/placement/order, no sampler.

    P3-30 independently proves this unchanged native primitive's data geometry.
    Here it is composed without any Split painter, receipt or state evaluator.
    """
    from atme.render.style_contracts import PaperInkStyle
    from atme.render.v2_chart import chart_svg
    from atme.render.v2_svg import SVGFrame, _rasterize_frozen_svg

    style = PaperInkStyle.model_validate_json(inputs.style_json)
    files = {name: data for name, _, data in inputs.bundle_bytes}
    width, height = layout.output_profile.width, layout.output_profile.height
    body = [f'<rect width="{width}" height="{height}" fill="{style.colors["paper"]}"/>']
    for obj in sorted(layout.objects, key=lambda obj: obj.z_index):
        source = obj.object_id == "source"
        if source and at >= 32 or not source and at == 0:
            continue
        fraction = .5 if at == 12 else 1.
        opacity = (.8333 if at == 12 else 1.) if source else 1.
        ink = chart_svg(obj, style, 2/3, files, draw_fraction=fraction if not source and mode == "draw" else None)
        if not source and at == 12 and mode in {"reveal", "enter"}:
            box = obj.geometry.bounds
            clip = "oracle-" + obj.object_id
            ink = (f'<defs><clipPath id="{clip}"><rect x="{box.x}" y="{box.y}" '
                   f'width="{box.width/2}" height="{box.height}"/></clipPath></defs>'
                   f'<g clip-path="url(#{clip})">{ink}</g>')
        tx = -40. if not source and at == 12 and mode == "enter" else 0.
        tx += dx if obj.object_id == "part-1" else 0.
        body.append(f'<g opacity="{opacity}" transform="translate({tx} 0)">{ink}</g>')
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">{"".join(body)}</svg>'
    return _rasterize_frozen_svg(SVGFrame(at, width, height, svg), style, files).png


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("kind", ["bars", "line"])
@pytest.mark.parametrize("mode", ["draw", "reveal", "enter"])
def test_chart_split_native_pixels_authored_clocks_order_and_shuffled_seek(portrait, kind, mode, tmp_path):
    layout, before, resolved, timeline, _ = chart_split_family(portrait, kind, mode)
    capture = capture_split(resolved, layout, before, {})
    inputs = verify_split_paint_inputs(layout, {})
    split_family_admission("part-1", capture, layout, inputs)
    outputs = chart_split_frames(layout, before, resolved, timeline, inputs, (40, 0, 12, 40, 12, 0))
    assert [row.object_id for row in resolved.action.split_policy.results] == ["part-2", "part-1"]
    for at in (0, 12, 40):
        assert pixels(outputs[at][1]) == pixels(native_chart_oracle(layout, inputs, at, mode))
        tree = ET.fromstring(outputs[at][0])
        order = [node.attrib["data-object-id"] for node in tree.iter() if "data-object-id" in node.attrib]
        assert order == {0: ["source"], 12: ["source", "part-1", "part-2"], 40: ["part-1", "part-2"]}[at]
        if at == 12:
            first = next(node for node in tree.iter() if node.attrib.get("data-object-id") == "part-1")
            point_ids = [node.attrib["data-chart-point"] for node in first.iter() if "data-chart-point" in node.attrib]
            assert point_ids == (["first"] if mode == "draw" else ["first", "second"])
            assert ("clip-path" in first.attrib) == (mode != "draw")
    assert outputs[0][1] != outputs[12][1] != outputs[40][1]
    (tmp_path / f"{kind}-{mode}-split.png").write_bytes(outputs[12][1])


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("kind", ["bars", "line"])
@pytest.mark.parametrize("mode", ["draw", "reveal", "enter"])
def test_chart_split_all_integer_ms_handoff_and_frozen_offline_pixels(portrait, kind, mode, monkeypatch):
    layout, before, resolved, timeline, _ = chart_split_family(portrait, kind, mode)
    capture = capture_split(resolved, layout, before, {})
    inputs = verify_split_paint_inputs(layout, {})
    expected = chart_split_frames(layout, before, resolved, timeline, inputs, (0, 12, 24, 32, 40))
    def forbidden(*args, **kwargs):
        raise AssertionError("frozen Split chart used live files or network")
    monkeypatch.setattr(Path, "read_bytes", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    proof = prove_split_coverage(capture, layout, inputs)
    assert proof.proof_kind == "native_alpha_all_integer_ms_v1"
    assert proof.intervals[0].start_ms == 0 and proof.intervals[-1].end_ms == 40
    assert proof.intervals[-1].painted_root_ids == ("part-1", "part-2")
    assert all(row.painted_root_ids for row in proof.intervals)
    for at, result in chart_split_frames(layout, before, resolved, timeline, inputs, (40, 12, 0, 32, 24)).items():
        assert result == expected[at]


@pytest.mark.parametrize("field", ["value", "label", "unit", "domain", "clock", "color", "highlight", "order"])
def test_fresh_chart_resources_cannot_replace_captured_semantic_content(field):
    layout, before, resolved, _, _ = chart_split_family()
    capture = capture_split(resolved, layout, before, {})
    raw = layout.model_dump(mode="json")
    payload = next(obj for obj in raw["objects"] if obj["object_id"] == "part-1")["chart_payload"]
    original = deepcopy(payload)
    if field == "value":
        payload["series"][0]["points"][0]["y"] = 5.
    elif field == "label":
        payload["series"][0]["points"][0]["label"] = "Different"
    elif field == "unit":
        payload["y_axis"]["unit"] = "ms"
    elif field == "domain":
        payload["y_axis"]["domain"][1] = 12.
    elif field == "clock":
        payload["construction"][1]["start_fraction"] = .6
    elif field == "color":
        payload["series"][0]["color"] = "success"
    elif field == "highlight":
        payload["highlights"][0]["color"] = "ink"
    else:
        payload["construction"].reverse()
    assert payload != original  # A supposed content mutation must never be a no-op.
    changed = ExecutableLayoutV2.model_validate(raw)
    with pytest.raises(ValueError, match="Split captured content differs"):
        split_family_admission("part-1", capture, changed, verify_split_paint_inputs(changed, {}))


def test_split_chart_write_remains_an_incompatible_mode():
    layout, before, resolved, _, _ = chart_split_family(mode="write")
    capture = capture_split(resolved, layout, before, {})
    with pytest.raises(ValueError, match="Split write is incompatible with data chart construction"):
        split_family_admission("part-1", capture, layout, verify_split_paint_inputs(layout, {}))


@pytest.mark.parametrize("fault", ["font", "missing_evidence", "forged_evidence"])
def test_chart_split_frozen_font_and_rehashed_native_evidence_tamper_reject(fault):
    layout, before, resolved, _, _ = chart_split_family()
    capture = capture_split(resolved, layout, before, {})
    inputs = verify_split_paint_inputs(layout, {})
    if fault == "font":
        rows = tuple((name, checksum, data+b"changed") if name.endswith(".ttf") else (name, checksum, data)
                     for name, checksum, data in inputs.bundle_bytes)
        forged = replace(inputs, bundle_bytes=rows)
        expected = "Split frozen bundle row is invalid"
    else:
        rows = [json.loads(row) for row in inputs.paint_evidence]
        if fault == "missing_evidence":
            rows = [row for row in rows if row.get("object_id") != "part-1"]
        else:
            next(row for row in rows if row.get("object_id") == "part-1")["paint"]["payload"]["title"] = "Forgery"
        manifest = json.loads(inputs.manifest_json)
        manifest["paint_evidence"] = rows
        encoded = json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        forged = replace(inputs, paint_evidence=tuple(json.dumps(row, sort_keys=True, separators=(",", ":"),
            ensure_ascii=False) for row in rows), manifest_json=encoded, inputs_sha256=sha256(encoded.encode()).hexdigest())
        expected = "Split frozen paint binding differs"
    with pytest.raises(ValueError, match=expected):
        split_family_admission("part-1", capture, layout, forged)
