"""Split capture must bind the observed immutable boundary before mutation."""

import importlib
import importlib.util
import json
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace

import pytest
from atme.render.style_bundle import EXPECTED_REGISTRY_SHA256, EXPECTED_STYLE_SHA256
from atme.render.v2_split_identity import split_content_receipts
from atme.store.contracts_v2 import ResolvedAction
from test_v2_split_identity import identity_sample
from v2_fixtures import digest
from v2_split_fixtures import split_documents


def capture_module():
    name = "atme.render.v2_split"
    assert importlib.util.find_spec(name) is not None, "Split live capture boundary is missing"
    return importlib.import_module(name)


def geometry_boundary():
    layout, before = identity_sample()
    _plan, _layout, timeline = split_documents()
    raw = deepcopy(timeline["actions"][0])
    before = replace(before, at_ms=raw["start_ms"])
    policy = raw["action"]["split_policy"]
    basis = policy["source_basis"]
    receipts = {row.object_id: row for row in split_content_receipts(layout, before, {})}
    basis.update(style_sha256=EXPECTED_STYLE_SHA256, registry_sha256=EXPECTED_REGISTRY_SHA256)
    for placement in basis["placements"]:
        placement["content_sha256"] = receipts[placement["object_id"]].content_sha256
    for correspondence in policy["correspondences"]:
        correspondence["source_content_sha256"] = receipts["source"].content_sha256
        correspondence["result_content_sha256"] = receipts[correspondence["result_object_id"]].content_sha256
    policy["source_basis_sha256"] = digest(basis)
    placements = deepcopy(basis["placements"])
    for row in placements:
        source = row["object_id"] == "source"
        row.update(state="removed" if source else "visible", state_version=2,
                   local_visibility=not source, effective_visibility=not source,
                   reveal=0.0 if source else 1.0, local_opacity=0.0 if source else 1.0)
    completion = {"source_basis_sha256": digest(basis), "policy_sha256": digest(policy),
                  "placements": placements, "read_dependencies": [], "asset_pins": [],
                  "style_sha256": basis["style_sha256"], "registry_sha256": basis["registry_sha256"]}
    completion["completion_sha256"] = digest(completion)
    raw["split_completion_receipt"] = completion
    return layout, before, ResolvedAction.model_validate(raw)


def test_capture_records_exact_observed_immutable_frames_and_normalized_ownership():
    module = capture_module()
    layout, before, resolved = geometry_boundary()
    capture = module.capture_split(resolved, layout, before, {})
    assert capture.owned_root_ids == ("source", "part-1", "part-2")
    assert set(capture.owned_object_ids) == {"source", "part-1", "part-2"}
    assert set(capture.owned_object_ids).isdisjoint(capture.read_dependency_ids)
    assert capture.baseline == before.objects
    assert capture.start_ms == resolved.start_ms and capture.end_ms == resolved.end_ms
    stored = capture.policy_json
    resolved.action.split_policy.correspondences[0].statement = "Later caller mutation"
    layout.objects[0].geometry.bounds.width += 1
    assert capture.policy_json == stored
    assert json.loads(stored)["correspondences"][0]["statement"] == "Authored part"
    with pytest.raises(FrozenInstanceError):
        capture.start_ms = 99


def test_coherently_rehashed_stale_ordinal_cannot_replace_observed_boundary():
    module = capture_module()
    layout, before, resolved = geometry_boundary()
    assert module.capture_split(resolved, layout, before, {})
    raw = resolved.model_dump(mode="json")
    policy = raw["action"]["split_policy"]
    basis = policy["source_basis"]
    basis["placements"][0]["sibling_ordinal"] = 99
    policy["source_basis_sha256"] = digest(basis)
    receipt = raw["split_completion_receipt"]
    receipt["placements"][0]["sibling_ordinal"] = 99
    receipt.update(source_basis_sha256=digest(basis), policy_sha256=digest(policy))
    receipt["completion_sha256"] = digest({key: value for key, value in receipt.items()
                                            if key != "completion_sha256"})
    forged = ResolvedAction.model_validate(raw)
    with pytest.raises(ValueError):
        module.capture_split(forged, layout, before, {})


@pytest.mark.parametrize("mutation", ["source_hidden", "source_partial", "source_zero_alpha",
    "result_visible", "result_partial", "result_zero_alpha", "wrong_time", "duplicate_versions",
    "missing_version", "stale_version", "changed_geometry", "wrong_style", "wrong_registry"])
def test_capture_rechecks_observed_state_version_content_and_time(mutation):
    module = capture_module()
    layout, before, resolved = geometry_boundary()
    if mutation in ("source_hidden", "source_partial", "source_zero_alpha"):
        changes = {"source_hidden": {"visible": False}, "source_partial": {"reveal_fraction": 0.5},
                   "source_zero_alpha": {"opacity": 0.0}}[mutation]
        before = replace(before, objects=tuple(replace(frame, **changes) if frame.object_id == "source"
                                               else frame for frame in before.objects))
    elif mutation in ("result_visible", "result_partial", "result_zero_alpha"):
        changes = {"result_visible": {"state": "visible", "visible": True},
                   "result_partial": {"reveal_fraction": 0.5}, "result_zero_alpha": {"opacity": 0.0}}[mutation]
        before = replace(before, objects=tuple(replace(frame, **changes) if frame.object_id == "part-1"
                                               else frame for frame in before.objects))
    elif mutation == "wrong_time":
        before = replace(before, at_ms=before.at_ms + 1)
    elif mutation == "duplicate_versions":
        before = replace(before, state_versions=(*before.state_versions, before.state_versions[0]))
    elif mutation == "missing_version":
        before = replace(before, state_versions=before.state_versions[1:])
    elif mutation == "stale_version":
        before = replace(before, state_versions=tuple((key, value + 1) for key, value in before.state_versions))
    elif mutation == "changed_geometry":
        layout.objects[0].geometry.bounds.width += 1
    else:
        raw = resolved.model_dump(mode="json")
        policy = raw["action"]["split_policy"]
        field = "style_sha256" if mutation == "wrong_style" else "registry_sha256"
        policy["source_basis"][field] = "0" * 64
        policy["source_basis_sha256"] = digest(policy["source_basis"])
        receipt = raw["split_completion_receipt"]
        receipt[field] = "0" * 64
        receipt.update(source_basis_sha256=policy["source_basis_sha256"], policy_sha256=digest(policy))
        receipt["completion_sha256"] = digest({key: value for key, value in receipt.items()
                                                if key != "completion_sha256"})
        resolved = ResolvedAction.model_validate(raw)
    with pytest.raises(ValueError):
        module.capture_split(resolved, layout, before, {})


