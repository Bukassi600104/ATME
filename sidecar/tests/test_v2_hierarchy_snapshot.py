"""Shared immutable hierarchy foundation; group actions are not enabled yet."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import FrozenInstanceError, replace

import pytest
from test_v2_group_hierarchy import grouped_documents
from v2_fixtures import digest

from atme.render.v2_hierarchy import (
    HierarchyNode,
    HierarchySnapshot,
    UnsupportedHierarchy,
    changed_hierarchy_objects,
    validate_transition_scope,
    validate_world_preservation,
)
from atme.render.v2_state import UnsupportedVisualAction, evaluate_frame
from atme.render.v2_svg import compose_png_frame, compose_svg_frame
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


def test_projection_keeps_authored_layer_identity_separate_from_dense_sibling_order():
    from test_v2_replace_action import documents

    layout, _ = documents()
    objects = {obj.object_id: obj for obj in ExecutableLayoutV2.model_validate(layout).objects}
    hierarchy = HierarchySnapshot.from_objects(objects)
    projected = hierarchy.object_map(objects)
    assert objects["object-system"].z_index == objects["object-replacement"].z_index
    assert projected["object-system"].z_index == projected["object-replacement"].z_index
    assert {key: obj.z_index for key, obj in projected.items()} == {key: obj.z_index for key, obj in objects.items()}
    root_ids = hierarchy.children("board-main", None)
    assert root_ids.index("object-system") != root_ids.index("object-replacement")


def test_svg_uses_snapshot_sibling_order_even_when_it_opposes_authored_layers(monkeypatch):
    import xml.etree.ElementTree as ET

    import atme.render.v2_svg as svg_module

    layout, timeline, objects, hierarchy = basis()
    frame = evaluate_frame(layout, timeline, 5000)
    reversed_children = HierarchySnapshot(tuple(
        replace(node, sibling_ordinal=1 - node.sibling_ordinal) if node.parent_id == "object-group" else node
        for node in hierarchy.nodes))
    projected = reversed_children.object_map(objects)
    assert projected["object-system"].z_index < projected["object-label"].z_index
    monkeypatch.setattr(svg_module, "evaluate_frame", lambda *args: replace(frame, hierarchy=reversed_children))
    root = ET.fromstring(compose_svg_frame(layout, timeline, 5000).svg)
    group = next(node for node in root.iter() if node.attrib.get("data-object-id") == "object-group")
    assert [child.attrib["data-object-id"] for child in group] == ["object-label", "object-system"]


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


@pytest.mark.parametrize("portrait", [False, True])
def test_frame_owns_complete_immutable_hierarchy_and_random_seeks_do_not_mutate_source(portrait):
    layout, timeline, _, expected = basis()
    if portrait:
        for document in (layout, timeline):
            document["output_profile"] = {"profile_id": "SHORT_FORM_9_16", "width": 720, "height": 1280, "fps": 30}
        layout["canvas"].update(width=720, height=1280)
        timeline["layout_sha256"] = digest(layout)
    original = deepcopy((layout, timeline))
    frame = evaluate_frame(layout, timeline, 5000)
    assert frame.hierarchy == expected
    with pytest.raises(FrozenInstanceError):
        frame.hierarchy.nodes[0].parent_id = None
    pixels = compose_png_frame(layout, timeline, 5000).png
    evaluate_frame(layout, timeline, 9000)
    assert evaluate_frame(layout, timeline, 5000) == frame
    assert compose_png_frame(layout, timeline, 5000).png == pixels
    assert (layout, timeline) == original


def test_state_camera_and_svg_consume_the_same_frame_hierarchy(monkeypatch):
    import atme.render.v2_state as state_module
    import atme.render.v2_svg as svg_module

    layout, timeline, _, _ = basis()
    observed = {}
    original_camera = state_module.camera_segments
    original_temporal = state_module._validate_pair_temporal
    original_evaluate = svg_module.evaluate_frame
    original_map = HierarchySnapshot.object_map

    def camera(layout, timeline, replay):
        observed["camera_calls"] = observed.get("camera_calls", 0) + 1
        observed["camera_clock"] = replay
        plan = original_camera(layout, timeline, replay)
        observed["camera_plan"] = plan
        return plan

    def temporal(context, replay, plan):
        observed["temporal_clock"] = replay
        observed["temporal_plan"] = plan
        return original_temporal(context, replay, plan)

    def evaluate(*args):
        snapshot = original_evaluate(*args)
        observed["frame"] = snapshot.hierarchy
        observed["frame_ready"] = True
        return snapshot

    def project(self, objects):
        if observed.get("frame_ready"):
            observed.setdefault("svg_consumers", []).append(self)
        return original_map(self, objects)

    monkeypatch.setattr(state_module, "camera_segments", camera)
    monkeypatch.setattr(state_module, "_validate_pair_temporal", temporal)
    monkeypatch.setattr(svg_module, "evaluate_frame", evaluate)
    monkeypatch.setattr(HierarchySnapshot, "object_map", project)
    rendered = compose_svg_frame(layout, timeline, 5000)
    assert 'data-object-id="object-group"' in rendered.svg
    assert observed["camera_calls"] == 1
    assert observed["camera_clock"] is observed["temporal_clock"]
    assert observed["camera_plan"] is observed["temporal_plan"]
    assert observed["camera_clock"].at(5000).hierarchy is observed["frame"]
    assert observed["svg_consumers"]
    assert all(snapshot is observed["frame"] for snapshot in observed["svg_consumers"])


@pytest.mark.parametrize("fixture", ["annotation", "evidence"])
def test_all_annotation_and_evidence_camera_checks_share_frame_hierarchy(monkeypatch, tmp_path, fixture):
    from test_v2_annotation_contract import annotation_documents
    from test_v2_evidence_compositor import evidence_documents

    import atme.render.v2_state as state_module

    if fixture == "annotation":
        _, layout, timeline = annotation_documents()
        service = None
    else:
        service, layout, timeline, _ = evidence_documents(tmp_path)
    observed = {}
    original = state_module.camera_segments
    original_temporal = state_module._validate_pair_temporal

    def camera(layout, timeline, replay):
        observed["camera_calls"] = observed.get("camera_calls", 0) + 1
        observed["camera_clock"] = replay
        plan = original(layout, timeline, replay)
        observed["camera_plan"] = plan
        return plan

    def temporal(context, replay, plan):
        observed["temporal_clock"] = replay
        observed["temporal_plan"] = plan
        return original_temporal(context, replay, plan)

    monkeypatch.setattr(state_module, "camera_segments", camera)
    monkeypatch.setattr(state_module, "_validate_pair_temporal", temporal)
    try:
        frame = evaluate_frame(layout, timeline, 100)
    finally:
        if service is not None:
            service.store.close()
    assert observed["camera_calls"] == 1
    assert observed["camera_clock"] is observed["temporal_clock"]
    assert observed["camera_plan"] is observed["temporal_plan"]
    assert observed["camera_clock"].at(100).hierarchy is frame.hierarchy


def test_topology_checks_observe_projected_connector_ancestry_not_stored_layout():
    from test_v2_connector_svg import connector_documents

    from atme.render.v2_state import V2FrameError, validate_static_hierarchy

    _, _, grouped_objects, grouped = basis()
    connector_layout, _ = connector_documents()
    connector = ExecutableLayoutV2.model_validate(connector_layout).objects[-1]
    objects = dict(grouped_objects)
    objects["object-group"].object_type = "clip"
    objects[connector.object_id] = connector
    group_layout, _, _, _ = basis()
    group_layout["objects"][3]["object_type"] = "clip"
    group_layout["objects"].append(connector.model_dump(mode="json"))
    group_layout["boards"][0]["object_ids"].append(connector.object_id)
    parsed = ExecutableLayoutV2.model_validate(group_layout)
    with pytest.raises(V2FrameError, match="clipped-endpoint"):
        validate_static_hierarchy(parsed, HierarchySnapshot.from_objects(objects).object_map(objects))
    after = HierarchySnapshot(tuple(sorted(
        ungrouped(grouped).nodes + (HierarchyNode(connector.object_id, connector.board_id, None, 4),),
        key=lambda node: node.object_id)))
    validate_static_hierarchy(parsed, after.object_map(objects))


def test_svg_paint_tree_consumes_a_supplied_projection_without_enabling_group_actions(monkeypatch):
    import xml.etree.ElementTree as ET

    import atme.render.v2_svg as svg_module

    layout, timeline, _, before = basis()
    frame = evaluate_frame(layout, timeline, 5000)
    projected = replace(frame, hierarchy=ungrouped(before))
    monkeypatch.setattr(svg_module, "evaluate_frame", lambda *args: projected)
    root = ET.fromstring(compose_svg_frame(layout, timeline, 5000).svg)
    group = next(node for node in root.iter() if node.attrib.get("data-object-id") == "object-group")
    assert list(group) == []
    assert sum(node.attrib.get("data-object-id") == "object-system" for node in root.iter()) == 1
    assert sum(node.attrib.get("data-object-id") == "object-label" for node in root.iter()) == 1
