"""F03 authentic registry, whole-source and shared read-aperture boundaries."""

import io
import json
import xml.etree.ElementTree as ET
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256

import pytest
from PIL import Image
from test_v2_registry_binding import registry_object
from test_v2_registry_illustrations import illustration_documents
from test_v2_split_capture import geometry_boundary
from test_v2_split_code_family import code_split_frames
from test_v2_split_identity import sample_for_layout
from test_v2_split_visual_family import (
    authored_receipts,
    illustration_boundary,
    native_reference,
    split_timeline,
)
from v2_fixtures import digest

from atme.render.v2_split import _observed_split_placements, capture_split
from atme.render.v2_split_identity import SplitContentReceipt
from atme.render.v2_split_paint import (
    prove_split_coverage,
    split_family_admission,
    verify_split_paint_inputs,
)
from atme.render.v2_svg import compose_png_frame
from atme.store.contracts_v2 import (
    ExecutableLayoutV2,
    ResolvedAction,
    SplitPolicy,
    _split_expected_completion,
)


def boundary_receipts(objects):
    """Extend the independent authored oracle only for actual read apertures."""
    by_id = {obj["object_id"]: obj for obj in objects}
    receipts = {}
    def content(key):
        obj = by_id[key]
        if "child_ids" not in obj:
            row = authored_receipts([obj])[key]
        else:
            payload = {field: deepcopy(obj[field]) for field in
                ("object_type", "geometry", "style", "anchors", "asset_id")}
            for field in ("character_assembly", "illustration_assembly"):
                if field in obj:
                    payload[field] = deepcopy(obj[field])
            payload["children"] = [{"object_id": child, "content_sha256": content(child).content_sha256}
                for child in sorted(obj["child_ids"])]
            if obj["object_type"] == "mask":
                payload.update({field: deepcopy(obj[field]) for field in
                    ("mask_mode", "mask_source_object_id", "mask_coordinate_space", "invert", "feather_px")})
            encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            row = SplitContentReceipt(key, encoded, sha256(encoded.encode()).hexdigest())
        receipts[key] = row
        return row
    for key in by_id:
        content(key)
    return receipts


def finish(raw, action):
    assert len(raw["objects"]) <= 12
    raw["boards"][0]["object_ids"] = [obj["object_id"] for obj in raw["objects"]]
    layout = ExecutableLayoutV2.model_validate(raw)
    before = sample_for_layout(layout)
    receipts = boundary_receipts(raw["objects"])
    action = action.model_dump(mode="json") if isinstance(action, ResolvedAction) else deepcopy(action)
    action["end_ms"] = 40
    policy = action["action"]["split_policy"]
    basis = policy["source_basis"]
    dependencies = []
    parents = sorted({obj["parent_id"] for obj in raw["objects"] if obj["parent_id"] is not None})
    apertures = sorted(obj["object_id"] for obj in raw["objects"] if obj["object_type"] in {"clip", "mask"})
    masks = sorted(obj["mask_source_object_id"] for obj in raw["objects"] if obj["object_type"] == "mask")
    for kind, ids in (("ancestor", parents), ("aperture", apertures), ("mask_source", masks)):
        if ids:
            dependencies.append({"kind": kind, "object_ids": ids})
    basis["read_dependencies"] = dependencies
    objects = {obj.object_id: obj for obj in layout.objects}
    basis["placements"] = [row.model_dump(mode="json") for row in
        _observed_split_placements(before, objects, set(objects), receipts)]
    for row in policy["correspondences"]:
        row.update(source_content_sha256=receipts["source"].content_sha256,
            result_content_sha256=receipts[row["result_object_id"]].content_sha256)
    policy["source_basis_sha256"] = digest(basis)
    completion = _split_expected_completion(SplitPolicy.model_validate(policy))
    completion["completion_sha256"] = digest(completion)
    action["split_completion_receipt"] = completion
    return layout, before, ResolvedAction.model_validate(action), receipts


