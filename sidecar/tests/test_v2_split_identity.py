"""Content identity must not confuse authored meaning with mutable placement."""

import importlib
import importlib.util
import json
from copy import deepcopy
from dataclasses import dataclass, replace

import pytest
from atme.render.v2_hierarchy import HierarchySnapshot
from atme.render.v2_state import (
    CountFrameObject,
    FrameObject,
    FramePoint,
    FrameTransform,
)
from atme.render.v2_timeline_replay import ReplaySample
from atme.store.contracts_v2 import ExecutableLayoutV2, SplitPolicy, TextObject
from v2_split_fixtures import split_action, split_documents


def identity_module():
    name = "atme.render.v2_split_identity"
    assert importlib.util.find_spec(name) is not None, "Split identity boundary is not implemented"
    return importlib.import_module(name)


def identity_sample():
    _plan, raw, _timeline = split_documents()
    layout = ExecutableLayoutV2.model_validate(raw)
    return layout, sample_for_layout(layout)


def sample_for_layout(layout):
    objects = {obj.object_id: obj for obj in layout.objects}
    sample = ReplaySample(
        at_ms=0,
        objects=tuple(FrameObject(
            object_id=obj.object_id, board_id=obj.board_id, state=obj.initial_state,
            visible=obj.visible, opacity=obj.opacity, reveal_fraction=float(obj.visible),
            transform=FrameTransform.from_contract(obj.transform),
        ) for obj in sorted(layout.objects, key=lambda item: item.object_id)),
        state_versions=tuple((key, 1) for key in sorted(objects)),
        hierarchy=HierarchySnapshot.from_objects(objects),
    )
    return sample


def source_receipt(module, layout, sample):
    return next(item for item in module.split_content_receipts(layout, sample, {})
                if item.object_id == "source")


@pytest.mark.parametrize("free_point", [False, True])
def test_stored_connector_roundtrip_preserves_omitted_or_authored_source_point(free_point):
    from test_v2_connector_svg import connector_documents
    from test_v2_pointer_contract import pointer_payload

    module = identity_module()
    raw, _ = connector_documents()
    if free_point:
        raw["objects"][3] = pointer_payload()
    layout = ExecutableLayoutV2.model_validate(raw)
    connector = layout.objects[3]
    stored = module._stored_value(connector)
    if free_point:
        assert stored["source_point"] == {"x": 80.5, "y": 60.25}
    else:
        assert "source_point" not in connector.model_fields_set
        assert "source_point" not in stored
    restored = ExecutableLayoutV2.model_validate(module._stored_value(layout))
    assert restored.model_dump(mode="json") == layout.model_dump(mode="json")
    assert module.split_content_receipts(restored, sample_for_layout(restored), {}) == (
        module.split_content_receipts(layout, sample_for_layout(layout), {}))


@pytest.mark.parametrize("mutation", ["explicit_null", "unknown_fieldset", "missing_authority",
    "invalid_route", "missing_field", "unknown_field", "source_point_subclass", "unsafe_point"])
def test_stored_connector_rejects_unsafe_constructed_authority(mutation):
    from atme.store.contracts_v2 import PointerSourcePoint
    from test_v2_connector_svg import connector_documents

    module = identity_module()
    raw, _ = connector_documents()
    connector = ExecutableLayoutV2.model_validate(raw).objects[3]
    if mutation == "explicit_null":
        connector = connector.model_copy(update={"source_point": None})
    elif mutation == "unknown_fieldset":
        connector.__pydantic_fields_set__.add("unrecognized_authority")
    elif mutation == "missing_authority":
        connector.__pydantic_fields_set__.remove("destination_object_id")
    elif mutation == "invalid_route":
        connector = connector.model_copy(update={"routing": "invented"})
    elif mutation == "missing_field":
        del connector.__dict__["routing"]
    elif mutation == "unknown_field":
        connector.__dict__["unrecognized_authority"] = "must not be discarded"
    else:
        if mutation == "source_point_subclass":
            class UnrecognizedPoint(PointerSourcePoint):
                pass

            point = UnrecognizedPoint(x=2, y=3)
        else:
            point = PointerSourcePoint.model_construct(x=True, y=3)
        connector = connector.model_copy(update={"source_point": point, "role": "pointer",
            "source_object_id": None, "source_anchor_id": None})
    with pytest.raises(ValueError):
        module._stored_value(connector)


def test_content_basis_completion_are_distinct():
    module = identity_module()
    layout, sample = identity_sample()
    original = source_receipt(module, layout, sample)
    source = sample.object("source")
    moved = replace(source, state="removed", visible=False, opacity=0.0,
                    reveal_fraction=0.0,
                    transform=replace(source.transform, position=FramePoint(12.0, 20.0)))
    changed_pose = replace(sample, at_ms=99,
        objects=tuple(moved if item.object_id == "source" else item for item in sample.objects),
        state_versions=tuple((key, 2) for key, _value in sample.state_versions))
    assert source_receipt(module, layout, changed_pose) == original

    changed_layout = layout.model_copy(deep=True)
    obj = next(item for item in changed_layout.objects if item.object_id == "source")
    obj.geometry.bounds.width += 1.0
    assert source_receipt(module, changed_layout, sample).content_sha256 != original.content_sha256

    policy = SplitPolicy.model_validate(split_action()["split_policy"])
    changed_basis = policy.source_basis.model_copy(deep=True)
    placement = next(item for item in changed_basis.placements if item.object_id == "source")
    placement.local_transform.position.x += 12.0
    placement.state_version += 1
    assert module.split_basis_digest(changed_basis) != module.split_basis_digest(policy.source_basis)
    assert module.split_basis_digest(policy.source_basis) == policy.source_basis_sha256


