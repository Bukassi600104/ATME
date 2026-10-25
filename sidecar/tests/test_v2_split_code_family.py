"""Task7 code subtype: owning code paint, not a Split-only approximation."""

import html
import io
import json
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256

import pytest
import resvg_py
from atme.render.style_bundle import load_bundle
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
from PIL import Image
from test_v2_code_contract import authored_payload
from test_v2_split_action import replay_split
from test_v2_split_families import geometry_split_family
from test_v2_split_identity import sample_for_layout
from v2_fixtures import digest


def code_split_family(portrait=False, mode="write", tokens=False, *, delayed_ink=False, technical=False, overlap=False):
    initial, _, resolved, timeline, _, _, boxes = geometry_split_family(portrait, "rectangle", mode)
    raw, action = initial.model_dump(mode="json"), resolved.model_dump(mode="json")
    texts = {"source": "src", "part-1": "e\u0301x", "part-2": "x=y"}
    if delayed_ink:
        texts.update({"part-1": "            x", "part-2": "            y"})
    hashes, receipts = {}, {}
    for obj in raw["objects"]:
        key = obj["object_id"]
        obj.pop("path_data")
        payload = authored_payload()
        payload.update(mode="tokens" if tokens else "plain")
        spans = [{"span_id": "plain", "role": "plain", "text": texts[key]}]
        if tokens and not delayed_ink and key != "source":
            spans = ([{"span_id": "accent", "role": "keyword", "text": "e\u0301"},
                      {"span_id": "name", "role": "identifier", "text": "x"}] if key == "part-1" else
                     [{"span_id": "name", "role": "identifier", "text": "x"},
                      {"span_id": "op", "role": "operator", "text": "="},
                      {"span_id": "value", "role": "literal", "text": "y"}])
        payload["lines"] = [{"line_id": "authored-line", "spans": spans}]
        if technical and key != "source":
            texts[key] = "x\t=\nΩ" if key == "part-1" else "e\u0301\nx"
            payload["mode"] = "tokens"
            payload["lines"] = ([{"line_id": "first", "spans": [
                {"span_id": "name", "role": "identifier", "text": "x"},
                {"span_id": "op", "role": "operator", "text": "\t="}]},
                {"line_id": "second", "spans": [{"span_id": "value", "role": "literal", "text": "Ω"}]}]
                if key == "part-1" else [{"line_id": "first", "spans": [
                    {"span_id": "accent", "role": "keyword", "text": "e\u0301"}]},
                    {"line_id": "second", "spans": [{"span_id": "other", "role": "identifier", "text": "x"}]}])
        if overlap and key != "source":
            texts[key] = "e\u0301x"
            payload["mode"] = "tokens"
            payload["lines"] = [{"line_id": "layered", "spans": [{"span_id": "layered",
                "role": "keyword" if key == "part-1" else "comment", "text": texts[key]}]}]
            obj["geometry"]["bounds"]["x"] = boxes["part-1"][0]
            boxes[key] = boxes["part-1"]
        obj.update(object_type="code", text=texts[key], items=[], code_payload=payload,
                   style={"stroke": None, "fill": None, "text": "text.code", "effect": None})
        obj["geometry"]["bounds"]["width"] = 180.
        boxes[key] = (*boxes[key][:2], 180., boxes[key][3])
        projection = {name: obj[name] for name in
                      ("object_type", "geometry", "style", "anchors", "asset_id", "text", "items", "code_payload")}
        canonical = json.dumps(projection, sort_keys=True, separators=(",", ":"))
        hashes[key] = sha256(canonical.encode()).hexdigest()
        receipts[key] = SplitContentReceipt(key, canonical, hashes[key])
    layout = ExecutableLayoutV2.model_validate(raw)
    before = sample_for_layout(layout)
    policy = action["action"]["split_policy"]
    if delayed_ink:
        policy["source_exit"].update(start_tick=0, end_tick=4000)
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
    return layout, before, resolved, ResolvedVisualTimelineV2.model_validate(raw_timeline), hashes, boxes