def registry_boundary(portrait=False, owner="part-1", mode="reveal"):
    layout, _, action = geometry_boundary()
    raw = layout.model_dump(mode="json")
    old = next(obj for obj in raw["objects"] if obj["object_id"] == owner)
    registry = registry_object()
    registry.update({field: deepcopy(old[field]) for field in
        ("object_id", "parent_id", "board_id", "beat_id", "coverage_ids", "initial_state", "visible", "z_index", "transform")})
    raw["objects"] = [registry if obj["object_id"] == owner else obj for obj in raw["objects"]]
    if portrait:
        raw["output_profile"].update(profile_id="SHORT_FORM_9_16", width=720, height=1280)
        raw["canvas"].update(width=720, height=1280)
    action = action.model_dump(mode="json")
    if owner != "source":
        result = next(row for row in action["action"]["split_policy"]["results"] if row["object_id"] == owner)
        result["construction"]["mode"] = mode
        if mode == "enter":
            result["destination"]["position"]["x"] = 80.
            result["construction"]["enter_destination"] = deepcopy(result["destination"])
    return finish(raw, action)


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("owner,mode", [("source", "reveal"), ("part-1", "reveal"), ("part-1", "enter")])
def test_authenticated_registry_identity_alpha_native_pixels_and_seek(portrait, owner, mode):
    layout, before, action, receipts = registry_boundary(portrait, owner, mode)
    capture = capture_split(action, layout, before, {})
    inputs = verify_split_paint_inputs(layout, {})
    admission = split_family_admission(owner, capture, layout, inputs)
    assert (admission.family, admission.proof_kind, admission.content_sha256) == (
        "registry illustration", "pinned_registry_alpha_v1", receipts[owner].content_sha256)
    evidence = next(json.loads(row) for row in inputs.paint_evidence if json.loads(row).get("object_id") == owner)
    assert len(evidence["paint"]["asset_sha256"]) == 64
    assert evidence["paint"]["alpha_bounds"] and evidence["paint"]["alpha_sha256"]
    proof = prove_split_coverage(capture, layout, inputs)
    assert proof.intervals[-1].painted_root_ids == ("part-1", "part-2")
    outputs = code_split_frames(layout, before, action, split_timeline(layout, before, action), inputs, (0, 12, 40, 0, 40))
    reference, clock = illustration_documents("person-collaborators", "character")
    # The owning fixture also contains unrelated label/rectangle actions.
    # Move those out of the crop; do not count their art as registry pixels.
    for unrelated in reference["objects"][:2]:
        unrelated["transform"] = deepcopy(unrelated["transform"])
        unrelated["transform"]["position"]["x"] = 2000.
    reference["objects"][2].update(geometry=registry_object()["geometry"],
        anchors=registry_object()["anchors"], registry_binding=registry_object()["registry_binding"])
    reference["output_profile"] = layout.output_profile.model_dump(mode="json")
    reference["canvas"] = layout.canvas.model_dump(mode="json")
    clock.update(output_profile=deepcopy(reference["output_profile"]), layout_sha256=digest(reference))
    expected = Image.open(io.BytesIO(compose_png_frame(reference, clock, 5000).png)).convert("RGBA")
    actual = Image.open(io.BytesIO(outputs[0 if owner == "source" else 40][1])).convert("RGBA")
    dx = 80 if owner != "source" and mode == "enter" else 0
    assert actual.crop((100+dx, 200, 400+dx, 500)).tobytes() == expected.crop((100, 200, 400, 500)).tobytes()


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("family", ["character", "illustration", "technical"])
def test_complete_original_source_fades_without_fragment_replacement(portrait, family):
    layout, before, action, _ = illustration_boundary(portrait=portrait, owner="source", family=family)
    inputs = verify_split_paint_inputs(layout, {})
    capture = capture_split(action, layout, before, {})
    proof = prove_split_coverage(capture, layout, inputs)
    assert proof.intervals[-1].painted_root_ids == ("part-1", "part-2")
    outputs = code_split_frames(layout, before, action, split_timeline(layout, before, action), inputs, (0, 12, 40, 12, 0))
    native, clock = native_reference(family, portrait)
    expected = Image.open(io.BytesIO(compose_png_frame(native, clock, 0).png)).convert("RGBA")
    initial, middle, final = [Image.open(io.BytesIO(outputs[at][1])).convert("RGBA") for at in (0, 12, 40)]
    box = (100, 180, 620, 610)
    assert initial.crop(box).tobytes() == expected.crop(box).tobytes()
    assert initial.crop(box).tobytes() != middle.crop(box).tobytes()
    assert final.crop(box).getextrema() == ((250, 250), (248, 248), (241, 241), (255, 255))
    ids = [node.attrib["data-object-id"] for node in ET.fromstring(outputs[40][0]).iter()
        if "data-object-id" in node.attrib]
    assert not set(capture.owned_object_ids).difference({"part-1", "part-2"}).intersection(ids)