@pytest.mark.parametrize("parent,child", [("source", "part-1"), ("part-1", "source"), ("part-1", "part-2")])
def test_actual_nested_closures_reject_even_when_submitted_closures_are_disjoint(parent, child):
    from atme.render.v2_hierarchy import HierarchySnapshot
    from atme.store.contracts_v2 import GroupContainer

    module = capture_module()
    layout, before, resolved = geometry_boundary()
    raw = next(obj for obj in layout.objects if obj.object_id == parent).model_dump(mode="json")
    raw.pop("path_data")
    raw.update(object_type="group", child_ids=[child])
    group = GroupContainer.model_validate(raw)
    objects = [group if obj.object_id == parent else obj.model_copy(update={"parent_id": parent}, deep=True)
               if obj.object_id == child else obj for obj in layout.objects]
    layout = layout.model_copy(update={"objects": objects})
    before = replace(before, hierarchy=HierarchySnapshot.from_objects({obj.object_id: obj for obj in objects}))
    with pytest.raises(ValueError, match="overlap|nest"):
        module.capture_split(resolved, layout, before, {})


def test_known_captured_split_subclass_retains_legacy_capture_shape():
    from atme.render.v2_timeline_replay import CapturedAction

    module = capture_module()
    layout, before, resolved = geometry_boundary()
    capture = module.capture_split(resolved, layout, before, {})
    wrapped = module.CapturedSplitAction(resolved_index=0, resolved_json=resolved.model_dump_json(),
        baseline=before.objects, split_capture=capture)
    assert isinstance(wrapped, CapturedAction)
    assert wrapped.split_capture == capture
    assert wrapped.resolved == resolved
    with pytest.raises(FrozenInstanceError):
        wrapped.split_capture = None


def ancestor_boundary(*, aperture=False, distinct=False):
    from dataclasses import asdict

    from atme.render.v2_hierarchy import HierarchySnapshot
    from atme.render.v2_state import FrameObject, FrameTransform
    from atme.render.v2_timeline_replay import replay_chronology
    from atme.store.contracts_v2 import ExecutableLayoutV2
    from test_v2_split_contract import split_with_earlier_ancestor
    from test_v2_split_identity import sample_for_layout

    _plan, raw_layout, timeline = split_with_earlier_ancestor()
    ancestor = next(obj for obj in raw_layout["objects"] if obj["object_id"] == "earlier")
    if aperture:
        ancestor["object_type"] = "clip"
    ancestor["transform"].update(position={"x": 100.0, "y": 50.0}, scale_x=2.0, scale_y=3.0,
                                 origin={"x": 0.0, "y": 0.0})
    if distinct:
        ancestor["child_ids"].remove("part-1")
        next(obj for obj in raw_layout["objects"] if obj["object_id"] == "part-1")["parent_id"] = None
    layout = ExecutableLayoutV2.model_validate(raw_layout)
    objects = {obj.object_id: obj for obj in layout.objects}
    initial = sample_for_layout(layout)
    assert all(type(frame) is FrameObject and type(frame.transform) is FrameTransform for frame in initial.objects)
    prior = ResolvedAction.model_validate(timeline["actions"][0])
    replay = replay_chronology(objects, HierarchySnapshot.from_objects(objects),
        {frame.object_id: frame for frame in initial.objects}, dict(initial.state_versions), (prior,),
        tuple((window.board_id, window.start_ms, window.end_ms) for window in layout.activations),
        timeline["duration_ms"])
    raw = deepcopy(timeline["actions"][1])
    before = replay.at(raw["start_ms"])
    assert before.object("earlier").state == "visible"
    assert dict(before.state_versions)["earlier"] == 2
    policy = raw["action"]["split_policy"]
    basis = policy["source_basis"]
    if distinct:
        policy["parent_policy"] = "authored_distinct_parents"
    if aperture:
        basis["read_dependencies"].append({"kind": "aperture", "object_ids": ["earlier"]})
    content = {row.object_id: row.content_sha256 for row in split_content_receipts(layout, before, {})}
    nodes = {node.object_id: node for node in before.hierarchy.nodes}
    for row in basis["placements"]:
        frame = before.object(row["object_id"])
        row.update(content_sha256=content[row["object_id"]], parent_id=nodes[row["object_id"]].parent_id,
                   sibling_ordinal=nodes[row["object_id"]].sibling_ordinal,
                   local_transform=asdict(frame.transform), state=frame.state,
                   local_visibility=frame.visible, effective_visibility=frame.visible,
                   reveal=frame.reveal_fraction, local_opacity=frame.opacity,
                   state_version=dict(before.state_versions)[row["object_id"]],
                   world_matrix=[2.0, 0.0, 0.0, 3.0, 90.0, 30.0],
                   world_corners=[{"x": x, "y": y} for x, y in ((110.0, 60.0), (150.0, 60.0),
                                                                            (150.0, 120.0), (110.0, 120.0))],
                   world_bounds={"x": 110.0, "y": 60.0, "width": 40.0, "height": 60.0})
        if distinct and row["object_id"] == "part-1":
            row.update(world_matrix=[1.0, 0.0, 0.0, 1.0, 0.0, 0.0],
                       world_corners=[{"x": x, "y": y} for x, y in ((10.0, 10.0), (30.0, 10.0),
                                                                                (30.0, 30.0), (10.0, 30.0))],
                       world_bounds={"x": 10.0, "y": 10.0, "width": 20.0, "height": 20.0})
    basis.update(style_sha256=EXPECTED_STYLE_SHA256, registry_sha256=EXPECTED_REGISTRY_SHA256)
    for row in policy["correspondences"]:
        row.update(source_content_sha256=content["source"], result_content_sha256=content[row["result_object_id"]])
    policy["source_basis_sha256"] = digest(basis)
    final = deepcopy(basis["placements"])
    for row in final:
        if row["object_id"] == "earlier":
            continue
        source = row["object_id"] == "source"
        row.update(state="removed" if source else "visible", state_version=2,
                   local_visibility=not source, effective_visibility=not source,
                   reveal=0.0 if source else 1.0, local_opacity=0.0 if source else 1.0)
    receipt = {"source_basis_sha256": digest(basis), "policy_sha256": digest(policy), "placements": final,
               "read_dependencies": deepcopy(basis["read_dependencies"]), "asset_pins": [],
               "style_sha256": basis["style_sha256"], "registry_sha256": basis["registry_sha256"]}
    receipt["completion_sha256"] = digest(receipt)
    raw["split_completion_receipt"] = receipt
    return layout, before, ResolvedAction.model_validate(raw)


