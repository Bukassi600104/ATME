"""Connection history must reject geometry that would fail later SVG painting."""

import xml.etree.ElementTree as ET
from copy import deepcopy
from dataclasses import replace
from math import cos, radians, sin

import pytest
from test_v2_annotation_action import append_target
from test_v2_connection_actions import relationship_documents
from test_v2_group_annotation import consumer_clock, private_svg
from test_v2_group_hierarchy import grouped_documents
from test_v2_hierarchy_contract import rehash
from test_v2_timeline_replay import resolved
from v2_fixtures import common_action, digest

from atme.render.v2_hierarchy import HierarchySnapshot, changed_hierarchy_objects
from atme.render.v2_state import V2FrameError, validate_resolved_return_history
from atme.store.contracts_v2 import (
    ExecutableLayoutV2,
    HierarchyBasis,
    ResolvedVisualTimelineV2,
)


def validate_history(layout, timeline):
    validate_resolved_return_history(
        ExecutableLayoutV2.model_validate(layout),
        ResolvedVisualTimelineV2.model_validate(timeline),
        layout_sha256=digest(layout),
    )


def grouped_connection_documents(*, regroup=False, portrait=False, routing="straight"):
    """Authored nested nonuniform/rotated Group receipt followed by a bound arrow."""
    layout, timeline = relationship_documents()
    arrow = layout["objects"][3]
    arrow.update(destination_object_id="object-evidence", routing=routing, beat_id="beat-002")
    arrow["geometry"]["bounds"] = {"x": 0, "y": 0, "width": 1280, "height": 720}
    for row, start, end in zip(timeline["actions"][2:], (6000, 7000), (6500, 7500), strict=True):
        row["action"]["destination_object_id"] = "object-evidence"
        row.update(resolved(row["action"], start, end).model_dump(mode="json"))
    group = deepcopy(grouped_documents()[0]["objects"][3])
    group.update(initial_state="grouped")
    group["geometry"]["bounds"] = {"x": 0, "y": 0, "width": 1280, "height": 720}
    group["transform"].update(position={"x": 20, "y": 10}, origin={"x": 0, "y": 0},
                              scale_x=1.1, scale_y=.9, rotation_degrees=7)
    outer = deepcopy(group)
    outer.update(object_id="outer-group", child_ids=["object-group"], z_index=-1, initial_state="visible")
    outer["transform"].update(position={"x": 30, "y": 20}, scale_x=.9, scale_y=1.1, rotation_degrees=5)
    group["parent_id"] = "outer-group"
    layout["objects"].extend([group, outer])
    for obj in layout["objects"][:2]:
        obj["parent_id"] = "object-group"
        obj["transform"]["origin"] = {"x": 0, "y": 0}
    for obj in (group, outer):
        timeline["initial_object_states"].append({"object_id": obj["object_id"], "state": obj["initial_state"],
                                                   "visible": True, "state_version": 1})
    reveal = deepcopy(timeline["actions"][0]["action"])
    reveal.update(action_id="evidence-reveal", target_ids=["object-evidence"])
    timeline["actions"].append(resolved(reveal, 3000, 3900).model_dump(mode="json"))
    timeline["coverage"][0]["action_ids"].append("evidence-reveal")
    if portrait:
        profile = {"profile_id": "SHORT_FORM_9_16", "width": 720, "height": 1280, "fps": 30}
        layout["output_profile"] = deepcopy(profile)
        timeline["output_profile"] = deepcopy(profile)
        layout["canvas"].update(width=720, height=1280)
        boxes = ((80, 180, 450, 320), (100, 220, 320, 80), (120, 750, 450, 300))
        for obj, box in zip(layout["objects"][:3], boxes, strict=True):
            obj["geometry"]["bounds"] = dict(zip(("x", "y", "width", "height"), box, strict=True))
        for obj in (arrow, group, outer):
            obj["geometry"]["bounds"].update(width=720, height=1280)
    layout["boards"][0].update(object_ids=[obj["object_id"] for obj in layout["objects"]], density_limit=6)
    objects = {obj.object_id: obj for obj in ExecutableLayoutV2.model_validate(layout).objects}
    before = HierarchySnapshot.from_objects(objects)
    member_ordinals = {"object-system": 1, "object-label": 2}
    after = HierarchySnapshot(tuple(replace(node, parent_id="outer-group", sibling_ordinal=member_ordinals[node.object_id])
                                    if node.object_id in member_ordinals else node for node in before.nodes))

    def moved_transform(obj):
        # Bake the shell's affine about page origin into each child's own origin.
        transform = deepcopy(group["transform"])
        x, y = obj.geometry.bounds.x, obj.geometry.bounds.y
        angle = radians(7)
        transform["position"] = {"x": 20 + 1.1 * cos(angle) * x - .9 * sin(angle) * y - x,
                                 "y": 10 + 1.1 * sin(angle) * x + .9 * cos(angle) * y - y}
        return transform
    bases = [HierarchyBasis(placements=[{
        "object_id": node.object_id, "board_id": node.board_id, "parent_id": node.parent_id,
        "sibling_ordinal": node.sibling_ordinal,
        "local_transform": (moved_transform(objects[node.object_id]) if snapshot is after
                            and node.object_id in ("object-system", "object-label")
                            else objects[node.object_id].transform.model_dump(mode="json")),
    } for node in snapshot.nodes]) for snapshot in (before, after)]
    action = deepcopy(reveal)
    action.pop("annotation", None)
    action.update(action_id="group-connection", verb="ungroup", target_ids=["object-system", "object-label"],
                  container_id="object-group", easing="step", expected_state="grouped", post_state="ungrouped",
                  hierarchy_policy={"member_root_ids": ["object-system", "object-label"],
                    "source_basis": bases[0].model_dump(mode="json"), "destination_basis": bases[1].model_dump(mode="json"),
                    "source_basis_sha256": bases[0].checksum(), "destination_basis_sha256": bases[1].checksum(),
                    "changed_object_ids": list(changed_hierarchy_objects(before, after, objects)),
                    "preserve_world_transform": True})
    if regroup:
        policy = action["hierarchy_policy"]
        policy["source_basis"], policy["destination_basis"] = policy["destination_basis"], policy["source_basis"]
        action.update(verb="group", expected_state="ungrouped", post_state="grouped")
        rehash(action)
        placements = {row["object_id"]: row for row in policy["source_basis"]["placements"]}
        for obj in layout["objects"]:
            placement = placements[obj["object_id"]]
            obj.update(parent_id=placement["parent_id"], z_index=placement["sibling_ordinal"] * 10,
                       transform=deepcopy(placement["local_transform"]))
            if obj["object_type"] == "group":
                obj["child_ids"] = [row["object_id"] for row in sorted(placements.values(), key=lambda row: row["sibling_ordinal"])
                                    if row["parent_id"] == obj["object_id"]]
        group["initial_state"] = "ungrouped"
        next(row for row in timeline["initial_object_states"] if row["object_id"] == "object-group")["state"] = "ungrouped"
        layout["initial_empty_group_ownership"] = [{"shell_object_id": "object-group", "owner_group_action_id": action["action_id"],
                                                    "owner_source_basis_sha256": policy["source_basis_sha256"]}]
    timeline["initial_hierarchy_basis"] = deepcopy(action["hierarchy_policy"]["source_basis"])
    timeline["initial_hierarchy_basis_sha256"] = action["hierarchy_policy"]["source_basis_sha256"]
    timeline["actions"].append(resolved(action, 4000, 5000).model_dump(mode="json"))
    timeline["actions"].sort(key=lambda row: row["start_ms"])
    timeline["coverage"][0]["action_ids"].append("group-connection")
    timeline["layout_sha256"] = digest(layout)
    return layout, timeline