def aperture_boundary(family, portrait, kind):
    layout, _, action, _ = illustration_boundary(family=family, kind="icon" if family == "illustration" else None,
        portrait=portrait)
    raw = layout.model_dump(mode="json")
    ancestor = deepcopy(next(obj for obj in raw["objects"] if obj["object_id"] == "source"))
    ancestor.pop("path_data")
    ancestor.update(object_id="read-stage", object_type=kind, child_ids=["source", "part-1", "part-2"],
        anchors=[], parent_id=None, style={"stroke": None, "fill": None, "text": None, "effect": None},
        initial_state="visible", visible=True, opacity=1.)
    ancestor["geometry"] = {"bounds": {"x": 0., "y": 0., "width": 380., "height": 650.},
        "points": [], "corner_radius": None}
    ancestor["transform"].update(position={"x": 37., "y": 13.}, origin={"x": 0., "y": 0.})
    if kind == "mask":
        ancestor.update(mask_mode="alpha", mask_source_object_id="mask-source",
            mask_coordinate_space="parent_local", invert=False, feather_px=0)
        mask = deepcopy(next(obj for obj in raw["objects"] if obj["object_id"] == "source"))
        mask.update(object_id="mask-source", parent_id=None, visible=True, initial_state="visible",
            geometry=deepcopy(ancestor["geometry"]), style=deepcopy(ancestor["style"]), anchors=[], z_index=9)
        raw["objects"].append(mask)
    for obj in raw["objects"]:
        if obj["object_id"] in {"source", "part-1", "part-2"}:
            obj["parent_id"] = "read-stage"
    raw["objects"].append(ancestor)
    return finish(raw, action)


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("kind", ["group", "clip", "mask"])
@pytest.mark.parametrize("family", ["character", "illustration", "technical"])
def test_complete_owners_reuse_actual_nonidentity_read_ancestry_and_apertures(family, kind, portrait):
    layout, before, action, _ = aperture_boundary(family, portrait, kind)
    capture = capture_split(action, layout, before, {})
    inputs = verify_split_paint_inputs(layout, {})
    assert split_family_admission("part-1", capture, layout, inputs).family != "compound"
    assert "read-stage" in capture.read_dependency_ids
    proof = prove_split_coverage(capture, layout, inputs)
    assert proof.intervals[-1].painted_root_ids == ("part-1", "part-2")
    frames = code_split_frames(layout, before, action, split_timeline(layout, before, action), inputs, (0, 12, 40, 12, 40))
    actual = Image.open(io.BytesIO(frames[40][1])).convert("RGBA")
    point = {"character": (335, 270), "illustration": (325, 435), "technical": (105, 350)}[family]
    assert actual.getpixel((point[0]+37, point[1]+13)) == (23, 32, 51, 255)
    # All three real owners straddle x=380; only their common authored aperture may cut them.
    if kind in {"clip", "mask"}:
        assert actual.crop((418, 200, 650, 610)).getextrema() == ((250, 250), (248, 248), (241, 241), (255, 255))
    ids = [node.attrib["data-object-id"] for node in ET.fromstring(frames[40][0]).iter()
        if "data-object-id" in node.attrib]
    assert ids.count("read-stage") == 1
    assert all(ids.count(key) == 1 for key in capture.owned_object_ids if key != "source")


