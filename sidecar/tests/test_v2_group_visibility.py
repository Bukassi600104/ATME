"""Whole-Group enter/exit reserves actual contents, but writes only roots."""

from copy import deepcopy
from dataclasses import replace

import pytest
from test_v2_connector_svg import connector_documents
from test_v2_hierarchy_replay import prepared
from test_v2_timeline_replay import moving, resolved, run

from atme.render.v2_hierarchy import HierarchySnapshot
from atme.render.v2_state import FrameTransform
from atme.render.v2_timeline_replay import ReplayError
from atme.store.contracts_v2 import ConnectorObject


def visibility(action, frames, targets=("object-group",), *, verb="exit", key="group-exit", start=1000, end=2000):
    doc = action.model_dump(mode="json")
    doc.pop("hierarchy_policy")
    doc.pop("container_id")
    doc.update(action_id=key, verb=verb, target_ids=list(targets), easing="linear",
               expected_state=frames[targets[0]].state, post_state="removed" if verb == "exit" else "visible",
               annotation=None)
    return resolved(doc, start, end)


def second_group(data, *, nested=False):
    action, objects, _, frames, versions = data
    group = objects["object-group"].model_copy(deep=True)
    group.object_id = "other-group"
    group.child_ids = ["object-group"] if nested else ["object-evidence"]
    member = "object-group" if nested else "object-evidence"
    objects[member].parent_id = group.object_id
    objects[group.object_id] = group
    frames[group.object_id] = replace(frames["object-group"], object_id=group.object_id,
                                      transform=FrameTransform.from_contract(group.transform))
    versions[group.object_id] = 11
    return action, objects, HierarchySnapshot.from_objects(objects), frames, versions


@pytest.mark.parametrize("verb", ["enter", "exit"])
def test_group_visibility_changes_only_root_local_frame_and_version(verb):
    data = prepared()
    action, _objects, hierarchy, frames, versions = data
    if verb == "enter":
        frames["object-group"] = replace(frames["object-group"], state="hidden", visible=False)
    original = deepcopy(data)
    trace = run([visibility(action, frames, verb=verb)], data)
    for time in (1000, 1500, 2000, 1500, 999, 2000):
        sample = trace.at(time)
        assert sample.hierarchy == hierarchy
        for key in frames.keys() - {"object-group"}:
            assert sample.object(key) == frames[key]
        assert dict(sample.state_versions) == {
            key: version + (key == "object-group" and time >= 2000) for key, version in versions.items()}
        root = sample.object("object-group")
        assert root.transform == frames["object-group"].transform
        if time == 1500:
            assert root.opacity == .5 and root.visible
        if time == 2000:
            assert root.state == ("visible" if verb == "enter" else "removed")
            assert root.visible is (verb == "enter")
    assert data == original


def test_multiple_disjoint_groups_are_one_root_only_operation():
    data = second_group(prepared())
    action, _, _, frames, versions = data
    trace = run([visibility(action, frames, ("object-group", "other-group"))], data)
    assert trace.at(1500).object("other-group").opacity == .5
    assert trace.at(1500).object("object-group").opacity == .5
    assert trace.at(2000).object("object-evidence") == frames["object-evidence"]
    assert dict(trace.at(2000).state_versions) == {
        key: value + (key in {"object-group", "other-group"}) for key, value in versions.items()}


@pytest.mark.parametrize("fault", ["duplicate", "nested", "mixed", "clip", "mask"])
def test_group_visibility_rejects_ambiguous_or_unapproved_container_targets(fault):
    data = second_group(prepared(), nested=fault == "nested")
    action, objects, hierarchy, frames, versions = data
    targets = ("object-group",)
    verb = "exit"
    if fault == "duplicate":
        targets = ("object-group", "object-group")
    elif fault == "nested":
        targets = ("object-group", "other-group")
    elif fault == "mixed":
        targets = ("object-group", "object-evidence")
        frames["object-evidence"] = replace(frames["object-evidence"], state=frames["object-group"].state)
    elif fault in {"clip", "mask"}:
        # Known typed Container payload, not an unknown/bypassed subclass.
        from atme.store.contracts_v2 import ClipContainer, MaskContainer

        model = ClipContainer if fault == "clip" else MaskContainer
        doc = objects["object-group"].model_dump(mode="json")
        doc["object_type"] = fault
        objects["object-group"] = model.model_validate(doc)
    with pytest.raises(ReplayError, match="Group.*(enter/exit|disjoint|unique|target)"):
        run([visibility(action, frames, targets, verb=verb)], (action, objects, hierarchy, frames, versions))


@pytest.mark.parametrize("verb", ["reveal", "draw", "write"])
def test_other_group_target_verbs_remain_closed_at_public_admission(verb):
    from test_v2_group_hierarchy import grouped_documents

    from atme.render.v2_state import V2FrameError, evaluate_frame

    layout, timeline = grouped_documents()
    action = timeline["actions"][2]["action"]
    action.update(verb=verb, target_ids=["object-group"], expected_state="visible")
    with pytest.raises(V2FrameError, match="descendant semantics"):
        evaluate_frame(layout, timeline, 0)


def test_missing_visibility_target_keeps_existing_replay_error_boundary():
    data = prepared()
    action, _, _, frames, _ = data
    with pytest.raises(ReplayError, match="missing local frame"):
        run([visibility(action, frames, ("object-group", "missing-root"))], data)


