"""Task7 Callout evidence uses the owning body; relationship gates stay separate."""

import html
import io
import json
from copy import deepcopy
from hashlib import sha256

import pytest
import resvg_py
from atme.render.v2_split_paint import _split_glyph_evidence
from atme.store.contracts_v2 import ExecutableLayoutV2
from PIL import Image
from test_v2_callout_compositor import compositor_documents
from test_v2_callout_native import native_inputs
from v2_fixtures import digest


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("boxed", [False, True])
def test_callout_split_evidence_binds_exact_body_binding_and_literal_native_alpha(portrait, boxed):
    obj, style, root, font, files, width, height = native_inputs(portrait, boxed)
    # Local native facts retain the independently authored primitive placement.
    # They do not assert captured relationship or full-frame admission.
    layout = ExecutableLayoutV2.model_validate(compositor_documents(portrait, boxed)[0])
    resources = style, None, files, {}
    evidence = _split_glyph_evidence(obj, layout, resources)
    x, y = (90, 280) if portrait else (80, 200)
    color, paper = style.colors["ink"], style.colors["paper"]
    body_box = (f'<rect x="{x}" y="{y}" width="320" height="100" rx="8" fill="{paper}" '
        f'stroke="{color}" stroke-width="2.6667" stroke-linecap="round" stroke-linejoin="round"/>') if boxed else ""
    text_x = "100.6667" if portrait and boxed else "90.6667" if boxed else str(x)
    baseline = "312" if portrait and boxed else "232" if boxed else "301.3333" if portrait else "221.3333"
    text = (f'<text x="{text_x}" y="{baseline}" fill="{color}" font-family="Atkinson Hyperlegible" '
        f'font-size="21.3333" font-weight="400" xml:space="preserve">A\u0301B</text>')
    assert evidence["callout_binding"] == obj.callout_binding.model_dump(mode="json")
    assert evidence["font_sha256"] == sha256(files[font.file]).hexdigest()
    for inner, prefix in ((body_box + text, "body"), (text, "glyph")):
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
            f'viewBox="{x} {y} 320 100">{inner}</svg>')
        png = bytes(resvg_py.svg_to_bytes(svg_string=svg, font_files=[str(root / font.file)],
            skip_system_fonts=True))
        with Image.open(io.BytesIO(png)) as image:
            alpha = image.convert("RGBA").getchannel("A")
            assert evidence[f"{prefix}_alpha_bounds"] == alpha.getbbox()
            assert evidence[f"{prefix}_alpha_size"] == alpha.size
            assert evidence[f"{prefix}_alpha_sha256"] == sha256(alpha.tobytes()).hexdigest()
    assert "pointer_svg" not in evidence and "leader_alpha_sha256" not in evidence


@pytest.mark.parametrize("boxed", [False, True])
def test_callout_split_evidence_requires_actual_glyph_ink_not_just_box_pixels(boxed):
    obj, style, _, _, files, _, _ = native_inputs(boxed=boxed)
    obj.text = "\u200b"
    layout = ExecutableLayoutV2.model_validate(compositor_documents(False, boxed)[0])
    with pytest.raises(ValueError, match="Callout.*no painted glyphs"):
        _split_glyph_evidence(obj, layout, (style, None, files, {}))


def test_callout_split_local_evidence_reads_only_verified_frozen_font_bytes(monkeypatch):
    from pathlib import Path

    obj, style, _, _, files, _, _ = native_inputs(boxed=True)
    layout = ExecutableLayoutV2.model_validate(compositor_documents(False, True)[0])
    expected = _split_glyph_evidence(obj, layout, (style, None, files, {}))

    def no_original(path):
        raise AssertionError(f"Callout evidence reopened source {path}")

    monkeypatch.setattr(Path, "read_bytes", no_original)
    assert _split_glyph_evidence(obj, layout, (style, None, files, {})) == expected