@pytest.mark.parametrize("case,match", [
    ("bounds", "exceeds authored bounds"),
    ("coincident", "degenerate"),
    ("head", "head exceeds authored bounds"),
])
def test_connection_storage_history_rejects_unpaintable_geometry(case, match):
    # Removing sampled route/head validation must admit these corrupt histories.
    layout, timeline = relationship_documents()
    arrow = layout["objects"][3]
    if case == "bounds":
        arrow["geometry"]["bounds"] = {"x": 0, "y": 0, "width": 10, "height": 10}
    elif case == "coincident":
        layout["objects"][1]["geometry"]["bounds"] = deepcopy(layout["objects"][0]["geometry"]["bounds"])
    else:
        # Exact center anchors (320,330) and (300,250) fit; the head's wing does not.
        arrow["geometry"]["bounds"] = {"x": 300, "y": 250, "width": 20, "height": 80}
    timeline["layout_sha256"] = digest(layout)
    original = deepcopy((layout, timeline))
    with pytest.raises(V2FrameError, match=match):
        validate_history(layout, timeline)
    assert (layout, timeline) == original


def test_valid_connection_history_keeps_relationship_versions_and_seek_state():
    layout, timeline = relationship_documents()
    validate_history(layout, timeline)
    _, replay, _ = consumer_clock(layout, timeline)
    assert replay.at(4900).object("object-arrow").state == "connected"
    assert replay.at(6900).object("object-arrow").state == "disconnected"
    assert dict(replay.at(6900).state_versions)["object-arrow"] == 3
    assert replay.at(4450) == replay.at(4450)


