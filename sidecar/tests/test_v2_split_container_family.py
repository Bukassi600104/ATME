"""S3-F05: authored container closures through the single Split family path."""

import io
import json
import socket
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

import pytest
import resvg_py
from PIL import Image
from test_v2_split_action import replay_split
from test_v2_split_families import geometry_split_family, n
from test_v2_split_identity import sample_for_layout
from v2_fixtures import digest

from atme.render.v2_split import _observed_split_placements, capture_split
from atme.render.v2_split_identity import split_content_receipts
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


def mask_split_family(portrait=False, root_id="part-1", mode="reveal", *, content="rectangle", mask_offset=0.):
    if content == "code":
        from test_v2_split_code_family import code_split_family
        base, _, action, timeline, *_ = code_split_family(portrait, mode)
    else:
        base, _, action, timeline, *_ = geometry_split_family(portrait, "rectangle", mode)
    raw = base.model_dump(mode="json")
    root = next(obj for obj in raw["objects"] if obj["object_id"] == root_id)
    leaf_id, control_id = root_id + "-ink", root_id + "-mask-definition"
    leaf = deepcopy(root)
    leaf.update(object_id=leaf_id, parent_id=root_id, z_index=0, visible=True, initial_state="visible")
    leaf["transform"].update(position={"x": 0., "y": 0.}, scale_x=1., scale_y=1.,
                             rotation_degrees=0., origin={"x": 0., "y": 0.})
    control = deepcopy(root)
    control.update(object_id=control_id, z_index=99, visible=True, initial_state="visible", anchors=[],
                   style={"stroke": None, "fill": None, "text": None, "effect": None})
    control["geometry"]["bounds"]["width"] /= 2
    control["geometry"]["bounds"]["x"] += mask_offset
    control["transform"]["position"]["x"] = 0.
    for field in ("path_data", "text", "items", "code_payload", "callout_binding", "structured_list"):
        root.pop(field, None)
        control.pop(field, None)
    control.update(object_type="rectangle", path_data=None)
    root.update(object_type="mask", child_ids=[leaf_id], anchors=[], mask_mode="alpha",
                mask_source_object_id=control_id, mask_coordinate_space="parent_local", invert=False,
                feather_px=0, style={"stroke": None, "fill": None, "text": None, "effect": None})
    raw["objects"].extend((leaf, control))
    raw["boards"][0]["object_ids"].extend((leaf_id, control_id))
    layout = ExecutableLayoutV2.model_validate(raw)
    before = sample_for_layout(layout)
    resolved = action.model_dump(mode="json")
    policy = resolved["action"]["split_policy"]
    basis = policy["source_basis"]
    closure = (basis["source_closure"] if root_id == "source" else
               next(row for row in basis["result_closures"] if row["root_id"] == root_id))
    closure["owned_ids"] = sorted((root_id, leaf_id))
    basis["read_dependencies"] = [
        {"kind": "ancestor", "object_ids": [root_id]},
        {"kind": "aperture", "object_ids": [root_id]},
        {"kind": "mask_source", "object_ids": [control_id]},
    ]
    receipts = {row.object_id: row for row in split_content_receipts(layout, before, {})}
    objects = {obj.object_id: obj for obj in layout.objects}
    basis["placements"] = [row.model_dump(mode="json") for row in
        _observed_split_placements(before, objects, set(objects), receipts)]
    for row in policy["correspondences"]:
        row.update(source_content_sha256=receipts["source"].content_sha256,
                   result_content_sha256=receipts[row["result_object_id"]].content_sha256)
    policy["source_basis_sha256"] = digest(basis)
    completion = _split_expected_completion(SplitPolicy.model_validate(policy))
    completion["completion_sha256"] = digest(completion)
    resolved["split_completion_receipt"] = completion
    clock = timeline.model_dump(mode="json")
    clock.update(actions=[resolved], layout_sha256=digest(raw), initial_object_states=[
        {"object_id": row.object_id, "state": row.state, "visible": row.visible,
         "state_version": dict(before.state_versions)[row.object_id]} for row in before.objects])
    return layout, before, ResolvedAction.model_validate(resolved), ResolvedVisualTimelineV2.model_validate(clock)


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("root_id", ["source", "part-1"])
def test_mask_owned_source_or_result_admits_painted_closure_not_definition(portrait, root_id):
    layout, before, action, _timeline = mask_split_family(portrait, root_id)
    capture = capture_split(action, layout, before, {})
    assert root_id + "-ink" in capture.owned_object_ids
    assert root_id + "-mask-definition" in capture.read_dependency_ids
    assert root_id + "-mask-definition" not in capture.owned_object_ids
    inputs = verify_split_paint_inputs(layout, {})
    admission = split_family_admission(root_id, capture, layout, inputs)
    assert admission.family == "compound"
    assert admission.proof_kind == "captured_compound_closure_v1"
    assert admission.mode == ("source_fade" if root_id == "source" else "reveal")