def pixels(raw):
    with Image.open(io.BytesIO(raw)) as image:
        return image.convert("RGBA").tobytes()


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("mode", ["write", "reveal", "enter"])
@pytest.mark.parametrize("tokens", [False, True])
def test_code_split_native_identity_mode_pixels_and_random_seek(portrait, mode, tokens):
    layout, before, resolved, timeline, hashes, boxes = code_split_family(portrait, mode, tokens)
    capture = capture_split(resolved, layout, before, {})
    inputs = verify_split_paint_inputs(layout, {})
    for key in ("source", "part-1", "part-2"):
        admission = split_family_admission(key, capture, layout, inputs)
        assert admission.family == "text"
        assert admission.proof_kind == "pinned_font_rendered_alpha_v1"
        assert admission.content_sha256 == hashes[key]
        assert admission.mode == ("source_fade" if key == "source" else mode)
    replay = replay_split(layout, before, (resolved,), duration=timeline.duration_ms)
    cameras = camera_segments(layout, timeline, replay)
    width, height = layout.output_profile.width, layout.output_profile.height
    style, _, root = load_bundle()
    outputs = {}
    for at in (0, 12, 40, 12, 0, 40):
        snapshot = _sample_validated_frame(layout, timeline, replay, cameras, at)
        svg = _compose_validated_svg_frame(layout, timeline, snapshot, {}, split_inputs=inputs)
        actual = _rasterize_svg_frame(layout, svg, split_inputs=inputs).png
        if at in outputs:
            assert (svg.svg, actual) == outputs[at]
        outputs[at] = (svg.svg, actual)
    for at, source_alpha in [(0, 1), (12, .8333), (40, 0)]:
        body = [f'<rect width="{width}" height="{height}" fill="{style.colors["paper"]}"/>']
        for key in ("source", "part-1", "part-2"):
            if key == "source" and not source_alpha or key != "source" and at == 0:
                continue
            x, y, w, h = boxes[key]
            baseline = f"{y + 56/3:.4f}".rstrip("0").rstrip(".")
            short = key != "source" and at == 12 and mode == "write"
            if key == "source":
                parts = [(0, "src", "ink")]
            elif key == "part-1":
                parts = [(0, "e\u0301", "accent" if tokens else "ink")]
                if not short:
                    parts.append((11.2, "x", "ink"))
            else:
                parts = [(0, "x", "ink")]
                if not short:
                    parts.extend([(11.2, "=", "accent" if tokens else "ink"),
                                  (22.4, "y", "success" if tokens else "ink")])
            inner = "".join(f'<text x="{x + offset:g}" y="{baseline}" fill="{style.colors[color]}" '
                            f'font-family="JetBrains Mono" font-size="18.6667" font-weight="400" '
                            f'xml:space="preserve">{html.escape(text)}</text>' for offset, text, color in parts)
            if key != "source" and at == 12 and mode in {"reveal", "enter"}:
                clip = "oracle-" + key
                inner = (f'<defs><clipPath id="{clip}"><rect x="{x:g}" y="{y:g}" width="{w/2:g}" '
                         f'height="{h:g}"/></clipPath></defs><g clip-path="url(#{clip})">{inner}</g>')
            transform = ' transform="translate(-40 0)"' if key != "source" and at == 12 and mode == "enter" else ""
            opacity = source_alpha if key == "source" else 1
            body.append(f'<g opacity="{opacity}"{transform}>{inner}</g>')
        literal = f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">{"".join(body)}</svg>'
        expected = bytes(resvg_py.svg_to_bytes(svg_string=literal,
            font_files=[str(root / "code-font-v1/fonts/JetBrainsMono-Regular.ttf")], skip_system_fonts=True))
        assert pixels(outputs[at][1]) == pixels(expected)


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("mode", ["write", "reveal", "enter"])
def test_code_split_native_continuous_coverage(portrait, mode):
    layout, before, resolved, _, _, _ = code_split_family(portrait, mode, True)
    capture = capture_split(resolved, layout, before, {})
    inputs = verify_split_paint_inputs(layout, {})
    immutable = repr(capture)
    proof = prove_split_coverage(capture, layout, inputs)
    assert proof.critical_times_ms[0] == 0 and proof.critical_times_ms[-1] == 40
    assert proof.intervals[0].start_ms == 0 and proof.intervals[-1].end_ms == 40
    assert all(row.start_ms < row.end_ms and row.painted_root_ids for row in proof.intervals)
    assert proof.intervals[-1].painted_root_ids == ("part-1", "part-2")
    assert repr(capture) == immutable