def append_endpoint_move(layout, timeline, start, end, *, x=5):
    template = common_action("endpoint-move", "instruction-1")
    template.update(action_id="endpoint-move", verb="move", target_ids=["object-system"],
                    coverage_id="coverage-1", fallback={"fallback_id": "fallback-1", "on_failure": "block"},
                    expected_state="visible", post_state="visible", opacity=None,
                    destination=deepcopy(layout["objects"][0]["transform"]))
    template["destination"]["position"]["x"] = x
    timeline["actions"].append(resolved(template, start, end).model_dump(mode="json"))
    timeline["actions"].sort(key=lambda row: row["start_ms"])
    timeline["coverage"][0]["action_ids"].append("endpoint-move")


@pytest.mark.parametrize("start,end", [(4200, 4500), (5200, 5500), (6200, 6500)])
def test_retained_connection_rejects_endpoint_motion_until_disconnect_completes(start, end):
    layout, timeline = relationship_documents()
    append_endpoint_move(layout, timeline, start, end)
    with pytest.raises(V2FrameError, match="connected lifetime"):
        validate_history(layout, timeline)


def test_connection_without_disconnect_rejects_late_unpaintable_endpoint_edit():
    layout, timeline = relationship_documents()
    timeline["actions"].pop()
    timeline["coverage"][2]["action_ids"].remove("action-4")
    append_endpoint_move(layout, timeline, 8000, 8500, x=1000)
    with pytest.raises(V2FrameError, match="connected lifetime"):
        validate_history(layout, timeline)


@pytest.mark.parametrize("start,end", [(3200, 3500), (6900, 7500)])
def test_endpoint_motion_outside_managed_relationship_lifetime_is_allowed(start, end):
    layout, timeline = relationship_documents()
    append_endpoint_move(layout, timeline, start, end)
    validate_history(layout, timeline)


def test_reconnect_after_completed_disconnect_captures_new_endpoint_pose():
    from atme.render.v2_svg import compose_svg_frame

    layout, timeline = relationship_documents()
    append_endpoint_move(layout, timeline, 6900, 7500)
    action = deepcopy(next(row["action"] for row in timeline["actions"] if row["action"]["verb"] == "connect"))
    action["action_id"] = "reconnect"
    timeline["actions"].append(resolved(action, 8000, 8500).model_dump(mode="json"))
    timeline["coverage"][2]["action_ids"].append("reconnect")
    validate_history(layout, timeline)
    assert 'd="M 320 330 L 300 250"' in compose_svg_frame(layout, timeline, 4900).svg
    assert 'd="M 325 330 L 300 250"' in compose_svg_frame(layout, timeline, 8500).svg


