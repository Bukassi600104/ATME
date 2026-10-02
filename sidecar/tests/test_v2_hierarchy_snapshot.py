"""Shared immutable hierarchy foundation; group actions are not enabled yet."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import FrozenInstanceError, replace

import pytest
from test_v2_group_hierarchy import grouped_documents

from atme.render.v2_hierarchy import (
    HierarchyNode,
    HierarchySnapshot,
    UnsupportedHierarchy,
    changed_hierarchy_objects,
    validate_transition_scope,
    validate_world_preservation,
)
from atme.render.v2_state import UnsupportedVisualAction, evaluate_frame
from atme.render.v2_world import world_bounds
from atme.store.contracts_v2 import ExecutableLayoutV2


def basis():
    layout, timeline = grouped_documents()
    parsed = ExecutableLayoutV2.model_validate(layout)
    objects = {obj.object_id: obj for obj in parsed.objects}
    return layout, timeline, objects, HierarchySnapshot.from_objects(objects)


def ungrouped(before):
    ordinals = {"object-group": 0, "object-system": 1, "object-label": 2, "object-evidence": 3}
    return HierarchySnapshot(tuple(replace(node, parent_id=None, sibling_ordinal=ordinals[node.object_id])
                                   for node in before.nodes))


def test_initial_snapshot_matches_actual_paint_order_and_owns_immutable_nodes():
    _, _, objects, snapshot = basis()
    assert snapshot.paint_order(objects, "board-main") == ("object-system", "object-label", "object-evidence")
    assert snapshot.children("board-main", None) == ("object-group", "object-evidence")
    assert snapshot.children("board-main", "object-group") == ("object-system", "object-label")
    assert snapshot.ancestors("object-label") == ("object-group",)
    with pytest.raises(FrozenInstanceError):
        snapshot.nodes[0].parent_id = "object-group"
    with pytest.raises(UnsupportedHierarchy, match="immutable tuple"):
        HierarchySnapshot(list(snapshot.nodes))


def test_explicit_parent_order_snapshots_do_not_mutate_layout_and_roundtrip_exactly():
    _, _, objects, before = basis()
    original = deepcopy(objects)
    after = ungrouped(before)
    projected = after.object_map(objects)
    assert projected["object-system"].parent_id is None
    assert projected["object-group"].child_ids == []
    assert after.paint_order(objects, "board-main") == before.paint_order(objects, "board-main")
    assert before.object_map(objects)["object-group"].child_ids == ["object-system", "object-label"]
    projected["object-system"].transform.position.x = 10
    assert objects == original


def test_changed_closure_includes_container_members_and_other_shifted_sibling_ordinals():
    _, _, objects, before = basis()
    after = ungrouped(before)
    # Evidence is not reparented, but its root ordinal changes from1 to3.
    # The version/return contract must not silently ignore this metadata change.
    assert changed_hierarchy_objects(before, after, objects) == tuple(sorted(objects))
    assert changed_hierarchy_objects(before, before, objects) == ()
    assert changed_hierarchy_objects(after, before, objects) == tuple(sorted(objects))


@pytest.mark.parametrize("field,value", [("object_id", ""), ("board_id", ""), ("parent_id", ""),
                                        ("sibling_ordinal", -1), ("sibling_ordinal", True),
                                        ("sibling_ordinal", .5)])
def test_node_rejects_incomplete_or_coerced_fields(field, value):
    fields = {"object_id": "node", "board_id": "board", "parent_id": None, "sibling_ordinal": 0}
    fields[field] = value
    with pytest.raises(UnsupportedHierarchy):
        HierarchyNode(**fields)


def test_snapshot_rejects_duplicates_nondeterministic_node_order_and_missing_inventory():
    _, _, objects, before = basis()
    with pytest.raises(UnsupportedHierarchy, match="repeats"):
        HierarchySnapshot(before.nodes + (before.nodes[0],))
    with pytest.raises(UnsupportedHierarchy, match="canonical"):
        HierarchySnapshot(tuple(reversed(before.nodes)))
    missing = HierarchySnapshot(before.nodes[:-1])
    with pytest.raises(UnsupportedHierarchy, match="exact layout inventory"):
        missing.validate(objects)


@pytest.mark.parametrize("object_id,changes,match", [
    ("object-system", {"parent_id": "absent"}, "same-board container"),
    ("object-system", {"parent_id": "object-label"}, "same-board container"),
    ("object-group", {"parent_id": "object-group"}, "cyclic"),
    ("object-system", {"board_id": "elsewhere"}, "board ownership"),
    ("object-label", {"sibling_ordinal": 0}, "permutation"),
    ("object-label", {"sibling_ordinal": 5}, "permutation"),
])
def test_invalid_authored_topology_never_projects(object_id, changes, match):
    _, _, objects, before = basis()
    changed = HierarchySnapshot(tuple(replace(node, **changes) if node.object_id == object_id else node
                                      for node in before.nodes))
    with pytest.raises(UnsupportedHierarchy, match=match):
        changed.object_map(objects)


def test_initial_membership_must_be_bidirectionally_exact():
    _, _, objects, _ = basis()
    objects["object-group"].child_ids.pop()
    with pytest.raises(UnsupportedHierarchy, match="parent inventory"):
        HierarchySnapshot.from_objects(objects)


def test_topology_preserves_existing_eight_ancestor_depth_limit():
    _, _, objects, _ = basis()
    parent = "object-group"
    for index in range(8):
        ancestor = objects["object-group"].model_copy(deep=True)
        ancestor.object_id = f"outer-{index}"
        ancestor.parent_id = None
        ancestor.child_ids = [parent]
        objects[parent].parent_id = ancestor.object_id
        objects[ancestor.object_id] = ancestor
        parent = ancestor.object_id
        if index < 7:
            snapshot = HierarchySnapshot.from_objects(objects)
            assert len(snapshot.ancestors("object-system")) == index + 2
    with pytest.raises(UnsupportedHierarchy, match="eight ancestor"):
        HierarchySnapshot.from_objects(objects)


def test_authored_world_mapping_preserves_translated_group_and_descendant_corners():
    _, _, objects, before = basis()
    objects["object-group"].transform.position.x = 100
    objects["object-group"].transform.position.y = 20
    transforms = {object_id: obj.transform.model_copy(deep=True) for object_id, obj in objects.items()}
    destination = deepcopy(transforms)
    for object_id in ("object-system", "object-label"):
        destination[object_id].position.x += 100
        destination[object_id].position.y += 20
    after = ungrouped(before)
    validate_world_preservation(before, after, objects, transforms, destination, ("object-system", "object-label"))
    old_map, new_map = before.object_map(objects), after.object_map(objects)
    assert world_bounds(old_map["object-system"], old_map, transforms) == world_bounds(new_map["object-system"], new_map, destination)
    validate_world_preservation(after, before, objects, destination, transforms, ("object-system", "object-label"))
    destination["object-label"].position.x += .1
    with pytest.raises(UnsupportedHierarchy, match="world affine"):
        validate_world_preservation(before, after, objects, transforms, destination, ("object-system", "object-label"))


def test_world_mapping_is_exact_not_just_matching_axis_aligned_bounds():
    _, _, objects, before = basis()
    after = ungrouped(before)
    transforms = {object_id: obj.transform for object_id, obj in objects.items()}
    destination = deepcopy(transforms)
    destination["object-system"].rotation_degrees = 180
    with pytest.raises(UnsupportedHierarchy, match="world affine"):
        validate_world_preservation(before, after, objects, transforms, destination, ("object-system", "object-label"))


@pytest.mark.parametrize("members", [(), ("object-system", "object-system"), ("absent",),
                                     ("object-group", "object-system")])
def test_world_mapping_rejects_missing_duplicate_or_nested_member_roots(members):
    _, _, objects, before = basis()
    transforms = {object_id: obj.transform for object_id, obj in objects.items()}
    with pytest.raises(UnsupportedHierarchy):
        validate_world_preservation(before, ungrouped(before), objects, transforms, transforms, members)


def test_utility_does_not_enable_uncontracted_group_action():
    layout, timeline, _, _ = basis()
    resolved = deepcopy(timeline["actions"][0])
    action = resolved["action"]
    action.update(action_id="uncontracted-group", verb="group", target_ids=["object-system", "object-label"],
                  container_id="object-group", expected_state="visible", post_state="visible",
                  trigger={"kind": "absolute", "at_ms": 7000})
    action.pop("annotation", None)
    resolved.update(start_ms=7000, end_ms=7500)
    resolved["resolved_trigger"].update(source=action["trigger"], alignment_anchor_ms=7000,
                                       resolved_at_ms=7000, matched_text=None, matched_occurrence=None)
    timeline["actions"].append(resolved)
    timeline["coverage"][0]["action_ids"].append(action["action_id"])
    with pytest.raises(UnsupportedVisualAction, match="group.*no frame implementation"):
        evaluate_frame(layout, timeline, 100)


def test_destination_cannot_nest_two_declared_member_roots():
    _, _, objects, before = basis()
    after = HierarchySnapshot(tuple(
        replace(node, parent_id="object-group", sibling_ordinal=2)
        if node.object_id == "object-evidence" else node for node in before.nodes
    ))
    transforms = {object_id: obj.transform for object_id, obj in objects.items()}
    with pytest.raises(UnsupportedHierarchy, match="member root"):
        validate_world_preservation(before, after, objects, transforms, transforms,
                                    ("object-group", "object-evidence"))


def test_transition_cannot_change_an_undeclared_local_transform():
    _, _, objects, before = basis()
    transforms = {object_id: obj.transform for object_id, obj in objects.items()}
    destination = deepcopy(transforms)
    destination["object-label"].position.x += 99
    with pytest.raises(UnsupportedHierarchy, match="undeclared.*transform"):
        validate_world_preservation(before, before, objects, transforms, destination, ("object-system",))


def test_transition_cannot_reparent_an_undeclared_object():
    _, _, objects, before = basis()
    after = HierarchySnapshot(tuple(
        replace(node, parent_id="object-group", sibling_ordinal=2)
        if node.object_id == "object-evidence" else node for node in before.nodes
    ))
    transforms = {object_id: obj.transform for object_id, obj in objects.items()}
    with pytest.raises(UnsupportedHierarchy, match="undeclared.*parent"):
        validate_world_preservation(before, after, objects, transforms, transforms, ("object-system",))


def test_transition_cannot_reorder_other_siblings_despite_preserving_geometry():
    _, _, objects, grouped = basis()
    before = ungrouped(grouped)
    after = HierarchySnapshot(tuple(
        replace(node, sibling_ordinal=3) if node.object_id == "object-group"
        else replace(node, sibling_ordinal=0) if node.object_id == "object-evidence" else node
        for node in before.nodes
    ))
    transforms = {object_id: obj.transform for object_id, obj in objects.items()}
    with pytest.raises(UnsupportedHierarchy, match="sibling order"):
        validate_world_preservation(before, after, objects, transforms, transforms,
                                    ("object-system", "object-label"))


def test_transition_scope_is_symmetric_complete_and_allows_explained_ordinal_shifts():
    _, _, objects, before = basis()
    after = ungrouped(before)
    transforms = {object_id: obj.transform for object_id, obj in objects.items()}
    members = ("object-system", "object-label")
    assert validate_transition_scope(before, after, objects, transforms, transforms, members) == tuple(sorted(members))
    assert validate_transition_scope(after, before, objects, transforms, transforms, members) == tuple(sorted(members))


@pytest.mark.parametrize("delta,accepted", [(0.000049, True), (0.000151, False)])
def test_world_tolerance_tracks_serialized_four_decimal_geometry(delta, accepted):
    _, _, objects, before = basis()
    transforms = {object_id: obj.transform for object_id, obj in objects.items()}
    destination = deepcopy(transforms)
    destination["object-system"].position.x += delta
    if accepted:
        validate_world_preservation(before, before, objects, transforms, destination, ("object-system",))
    else:
        with pytest.raises(UnsupportedHierarchy, match="world affine"):
            validate_world_preservation(before, before, objects, transforms, destination, ("object-system",))