@pytest.mark.parametrize("aperture", [False, True])
@pytest.mark.parametrize("distinct", [False, True])
def test_capture_uses_completed_prior_history_and_nonidentity_ancestor_world(aperture, distinct):
    module = capture_module()
    layout, before, resolved = ancestor_boundary(aperture=aperture, distinct=distinct)
    captured = module.capture_split(resolved, layout, before, {})
    assert captured.read_dependency_ids == ("earlier",)
    actual = {row["object_id"]: row for row in json.loads(captured.basis_json)["placements"]}
    assert actual["source"]["parent_id"] == "earlier"
    assert actual["source"]["world_matrix"] == [2.0, 0.0, 0.0, 3.0, 90.0, 30.0]
    assert actual["earlier"]["state_version"] == 2
    assert actual["part-1"]["parent_id"] == (None if distinct else "earlier")


@pytest.mark.parametrize("aperture", [False, True])
def test_split_reserves_actual_ancestor_and_aperture_against_writes_but_allows_read_read(aperture):
    module = capture_module()
    layout, before, resolved = ancestor_boundary(aperture=aperture)
    captured = module.capture_split(resolved, layout, before, {})
    writer = peer_action("fade", target_ids=["earlier"], opacity=0.5)
    # Match this capture's later interval rather than the base fixture's clock.
    writer = writer.model_copy(update={"start_ms": resolved.start_ms, "end_ms": resolved.end_ms})
    with pytest.raises(ValueError, match="reservation.*earlier"):
        module.validate_split_reservations(captured, (writer,))
    reader = peer_action("connect", connector_id="unrelated-arrow", destination_object_id="earlier",
                         destination_anchor_id="center")
    reader = reader.model_copy(update={"start_ms": resolved.start_ms, "end_ms": resolved.end_ms})
    module.validate_split_reservations(captured, (reader,))


def test_coherent_stale_aperture_cannot_replace_actual_capture():
    from atme.store.contracts_v2 import SplitPolicy, _split_expected_completion

    module = capture_module()
    layout, before, resolved = ancestor_boundary(aperture=True)
    assert module.capture_split(resolved, layout, before, {})
    raw = resolved.model_dump(mode="json")
    policy = raw["action"]["split_policy"]
    aperture = next(row for row in policy["source_basis"]["placements"] if row["object_id"] == "earlier")
    aperture["content_sha256"] = "a" * 64
    policy["source_basis_sha256"] = digest(policy["source_basis"])
    receipt = _split_expected_completion(SplitPolicy.model_validate(policy))
    receipt["completion_sha256"] = digest(receipt)
    raw["split_completion_receipt"] = receipt
    forged = ResolvedAction.model_validate(raw)
    with pytest.raises(ValueError, match="actual observed history"):
        module.capture_split(forged, layout, before, {})


@pytest.mark.parametrize("reveal", [0.0, 0.5])
def test_source_under_unconstructed_ancestor_is_not_ready_even_with_full_local_reveal(reveal):
    module = capture_module()
    layout, before, resolved = ancestor_boundary()
    before = replace(before, objects=tuple(replace(frame, reveal_fraction=reveal)
        if frame.object_id == "earlier" else frame for frame in before.objects))
    # Make the submitted basis coherent too: merely comparing its hash cannot
    # replace the actual source-readiness condition.
    from atme.store.contracts_v2 import SplitPolicy, _split_expected_completion

    raw = resolved.model_dump(mode="json")
    policy = raw["action"]["split_policy"]
    next(row for row in policy["source_basis"]["placements"] if row["object_id"] == "earlier")["reveal"] = reveal
    policy["source_basis_sha256"] = digest(policy["source_basis"])
    receipt = _split_expected_completion(SplitPolicy.model_validate(policy))
    receipt["completion_sha256"] = digest(receipt)
    raw["split_completion_receipt"] = receipt
    with pytest.raises(ValueError, match="source.*fully revealed"):
        module.capture_split(ResolvedAction.model_validate(raw), layout, before, {})


def peer_action(verb, **parameters):
    """Author a distinct peer; never filter the owning Split by packet equality."""
    _, _, resolved = geometry_boundary()
    raw = resolved.model_dump(mode="json")
    raw.pop("split_completion_receipt")
    action = raw["action"]
    for field in ("split_policy", "container_id", "target_ids"):
        action.pop(field, None)
    action.update(action_id="peer", verb=verb, expected_state="visible", post_state="visible", **parameters)
    raw["action"] = action
    return ResolvedAction.model_validate(raw)


@pytest.mark.parametrize("verb,parameters", [
    ("reveal", {"target_ids": ["source"]}),
    ("fade", {"target_ids": ["part-1"], "opacity": 0.5}),
    ("replace", {"from_object_id": "unrelated", "to_object_id": "part-2"}),
    ("isolate", {"target_ids": ["unrelated"]}),
    ("connect", {"connector_id": "unrelated-arrow", "destination_object_id": "source",
                 "destination_anchor_id": "center"}),
    ("disconnect", {"connector_id": "unrelated-arrow", "destination_object_id": "part-1",
                    "destination_anchor_id": "center"}),
    ("annotate", {"target_ids": ["source"], "annotation_policy": {
        "annotation_object_ids": ["note"], "phases": [{"object_id": "note", "mode": "write", "weight": 1}],
        "readable_hold_ms": 100}}),
])
def test_split_reserves_owned_objects_against_writers_and_anchor_consumers(verb, parameters):
    module = capture_module()
    layout, before, resolved = geometry_boundary()
    captured = module.capture_split(resolved, layout, before, {})
    with pytest.raises(ValueError, match="reservation"):
        module.validate_split_reservations(captured, (peer_action(verb, **parameters),))