def callout_split_fixture(portrait=False, mode="write", boxed=False, source_state="removed", target_group=False,
                          leader_parent=False):
    from atme.render.v2_split import _observed_split_placements
    from atme.render.v2_split_identity import (
        SplitContentReceipt,
        split_basis_digest,
        split_content_receipts,
    )
    from atme.store.contracts_v2 import (
        ResolvedAction,
        ResolvedVisualTimelineV2,
        SplitBasis,
        SplitPolicy,
        _split_expected_completion,
        _split_packet_digest,
    )
    from test_v2_split_action import replay_split
    from test_v2_split_code_family import code_split_family
    from test_v2_split_identity import sample_for_layout
    from test_v2_timeline_replay import resolved as resolve

    original, _, split, timeline, _, _ = code_split_family(portrait, mode)
    raw, action = original.model_dump(mode="json"), split.model_dump(mode="json")
    texts = {"source": "src", "part-1": "A\u0301B", "part-2": "x=y"}
    hashes, receipts = {}, {}
    pointer_template = compositor_documents(portrait)[0]["objects"][2]
    for obj in list(raw["objects"]):
        key = obj["object_id"]
        obj.pop("code_payload")
        obj.update(object_type="callout", text=texts[key], anchors=[
            {"anchor_id": "center", "point": {"x": .5, "y": .5}}],
            style={"stroke": "ink.primary" if boxed else None, "fill": "surface.paper" if boxed else None,
                   "text": "text.body", "effect": None}, callout_binding={
                "version": "1.0.0", "leader_connector_id": f"leader-{key}", "callout_anchor_id": "center",
                "target_object_id": "callout-target", "target_anchor_id": "center"})
        obj["geometry"]["corner_radius"] = 8. if boxed else None
        pointer = deepcopy(pointer_template)
        pointer.update(object_id=f"leader-{key}", source_object_id=key, destination_object_id="callout-target",
            z_index=20+len(raw["objects"]), visible=obj["visible"], initial_state=obj["initial_state"])
        pointer["geometry"]["bounds"] = {"x": 0., "y": 0., "width": float(original.output_profile.width),
            "height": float(original.output_profile.height)}
        raw["objects"].append(pointer)
        projection = {name: obj[name] for name in ("object_type", "geometry", "style", "anchors", "asset_id",
            "text", "items", "callout_binding")}
        encoded = json.dumps(projection, sort_keys=True, separators=(",", ":"))
        hashes[key] = sha256(encoded.encode()).hexdigest()
        receipts[key] = SplitContentReceipt(key, encoded, hashes[key])
    target = deepcopy(compositor_documents(portrait)[0]["objects"][0])
    target.update(object_id="callout-target", z_index=-10, visible=True, initial_state="visible")
    target["geometry"]["bounds"] = {"x": 300. if portrait else 200., "y": 1000. if portrait else 500.,
        "width": 80., "height": 80.}
    raw["objects"].append(target)
    if target_group:
        from test_v2_group_hierarchy import grouped_documents

        shell = deepcopy(grouped_documents()[0]["objects"][3])
        shell.update(object_id="target-stage", child_ids=["callout-target"], z_index=-20)
        target["parent_id"] = "target-stage"
        raw["objects"].append(shell)
    if leader_parent:
        from test_v2_group_hierarchy import grouped_documents

        shell = deepcopy(grouped_documents()[0]["objects"][3])
        shell.update(object_id="leader-stage", child_ids=["leader-source", "leader-part-1", "leader-part-2"], z_index=100)
        shell["transform"].update(position={"x": 15., "y": 5.}, scale_x=1.1, scale_y=.9,
                                  rotation_degrees=3., origin={"x": 0., "y": 0.})
        for obj in raw["objects"]:
            if obj["object_id"] in shell["child_ids"]:
                obj["parent_id"] = shell["object_id"]
        raw["objects"].append(shell)
    raw["boards"][0]["object_ids"] = [obj["object_id"] for obj in raw["objects"]]
    raw["boards"][0]["density_limit"] = len(raw["objects"])
    layout = ExecutableLayoutV2.model_validate(raw)
    initial = sample_for_layout(layout)
    prefix = []
    if source_state != "live":
        exit_raw = {name: deepcopy(value) for name, value in action["action"].items()
            if name not in {"split_policy", "container_id"}}
        exit_raw.update(action_id="source-pointer-exit", verb="exit", target_ids=["leader-source"],
            expected_state="visible", post_state="removed")
        prefix.append(resolve(exit_raw, 0, 1))
    # This is an actual ordinary exit commit from the existing clock, not a
    # model_copy which invents a removed pointer frame.
    prior = replay_split(layout, initial, tuple(prefix), timeline.duration_ms)
    before = prior.at(1)
    assert before.object("leader-source").state == ("visible" if source_state == "live" else "removed")
    actual = {row.object_id: row for row in split_content_receipts(layout, before, {})}
    for key, receipt in receipts.items():
        assert actual[key] == receipt
    actual.update(receipts)
    policy = action["action"]["split_policy"]
    stages = sorted((["target-stage"] if target_group else []) + (["leader-stage"] if leader_parent else []))
    policy["source_basis"]["read_dependencies"] = ([{"kind": "ancestor", "object_ids": stages}]
        if stages else []) + [{"kind": "connector_anchor",
        "object_ids": sorted(obj.object_id for obj in layout.objects if obj.object_id not in stages)}]
    policy["source_basis"]["placements"] = [row.model_dump(mode="json") for row in _observed_split_placements(
        before, {obj.object_id: obj for obj in layout.objects}, set(actual), actual)]
    for row in policy["correspondences"]:
        row.update(source_content_sha256=hashes["source"], result_content_sha256=hashes[row["result_object_id"]])
    policy["source_basis_sha256"] = split_basis_digest(SplitBasis.model_validate(policy["source_basis"]))
    trigger = {"kind": "absolute", "at_ms": 1}
    action["action"]["trigger"] = trigger
    action.update(start_ms=1, end_ms=41)
    action["resolved_trigger"].update(source=trigger, alignment_anchor_ms=1, resolved_at_ms=1,
        matched_text=None, matched_occurrence=None, confidence=1., exact=True)
    completion = _split_expected_completion(SplitPolicy.model_validate(policy))
    completion["completion_sha256"] = _split_packet_digest(completion)
    action["split_completion_receipt"] = completion
    resolved = ResolvedAction.model_validate(action)
    raw_timeline = timeline.model_dump(mode="json")
    raw_timeline["actions"] = [row.model_dump(mode="json") for row in prefix] + [action]
    raw_timeline["coverage"][0]["action_ids"] = [row["action"]["action_id"] for row in raw_timeline["actions"]]
    raw_timeline["layout_sha256"] = digest(raw)
    raw_timeline["initial_object_states"] = [{"object_id": row.object_id, "state": row.state,
        "visible": row.visible, "state_version": 1} for row in initial.objects]
    return layout, initial, before, tuple(prefix), resolved, ResolvedVisualTimelineV2.model_validate(raw_timeline), hashes


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("mode", ["write", "reveal", "enter"])
@pytest.mark.parametrize("boxed", [False, True])
def test_callout_body_adapter_requires_real_prior_exit_and_preserves_separate_hidden_pointers(portrait, mode, boxed):
    from atme.render.v2_split import capture_split
    from atme.render.v2_split_paint import (
        split_family_admission,
        verify_split_paint_inputs,
    )
    from atme.render.v2_state import _sample_validated_frame, camera_segments
    from atme.render.v2_svg import _compose_validated_svg_frame, _rasterize_svg_frame
    from test_v2_split_action import replay_split

    layout, initial, before, prefix, split, timeline, hashes = callout_split_fixture(portrait, mode, boxed)
    capture = capture_split(split, layout, before, {})
    inputs = verify_split_paint_inputs(layout, {})
    assert set(capture.read_dependency_ids) == {"leader-source", "leader-part-1", "leader-part-2", "callout-target"}
    for key in ("source", "part-1", "part-2"):
        admission = split_family_admission(key, capture, layout, inputs)
        assert admission.family == "text" and admission.proof_kind == "pinned_font_rendered_alpha_v1"
        assert admission.content_sha256 == hashes[key]
        assert admission.mode == ("source_fade" if key == "source" else mode)
    replay = replay_split(layout, initial, (*prefix, split), timeline.duration_ms)
    cameras = camera_segments(layout, timeline, replay)
    outputs = {}
    for time in [1, 13, 41, 1, 41, 13]:
        sample = _sample_validated_frame(layout, timeline, replay, cameras, time)
        svg = _compose_validated_svg_frame(layout, timeline, sample, {}, split_inputs=inputs)
        png = _rasterize_svg_frame(layout, svg, split_inputs=inputs)
        assert 'data-object-id="leader-' not in svg.svg
        if time in outputs:
            assert (svg, png) == outputs[time]
        outputs[time] = svg, png
        for key in capture.read_dependency_ids:
            assert sample.object(key) == before.object(key)
    from atme.render.style_bundle import load_bundle

    style, _, root = load_bundle()
    color, paper = style.colors["ink"], style.colors["paper"]
    objects = {obj.object_id: obj for obj in layout.objects}
    width, height = layout.output_profile.width, layout.output_profile.height
    target = objects["callout-target"].geometry.bounds
    for time, source_alpha in [(1, 1), (13, .8333), (41, 0)]:
        body = [f'<rect width="{width}" height="{height}" fill="{paper}"/>',
            (f'<rect x="{target.x:g}" y="{target.y:g}" width="80" height="80" fill="{paper}" '
             f'stroke="{color}" stroke-width="2.6667" stroke-linecap="round" stroke-linejoin="round"/>')]
        for key in ["source", "part-1", "part-2"]:
            if key == "source" and not source_alpha or key != "source" and time == 1:
                continue
            bounds = objects[key].geometry.bounds
            x, y, w, h = bounds.x, bounds.y, bounds.width, bounds.height
            text = {"source": "src", "part-1": "A\u0301B", "part-2": "x=y"}[key]
            if key != "source" and time == 13 and mode == "write":
                text = "A\u0301" if key == "part-1" else "x"
            inset = 32/3 if boxed else 0
            glyph = (f'<text x="{x+inset:.4f}" y="{y+inset+64/3:.4f}" fill="{color}" '
                f'font-family="Atkinson Hyperlegible" font-size="21.3333" font-weight="400" '
                f'xml:space="preserve">{html.escape(text)}</text>')
            box = (f'<rect x="{x:g}" y="{y:g}" width="{w:g}" height="{h:g}" rx="8" '
                f'fill="{paper}" stroke="{color}" stroke-width="2.6667" '
                f'stroke-linecap="round" stroke-linejoin="round"/>') if boxed else ""
            inner = box + glyph
            if key != "source" and time == 13 and mode in {"reveal", "enter"}:
                inner = (f'<defs><clipPath id="oracle-{key}"><rect x="{x:g}" y="{y:g}" '
                    f'width="{w/2:g}" height="{h:g}"/></clipPath></defs>'
                    f'<g clip-path="url(#oracle-{key})">{inner}</g>')
            shift = ' transform="translate(-40 0)"' if key != "source" and time == 13 and mode == "enter" else ""
            body.append(f'<g opacity="{source_alpha if key == "source" else 1}"{shift}>{inner}</g>')
        literal = f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">{"".join(body)}</svg>'
        expected = bytes(resvg_py.svg_to_bytes(svg_string=literal,
            font_files=[str(root / "fonts/AtkinsonHyperlegible-Regular.otf")], skip_system_fonts=True))
        with Image.open(io.BytesIO(expected)) as oracle, Image.open(io.BytesIO(outputs[time][1].png)) as actual:
            assert actual.convert("RGBA").tobytes() == oracle.convert("RGBA").tobytes()
    final = replay.at(41)
    assert dict(final.state_versions)["leader-source"] == 2
    assert dict(final.state_versions)["leader-part-1"] == 1
    assert not final.object("leader-part-1").visible


