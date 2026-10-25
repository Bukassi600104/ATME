"""S3-F05 real container/expanded-instance closures, not a second painter."""

import json
import xml.etree.ElementTree as ET
from copy import deepcopy
from hashlib import sha256

import pytest
import resvg_py
from test_v2_split_container_family import (
    container_frames,
    deny_live_reads_and_network,
    rgba,
)
from test_v2_split_families import geometry_split_family, n
from test_v2_split_identity import sample_for_layout
from v2_fixtures import digest

from atme.render.v2_composition import (
    build_composition_binding,
    materialize_composition,
)
from atme.render.v2_split import _observed_split_placements, capture_split
from atme.render.v2_split_identity import SplitContentReceipt
from atme.render.v2_split_paint import (
    prove_split_coverage,
    split_family_admission,
    verify_split_paint_inputs,
)
from atme.store.contracts_v2 import (
    ExecutableLayoutV2,
    ResolvedAction,
    ResolvedVisualTimelineV2,
    SplitPolicy,
    _split_expected_completion,
    _split_packet_digest,
)


def independent_receipts(raw):
    objects = {obj["object_id"]: obj for obj in raw["objects"]}
    receipts = {}
    def project(key):
        obj = objects[key]
        payload = {field: obj[field] for field in ("object_type", "geometry", "style", "anchors", "asset_id")}
        if obj["object_type"] == "rectangle":
            payload["path_data"] = obj["path_data"]
        elif obj["object_type"] == "code":
            payload.update({field: obj[field] for field in ("text", "items", "code_payload")})
        else:
            payload["children"] = [{"object_id": child, "content_sha256": project(child).content_sha256}
                                   for child in sorted(obj["child_ids"])]
            if obj.get("composition_binding") is not None:
                payload["composition_binding"] = obj["composition_binding"]
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        receipts[key] = SplitContentReceipt(key, canonical, sha256(canonical.encode()).hexdigest())
        return receipts[key]
    for key in objects:
        project(key)
    return receipts


