"""Existing Group chronology must preserve explicitly borrowed aperture reads."""
from copy import deepcopy
from dataclasses import replace

import pytest
from atme.render import v2_svg
from atme.render.v2_hierarchy import (
    HierarchySnapshot,
    UnsupportedHierarchy,
    changed_hierarchy_objects,
    validate_authored_hierarchy,
)
from atme.render.v2_hierarchy_replay import completed_hierarchy_basis
from atme.store import contracts_v2 as contracts
from test_v2_external_aperture_lifecycle import add_action, initial_state
from test_v2_external_aperture_runtime import runtime_documents
from test_v2_group_annotation import consumer_clock, private_svg
from test_v2_split_identity import sample_for_layout
from v2_fixtures import digest


def membership_documents(kind, *, portrait=False, ungroup=False, live=False):
    _plan, layout, clock, ids = runtime_documents(kind, portrait=portrait, group=True)
    reference = deepcopy((layout, clock))
    objects = {obj["object_id"]: obj for obj in layout["objects"]}
    root, member = objects[ids["root"]], objects[ids["receiver"]]
    shell = deepcopy(root)
    shell.update(object_id="aperture-membership-shell", parent_id=ids["root"], z_index=19,
                 child_ids=[member["object_id"]] if ungroup else [],
                 initial_state="grouped" if ungroup else "ungrouped", clip_id=None)
    shell["transform"].update(position={"x": 10., "y": 20.}, scale_x=1., scale_y=1.,
                              rotation_degrees=0., origin={"x": 0., "y": 0.})
    root["child_ids"].append(shell["object_id"])
    if ungroup:
        root["child_ids"].remove(member["object_id"])
        member["parent_id"] = shell["object_id"]
        member["transform"]["position"].update(x=-10., y=-20.)
    layout["objects"].append(shell)
    layout["boards"][0]["object_ids"].append(shell["object_id"])
    clock["initial_object_states"].append({"object_id": shell["object_id"], "state": shell["initial_state"],
                                           "visible": True, "state_version": 1})
    if not ungroup:
        layout["initial_empty_group_ownership"] = [{"shell_object_id": shell["object_id"],
            "owner_group_action_id": "external-membership", "owner_source_basis_sha256": "0" * 64}]
    # The visible, fully ready ordinary Group has no positive child paint while
    # membership changes. Its actual child reveal starts at the exact boundary.
    if not live:
        initial_state(layout, clock, "external-receiver", "hidden", False)
    typed = contracts.ExecutableLayoutV2.model_validate(layout)
    objects = {obj.object_id: obj for obj in typed.objects}
    sample = sample_for_layout(typed)
    before = HierarchySnapshot.from_objects(objects)
    shell_node = next(node for node in before.nodes if node.object_id == shell["object_id"])
    after = HierarchySnapshot(tuple(replace(node,
        parent_id=ids["root"] if ungroup else shell["object_id"],
        sibling_ordinal=shell_node.sibling_ordinal + 1 if ungroup else 0)
        if node.object_id == member["object_id"] else node for node in before.nodes))
    source = completed_hierarchy_basis(before, {row.object_id: row for row in sample.objects})
    destination = deepcopy(source.model_dump(mode="json"))
    for row in destination["placements"]:
        if row["object_id"] == member["object_id"]:
            row.update(parent_id=ids["root"] if ungroup else shell["object_id"],
                       sibling_ordinal=shell_node.sibling_ordinal + 1 if ungroup else 0)
            row["local_transform"]["position"].update(x=0. if ungroup else -10., y=0. if ungroup else -20.)
    destination = contracts.HierarchyBasis.model_validate(destination)
    action = deepcopy(clock["actions"][0]["action"])
    action.pop("annotation", None)
    action.update(action_id="external-membership", verb="ungroup" if ungroup else "group",
        target_ids=[member["object_id"]], container_id=shell["object_id"], easing="step",
        expected_state=shell["initial_state"], post_state="ungrouped" if ungroup else "grouped",
        hierarchy_policy={"member_root_ids": [member["object_id"]],
            "source_basis": source.model_dump(mode="json"), "source_basis_sha256": source.checksum(),
            "destination_basis": destination.model_dump(mode="json"), "destination_basis_sha256": destination.checksum(),
            "changed_object_ids": list(changed_hierarchy_objects(before, after, objects)), "preserve_world_transform": True})
    if not ungroup:
        layout["initial_empty_group_ownership"][0]["owner_source_basis_sha256"] = source.checksum()
    add_action(clock, action, 1000, 1500)
    if not live:
        reveal = deepcopy(clock["actions"][0]["action"])
        reveal.update(action_id="reveal-after-membership", target_ids=["external-receiver"])
        add_action(clock, reveal, 1500, 2000)
    clock.update(initial_hierarchy_basis=source.model_dump(mode="json"),
                 initial_hierarchy_basis_sha256=source.checksum(), layout_sha256=digest(layout))
    return layout, clock, ids, reference


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("kind", ["clip", "mask"])
@pytest.mark.parametrize("ungroup", [False, True])
def test_external_consumer_membership_preserves_actual_aperture_pixels_after_exact_boundary(kind, portrait, ungroup):
    layout, clock, ids, reference = membership_documents(kind, portrait=portrait, ungroup=ungroup)
    original = deepcopy((layout, clock))
    expected = {at: v2_svg.compose_png_frame(*reference, at).png for at in (2500, 4500)}
    context, replay, camera = consumer_clock(layout, clock)
    assert replay.at(1499).object("aperture-membership-shell").state == ("grouped" if ungroup else "ungrouped")
    assert replay.at(1500).object("aperture-membership-shell").state == ("ungrouped" if ungroup else "grouped")
    assert replay.before_action("reveal-after-membership").hierarchy.ancestors(ids["receiver"]) == (
        (ids["root"],) if ungroup else ("aperture-membership-shell", ids["root"]))
    for at in (4500, 2500, 4500):
        svg = private_svg(context, replay, camera, at)
        assert v2_svg._rasterize_svg_frame(context.layout, svg).png == expected[at]
    assert (layout, clock) == original


