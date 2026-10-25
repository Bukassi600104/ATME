"""Authored illustration roles survive the actual shared hierarchy and clock."""

from copy import deepcopy
from dataclasses import replace
from importlib import import_module
from importlib.util import find_spec

import pytest
from test_v2_character_assembly_runtime import (
    replacement_documents as character_replacement,
)
from test_v2_group_annotation import consumer_clock
from test_v2_group_hierarchy import grouped_documents
from test_v2_illustration_assembly_contract import documents
from test_v2_split_identity import sample_for_layout
from test_v2_timeline_replay import resolved
from v2_fixtures import digest

from atme.render import v2_state
from atme.render.v2_hierarchy import HierarchySnapshot, changed_hierarchy_objects
from atme.render.v2_hierarchy_replay import completed_hierarchy_basis
from atme.render.v2_svg import _compose_validated_svg_frame
from atme.render.v2_timeline_replay import ReplayError, replay_chronology
from atme.render.v2_world import world_anchor
from atme.store import contracts_v2 as contracts


def current_guard():
    assert hasattr(contracts, "validate_illustration_assembly_map"), "named illustration current-map guard is missing"
    return contracts.validate_illustration_assembly_map


def transition_guard():
    name = "atme.render.v2_illustration_assembly"
    assert find_spec(name) is not None, "illustration transition ownership guard is missing"
    return import_module(name).validate_illustration_transition


def runtime_documents():
    _, layout = documents()
    _, timeline = grouped_documents()
    row = deepcopy(timeline["actions"][-1])
    common = ("action_id", "source_instruction_id", "board_id", "semantic_reason", "trigger",
              "easing", "expected_state", "post_state", "fallback", "coverage_id")
    row["action"] = {key: row["action"][key] for key in common}
    row["action"].update(verb="fade", target_ids=["illustration-group"], opacity=.5, destination=None,
                         expected_state="visible", post_state="visible", easing="linear",
                         trigger={"kind": "absolute", "at_ms": 0})
    row.update(start_ms=0, end_ms=1000)
    row["resolved_trigger"].update(source=row["action"]["trigger"], alignment_anchor_ms=0,
                                    resolved_at_ms=0, matched_text=None, matched_occurrence=None)
    timeline.update(actions=[row], resolved_assets=[], coverage=[timeline["coverage"][2]],
                    fallbacks=[timeline["fallbacks"][2]])
    timeline["initial_object_states"] = [{"object_id": obj["object_id"], "state": obj["initial_state"],
        "visible": obj["visible"], "state_version": 1} for obj in layout["objects"]]
    timeline.update(layout_sha256=digest(layout), plan_sha256=layout["plan_sha256"])
    return layout, timeline


@pytest.mark.parametrize("family", ["icon", "pictogram", "device", "document", "terminal"])
def test_named_current_map_guard_checks_authored_roles_without_mutation(family):
    _, raw = documents(family)
    objects = {obj.object_id: obj for obj in contracts.ExecutableLayoutV2.model_validate(raw).objects}
    before = deepcopy(objects)
    current_guard()(objects)
    assert objects == before


@pytest.mark.parametrize("fault", ["extra_child", "anchor", "cross_role_anchor", "role_order", "missing",
                                   "identity", "invalid_kind", "duplicate_role", "invalid_state_id"])
def test_current_map_rejects_actual_graph_anchor_or_binding_invalidation(fault):
    _, raw = documents()
    objects = {obj.object_id: obj for obj in contracts.ExecutableLayoutV2.model_validate(raw).objects}
    binding = objects["illustration-group"].illustration_assembly
    if fault == "extra_child":
        objects["object-system"] = objects["object-system"].model_copy(update={"parent_id": "illustration-group"})
    elif fault == "anchor":
        objects["device-shell"] = objects["device-shell"].model_copy(update={"anchors": []})
    elif fault == "cross_role_anchor":
        binding.semantic_anchors[0].object_id = "device-label"
    elif fault == "role_order":
        objects["illustration-group"].child_ids.reverse()
    elif fault == "missing":
        objects.pop("device-label")
    elif fault == "identity":
        objects["device-shell"] = objects["device-shell"].model_copy(update={"object_id": "different-shell"})
    elif fault == "invalid_kind":
        binding.roles[0].kind = "invented"
    elif fault == "duplicate_role":
        binding.roles[1].role_id = binding.roles[0].role_id
    else:
        binding.content_state_id = "not a stable ID"
    guard = current_guard()
    with pytest.raises(ValueError, match="illustration_assembly"):
        guard(objects)