def test_known_payloads_and_canonical_correspondence():
    module = identity_module()
    layout, sample = identity_sample()
    receipts = module.split_content_receipts(layout, sample, {})
    assert tuple(row.object_id for row in receipts) == ("part-1", "part-2", "source")
    assert all(json.loads(row.canonical_json) for row in receipts)
    policy = SplitPolicy.model_validate(split_action()["split_policy"])
    assert [row.result_object_id for row in policy.correspondences] == [
        row.object_id for row in policy.results]
    before = module.split_policy_digest(policy)
    changed = policy.model_copy(deep=True)
    changed.correspondences[0].statement = "A different explicit authorship statement"
    assert module.split_policy_digest(changed) != before


@pytest.mark.parametrize("mutation", ["unknown_frame", "unknown_object_field"])
def test_unknown_payloads_never_silently_disappear_from_identity(mutation):
    module = identity_module()
    layout, sample = identity_sample()
    if mutation == "unknown_frame":
        @dataclass(frozen=True)
        class UnknownFrame(FrameObject):
            unrecognized_meaning: str = "must not disappear"

        old = sample.object("source")
        rogue = UnknownFrame(**old.__dict__)
        sample = replace(sample, objects=tuple(
            rogue if item.object_id == "source" else item for item in sample.objects))
    else:
        layout = layout.model_copy(deep=True)
        obj = next(item for item in layout.objects if item.object_id == "source")
        obj.__dict__["unknown_family_field"] = "must not disappear"
    with pytest.raises(ValueError):
        module.split_content_receipts(layout, sample, {})


def test_content_receipt_retains_immutable_json_not_mutable_inputs():
    module = identity_module()
    layout, sample = identity_sample()
    receipt = source_receipt(module, layout, sample)
    captured = receipt.canonical_json
    next(item for item in layout.objects if item.object_id == "source").geometry.bounds.width = 40.0
    assert receipt.canonical_json == captured
    with pytest.raises((AttributeError, TypeError)):
        receipt.content_sha256 = "f" * 64


@pytest.mark.parametrize("change", ["glyph", "rational"])
def test_completed_count_identity_keeps_text_and_exact_rational(change):
    module = identity_module()
    layout, sample = identity_sample()
    old_obj = next(item for item in layout.objects if item.object_id == "source")
    raw = old_obj.model_dump(mode="json")
    raw.pop("path_data")
    raw.update(object_type="text", text="1", items=[])
    text = TextObject.model_validate(raw)
    layout = layout.model_copy(update={"objects": [
        text if item.object_id == "source" else item for item in layout.objects]})
    counted = CountFrameObject(**sample.object("source").__dict__, display_text="1", count_value=(1, 1))
    sample = replace(sample, objects=tuple(
        counted if item.object_id == "source" else item for item in sample.objects))
    before = source_receipt(module, layout, sample)
    changed = replace(counted, **({"display_text": "2"} if change == "glyph"
                                  else {"count_value": (3, 2)}))
    sample = replace(sample, objects=tuple(
        changed if item.object_id == "source" else item for item in sample.objects))
    assert source_receipt(module, layout, sample).content_sha256 != before.content_sha256


def test_morph_geometry_is_content_not_a_pose_change():
    from atme.render.v2_morph import MorphGeometry

    module = identity_module()
    layout, sample = identity_sample()
    before = source_receipt(module, layout, sample)
    geometry = MorphGeometry((10.0, 10.0, 21.0, 20.0), "M10 10 L31 10 L31 30 L10 30 Z")
    sample = replace(sample, objects=tuple(
        replace(item, morph_geometry=geometry) if item.object_id == "source" else item
        for item in sample.objects))
    assert source_receipt(module, layout, sample).content_sha256 != before.content_sha256


def test_completion_receipt_is_resolved_only_and_omitted_for_legacy_records():
    from atme.store import contracts_v2 as contracts

    assert hasattr(contracts, "SplitCompletionReceipt"), "strict completion receipt is missing"
    plan, _layout, timeline = split_documents()
    parsed = contracts.ResolvedAction.model_validate(timeline["actions"][0])
    assert "split_completion_receipt" not in parsed.model_dump(mode="json")
    invalid = deepcopy(plan["actions"][0])
    invalid["split_policy"]["completion_sha256"] = "f" * 64
    with pytest.raises(ValueError):
        contracts.SplitAction.model_validate(invalid)


def test_asset_content_hashes_actual_bytes_and_rejects_missing_payload():
    module = identity_module()
    layout, sample = identity_sample()
    obj = next(item for item in layout.objects if item.object_id == "source")
    obj.asset_id = "authored-asset"
    with pytest.raises(ValueError, match="actual nonempty asset bytes"):
        module.split_content_receipts(layout, sample, {})
    first = module.split_content_receipts(layout, sample, {"authored-asset": b"first"})
    second = module.split_content_receipts(layout, sample, {"authored-asset": b"second"})
    assert first[-1].content_sha256 != second[-1].content_sha256