def reusable_split_family(portrait=False, kind="instance", mode="reveal", *, content="rectangle"):
    if content == "code":
        from test_v2_split_code_family import code_split_family
        base, _, split, timeline, _, boxes = code_split_family(portrait, mode)
    else:
        base, _, split, timeline, _, _, boxes = geometry_split_family(portrait, "rectangle", mode)
    # Apertures overlap too, making actual sibling paint order observable.
    boxes["part-2"] = (boxes["part-1"][0]+20., *boxes["part-1"][1:])
    raw, action = base.model_dump(mode="json"), split.model_dump(mode="json")
    originals = deepcopy(raw["objects"])
    raw["objects"] = []
    specs = []
    closures, ancestors, apertures = {}, {"studio-stage"}, set()
    empty_style = {"stroke": None, "fill": None, "text": None, "effect": None}
    for original in originals:
        key = original["object_id"]
        x, y, _, _ = boxes[key]
        root = deepcopy(original)
        for field in ("path_data", "text", "items", "code_payload", "callout_binding", "structured_list"):
            root.pop(field, None)
        root.update(object_type="group", anchors=[], style=empty_style, parent_id="studio-stage", child_ids=[key+"-ink"])
        root["geometry"]["bounds"].update(x=0., y=0.)
        root["transform"]["position"] = {"x": x+(-80. if mode == "enter" and key != "source" else 0.), "y": y}
        leaf = deepcopy(original)
        leaf.update(object_id=key+"-ink", parent_id=key, z_index=0, visible=True, initial_state="visible")
        leaf["geometry"]["bounds"].update(x=0., y=0.)
        leaf["transform"].update(position={"x": 0., "y": 0.}, origin={"x": 0., "y": 0.})
        if kind in {"composition", "instance"}:
            # Actual strict materializer + exact Binding. The two result
            # instances share ONE definition but explicit distinct IDs/values.
            template_root, template_leaf = deepcopy(root), deepcopy(leaf)
            template_root.update(object_id="root", parent_id=None, child_ids=["aperture"], z_index=0)
            template_root["transform"]["position"] = {"x": 0., "y": 0.}
            template_leaf.update(object_id="ink", parent_id="aperture")
            if content == "rectangle":
                template_leaf["style"]["stroke"] = "ink.primary"
            aperture = deepcopy(template_root)
            aperture.update(object_id="aperture", object_type="clip", parent_id="root", child_ids=["ink"],
                            visible=True, initial_state="visible")
            aperture["geometry"]["bounds"]["width"] = 40.
            templates = [template_root, aperture, template_leaf]
            for obj in templates:
                obj.update(board_id="template-board", beat_id="template-beat", coverage_ids=["coverage-local"])
            definition = {"version": "1.0.0", "definition_id": "shared-result" if kind == "instance" and key != "source" and content == "rectangle" else key+"-definition",
                "revision": 1, "root_local_id": "root", "template_board_id": "template-board", "template_beat_id": "template-beat",
                "template_coverage_ids": ["coverage-local"], "objects": templates,
                "parameters": ([{"parameter_id": "ink", "value_type": "string", "targets": [{"object_id": "ink", "field": "style.stroke"}]}]
                               if content == "rectangle" else [])}
            from atme.store.contracts_v2 import composition_definition_digest
            spec = {"version": "1.0.0", "kind": kind, "definition": definition,
                "definition_sha256": composition_definition_digest(definition), "root_object_id": key,
                "board_id": original["board_id"], "beat_id": original["beat_id"], "root_parent_id": "studio-stage",
                "root_z_index": original["z_index"],
                "coverage_map": [{"local_coverage_id": "coverage-local", "coverage_id": original["coverage_ids"][0]}],
                "object_map": [{"local_object_id": local, "object_id": key if local == "root" else f"composition-{len(key)}:{key}:{local}"}
                               for local in ("root", "aperture", "ink")],
                "parameter_values": ([{"parameter_id": "ink", "value": {"value_type": "string", "value": original["style"]["stroke"]}}]
                                     if content == "rectangle" else []),
                "overrides": [{"target": {"object_id": "root", "field": "transform.position."+axis},
                               "value": {"value_type": "number", "value": value}}
                              for axis, value in root["transform"]["position"].items()]}
            expanded = [obj.model_dump(mode="json") for obj in materialize_composition(spec)]
            specs.append(spec)
            raw["objects"].extend(expanded)
            closures[key] = [obj["object_id"] for obj in expanded]
            ancestors.add(key)
            aperture_id = next(obj["object_id"] for obj in expanded if obj["object_type"] == "clip")
            ancestors.add(aperture_id)
            apertures.add(aperture_id)
        else:
            if kind == "clip":
                root["object_type"] = "clip"
                root["geometry"]["bounds"]["width"] = 40.
                apertures.add(key)
            raw["objects"].extend((root, leaf))
            closures[key] = [key, leaf["object_id"]]
            ancestors.add(key)
    stage = deepcopy(next(obj for obj in raw["objects"] if obj["object_id"] == "source"))
    stage.update(object_id="studio-stage", parent_id=None, child_ids=["source", "part-1", "part-2"],
                 object_type="group", z_index=0, visible=True, initial_state="visible", composition_binding=None)
    stage["transform"].update(position={"x": 10., "y": 20.}, scale_x=1.1, scale_y=.9)
    stage["geometry"]["bounds"].update(x=0., y=0., width=1000., height=1000.)
    raw["objects"].append(stage)
    raw["boards"][0].update(object_ids=[obj["object_id"] for obj in raw["objects"]], density_limit=12)
    for spec in specs:
        next(obj for obj in raw["objects"] if obj["object_id"] == spec["root_object_id"])["composition_binding"] = build_composition_binding(spec, raw)
    layout = ExecutableLayoutV2.model_validate(raw)
    # Canonical authored fields, independently projected content hashes.
    raw = layout.model_dump(mode="json")
    receipts = independent_receipts(raw)
    before = sample_for_layout(layout)
    policy = action["action"]["split_policy"]
    basis = policy["source_basis"]
    basis["source_closure"]["owned_ids"] = sorted(closures["source"])
    for row in basis["result_closures"]:
        row["owned_ids"] = sorted(closures[row["root_id"]])
    basis["read_dependencies"] = [{"kind": "ancestor", "object_ids": sorted(ancestors)}]
    if apertures:
        basis["read_dependencies"].append({"kind": "aperture", "object_ids": sorted(apertures)})
    objects = {obj.object_id: obj for obj in layout.objects}
    basis["placements"] = [row.model_dump(mode="json") for row in _observed_split_placements(before, objects, set(objects), receipts)]
    for row in policy["correspondences"]:
        row.update(source_content_sha256=receipts["source"].content_sha256,
                   result_content_sha256=receipts[row["result_object_id"]].content_sha256)
    for result in policy["results"]:
        key = result["object_id"]
        result["destination"] = objects[key].transform.model_dump(mode="json")
        result["destination"]["position"] = dict(zip(("x", "y"), boxes[key][:2]))
        if mode == "enter":
            result["construction"]["enter_destination"] = result["destination"]
    policy["source_basis_sha256"] = _split_packet_digest(basis)
    completion = _split_expected_completion(SplitPolicy.model_validate(policy))
    completion["completion_sha256"] = _split_packet_digest(completion)
    action["split_completion_receipt"] = completion
    clock = timeline.model_dump(mode="json")
    clock.update(actions=[action], layout_sha256=digest(raw), initial_object_states=[
        {"object_id": frame.object_id, "state": frame.state, "visible": frame.visible,
         "state_version": dict(before.state_versions)[frame.object_id]} for frame in before.objects])
    return layout, before, ResolvedAction.model_validate(action), ResolvedVisualTimelineV2.model_validate(clock), receipts, specs, boxes