def test_callout_body_adapter_rejects_an_actually_live_source_pointer():
    from atme.render.v2_split import capture_split
    from atme.render.v2_split_paint import (
        split_family_admission,
        verify_split_paint_inputs,
    )

    layout, _, before, _, split, _, _ = callout_split_fixture(source_state="live")
    capture = capture_split(split, layout, before, {})
    inputs = verify_split_paint_inputs(layout, {})
    with pytest.raises(ValueError, match="Callout.*removed source pointer"):
        split_family_admission("source", capture, layout, inputs)


@pytest.mark.parametrize("fault", ["target_geometry", "target_anchor", "leader_route"])
def test_callout_body_adapter_rejects_read_payload_tamper_with_fresh_verified_input_manifest(fault):
    from atme.render.v2_split import capture_split
    from atme.render.v2_split_paint import (
        split_family_admission,
        verify_split_paint_inputs,
    )

    layout, _, before, _, split, _, _ = callout_split_fixture()
    capture = capture_split(split, layout, before, {})
    raw = layout.model_dump(mode="json")
    if fault == "leader_route":
        next(obj for obj in raw["objects"] if obj["object_id"] == "leader-source")["routing"] = "elbow"
    else:
        target = next(obj for obj in raw["objects"] if obj["object_id"] == "callout-target")
        if fault == "target_anchor":
            target["anchors"][0]["point"]["x"] = .6
        else:
            target["geometry"]["bounds"]["x"] += 1.
    changed = ExecutableLayoutV2.model_validate(raw)
    with pytest.raises(ValueError, match="Callout captured read content differs"):
        split_family_admission("source", capture, changed, verify_split_paint_inputs(changed, {}))


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("mode", ["write", "reveal", "enter"])
def test_callout_body_native_every_ms_coverage_preserves_readonly_leaders(portrait, mode):
    from atme.render.v2_split import capture_split
    from atme.render.v2_split_paint import (
        prove_split_coverage,
        verify_split_paint_inputs,
    )

    layout, _, before, _, split, _, _ = callout_split_fixture(portrait, mode, boxed=True)
    capture = capture_split(split, layout, before, {})
    before_capture = repr(capture)
    proof = prove_split_coverage(capture, layout, verify_split_paint_inputs(layout, {}))
    assert proof.proof_kind == "native_alpha_all_integer_ms_v1"
    assert all("leader-" not in key for interval in proof.intervals for key in interval.painted_root_ids)
    assert proof.critical_times_ms[0] == 1 and proof.critical_times_ms[-1] == 41
    assert repr(capture) == before_capture