@pytest.mark.parametrize("mutation", ["duplicate", "missing", "wrong_board"])
def test_frame_inventory_must_match_layout_exactly(mutation):
    module = identity_module()
    layout, sample = identity_sample()
    if mutation == "duplicate":
        sample = replace(sample, objects=(*sample.objects, sample.objects[0]))
    elif mutation == "missing":
        sample = replace(sample, objects=sample.objects[1:])
    else:
        sample = replace(sample, objects=(replace(sample.objects[0], board_id="wrong"),
                                          *sample.objects[1:]))
    with pytest.raises(ValueError):
        module.split_content_receipts(layout, sample, {})


def test_nonfinite_content_is_not_serialized_as_json_extension():
    module = identity_module()
    layout, sample = identity_sample()
    obj = next(item for item in layout.objects if item.object_id == "source")
    obj.geometry.bounds.width = float("nan")
    with pytest.raises(ValueError):
        module.split_content_receipts(layout, sample, {})


@pytest.mark.parametrize("field", ["position", "world_matrix", "world_corners"])
def test_basis_digest_uses_existing_four_decimal_pose_precision(field):
    module = identity_module()
    original = SplitPolicy.model_validate(split_action()["split_policy"])
    changed = original.source_basis.model_copy(deep=True)
    placement = changed.placements[0]
    if field == "position":
        placement.local_transform.position.x = 0.00001
    elif field == "world_matrix":
        placement.world_matrix = (1.0, 0.0, 0.0, 1.0, 0.00001, 0.0)
    else:
        placement.world_corners[0].x += 0.00001
    assert module.split_basis_digest(changed) == module.split_basis_digest(original.source_basis)
    # The contract must use the same digest boundary as capture/replay.
    raw = original.model_dump(mode="json")
    raw["source_basis"] = changed.model_dump(mode="json")
    SplitPolicy.model_validate(raw)


def test_basis_digest_does_not_quantize_nonpose_state_channels():
    module = identity_module()
    basis = SplitPolicy.model_validate(split_action()["split_policy"]).source_basis
    changed = basis.model_copy(deep=True)
    changed.placements[0].local_opacity -= 0.00001
    assert module.split_basis_digest(changed) != module.split_basis_digest(basis)


def test_policy_digest_includes_basis_hash_and_preserves_order():
    module = identity_module()
    policy = SplitPolicy.model_validate(split_action()["split_policy"])
    changed = policy.model_copy(deep=True)
    changed.source_basis_sha256 = "0" * 64
    assert module.split_policy_digest(changed) != module.split_policy_digest(policy)
    changed = policy.model_copy(deep=True)
    changed.results.reverse()
    assert module.split_policy_digest(changed) != module.split_policy_digest(policy)


def test_unknown_nested_geometry_subclass_is_not_admitted_as_known_content():
    from atme.store.contracts_v2 import Geometry

    class UnknownGeometry(Geometry):
        invented_part: str = "not an approved geometry channel"

    module = identity_module()
    layout, sample = identity_sample()
    obj = next(item for item in layout.objects if item.object_id == "source")
    obj.geometry = UnknownGeometry(**obj.geometry.model_dump())
    with pytest.raises(ValueError, match="unknown"):
        module.split_content_receipts(layout, sample, {})


@pytest.mark.parametrize("channel", ["emphasis_fraction", "cross_out_fraction"])
def test_transient_attention_paint_is_not_content(channel):
    module = identity_module()
    layout, sample = identity_sample()
    before = source_receipt(module, layout, sample)
    changed = replace(sample, objects=tuple(
        replace(item, **{channel: 0.5}) if item.object_id == "source" else item
        for item in sample.objects))
    assert source_receipt(module, layout, changed) == before


def test_clip_assignment_is_a_dependency_not_intrinsic_content():
    module = identity_module()
    layout, sample = identity_sample()
    before = source_receipt(module, layout, sample)
    next(item for item in layout.objects if item.object_id == "source").clip_id = "aperture"
    assert source_receipt(module, layout, sample) == before


def test_split_placement_retains_local_visibility_independently_of_effective_visibility():
    from atme.store.contracts_v2 import SplitPlacement

    raw = split_action()["split_policy"]["source_basis"]["placements"][0]
    raw["local_visibility"] = True
    raw["effective_visibility"] = False
    parsed = SplitPlacement.model_validate(raw)
    assert parsed.local_visibility is True
    assert parsed.effective_visibility is False
    for invalid in (None, 0, 1, "true"):
        raw["local_visibility"] = invalid
        with pytest.raises(ValueError):
            SplitPlacement.model_validate(raw)
    raw.pop("local_visibility")
    with pytest.raises(ValueError):
        SplitPlacement.model_validate(raw)


