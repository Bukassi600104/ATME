"""Real character parts retain ordinary actions on the one hierarchy clock."""

from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from socket import socket
from xml.etree import ElementTree as ET

import pytest
from test_v2_character_assembly_contract import documents
from test_v2_connector_svg import connector_documents
from test_v2_group_annotation import consumer_clock
from test_v2_group_hierarchy import grouped_documents
from test_v2_split_identity import sample_for_layout
from test_v2_timeline_replay import resolved
from v2_fixtures import digest

from atme.render import v2_state
from atme.render.style_bundle import registry_endpoint_inputs_for_objects
from atme.render.v2_character_assembly import validate_character_transition
from atme.render.v2_hierarchy import HierarchySnapshot, changed_hierarchy_objects
from atme.render.v2_hierarchy_replay import completed_hierarchy_basis
from atme.render.v2_morph import geometry_object
from atme.render.v2_split_paint import verify_split_paint_inputs
from atme.render.v2_svg import (
    _compose_validated_svg_frame,
    _rasterize_svg_frame,
    compose_png_frame,
    compose_svg_frame,
)
from atme.render.v2_timeline_replay import ReplayError, replay_chronology
from atme.render.v2_world import world_anchor
from atme.store import contracts_v2 as contracts


def runtime_documents(*, portrait=False, verb="fade", target="actor-group", pose="neutral"):
    _, layout = documents(pose)
    _, timeline = grouped_documents()
    row = deepcopy(timeline["actions"][-1])
    common = ("action_id", "source_instruction_id", "board_id", "semantic_reason", "trigger",
              "easing", "expected_state", "post_state", "fallback", "coverage_id")
    row["action"] = {key: row["action"][key] for key in common}
    row["action"].update(verb=verb, target_ids=[target], expected_state="visible", post_state="visible",
                         easing="linear", trigger={"kind": "absolute", "at_ms": 0})
    if verb == "fade":
        row["action"].update(opacity=.5, destination=None)
    row.update(start_ms=0, end_ms=1000)
    row["resolved_trigger"].update(source=row["action"]["trigger"], alignment_anchor_ms=0,
                                    resolved_at_ms=0, matched_text=None, matched_occurrence=None)
    timeline.update(actions=[row], resolved_assets=[], coverage=[timeline["coverage"][2]],
                    fallbacks=[timeline["fallbacks"][2]])
    timeline["initial_object_states"] = [{"object_id": obj["object_id"], "state": obj["initial_state"],
        "visible": obj["visible"], "state_version": 1} for obj in layout["objects"]]
    if portrait:
        layout["output_profile"] = {"profile_id": "SHORT_FORM_9_16", "width": 720, "height": 1280, "fps": 30}
        layout["canvas"].update(width=720, height=1280)
        timeline["output_profile"] = deepcopy(layout["output_profile"])
    timeline.update(layout_sha256=digest(layout), plan_sha256=layout["plan_sha256"])
    return layout, timeline


def nested_role(layout, role="torso"):
    objects = {obj["object_id"]: obj for obj in layout["objects"]}
    part = objects["actor-" + role]
    group = deepcopy(objects["actor-group"])
    group.pop("character_assembly")
    group.update(object_id=part["object_id"] + "-role", parent_id="actor-group",
                 child_ids=[part["object_id"]], z_index=part["z_index"])
    part.update(parent_id=group["object_id"], z_index=0)
    actor = objects["actor-group"]
    actor["child_ids"][actor["child_ids"].index(part["object_id"])] = group["object_id"]
    next(row for row in actor["character_assembly"]["roles"] if row["role"] == role)["object_id"] = group["object_id"]
    layout["objects"].append(group)
    return group, part


