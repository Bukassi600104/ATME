"""S3-F03 owning visual families use the existing capture/paint admission path."""

import io
import json
import xml.etree.ElementTree as ET
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from socket import socket

import pytest
from PIL import Image
from test_v2_character_assembly_compositor import original_pose_documents
from test_v2_illustration_assembly_compositor import original_illustration_documents
from test_v2_split_action import replay_split
from test_v2_split_capture import geometry_boundary
from test_v2_split_identity import sample_for_layout
from test_v2_technical_frame_compositor import composite_documents
from test_v2_technical_frame_contract import CASES
from v2_fixtures import digest
from v2_split_fixtures import split_documents

from atme.render.v2_camera import camera_segments
from atme.render.v2_split import _observed_split_placements, capture_split
from atme.render.v2_split_identity import SplitContentReceipt
from atme.render.v2_split_paint import (
    prove_split_coverage,
    split_family_admission,
    verify_split_paint_inputs,
)
from atme.render.v2_state import _sample_validated_frame
from atme.render.v2_svg import (
    _compose_validated_svg_frame,
    _rasterize_svg_frame,
    compose_png_frame,
)
from atme.store.contracts_v2 import (
    ExecutableLayoutV2,
    ResolvedAction,
    ResolvedVisualTimelineV2,
    SplitPolicy,
    _split_expected_completion,
)


def authored_receipts(objects):
    """Independent contract projection; never use the production identity producer."""
    by_id = {obj["object_id"]: obj for obj in objects}
    results = {}
    def content(key):
        obj = by_id[key]
        payload = {field: deepcopy(obj[field]) for field in ("object_type", "geometry", "style", "anchors", "asset_id")}
        if obj["object_type"] == "group":
            for field in ("illustration_assembly", "character_assembly"):
                if field in obj:
                    payload[field] = deepcopy(obj[field])
            payload["children"] = [{"object_id": child, "content_sha256": content(child).content_sha256}
                                    for child in sorted(obj["child_ids"])]
        elif obj["object_type"] in {"text", "code"}:
            payload.update(text=obj["text"], items=deepcopy(obj["items"]))
            if "code_payload" in obj:
                payload["code_payload"] = deepcopy(obj["code_payload"])
        elif "variant" in obj:
            payload["variant"] = obj["variant"]
            for field in ("registry_binding", "technical_frame"):
                if obj.get(field) is not None:
                    payload[field] = deepcopy(obj[field])
        else:
            payload["path_data"] = obj["path_data"]
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        receipt = SplitContentReceipt(key, canonical, sha256(canonical.encode()).hexdigest())
        results[key] = receipt
        return receipt
    for key in by_id:
        content(key)
    return results