def test_split_reservation_allows_camera_unrelated_writes_and_touching_intervals():
    module = capture_module()
    layout, before, resolved = geometry_boundary()
    captured = module.capture_split(resolved, layout, before, {})
    camera = peer_action("camera_hold", target_ids=["source"], framing="wide", movement_purpose="orient")
    unrelated = peer_action("reveal", target_ids=["unrelated"])
    touching = peer_action("reveal", target_ids=["source"]).model_copy(update={
        "start_ms": resolved.end_ms, "end_ms": resolved.end_ms + 100})
    module.validate_split_reservations(captured, (camera, unrelated, touching))


def test_identical_peer_split_is_not_mistaken_for_the_owner():
    module = capture_module()
    layout, before, resolved = geometry_boundary()
    captured = module.capture_split(resolved, layout, before, {})
    peer = resolved.model_copy(deep=True)
    peer.action.action_id = "different-split-same-packet"
    with pytest.raises(ValueError, match="reservation"):
        module.validate_split_reservations(captured, (peer,))


@pytest.mark.parametrize("field,value", [("owned_object_ids", ()), ("owned_root_ids", ("source",)),
    ("baseline", ()), ("start_ms", True), ("read_dependency_ids", ("invented",))])
def test_forged_capture_cannot_bypass_reservations(field, value):
    module = capture_module()
    layout, before, resolved = geometry_boundary()
    captured = module.capture_split(resolved, layout, before, {})
    with pytest.raises(ValueError, match="capture"):
        module.validate_split_reservations(replace(captured, **{field: value}), ())


def test_mutable_layout_bypass_is_revalidated_before_capture():
    module = capture_module()
    layout, before, resolved = geometry_boundary()
    # This invalid local alpha is invisible to a frame-only observation/hash.
    layout.objects[0].opacity = -1.0
    with pytest.raises(ValueError):
        module.capture_split(resolved, layout, before, {})


def counted_boundary(*, group_after_count=False, group_first=False):
    from dataclasses import asdict

    from atme.render.v2_hierarchy_replay import completed_hierarchy_basis
    from atme.render.v2_timeline_replay import replay_chronology
    from atme.render.v2_world import world_matrix
    from atme.store.contracts_v2 import (
        ExecutableLayoutV2,
        HierarchyBasis,
        SplitPolicy,
        _split_expected_completion,
    )
    from test_v2_count_contract import count_policy
    from test_v2_split_identity import sample_for_layout
    from test_v2_timeline_replay import resolved as timed

    layout, _, split = geometry_boundary()
    raw_layout = layout.model_dump(mode="json")
    text = next(row for row in raw_layout["objects"] if row["object_id"] == "source")
    text.pop("path_data")
    text.update(object_type="text", text="0 widgets", items=[],
                style={"stroke": None, "fill": None, "text": "text.body", "effect": None})
    if group_after_count:
        shell = deepcopy(next(row for row in raw_layout["objects"] if row["object_id"] == "part-1"))
        shell.pop("path_data")
        shell.update(object_id="shell", object_type="group", initial_state="grouped", visible=True,
                     child_ids=["source"], z_index=0, anchors=[], clip_id=None)
        shell["style"].update(stroke=None, fill=None, text=None, effect=None)
        shell["transform"].update(position={"x": 100.0, "y": 50.0}, origin={"x": 0.0, "y": 0.0},
                                   scale_x=2.0, scale_y=3.0)
        for obj in raw_layout["objects"]:
            if obj["object_id"] == "source":
                obj["parent_id"] = "shell"
        raw_layout["objects"].append(shell)
        raw_layout["boards"][0]["object_ids"].append("shell")
    layout = ExecutableLayoutV2.model_validate(raw_layout)
    initial = sample_for_layout(layout)
    count = timed(peer_action("count", target_ids=["source"],
        count_policy=count_policy(text_object_id="source")).action, 0, 500)
    prior = [count]
    capture_at = 500
    if group_after_count:
        source_basis = completed_hierarchy_basis(initial.hierarchy, {row.object_id: row for row in initial.objects})
        destination = source_basis.model_dump(mode="json")
        for row in destination["placements"]:
            if row["object_id"] != "shell":
                row.update(parent_id=None, sibling_ordinal={"source": 1, "part-1": 2, "part-2": 3}[row["object_id"]])
                if row["object_id"] == "source":
                    row["local_transform"] = deepcopy(shell["transform"])
        destination_basis = HierarchyBasis.model_validate(destination)
        group = {key: value for key, value in count.action.model_dump(mode="json").items()
                 if key not in {"count_policy", "annotation", "annotation_policy"}}
        group.update(action_id="ungroup-after-count", verb="ungroup", easing="step", target_ids=["source"],
                     container_id="shell", expected_state="grouped", post_state="ungrouped", hierarchy_policy={
                         "member_root_ids": ["source"],
                         "source_basis": source_basis.model_dump(mode="json"), "source_basis_sha256": source_basis.checksum(),
                         "destination_basis": destination, "destination_basis_sha256": destination_basis.checksum(),
                         "changed_object_ids": ["part-1", "part-2", "shell", "source"], "preserve_world_transform": True})
        prior.append(timed(group, 500, 800))
        capture_at = 800
        if group_first:
            prior = [timed(group, 0, 300), timed(count.action, 300, 500)]
            capture_at = 500
    objects = {obj.object_id: obj for obj in layout.objects}
    replay = replay_chronology(objects, initial.hierarchy,
        {frame.object_id: frame for frame in initial.objects}, dict(initial.state_versions), tuple(prior),
        tuple((row.board_id, row.start_ms, row.end_ms) for row in layout.activations), 2000)
    before = replay.at(capture_at)
    raw = split.model_dump(mode="json")
    raw.update(start_ms=capture_at, end_ms=capture_at + 1000)
    policy = raw["action"]["split_policy"]
    content = {row.object_id: row.content_sha256 for row in split_content_receipts(layout, before, {})}
    for row in policy["source_basis"]["placements"]:
        row.update(content_sha256=content[row["object_id"]], state_version=dict(before.state_versions)[row["object_id"]])
        if group_after_count:
            frame = before.object(row["object_id"])
            row["sibling_ordinal"] = {"source": 1, "part-1": 2, "part-2": 3}[row["object_id"]]
            row["local_transform"] = asdict(frame.transform)
            projected = before.hierarchy.object_map(objects)
            matrix = world_matrix(projected[row["object_id"]], projected,
                                  {frame.object_id: frame.transform for frame in before.objects})
            row["world_matrix"] = [matrix.a, matrix.b, matrix.c, matrix.d, matrix.e, matrix.f]
            row["world_corners"] = [{"x": x, "y": y} for x, y in (matrix.point(x, y)
                for x, y in ((10, 10), (30, 10), (30, 30), (10, 30)))]
            row["world_bounds"] = ({"x": 110.0, "y": 60.0, "width": 40.0, "height": 60.0}
                if row["object_id"] == "source" else {"x": 10.0, "y": 10.0, "width": 20.0, "height": 20.0})
    for row in policy["correspondences"]:
        row.update(source_content_sha256=content["source"], result_content_sha256=content[row["result_object_id"]])
    policy["source_basis_sha256"] = digest(policy["source_basis"])
    receipt = _split_expected_completion(SplitPolicy.model_validate(policy))
    receipt["completion_sha256"] = digest(receipt)
    raw["split_completion_receipt"] = receipt
    return layout, initial, before, tuple(prior), ResolvedAction.model_validate(raw)


