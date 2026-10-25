"""Task7 text/list matrix uses authored payloads and the single Split adapter."""

import html
import io
import json
import math
from copy import deepcopy
from hashlib import sha256

import pytest
import regex
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
from test_v2_group_hierarchy import grouped_documents
from test_v2_split_action import replay_split
from test_v2_split_families import geometry_split_family
from test_v2_split_identity import sample_for_layout
from v2_fixtures import digest


def pixels(png):
    with Image.open(io.BytesIO(png)) as image:
        return image.convert("RGBA").tobytes()


def literal_text_list_frame(portrait, flat, mode, at_ms, boxes, font_path):
    width, height = (720, 1280) if portrait else (1280, 720)
    body = [f'<rect width="{width}" height="{height}" fill="#FAF8F1"/>']
    for key in ("source", "part-1", "part-2"):
        if key == "source" and at_ms == 40 or key != "source" and at_ms == 0:
            continue
        x, y, w, h = boxes[key]
        lines = [{"source": "S", "part-1": "e\u0301x", "part-2": "xy"}[key]]
        if flat:
            lines.extend(("• One", "• Two"))
        if key != "source" and at_ms == 12 and mode == "write":
            clusters = regex.findall(r"\X", "\n".join(lines))
            lines = "".join(clusters[:math.floor(len(clusters)/2)]).split("\n")
        color = "#2457D6" if key == "part-1" and not flat else "#172033"
        spans = "".join(f'<tspan x="{x:g}" dy="{0 if index == 0 else 28.8:g}">{html.escape(value)}</tspan>'
            for index, value in enumerate(lines))
        inner = (f'<text x="{x:g}" y="{y+64/3:.4f}" fill="{color}" '
            'font-family="Atkinson Hyperlegible" font-weight="400" font-size="21.3333" '
            f'xml:space="preserve">{spans}</text>')
        if key != "source" and at_ms == 12 and mode in {"reveal", "enter"}:
            clip = "literal-"+key
            inner = (f'<defs><clipPath id="{clip}"><rect x="{x:g}" y="{y:g}" width="{w/2:g}" '
                f'height="{h:g}"/></clipPath></defs><g clip-path="url(#{clip})">{inner}</g>')
        transform = ' transform="translate(-40 0)"' if key != "source" and at_ms == 12 and mode == "enter" else ""
        opacity = .8333 if key == "source" and at_ms == 12 else 1
        body.append(f'<g opacity="{opacity}"{transform}>{inner}</g>')
    literal = f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">{"".join(body)}</svg>'
    return bytes(resvg_py.svg_to_bytes(svg_string=literal, font_files=[str(font_path)], skip_system_fonts=True))


def literal_structured_frame(portrait, nested, mode, at_ms, boxes, font_path, nonidentity=False):
    width, height = (720, 1280) if portrait else (1280, 720)
    body = [f'<rect width="{width}" height="{height}" fill="#FAF8F1"/>']
    for key in ("source", "part-1", "part-2"):
        if key == "source" and at_ms == 40 or key != "source" and at_ms == 0:
            continue
        x, y, w, h = boxes[key]
        values = ["S" if key == "source" else "A" if key == "part-1" else "B", "One"]
        if not nested:
            values.append("Two")
        if key != "source" and at_ms == 12 and mode == "write":
            # The approved compound envelope applies its write fraction to
            # each authored leaf; it does not infer a sequential item budget.
            values = ["".join(clusters[:math.floor(len(clusters)/2)]) for value in values
                for clusters in [regex.findall(r"\X", value)]]
        leaves = []
        for index, value in enumerate(values):
            if not value:
                continue
            leaf = (f'<text x="{x:g}" y="{y+40*index+64/3:.4f}" fill="#172033" '
                'font-family="Atkinson Hyperlegible" font-weight="400" font-size="21.3333" '
                f'xml:space="preserve">{html.escape(value)}</text>')
            if index and nonidentity:
                leaf = (f'<g transform="translate(18 8) translate({x:g} {y:g}) '
                    f'scale(1.25 .8) translate({-x:g} {-y:g})">{leaf}</g>')
            leaves.append(leaf)
        inner = "".join(leaves)
        if key != "source" and at_ms == 12 and mode in {"reveal", "enter"}:
            clip = "structured-literal-"+key
            inner = (f'<defs><clipPath id="{clip}"><rect x="{x:g}" y="{y:g}" width="{w/2:g}" '
                f'height="{h:g}"/></clipPath></defs><g clip-path="url(#{clip})">{inner}</g>')
        transform = ' transform="translate(-40 0)"' if key != "source" and at_ms == 12 and mode == "enter" else ""
        opacity = .8333 if key == "source" and at_ms == 12 else 1
        body.append(f'<g opacity="{opacity}"{transform}>{inner}</g>')
    literal = f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">{"".join(body)}</svg>'
    return bytes(resvg_py.svg_to_bytes(svg_string=literal, font_files=[str(font_path)], skip_system_fonts=True))