def illustration_boundary(*, portrait=False, owner="part-1", family="illustration", kind=None,
                          active=True, mode="reveal", role_dx=0., root_dx=0.):
    base, _, resolved = geometry_boundary()
    raw = base.model_dump(mode="json")
    if family == "character":
        native, _ = original_pose_documents(kind or "neutral", portrait=portrait)
        native_root = "actor-group"
    elif family == "technical":
        kind = kind or "browser"
        _, states, roles = next(row for row in CASES if row[0] == kind)
        native, _ = composite_documents(kind, states[0 if active else -1], roles, portrait=portrait)
        native_root = "list-group"
    else:
        native, _ = original_illustration_documents(kind or "device", active=active, portrait=portrait)
        native_root = "illustration-group"
    # Keep the complete real owner closure, not unrelated hidden fixture art.
    native_objects = {obj["object_id"]: obj for obj in native["objects"]}
    selected = set()
    def visit(key):
        selected.add(key)
        for child in native_objects[key].get("child_ids", []):
            visit(child)
    visit(native_root)
    native["objects"] = [obj for obj in native["objects"] if obj["object_id"] in selected]
    chosen = next(obj for obj in raw["objects"] if obj["object_id"] == owner)
    names = {obj["object_id"]: owner if obj["object_id"] == native_root else owner + "." + obj["object_id"]
             for obj in native["objects"]}
    def renamed(value):
        if isinstance(value, dict):
            return {key: renamed(item) for key, item in value.items()}
        if isinstance(value, list):
            return [renamed(item) for item in value]
        return names.get(value, value) if isinstance(value, str) else value
    replacement = renamed(native["objects"])
    for obj in replacement:
        obj.update(board_id=chosen["board_id"], beat_id=chosen["beat_id"], coverage_ids=deepcopy(chosen["coverage_ids"]))
        if obj["object_id"] == owner:
            obj.update(z_index=chosen["z_index"], initial_state=chosen["initial_state"], visible=chosen["visible"])
            obj["transform"]["position"]["x"] += root_dx
        elif family == "technical" and obj["object_id"] == names.get("part-title"):
            obj["transform"]["position"]["x"] += role_dx
    raw["objects"] = [obj for obj in raw["objects"] if obj["object_id"] != owner] + replacement
    assert len(raw["objects"]) <= 12  # retain every real descendant; never prune to fit
    raw["boards"][0]["object_ids"] = [obj["object_id"] for obj in raw["objects"]]
    raw["output_profile"] = deepcopy(native["output_profile"])
    raw["canvas"] = deepcopy(native["canvas"])
    layout = ExecutableLayoutV2.model_validate(raw)
    before = sample_for_layout(layout)
    receipts = authored_receipts(raw["objects"])
    action = resolved.model_dump(mode="json")
    action["end_ms"] = 40
    policy = action["action"]["split_policy"]
    basis = policy["source_basis"]
    expanded = sorted(names.values())
    if owner == "source":
        basis["source_closure"]["owned_ids"] = expanded
    else:
        next(row for row in basis["result_closures"] if row["root_id"] == owner)["owned_ids"] = expanded
    basis["read_dependencies"] = [{"kind": "ancestor", "object_ids": sorted({
        obj["parent_id"] for obj in replacement if obj["parent_id"] is not None})}]
    objects = {obj.object_id: obj for obj in layout.objects}
    basis["placements"] = [row.model_dump(mode="json") for row in
        _observed_split_placements(before, objects, set(objects), receipts)]
    for row in policy["correspondences"]:
        row.update(source_content_sha256=receipts["source"].content_sha256,
                   result_content_sha256=receipts[row["result_object_id"]].content_sha256)
    policy["source_basis_sha256"] = digest(basis)
    if owner != "source":
        result = next(row for row in policy["results"] if row["object_id"] == owner)
        result["construction"]["mode"] = mode
        result["destination"] = objects[owner].transform.model_dump(mode="json")
        if mode == "enter":
            result["destination"]["position"]["x"] += 80.
            result["construction"]["enter_destination"] = deepcopy(result["destination"])
    completion = _split_expected_completion(SplitPolicy.model_validate(policy))
    completion["completion_sha256"] = digest(completion)
    action["split_completion_receipt"] = completion
    return layout, before, ResolvedAction.model_validate(action), receipts


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("owner", ["source", "part-1"])
def test_complete_authored_illustration_owner_has_f03_admission_not_generic_container_credit(portrait, owner):
    layout, before, action, expected = illustration_boundary(portrait=portrait, owner=owner)
    capture = capture_split(action, layout, before, {})
    inputs = verify_split_paint_inputs(layout, {})
    admission = split_family_admission(owner, capture, layout, inputs)
    assert admission.family == "authored illustration"
    assert admission.proof_kind == "authored_illustration_closure_v1"
    assert admission.content_sha256 == expected[owner].content_sha256
    assert admission.mode == ("source_fade" if owner == "source" else "reveal")
    assert admission.paint_inputs_sha256 == inputs.inputs_sha256


def test_technical_admission_rejects_coherent_captured_role_outside_native_region():
    layout, before, action, _ = illustration_boundary(family="technical", role_dx=800.)
    capture = capture_split(action, layout, before, {})
    with pytest.raises(ValueError, match="technical_frame part .* outside its physical native"):
        split_family_admission("part-1", capture, layout, verify_split_paint_inputs(layout, {}))


def test_technical_admission_cannot_substitute_baseline_transform_for_bound_placement():
    layout, before, action, _ = illustration_boundary(family="technical")
    capture = capture_split(action, layout, before, {})
    old = next(row for row in capture.baseline if row.object_id == "part-1.part-title")
    transform = replace(old.transform, position=replace(old.transform.position, x=old.transform.position.x+800.))
    changed = replace(capture, baseline=tuple(replace(row, transform=transform) if row == old else row
                                              for row in capture.baseline))
    with pytest.raises(ValueError, match="Split captured state differs from its placement"):
        split_family_admission("part-1", changed, layout, verify_split_paint_inputs(layout, {}))


@pytest.mark.parametrize("portrait", [False, True])
def test_technical_whole_root_nonidentity_transform_preserves_physical_role_fit(portrait):
    layout, before, action, _ = illustration_boundary(family="technical", portrait=portrait, root_dx=37.)
    capture = capture_split(action, layout, before, {})
    assert split_family_admission("part-1", capture, layout, verify_split_paint_inputs(layout, {})).family == "technical illustration"


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("owner", ["source", "part-1"])
@pytest.mark.parametrize("family,expected_family,proof", [
    ("character", "authored character", "authored_character_closure_v1"),
    ("technical", "technical illustration", "native_technical_closure_v1"),
])
def test_real_character_and_technical_owner_have_precise_admission(family, expected_family, proof, owner, portrait):
    layout, before, action, expected = illustration_boundary(family=family, portrait=portrait, owner=owner)
    capture = capture_split(action, layout, before, {})
    inputs = verify_split_paint_inputs(layout, {})
    admission = split_family_admission(owner, capture, layout, inputs)
    assert admission.family == expected_family
    assert admission.proof_kind == proof
    assert admission.content_sha256 == expected[owner].content_sha256
    assert admission.paint_inputs_sha256 == inputs.inputs_sha256