def replacement_documents(verb="morph", *, anchored=False, cross_role=False, external=False):
    layout, timeline = runtime_documents()
    group, source = nested_role(layout, "head" if anchored else "torso")
    destination = deepcopy(source)
    destination.update(object_id=source["object_id"] + "-next", initial_state="hidden", visible=False)
    # Same authored layer is required by the existing Morph contract. Explicit
    # sibling order is (z_index, object_id), not unique z_index per leaf.
    if verb == "morph":
        destination["geometry"]["bounds"]["x"] += 20.
    if source["path_data"]:
        destination["path_data"] = source["path_data"].replace("330", "335")
    group["child_ids"].append(destination["object_id"])
    layout["objects"].append(destination)
    if cross_role:
        other, _ = nested_role(layout, "left_arm")
        group["child_ids"].remove(destination["object_id"])
        other["child_ids"].append(destination["object_id"])
        destination["parent_id"] = other["object_id"]
    elif external:
        group["child_ids"].remove(destination["object_id"])
        destination["parent_id"] = None
    layout["boards"][0].update(object_ids=[obj["object_id"] for obj in layout["objects"]], density_limit=12)
    row = timeline["actions"][0]
    action = row["action"]
    action.pop("target_ids")
    action.pop("opacity")
    action.pop("destination")
    action.update(verb=verb, from_object_id=source["object_id"], to_object_id=destination["object_id"])
    if verb == "morph":
        action["morph_policy"] = {"mapping": "canonical_outline" if anchored else "matching_path_commands",
            "paint": "shared_style", "transforms": "interpolate_all"}
        if not anchored:
            action["morph_policy"]["path_commands"] = ["M", "C", "C"]
    timeline["initial_object_states"].append({"object_id": destination["object_id"], "state": "hidden",
                                                "visible": False, "state_version": 1})
    timeline["initial_object_states"].extend({"object_id": obj["object_id"], "state": "visible",
        "visible": True, "state_version": 1} for obj in layout["objects"]
        if obj["object_id"] not in {row["object_id"] for row in timeline["initial_object_states"]})
    timeline["layout_sha256"] = digest(layout)
    return layout, timeline


def test_named_current_map_guard_reuses_exact_role_graph_and_anchor_contract():
    assert hasattr(contracts, "validate_character_assembly_map"), "named current-map authentication is missing"
    _, raw = documents()
    objects = {obj.object_id: obj for obj in contracts.ExecutableLayoutV2.model_validate(raw).objects}
    before = deepcopy(objects)
    contracts.validate_character_assembly_map(objects)
    assert objects == before
    objects["actor-head"] = objects["actor-head"].model_copy(update={"parent_id": None})
    with pytest.raises(ValueError, match="character_assembly"):
        contracts.validate_character_assembly_map(objects)


@pytest.mark.parametrize("verb", ["replace", "morph"])
def test_same_role_transition_keeps_stable_anchors_versions_and_random_seek(verb):
    layout, timeline = replacement_documents(verb)
    before = deepcopy((layout, timeline))
    # This must parse with the same-layer pair; a blanket tied-z rejection would
    # silently disable an already-approved ordinary action for character parts.
    contracts.ExecutableLayoutV2.model_validate(layout)
    middle = v2_state.evaluate_frame(layout, timeline, 500)
    assert middle.object("actor-torso").visible
    assert middle.object("actor-left_arm").visible
    end = v2_state.evaluate_frame(layout, timeline, 1000)
    assert end.object("actor-torso").state == "removed"
    assert end.object("actor-torso-next").visible
    context, replay, _ = consumer_clock(layout, timeline)
    assert dict(replay.at(500).state_versions) == {key: 1 for key in context.objects}
    assert dict(replay.at(1000).state_versions) == {key: 2 if key in {"actor-torso", "actor-torso-next"} else 1
                                                 for key in context.objects}
    for at_ms in (0, 500, 1000):
        sample = replay.at(at_ms)
        objects = sample.hierarchy.object_map(context.objects)
        transforms = {obj.object_id: obj.transform for obj in sample.objects}
        for key, anchor, expected in (("actor-head", "head-top", (370., 230.)),
            ("actor-left_arm", "hand", (310., 440.)), ("actor-right_arm", "hand", (435., 440.))):
            assert world_anchor(objects[key], anchor, objects, transforms) == expected
    sampled = replay.at(500)
    current = sampled.hierarchy.object_map(context.objects)
    current = {key: geometry_object(obj, sampled.object(key).morph_geometry) for key, obj in current.items()}
    transforms = {obj.object_id: obj.transform for obj in sampled.objects}
    assert world_anchor(current["actor-torso"], "hand", current, transforms) == (405. if verb == "morph" else 395., 315.)
    assert world_anchor(current["actor-torso-next"], "hand", current, transforms) == (415. if verb == "morph" else 395., 315.)
    for at_ms in (1000, 0, 999, 500):
        v2_state.evaluate_frame(layout, timeline, at_ms)
    assert v2_state.evaluate_frame(layout, timeline, 500) == middle
    assert (layout, timeline) == before