def test_direct_capture_rejects_count_payload_without_its_completed_origin():
    module = capture_module()
    layout, _, before, _, split = counted_boundary()
    with pytest.raises(ValueError, match="Count.*origin"):
        module.capture_split(split, layout, before, {})


def test_private_chronology_captures_same_time_completed_count_and_keeps_public_closed():
    from atme.render import v2_timeline_replay as replay_module

    layout, initial, before, prior, split = counted_boundary()
    captured = replay_module._capture_split_from_history(layout, initial, (*prior, split), 1, 2000, {})
    assert captured.resolved_index == 1
    assert captured.split_capture.baseline == before.objects
    source = next(frame for frame in captured.split_capture.baseline if frame.object_id == "source")
    assert source.display_text == "10 widgets" and source.count_value == (10, 1)
    assert not replay_module.supports_operator(split.action)
    with pytest.raises(replay_module.ReplayError, match="no chronological operator"):
        replay_module.replay_chronology({obj.object_id: obj for obj in layout.objects}, initial.hierarchy,
            {frame.object_id: frame for frame in initial.objects}, dict(initial.state_versions), (*prior, split),
            tuple((row.board_id, row.start_ms, row.end_ms) for row in layout.activations), 2000)


@pytest.mark.parametrize("reorder", [False, True])
@pytest.mark.parametrize("group_first", [False, True])
def test_count_origin_survives_group_version_change_and_authored_array_order(reorder, group_first):
    from atme.render.v2_timeline_replay import _capture_split_from_history

    layout, initial, before, prior, split = counted_boundary(group_after_count=True, group_first=group_first)
    # Authored object array order is not resolved chronological action order.
    if reorder:
        layout.objects.reverse()
    actions = (*prior, split)
    owner_index = 2
    capture = _capture_split_from_history(layout, initial, actions, owner_index, 2000, {}).split_capture
    source = next(row for row in json.loads(capture.basis_json)["placements"] if row["object_id"] == "source")
    assert source["state_version"] == 3
    assert source["parent_id"] is None and source["sibling_ordinal"] == 1
    assert source["world_matrix"] == [2.0, 0.0, 0.0, 3.0, 90.0, 30.0]
    assert before.object("source").display_text == "10 widgets"
    assert next(row for row in capture.baseline if row.object_id == "source") == before.object("source")


def test_stale_count_commit_version_cannot_replace_later_group_version():
    from atme.render.v2_timeline_replay import _capture_split_from_history
    from atme.store.contracts_v2 import SplitPolicy, _split_expected_completion

    layout, initial, _, prior, split = counted_boundary(group_after_count=True)
    raw = split.model_dump(mode="json")
    policy = raw["action"]["split_policy"]
    next(row for row in policy["source_basis"]["placements"] if row["object_id"] == "source")["state_version"] = 2
    policy["source_basis_sha256"] = digest(policy["source_basis"])
    receipt = _split_expected_completion(SplitPolicy.model_validate(policy))
    receipt["completion_sha256"] = digest(receipt)
    raw["split_completion_receipt"] = receipt
    with pytest.raises(ValueError, match="actual observed history"):
        _capture_split_from_history(layout, initial, (*prior, ResolvedAction.model_validate(raw)), 2, 2000, {})


def test_owner_included_in_peer_list_is_rejected_and_private_owner_index_is_exact():
    from atme.render.v2_timeline_replay import _capture_split_from_history

    module = capture_module()
    layout, before, split = geometry_boundary()
    capture = module.capture_split(split, layout, before, {})
    with pytest.raises(ValueError, match="reservation"):
        module.validate_split_reservations(capture, (split,))
    for invalid in (True, -1, 1):
        with pytest.raises(ValueError, match="owner index"):
            _capture_split_from_history(layout, before, (split,), invalid, 2000, {})


def test_group_reservation_includes_descendants_beyond_direct_changed_roots():
    from atme.store.contracts_v2 import GroupAction
    from test_v2_group_replacement import grouped_replacement_documents

    module = capture_module()
    _, timeline = grouped_replacement_documents()
    action = GroupAction.model_validate(next(row["action"] for row in timeline["actions"]
                                            if row["action"]["verb"] == "ungroup"))
    writes, reads = module._reservation_footprint(action)
    assert {"replacement-pair", "replacement-shell", "object-system", "object-replacement"} <= writes
    assert "replacement-outer" in reads
    assert "object-label" not in writes