@pytest.mark.parametrize("field", ["roles", "semantic_anchors"])
@pytest.mark.parametrize("container", ["null", "tuple"])
def test_current_binding_inventory_retains_its_strict_list_contract(field, container):
    _, raw = documents()
    objects = {obj.object_id: obj for obj in contracts.ExecutableLayoutV2.model_validate(raw).objects}
    binding = objects["illustration-group"].illustration_assembly
    setattr(binding, field, None if container == "null" else tuple(getattr(binding, field)))
    with pytest.raises(ValueError, match="illustration_assembly"):
        current_guard()(objects)


def structural_replay(container):
    layout, timeline = runtime_documents()
    for obj in layout["objects"]:
        obj.update(initial_state="visible", visible=True)
    next(obj for obj in layout["objects"] if obj["object_id"] == container)["initial_state"] = "grouped"
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
    return objects, initial, resolved(contracts.GroupAction.model_validate(common), 1000, 2000)


@pytest.mark.parametrize("container", ["illustration-group", "object-group"])
def test_real_structural_replay_protects_roles_but_keeps_unrelated_group_actions(container):
    objects, initial, action = structural_replay(container)
    before = deepcopy((objects, initial, action))
    def run():
        return replay_chronology(objects, initial.hierarchy, {obj.object_id: obj for obj in initial.objects},
            dict(initial.state_versions), (action,), (("board-main", 0, 8000),), 8000)
    if container == "illustration-group":
        with pytest.raises(ReplayError, match="illustration_assembly"):
            run()
    else:
        replay = run()
        assert replay.at(2000).hierarchy.ancestors("object-system") == ()
        assert replay.at(2000).hierarchy.ancestors("device-shell") == ("illustration-group",)
    assert (objects, initial, action) == before


@pytest.mark.parametrize("boundary", ["sample", "paint", "at", "before_action"])
def test_real_sample_replay_and_shared_paint_boundaries_authenticate_current_roles(boundary, monkeypatch):
    layout, timeline = runtime_documents()
    context, replay, camera = consumer_clock(layout, timeline)
    hierarchy = replay.at(500).hierarchy
    swapped = HierarchySnapshot(tuple(replace(node, sibling_ordinal=1 if node.object_id == "device-shell" else 0)
        if node.object_id in {"device-shell", "device-label"} else node for node in hierarchy.nodes))
    if boundary == "sample":
        sample = replace(replay.at(500), hierarchy=swapped)
        monkeypatch.setattr(type(replay), "at", lambda self, at_ms: sample)
        with pytest.raises(ValueError, match="illustration_assembly") as failure:
            v2_state._sample_validated_frame(context.layout, context.timeline, replay, camera, 500)
        assert type(failure.value) is ValueError
    elif boundary == "paint":
        sample = v2_state._sample_validated_frame(context.layout, context.timeline, replay, camera, 500)
        with pytest.raises(ValueError, match="illustration_assembly"):
            _compose_validated_svg_frame(context.layout, context.timeline, replace(sample, hierarchy=swapped), {})
    else:
        corrupted = replace(replay, checkpoints=tuple(replace(row, hierarchy=swapped) for row in replay.checkpoints))
        with pytest.raises(ReplayError, match="illustration_assembly"):
            if boundary == "at":
                corrupted.at(500)
            else:
                corrupted.before_action(timeline["actions"][0]["action"]["action_id"])