def container_frames(layout, before, action, timeline, inputs, times):
    replay = replay_split(layout, before, (action,), duration=timeline.duration_ms)
    cameras = camera_segments(layout, timeline, replay)
    outputs = {}
    for at in times:
        local = replay.at(at)
        assert local.hierarchy == before.hierarchy  # Split never transfers parents/paint slots.
        roots = {"source", "part-1", "part-2"}
        for original in before.objects:
            if original.object_id not in roots:
                assert local.object(original.object_id) == original
            assert dict(local.state_versions)[original.object_id] == (
                dict(before.state_versions)[original.object_id] +
                int(original.object_id in roots and at >= action.end_ms))
        snapshot = _sample_validated_frame(layout, timeline, replay, cameras, at)
        svg = _compose_validated_svg_frame(layout, timeline, snapshot, {}, split_inputs=inputs)
        png = _rasterize_svg_frame(layout, svg, split_inputs=inputs).png
        result = (svg.svg, png)
        if at in outputs:
            assert result == outputs[at]
        outputs[at] = result
    return outputs


def rgba(png):
    with Image.open(io.BytesIO(png)) as image:
        return image.convert("RGBA").tobytes()


def deny_live_reads_and_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("frozen Split used live files/network")
    original_open = Path.open
    def write_only(path, mode="r", *args, **kwargs):
        if "r" in mode or "+" in mode or not any(flag in mode for flag in ("w", "a", "x")):
            forbidden()
        return original_open(path, mode, *args, **kwargs)
    monkeypatch.setattr(Path, "read_bytes", forbidden)
    monkeypatch.setattr(Path, "open", write_only)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)


