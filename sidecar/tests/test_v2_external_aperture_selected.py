"""The real Split capture remains bounded without weakening full-map paint."""
from copy import deepcopy
from dataclasses import replace

import pytest
from atme.render.v2_split import _observed_split_placements, capture_split
from atme.render.v2_split_identity import split_content_receipts
from atme.render.v2_split_paint import (
    prove_split_coverage,
    verify_split_paint_inputs,
)
from atme.store.contracts_v2 import (
    ExecutableLayoutV2,
    ResolvedAction,
    SplitPolicy,
    _split_expected_completion,
)
from test_v2_split_capture import geometry_boundary
from test_v2_split_identity import sample_for_layout
from v2_fixtures import digest


def selected_boundary(kind="clip", *, outside=False, ancestor_consumer=False):
    layout, _before, split = geometry_boundary()
    raw = layout.model_dump(mode="json")
    owner = deepcopy(raw["objects"][0])
    owner.pop("path_data")
    owner.update(object_id="aperture", object_type=kind, child_ids=["unrelated-art"], initial_state="visible", visible=True,
                 style={"stroke": None, "fill": None, "text": None, "effect": None})
    owner["geometry"]["bounds"].update(x=0., y=0., width=100., height=100.)
    child = deepcopy(raw["objects"][0])
    child.update(object_id="unrelated-art", parent_id="aperture", initial_state="visible", visible=True)
    for obj in raw["objects"]:
        obj["clip_id"] = "aperture"
        if outside:
            obj["transform"]["position"]["x"] = 300.
    raw["objects"].extend([owner, child])
    if ancestor_consumer:
        parent, unrelated = deepcopy(owner), deepcopy(child)
        parent.update(object_id="external-parent", object_type="group", clip_id="aperture",
                      child_ids=["source", "part-1", "part-2", "unrelated-parent-child"])
        unrelated.update(object_id="unrelated-parent-child", parent_id="external-parent")
        for obj in raw["objects"][:3]:
            obj.update(parent_id="external-parent", clip_id=None)
        raw["objects"].extend([parent, unrelated])
    if kind == "mask":
        source = deepcopy(child)
        source.update(object_id="mask-source", parent_id=None,
                      style={"stroke": None, "fill": None, "text": None, "effect": None})
        source["geometry"]["bounds"] = deepcopy(owner["geometry"]["bounds"])
        raw["objects"].append(source)
        owner.update(mask_mode="alpha", mask_source_object_id="mask-source",
                     mask_coordinate_space="parent_local", invert=False, feather_px=0, anchors=[])
    raw["boards"][0]["object_ids"] = [obj["object_id"] for obj in raw["objects"]]
    layout = ExecutableLayoutV2.model_validate(raw)
    before = sample_for_layout(layout)
    objects = {obj.object_id: obj for obj in layout.objects}
    receipts = {row.object_id: row for row in split_content_receipts(layout, before, {})}
    packet = split.model_dump(mode="json")
    packet.update(start_ms=0, end_ms=40)
    policy = packet["action"]["split_policy"]
    basis = policy["source_basis"]
    basis["read_dependencies"] = [{"kind": "aperture", "object_ids": ["aperture"]}]
    bound = {"source", "part-1", "part-2", "aperture"}
    if ancestor_consumer:
        bound.add("external-parent")
        basis["read_dependencies"].insert(0, {"kind": "ancestor", "object_ids": ["external-parent"]})
    if kind == "mask":
        bound.add("mask-source")
        basis["read_dependencies"].append({"kind": "mask_source", "object_ids": ["mask-source"]})
    basis["placements"] = [row.model_dump(mode="json") for row in
        _observed_split_placements(before, objects, bound, receipts)]
    for row in policy["correspondences"]:
        row.update(source_content_sha256=receipts["source"].content_sha256,
                   result_content_sha256=receipts[row["result_object_id"]].content_sha256)
    if outside:
        for result in policy["results"]:
            result["destination"]["position"]["x"] = 300.
    policy["source_basis_sha256"] = digest(basis)
    completion = _split_expected_completion(SplitPolicy.model_validate(policy))
    completion["completion_sha256"] = digest(completion)
    packet["split_completion_receipt"] = completion
    return layout, capture_split(ResolvedAction.model_validate(packet), layout, before, {})


@pytest.mark.parametrize("kind", ["clip", "mask"])
def test_real_split_selected_paint_borrows_nonempty_owner_without_capturing_or_painting_its_unrelated_children(kind):
    layout, capture = selected_boundary(kind)
    assert "unrelated-art" not in {row.object_id for row in capture.baseline}
    owner = next(obj for obj in layout.objects if obj.object_id == "aperture")
    assert owner.child_ids == ["unrelated-art"]
    proof = prove_split_coverage(capture, layout, verify_split_paint_inputs(layout, {}))
    assert all(row.painted_root_ids for row in proof.intervals)
    assert {key for row in proof.intervals for key in row.painted_root_ids} == {"source", "part-1", "part-2"}
    assert owner.child_ids == ["unrelated-art"]


@pytest.mark.parametrize("kind", ["clip", "mask"])
def test_real_selected_aperture_cannot_approve_zero_painted_coverage(kind):
    layout, capture = selected_boundary(kind, outside=True)
    with pytest.raises(ValueError, match="Split.*zero painted coverage at 0 ms"):
        prove_split_coverage(capture, layout, verify_split_paint_inputs(layout, {}))