@pytest.mark.parametrize("family", ["illustration", "technical"])
@pytest.mark.parametrize("mode", ["draw", "write"])
def test_mixed_whole_assembly_does_not_invent_per_role_construction(family, mode):
    layout, before, action, _ = illustration_boundary(family=family, mode=mode)
    capture = capture_split(action, layout, before, {})
    with pytest.raises(ValueError, match=f"Split {mode} is incompatible with"):
        split_family_admission("part-1", capture, layout, verify_split_paint_inputs(layout, {}))


@pytest.mark.parametrize("family,child,expected", [
    ("illustration", "artwork-role", "compound"),
    ("character", "actor-head-role", "compound"),
    ("technical", "object-evidence", "technical chrome"),
])
def test_real_descendant_cannot_claim_complete_owning_family(family, child, expected):
    layout, before, action, _ = illustration_boundary(family=family)
    capture = capture_split(action, layout, before, {})
    admission = split_family_admission("part-1." + child, capture, layout, verify_split_paint_inputs(layout, {}))
    assert admission.family == expected
    assert not admission.proof_kind.endswith("illustration_closure_v1")


def split_timeline(layout, before, action):
    _, _, raw = split_documents(layout.output_profile.profile_id)
    raw.update(layout_sha256=digest(layout.model_dump(mode="json")), plan_sha256=layout.plan_sha256,
        actions=[action.model_dump(mode="json")],
        initial_object_states=[{"object_id": row.object_id, "state": row.state, "visible": row.visible,
            "state_version": dict(before.state_versions)[row.object_id]} for row in before.objects])
    return ResolvedVisualTimelineV2.model_validate(raw)


def native_reference(family, portrait):
    if family == "character":
        return original_pose_documents(portrait=portrait)
    if family == "technical":
        return composite_documents(portrait=portrait)
    return original_illustration_documents(portrait=portrait)


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("family,mode", [
    ("illustration", "reveal"), ("illustration", "enter"),
    ("character", "reveal"), ("character", "enter"), ("character", "draw"),
    ("technical", "reveal"), ("technical", "enter"),
])
def test_real_f03_owner_native_pixels_seek_frozen_inputs_and_every_ms_coverage(family, mode, portrait, monkeypatch, tmp_path):
    layout, before, action, _ = illustration_boundary(family=family, mode=mode, portrait=portrait)
    capture = capture_split(action, layout, before, {})
    inputs = verify_split_paint_inputs(layout, {})
    proof = prove_split_coverage(capture, layout, inputs)
    assert proof.critical_times_ms[0] == 0 and proof.critical_times_ms[-1] == 40
    assert proof.intervals[0].start_ms == 0 and proof.intervals[-1].end_ms == 40
    assert all(row.painted_root_ids and row.start_ms < row.end_ms for row in proof.intervals)
    assert proof.intervals[-1].painted_root_ids == ("part-1", "part-2")
    timeline = split_timeline(layout, before, action)
    replay = replay_split(layout, before, (action,), duration=timeline.duration_ms)
    cameras = camera_segments(layout, timeline, replay)
    original = repr((layout, before, action, capture, inputs))
    outputs = {}
    for at in (0, 12, 40):
        frame = _sample_validated_frame(layout, timeline, replay, cameras, at)
        svg = _compose_validated_svg_frame(layout, timeline, frame, {}, split_inputs=inputs)
        outputs[at] = (svg.svg, _rasterize_svg_frame(layout, svg, split_inputs=inputs).png)
    reference_layout, reference_timeline = native_reference(family, portrait)
    reference = Image.open(io.BytesIO(compose_png_frame(reference_layout, reference_timeline, 0).png)).convert("RGBA")
    final = Image.open(io.BytesIO(outputs[40][1])).convert("RGBA")
    offset = 80 if mode == "enter" else 0
    # Owning primitives already have independent literal native art oracles.
    # Split must retain their entire actual native crop, not a placeholder box.
    assert final.crop((100+offset, 180, 620+offset, 610)).tobytes() == reference.crop((100, 180, 620, 610)).tobytes()
    ink = (23, 32, 51, 255)
    point = {"illustration": (215, 325), "character": (335, 270), "technical": (105, 350)}[family]
    assert final.getpixel((point[0]+offset, point[1])) == ink
    tree = ET.fromstring(outputs[40][0])
    ids = [node.attrib["data-object-id"] for node in tree.iter() if "data-object-id" in node.attrib]
    assert all(ids.count(key) == 1 for key in capture.owned_object_ids if key != "source")
    (tmp_path / f"{family}-{mode}-final.png").write_bytes(outputs[40][1])
    def forbidden(*args, **kwargs):
        raise AssertionError("frozen F03 rendering attempted source IO or network")
    monkeypatch.setattr(Path, "read_bytes", forbidden)
    monkeypatch.setattr(socket, "connect", forbidden)
    for at in (40, 12, 0, 12, 40):
        frame = _sample_validated_frame(layout, timeline, replay, cameras, at)
        svg = _compose_validated_svg_frame(layout, timeline, frame, {}, split_inputs=inputs)
        assert (svg.svg, _rasterize_svg_frame(layout, svg, split_inputs=inputs).png) == outputs[at]
    assert repr((layout, before, action, capture, inputs)) == original