def literal_mask_oracle(portrait, root_id, mode, at, inputs, *, content="rectangle"):
    """Literal geometry, phase math and parent-local aperture; no Split renderer."""
    _, _, _, _, _, literal, boxes = geometry_split_family(portrait, "rectangle", mode)
    width, height = (720, 1280) if portrait else (1280, 720)
    fraction, source_alpha = {0: (0, 1), 12: (.5, .8333), 40: (1, 0)}[at]
    colors = json.loads(inputs.style_json)["colors"]
    body = [f'<rect width="{width}" height="{height}" fill="#FAF8F1"/>']
    for key in ("source", "part-1", "part-2"):
        alpha = source_alpha if key == "source" else 1
        if not alpha or key != "source" and fraction == 0:
            continue
        markup, length = literal[key]
        dash = (f' stroke-dasharray="{n(length)} {n(length)}" stroke-dashoffset="{n(length/2)}"'
                if key != "source" and fraction == .5 and mode == "draw" else "")
        color = colors[{"source": "ink", "part-1": "accent", "part-2": "attention"}[key]]
        x, y, w, h = boxes[key]
        if content == "code":
            text = ("src" if key == "source" else
                    ("e\u0301" if key == "part-1" else "x") if at == 12 and mode == "write" else
                    "e\u0301x" if key == "part-1" else "x=y")
            inner = (f'<text x="{n(x)}" y="{n(y+56/3)}" fill="{colors["ink"]}" '
                     f'font-family="JetBrains Mono" font-size="18.6667" font-weight="400" '
                     f'xml:space="preserve">{text}</text>')
        else:
            inner = (f'{markup} fill="none" stroke="{color}" stroke-width="{n(4*2/3)}" '
                     f'stroke-linecap="round" stroke-linejoin="round"{dash}/>')
        if key != "source" and fraction == .5 and mode in {"reveal", "enter"}:
            inner = (f'<defs><clipPath id="reveal-{key}"><rect x="{n(x)}" y="{n(y)}" '
                     f'width="{n(w/2)}" height="{n(h)}"/></clipPath></defs>'
                     f'<g clip-path="url(#reveal-{key})">{inner}</g>')
        if key != "source" and fraction == .5 and mode == "enter":
            inner = f'<g transform="translate(-40 0)">{inner}</g>'
        if key == root_id:
            inner = (f'<defs><mask id="literal-mask" maskUnits="userSpaceOnUse" '
                     f'maskContentUnits="userSpaceOnUse" x="0" y="0" width="{width}" height="{height}" '
                     f'style="mask-type:alpha"><rect x="{n(x)}" y="{n(y)}" width="{n(w/2)}" '
                     f'height="{n(h)}" fill="#ffffff"/></mask></defs>'
                     f'<g mask="url(#literal-mask)">{inner}</g>')
        body.append(f'<g opacity="{alpha}">{inner}</g>')
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">{"".join(body)}</svg>'
    if content == "code":
        from atme.render.style_contracts import PaperInkStyle
        from atme.render.v2_svg import SVGFrame, _rasterize_frozen_svg
        return _rasterize_frozen_svg(SVGFrame(at, width, height, svg),
            PaperInkStyle.model_validate_json(inputs.style_json),
            {name: raw for name, _, raw in inputs.bundle_bytes}).png
    return resvg_py.svg_to_bytes(svg_string=svg, skip_system_fonts=True)


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("root_id", ["source", "part-1"])
@pytest.mark.parametrize("mode", ["reveal", "draw", "enter"])
def test_mask_split_native_pixels_source_fade_construction_and_shuffled_seek(portrait, root_id, mode, tmp_path):
    layout, before, action, timeline = mask_split_family(portrait, root_id, mode)
    capture = capture_split(action, layout, before, {})
    inputs = verify_split_paint_inputs(layout, {})
    # Identity oracle is independently projected from the authored root/leaf.
    objects = {row.object_id: row.model_dump(mode="json") for row in layout.objects}
    leaf_id = root_id + "-ink"
    payload = {key: objects[leaf_id][key] for key in
               ("object_type", "geometry", "style", "anchors", "asset_id", "path_data")}
    leaf_hash = sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    payload = {key: objects[root_id][key] for key in
               ("object_type", "geometry", "style", "anchors", "asset_id", "mask_mode",
                "mask_source_object_id", "mask_coordinate_space", "invert", "feather_px")}
    payload["children"] = [{"object_id": leaf_id, "content_sha256": leaf_hash}]
    expected_hash = sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert split_family_admission(root_id, capture, layout, inputs).content_sha256 == expected_hash
    outputs = container_frames(layout, before, action, timeline, inputs, (40, 0, 12, 40, 12, 0))
    for at in (0, 12, 40):
        assert rgba(outputs[at][1]) == rgba(literal_mask_oracle(portrait, root_id, mode, at, inputs))
        assert 'data-object-id="' + root_id + '-mask-definition"' not in outputs[at][0]
    (tmp_path / f"{root_id}-{mode}-mask.png").write_bytes(outputs[12][1])


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("root_id", ["source", "part-1"])
@pytest.mark.parametrize("mode", ["reveal", "draw", "enter"])
def test_mask_split_all_ms_coverage_and_frozen_offline_pixels(portrait, root_id, mode, monkeypatch):
    layout, before, action, timeline = mask_split_family(portrait, root_id, mode)
    capture = capture_split(action, layout, before, {})
    inputs = verify_split_paint_inputs(layout, {})
    expected = container_frames(layout, before, action, timeline, inputs, (0, 12, 24, 32, 40))
    original = deepcopy(layout.model_dump(mode="json")), repr(capture)
    deny_live_reads_and_network(monkeypatch)
    proof = prove_split_coverage(capture, layout, inputs)
    assert proof.proof_kind == "native_alpha_all_integer_ms_v1"
    assert proof.intervals[0].start_ms == 0 and proof.intervals[-1].end_ms == 40
    assert all(row.painted_root_ids for row in proof.intervals)
    for at, result in container_frames(layout, before, action, timeline, inputs, (40, 12, 0, 32, 24)).items():
        assert result == expected[at]
    assert (layout.model_dump(mode="json"), repr(capture)) == original


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("target", ["part-1-ink", "part-1-mask-definition"])
def test_mask_split_fresh_inputs_cannot_replace_captured_child_or_read_content(portrait, target):
    layout, before, action, _ = mask_split_family(portrait)
    capture = capture_split(action, layout, before, {})
    next(row for row in layout.objects if row.object_id == target).geometry.bounds.width += 1
    inputs = verify_split_paint_inputs(layout, {})
    with pytest.raises(ValueError, match="Split captured.*content differs"):
        split_family_admission("part-1", capture, layout, inputs)