@pytest.mark.parametrize("routing", ["straight", "elbow", "curve"])
@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("regroup", [False, True])
def test_completed_nested_group_connection_uses_current_world_anchors(regroup, portrait, routing):
    layout, timeline = grouped_connection_documents(regroup=regroup, portrait=portrait, routing=routing)
    original = deepcopy((layout, timeline))
    validate_history(layout, timeline)
    context, replay, camera = consumer_clock(layout, timeline)
    captured = replay.before_action("action-3")
    expected_parents = ("object-group", "outer-group") if regroup else ("outer-group",)
    assert captured.hierarchy.ancestors("object-system") == expected_parents
    assert captured.hierarchy.ancestors("object-evidence") == ()
    assert dict(replay.at(6500).state_versions)["object-arrow"] == 2
    assert dict(replay.at(7500).state_versions)["object-arrow"] == 3
    frames = {}
    for at in (5000, 6000, 6250, 6500, 7000, 7250, 7500):
        frames[at] = private_svg(context, replay, camera, at).svg
        root = ET.fromstring(frames[at])
        arrows = [node for node in root.iter() if node.attrib.get("data-object-id") == "object-arrow"]
        assert bool(arrows) == (6000 < at < 7500)
        if arrows:
            assert sum(node.tag.endswith("polygon") for node in arrows[0]) == (at in (6500, 7000))
            path = next(node for node in arrows[0] if node.tag.endswith("path"))
            tokens = path.attrib["d"].split()
            expected_start = (279.0587, 433.3467) if portrait else (295.3889, 427.1321)
            expected_end = (345, 900) if portrait else (930, 340)
            assert tuple(map(float, tokens[1:3])) == pytest.approx(expected_start, abs=.0002)
            assert tuple(map(float, tokens[-2:])) == expected_end
            if routing == "elbow":
                assert tuple(map(float, tokens[4:6])) == pytest.approx((expected_end[0], expected_start[1]), abs=.0002)
    assert frames[6250] != frames[6500]
    assert private_svg(context, replay, camera, 6250).svg == frames[6250]
    assert (layout, timeline) == original


@pytest.mark.parametrize("regroup", [False, True])
@pytest.mark.parametrize("target,verb", [("object-system", "fade"), ("object-evidence", "exit"),
                                         ("outer-group", "rotate")])
def test_connected_nested_endpoint_or_ancestor_edits_require_completed_disconnect(regroup, target, verb):
    layout, timeline = grouped_connection_documents(regroup=regroup)
    options = {}
    if verb == "fade":
        options["opacity"] = .5
    elif verb == "rotate":
        options["destination"] = deepcopy(next(obj for obj in layout["objects"] if obj["object_id"] == target)["transform"])
        options["destination"]["rotation_degrees"] = 15
    elif verb == "exit":
        timeline["actions"] = [row for row in timeline["actions"] if row["action"]["action_id"] != "action-4"]
        timeline["coverage"][2]["action_ids"].remove("action-4")
    append_target(timeline, target, verb, 6700, 6800, **options)
    with pytest.raises(V2FrameError, match="connected lifetime"):
        validate_history(layout, timeline)


@pytest.mark.parametrize("regroup", [False, True])
def test_later_related_hierarchy_edit_is_rejected_during_connected_hold(regroup):
    layout, timeline = grouped_connection_documents(regroup=regroup)
    action = deepcopy(next(row["action"] for row in timeline["actions"] if row["action"]["verb"] in {"group", "ungroup"}))
    policy = action["hierarchy_policy"]
    policy["source_basis"], policy["destination_basis"] = policy["destination_basis"], policy["source_basis"]
    action.update(action_id="group-during-connection", verb="ungroup" if regroup else "group",
                  expected_state="grouped" if regroup else "ungrouped", post_state="ungrouped" if regroup else "grouped")
    rehash(action)
    timeline["actions"].append(resolved(action, 6700, 6800).model_dump(mode="json"))
    timeline["actions"].sort(key=lambda row: row["start_ms"])
    timeline["coverage"][0]["action_ids"].append(action["action_id"])
    with pytest.raises(V2FrameError, match="connected lifetime"):
        validate_history(layout, timeline)