@pytest.mark.parametrize("kind", ["group", "clip", "mask"])
@pytest.mark.parametrize("fault", ["transform", "content"])
def test_native_technical_read_ancestor_cannot_be_coherently_substituted(kind, fault):
    layout, before, action, _ = aperture_boundary("technical", False, kind)
    capture = capture_split(action, layout, before, {})
    if fault == "transform":
        old = next(row for row in capture.baseline if row.object_id == "read-stage")
        changed_frame = replace(old, transform=replace(old.transform,
            position=replace(old.transform.position, x=999.)))
        forged = replace(capture, baseline=tuple(changed_frame if row.object_id == old.object_id else row
            for row in capture.baseline))
        expected = "Split captured state differs from its placement"
    else:
        changed = layout.model_copy(deep=True)
        next(obj for obj in changed.objects if obj.object_id == "read-stage").geometry.bounds.width = 381.
        layout = changed
        forged = capture
        expected = "Split captured ancestor content differs"
    with pytest.raises(ValueError, match=expected):
        split_family_admission("part-1", forged, layout, verify_split_paint_inputs(layout, {}))


@pytest.mark.parametrize("fault", ["anchor", "binding", "registry_bytes"])
def test_authenticated_registry_never_accepts_anchor_alias_or_replaced_bytes(fault):
    layout, before, action, _ = registry_boundary()
    capture = capture_split(action, layout, before, {})
    inputs = verify_split_paint_inputs(layout, {})
    if fault == "registry_bytes":
        rows = tuple((name, checksum, value+b"changed") if name.endswith("person-collaborators.svg")
            else (name, checksum, value) for name, checksum, value in inputs.bundle_bytes)
        assert rows != inputs.bundle_bytes
        with pytest.raises(ValueError, match="Split frozen bundle row is invalid"):
            split_family_admission("part-1", capture, layout, replace(inputs, bundle_bytes=rows))
    else:
        changed = layout.model_copy(deep=True)
        obj = next(obj for obj in changed.objects if obj.object_id == "part-1")
        if fault == "anchor":
            obj.anchors[0].point.x += .1
        else:
            obj.registry_binding.anchor_mappings[0].registry_anchor_name = "right_person"
        with pytest.raises(ValueError, match="anchor|binding"):
            split_family_admission("part-1", capture, changed, verify_split_paint_inputs(changed, {}))


@pytest.mark.parametrize("portrait", [False, True])
def test_authored_semantic_order_cannot_reverse_real_registry_paint_order(portrait):
    layout, _, action, _ = registry_boundary(portrait)
    raw = layout.model_dump(mode="json")
    top = next(obj for obj in raw["objects"] if obj["object_id"] == "part-2")
    top["geometry"]["bounds"] = {"x": 100., "y": 200., "width": 300., "height": 300.}
    top["style"]["fill"] = "ink.accent"
    data = action.model_dump(mode="json")
    policy = data["action"]["split_policy"]
    policy["results"].reverse()
    policy["correspondences"].reverse()
    policy["source_basis"]["result_closures"].reverse()
    layout, before, action, _ = finish(raw, data)
    capture = capture_split(action, layout, before, {})
    inputs = verify_split_paint_inputs(layout, {})
    split_family_admission("part-1", capture, layout, inputs)
    frames = code_split_frames(layout, before, action, split_timeline(layout, before, action), inputs, (40, 0, 40))
    ids = [node.attrib["data-object-id"] for node in ET.fromstring(frames[40][0]).iter()
        if "data-object-id" in node.attrib]
    assert ids == ["part-1", "part-2"]
    assert [row.object_id for row in action.action.split_policy.results] == ["part-2", "part-1"]
    assert Image.open(io.BytesIO(frames[40][1])).convert("RGBA").getpixel((250, 350)) == (36, 87, 214, 255)