def test_mask_mark_closure_cannot_claim_text_write_construction():
    layout, before, action, _ = mask_split_family(mode="write")
    capture = capture_split(action, layout, before, {})
    with pytest.raises(ValueError, match="Split write is incompatible with geometry construction"):
        split_family_admission("part-1", capture, layout, verify_split_paint_inputs(layout, {}))


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("root_id", ["source", "part-1"])
def test_mask_code_closure_write_has_literal_glyph_pixels_and_offline_coverage(portrait, root_id, monkeypatch):
    layout, before, action, timeline = mask_split_family(portrait, root_id, "write", content="code")
    capture = capture_split(action, layout, before, {})
    inputs = verify_split_paint_inputs(layout, {})
    assert split_family_admission(root_id, capture, layout, inputs).mode == (
        "source_fade" if root_id == "source" else "write")
    expected = container_frames(layout, before, action, timeline, inputs, (0, 12, 40))
    for at in (0, 12, 40):
        assert rgba(expected[at][1]) == rgba(literal_mask_oracle(
            portrait, root_id, "write", at, inputs, content="code"))
    deny_live_reads_and_network(monkeypatch)
    proof = prove_split_coverage(capture, layout, inputs)
    assert all(row.painted_root_ids for row in proof.intervals)
    assert container_frames(layout, before, action, timeline, inputs, (40, 12, 0, 12, 40)) == expected


@pytest.mark.parametrize("portrait", [False, True])
def test_mask_definition_cannot_stand_in_for_zero_painted_source_coverage(portrait):
    layout, before, action, _ = mask_split_family(portrait, "source", mask_offset=120.)
    capture = capture_split(action, layout, before, {})
    inputs = verify_split_paint_inputs(layout, {})
    assert split_family_admission("source", capture, layout, inputs).family == "compound"
    with pytest.raises(ValueError, match="Split.*zero painted coverage.*0"):
        prove_split_coverage(capture, layout, inputs)


@pytest.mark.parametrize("fault", ["state", "transform", "missing_receipt"])
def test_mask_read_capture_cannot_substitute_local_state_or_receipts(fault):
    from dataclasses import replace
    layout, before, action, _ = mask_split_family()
    capture = capture_split(action, layout, before, {})
    key = "part-1-mask-definition"
    if fault == "missing_receipt":
        capture = replace(capture, content_receipts=tuple(row for row in capture.content_receipts if row.object_id != key))
        message = "Split captured paint receipts differ"
    else:
        frame = next(row for row in capture.baseline if row.object_id == key)
        changed = (replace(frame, visible=False) if fault == "state" else replace(frame,
            transform=replace(frame.transform, position=replace(frame.transform.position, x=3.))))
        capture = replace(capture, baseline=tuple(changed if row.object_id == key else row for row in capture.baseline))
        message = "Split captured read state differs"
    with pytest.raises(ValueError, match=message):
        split_family_admission("part-1", capture, layout, verify_split_paint_inputs(layout, {}))