def replacement_documents(*, anchored=False, cross_role=False, external=False):
    layout, _ = runtime_documents()
    objects = {obj["object_id"]: obj for obj in layout["objects"]}
    actor = objects["illustration-group"]
    source = objects["device-shell"]
    role = deepcopy(actor)
    role.pop("illustration_assembly")
    role.update(object_id="shell-role", parent_id=actor["object_id"], child_ids=[source["object_id"]], z_index=0)
    source.update(parent_id=role["object_id"])
    actor["child_ids"][0] = role["object_id"]
    actor["illustration_assembly"]["roles"][0]["object_id"] = role["object_id"]
    if not anchored:
        actor["illustration_assembly"]["semantic_anchors"] = []
    destination = deepcopy(source)
    destination.update(object_id="device-shell-next", initial_state="hidden", visible=False)
    if cross_role:
        label = objects["device-label"]
        other = deepcopy(role)
        other.update(object_id="caption-role", z_index=1, child_ids=[label["object_id"], destination["object_id"]])
        label.update(parent_id=other["object_id"], z_index=0)
        destination.update(parent_id=other["object_id"], z_index=1)
        actor["child_ids"][1] = other["object_id"]
        actor["illustration_assembly"]["roles"][1]["object_id"] = other["object_id"]
        layout["objects"].append(other)
    elif external:
        destination["parent_id"] = None
    else:
        role["child_ids"].append(destination["object_id"])
    layout["objects"].extend([role, destination])
    layout["boards"][0].update(object_ids=[obj["object_id"] for obj in layout["objects"]], density_limit=12)
    _, previous = character_replacement("replace")
    action = deepcopy(previous["actions"][0]["action"])
    action.update(from_object_id=source["object_id"], to_object_id=destination["object_id"])
    return layout, contracts.ReplaceAction.model_validate(action)


@pytest.mark.parametrize("fault", ["within-role", "anchored-source", "cross-role", "external", "root"])
def test_transition_ownership_uses_explicit_real_role_ids_and_stable_anchor_leaves(fault):
    layout, action = replacement_documents(anchored=fault == "anchored-source", cross_role=fault == "cross-role",
                                           external=fault == "external")
    if fault == "root":
        action = action.model_copy(update={"from_object_id": "illustration-group"})
    typed = contracts.ExecutableLayoutV2.model_validate(layout)
    objects = {obj.object_id: obj for obj in typed.objects}
    initial = sample_for_layout(typed)
    before = deepcopy((objects, initial, action))
    guard = transition_guard()
    if fault == "within-role":
        guard(action, objects, initial.hierarchy)
    else:
        with pytest.raises(ValueError, match="illustration_assembly"):
            guard(action, objects, initial.hierarchy)
    assert (objects, initial, action) == before


def replacement_timeline(verb, **kwargs):
    layout, action = replacement_documents(**kwargs)
    raw = action.model_dump(mode="json")
    raw["verb"] = verb
    if verb == "morph":
        raw["morph_policy"] = {"mapping": "canonical_outline", "paint": "shared_style", "transforms": "interpolate_all"}
        next(obj for obj in layout["objects"] if obj["object_id"] == "device-shell-next")["geometry"]["bounds"]["x"] += 20.
    _, timeline = runtime_documents()
    timeline["actions"] = [resolved(raw, 0, 1000).model_dump(mode="json")]
    timeline["initial_object_states"] = [{"object_id": obj["object_id"], "state": obj["initial_state"],
        "visible": obj["visible"], "state_version": 1} for obj in layout["objects"]]
    timeline["layout_sha256"] = digest(layout)
    return layout, timeline


@pytest.mark.parametrize("verb", ["replace", "morph"])
def test_real_same_role_replay_keeps_exact_state_versions_and_shuffled_seek(verb):
    layout, timeline = replacement_timeline(verb)
    before = deepcopy((layout, timeline))
    context, replay, _ = consumer_clock(layout, timeline)
    middle = v2_state.evaluate_frame(layout, timeline, 500)
    end = v2_state.evaluate_frame(layout, timeline, 1000)
    assert middle.object("device-shell").visible
    assert end.object("device-shell").state == "removed"
    assert end.object("device-shell-next").visible
    assert dict(replay.at(500).state_versions) == {key: 1 for key in context.objects}
    assert dict(replay.at(1000).state_versions) == {key: 2 if key in {"device-shell", "device-shell-next"} else 1
                                                 for key in context.objects}
    for at_ms in (1000, 0, 999, 500):
        v2_state.evaluate_frame(layout, timeline, at_ms)
    assert v2_state.evaluate_frame(layout, timeline, 500) == middle
    assert (layout, timeline) == before