def completion_document():
    from v2_fixtures import digest

    _plan, _layout, timeline = split_documents()
    document = deepcopy(timeline["actions"][0])
    policy = document["action"]["split_policy"]
    basis = policy["source_basis"]
    child = deepcopy(basis["placements"][0])
    child.update(object_id="child", parent_id="part-1", sibling_ordinal=0,
                 local_visibility=True, effective_visibility=False, state="visible", reveal=1.0)
    basis["placements"].insert(0, child)
    basis["result_closures"][0]["owned_ids"].append("child")
    source_child = deepcopy(child)
    source_child.update(object_id="source-child", parent_id="source", effective_visibility=True)
    basis["placements"].append(source_child)
    basis["placements"].sort(key=lambda row: row["object_id"])
    basis["source_closure"]["owned_ids"].append("source-child")
    policy["source_basis_sha256"] = digest(basis)
    placements = deepcopy(basis["placements"])
    for row in placements:
        if row["object_id"] == "source":
            row.update(state="removed", local_visibility=False, effective_visibility=False,
                       local_opacity=0.0, reveal=0.0, state_version=2)
        elif row["object_id"].startswith("part-"):
            row.update(state="visible", local_visibility=True, effective_visibility=True,
                       reveal=1.0, state_version=2)
        elif row["object_id"] == "child":
            row["effective_visibility"] = True
        else:
            row["effective_visibility"] = False
    receipt = {"source_basis_sha256": digest(basis), "policy_sha256": digest(policy),
               "placements": placements, "read_dependencies": [], "asset_pins": [],
               "style_sha256": basis["style_sha256"], "registry_sha256": basis["registry_sha256"]}
    receipt["completion_sha256"] = digest(receipt)
    document["split_completion_receipt"] = receipt
    return document


def test_completion_digest_excludes_only_its_self_hash():
    from atme.store import contracts_v2 as contracts

    module = identity_module()
    assert hasattr(contracts, "SplitCompletionReceipt")
    raw = completion_document()["split_completion_receipt"]
    receipt = contracts.SplitCompletionReceipt.model_validate(raw)
    assert module.split_completion_digest(receipt) == raw["completion_sha256"]
    changed = receipt.model_copy(update={"completion_sha256": "0" * 64})
    assert module.split_completion_digest(changed) == module.split_completion_digest(receipt)
    changed = receipt.model_copy(update={"registry_sha256": "0" * 64})
    assert module.split_completion_digest(changed) != module.split_completion_digest(receipt)


@pytest.mark.parametrize("mutation", [None, "child_version", "child_local_visibility", "source_state",
    "source_reveal", "result_pose", "result_world", "result_state", "content", "missing",
    "extra", "order", "pin"])
def test_completion_is_rederived_not_authorized_by_its_own_checksum(mutation):
    from atme.store.contracts_v2 import ResolvedAction
    from v2_fixtures import digest

    document = completion_document()
    receipt = document["split_completion_receipt"]
    rows = {row["object_id"]: row for row in receipt["placements"]}
    if mutation == "child_version":
        rows["child"]["state_version"] += 1
    elif mutation == "child_local_visibility":
        rows["child"]["local_visibility"] = False
    elif mutation == "source_state":
        rows["source"]["state"] = "visible"
    elif mutation == "source_reveal":
        rows["source"]["reveal"] = 1.0
    elif mutation == "result_pose":
        rows["part-1"]["local_transform"]["position"]["x"] += 1
    elif mutation == "result_world":
        rows["part-1"]["world_matrix"][4] += 1
    elif mutation == "result_state":
        rows["part-1"]["state"] = "hidden"
    elif mutation == "content":
        rows["part-1"]["content_sha256"] = "0" * 64
    elif mutation == "missing":
        receipt["placements"].pop()
    elif mutation == "extra":
        receipt["placements"].append(deepcopy(rows["child"]))
    elif mutation == "order":
        receipt["placements"].reverse()
    elif mutation == "pin":
        receipt["style_sha256"] = "0" * 64
    receipt["completion_sha256"] = digest({key: value for key, value in receipt.items()
                                            if key != "completion_sha256"})
    if mutation is None:
        assert ResolvedAction.model_validate(document).split_completion_receipt is not None
    else:
        with pytest.raises(ValueError):
            ResolvedAction.model_validate(document)


def test_completion_preserves_child_local_records_while_recomputing_effective_visibility():
    from atme.store.contracts_v2 import ResolvedAction

    parsed = ResolvedAction.model_validate(completion_document())
    rows = {row.object_id: row for row in parsed.split_completion_receipt.placements}
    assert rows["source"].reveal == 0.0
    for key in ("child", "source-child"):
        assert rows[key].local_visibility is True
        assert rows[key].reveal == 1.0
        assert rows[key].state_version == 1
        assert rows[key].state == "visible"
    assert rows["child"].effective_visibility is True
    assert rows["source-child"].effective_visibility is False


@pytest.mark.parametrize("mutation", [None, "raw", "object", "treatment", "checksum", "revision",
                                     "width", "height", "payload", "missing_treatment", "unknown_field"])
def test_evidence_content_requires_exact_attested_bytes_and_layout_treatment(tmp_path, mutation):
    from test_v2_evidence_compositor import evidence_documents

    module = identity_module()
    _service, raw, _timeline, verified = evidence_documents(tmp_path)
    layout = ExecutableLayoutV2.model_validate(raw)
    sample = sample_for_layout(layout)
    payload = verified
    if mutation == "raw":
        payload = verified.payload
    elif mutation == "object":
        changed = verified.treatment.model_copy(update={"object_id": "wrong-object"})
        payload = replace(verified, treatment=changed)
    elif mutation == "treatment":
        changed = verified.treatment.model_copy(deep=True)
        changed.intent.source_label = "Wrong label"
        payload = replace(verified, treatment=changed)
    elif mutation == "checksum":
        payload = replace(verified, sha256="0" * 64)
    elif mutation == "revision":
        payload = replace(verified, revision=verified.revision + 1)
    elif mutation == "width":
        payload = replace(verified, width=0)
    elif mutation == "height":
        payload = replace(verified, height=verified.height + 1)
    elif mutation == "payload":
        payload = replace(verified, payload=b"not the immutable evidence bytes")
    elif mutation == "missing_treatment":
        layout = layout.model_copy(update={"evidence_treatments": []})
    elif mutation == "unknown_field":
        payload.__dict__["unknown_field"] = "must reject"
    if mutation is None:
        receipts = module.split_content_receipts(layout, sample, {verified.asset_id: payload})
        assert len(receipts) == len(layout.objects)
    else:
        with pytest.raises(ValueError):
            module.split_content_receipts(layout, sample, {verified.asset_id: payload})