@pytest.mark.parametrize("reorder", [False, True])
def test_private_capture_after_completed_morph_binds_destination_content_and_version(reorder):
    from atme.render.v2_timeline_replay import (
        _capture_split_from_history,
        replay_chronology,
    )
    from atme.store.contracts_v2 import (
        ExecutableLayoutV2,
        SplitPolicy,
        _split_expected_completion,
    )
    from test_v2_split_identity import sample_for_layout
    from test_v2_timeline_replay import resolved as timed

    layout, _, split = geometry_boundary()
    raw_layout = layout.model_dump(mode="json")
    source = next(obj for obj in raw_layout["objects"] if obj["object_id"] == "source")
    origin = deepcopy(source)
    origin.update(object_id="origin", object_type="ellipse")
    source.update(initial_state="hidden", visible=False)
    raw_layout["objects"].append(origin)
    raw_layout["boards"][0]["object_ids"].append("origin")
    layout = ExecutableLayoutV2.model_validate(raw_layout)
    initial = sample_for_layout(layout)
    morph = timed(peer_action("morph", from_object_id="origin", to_object_id="source",
        morph_policy={"mapping": "canonical_outline"}).action, 0, 500)
    objects = {obj.object_id: obj for obj in layout.objects}
    replay = replay_chronology(objects, initial.hierarchy,
        {obj.object_id: obj for obj in initial.objects}, dict(initial.state_versions), (morph,),
        tuple((row.board_id, row.start_ms, row.end_ms) for row in layout.activations), 2000)
    before = replay.at(500)
    raw = split.model_dump(mode="json")
    raw.update(start_ms=500, end_ms=1500)
    policy = raw["action"]["split_policy"]
    contents = {row.object_id: row.content_sha256 for row in split_content_receipts(layout, before, {})}
    for row in policy["source_basis"]["placements"]:
        row.update(sibling_ordinal={"source": 1, "part-1": 2, "part-2": 3}[row["object_id"]],
                   state_version=2 if row["object_id"] == "source" else 1, content_sha256=contents[row["object_id"]])
    for row in policy["correspondences"]:
        row.update(source_content_sha256=contents["source"], result_content_sha256=contents[row["result_object_id"]])
    policy["source_basis_sha256"] = digest(policy["source_basis"])
    receipt = _split_expected_completion(SplitPolicy.model_validate(policy))
    receipt["completion_sha256"] = digest(receipt)
    raw["split_completion_receipt"] = receipt
    split = ResolvedAction.model_validate(raw)
    if reorder:
        layout.objects.reverse()
    actions = (morph, split)
    captured = _capture_split_from_history(layout, initial, actions, 1, 2000, {})
    assert before.object("origin").state == "removed"
    assert before.object("source").state == "visible" and before.object("source").morph_geometry is None
    assert "origin" not in captured.split_capture.owned_object_ids
    assert next(row for row in captured.split_capture.baseline if row.object_id == "source") == before.object("source")


def test_private_capture_rejects_nonchronological_resolved_actions():
    from atme.render.v2_timeline_replay import _capture_split_from_history

    layout, initial, _, prior, split = counted_boundary()
    with pytest.raises(ValueError, match="chronolog"):
        _capture_split_from_history(layout, initial, (split, *prior), 0, 2000, {})


def test_canonical_equal_basis_capture_remains_consistent_for_reservations():
    from atme.store.contracts_v2 import SplitPolicy, _split_expected_completion

    module = capture_module()
    layout, before, split = geometry_boundary()
    raw = split.model_dump(mode="json")
    policy = raw["action"]["split_policy"]
    source = next(row for row in policy["source_basis"]["placements"] if row["object_id"] == "source")
    source["local_transform"]["position"]["x"] = 0.00001
    # Contract hashing quantizes poses; retain that approved equality instead
    # of accidentally requiring raw floating-point identity in the carrier.
    from atme.render.v2_split_identity import split_basis_digest, split_policy_digest
    from atme.store.contracts_v2 import SplitBasis, _split_packet_digest

    policy["source_basis_sha256"] = split_basis_digest(SplitBasis.model_validate(policy["source_basis"]))
    parsed = SplitPolicy.model_validate(policy)
    receipt = _split_expected_completion(parsed)
    receipt["policy_sha256"] = split_policy_digest(parsed)
    receipt["completion_sha256"] = _split_packet_digest(receipt)
    raw["split_completion_receipt"] = receipt
    captured = module.capture_split(ResolvedAction.model_validate(raw), layout, before, {})
    module.validate_split_reservations(captured, ())


def test_same_time_later_start_is_not_part_of_owner_precondition():
    from atme.render.v2_timeline_replay import _capture_split_from_history
    from atme.store.contracts_v2 import ExecutableLayoutV2
    from test_v2_split_identity import sample_for_layout

    layout, _, split = geometry_boundary()
    raw = layout.model_dump(mode="json")
    extra = deepcopy(next(obj for obj in raw["objects"] if obj["object_id"] == "part-1"))
    extra.update(object_id="unrelated", z_index=3)
    raw["objects"].append(extra)
    raw["boards"][0]["object_ids"].append("unrelated")
    layout = ExecutableLayoutV2.model_validate(raw)
    initial = sample_for_layout(layout)
    later = peer_action("reveal", target_ids=["unrelated"])
    later.action.expected_state = "hidden"
    captured = _capture_split_from_history(layout, initial, (split, later), 0, 2000, {})
    assert not next(frame for frame in captured.baseline if frame.object_id == "unrelated").visible


def test_private_caller_checks_capture_clock_against_verified_owner(monkeypatch):
    from atme.render.v2_timeline_replay import _capture_split_from_history

    module = capture_module()
    layout, before, split = geometry_boundary()
    real_capture = module._capture_split

    def shifted(*args):
        result = real_capture(*args)
        return replace(result, start_ms=result.start_ms + 10000, end_ms=result.end_ms + 10000)

    monkeypatch.setattr(module, "_capture_split", shifted)
    with pytest.raises(ValueError, match="capture.*interval"):
        _capture_split_from_history(layout, before, (split,), 0, 2000, {})


