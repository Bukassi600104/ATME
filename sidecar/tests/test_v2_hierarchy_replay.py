"""Real immutable hierarchy step semantics, before chronological frame integration."""

from copy import deepcopy
from dataclasses import FrozenInstanceError, replace

import pytest
from test_v2_hierarchy_contract import receipt_documents, rehash
from test_v2_hierarchy_snapshot import basis
from v2_fixtures import digest

from atme.render.v2_hierarchy import (
    HierarchyNode,
    HierarchySnapshot,
    UnsupportedHierarchy,
    changed_hierarchy_objects,
    validate_authored_hierarchy,
)
from atme.render.v2_hierarchy_replay import (
    apply_hierarchy_step,
    completed_hierarchy_basis,
)
from atme.render.v2_state import FrameObject, FramePoint, FrameTransform, evaluate_frame
from atme.store.contracts_v2 import ExecutableLayoutV2, GroupAction


def prepared():
    plan, _, objects = receipt_documents()
    layout, timeline, _, _ = basis()
    layout["objects"][3]["initial_state"] = "grouped"
    timeline["initial_object_states"][3]["state"] = "grouped"
    timeline["layout_sha256"] = digest(layout)
    frame = evaluate_frame(layout, timeline, 5000)
    frames = {item.object_id: item for item in frame.objects}
    versions = {key: index + 1 for index, key in enumerate(sorted(objects))}
    action = GroupAction.model_validate(plan["actions"][-1])
    return action, objects, frame.hierarchy, frames, versions


def reverse(action):
    document = action.model_dump(mode="json")
    policy = document["hierarchy_policy"]
    policy["source_basis"], policy["destination_basis"] = policy["destination_basis"], policy["source_basis"]
    document.update(verb="group", expected_state="ungrouped", post_state="grouped")
    rehash(document)
    return GroupAction.model_validate(document)


def test_real_ungroup_regroup_restores_exact_hierarchy_local_transforms_and_paint_identity():
    action, objects, hierarchy, frames, versions = prepared()
    original = deepcopy((objects, hierarchy, frames, versions, action))
    outcome = apply_hierarchy_step(action, objects, hierarchy, frames, versions, "board-main")
    resulting = {item.object_id: item for item in outcome.objects}
    assert outcome.hierarchy.ancestors("object-system") == ()
    assert outcome.hierarchy.children("board-main", "object-group") == ()
    assert resulting["object-group"].state == "ungrouped"
    assert resulting["object-system"].state == frames["object-system"].state
    assert outcome.hierarchy.paint_order(objects, "board-main") == hierarchy.paint_order(objects, "board-main")
    assert dict(outcome.state_versions) == {key: value + 1 for key, value in versions.items()}
    restored = apply_hierarchy_step(reverse(action), objects, outcome.hierarchy, resulting,
                                    dict(outcome.state_versions), "board-main")
    assert restored.hierarchy == hierarchy
    assert restored.objects == tuple(frames[key] for key in sorted(frames))
    assert dict(restored.state_versions) == {key: value + 2 for key, value in versions.items()}
    assert (objects, hierarchy, frames, versions, action) == original
    with pytest.raises(FrozenInstanceError):
        outcome.objects[0].state = "changed"
    with pytest.raises(FrozenInstanceError):
        outcome.hierarchy.nodes[0].parent_id = "changed"


def test_replaying_the_same_step_cannot_apply_a_stale_source_basis_twice():
    action, objects, hierarchy, frames, versions = prepared()
    outcome = apply_hierarchy_step(action, objects, hierarchy, frames, versions, "board-main")
    with pytest.raises(UnsupportedHierarchy, match="source basis"):
        apply_hierarchy_step(action, objects, outcome.hierarchy, {item.object_id: item for item in outcome.objects},
                             dict(outcome.state_versions), "board-main")