@pytest.mark.parametrize("mutation", ["negative_bounds", "nonfinite", "unknown_field", "subclass"])
def test_morph_content_requires_known_finite_positive_geometry(mutation):
    from atme.render.v2_morph import MorphGeometry

    module = identity_module()
    layout, sample = identity_sample()
    geometry = MorphGeometry((10.0, 10.0, 20.0, 20.0), "M10 10 L30 30")
    if mutation == "negative_bounds":
        geometry = replace(geometry, bounds=(10.0, 10.0, -1.0, 20.0))
    elif mutation == "nonfinite":
        geometry = replace(geometry, bounds=(float("inf"), 10.0, 20.0, 20.0))
    elif mutation == "unknown_field":
        geometry.__dict__["unrecognized"] = "must reject"
    else:
        @dataclass(frozen=True)
        class UnknownMorph(MorphGeometry):
            unrecognized: str = "must reject"
        geometry = UnknownMorph(geometry.bounds, geometry.svg_d)
    sample = replace(sample, objects=tuple(
        replace(item, morph_geometry=geometry) if item.object_id == "source" else item
        for item in sample.objects))
    with pytest.raises(ValueError):
        module.split_content_receipts(layout, sample, {})


def compound_sample(container_type="group"):
    from atme.store.contracts_v2 import ClipContainer, GroupContainer, MaskContainer

    layout, _sample = identity_sample()
    source = next(item for item in layout.objects if item.object_id == "source")
    raw = source.model_dump(mode="json")
    raw.pop("path_data")
    outer = GroupContainer.model_validate({**raw, "object_id": "outer", "object_type": "group",
                                          "child_ids": ["inner", "aperture"]})
    inner_raw = {**raw, "object_id": "inner", "object_type": container_type,
                 "parent_id": "outer", "child_ids": ["source", "part-1"]}
    cls = {"group": GroupContainer, "clip": ClipContainer, "mask": MaskContainer}[container_type]
    if container_type == "mask":
        inner_raw.update(mask_mode="alpha", mask_source_object_id="aperture",
                         mask_coordinate_space="parent_local", invert=False, feather_px=0)
    inner = cls.model_validate(inner_raw)
    aperture = source.model_copy(update={"object_id": "aperture", "parent_id": "outer"}, deep=True)
    objects = [item.model_copy(update={"parent_id": "inner"}, deep=True)
               if item.object_id in ("source", "part-1") else item for item in layout.objects]
    layout = layout.model_copy(update={"objects": [*objects, outer, inner, aperture]})
    return layout, sample_for_layout(layout)


@pytest.mark.parametrize("container_type", ["group", "clip", "mask"])
def test_compound_identity_tracks_child_content_but_not_sibling_paint_order(container_type):
    module = identity_module()
    layout, sample = compound_sample(container_type)
    receipts = {row.object_id: row for row in module.split_content_receipts(layout, sample, {})}
    swapped = replace(sample, hierarchy=HierarchySnapshot(tuple(
        replace(node, sibling_ordinal=1 - node.sibling_ordinal)
        if node.parent_id == "inner" else node for node in sample.hierarchy.nodes)))
    assert module.split_content_receipts(layout, swapped, {}) == tuple(
        receipts[key] for key in sorted(receipts))
    changed = layout.model_copy(deep=True)
    next(item for item in changed.objects if item.object_id == "source").geometry.bounds.width += 1
    mutated = {row.object_id: row for row in module.split_content_receipts(changed, sample, {})}
    for key in ("source", "inner", "outer"):
        assert mutated[key].content_sha256 != receipts[key].content_sha256
    assert mutated["part-2"] == receipts["part-2"]


def test_compound_membership_uses_current_hierarchy_and_ignores_unrelated_content():
    module = identity_module()
    layout, sample = compound_sample()
    receipts = {row.object_id: row for row in module.split_content_receipts(layout, sample, {})}
    parents = {node.object_id: node.parent_id for node in sample.hierarchy.nodes}
    parents["source"] = "outer"
    siblings = {}
    nodes = []
    for node in sample.hierarchy.nodes:
        parent = parents[node.object_id]
        ordinal = siblings.setdefault((node.board_id, parent), 0)
        nodes.append(replace(node, parent_id=parent, sibling_ordinal=ordinal))
        siblings[(node.board_id, parent)] += 1
    changed = replace(sample, hierarchy=HierarchySnapshot(tuple(nodes)))
    moved = {row.object_id: row for row in module.split_content_receipts(layout, changed, {})}
    assert moved["inner"].content_sha256 != receipts["inner"].content_sha256
    assert moved["outer"].content_sha256 != receipts["outer"].content_sha256
    assert moved["source"] == receipts["source"]
    layout.objects.reverse()
    assert module.split_content_receipts(layout, changed, {}) == tuple(moved[key] for key in sorted(moved))
    next(item for item in layout.objects if item.object_id == "part-2").geometry.bounds.width += 1
    unrelated = {row.object_id: row for row in module.split_content_receipts(layout, changed, {})}
    assert unrelated["outer"] == moved["outer"]