def test_code_split_write_whitespace_cannot_hide_a_zero_ink_handoff():
    layout, before, resolved, _, _, _ = code_split_family(delayed_ink=True)
    capture = capture_split(resolved, layout, before, {})
    with pytest.raises(ValueError, match="Split has zero painted coverage"):
        prove_split_coverage(capture, layout, verify_split_paint_inputs(layout, {}))


def test_code_split_draw_is_not_a_code_construction_mode():
    layout, before, resolved, _, _, _ = code_split_family(mode="draw")
    capture = capture_split(resolved, layout, before, {})
    with pytest.raises(ValueError, match="Split draw is incompatible with text construction"):
        split_family_admission("part-1", capture, layout, verify_split_paint_inputs(layout, {}))


@pytest.mark.parametrize("mutation", ["span_role", "tab_size", "line_id"])
def test_code_split_fresh_native_paint_cannot_replace_captured_authored_content(mutation):
    layout, before, resolved, _, _, _ = code_split_family(tokens=True)
    capture = capture_split(resolved, layout, before, {})
    raw = deepcopy(layout.model_dump(mode="json"))
    payload = raw["objects"][1]["code_payload"]
    if mutation == "span_role":
        payload["lines"][0]["spans"][0]["role"] = "comment"
    elif mutation == "tab_size":
        payload["tab_size"] = 8
    else:
        payload["lines"][0]["line_id"] = "different-line"
    changed = ExecutableLayoutV2.model_validate(raw)
    with pytest.raises(ValueError, match="Split captured content differs"):
        split_family_admission("part-1", capture, changed, verify_split_paint_inputs(changed, {}))


def code_split_frames(layout, before, resolved, timeline, inputs, times):
    replay = replay_split(layout, before, (resolved,), duration=timeline.duration_ms)
    cameras = camera_segments(layout, timeline, replay)
    result = {}
    for at in times:
        frame = _compose_validated_svg_frame(layout, timeline,
            _sample_validated_frame(layout, timeline, replay, cameras, at), {}, split_inputs=inputs)
        value = (frame.svg, _rasterize_svg_frame(layout, frame, split_inputs=inputs).png)
        if at in result:
            assert value == result[at]
        result[at] = value
    return result


def literal_code(layout, parts, *, world_transform=None):
    style, _, root = load_bundle()
    width, height = layout.output_profile.width, layout.output_profile.height
    body = [f'<rect width="{width}" height="{height}" fill="{style.colors["paper"]}"/>']
    glyphs = []
    for x, y, text, color, opacity in parts:
        glyphs.append(f'<text x="{x:g}" y="{y:.4f}" fill="{style.colors[color]}" opacity="{opacity}" '
                    f'font-family="JetBrains Mono" font-size="18.6667" font-weight="400" '
                    f'xml:space="preserve">{html.escape(text)}</text>')
    ink = "".join(glyphs)
    body.append(f'<g transform="{world_transform}">{ink}</g>' if world_transform else ink)
    literal = f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">{"".join(body)}</svg>'
    return bytes(resvg_py.svg_to_bytes(svg_string=literal,
        font_files=[str(root / "code-font-v1/fonts/JetBrainsMono-Regular.ttf")], skip_system_fonts=True))


@pytest.mark.parametrize("portrait", [False, True])
def test_split_code_tabs_between_roles_and_multiline_unicode_have_literal_pixels(portrait):
    layout, before, resolved, timeline, _, boxes = code_split_family(portrait, technical=True)
    capture = capture_split(resolved, layout, before, {})
    inputs = verify_split_paint_inputs(layout, {})
    split_family_admission("part-1", capture, layout, inputs)
    outputs = code_split_frames(layout, before, resolved, timeline, inputs, (12, 40, 12, 40))
    source_x, source_y, _, _ = boxes["source"]
    x, y, _, _ = boxes["part-1"]
    second_x, second_y, _, _ = boxes["part-2"]
    for at in (12, 40):
        parts = [(x, y + 56/3, "x", "ink", 1), (second_x, second_y + 56/3, "e\u0301", "accent", 1)]
        if at == 12:
            parts.insert(0, (source_x, source_y + 56/3, "src", "ink", .8333))
        else:
            parts.extend([(x + 44.8, y + 56/3, "=", "accent", 1),
                          (x, y + 56/3 + 25.2, "Ω", "success", 1),
                          (second_x, second_y + 56/3 + 25.2, "x", "ink", 1)])
        assert pixels(outputs[at][1]) == pixels(literal_code(layout, parts))