@pytest.mark.parametrize("regroup", [False, True])
@pytest.mark.parametrize("case", ["hidden_destination", "transparent_ancestor"])
def test_sampled_endpoint_and_ancestor_visibility_is_proved_after_group(regroup, case):
    layout, timeline = grouped_connection_documents(regroup=regroup)
    if case == "hidden_destination":
        timeline["actions"] = [row for row in timeline["actions"] if row["action"]["action_id"] != "evidence-reveal"]
        timeline["coverage"][0]["action_ids"].remove("evidence-reveal")
    else:
        append_target(timeline, "outer-group", "fade", 5500, 5600, opacity=0)
    with pytest.raises(V2FrameError, match="hidden endpoint"):
        validate_history(layout, timeline)


@pytest.mark.parametrize("regroup", [False, True])
def test_unrelated_group_during_connection_does_not_block_other_relationships(regroup):
    layout, timeline = grouped_connection_documents(regroup=regroup)
    unrelated = deepcopy(layout["objects"][2])
    unrelated.update(object_id="unrelated-endpoint", initial_state="visible", visible=True, z_index=60)
    unrelated["geometry"]["bounds"] = {"x": 950, "y": 500, "width": 80, "height": 60}
    layout["objects"].append(unrelated)
    layout["boards"][0]["object_ids"].append("unrelated-endpoint")
    layout["boards"][0]["density_limit"] = 7
    timeline["initial_object_states"].append({"object_id": "unrelated-endpoint", "state": "visible",
                                              "visible": True, "state_version": 1})
    placement = {"object_id": "unrelated-endpoint", "board_id": "board-main", "parent_id": None,
                 "sibling_ordinal": 3, "local_transform": deepcopy(unrelated["transform"])}
    group = next(row for row in timeline["actions"] if row["action"]["verb"] in {"group", "ungroup"})
    for side in ("source", "destination"):
        group["action"]["hierarchy_policy"][f"{side}_basis"]["placements"].append(deepcopy(placement))
        group["action"]["hierarchy_policy"][f"{side}_basis"]["placements"].sort(key=lambda row: row["object_id"])
    rehash(group["action"])
    if regroup:
        layout["initial_empty_group_ownership"][0]["owner_source_basis_sha256"] = group["action"]["hierarchy_policy"]["source_basis_sha256"]
    group.update(resolved(group["action"], 6200, 6400).model_dump(mode="json"))
    timeline["initial_hierarchy_basis"] = deepcopy(group["action"]["hierarchy_policy"]["source_basis"])
    timeline["initial_hierarchy_basis_sha256"] = group["action"]["hierarchy_policy"]["source_basis_sha256"]
    layout["objects"][3]["source_object_id"] = "unrelated-endpoint"
    for row in timeline["actions"]:
        if row["action"]["verb"] in {"connect", "disconnect"}:
            row["action"]["source_object_id"] = "unrelated-endpoint"
    timeline["actions"].sort(key=lambda row: row["start_ms"])
    timeline["layout_sha256"] = digest(layout)
    validate_history(layout, timeline)
    context, replay, camera = consumer_clock(layout, timeline)
    assert replay.at(6250).object("object-arrow").visible
    assert 'data-object-id="object-arrow"' in private_svg(context, replay, camera, 6250).svg


def initially_connected_documents(builder=relationship_documents, **kwargs):
    layout, timeline = builder(**kwargs)
    initialized = {"object-system", "object-label", "object-evidence"}
    for obj in layout["objects"]:
        if obj["object_id"] in initialized:
            obj.update(initial_state="visible", visible=True)
        elif obj["object_id"] == "object-arrow":
            obj.update(initial_state="connected", visible=True)
    for row in timeline["initial_object_states"]:
        if row["object_id"] in initialized:
            row.update(state="visible", visible=True)
        elif row["object_id"] == "object-arrow":
            row.update(state="connected", visible=True)
    removed_ids = {row["action"]["action_id"] for row in timeline["actions"]
                   if row["action"]["verb"] in {"connect", "reveal"}}
    timeline["actions"] = [row for row in timeline["actions"] if row["action"]["action_id"] not in removed_ids]
    for coverage in timeline["coverage"]:
        coverage["action_ids"] = [key for key in coverage["action_ids"] if key not in removed_ids]
    removed_instructions = {row["instruction_id"] for row in timeline["coverage"] if not row["action_ids"]}
    timeline["coverage"] = [row for row in timeline["coverage"] if row["action_ids"]]
    for fallback in timeline["fallbacks"]:
        fallback["affected_ids"] = [key for key in fallback["affected_ids"] if key not in removed_instructions]
    timeline["fallbacks"] = [row for row in timeline["fallbacks"] if row["affected_ids"]]
    timeline["layout_sha256"] = digest(layout)
    return layout, timeline