@pytest.mark.parametrize("mutation", ["cycle", "missing_parent", "missing_node"])
def test_compound_invalid_hierarchy_fails_closed(mutation):
    module = identity_module()
    layout, sample = compound_sample()
    if mutation == "missing_node":
        nodes = sample.hierarchy.nodes[1:]
    else:
        nodes = tuple(replace(node, parent_id="inner" if mutation == "cycle" else "missing")
                      if node.object_id == "outer" else node for node in sample.hierarchy.nodes)
    sample = replace(sample, hierarchy=HierarchySnapshot(nodes))
    with pytest.raises(ValueError):
        module.split_content_receipts(layout, sample, {})


@pytest.mark.parametrize("family,field,value", [
    ("mark", "path_data", "M10 10 L30 30"), ("text", "text", "Changed Ω"),
    ("text", "items", ["One", "Two"]), ("visual", "variant", "authored-version-2"),
    ("connector", "source_anchor_id", "edge"), ("connector", "destination_anchor_id", "edge"),
    ("connector", "destination_object_id", "part-2"), ("connector", "source_object_id", "part-2"),
    ("connector", "routing", "elbow"), ("connector", "role", "pointer"),
    ("connector", "allow_self_loop", True),
])
def test_every_concrete_family_payload_change_affects_identity(family, field, value):
    from atme.store.contracts_v2 import ConnectorObject, VisualObject

    module = identity_module()
    layout, sample = identity_sample()
    original = next(item for item in layout.objects if item.object_id == "source")
    raw = original.model_dump(mode="json")
    if family != "mark":
        raw.pop("path_data")
    if family == "text":
        obj = TextObject.model_validate({**raw, "object_type": "text", "text": "Original", "items": []})
    elif family == "visual":
        obj = VisualObject.model_validate({**raw, "object_type": "composition", "variant": "original"})
    elif family == "connector":
        obj = ConnectorObject.model_validate({**raw, "object_type": "arrow", "source_object_id": "part-1",
            "source_anchor_id": "center", "destination_object_id": "source", "destination_anchor_id": "center",
            "role": "semantic_connector", "routing": "straight"})
    else:
        obj = original
    layout = layout.model_copy(update={"objects": [obj if item.object_id == "source" else item
                                                  for item in layout.objects]})
    before = source_receipt(module, layout, sample)
    setattr(obj, field, value)
    assert source_receipt(module, layout, sample).content_sha256 != before.content_sha256


@pytest.mark.parametrize("channel", ["style", "points", "corner_radius", "morph_path"])
def test_authored_style_and_geometry_channels_are_content(channel):
    from atme.render.v2_morph import MorphGeometry
    from atme.store.contracts_v2 import Point

    module = identity_module()
    layout, sample = identity_sample()
    before = source_receipt(module, layout, sample)
    obj = next(item for item in layout.objects if item.object_id == "source")
    if channel == "style":
        obj.style.stroke = "authored.new.stroke"
    elif channel == "points":
        obj.geometry.points.append(Point(x=15, y=20))
    elif channel == "corner_radius":
        obj.geometry.corner_radius = 3
    else:
        sample = replace(sample, objects=tuple(replace(item,
            morph_geometry=MorphGeometry((10.0, 10.0, 20.0, 20.0), "M10 10 L30 30"))
            if item.object_id == "source" else item for item in sample.objects))
    assert source_receipt(module, layout, sample).content_sha256 != before.content_sha256


@pytest.mark.parametrize("field", ["style_sha256", "registry_sha256", "asset_revision", "asset_uri", "asset_checksum"])
def test_basis_binds_style_registry_and_asset_revision_pins(field):
    from atme.store.contracts_v2 import SplitAssetPin

    module = identity_module()
    basis = SplitPolicy.model_validate(split_action()["split_policy"]).source_basis
    basis.asset_pins = [SplitAssetPin(asset_id="asset", revision=1, resource_uri="project:asset/1",
                                    checksum_sha256="a" * 64)]
    changed = basis.model_copy(deep=True)
    if field in ("style_sha256", "registry_sha256"):
        setattr(changed, field, "0" * 64)
    elif field == "asset_revision":
        changed.asset_pins[0].revision += 1
    elif field == "asset_uri":
        changed.asset_pins[0].resource_uri = "project:asset/2"
    else:
        changed.asset_pins[0].checksum_sha256 = "0" * 64
    assert module.split_basis_digest(changed) != module.split_basis_digest(basis)


def test_evidence_revision_binding_is_separate_from_unchanged_content_bytes(tmp_path):
    from test_v2_evidence_compositor import evidence_documents

    module = identity_module()
    _service, raw, _timeline, verified = evidence_documents(tmp_path)
    layout = ExecutableLayoutV2.model_validate(raw)
    sample = sample_for_layout(layout)
    before = module.split_content_receipts(layout, sample, {verified.asset_id: verified})
    changed = layout.model_copy(deep=True)
    changed.evidence_treatments[0].asset_revision += 1
    changed.evidence_treatments[0].asset_managed_ref += "/new-revision"
    new_payload = replace(verified, revision=verified.revision + 1,
                          treatment=changed.evidence_treatments[0])
    assert module.split_content_receipts(changed, sample, {verified.asset_id: new_payload}) == before