@pytest.mark.parametrize("portrait", [False, True])
def test_split_code_semantic_order_cannot_reverse_native_overlapping_paint(portrait):
    import xml.etree.ElementTree as ET

    layout, before, resolved, timeline, _, boxes = code_split_family(portrait, overlap=True)
    capture = capture_split(resolved, layout, before, {})
    inputs = verify_split_paint_inputs(layout, {})
    split_family_admission("part-2", capture, layout, inputs)
    outputs = code_split_frames(layout, before, resolved, timeline, inputs, (40, 0, 40))
    order = [node.attrib["data-object-id"] for node in ET.fromstring(outputs[40][0]).iter()
             if "data-object-id" in node.attrib]
    assert order == ["part-1", "part-2"]
    assert [row.object_id for row in resolved.action.split_policy.results] == ["part-2", "part-1"]
    x, y, _, _ = boxes["part-1"]
    # Antialiased edges retain the lower layer; both original colors/order
    # belong in the independent oracle, not only the opaque top glyph body.
    assert pixels(outputs[40][1]) == pixels(literal_code(layout, [
        (x, y + 56/3, "e\u0301x", "accent", 1), (x, y + 56/3, "e\u0301x", "muted", 1)]))


@pytest.mark.parametrize("portrait", [False, True])
def test_split_code_authored_movement_after_write_has_literal_pixels(portrait):
    layout, before, resolved, timeline, _, boxes = code_split_family(portrait)
    raw = resolved.model_dump(mode="json")
    result = next(row for row in raw["action"]["split_policy"]["results"] if row["object_id"] == "part-1")
    original = result["destination"]
    moved = {**original, "position": {"x": 60., "y": 0.}}
    result.update(destination=moved, movement={"phase": {"start_tick": 6000, "end_tick": 10000,
        "easing": "linear"}, "from_transform": original, "destination": moved})
    completion = _split_expected_completion(SplitPolicy.model_validate(raw["action"]["split_policy"]))
    completion["completion_sha256"] = digest(completion)
    raw["split_completion_receipt"] = completion
    resolved = ResolvedAction.model_validate(raw)
    timeline = timeline.model_copy(update={"actions": [resolved]})
    capture = capture_split(resolved, layout, before, {})
    inputs = verify_split_paint_inputs(layout, {})
    proof = prove_split_coverage(capture, layout, inputs)
    assert 24 in proof.critical_times_ms
    outputs = code_split_frames(layout, before, resolved, timeline, inputs, (24, 32, 40, 24, 40))
    for at, dx in [(24, 0), (32, 30), (40, 60)]:
        first_x, first_y, _, _ = boxes["part-1"]
        second_x, second_y, _, _ = boxes["part-2"]
        parts = [(first_x + dx, first_y + 56/3, "e\u0301x", "ink", 1),
                 (second_x, second_y + 56/3, "x=y", "ink", 1)]
        if at == 24:
            source_x, source_y, _, _ = boxes["source"]
            parts.insert(0, (source_x, source_y + 56/3, "src", "ink", .3333))
        assert pixels(outputs[at][1]) == pixels(literal_code(layout, parts))


@pytest.mark.parametrize("fault", ["manifest", "font", "license", "missing_evidence", "forged_evidence"])
def test_split_code_frozen_resource_and_rehashed_paint_tamper_cannot_attest_code(fault):
    layout, before, resolved, _, _, _ = code_split_family(tokens=True)
    capture = capture_split(resolved, layout, before, {})
    inputs = verify_split_paint_inputs(layout, {})
    if fault in {"manifest", "font", "license"}:
        suffix = {"manifest": "code-font.json", "font": "JetBrainsMono-Regular.ttf",
                  "license": "OFL-JetBrainsMono.txt"}[fault]
        rows = tuple((name, checksum, data + b"changed") if name.endswith(suffix) else (name, checksum, data)
                     for name, checksum, data in inputs.bundle_bytes)
        forged = replace(inputs, bundle_bytes=rows)
        expected = "Split frozen bundle row is invalid"
    else:
        rows = [json.loads(row) for row in inputs.paint_evidence]
        if fault == "missing_evidence":
            rows = [row for row in rows if row.get("object_id") != "part-1"]
        else:
            next(row for row in rows if row.get("object_id") == "part-1")["paint"]["font_sha256"] = "0" * 64
        manifest = json.loads(inputs.manifest_json)
        manifest["paint_evidence"] = rows
        encoded = json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        forged = replace(inputs, paint_evidence=tuple(json.dumps(row, sort_keys=True, separators=(",", ":"),
            ensure_ascii=False) for row in rows), manifest_json=encoded, inputs_sha256=sha256(encoded.encode()).hexdigest())
        expected = "Split frozen paint binding differs"
    with pytest.raises(ValueError, match=expected):
        split_family_admission("part-1", capture, layout, forged)