def test_initially_connected_valid_baseline_and_exact_disconnect_end_edit():
    layout, timeline = initially_connected_documents()
    validate_history(layout, timeline)
    # Keep real coverage for a new source edit, rather than inventing a hidden reveal.
    timeline["coverage"].insert(0, {"coverage_id": "coverage-1", "instruction_id": "instruction-1",
                                   "status": "executed", "action_ids": [], "fallback_id": None})
    timeline["fallbacks"].append(deepcopy(relationship_documents()[1]["fallbacks"][0]))
    append_endpoint_move(layout, timeline, 6900, 7500)
    validate_history(layout, timeline)


def test_initially_connected_rejects_endpoint_motion_before_first_disconnect():
    layout, timeline = initially_connected_documents()
    validate_history(layout, timeline)  # Establish that rejection is not an invalid baseline.
    timeline["coverage"].insert(0, {"coverage_id": "coverage-1", "instruction_id": "instruction-1",
                                   "status": "executed", "action_ids": [], "fallback_id": None})
    timeline["fallbacks"].append(deepcopy(relationship_documents()[1]["fallbacks"][0]))
    append_endpoint_move(layout, timeline, 5200, 5500)
    with pytest.raises(V2FrameError, match="connected lifetime"):
        validate_history(layout, timeline)


@pytest.mark.parametrize("case,match", [("bounds", "exceeds authored bounds"),
                                       ("head", "head exceeds authored bounds")])
def test_initially_connected_geometry_is_proved_before_first_disconnect(case, match):
    layout, timeline = initially_connected_documents()
    validate_history(layout, timeline)
    layout["objects"][3]["geometry"]["bounds"] = (
        {"x": 0, "y": 0, "width": 10, "height": 10} if case == "bounds" else
        {"x": 300, "y": 250, "width": 20, "height": 80})
    timeline["layout_sha256"] = digest(layout)
    with pytest.raises(V2FrameError, match=match):
        validate_history(layout, timeline)


@pytest.mark.parametrize("regroup", [False, True])
def test_initially_connected_rejects_related_group_before_first_disconnect(regroup):
    layout, timeline = initially_connected_documents(grouped_connection_documents, regroup=regroup)
    with pytest.raises(V2FrameError, match="connected lifetime"):
        validate_history(layout, timeline)


def test_initially_connected_rejects_ancestor_edit_before_first_disconnect():
    layout, timeline = initially_connected_documents()
    group = deepcopy(grouped_documents()[0]["objects"][3])
    group["child_ids"] = ["object-system"]
    layout["objects"][0]["parent_id"] = "object-group"
    layout["objects"].append(group)
    layout["boards"][0]["object_ids"].append("object-group")
    timeline["initial_object_states"].append({"object_id": "object-group", "state": "visible",
                                              "visible": True, "state_version": 1})
    timeline["layout_sha256"] = digest(layout)
    validate_history(layout, timeline)
    action = common_action("action-1", "instruction-1")
    action.update(action_id="ancestor-fade", verb="fade", target_ids=["object-group"],
                  expected_state="visible", post_state="visible", opacity=.5, destination=None)
    timeline["actions"].insert(0, resolved(action, 5200, 5500).model_dump(mode="json"))
    timeline["coverage"].insert(0, {"coverage_id": "coverage-1", "instruction_id": "instruction-1",
                                   "status": "executed", "action_ids": ["ancestor-fade"], "fallback_id": None})
    timeline["fallbacks"].append(deepcopy(relationship_documents()[1]["fallbacks"][0]))
    with pytest.raises(V2FrameError, match="connected lifetime"):
        validate_history(layout, timeline)