def test_source_basis_binds_current_completed_transforms_not_just_initial_layout():
    action, objects, hierarchy, frames, versions = prepared()
    frame = frames["object-system"]
    frames[frame.object_id] = replace(frame, transform=replace(frame.transform, position=FramePoint(20, 0)))
    assert completed_hierarchy_basis(hierarchy, frames).checksum() != action.hierarchy_policy.source_basis_sha256
    with pytest.raises(UnsupportedHierarchy, match="source basis"):
        apply_hierarchy_step(action, objects, hierarchy, frames, versions, "board-main")


@pytest.mark.parametrize("change", [
    lambda frames: frames.update({"object-label": replace(frames["object-label"], visible=False)}),
    lambda frames: frames.update({"object-label": replace(frames["object-label"], reveal_fraction=.5)}),
    lambda frames: frames.update({"object-label": replace(frames["object-label"], opacity=0)}),
    lambda frames: frames.update({"object-group": replace(frames["object-group"], opacity=.5)}),
    lambda frames: frames.update({"object-group": replace(frames["object-group"], state="visible")}),
])
def test_step_rejects_unready_participant_or_shell_frame_state(change):
    action, objects, hierarchy, frames, versions = prepared()
    change(frames)
    with pytest.raises(UnsupportedHierarchy):
        apply_hierarchy_step(action, objects, hierarchy, frames, versions, "board-main")


@pytest.mark.parametrize("bad", [{}, {"object-group": 1},
                                 {"object-evidence": 1, "object-group": True, "object-label": 1, "object-system": 1},
                                 {"object-evidence": 1, "object-group": 1, "object-label": 0, "object-system": 1}])
def test_step_requires_complete_positive_integer_version_inventory(bad):
    action, objects, hierarchy, frames, _ = prepared()
    with pytest.raises(UnsupportedHierarchy, match="version inventory"):
        apply_hierarchy_step(action, objects, hierarchy, frames, bad, "board-main")


def test_step_requires_its_real_active_board():
    action, objects, hierarchy, frames, versions = prepared()
    with pytest.raises(UnsupportedHierarchy, match="active board"):
        apply_hierarchy_step(action, objects, hierarchy, frames, versions, "elsewhere")


def test_complete_basis_never_infers_missing_frame_data():
    _, _, hierarchy, frames, _ = prepared()
    del frames["object-label"]
    with pytest.raises(UnsupportedHierarchy, match="exact immutable frame inventory"):
        completed_hierarchy_basis(hierarchy, frames)


@pytest.mark.parametrize("hidden_descendant", [False, True])
def test_nested_nonidentity_parent_step_preserves_descendant_local_state_and_versions(hidden_descendant):
    original_action, objects, _, frames, versions = prepared()
    outer = objects["object-group"].model_copy(deep=True)
    outer.object_id = "outer-group"
    outer.child_ids = ["object-group"]
    outer.transform.position.x, outer.transform.position.y = 100, 20
    objects["object-group"].parent_id = outer.object_id
    objects["object-group"].transform.position.x, objects["object-group"].transform.position.y = 10, 30
    objects[outer.object_id] = outer
    frames["object-group"] = replace(frames["object-group"], transform=FrameTransform.from_contract(objects["object-group"].transform))
    frames[outer.object_id] = replace(frames["object-group"], object_id=outer.object_id,
                                      transform=FrameTransform.from_contract(outer.transform), state="grouped")
    versions[outer.object_id] = 1
    if hidden_descendant:
        frames["object-label"] = replace(frames["object-label"], state="hidden", visible=False,
                                          opacity=0, reveal_fraction=0)
    before = HierarchySnapshot.from_objects(objects)
    root_ordinals = {"outer-group": 0, "object-group": 1, "object-evidence": 2}
    after = HierarchySnapshot(tuple(
        replace(node, parent_id=None, sibling_ordinal=root_ordinals[node.object_id])
        if node.object_id in root_ordinals else node for node in before.nodes))
    source = completed_hierarchy_basis(before, frames)
    destination = deepcopy(source.model_dump(mode="json"))
    after_nodes = {node.object_id: node for node in after.nodes}
    for item in destination["placements"]:
        node = after_nodes[item["object_id"]]
        item.update(parent_id=node.parent_id, sibling_ordinal=node.sibling_ordinal)
        if item["object_id"] == "object-group":
            item["local_transform"]["position"] = {"x": 110, "y": 50}
    document = original_action.model_dump(mode="json")
    document.update(target_ids=["object-group"], container_id="outer-group")
    document["hierarchy_policy"].update(member_root_ids=["object-group"], source_basis=source.model_dump(mode="json"),
                                        destination_basis=destination,
                                        changed_object_ids=list(changed_hierarchy_objects(before, after, objects)))
    rehash(document)
    outcome = apply_hierarchy_step(GroupAction.model_validate(document), objects, before, frames, versions, "board-main")
    resulting = {item.object_id: item for item in outcome.objects}
    assert outcome.hierarchy.ancestors("object-system") == ("object-group",)
    assert resulting["object-group"].transform.position == FramePoint(110, 50)
    assert resulting["object-system"] == frames["object-system"]
    assert resulting["object-label"] == frames["object-label"]
    assert dict(outcome.state_versions)["object-system"] == versions["object-system"] + 1
    assert dict(outcome.state_versions)["object-label"] == versions["object-label"] + 1