def text_list_split_family(portrait=False, mode="write", flat=False):
    initial, _, resolved, timeline, _, _, boxes = geometry_split_family(portrait, "rectangle", mode)
    raw, action = initial.model_dump(mode="json"), resolved.model_dump(mode="json")
    hashes, receipts = {}, {}
    for obj in raw["objects"]:
        key = obj["object_id"]
        obj.pop("path_data")
        obj.update(object_type="list" if flat else "text", text={"source": "S", "part-1": "e\u0301x", "part-2": "xy"}[key],
            items=["One", "Two"] if flat else [],
            style={"stroke": None, "fill": None, "text": "text.body" if flat else
                {"source": "text.body", "part-1": "text.accent", "part-2": "text.body"}[key], "effect": None})
        projection = {name: obj[name] for name in
            ("object_type", "geometry", "style", "anchors", "asset_id", "text", "items")}
        encoded = json.dumps(projection, sort_keys=True, separators=(",", ":"))
        hashes[key] = sha256(encoded.encode()).hexdigest()
        receipts[key] = SplitContentReceipt(key, encoded, hashes[key])
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
    return layout, before, resolved, ResolvedVisualTimelineV2.model_validate(raw_timeline), hashes, boxes


def structured_list_split_family(portrait=False, mode="write", nested=False, nonidentity=False):
    original, _, resolved, timeline, _, _ = text_list_split_family(portrait, mode)
    raw, action = original.model_dump(mode="json"), resolved.model_dump(mode="json")
    authored, boxes, closures = [], {}, {}
    group_template = grouped_documents()[0]["objects"][3]
    for original_obj in raw["objects"]:
        key = original_obj["object_id"]
        x, y = original_obj["geometry"]["bounds"]["x"], original_obj["geometry"]["bounds"]["y"]
        boxes[key] = (x, y, 200., 120.)
        root = deepcopy(group_template)
        root.update(object_id=key, beat_id=original_obj["beat_id"], coverage_ids=original_obj["coverage_ids"],
            visible=original_obj["visible"], initial_state=original_obj["initial_state"], z_index=original_obj["z_index"],
            transform=deepcopy(original_obj["transform"]), anchors=[], child_ids=[])
        root["geometry"]["bounds"] = dict(zip(("x", "y", "width", "height"), boxes[key], strict=True))
        rows = []
        values = ("S" if key == "source" else "A" if key == "part-1" else "B", "One") if nested else (
            "S" if key == "source" else "A" if key == "part-1" else "B", "One", "Two")
        for index, text in enumerate(values):
            obj = deepcopy(original_obj)
            child_id = f"{key}-heading" if index == 0 else f"{key}-item-{index}"
            obj.update(object_id=child_id, object_type="list" if index == 0 else "text", text=text,
                items=[], visible=True, initial_state="visible", parent_id=key, z_index=index,
                style={"stroke": None, "fill": None, "text": "text.body", "effect": None},
                anchors=[{"anchor_id": "authored-center", "point": {"x": .5, "y": .5}}],
                transform={"position": {"x": 0., "y": 0.}, "scale_x": 1., "scale_y": 1.,
                    "rotation_degrees": 0., "origin": {"x": .5, "y": .5}})
            obj["geometry"]["bounds"] = {"x": x, "y": y+40*index, "width": 200., "height": 40.}
            if index == 0:
                obj["structured_list"] = {"version": "1.0.0", "container_group_id": key,
                    "item_object_ids": [f"{key}-item-{item}" for item in range(1, len(values))]}
            rows.append(obj)
        root["child_ids"] = [obj["object_id"] for obj in rows]
        if nested:
            subgroup = deepcopy(root)
            subgroup.update(object_id=f"{key}-items", parent_id=key, child_ids=root["child_ids"][1:],
                visible=True, initial_state="visible", z_index=1,
                transform=deepcopy(rows[0]["transform"]))
            if nonidentity:
                subgroup["transform"].update(position={"x": 18., "y": 8.}, scale_x=1.25, scale_y=.8,
                    origin={"x": 0., "y": 0.})
            for obj in rows[1:]:
                obj["parent_id"] = subgroup["object_id"]
            root["child_ids"] = [rows[0]["object_id"], subgroup["object_id"]]
            rows.append(subgroup)
        authored.extend((root, *rows))
        closures[key] = sorted(obj["object_id"] for obj in (root, *rows))
    raw["objects"] = authored
    raw["boards"][0].update(object_ids=[obj["object_id"] for obj in authored], density_limit=len(authored))
    layout = ExecutableLayoutV2.model_validate(raw)
    before = sample_for_layout(layout)
    source_objects = {obj["object_id"]: obj for obj in authored}
    receipts = {}

    def receipt(key):
        if key in receipts:
            return receipts[key]
        obj = source_objects[key]
        projection = {name: obj[name] for name in ("object_type", "geometry", "style", "anchors", "asset_id")}
        if obj["object_type"] == "group":
            projection["children"] = [{"object_id": child, "content_sha256": receipt(child).content_sha256}
                for child in sorted(obj["child_ids"])]
        else:
            projection.update(text=obj["text"], items=obj["items"])
            if "structured_list" in obj:
                projection["structured_list"] = obj["structured_list"]
        encoded = json.dumps(projection, sort_keys=True, separators=(",", ":"))
        receipts[key] = SplitContentReceipt(key, encoded, sha256(encoded.encode()).hexdigest())
        return receipts[key]

    for key in source_objects:
        receipt(key)
    policy = action["action"]["split_policy"]
    policy["source_basis"]["read_dependencies"] = [{"kind": "ancestor", "object_ids":
        sorted(obj["object_id"] for obj in authored if obj["object_type"] == "group")}]
    policy["source_basis"]["source_closure"]["owned_ids"] = closures["source"]
    for row in policy["source_basis"]["result_closures"]:
        row["owned_ids"] = closures[row["root_id"]]
    policy["source_basis"]["placements"] = [row.model_dump(mode="json") for row in
        _observed_split_placements(before, {obj.object_id: obj for obj in layout.objects}, set(source_objects), receipts)]
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
@pytest.mark.parametrize("mode", ["write", "reveal", "enter"])
@pytest.mark.parametrize("flat", [False, True])
def test_text_and_flat_list_split_reuse_exact_identity_and_one_native_seek_path(portrait, mode, flat):
    layout, before, resolved, timeline, hashes, boxes = text_list_split_family(portrait, mode, flat)
    _, _, root = load_bundle()
    capture = capture_split(resolved, layout, before, {})
    inputs = verify_split_paint_inputs(layout, {})
    for key in hashes:
        admission = split_family_admission(key, capture, layout, inputs)
        assert admission.family == "text"
        assert admission.proof_kind == "pinned_font_rendered_alpha_v1"
        assert admission.content_sha256 == hashes[key]
        assert admission.mode == ("source_fade" if key == "source" else mode)
    replay = replay_split(layout, before, (resolved,), duration=timeline.duration_ms)
    cameras = camera_segments(layout, timeline, replay)
    frames = {}
    for at_ms in (0, 12, 40):
        snapshot = _sample_validated_frame(layout, timeline, replay, cameras, at_ms)
        svg = _compose_validated_svg_frame(layout, timeline, snapshot, {}, split_inputs=inputs)
        frames[at_ms] = (svg.svg, _rasterize_svg_frame(layout, svg, split_inputs=inputs).png)
        assert pixels(frames[at_ms][1]) == pixels(literal_text_list_frame(portrait, flat, mode, at_ms, boxes,
            root / "fonts/AtkinsonHyperlegible-Regular.otf"))
    for at_ms in (40, 0, 12, 40, 12, 0):
        snapshot = _sample_validated_frame(layout, timeline, replay, cameras, at_ms)
        svg = _compose_validated_svg_frame(layout, timeline, snapshot, {}, split_inputs=inputs)
        assert (svg.svg, _rasterize_svg_frame(layout, svg, split_inputs=inputs).png) == frames[at_ms]


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("nested", [False, True])
@pytest.mark.parametrize("mode", ["write", "reveal", "enter"])
def test_structured_source_and_result_group_closures_use_exact_real_item_identities(portrait, nested, mode):
    layout, before, resolved, timeline, receipts, boxes = structured_list_split_family(portrait, mode, nested)
    _, _, root = load_bundle()
    capture = capture_split(resolved, layout, before, {})
    inputs = verify_split_paint_inputs(layout, {})
    for key in ("source", "part-1", "part-2"):
        admission = split_family_admission(key, capture, layout, inputs)
        assert admission.family == "compound"
        assert admission.content_sha256 == receipts[key].content_sha256
        assert admission.proof_kind == "captured_compound_closure_v1"
    replay = replay_split(layout, before, (resolved,), timeline.duration_ms)
    complete = replay.at(40)
    for key in receipts.keys() - {"source", "part-1", "part-2"}:
        assert complete.object(key) == before.object(key)
        assert dict(complete.state_versions)[key] == dict(before.state_versions)[key]
    cameras = camera_segments(layout, timeline, replay)
    outputs = {}
    for at_ms in (0, 12, 40):
        snapshot = _sample_validated_frame(layout, timeline, replay, cameras, at_ms)
        svg = _compose_validated_svg_frame(layout, timeline, snapshot, {}, split_inputs=inputs)
        png = _rasterize_svg_frame(layout, svg, split_inputs=inputs).png
        assert pixels(png) == pixels(literal_structured_frame(portrait, nested, mode, at_ms, boxes,
            root / "fonts/AtkinsonHyperlegible-Regular.otf"))
        outputs[at_ms] = (svg.svg, png)
    for at_ms in (40, 12, 0, 12, 40, 0):
        snapshot = _sample_validated_frame(layout, timeline, replay, cameras, at_ms)
        svg = _compose_validated_svg_frame(layout, timeline, snapshot, {}, split_inputs=inputs)
        assert (svg.svg, _rasterize_svg_frame(layout, svg, split_inputs=inputs).png) == outputs[at_ms]


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("mode", ["write", "reveal", "enter"])
@pytest.mark.parametrize("kind", ["text", "flat", "structured", "nested"])
def test_list_family_native_every_integer_ms_coverage(portrait, mode, kind):
    if kind in {"structured", "nested"}:
        layout, before, resolved, _, _, _ = structured_list_split_family(portrait, mode, kind == "nested")
    else:
        layout, before, resolved, _, _, _ = text_list_split_family(portrait, mode, kind == "flat")
    capture = capture_split(resolved, layout, before, {})
    inputs = verify_split_paint_inputs(layout, {})
    original = repr(capture)
    proof = prove_split_coverage(capture, layout, inputs)
    assert proof.critical_times_ms[0] == 0 and proof.critical_times_ms[-1] == 40
    assert proof.intervals[0].start_ms == 0 and proof.intervals[-1].end_ms == 40
    assert all(row.start_ms < row.end_ms and row.painted_root_ids for row in proof.intervals)
    assert proof.intervals[-1].painted_root_ids == ("part-1", "part-2")
    assert repr(capture) == original


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("mode", ["write", "reveal", "enter"])
def test_nested_list_nonidentity_world_pixels_preserve_child_local_frames_and_versions(portrait, mode):
    layout, before, resolved, timeline, receipts, boxes = structured_list_split_family(
        portrait, mode, nested=True, nonidentity=True)
    _, _, root = load_bundle()
    capture = capture_split(resolved, layout, before, {})
    inputs = verify_split_paint_inputs(layout, {})
    for key in ("source", "part-1", "part-2"):
        assert split_family_admission(key, capture, layout, inputs).content_sha256 == receipts[key].content_sha256
    replay = replay_split(layout, before, (resolved,), timeline.duration_ms)
    cameras = camera_segments(layout, timeline, replay)
    outputs = {}
    for at_ms in (0, 12, 40):
        sample = replay.at(at_ms)
        for key in receipts.keys() - {"source", "part-1", "part-2"}:
            assert sample.object(key) == before.object(key)
            assert dict(sample.state_versions)[key] == dict(before.state_versions)[key]
        snapshot = _sample_validated_frame(layout, timeline, replay, cameras, at_ms)
        svg = _compose_validated_svg_frame(layout, timeline, snapshot, {}, split_inputs=inputs)
        png = _rasterize_svg_frame(layout, svg, split_inputs=inputs).png
        assert pixels(png) == pixels(literal_structured_frame(portrait, True, mode, at_ms, boxes,
            root / "fonts/AtkinsonHyperlegible-Regular.otf", nonidentity=True))
        outputs[at_ms] = (svg.svg, png)
    for at_ms in (40, 0, 12, 40, 12, 0):
        snapshot = _sample_validated_frame(layout, timeline, replay, cameras, at_ms)
        svg = _compose_validated_svg_frame(layout, timeline, snapshot, {}, split_inputs=inputs)
        assert (svg.svg, _rasterize_svg_frame(layout, svg, split_inputs=inputs).png) == outputs[at_ms]