@pytest.mark.parametrize("verb", ["replace", "morph"])
def test_semantic_anchor_source_cannot_be_replaced_without_reauthoring_binding(verb):
    layout, timeline = replacement_documents(verb, anchored=True)
    with pytest.raises(ValueError, match="character_assembly.*anchor"):
        v2_state.evaluate_frame(layout, timeline, 0)


@pytest.mark.parametrize("fault", ["cross_role", "external"])
@pytest.mark.parametrize("verb", ["replace", "morph"])
def test_current_role_transition_cannot_borrow_a_foreign_destination(fault, verb):
    layout, timeline = replacement_documents(verb, **{fault: True})
    typed = contracts.ExecutableLayoutV2.model_validate(layout)
    objects = {obj.object_id: obj for obj in typed.objects}
    action = contracts.ResolvedVisualTimelineV2.model_validate(timeline).actions[0].action
    with pytest.raises(ValueError, match="character_assembly.*same real role"):
        validate_character_transition(action, objects, HierarchySnapshot.from_objects(objects))
    # The normal public path also rejects; its ordinary same-parent/layer gate
    # may reject before character ownership. No weaker alternative is admitted.
    with pytest.raises(ValueError):
        v2_state.evaluate_frame(layout, timeline, 0)


@pytest.mark.parametrize("fault", ["extra_child", "anchor", "cross_role_anchor", "role_order", "missing"])
def test_current_map_rejects_actual_graph_or_anchor_invalidation(fault):
    _, layout = documents()
    objects = {obj.object_id: obj for obj in contracts.ExecutableLayoutV2.model_validate(layout).objects}
    if fault == "extra_child":
        objects["object-system"] = objects["object-system"].model_copy(update={"parent_id": "actor-group"})
    elif fault == "anchor":
        objects["actor-head"] = objects["actor-head"].model_copy(update={"anchors": []})
    elif fault == "cross_role_anchor":
        objects["actor-group"].character_assembly.semantic_anchors[1].object_id = "actor-torso"
    elif fault == "role_order":
        objects["actor-group"].child_ids.reverse()
    else:
        objects.pop("actor-left_arm")
    with pytest.raises(ValueError, match="character_assembly"):
        contracts.validate_character_assembly_map(objects)


def structural_replay(container):
    layout, _ = runtime_documents()
    for obj in layout["objects"]:
        obj.update(initial_state="visible", visible=True)
    raw = next(obj for obj in layout["objects"] if obj["object_id"] == container)
    raw["initial_state"] = "grouped"
    typed = contracts.ExecutableLayoutV2.model_validate(layout)
    initial = sample_for_layout(typed)
    objects = {obj.object_id: obj for obj in typed.objects}
    frames = {obj.object_id: obj for obj in initial.objects}
    before = initial.hierarchy
    roots = list(before.children("board-main", None))
    members = list(before.children("board-main", container))
    index = roots.index(container) + 1
    roots[index:index] = members
    after = HierarchySnapshot(tuple(replace(node, parent_id=None, sibling_ordinal=roots.index(node.object_id))
        if node.object_id in roots else node for node in before.nodes))
    source = completed_hierarchy_basis(before, frames)
    destination = source.model_dump(mode="json")
    nodes = {node.object_id: node for node in after.nodes}
    for row in destination["placements"]:
        node = nodes[row["object_id"]]
        row.update(parent_id=node.parent_id, sibling_ordinal=node.sibling_ordinal)
    destination = contracts.HierarchyBasis.model_validate(destination)
    _, timeline = runtime_documents()
    common = deepcopy(timeline["actions"][0]["action"])
    for key in ("opacity", "destination", "target_ids"):
        common.pop(key)
    common.update(verb="ungroup", container_id=container, target_ids=members, easing="step",
        expected_state="grouped", post_state="ungrouped", hierarchy_policy={
            "member_root_ids": members, "source_basis": source.model_dump(mode="json"),
            "destination_basis": destination.model_dump(mode="json"),
            "source_basis_sha256": source.checksum(), "destination_basis_sha256": destination.checksum(),
            "changed_object_ids": list(changed_hierarchy_objects(before, after, objects)),
            "preserve_world_transform": True})
    action = contracts.GroupAction.model_validate(common)
    return objects, initial, resolved(action, 1000, 2000)