def nested_code_split(portrait, kind, mode, *, source_compound=False, ancestry=False):
    layout, _, resolved, timeline, _, boxes = code_split_family(portrait, mode)
    raw, action = layout.model_dump(mode="json"), resolved.model_dump(mode="json")
    policy = action["action"]["split_policy"]
    empty_style = {"stroke": None, "fill": None, "text": None, "effect": None}
    if kind in {"group", "clip"}:
        root_key = "source" if source_compound else "part-1"
        root = next(obj for obj in raw["objects"] if obj["object_id"] == root_key)
        child = deepcopy(root)
        child.update(object_id="code-child", parent_id=root_key, initial_state="visible", visible=True, z_index=0)
        child["transform"]["position"] = {"x": 0., "y": 0.}
        for name in ("text", "items", "code_payload"):
            root.pop(name)
        root.update(object_type=kind, child_ids=["code-child"], style=empty_style)
        if kind == "clip":
            root["geometry"]["bounds"]["width"] = 12.
        raw["objects"].append(child)
        raw["boards"][0]["object_ids"].append("code-child")
        closure = (policy["source_basis"]["source_closure"] if source_compound else
                   next(row for row in policy["source_basis"]["result_closures"] if row["root_id"] == root_key))
        closure["owned_ids"] = ["code-child", root_key]
        policy["source_basis"]["read_dependencies"] = [{"kind": "ancestor", "object_ids": [root_key]}]
        if kind == "clip":
            policy["source_basis"]["read_dependencies"].append({"kind": "aperture", "object_ids": [root_key]})
    else:
        ancestor = deepcopy(raw["objects"][0])
        for name in ("text", "items", "code_payload"):
            ancestor.pop(name)
        ancestor.update(object_id="code-mask", object_type="mask", mask_mode="alpha",
            mask_source_object_id="mask-source", mask_coordinate_space="parent_local", invert=False,
            feather_px=0, child_ids=["source", "part-1", "part-2"], anchors=[], style=empty_style,
            initial_state="visible", visible=True, opacity=1.)
        ancestor["transform"]["position"] = {"x": 0., "y": 0.}
        ancestor["geometry"]["bounds"] = {"x": 50., "y": 0., "width": 140. if portrait else 430., "height": 650.}
        mask_source = {key: deepcopy(value) for key, value in ancestor.items()
                       if key not in {"mask_mode", "mask_source_object_id", "mask_coordinate_space",
                                      "invert", "feather_px", "child_ids"}}
        mask_source.update(object_id="mask-source", object_type="rectangle", path_data=None, z_index=9)
        for obj in raw["objects"]:
            obj["parent_id"] = "code-mask"
        raw["objects"].extend([ancestor, mask_source])
        raw["boards"][0]["object_ids"].extend(["code-mask", "mask-source"])
        policy["source_basis"]["read_dependencies"] = [
            {"kind": "ancestor", "object_ids": ["code-mask"]},
            {"kind": "aperture", "object_ids": ["code-mask"]},
            {"kind": "mask_source", "object_ids": ["mask-source"]}]
    if ancestry:
        for obj in raw["objects"]:
            if obj["parent_id"] is None:
                obj["parent_id"] = "code-stage"
        stage = deepcopy(next(obj for obj in raw["objects"] if obj["object_id"] == "source"))
        for name in ("text", "items", "code_payload"):
            stage.pop(name, None)
        stage.update(object_id="code-stage", object_type="group", parent_id="outer-stage",
            child_ids=["source", "part-1", "part-2"], initial_state="visible", visible=True,
            opacity=1., anchors=[], style=empty_style)
        stage["geometry"]["bounds"] = {"x": 0., "y": 0.,
            "width": float(layout.output_profile.width), "height": float(layout.output_profile.height)}
        stage["transform"].update(position={"x": 30., "y": 10.}, scale_x=1.25, scale_y=.8,
                                   rotation_degrees=0., origin={"x": 0., "y": 0.})
        outer = deepcopy(stage)
        outer.update(object_id="outer-stage", parent_id=None, child_ids=["code-stage"])
        outer["transform"].update(position={"x": 10., "y": 20.}, scale_x=1., scale_y=1.)
        raw["objects"].extend([stage, outer])
        raw["boards"][0]["object_ids"].extend(["code-stage", "outer-stage"])
        dependency = next(row for row in policy["source_basis"]["read_dependencies"] if row["kind"] == "ancestor")
        dependency["object_ids"] = sorted({*dependency["object_ids"], "code-stage", "outer-stage"})
    layout = ExecutableLayoutV2.model_validate(raw)
    # Independently specified composite identity: authored local fields plus
    # sorted child IDs/content hashes, never a runtime-generated receipt oracle.
    authored = {obj["object_id"]: obj for obj in raw["objects"]}
    receipts = {}

    def receipt(key):
        if key in receipts:
            return receipts[key]
        obj = authored[key]
        payload = {name: obj[name] for name in ("object_type", "geometry", "style", "anchors", "asset_id")}
        if obj["object_type"] == "code":
            payload.update({name: obj[name] for name in ("text", "items", "code_payload")})
        elif obj["object_type"] == "rectangle":
            payload["path_data"] = obj["path_data"]
        else:
            payload["children"] = [{"object_id": child, "content_sha256": receipt(child).content_sha256}
                                   for child in sorted(obj["child_ids"])]
            if obj["object_type"] == "mask":
                payload.update({name: obj[name] for name in ("mask_mode", "mask_source_object_id",
                    "mask_coordinate_space", "invert", "feather_px")})
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        receipts[key] = SplitContentReceipt(key, encoded, sha256(encoded.encode()).hexdigest())
        return receipts[key]

    for key in authored:
        receipt(key)
    before = sample_for_layout(layout)
    policy["source_basis"]["placements"] = [row.model_dump(mode="json") for row in
        _observed_split_placements(before, {obj.object_id: obj for obj in layout.objects}, set(authored), receipts)]
    for row in policy["correspondences"]:
        row.update(source_content_sha256=receipts["source"].content_sha256,
                   result_content_sha256=receipts[row["result_object_id"]].content_sha256)
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
    return layout, before, resolved, ResolvedVisualTimelineV2.model_validate(raw_timeline), receipts, boxes


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("kind", ["group", "clip", "mask"])
@pytest.mark.parametrize("mode", ["write", "reveal", "enter"])
def test_code_split_owning_root_and_read_aperture_pixels_and_every_ms_coverage(portrait, kind, mode):
    layout, before, resolved, timeline, receipts, boxes = nested_code_split(portrait, kind, mode)
    capture = capture_split(resolved, layout, before, {})
    inputs = verify_split_paint_inputs(layout, {})
    admission = split_family_admission("part-1", capture, layout, inputs)
    assert admission.family == ("text" if kind == "mask" else "compound")
    assert admission.content_sha256 == receipts["part-1"].content_sha256
    if kind != "mask":
        assert split_family_admission("code-child", capture, layout, inputs).family == "text"
    proof = prove_split_coverage(capture, layout, inputs)
    assert proof.intervals[-1].painted_root_ids == ("part-1", "part-2")
    outputs = code_split_frames(layout, before, resolved, timeline, inputs, (12, 40, 12, 40))
    width, height = layout.output_profile.width, layout.output_profile.height
    style, _, font_root = load_bundle()
    for at in (12, 40):
        body = []
        for key in ("source", "part-1", "part-2"):
            if key == "source" and at == 40:
                continue
            x, y, w, h = boxes[key]
            text = "src" if key == "source" else ("e\u0301" if key == "part-1" else "x") if at == 12 and mode == "write" else (
                "e\u0301x" if key == "part-1" else "x=y")
            inner = (f'<text x="{x:g}" y="{y + 56/3:.4f}" fill="{style.colors["ink"]}" '
                f'font-family="JetBrains Mono" font-size="18.6667" font-weight="400" '
                f'xml:space="preserve">{text}</text>')
            if kind == "clip" and key == "part-1":
                inner = (f'<defs><clipPath id="owned"><rect x="{x:g}" y="{y:g}" width="12" height="{h:g}"/>'
                         f'</clipPath></defs><g clip-path="url(#owned)">{inner}</g>')
            if key != "source" and at == 12 and mode in {"reveal", "enter"}:
                width_fraction = 6 if kind == "clip" and key == "part-1" else w/2
                clip = "oracle-" + key
                inner = (f'<defs><clipPath id="{clip}"><rect x="{x:g}" y="{y:g}" width="{width_fraction:g}" '
                         f'height="{h:g}"/></clipPath></defs><g clip-path="url(#{clip})">{inner}</g>')
            transform = ' transform="translate(-40 0)"' if key != "source" and at == 12 and mode == "enter" else ""
            opacity = .8333 if key == "source" else 1
            body.append(f'<g opacity="{opacity}"{transform}>{inner}</g>')
        inner = "".join(body)
        if kind == "mask":
            inner = (f'<defs><mask id="oracle-mask" maskUnits="userSpaceOnUse" maskContentUnits="userSpaceOnUse" '
                     f'style="mask-type:alpha"><rect x="50" y="0" width="{140 if portrait else 430}" '
                     f'height="650" fill="white"/></mask></defs><g mask="url(#oracle-mask)">{inner}</g>')
        literal = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">'
            f'<rect width="{width}" height="{height}" fill="{style.colors["paper"]}"/>{inner}</svg>')
        expected = bytes(resvg_py.svg_to_bytes(svg_string=literal,
            font_files=[str(font_root / "code-font-v1/fonts/JetBrainsMono-Regular.ttf")], skip_system_fonts=True))
        assert pixels(outputs[at][1]) == pixels(expected)


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("source_compound,ancestry", [(True, False), (False, True), (True, True)])
def test_code_split_compound_source_fade_and_nested_nonidentity_ancestry(portrait, source_compound, ancestry):
    layout, before, resolved, timeline, receipts, boxes = nested_code_split(portrait, "group", "write",
        source_compound=source_compound, ancestry=ancestry)
    capture = capture_split(resolved, layout, before, {})
    inputs = verify_split_paint_inputs(layout, {})
    source = split_family_admission("source", capture, layout, inputs)
    assert source.family == ("compound" if source_compound else "text")
    assert source.mode == "source_fade" and source.content_sha256 == receipts["source"].content_sha256
    if ancestry:
        assert {"code-stage", "outer-stage"}.issubset(capture.read_dependency_ids)
        basis = json.loads(capture.basis_json)
        child = next(row for row in basis["placements"] if row["object_id"] == "code-child")
        assert child["world_matrix"] == [1.25, 0., 0., .8, 40., 30.]
    proof = prove_split_coverage(capture, layout, inputs)
    assert proof.intervals[-1].painted_root_ids == ("part-1", "part-2")
    outputs = code_split_frames(layout, before, resolved, timeline, inputs, (0, 12, 40, 12, 0, 40))
    for at, opacity in [(0, 1), (12, .8333), (40, 0)]:
        parts = []
        if opacity:
            x, y, _, _ = boxes["source"]
            parts.append((x, y + 56/3, "src", "ink", opacity))
        if at:
            first_x, first_y, _, _ = boxes["part-1"]
            second_x, second_y, _, _ = boxes["part-2"]
            parts.extend([(first_x, first_y + 56/3, "e\u0301" if at == 12 else "e\u0301x", "ink", 1),
                          (second_x, second_y + 56/3, "x" if at == 12 else "x=y", "ink", 1)])
        assert pixels(outputs[at][1]) == pixels(literal_code(layout, parts,
            world_transform="matrix(1.25 0 0 .8 40 30)" if ancestry else None))
    if source_compound:
        replay = replay_split(layout, before, (resolved,), duration=timeline.duration_ms)
        assert replay.at(40).object("code-child") == before.object("code-child")
        assert dict(replay.at(40).state_versions)["code-child"] == 1
        assert not replay.at(40).object("source").visible