@pytest.mark.parametrize("fault", ["read_kind", "missing_leader", "missing_target", "missing_ancestor",
    "read_transform", "result_visible", "result_partial", "result_zero_alpha", "source_not_removed"])
def test_callout_body_captured_dependency_or_state_forgery_never_admits_pointer_paint(fault):
    from dataclasses import replace

    from atme.render.v2_split import capture_split
    from atme.render.v2_split_paint import (
        split_family_admission,
        verify_split_paint_inputs,
    )
    from atme.store.contracts_v2 import SplitPolicy, _split_expected_completion

    layout, _, before, _, split, _, _ = callout_split_fixture(target_group=fault == "missing_ancestor")
    capture = capture_split(split, layout, before, {})
    policy = json.loads(capture.policy_json)
    basis = policy["source_basis"]
    frames = {row.object_id: row for row in capture.baseline}
    placements = {row["object_id"]: row for row in basis["placements"]}
    removed = set()
    if fault == "read_kind":
        basis["read_dependencies"][0]["kind"] = "ancestor"
    elif fault.startswith("missing_"):
        removed.add({"missing_leader": "leader-source", "missing_target": "callout-target",
            "missing_ancestor": "target-stage"}[fault])
        for dependency in basis["read_dependencies"]:
            dependency["object_ids"] = [key for key in dependency["object_ids"] if key not in removed]
        basis["read_dependencies"] = [row for row in basis["read_dependencies"] if row["object_ids"]]
        basis["placements"] = [row for row in basis["placements"] if row["object_id"] not in removed]
    elif fault == "read_transform":
        target = frames["callout-target"]
        frames["callout-target"] = replace(target, transform=replace(target.transform,
            position=replace(target.transform.position, x=1.)))
        # A forged frame cannot disagree with the exact captured placement.
    else:
        key = "leader-source" if fault == "source_not_removed" else "leader-part-1"
        update = {"result_visible": {"state": "visible", "visible": True, "reveal_fraction": 1.},
            "result_partial": {"reveal_fraction": .5}, "result_zero_alpha": {"opacity": 0.},
            "source_not_removed": {"state": "visible"}}[fault]
        frames[key] = replace(frames[key], **update)
        for name, value in update.items():
            placements[key][{"visible": "local_visibility", "opacity": "local_opacity",
                "reveal_fraction": "reveal"}.get(name, name)] = value
        if "visible" in update:
            placements[key]["effective_visibility"] = update["visible"]
    # These are negative coherent carrier forgeries, never positive/history evidence.
    with pytest.raises(ValueError, match="Callout|ancestry|parent"):
        policy["source_basis_sha256"] = digest(basis)
        completion = _split_expected_completion(SplitPolicy.model_validate(policy))
        completion["completion_sha256"] = digest(completion)
        forged = replace(capture, policy_json=json.dumps(policy, sort_keys=True, separators=(",", ":")),
            basis_json=json.dumps(basis, sort_keys=True, separators=(",", ":")),
            completion_json=json.dumps(completion, sort_keys=True, separators=(",", ":")),
            read_dependency_ids=tuple(key for key in capture.read_dependency_ids if key not in removed),
            baseline=tuple(frames[key] for key in sorted(frames) if key not in removed),
            content_receipts=tuple(row for row in capture.content_receipts if row.object_id not in removed))
        split_family_admission("source", forged, layout, verify_split_paint_inputs(layout, {}))