@pytest.mark.parametrize("container", ["actor-group", "object-group"])
def test_real_structural_boundary_protects_roles_but_not_unrelated_groups(container):
    objects, initial, action = structural_replay(container)
    before = deepcopy((objects, initial, action))
    def run():
        return replay_chronology(objects, initial.hierarchy, {obj.object_id: obj for obj in initial.objects},
            dict(initial.state_versions), (action,), (("board-main", 0, 8000),), 8000)
    if container == "actor-group":
        with pytest.raises(ValueError, match="character_assembly"):
            run()
    else:
        replay = run()
        assert replay.at(2000).hierarchy.ancestors("object-system") == ()
        assert replay.at(2000).hierarchy.ancestors("actor-head") == ("actor-group",)
    assert (objects, initial, action) == before


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("verb,target", [("move", "actor-group"), ("move", "actor-left_arm"),
    ("scale", "actor-right_arm"), ("rotate", "actor-head"), ("fade", "actor-head"), ("exit", "actor-group"),
    ("reveal", "actor-head"), ("enter", "actor-left_arm"), ("exit", "actor-right_arm")])
def test_real_root_and_part_actions_preserve_ordinary_local_state_and_world_anchors(verb, target, portrait):
    layout, timeline = runtime_documents(portrait=portrait, verb=verb, target=target)
    action = timeline["actions"][0]["action"]
    obj = next(obj for obj in layout["objects"] if obj["object_id"] == target)
    if verb in {"move", "scale", "rotate"}:
        action["destination"] = deepcopy(obj["transform"])
        if verb == "move":
            action["destination"]["position"].update(x=40., y=20.)
        elif verb == "scale":
            action["destination"].update(scale_x=1.2, scale_y=.8)
        else:
            action["destination"]["rotation_degrees"] = 20.
    elif verb == "exit":
        action["post_state"] = "removed"
    elif verb in {"reveal", "enter"}:
        obj.update(initial_state="hidden", visible=False)
        action["expected_state"] = "hidden"
        initial = next(row for row in timeline["initial_object_states"] if row["object_id"] == target)
        initial.update(state="hidden", visible=False)
    timeline["layout_sha256"] = digest(layout)
    context, replay, _ = consumer_clock(layout, timeline)
    middle, end = replay.at(500), replay.at(1000)
    versions = dict(end.state_versions)
    assert versions[target] == 2
    assert all(value == 1 for key, value in versions.items() if key != target)
    assert middle.object(target).state == ("hidden" if verb in {"reveal", "enter"} else "visible")
    current = middle.hierarchy.object_map(context.objects)
    transforms = {obj.object_id: obj.transform for obj in middle.objects}
    if verb == "move":
        anchor_id = "hand" if target == "actor-left_arm" else "head-top"
        key = target if target == "actor-left_arm" else "actor-head"
        expected = (330., 450.) if key == "actor-left_arm" else (390., 240.)
        assert world_anchor(current[key], anchor_id, current, transforms) == expected
    pixels = {at: compose_png_frame(layout, timeline, at).png for at in (0, 500, 1000)}
    assert pixels[0] != pixels[500] != pixels[1000]
    if verb == "exit" and target == "actor-group":
        assert end.object("actor-head").visible  # root action never rewrites part state
        assert not v2_state.evaluate_frame(layout, timeline, 1000).object("actor-head").visible
    assert replay.at(500) == middle


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("pose", ["neutral", "point_right", "open_hands"])
def test_frozen_shared_tree_parity_is_offline_and_random_seekable(portrait, pose, monkeypatch):
    from test_v2_character_assembly_compositor import original_pose_documents

    layout, timeline = original_pose_documents(pose, portrait=portrait)
    before = deepcopy((layout, timeline))
    expected = {at: compose_png_frame(layout, timeline, at).png for at in (0, 500, 1000)}
    typed, resolved_timeline = contracts.ExecutableLayoutV2.model_validate(layout), contracts.ResolvedVisualTimelineV2.model_validate(timeline)
    inputs = verify_split_paint_inputs(typed, {})
    registry = registry_endpoint_inputs_for_objects({obj.object_id: obj for obj in typed.objects},
        frozen_files={name: raw for name, _, raw in inputs.bundle_bytes})
    def forbidden(*args, **kwargs):
        raise AssertionError("frozen character assembly attempted live IO")
    monkeypatch.setattr(Path, "read_bytes", forbidden)
    monkeypatch.setattr(socket, "connect", forbidden)
    for at in (1000, 0, 500, 1000, 500):
        sample = v2_state._evaluate_frame_with_registry_inputs(layout, timeline, at, registry)
        frame = _compose_validated_svg_frame(typed, resolved_timeline, sample, {}, split_inputs=inputs)
        assert _rasterize_svg_frame(typed, frame, split_inputs=inputs).png == expected[at]
    assert (layout, timeline) == before