@pytest.mark.parametrize("mutation", ["anchor", "item_order"])
def test_valid_structured_identity_mutation_rejects_stale_capture(mutation):
    layout, before, resolved, _, _, _ = structured_list_split_family()
    capture = capture_split(resolved, layout, before, {})
    raw = layout.model_dump(mode="json")
    objects = {obj["object_id"]: obj for obj in raw["objects"]}
    if mutation == "anchor":
        objects["part-1-item-1"]["anchors"][0]["point"]["x"] = .25
    else:
        items = ["part-1-item-2", "part-1-item-1"]
        objects["part-1-heading"]["structured_list"]["item_object_ids"] = items
        objects["part-1"]["child_ids"] = ["part-1-heading", *items]
        for index, key in enumerate(items, start=1):
            objects[key]["z_index"] = index
    changed = ExecutableLayoutV2.model_validate(raw)
    assert all(objects[obj.object_id].get("text") == obj.model_dump(mode="json").get("text")
        for obj in layout.objects)
    inputs = verify_split_paint_inputs(changed, {})
    with pytest.raises(ValueError, match="captured content differs"):
        split_family_admission("part-1", capture, changed, inputs)


@pytest.mark.parametrize("kind", ["text", "flat", "structured"])
def test_list_family_rejects_incompatible_draw_mode_without_fallback(kind):
    if kind == "structured":
        layout, before, resolved, _, _, _ = structured_list_split_family()
    else:
        layout, before, resolved, _, _, _ = text_list_split_family(flat=kind == "flat")
    raw = resolved.model_dump(mode="json")
    for row in raw["action"]["split_policy"]["results"]:
        row["construction"]["mode"] = "draw"
    completion = _split_expected_completion(SplitPolicy.model_validate(raw["action"]["split_policy"]))
    completion["completion_sha256"] = digest(completion)
    raw["split_completion_receipt"] = completion
    capture = capture_split(ResolvedAction.model_validate(raw), layout, before, {})
    inputs = verify_split_paint_inputs(layout, {})
    with pytest.raises(ValueError, match="incompatible with text"):
        split_family_admission("part-1", capture, layout, inputs)