def test_real_captured_external_group_ancestor_keeps_its_uncaptured_sibling_outside_all_traversals():
    layout, capture = selected_boundary(ancestor_consumer=True)
    assert "unrelated-parent-child" not in {row.object_id for row in capture.baseline}
    assert "external-parent" in capture.read_dependency_ids
    proof = prove_split_coverage(capture, layout, verify_split_paint_inputs(layout, {}))
    assert all(row.painted_root_ids for row in proof.intervals)


def test_shared_compositor_never_infers_authoritative_board_from_visible_records():
    from atme.render.v2_split_paint import _checked_split_resources
    from atme.render.v2_svg import _compose_object_tree
    from test_v2_external_aperture_runtime import runtime_documents

    _plan, raw, _clock, _ids = runtime_documents("clip")
    layout = ExecutableLayoutV2.model_validate(raw)
    states = {row.object_id: row for row in sample_for_layout(layout).objects}
    objects = {obj.object_id: obj for obj in layout.objects}
    resources = _checked_split_resources(layout, verify_split_paint_inputs(layout, {}))
    with pytest.raises(ValueError, match="authoritative active board"):
        _compose_object_tree(objects, states, {key: i for i, key in enumerate(objects)},
                             resources[0], None, 1., {}, {}, {}, {}, resources)


@pytest.mark.parametrize("fault", ["object", "state", "owned_missing", "read_missing", "board", "no_context"])
def test_captured_subset_cannot_be_reused_with_another_map_sample_or_board(fault):
    from atme.render.v2_external_aperture import external_aperture_projections
    from atme.render.v2_split_paint import _split_coverage_context

    layout, capture = selected_boundary()
    inputs = verify_split_paint_inputs(layout, {})
    _resources, objects, states, _placements, _closures, _included, issue = _split_coverage_context(capture, layout, inputs)
    context = issue(0, states)
    board = context.active_board_id
    assert external_aperture_projections(objects, states, active_board=board, captured_subset=context)
    if fault == "object":
        objects["aperture"].geometry.bounds.width += 1.
    elif fault == "state":
        states["aperture"] = replace(states["aperture"], opacity=.5)
    elif fault in {"owned_missing", "read_missing"}:
        key = "source" if fault == "owned_missing" else "aperture"
        del objects[key]
        del states[key]
    elif fault == "board":
        board = "not-the-captured-board"
    else:
        context = None
    with pytest.raises(ValueError, match="captured subset|authoritative active board|complete reciprocal"):
        external_aperture_projections(objects, states, active_board=board, captured_subset=context)


@pytest.mark.parametrize("fault", ["map", "sample", "time"])
def test_post_authentication_issuer_rejects_mutated_inputs(fault):
    from atme.render.v2_split_paint import _split_coverage_context

    layout, capture = selected_boundary()
    _r, objects, states, _p, _c, _i, issue = _split_coverage_context(capture, layout, verify_split_paint_inputs(layout, {}))
    at_ms = 0
    if fault == "map":
        objects["aperture"].child_ids.clear()
    elif fault == "sample":
        states["source"] = replace(states["source"], opacity=.2)
    else:
        at_ms = -1
    with pytest.raises(ValueError, match="authenticated captured"):
        issue(at_ms, states)


def test_captured_subset_has_no_unauthenticated_constructor_or_mutable_transport():
    from dataclasses import FrozenInstanceError

    from atme.render.v2_external_aperture import ApertureCapturedSubset
    from atme.render.v2_split_paint import _split_coverage_context

    with pytest.raises(TypeError, match="only after live Split"):
        ApertureCapturedSubset()
    layout, capture = selected_boundary()
    _r, _o, states, _p, _c, _i, issue = _split_coverage_context(capture, layout, verify_split_paint_inputs(layout, {}))
    context = issue(0, states)
    with pytest.raises(FrozenInstanceError):
        context.missing_edges = frozenset()


def test_explicit_active_board_keeps_readiness_checks_even_when_another_board_has_visible_records():
    from atme.render.v2_split_paint import _checked_split_resources
    from atme.render.v2_svg import _compose_object_tree
    from test_v2_external_aperture_lifecycle import pure_sample

    raw, _clock, ids, objects, states, _versions = pure_sample("clip")
    layout = ExecutableLayoutV2.model_validate(raw)
    extra = objects[ids["art"]].model_copy(update={"object_id": "other-board-art", "board_id": "board-other", "parent_id": None})
    objects[extra.object_id] = extra
    states[extra.object_id] = replace(states[ids["art"]], object_id=extra.object_id, board_id=extra.board_id, visible=True)
    states[ids["aperture"]] = replace(states[ids["aperture"]], opacity=.5)
    resources = _checked_split_resources(layout, verify_split_paint_inputs(layout, {}))
    with pytest.raises(ValueError, match="fully ready opaque exclusive read branches"):
        _compose_object_tree(objects, states, {key: i for i, key in enumerate(objects)},
            resources[0], None, 1., {}, {}, {}, {}, resources, active_board_id=objects[ids["receiver"]].board_id)