def test_step_rejects_moved_connector_before_nested_connector_semantics_exist():
    from test_v2_connector_svg import connector_documents

    action, objects, hierarchy, frames, versions = prepared()
    ungroup = apply_hierarchy_step(action, objects, hierarchy, frames, versions, "board-main")
    frames = {item.object_id: item for item in ungroup.objects}
    versions = dict(ungroup.state_versions)
    connector_layout, _ = connector_documents()
    connector = ExecutableLayoutV2.model_validate(connector_layout).objects[-1]
    objects[connector.object_id] = connector
    frames[connector.object_id] = FrameObject(connector.object_id, connector.board_id, "visible", True, 1, 1,
                                             FrameTransform.from_contract(connector.transform))
    versions[connector.object_id] = 1
    ordinals = {"object-group": 0, "object-arrow": 1, "object-system": 2, "object-label": 3, "object-evidence": 4}
    before = HierarchySnapshot(tuple(HierarchyNode(key, "board-main", None, ordinals[key]) for key in sorted(objects)))
    after = HierarchySnapshot(tuple(
        replace(node, parent_id="object-group", sibling_ordinal=0) if node.object_id == "object-arrow"
        else replace(node, sibling_ordinal=node.sibling_ordinal - 1) if node.sibling_ordinal > 1 else node
        for node in before.nodes))
    source = completed_hierarchy_basis(before, frames).model_dump(mode="json")
    destination = deepcopy(source)
    after_nodes = {node.object_id: node for node in after.nodes}
    for item in destination["placements"]:
        node = after_nodes[item["object_id"]]
        item.update(parent_id=node.parent_id, sibling_ordinal=node.sibling_ordinal)
    document = reverse(action).model_dump(mode="json")
    document.update(target_ids=[connector.object_id])
    document["hierarchy_policy"].update(member_root_ids=[connector.object_id], source_basis=source,
                                        destination_basis=destination,
                                        changed_object_ids=list(changed_hierarchy_objects(before, after, objects)))
    rehash(document)
    with pytest.raises(UnsupportedHierarchy, match="connector without inverse-parent"):
        validate_authored_hierarchy(GroupAction.model_validate(document), objects)
    with pytest.raises(UnsupportedHierarchy, match="connector without inverse-parent"):
        apply_hierarchy_step(GroupAction.model_validate(document), objects, before, frames, versions, "board-main")


@pytest.mark.parametrize("opacity", [float("nan"), float("inf"), 2])
def test_step_never_accepts_nonfinite_or_out_of_range_completed_paint(opacity):
    action, objects, hierarchy, frames, versions = prepared()
    frames["object-label"] = replace(frames["object-label"], opacity=opacity)
    with pytest.raises(UnsupportedHierarchy, match="frame inventory"):
        apply_hierarchy_step(action, objects, hierarchy, frames, versions, "board-main")