@pytest.mark.parametrize("kind", ["text", "flat", "structured"])
def test_list_family_current_payload_cannot_differ_from_pinned_captured_identity(kind):
    if kind == "structured":
        layout, before, resolved, _, _, _ = structured_list_split_family()
        key = "part-1-item-1"
    else:
        layout, before, resolved, _, _, _ = text_list_split_family(flat=kind == "flat")
        key = "part-1"
    capture = capture_split(resolved, layout, before, {})
    raw = layout.model_dump(mode="json")
    next(obj for obj in raw["objects"] if obj["object_id"] == key)["text"] += "!"
    changed = ExecutableLayoutV2.model_validate(raw)
    inputs = verify_split_paint_inputs(changed, {})
    with pytest.raises(ValueError, match="captured content differs"):
        split_family_admission("part-1", capture, changed, inputs)


def progressed_source_fixture(portrait=False):
    layout, _, resolved, timeline, receipts, boxes = structured_list_split_family(portrait)
    raw = layout.model_dump(mode="json")
    items = ("source-item-1", "source-item-2")
    for obj in raw["objects"]:
        if obj["object_id"] in items:
            obj.update(visible=False, initial_state="hidden")
    layout = ExecutableLayoutV2.model_validate(raw)
    initial = sample_for_layout(layout)
    trigger = {"kind": "absolute", "at_ms": 0}
    split = resolved.model_dump(mode="json")
    template = split["action"]
    keys = ("source_instruction_id", "board_id", "semantic_reason", "fallback", "coverage_id")
    prefix = {"action": {**{key: deepcopy(template[key]) for key in keys},
        "action_id": "prepare-source-list", "verb": "progressive_reveal", "target_ids": list(items),
        "easing": "linear", "expected_state": "hidden", "post_state": "visible", "trigger": trigger,
        "structured_list_policy": {"version": "1.0.0", "list_object_id": "source-heading", "container_group_id": "source",
            "item_object_ids": list(items), "phases": [{"object_id": key, "weight": 1} for key in items],
            "expected_item_state_versions": {key: 1 for key in items}}},
        "start_ms": 0, "end_ms": 4, "resolved_trigger": {"source": trigger, "resolved_at_ms": 0,
            "alignment_anchor_ms": 0, "matched_text": None, "matched_occurrence": None, "confidence": 1, "exact": True}}
    prefix = ResolvedAction.model_validate(prefix)
    before = replay_split(layout, initial, (prefix,), timeline.duration_ms).at(4)
    split.update(start_ms=4, end_ms=44)
    split["action"]["trigger"] = trigger = {"kind": "absolute", "at_ms": 4}
    split["resolved_trigger"].update(source=trigger, resolved_at_ms=4, alignment_anchor_ms=4,
        matched_text=None, matched_occurrence=None)
    policy = split["action"]["split_policy"]
    policy["source_basis"]["placements"] = [row.model_dump(mode="json") for row in _observed_split_placements(
        before, {obj.object_id: obj for obj in layout.objects}, set(receipts), receipts)]
    policy["source_basis_sha256"] = digest(policy["source_basis"])
    completion = _split_expected_completion(SplitPolicy.model_validate(policy))
    completion["completion_sha256"] = digest(completion)
    split["split_completion_receipt"] = completion
    resolved = ResolvedAction.model_validate(split)
    raw_timeline = timeline.model_dump(mode="json")
    raw_timeline["actions"] = [prefix.model_dump(mode="json"), split]
    raw_timeline["coverage"][0]["action_ids"].append(prefix.action.action_id)
    raw_timeline["layout_sha256"] = digest(raw)
    raw_timeline["initial_object_states"] = [{"object_id": row.object_id, "state": row.state,
        "visible": row.visible, "state_version": dict(initial.state_versions)[row.object_id]} for row in initial.objects]
    return layout, initial, before, prefix, resolved, ResolvedVisualTimelineV2.model_validate(raw_timeline), receipts, boxes


@pytest.mark.parametrize("portrait", [False, True])
def test_split_captures_real_source_list_progression_and_preserves_item_versions(portrait):
    layout, initial, before, prefix, resolved, timeline, receipts, _ = progressed_source_fixture(portrait)
    assert all(dict(before.state_versions)[key] == 2 for key in ("source-item-1", "source-item-2"))
    capture = capture_split(resolved, layout, before, {})
    inputs = verify_split_paint_inputs(layout, {})
    assert split_family_admission("source", capture, layout, inputs).content_sha256 == receipts["source"].content_sha256
    replay = replay_split(layout, initial, (prefix, resolved), timeline.duration_ms)
    for key in ("source-item-1", "source-item-2"):
        assert replay.at(44).object(key) == before.object(key)
        assert dict(replay.at(44).state_versions)[key] == 2