def retarget_group(layout, clock, ids, target):
    typed = contracts.ExecutableLayoutV2.model_validate(layout)
    objects = {obj.object_id: obj for obj in typed.objects}
    action = next(row["action"] for row in clock["actions"] if row["action"]["action_id"] == "external-membership")
    before = HierarchySnapshot.from_objects(objects)
    remaining = [key for key in before.children("board-main", ids["root"]) if key != target]
    ordinals = {key: ordinal for ordinal, key in enumerate(remaining)}
    after = HierarchySnapshot(tuple(
        replace(node, parent_id="aperture-membership-shell", sibling_ordinal=0) if node.object_id == target
        else replace(node, sibling_ordinal=ordinals[node.object_id]) if node.object_id in ordinals else node
        for node in before.nodes))
    action["target_ids"] = [target]
    policy = action["hierarchy_policy"]
    policy["member_root_ids"] = [target]
    source = completed_hierarchy_basis(before, {row.object_id: row for row in sample_for_layout(typed).objects})
    policy.update(source_basis=source.model_dump(mode="json"), source_basis_sha256=source.checksum())
    destination = deepcopy(policy["source_basis"])
    nodes = {node.object_id: node for node in after.nodes}
    for row in destination["placements"]:
        node = nodes[row["object_id"]]
        row.update(parent_id=node.parent_id, sibling_ordinal=node.sibling_ordinal)
        if row["object_id"] == target:
            row["local_transform"]["position"]["x"] -= 10.
            row["local_transform"]["position"]["y"] -= 20.
    policy.update(destination_basis=destination,
                  destination_basis_sha256=contracts.HierarchyBasis.model_validate(destination).checksum(),
                  changed_object_ids=list(changed_hierarchy_objects(before, after, objects)))
    return contracts.GroupAction.model_validate(action), objects


def test_dedicated_mask_source_is_not_an_ordinary_movable_leaf_without_clip_id():
    layout, clock, ids, _reference = membership_documents("mask")
    action, objects = retarget_group(layout, clock, ids, ids["source"])
    assert objects[ids["source"]].clip_id is None
    with pytest.raises(UnsupportedHierarchy, match="aperture|mask source"):
        validate_authored_hierarchy(action, objects)


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("kind", ["clip", "mask"])
@pytest.mark.parametrize("ungroup", [False, True])
def test_actual_replay_rejects_membership_during_positive_external_consumer_paint(kind, portrait, ungroup):
    layout, clock, _ids, _reference = membership_documents(kind, portrait=portrait, ungroup=ungroup, live=True)
    with pytest.raises(ValueError, match="external aperture.*read lifetime conflicts with action external-membership"):
        consumer_clock(layout, clock)


@pytest.mark.parametrize("kind", ["clip", "mask"])
@pytest.mark.parametrize("branch", [False, True])
def test_named_owner_or_exclusive_read_branch_cannot_move_through_consumer_membership(kind, branch):
    layout, clock, ids, _reference = membership_documents(kind)
    target = ids["aperture"]
    if branch:
        objects = {obj["object_id"]: obj for obj in layout["objects"]}
        children = [ids["aperture"], *([ids["source"]] if kind == "mask" else [])]
        carrier = deepcopy(objects[ids["root"]])
        carrier.update(object_id="exclusive-aperture-branch", parent_id=ids["root"], child_ids=children, z_index=0)
        carrier["transform"].update(position={"x": 0., "y": 0.}, scale_x=1., scale_y=1.,
                                    rotation_degrees=0., origin={"x": 0., "y": 0.})
        for key in children:
            objects[key]["parent_id"] = carrier["object_id"]
            objects[ids["root"]]["child_ids"].remove(key)
        objects[ids["root"]]["child_ids"].insert(0, carrier["object_id"])
        layout["objects"].append(carrier)
        layout["boards"][0]["object_ids"].append(carrier["object_id"])
        target = carrier["object_id"]
    action, objects = retarget_group(layout, clock, ids, target)
    with pytest.raises(UnsupportedHierarchy, match="cannot cross aperture or evidence ownership"):
        validate_authored_hierarchy(action, objects)


@pytest.mark.parametrize("kind", ["clip", "mask"])
def test_coherently_rehashed_read_pose_cannot_replace_actual_completed_replay(kind):
    layout, clock, ids, _reference = membership_documents(kind)
    action = next(row["action"] for row in clock["actions"] if row["action"]["action_id"] == "external-membership")
    policy = action["hierarchy_policy"]
    for side in ("source", "destination"):
        row = next(row for row in policy[f"{side}_basis"]["placements"] if row["object_id"] == ids["aperture"])
        row["local_transform"]["position"]["x"] += 1.
        policy[f"{side}_basis_sha256"] = contracts.HierarchyBasis.model_validate(policy[f"{side}_basis"]).checksum()
    layout["initial_empty_group_ownership"][0]["owner_source_basis_sha256"] = policy["source_basis_sha256"]
    clock.update(initial_hierarchy_basis=deepcopy(policy["source_basis"]),
                 initial_hierarchy_basis_sha256=policy["source_basis_sha256"], layout_sha256=digest(layout))
    with pytest.raises(ValueError, match="initial hierarchy|source basis|initial.*transform|local transform"):
        consumer_clock(layout, clock)