@pytest.mark.parametrize("starts", [0, 1000, 1500, 1999])
def test_group_visibility_reserves_complete_descendants_for_entire_interval(starts):
    data = prepared()
    action, _, _, frames, _ = data
    rows = [visibility(action, frames), moving(action, frames, "object-system", start=starts, end=2500)]
    with pytest.raises(ReplayError, match="Group.*reserved"):
        run(sorted(rows, key=lambda row: row.start_ms), data)


def test_descendant_action_at_exact_group_completion_is_allowed():
    data = prepared()
    action, _, _, frames, _ = data
    # Local leaf state stays visible even when the composite has just exited.
    trace = run([visibility(action, frames), moving(action, frames, "object-system", start=2000, end=3000)], data)
    assert trace.at(2500).object("object-system").transform.position.x == frames["object-system"].transform.position.x + 150


@pytest.mark.parametrize("managed", [False, True])
def test_group_visibility_reserves_endpoint_reads_of_external_connectors(managed):
    data = prepared()
    action, objects, hierarchy, frames, versions = data
    layout, _ = connector_documents()
    arrow = ConnectorObject.model_validate(layout["objects"][-1])
    objects[arrow.object_id] = arrow
    frames[arrow.object_id] = replace(frames["object-evidence"], object_id=arrow.object_id, state="hidden", visible=False)
    versions[arrow.object_id] = 1
    hierarchy = HierarchySnapshot.from_objects(objects)
    peer = visibility(action, frames, (arrow.object_id,), verb="draw", key="arrow-in", start=1500, end=2500).model_dump(mode="json")
    if managed:
        peer["action"].pop("target_ids")
        peer["action"].pop("annotation")
        peer["action"].update(verb="connect", connector_id=arrow.object_id,
            source_object_id="object-system", source_anchor_id="center",
            destination_object_id="object-label", destination_anchor_id="center")
    with pytest.raises(ReplayError, match="Group.*reserved"):
        run([visibility(action, frames), resolved(peer["action"], 1500, 2500)],
            (action, objects, hierarchy, frames, versions))


@pytest.mark.parametrize("regroup", [False, True])
def test_group_visibility_reservation_uses_current_receipt_hierarchy(regroup):
    from test_v2_hierarchy_replay import reverse

    data = prepared()
    action, objects, hierarchy, frames, versions = data
    structural = action
    if regroup:
        from atme.render.v2_hierarchy_replay import apply_hierarchy_step

        outcome = apply_hierarchy_step(action, objects, hierarchy, frames, versions, "board-main")
        hierarchy, frames, versions = outcome.hierarchy, {row.object_id: row for row in outcome.objects}, dict(outcome.state_versions)
        structural = reverse(action)
    root_frames = dict(frames)
    root_frames["object-group"] = replace(root_frames["object-group"], state="grouped" if regroup else "ungrouped")
    rows = [resolved(structural, 100, 500), visibility(action, root_frames, start=1000, end=2000),
            moving(action, frames, "object-system", start=1500, end=2500)]
    if regroup:
        with pytest.raises(ReplayError, match="Group.*reserved"):
            run(rows, (action, objects, hierarchy, frames, versions))
    else:
        trace = run(rows, data)
        assert trace.at(2000).hierarchy.ancestors("object-system") == ()
        assert trace.at(2000).object("object-system").transform.position.x == frames["object-system"].transform.position.x + 150


def test_roots_become_disjoint_before_visibility_capture_not_initial_layout():
    from atme.render.v2_hierarchy import changed_hierarchy_objects
    from atme.render.v2_hierarchy_replay import completed_hierarchy_basis
    from atme.store.contracts_v2 import GroupAction, HierarchyBasis

    data = second_group(prepared(), nested=True)
    action, objects, hierarchy, frames, _ = data
    source = completed_hierarchy_basis(hierarchy, frames)
    after = HierarchySnapshot(tuple(
        replace(node, parent_id=None, sibling_ordinal=1) if node.object_id == "object-group"
        else replace(node, sibling_ordinal=2) if node.object_id == "object-evidence"
        else node for node in hierarchy.nodes))
    destination = source.model_dump(mode="json")
    actual = {node.object_id: node for node in after.nodes}
    for placement in destination["placements"]:
        placement.update(parent_id=actual[placement["object_id"]].parent_id,
                         sibling_ordinal=actual[placement["object_id"]].sibling_ordinal)
    doc = action.model_dump(mode="json")
    doc.update(action_id="detach-group", target_ids=["object-group"], container_id="other-group",
        hierarchy_policy={"member_root_ids": ["object-group"], "source_basis": source.model_dump(mode="json"),
            "destination_basis": destination, "source_basis_sha256": source.checksum(),
            "destination_basis_sha256": HierarchyBasis.model_validate(destination).checksum(),
            "changed_object_ids": list(changed_hierarchy_objects(hierarchy, after, objects)),
            "preserve_world_transform": True})
    exit_doc = visibility(action, frames, ("object-group", "other-group")).action.model_dump(mode="json")
    exit_doc["expected_state"] = None
    trace = run([resolved(GroupAction.model_validate(doc), 100, 500), resolved(exit_doc, 1000, 2000)], data)
    assert trace.at(1500).hierarchy.ancestors("object-group") == ()
    assert not trace.at(2000).object("object-group").visible
    assert not trace.at(2000).object("other-group").visible