@pytest.mark.parametrize("field", ["state", "local_visibility", "effective_visibility", "reveal",
    "local_opacity", "state_version", "parent_id", "sibling_ordinal", "read_dependencies"])
def test_each_mutable_basis_channel_changes_basis_identity(field):
    from atme.store.contracts_v2 import SplitReadDependency

    module = identity_module()
    basis = SplitPolicy.model_validate(split_action()["split_policy"]).source_basis
    changed = basis.model_copy(deep=True)
    values = {"state": "different", "local_visibility": True, "effective_visibility": True,
              "reveal": 0.5, "local_opacity": 0.5, "state_version": 2,
              "parent_id": "source", "sibling_ordinal": 99}
    if field == "read_dependencies":
        changed.read_dependencies = [SplitReadDependency(kind="ancestor", object_ids=["source"])]
    else:
        setattr(changed.placements[0], field, values[field])
    assert module.split_basis_digest(changed) != module.split_basis_digest(basis)


@pytest.mark.parametrize("mutation", ["own_hash", "basis_hash", "policy_hash", "dependency", "asset_pin",
                                      "registry", "descendant_bounds", "descendant_pose"])
def test_completion_binds_every_retained_identity(mutation):
    from atme.store.contracts_v2 import ResolvedAction
    from v2_fixtures import digest

    document = completion_document()
    receipt = document["split_completion_receipt"]
    if mutation == "own_hash":
        receipt["completion_sha256"] = "0" * 64
    else:
        if mutation == "basis_hash":
            receipt["source_basis_sha256"] = "0" * 64
        elif mutation == "policy_hash":
            receipt["policy_sha256"] = "0" * 64
        elif mutation == "dependency":
            receipt["read_dependencies"] = [{"kind": "ancestor", "object_ids": ["source"]}]
        elif mutation == "asset_pin":
            receipt["asset_pins"] = [{"asset_id": "wrong", "revision": 1,
                "resource_uri": "project:wrong", "checksum_sha256": "0" * 64}]
        elif mutation == "registry":
            receipt["registry_sha256"] = "0" * 64
        elif mutation == "descendant_bounds":
            receipt["placements"][0]["local_content_bounds"]["width"] += 1
        else:
            receipt["placements"][0]["local_transform"]["position"]["x"] += 1
        receipt["completion_sha256"] = digest({key: value for key, value in receipt.items()
                                                if key != "completion_sha256"})
    with pytest.raises(ValueError):
        ResolvedAction.model_validate(document)


def test_completion_receipt_rejects_unrelated_action_and_extra_fields():
    from atme.store.contracts_v2 import ResolvedAction, SplitCompletionReceipt

    document = completion_document()
    document["action"].pop("split_policy")
    with pytest.raises(ValueError):
        ResolvedAction.model_validate(document)
    raw = document["split_completion_receipt"]
    raw["unknown_field"] = "must reject"
    with pytest.raises(ValueError):
        SplitCompletionReceipt.model_validate(raw)


def test_mask_policy_and_source_identity_are_explicit_content():
    module = identity_module()
    layout, sample = compound_sample("mask")
    before = module.split_content_receipts(layout, sample, {})
    inner = next(item for item in layout.objects if item.object_id == "inner")
    inner.mask_source_object_id = "part-2"
    after = module.split_content_receipts(layout, sample, {})
    assert next(row for row in before if row.object_id == "inner").content_sha256 != next(
        row for row in after if row.object_id == "inner").content_sha256


def test_canonical_content_handles_unicode_and_immutable_nested_inputs():
    module = identity_module()
    layout, sample = identity_sample()
    raw = next(item for item in layout.objects if item.object_id == "source").model_dump(mode="json")
    raw.pop("path_data")
    text = TextObject.model_validate({**raw, "object_type": "text", "text": "Ω café 漢字", "items": []})
    layout.objects = [text if item.object_id == "source" else item for item in layout.objects]
    receipt = source_receipt(module, layout, sample)
    assert json.loads(receipt.canonical_json)["text"] == "Ω café 漢字"
    text.items.append("Changed")
    assert json.loads(receipt.canonical_json)["items"] == []