def literal_reusable_oracle(portrait, kind, mode, at, inputs, boxes, *, content="rectangle"):
    width, height = (720, 1280) if portrait else (1280, 720)
    fraction, source_alpha = {0: (0, 1), 12: (.5, .8333), 40: (1, 0)}[at]
    colors = json.loads(inputs.style_json)["colors"]
    parts = []
    for key in ("source", "part-1", "part-2"):
        if key == "source" and not source_alpha or key != "source" and not fraction:
            continue
        x, y, _w, _h = boxes[key]
        dash = (' stroke-dasharray="400 400" stroke-dashoffset="200"'
                if key != "source" and fraction == .5 and mode == "draw" else "")
        color = colors[{"source": "ink", "part-1": "accent", "part-2": "attention"}[key]]
        if content == "code":
            text = ("src" if key == "source" else
                    ("e\u0301" if key == "part-1" else "x") if at == 12 and mode == "write" else
                    "e\u0301x" if key == "part-1" else "x=y")
            inner = (f'<text x="0" y="{n(56/3)}" fill="{colors["ink"]}" '
                     f'font-family="JetBrains Mono" font-size="18.6667" font-weight="400" '
                     f'xml:space="preserve">{text}</text>')
        else:
            inner = (f'<rect x="0" y="0" width="80" height="120" rx="0" fill="none" stroke="{color}" '
                     f'stroke-width="{n(4*2/3)}" stroke-linecap="round" stroke-linejoin="round"{dash}/>')
        clip_width = 40. if kind != "group" else None
        if key != "source" and fraction == .5 and mode in {"reveal", "enter"}:
            clip_width = (20. if kind == "clip" else 40.)
        if clip_width is not None:
            inner = (f'<defs><clipPath id="literal-{key}"><rect width="{n(clip_width)}" height="120"/></clipPath></defs>'
                     f'<g clip-path="url(#literal-{key})">{inner}</g>')
        dx = -40 if key != "source" and at == 12 and mode == "enter" else 0
        parts.append(f'<g transform="translate({n(x+dx)} {n(y)})" opacity="{source_alpha if key == "source" else 1}">{inner}</g>')
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">'
           f'<rect width="{width}" height="{height}" fill="#FAF8F1"/>'
           # Authored stage scales around its 1000x1000 midpoint: e=-40,f=70.
           f'<g transform="matrix(1.1 0 0 .9 -40 70)">{"".join(parts)}</g></svg>')
    if content == "code":
        from atme.render.style_contracts import PaperInkStyle
        from atme.render.v2_svg import SVGFrame, _rasterize_frozen_svg
        return _rasterize_frozen_svg(SVGFrame(at, width, height, svg),
            PaperInkStyle.model_validate_json(inputs.style_json),
            {name: raw for name, _, raw in inputs.bundle_bytes}).png
    return resvg_py.svg_to_bytes(svg_string=svg, skip_system_fonts=True)


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("kind", ["group", "clip", "composition", "instance"])
@pytest.mark.parametrize("mode,content", [("reveal", "rectangle"), ("draw", "rectangle"), ("enter", "rectangle"), ("write", "code")])
def test_reusable_split_exact_closure_identity_pixels_current_world_and_offline_coverage(portrait, kind, mode, content, monkeypatch, tmp_path):
    layout, before, action, timeline, receipts, specs, boxes = reusable_split_family(portrait, kind, mode, content=content)
    original = deepcopy(layout.model_dump(mode="json"))
    capture = capture_split(action, layout, before, {})
    inputs = verify_split_paint_inputs(layout, {})
    for key in ("source", "part-1", "part-2"):
        admission = split_family_admission(key, capture, layout, inputs)
        assert admission.family == "compound" and admission.proof_kind == "captured_compound_closure_v1"
        assert admission.content_sha256 == receipts[key].content_sha256
    assert len({receipts[key].content_sha256 for key in ("source", "part-1", "part-2")}) == 3
    if kind == "instance":
        result_specs = [spec for spec in specs if spec["root_object_id"] != "source"]
        if content == "rectangle":
            assert result_specs[0]["definition_sha256"] == result_specs[1]["definition_sha256"]
        first, second = ({row["object_id"] for row in spec["object_map"]} for spec in result_specs)
        assert not first & second
    expected = container_frames(layout, before, action, timeline, inputs, (40, 0, 12, 40, 12, 0))
    assert [row.object_id for row in action.action.split_policy.results] == ["part-2", "part-1"]
    painted = [node.attrib["data-object-id"] for node in ET.fromstring(expected[12][0]).iter()
               if node.attrib.get("data-object-id") in {"source", "part-1", "part-2"}]
    assert painted == ["source", "part-1", "part-2"]
    for at in (0, 12, 40):
        actual = rgba(expected[at][1])
        literal = rgba(literal_reusable_oracle(portrait, kind, mode, at, inputs, boxes, content=content))
        if actual != literal:
            pytest.fail(f"literal pixel mismatch at {at}ms: actual={sha256(actual).hexdigest()}, expected={sha256(literal).hexdigest()}")
    (tmp_path / f"{kind}-{mode}.png").write_bytes(expected[12][1])
    deny_live_reads_and_network(monkeypatch)
    proof = prove_split_coverage(capture, layout, inputs)
    assert all(row.painted_root_ids for row in proof.intervals)
    assert proof.intervals[0].start_ms == 0 and proof.intervals[-1].end_ms == 40
    assert container_frames(layout, before, action, timeline, inputs, (12, 0, 40)) == expected
    assert layout.model_dump(mode="json") == original