@pytest.mark.parametrize("boundary", ["sample", "paint", "at", "capture"])
def test_actual_sample_and_paint_boundaries_authenticate_current_role_order(boundary, monkeypatch):
    layout, timeline = runtime_documents()
    context, replay, camera = consumer_clock(layout, timeline)
    hierarchy = replay.at(500).hierarchy
    swapped = HierarchySnapshot(tuple(replace(node, sibling_ordinal=1 if node.object_id == "actor-head" else 0)
        if node.object_id in {"actor-head", "actor-torso"} else node for node in hierarchy.nodes))
    if boundary == "sample":
        # A genuine sampled carrier with a reconstructed hierarchy exercises
        # this later consumer independently of the scheduler's earlier guard.
        sample = replace(replay.at(500), hierarchy=swapped)
        monkeypatch.setattr(type(replay), "at", lambda self, at_ms: sample)
        with pytest.raises(ValueError, match="character_assembly") as failure:
            v2_state._sample_validated_frame(context.layout, context.timeline, replay, camera, 500)
        assert type(failure.value) is ValueError
    elif boundary != "paint":
        corrupted = replace(replay, checkpoints=tuple(replace(row, hierarchy=swapped) for row in replay.checkpoints))
        with pytest.raises(ReplayError, match="character_assembly"):
            if boundary == "at":
                corrupted.at(500)
            else:
                corrupted.before_action(timeline["actions"][0]["action"]["action_id"])
    else:
        sample = v2_state._sample_validated_frame(context.layout, context.timeline, replay, camera, 500)
        with pytest.raises(ValueError, match="character_assembly"):
            _compose_validated_svg_frame(context.layout, context.timeline, replace(sample, hierarchy=swapped), {})


@pytest.mark.parametrize("verb", ["replace", "morph"])
def test_stable_semantic_anchor_destination_may_become_visible_in_its_own_role(verb):
    layout, timeline = replacement_documents(verb, anchored=True)
    objects = {obj["object_id"]: obj for obj in layout["objects"]}
    # The hidden destination's identity and literal head anchor remain fixed.
    actor = objects["actor-group"]
    actor["character_assembly"]["semantic_anchors"][0]["object_id"] = "actor-head-next"
    timeline["layout_sha256"] = digest(layout)
    context, replay, _ = consumer_clock(layout, timeline)
    assert not replay.at(0).object("actor-head-next").visible
    assert replay.at(1000).object("actor-head-next").visible
    sampled = replay.at(500)
    current = sampled.hierarchy.object_map(context.objects)
    assert world_anchor(current["actor-head-next"], "head-top", current,
        {obj.object_id: obj.transform for obj in sampled.objects}) == (390. if verb == "morph" else 370., 230.)