@pytest.mark.parametrize("transform", [
    FrameTransform(FramePoint(float("nan"), 0), 1, 1, 0, FramePoint(.5, .5)),
    FrameTransform(FramePoint(0, 0), float("inf"), 1, 0, FramePoint(.5, .5)),
    FrameTransform(FramePoint(0, 0), 0, 1, 0, FramePoint(.5, .5)),
])
def test_invalid_completed_transform_has_stable_replay_error_and_does_not_mutate_input(transform):
    action, objects, hierarchy, frames, versions = prepared()
    frames["object-label"] = replace(frames["object-label"], transform=transform)
    original = (deepcopy(objects), hierarchy, dict(frames), dict(versions), action.model_dump(mode="json"))
    with pytest.raises(UnsupportedHierarchy, match="completed transform"):
        apply_hierarchy_step(action, objects, hierarchy, frames, versions, "board-main")
    assert (objects, hierarchy, frames, versions, action.model_dump(mode="json")) == original


def test_group_multiple_roots_into_translated_rotated_scaled_shell_with_authored_compensation():
    action, objects, hierarchy, frames, versions = prepared()
    outside = apply_hierarchy_step(action, objects, hierarchy, frames, versions, "board-main")
    frames = {item.object_id: item for item in outside.objects}
    versions = dict(outside.state_versions)
    # The authored shell maps (x,y) to (350-2y,20+2x). Each root's
    # standalone transform is explicitly supplied, never inferred by replay.
    shell_transform = FrameTransform(FramePoint(100, 20), 2, 2, 90, FramePoint(0, 0))
    frames["object-group"] = replace(frames["object-group"], transform=shell_transform)
    offsets = {"object-system": FramePoint(12, 8), "object-label": FramePoint(-5, 14)}
    for key, offset in offsets.items():
        bounds = objects[key].geometry.bounds
        position = FramePoint(350 - 2 * offset.y - bounds.x - 2 * bounds.y,
                              20 + 2 * offset.x - bounds.y + 2 * bounds.x)
        frames[key] = replace(frames[key], transform=FrameTransform(position, 2, 2, 90, FramePoint(0, 0)))
    document = reverse(action).model_dump(mode="json")
    source = completed_hierarchy_basis(outside.hierarchy, frames).model_dump(mode="json")
    destination = deepcopy(source)
    grouped_nodes = {node.object_id: node for node in hierarchy.nodes}
    for item in destination["placements"]:
        node = grouped_nodes[item["object_id"]]
        item.update(parent_id=node.parent_id, sibling_ordinal=node.sibling_ordinal)
        if item["object_id"] in offsets:
            offset = offsets[item["object_id"]]
            item["local_transform"] = {"position": {"x": offset.x, "y": offset.y}, "scale_x": 1,
                                       "scale_y": 1, "rotation_degrees": 0, "origin": {"x": 0, "y": 0}}
    document["hierarchy_policy"].update(source_basis=source, destination_basis=destination)
    rehash(document)
    grouping = GroupAction.model_validate(document)
    original = deepcopy((objects, outside.hierarchy, frames, versions, grouping))
    outcome = apply_hierarchy_step(grouping, objects, outside.hierarchy, frames, versions, "board-main")
    resulting = {item.object_id: item for item in outcome.objects}
    assert resulting["object-group"].transform == shell_transform
    for key, offset in offsets.items():
        assert resulting[key].transform == FrameTransform(offset, 1, 1, 0, FramePoint(0, 0))
        assert resulting[key].state == frames[key].state
    assert outcome.hierarchy == hierarchy
    assert dict(outcome.state_versions) == {key: value + 1 for key, value in versions.items()}
    assert (objects, outside.hierarchy, frames, versions, grouping) == original