def hidden_result_boundary():
    from atme.store.contracts_v2 import (
        ExecutableLayoutV2,
        SplitPolicy,
        _split_expected_completion,
    )
    from test_v2_split_identity import sample_for_layout

    layout, _, split = geometry_boundary()
    raw_layout = layout.model_dump(mode="json")
    root = next(row for row in raw_layout["objects"] if row["object_id"] == "part-1")
    child = deepcopy(root)
    child.update(object_id="child", initial_state="visible", visible=True, parent_id="part-1", z_index=0)
    root.pop("path_data")
    root.update(object_type="group", child_ids=["child"])
    raw_layout["objects"].append(child)
    raw_layout["boards"][0]["object_ids"].append("child")
    layout = ExecutableLayoutV2.model_validate(raw_layout)
    before = sample_for_layout(layout)
    raw = split.model_dump(mode="json")
    policy = raw["action"]["split_policy"]
    basis = policy["source_basis"]
    next(row for row in basis["result_closures"] if row["root_id"] == "part-1")["owned_ids"] = ["child", "part-1"]
    placement = deepcopy(next(row for row in basis["placements"] if row["object_id"] == "part-1"))
    placement.update(object_id="child", parent_id="part-1", sibling_ordinal=0, state="visible",
                     local_visibility=True, effective_visibility=False, reveal=1.0)
    basis["placements"] = sorted([*basis["placements"], placement], key=lambda row: row["object_id"])
    content = {row.object_id: row.content_sha256 for row in split_content_receipts(layout, before, {})}
    for row in basis["placements"]:
        row["content_sha256"] = content[row["object_id"]]
    for row in policy["correspondences"]:
        row.update(source_content_sha256=content["source"], result_content_sha256=content[row["result_object_id"]])
    # The parent is owned but is also bound as an ancestor read definition.
    basis["read_dependencies"] = [{"kind": "ancestor", "object_ids": ["part-1"]}]
    policy["source_basis_sha256"] = digest(basis)
    receipt = _split_expected_completion(SplitPolicy.model_validate(policy))
    receipt["completion_sha256"] = digest(receipt)
    raw["split_completion_receipt"] = receipt
    return layout, before, ResolvedAction.model_validate(raw)


def test_hidden_result_closure_keeps_child_local_visibility_separate_from_effective_visibility():
    module = capture_module()
    layout, before, split = hidden_result_boundary()
    captured = module.capture_split(split, layout, before, {})
    child_basis = next(row for row in json.loads(captured.basis_json)["placements"] if row["object_id"] == "child")
    assert child_basis["local_visibility"] is True and child_basis["effective_visibility"] is False
    assert captured.read_dependency_ids == ()
    assert "child" in captured.owned_object_ids
    with pytest.raises(ValueError, match="reservation.*child"):
        module.validate_split_reservations(captured, (peer_action("fade", target_ids=["child"], opacity=0.5),))


def test_private_history_rejects_count_payload_changed_after_origin(monkeypatch):
    from atme.render import v2_timeline_replay as runtime

    layout, initial, _, prior, split = counted_boundary(group_after_count=True)
    original = runtime._sample_active

    def changed(committed, active, at, objects, *, evidence_treatments=(), evidence_reads=()):
        observed = original(committed, active, at, objects,
                            evidence_treatments=evidence_treatments, evidence_reads=evidence_reads)
        if at == split.start_ms:
            observed["source"] = replace(observed["source"], display_text="99 widgets", count_value=(99, 1))
        return observed

    monkeypatch.setattr(runtime, "_sample_active", changed)
    with pytest.raises(ValueError, match="Count origin"):
        runtime._capture_split_from_history(layout, initial, (*prior, split), 2, 2000, {})


@pytest.mark.parametrize("dependency", ["asset", "annotation"])
def test_unverified_asset_and_retained_annotation_paths_remain_closed(dependency):
    from atme.store.contracts_v2 import SplitPolicy, _split_expected_completion

    module = capture_module()
    layout, before, split = geometry_boundary()
    if dependency == "asset":
        next(obj for obj in layout.objects if obj.object_id == "source").asset_id = "asset-unverified"
    else:
        raw = split.model_dump(mode="json")
        policy = raw["action"]["split_policy"]
        policy["source_basis"]["read_dependencies"] = [{"kind": "annotation_anchor", "object_ids": ["source"]}]
        policy["source_basis_sha256"] = digest(policy["source_basis"])
        receipt = _split_expected_completion(SplitPolicy.model_validate(policy))
        receipt["completion_sha256"] = digest(receipt)
        raw["split_completion_receipt"] = receipt
        split = ResolvedAction.model_validate(raw)
    with pytest.raises(ValueError, match="(exact trusted project asset inventory|annotation dependencies)"):
        module.capture_split(split, layout, before, {"asset-unverified": b"not an origin receipt"})


def test_history_rejects_retained_annotation_omitted_from_submitted_dependencies():
    from atme.render.v2_timeline_replay import (
        _capture_split_from_history,
        replay_chronology,
    )
    from atme.store.contracts_v2 import ExecutableLayoutV2
    from test_v2_split_identity import sample_for_layout
    from test_v2_timeline_replay import resolved as timed

    layout, _, split = geometry_boundary()
    raw = layout.model_dump(mode="json")
    note = deepcopy(next(row for row in raw["objects"] if row["object_id"] == "part-1"))
    note.update(object_id="note", z_index=3)
    raw["objects"].append(note)
    raw["boards"][0]["object_ids"].append("note")
    layout = ExecutableLayoutV2.model_validate(raw)
    initial = sample_for_layout(layout)
    annotation = timed(peer_action("annotate", target_ids=["source"], annotation_policy={
        "annotation_object_ids": ["note"], "phases": [{"object_id": "note", "mode": "draw", "weight": 1}],
        "readable_hold_ms": 100}).action, 0, 500)
    split = split.model_copy(update={"start_ms": 500, "end_ms": 1500})
    replay = replay_chronology({obj.object_id: obj for obj in layout.objects}, initial.hierarchy,
        {obj.object_id: obj for obj in initial.objects}, dict(initial.state_versions), (annotation,),
        tuple((row.board_id, row.start_ms, row.end_ms) for row in layout.activations), 2000)
    assert replay.at(500).object("note").visible
    # Pure frames cannot identify the retained relationship; submitted basis omits it.
    assert capture_module().capture_split(split, layout, replay.at(500), {})
    with pytest.raises(ValueError, match="retained annotation"):
        _capture_split_from_history(layout, initial, (annotation, split), 1, 2000, {})