@pytest.mark.parametrize("kind", ["group", "clip", "composition", "instance"])
def test_reusable_mark_closure_cannot_claim_text_write(kind):
    layout, before, action, _, _, _, _ = reusable_split_family(kind=kind, mode="write")
    capture = capture_split(action, layout, before, {})
    with pytest.raises(ValueError, match="Split write is incompatible with geometry construction"):
        split_family_admission("part-1", capture, layout, verify_split_paint_inputs(layout, {}))


@pytest.mark.parametrize("kind", ["group", "clip", "composition", "instance"])
@pytest.mark.parametrize("fault", ["owned_ink", "read_parent"])
def test_reusable_fresh_inputs_cannot_replace_exact_captured_payload(kind, fault):
    layout, before, action, _, _, specs, _ = reusable_split_family(kind=kind)
    capture = capture_split(action, layout, before, {})
    key = "studio-stage" if fault == "read_parent" else (
        next(row["object_id"] for spec in specs if spec["root_object_id"] == "part-1"
             for row in spec["object_map"] if row["local_object_id"] == "ink") if specs else "part-1-ink")
    next(obj for obj in layout.objects if obj.object_id == key).geometry.bounds.width += 1
    # Exact initial Binding validation rejects bound member edits even before
    # admission; the following coherent-variant test reaches the capture guard.
    message = ("composition destination changes or omits an exact initial expanded member"
               if specs and fault == "owned_ink" else "Split captured.*content differs")
    with pytest.raises(ValueError, match=message):
        split_family_admission("part-1", capture, layout, verify_split_paint_inputs(layout, {}))


@pytest.mark.parametrize("kind", ["composition", "instance"])
def test_coherent_new_expansion_binding_is_not_authority_for_an_old_split_capture(kind):
    layout, before, action, _, _, specs, _ = reusable_split_family(kind=kind)
    capture = capture_split(action, layout, before, {})
    raw = layout.model_dump(mode="json")
    spec = deepcopy(next(row for row in specs if row["root_object_id"] == "part-1"))
    spec["overrides"].append({"target": {"object_id": "ink", "field": "geometry.bounds.width"},
                             "value": {"value_type": "number", "value": 81.}})
    expanded = {obj.object_id: obj.model_dump(mode="json") for obj in materialize_composition(spec)}
    raw["objects"] = [expanded.get(obj["object_id"], obj) for obj in raw["objects"]]
    next(obj for obj in raw["objects"] if obj["object_id"] == "part-1")["composition_binding"] = build_composition_binding(spec, raw)
    changed = ExecutableLayoutV2.model_validate(raw)
    fresh_inputs = verify_split_paint_inputs(changed, {})
    with pytest.raises(ValueError, match="Split captured content differs"):
        split_family_admission("part-1", capture, changed, fresh_inputs)