@pytest.mark.parametrize("mutation", ["width_bool", "height_bool", "custom_treatment", "id_subclass", "sha_subclass"])
def test_evidence_attestation_requires_exact_primitive_and_model_types(tmp_path, mutation):
    import hashlib
    import io

    from atme.store.contracts_v2 import Bounds
    from PIL import Image
    from test_v2_evidence_compositor import evidence_documents

    module = identity_module()
    _service, raw, _timeline, verified = evidence_documents(tmp_path)
    layout = ExecutableLayoutV2.model_validate(raw)
    treatment = layout.evidence_treatments[0]
    output = io.BytesIO()
    Image.new("RGBA", (1, 1), (10, 20, 30, 255)).save(output, format="PNG")
    payload = output.getvalue()
    sha = hashlib.sha256(payload).hexdigest()
    treatment.asset_width = treatment.asset_height = 1
    treatment.asset_checksum_sha256 = treatment.asset_provenance.checksum_sha256 = sha
    treatment.intent.crop = treatment.intent.focus_region = Bounds(x=0, y=0, width=1, height=1)
    attestation = replace(verified, payload=payload, sha256=sha, width=1, height=1, treatment=treatment)
    sample = sample_for_layout(layout)
    assert module.split_content_receipts(layout, sample, {verified.asset_id: attestation})
    if mutation == "width_bool":
        attestation = replace(attestation, width=True)
    elif mutation == "height_bool":
        attestation = replace(attestation, height=True)
    elif mutation == "custom_treatment":
        class CustomTreatment:
            intent = treatment.intent

            def __eq__(self, other):
                return True
        attestation = replace(attestation, treatment=CustomTreatment())
    else:
        class CustomString(str):
            pass
        attestation = replace(attestation, **{"asset_id" if mutation == "id_subclass" else "sha256":
            CustomString(verified.asset_id if mutation == "id_subclass" else sha)})
    with pytest.raises(ValueError):
        module.split_content_receipts(layout, sample, {verified.asset_id: attestation})


@pytest.mark.parametrize("wrong_world", [False, True])
def test_completion_nonidentity_ancestor_and_moved_result_preserve_descendant_world(wrong_world):
    from atme.store.contracts_v2 import ResolvedAction
    from v2_fixtures import digest

    document = completion_document()
    policy = document["action"]["split_policy"]
    basis = policy["source_basis"]
    rows = {row["object_id"]: row for row in basis["placements"]}
    ancestor = deepcopy(rows["source"])
    ancestor.update(object_id="ancestor", parent_id=None, sibling_ordinal=0)
    ancestor["local_transform"]["position"] = {"x": 100.0, "y": 50.0}
    ancestor["local_transform"].update(scale_x=2.0, scale_y=3.0, origin={"x": 0.0, "y": 0.0})
    rows["ancestor"] = ancestor
    basis["read_dependencies"] = [{"kind": "ancestor", "object_ids": ["ancestor"]}]
    for key in ("source", "part-1", "part-2"):
        rows[key]["parent_id"] = "ancestor"
    rows["child"]["local_transform"]["position"] = {"x": 2.0, "y": 4.0}

    def authored_world(row, e, f):
        row["world_matrix"] = [2.0, 0.0, 0.0, 3.0, e, f]
        row["world_corners"] = [{"x": x, "y": y} for x, y in (
            (e + 20.0, f + 30.0), (e + 60.0, f + 30.0),
            (e + 60.0, f + 90.0), (e + 20.0, f + 90.0))]
        row["world_bounds"] = {"x": e + 20.0, "y": f + 30.0, "width": 40.0, "height": 60.0}

    for key, row in rows.items():
        authored_world(row, 94.0 if key == "child" else 90.0, 42.0 if key == "child" else 30.0)
    basis["placements"] = [rows[key] for key in sorted(rows)]
    result = policy["results"][0]
    result["destination"]["position"] = {"x": 5.0, "y": 7.0}
    result["movement"] = {"phase": {"start_tick": 6000, "end_tick": 10000, "easing": "linear"},
        "from_transform": deepcopy(rows["part-1"]["local_transform"]),
        "destination": deepcopy(result["destination"])}
    policy["source_basis_sha256"] = digest(basis)
    receipt = document["split_completion_receipt"]
    final = {row["object_id"]: deepcopy(row) for row in basis["placements"]}
    final["source"].update(state="removed", local_visibility=False, effective_visibility=False,
                           local_opacity=0.0, reveal=0.0, state_version=2)
    final["source-child"]["effective_visibility"] = False
    for key in ("part-1", "part-2"):
        final[key].update(state="visible", local_visibility=True, effective_visibility=True,
                          reveal=1.0, state_version=2)
    final["child"]["effective_visibility"] = True
    final["part-1"]["local_transform"] = deepcopy(result["destination"])
    authored_world(final["part-1"], 100.0, 51.0)
    authored_world(final["child"], 104.0, 63.0)
    receipt.update(source_basis_sha256=digest(basis), policy_sha256=digest(policy),
                   placements=[final[key] for key in sorted(final)],
                   read_dependencies=deepcopy(basis["read_dependencies"]))
    if wrong_world:
        final["child"]["world_matrix"][4] += 1.0
    receipt["completion_sha256"] = digest({key: value for key, value in receipt.items()
                                            if key != "completion_sha256"})
    if wrong_world:
        with pytest.raises(ValueError):
            ResolvedAction.model_validate(document)
    else:
        parsed = ResolvedAction.model_validate(document)
        child = next(row for row in parsed.split_completion_receipt.placements if row.object_id == "child")
        assert child.world_matrix == (2.0, 0.0, 0.0, 3.0, 104.0, 63.0)
        assert [(point.x, point.y) for point in child.world_corners] == [
            (124.0, 93.0), (164.0, 93.0), (164.0, 153.0), (124.0, 153.0)]
        assert child.world_bounds.model_dump() == {"x": 124.0, "y": 93.0, "width": 40.0, "height": 60.0}
        assert child.effective_visibility is True and child.local_visibility is True
        assert child.state_version == 1
        assert child.local_transform.position.x == 2.0 and child.local_transform.position.y == 4.0