@pytest.mark.parametrize("source,destination", [("actor-torso", "second-torso"),
    ("actor-group", "second-group"), ("actor-torso", "actor-group")])
def test_cross_assembly_and_actor_root_substitution_is_not_an_ordinary_part_transition(source, destination):
    layout, timeline = runtime_documents()
    layout["objects"] = [obj for obj in layout["objects"] if obj["object_id"].startswith("actor-")]
    copied = deepcopy([obj for obj in layout["objects"] if obj["object_id"].startswith("actor-")])
    for obj in copied:
        obj["object_id"] = obj["object_id"].replace("actor-", "second-")
        if obj["parent_id"]:
            obj["parent_id"] = obj["parent_id"].replace("actor-", "second-")
        if obj["object_type"] == "group":
            obj["z_index"] = 20
            obj["child_ids"] = [key.replace("actor-", "second-") for key in obj["child_ids"]]
            for field in ("roles", "semantic_anchors"):
                for row in obj["character_assembly"][field]:
                    row["object_id"] = row["object_id"].replace("actor-", "second-")
    layout["objects"].extend(copied)
    layout["boards"][0]["object_ids"] = [obj["object_id"] for obj in layout["objects"]]
    objects = {obj.object_id: obj for obj in contracts.ExecutableLayoutV2.model_validate(layout).objects}
    raw = timeline["actions"][0]["action"]
    for key in ("target_ids", "opacity", "destination"):
        raw.pop(key)
    raw.update(verb="replace", from_object_id=source, to_object_id=destination)
    with pytest.raises(ValueError, match="character_assembly.*same real role"):
        validate_character_transition(contracts.ReplaceAction.model_validate(raw), objects, HierarchySnapshot.from_objects(objects))


@pytest.mark.parametrize("portrait", [False, True])
def test_real_relationship_paint_tracks_named_leaf_anchors_through_root_motion(portrait):
    layout, timeline = runtime_documents(portrait=portrait, verb="move")
    objects = {obj["object_id"]: obj for obj in layout["objects"]}
    move = timeline["actions"][0]["action"]
    move["destination"] = deepcopy(objects["actor-group"]["transform"])
    move["destination"]["position"].update(x=40., y=20.)
    arrow_layout, _ = connector_documents()
    arrow = deepcopy(arrow_layout["objects"][-1])
    arrow.update(initial_state="visible", visible=True, source_object_id="actor-left_arm", source_anchor_id="hand",
        destination_object_id="actor-head", destination_anchor_id="head-top", z_index=11)
    arrow["geometry"]["bounds"] = {"x": 240., "y": 200., "width": 300., "height": 300.}
    layout["objects"].append(arrow)
    layout["boards"][0]["object_ids"].append(arrow["object_id"])
    timeline["initial_object_states"].append({"object_id": arrow["object_id"], "state": "visible",
                                                "visible": True, "state_version": 1})
    timeline["layout_sha256"] = digest(layout)
    before = deepcopy((layout, timeline))
    pngs = {}
    for at_ms, expected in ((0, "M 310 440 L 370 230"), (500, "M 330 450 L 390 240"),
                            (1000, "M 350 460 L 410 250")):
        root = ET.fromstring(compose_svg_frame(layout, timeline, at_ms).svg)
        node = next(node for node in root.iter() if node.attrib.get("data-object-id") == "object-arrow")
        assert next(node for node in node if node.tag.endswith("path")).attrib["d"] == expected
        pngs[at_ms] = compose_png_frame(layout, timeline, at_ms).png
    assert len(set(pngs.values())) == 3
    assert compose_png_frame(layout, timeline, 500).png == pngs[500]
    assert (layout, timeline) == before