@pytest.mark.parametrize("verb", ["replace", "morph"])
@pytest.mark.parametrize("fault", ["anchored", "cross_role", "external"])
def test_actual_replay_rejects_semantic_anchor_source_or_foreign_role_transition(verb, fault):
    layout, timeline = replacement_timeline(verb, **{fault: True})
    typed = contracts.ExecutableLayoutV2.model_validate(layout)
    clock = contracts.ResolvedVisualTimelineV2.model_validate(timeline)
    initial = sample_for_layout(typed)
    objects = {obj.object_id: obj for obj in typed.objects}
    # Exercise the chronological boundary itself. Public static ownership
    # checks may correctly reject a foreign-parent pair even earlier.
    with pytest.raises(ReplayError, match="illustration_assembly"):
        replay_chronology(objects, initial.hierarchy, {obj.object_id: obj for obj in initial.objects},
            dict(initial.state_versions), tuple(clock.actions), (("board-main", 0, 8000),), 8000)


@pytest.mark.parametrize("verb", ["replace", "morph"])
def test_fixed_semantic_anchor_destination_may_become_visible_inside_its_role(verb):
    layout, timeline = replacement_timeline(verb, anchored=True)
    group = next(obj for obj in layout["objects"] if obj["object_id"] == "illustration-group")
    group["illustration_assembly"]["semantic_anchors"][0]["object_id"] = "device-shell-next"
    timeline["layout_sha256"] = digest(layout)
    context, replay, _ = consumer_clock(layout, timeline)
    assert not replay.at(0).object("device-shell-next").visible
    assert replay.at(1000).object("device-shell-next").visible
    sample = replay.at(500)
    current = sample.hierarchy.object_map(context.objects)
    assert world_anchor(current["device-shell-next"], "screen-center", current,
        {obj.object_id: obj.transform for obj in sample.objects}) == (415. if verb == "morph" else 395., 320.)


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("verb,target", [("move", "illustration-group"), ("move", "device-shell"),
    ("scale", "device-shell"), ("rotate", "device-shell"), ("fade", "device-label"),
    ("reveal", "device-shell"), ("enter", "device-shell"), ("exit", "illustration-group")])
def test_ordinary_root_and_part_actions_keep_local_versions_and_real_world_anchors(portrait, verb, target):
    layout, timeline = runtime_documents()
    objects = {obj["object_id"]: obj for obj in layout["objects"]}
    action = timeline["actions"][0]["action"]
    action.update(verb=verb, target_ids=[target])
    action.pop("opacity")
    action.pop("destination")
    if verb in {"move", "scale", "rotate"}:
        action["destination"] = deepcopy(objects[target]["transform"])
        if verb == "move":
            action["destination"]["position"].update(x=40., y=20.)
        elif verb == "scale":
            action["destination"].update(scale_x=1.2, scale_y=.8)
        else:
            action["destination"]["rotation_degrees"] = 20.
    elif verb == "fade":
        action.update(opacity=.5, destination=None)
    elif verb == "exit":
        action["post_state"] = "removed"
    else:
        objects[target].update(initial_state="hidden", visible=False)
        action["expected_state"] = "hidden"
        next(row for row in timeline["initial_object_states"] if row["object_id"] == target).update(state="hidden", visible=False)
    if portrait:
        layout["output_profile"] = {"profile_id": "SHORT_FORM_9_16", "width": 720, "height": 1280, "fps": 30}
        layout["canvas"].update(width=720, height=1280)
        timeline["output_profile"] = deepcopy(layout["output_profile"])
    timeline["layout_sha256"] = digest(layout)
    context, replay, _ = consumer_clock(layout, timeline)
    middle, end = replay.at(500), replay.at(1000)
    assert dict(end.state_versions) == {key: 2 if key == target else 1 for key in context.objects}
    if verb == "move":
        current = middle.hierarchy.object_map(context.objects)
        assert world_anchor(current["device-shell"], "screen-center", current,
            {obj.object_id: obj.transform for obj in middle.objects}) == (415., 330.)
    if verb == "exit":
        assert end.object("device-shell").visible
        assert not v2_state.evaluate_frame(layout, timeline, 1000).object("device-shell").visible
    assert replay.at(500) == middle