@pytest.mark.parametrize("connected_by_action", [False, True])
def test_history_rejects_managed_connector_with_matching_submitted_dependency(connected_by_action):
    from atme.render.v2_timeline_replay import (
        _capture_split_from_history,
        replay_chronology,
    )
    from atme.store.contracts_v2 import (
        ExecutableLayoutV2,
        SplitPolicy,
        _split_expected_completion,
    )
    from test_v2_split_identity import sample_for_layout
    from test_v2_timeline_replay import resolved as timed

    module = capture_module()
    layout, _, split = geometry_boundary()
    raw = layout.model_dump(mode="json")
    arrow = deepcopy(next(row for row in raw["objects"] if row["object_id"] == "source"))
    arrow.pop("path_data")
    arrow.update(object_id="arrow", z_index=3, object_type="arrow", source_object_id="source",
        source_anchor_id="center", destination_object_id="source", destination_anchor_id="center",
        role="semantic_connector", routing="straight", allow_self_loop=True,
        initial_state="disconnected" if connected_by_action else "connected", visible=not connected_by_action)
    raw["objects"].append(arrow)
    raw["boards"][0]["object_ids"].append("arrow")
    layout = ExecutableLayoutV2.model_validate(raw)
    initial = sample_for_layout(layout)
    params = {"connector_id": "arrow", "source_object_id": "source", "source_anchor_id": "center",
              "destination_object_id": "source", "destination_anchor_id": "center"}
    connection = peer_action("connect" if connected_by_action else "disconnect", **params)
    connection.action.expected_state = "disconnected" if connected_by_action else "connected"
    connection.action.post_state = "connected" if connected_by_action else "disconnected"
    connection = timed(connection.action, 0 if connected_by_action else 1600, 500 if connected_by_action else 1900)
    prefix = (connection,) if connected_by_action else ()
    replay = replay_chronology({obj.object_id: obj for obj in layout.objects}, initial.hierarchy,
        {obj.object_id: obj for obj in initial.objects}, dict(initial.state_versions), prefix,
        tuple((row.board_id, row.start_ms, row.end_ms) for row in layout.activations), 2000)
    before = replay.at(500)
    raw = split.model_dump(mode="json")
    raw.update(start_ms=500, end_ms=1500)
    policy = raw["action"]["split_policy"]
    basis = policy["source_basis"]
    placement = deepcopy(next(row for row in basis["placements"] if row["object_id"] == "source"))
    content = {row.object_id: row.content_sha256 for row in split_content_receipts(layout, before, {})}
    placement.update(object_id="arrow", sibling_ordinal=3, state="connected",
        state_version=2 if connected_by_action else 1, content_sha256=content["arrow"])
    basis["placements"] = sorted([*basis["placements"], placement], key=lambda row: row["object_id"])
    basis["read_dependencies"] = [{"kind": "connector_anchor", "object_ids": ["arrow", "source"]}]
    policy["source_basis_sha256"] = digest(basis)
    receipt = _split_expected_completion(SplitPolicy.model_validate(policy))
    receipt["completion_sha256"] = digest(receipt)
    raw["split_completion_receipt"] = receipt
    split = ResolvedAction.model_validate(raw)
    assert module.capture_split(split, layout, before, {})
    if not connected_by_action:
        # Same static arrow without any ConnectionAction remains supported.
        assert _capture_split_from_history(layout, initial, (split,), 0, 2000, {})
    actions = (connection, split) if connected_by_action else (split, connection)
    with pytest.raises(ValueError, match="managed connector"):
        _capture_split_from_history(layout, initial, actions, int(connected_by_action), 2000, {})


def test_history_rejects_unproven_same_board_evidence_read_hold():
    from atme.render.v2_timeline_replay import _capture_split_from_history
    from atme.store.contracts_v2 import ExecutableLayoutV2
    from test_v2_split_identity import sample_for_layout
    from test_v2_timeline_replay import resolved as timed

    layout, _, split = geometry_boundary()
    raw = layout.model_dump(mode="json")
    evidence = deepcopy(next(row for row in raw["objects"] if row["object_id"] == "part-1"))
    evidence.update(object_id="evidence", z_index=3)
    raw["objects"].append(evidence)
    raw["boards"][0]["object_ids"].append("evidence")
    layout = ExecutableLayoutV2.model_validate(raw)
    initial = sample_for_layout(layout)
    insertion = peer_action("insert_evidence", evidence_asset_id="asset-evidence",
        destination_board_id=split.action.board_id, target_object_id="evidence", destination_state="evidence_visible")
    insertion.action.expected_state = "hidden"
    insertion.action.post_state = "evidence_visible"
    insertion = timed(insertion.action, 0, 500)
    split = split.model_copy(update={"start_ms": 500, "end_ms": 1500})
    with pytest.raises(ValueError, match="evidence.*hold"):
        _capture_split_from_history(layout, initial, (insertion, split), 1, 2000, {})


def test_shared_child_cannot_belong_to_two_split_result_roots():
    from atme.store.contracts_v2 import ExecutableLayoutV2

    layout, _, _ = geometry_boundary()
    raw = layout.model_dump(mode="json")
    child = deepcopy(next(row for row in raw["objects"] if row["object_id"] == "part-1"))
    child.update(object_id="shared-child", parent_id="part-1")
    for row in raw["objects"]:
        if row["object_id"] in {"part-1", "part-2"}:
            row.pop("path_data")
            row.update(object_type="group", child_ids=["shared-child"])
    raw["objects"].append(child)
    raw["boards"][0]["object_ids"].append("shared-child")
    with pytest.raises(ValueError):
        ExecutableLayoutV2.model_validate(raw)