def compound_callout_fixture(portrait, source_compound=False, ancestry=False):
    from atme.render.v2_split import _observed_split_placements
    from atme.render.v2_split_identity import (
        SplitContentReceipt,
        split_content_receipts,
    )
    from atme.store.contracts_v2 import (
        ResolvedAction,
        ResolvedVisualTimelineV2,
        SplitPolicy,
        _split_expected_completion,
    )
    from test_v2_group_hierarchy import grouped_documents
    from test_v2_split_action import replay_split
    from test_v2_split_identity import sample_for_layout

    original, _, _, prefix, split, timeline, _ = callout_split_fixture(portrait, boxed=True)
    raw, action = original.model_dump(mode="json"), split.model_dump(mode="json")
    root_id = "source" if source_compound else "part-1"
    body = next(obj for obj in raw["objects"] if obj["object_id"] == root_id)
    child = deepcopy(body)
    # A hidden result root controls effective visibility; child-local paint
    # stays ready/immutable, just as for the accepted Code compound contract.
    child.update(object_id="callout-child", parent_id=root_id, visible=True, initial_state="visible")
    root = deepcopy(grouped_documents()[0]["objects"][3])
    root.update(object_id=root_id, child_ids=["callout-child"], z_index=body["z_index"],
        visible=body["visible"], initial_state=body["initial_state"], geometry=deepcopy(body["geometry"]))
    root["geometry"]["corner_radius"] = None
    raw["objects"] = [obj for obj in raw["objects"] if obj["object_id"] != root_id] + [root, child]
    next(obj for obj in raw["objects"] if obj["object_id"] == f"leader-{root_id}")["source_object_id"] = "callout-child"
    policy = action["action"]["split_policy"]
    closure = (policy["source_basis"]["source_closure"] if source_compound else
        next(row for row in policy["source_basis"]["result_closures"] if row["root_id"] == root_id))
    closure["owned_ids"] = ["callout-child", root_id]
    ancestors = {root_id}
    if ancestry:
        stage = deepcopy(root)
        stage.update(object_id="callout-stage", parent_id="outer-stage", child_ids=["source", "part-1", "part-2"],
            visible=True, initial_state="visible", z_index=0)
        stage["geometry"]["bounds"] = {"x": 0., "y": 0., "width": float(original.output_profile.width),
            "height": float(original.output_profile.height)}
        stage["transform"].update(position={"x": 30., "y": 10.}, scale_x=1.25, scale_y=.8,
            rotation_degrees=0., origin={"x": 0., "y": 0.})
        outer = deepcopy(stage)
        outer.update(object_id="outer-stage", parent_id=None, child_ids=["callout-stage"])
        outer["transform"].update(position={"x": 10., "y": 20.}, scale_x=1., scale_y=1.)
        for obj in raw["objects"]:
            if obj["object_id"] in {"source", "part-1", "part-2"}:
                obj["parent_id"] = "callout-stage"
        raw["objects"].extend((stage, outer))
        ancestors.update(("callout-stage", "outer-stage"))
    raw["boards"][0].update(object_ids=[obj["object_id"] for obj in raw["objects"]], density_limit=len(raw["objects"]))
    layout = ExecutableLayoutV2.model_validate(raw)
    initial = sample_for_layout(layout)
    before = replay_split(layout, initial, prefix, timeline.duration_ms).at(1)
    authored = {obj["object_id"]: obj for obj in raw["objects"]}
    receipts = {}

    def receipt(key):
        if key in receipts:
            return receipts[key]
        obj = authored[key]
        payload = {name: obj[name] for name in ("object_type", "geometry", "style", "anchors", "asset_id")}
        if obj["object_type"] == "callout":
            payload.update({name: obj[name] for name in ("text", "items", "callout_binding")})
        elif obj["object_type"] == "rectangle":
            payload["path_data"] = obj["path_data"]
        elif obj["object_type"] == "arrow":
            payload.update({name: obj[name] for name in ("source_object_id", "source_anchor_id", "destination_object_id",
                "destination_anchor_id", "role", "routing", "allow_self_loop")})
        else:
            payload["children"] = [{"object_id": child, "content_sha256": receipt(child).content_sha256}
                for child in sorted(obj["child_ids"])]
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        receipts[key] = SplitContentReceipt(key, encoded, sha256(encoded.encode()).hexdigest())
        return receipts[key]

    for key in authored:
        receipt(key)
    assert receipts == {row.object_id: row for row in split_content_receipts(layout, before, {})}
    connector_ids = {"callout-target", "leader-source", "leader-part-1", "leader-part-2", "source", "part-1", "part-2"}
    connector_ids.remove(root_id)
    connector_ids.add("callout-child")
    policy["source_basis"]["read_dependencies"] = [
        {"kind": "ancestor", "object_ids": sorted(ancestors)},
        {"kind": "connector_anchor", "object_ids": sorted(connector_ids)}]
    policy["source_basis"]["placements"] = [row.model_dump(mode="json") for row in _observed_split_placements(
        before, {obj.object_id: obj for obj in layout.objects}, set(authored), receipts)]
    for row in policy["correspondences"]:
        row.update(source_content_sha256=receipts["source"].content_sha256,
            result_content_sha256=receipts[row["result_object_id"]].content_sha256)
    policy["source_basis_sha256"] = digest(policy["source_basis"])
    completion = _split_expected_completion(SplitPolicy.model_validate(policy))
    completion["completion_sha256"] = digest(completion)
    action["split_completion_receipt"] = completion
    resolved = ResolvedAction.model_validate(action)
    raw_timeline = timeline.model_dump(mode="json")
    raw_timeline.update(actions=[row.model_dump(mode="json") for row in prefix]+[action], layout_sha256=digest(raw),
        initial_object_states=[{"object_id": row.object_id, "state": row.state, "visible": row.visible,
            "state_version": 1} for row in initial.objects])
    return layout, initial, before, prefix, resolved, ResolvedVisualTimelineV2.model_validate(raw_timeline), receipts, child


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("source_compound,ancestry", [(True, False), (False, True), (True, True)])
def test_callout_body_compound_source_result_and_nested_read_ancestry_preserve_local_child(portrait, source_compound, ancestry):
    from atme.render.v2_split import capture_split
    from atme.render.v2_split_paint import (
        prove_split_coverage,
        split_family_admission,
        verify_split_paint_inputs,
    )
    from test_v2_split_action import replay_split

    layout, initial, before, prefix, split, timeline, receipts, _ = compound_callout_fixture(portrait, source_compound, ancestry)
    capture = capture_split(split, layout, before, {})
    inputs = verify_split_paint_inputs(layout, {})
    root_id = "source" if source_compound else "part-1"
    admission = split_family_admission(root_id, capture, layout, inputs)
    assert admission.family == "compound" and admission.content_sha256 == receipts[root_id].content_sha256
    assert split_family_admission("callout-child", capture, layout, inputs).family == "text"
    if ancestry:
        assert {"callout-stage", "outer-stage"}.issubset(capture.read_dependency_ids)
        child = next(row for row in json.loads(capture.basis_json)["placements"] if row["object_id"] == "callout-child")
        assert child["world_matrix"] == [1.25, 0., 0., .8, 40., 30.]
    proof = prove_split_coverage(capture, layout, inputs)
    assert proof.intervals[-1].painted_root_ids == ("part-1", "part-2")
    replay = replay_split(layout, initial, (*prefix, split), timeline.duration_ms)
    if source_compound:
        assert replay.at(41).object("callout-child") == before.object("callout-child")
        assert dict(replay.at(41).state_versions)["callout-child"] == 1
    for key in capture.read_dependency_ids:
        assert replay.at(41).object(key) == before.object(key)
    from atme.render.style_bundle import load_bundle
    from atme.render.v2_state import _sample_validated_frame, camera_segments
    from atme.render.v2_svg import _compose_validated_svg_frame, _rasterize_svg_frame

    style, _, font_root = load_bundle()
    cameras = camera_segments(layout, timeline, replay)
    width, height = layout.output_profile.width, layout.output_profile.height
    objects = {obj.object_id: obj for obj in layout.objects}
    color, paper = style.colors["ink"], style.colors["paper"]
    target = objects["callout-target"].geometry.bounds
    outputs = {}
    for at, opacity in [(1, 1), (13, .8333), (41, 0)]:
        parts = []
        for key in ("source", "part-1", "part-2"):
            if key == "source" and not opacity or key != "source" and at == 1:
                continue
            obj = objects["callout-child" if key == root_id else key]
            bounds = obj.geometry.bounds
            x, y, w, h = bounds.x, bounds.y, bounds.width, bounds.height
            text = "src" if key == "source" else ("A\u0301" if key == "part-1" else "x") if at == 13 else (
                "A\u0301B" if key == "part-1" else "x=y")
            inner = (f'<rect x="{x:g}" y="{y:g}" width="{w:g}" height="{h:g}" rx="8" fill="{paper}" '
                f'stroke="{color}" stroke-width="2.6667" stroke-linecap="round" stroke-linejoin="round"/>'
                f'<text x="{x+32/3:.4f}" y="{y+32:.4f}" fill="{color}" font-family="Atkinson Hyperlegible" '
                f'font-size="21.3333" font-weight="400" xml:space="preserve">{html.escape(text)}</text>')
            # Compound write keeps child-local reveal=1: construct graphemes,
            # not a rectangular wipe of the explicitly authored body box.
            parts.append(f'<g opacity="{opacity if key == "source" else 1}">{inner}</g>')
        owned = "".join(parts)
        if ancestry:
            owned = f'<g transform="matrix(1.25 0 0 .8 40 30)">{owned}</g>'
        literal = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">'
            f'<rect width="{width}" height="{height}" fill="{paper}"/>'
            f'<rect x="{target.x:g}" y="{target.y:g}" width="80" height="80" fill="{paper}" '
            f'stroke="{color}" stroke-width="2.6667" stroke-linecap="round" stroke-linejoin="round"/>{owned}</svg>')
        expected = bytes(resvg_py.svg_to_bytes(svg_string=literal,
            font_files=[str(font_root / "fonts/AtkinsonHyperlegible-Regular.otf")], skip_system_fonts=True))
        frame = _sample_validated_frame(layout, timeline, replay, cameras, at)
        svg = _compose_validated_svg_frame(layout, timeline, frame, {}, split_inputs=inputs)
        png = _rasterize_svg_frame(layout, svg, split_inputs=inputs)
        with Image.open(io.BytesIO(png.png)) as actual, Image.open(io.BytesIO(expected)) as oracle:
            assert actual.convert("RGBA").tobytes() == oracle.convert("RGBA").tobytes()
        assert 'data-object-id="leader-' not in svg.svg
        outputs[at] = svg, png
    for at in [41, 1, 13, 41, 13]:
        frame = _sample_validated_frame(layout, timeline, replay, cameras, at)
        svg = _compose_validated_svg_frame(layout, timeline, frame, {}, split_inputs=inputs)
        assert (svg, _rasterize_svg_frame(layout, svg, split_inputs=inputs)) == outputs[at]
