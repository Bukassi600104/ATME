"""Immutable initial definitions do not reset current structural board history."""
import json
from copy import deepcopy
from dataclasses import replace

import pytest
from atme.render import v2_state
from atme.render.v2_hierarchy import HierarchySnapshot, changed_hierarchy_objects
from atme.render.v2_hierarchy_replay import completed_hierarchy_basis
from atme.render.v2_split_identity import split_content_receipts
from atme.render.v2_split_paint import verify_split_paint_inputs
from atme.render.v2_svg import _compose_validated_svg_frame, _rasterize_svg_frame
from atme.store import contracts_v2 as contracts
from test_v2_composition_attachment import composition_project_documents
from test_v2_composition_contract import composition_definition
from test_v2_group_annotation import consumer_clock
from test_v2_hierarchy_replay import reverse
from test_v2_return_board import return_documents
from test_v2_return_hierarchy import rehash_receipt
from test_v2_timeline_replay import resolved
from v2_fixtures import digest, resolved_timeline_v2


def structural_return_documents(*, portrait=False, regroup=False):
    definition = composition_definition()
    root = definition["objects"][0]
    root["geometry"]["corner_radius"] = None
    root["initial_state"] = "grouped"
    root["transform"]["position"] = {"x": -20.0 if portrait else 100.0, "y": 150.0 if portrait else 0.0}
    plan, layout = composition_project_documents(definition=definition)
    root, mark, label = layout["objects"]
    layout["boards"][0]["expected_prior_state"] = "system_established"
    between = deepcopy(mark)
    between.update(object_id="between-boards", board_id="board-between", beat_id="beat-between",
                   parent_id=None, initial_state="visible", visible=True, coverage_ids=["coverage-between"])
    between["geometry"]["bounds"].update(x=150.0, y=180.0, width=220.0, height=220.0)
    layout["objects"].append(between)
    board = deepcopy(layout["boards"][0])
    board.update(board_id="board-between", object_ids=[between["object_id"]], density_limit=1,
                 persistence_policy="single_beat", activation_policy="once", expected_prior_state=None)
    layout["boards"].append(board)
    layout["activations"] = [
        {**layout["activations"][0], "end_ms": 6500},
        {"activation_id": "activation-between", "board_id": "board-between", "start_ms": 6500,
         "end_ms": 7000, "reason": "Inspect the explicitly authored second board"},
        {**layout["activations"][0], "activation_id": "activation-return", "start_ms": 7000},
    ]
    profile = ({"profile_id": "SHORT_FORM_9_16", "width": 720, "height": 1280, "fps": 30}
               if portrait else {"profile_id": "LONG_FORM_16_9", "width": 1280, "height": 720, "fps": 30})
    plan["output_profile"] = deepcopy(profile)
    layout.update(output_profile=deepcopy(profile), plan_sha256=digest(plan))
    layout["canvas"].update(width=profile["width"], height=profile["height"])
    timeline = resolved_timeline_v2(plan, layout)
    timeline.update(output_profile=deepcopy(profile), resolved_assets=[], beat_anchors=timeline["beat_anchors"][:1])
    timeline["initial_object_states"] = [{"object_id": obj["object_id"], "state": obj["initial_state"],
        "visible": obj["visible"], "state_version": 1} for obj in layout["objects"]]
    objects = {obj.object_id: obj for obj in contracts.ExecutableLayoutV2.model_validate(layout).objects}
    before = HierarchySnapshot.from_objects(objects)
    initial = contracts.HierarchyBasis(placements=[{"object_id": node.object_id, "board_id": node.board_id,
        "parent_id": node.parent_id, "sibling_ordinal": node.sibling_ordinal,
        "local_transform": objects[node.object_id].transform} for node in before.nodes])
    timeline["initial_hierarchy_basis"] = initial.model_dump(mode="json")
    timeline["initial_hierarchy_basis_sha256"] = initial.checksum()
    timeline["layout_sha256"] = digest(layout)
    _, prefix, _camera = consumer_clock(layout, timeline)
    sample = prefix.at(3000)
    source = completed_hierarchy_basis(sample.hierarchy, {obj.object_id: obj for obj in sample.objects})
    members = [mark["object_id"], label["object_id"]]
    after = HierarchySnapshot(tuple(replace(node, parent_id=None, sibling_ordinal=members.index(node.object_id) + 1)
        if node.object_id in members else node for node in before.nodes))
    destination = source.model_dump(mode="json")
    for row in destination["placements"]:
        if row["object_id"] in members:
            row.update(parent_id=None, sibling_ordinal=members.index(row["object_id"]) + 1)
            # Explicit authored translation-only world preservation; no inverse
            # or decomposed transform is inferred by the production engine.
            row["local_transform"]["position"]["x"] += root["transform"]["position"]["x"]
            row["local_transform"]["position"]["y"] += root["transform"]["position"]["y"]
    destination = contracts.HierarchyBasis.model_validate(destination)
    action = deepcopy(plan["actions"][0])
    action.pop("annotation")
    action.update(action_id="ungroup-instance", verb="ungroup", container_id=root["object_id"], target_ids=members,
                  expected_state="grouped", post_state="ungrouped", easing="step", hierarchy_policy={
                      "member_root_ids": members, "source_basis": source.model_dump(mode="json"),
                      "destination_basis": destination.model_dump(mode="json"),
                      "source_basis_sha256": source.checksum(), "destination_basis_sha256": destination.checksum(),
                      "changed_object_ids": list(changed_hierarchy_objects(before, after, objects)),
                      "preserve_world_transform": True})
    action = contracts.GroupAction.model_validate(action)
    timeline["actions"].append(resolved(action, 4000, 5000).model_dump(mode="json"))
    if regroup:
        restored = reverse(action).model_copy(update={"action_id": "regroup-instance"})
        timeline["actions"].append(resolved(restored, 5100, 5400).model_dump(mode="json"))
    moving = deepcopy(plan["actions"][0])
    moving.pop("annotation")
    moving.update(action_id="between-move", verb="move", target_ids=[between["object_id"]], board_id="board-between",
                  source_instruction_id="instruction-between", coverage_id="coverage-between",
                  expected_state="visible", post_state="visible", easing="linear", opacity=None,
                  destination=deepcopy(between["transform"]))
    moving["destination"]["position"]["x"] = 100.0
    timeline["actions"].append(resolved(moving, 6500, 6800).model_dump(mode="json"))
    timeline["fallbacks"][0]["affected_ids"].append("instruction-between")
    timeline["coverage"][0]["action_ids"].extend(item["action"]["action_id"] for item in timeline["actions"]
        if item["action"]["verb"] in {"group", "ungroup"})
    timeline["coverage"].append({"coverage_id": "coverage-between", "instruction_id": "instruction-between",
        "status": "executed", "action_ids": ["between-move"], "fallback_id": None})
    timeline["beat_anchors"].append({"beat_id": "beat-between", "start_ms": 6500})
    _, prefix, _camera = consumer_clock(layout, timeline)
    retained = prefix.at(7000)
    owned = {obj.object_id: obj for obj in retained.objects if obj.board_id == "board-main"}
    basis = completed_hierarchy_basis(HierarchySnapshot(tuple(node for node in retained.hierarchy.nodes
        if node.board_id == "board-main")), owned)
    returned = deepcopy(return_documents()[1]["actions"][2])
    returned.update(start_ms=7000, end_ms=7001)
    returned["action"].update(source_board_id="board-between", source_activation_id="activation-between",
        source_instruction_id="instruction-1", coverage_id="coverage-1",
        fallback={"fallback_id": "fallback-1", "on_failure": "block"},
        trigger={"kind": "absolute", "at_ms": 7000},
        expected_object_states={key: obj.state for key, obj in owned.items()},
        expected_object_state_versions={key: dict(retained.state_versions)[key] for key in owned})
    returned["resolved_trigger"].update(source=returned["action"]["trigger"], alignment_anchor_ms=7000,
                                         resolved_at_ms=7000)
    returned["return_hierarchy_receipt"] = {"action_id": "return-1", "destination_board_id": "board-main",
        "destination_activation_id": "activation-return", "hierarchy_basis": basis.model_dump(mode="json"),
        "hierarchy_basis_sha256": basis.checksum()}
    timeline["actions"].append(returned)
    timeline["coverage"][0]["action_ids"].append("return-1")
    return layout, timeline


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("regroup", [False, True])
def test_current_composition_membership_and_a_b_a_receipt_do_not_reexpand_initial_definition(portrait, regroup):
    layout, timeline = structural_return_documents(portrait=portrait, regroup=regroup)
    original = deepcopy((layout, timeline))
    context, replay, camera = consumer_clock(layout, timeline)
    inputs = verify_split_paint_inputs(context.layout, {})
    owner, mark, _label = layout["objects"][:3]
    before = replay.at(3999)
    flattened = replay.at(5000)
    returned = replay.at(7001)
    assert before.hierarchy.ancestors(mark["object_id"]) == (owner["object_id"],)
    assert flattened.hierarchy.ancestors(mark["object_id"]) == ()
    assert returned.hierarchy.children("board-main", owner["object_id"]) == (tuple(owner["child_ids"]) if regroup else ())
    current = returned.hierarchy.object_map({obj.object_id: obj for obj in context.layout.objects})
    assert current[owner["object_id"]].composition_binding.model_dump(mode="json") == owner["composition_binding"]
    # Content identity authenticates immutable initial binding AND actual current
    # children, not a stale expansion substituted for the sampled topology.
    content = {row.object_id: row for row in split_content_receipts(context.layout, returned, {})}
    payload = json.loads(content[owner["object_id"]].canonical_json)
    assert payload["composition_binding"] == owner["composition_binding"]
    current_children = returned.hierarchy.children("board-main", owner["object_id"])
    assert payload["children"] == [{"object_id": key, "content_sha256": content[key].content_sha256}
                                   for key in sorted(current_children)]
    assert dict(returned.state_versions)[mark["object_id"]] == 3 + int(regroup)

    def paint(at):
        sample = v2_state._sample_validated_frame(context.layout, context.timeline, replay, camera, at)
        svg = _compose_validated_svg_frame(context.layout, context.timeline, sample, {}, split_inputs=inputs)
        return _rasterize_svg_frame(context.layout, svg, split_inputs=inputs).png

    frames = {at: paint(at) for at in (3999, 5000, 6499, 6750, 7001)}
    assert frames[3999] == frames[5000] == frames[6499] == frames[7001]
    assert frames[6750] != frames[7001]
    for at in (7001, 5000, 6750, 3999, 6499, 7001):
        assert paint(at) == frames[at]
    assert (layout, timeline) == original


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("fault", ["initial_topology", "version"])
def test_false_but_coherently_rehashed_composition_return_history_rejects(portrait, fault):
    layout, timeline = structural_return_documents(portrait=portrait)
    returned = timeline["actions"][-1]
    if fault == "initial_topology":
        # A coherent old initial topology/pose, not merely a damaged packet.
        returned["return_hierarchy_receipt"]["hierarchy_basis"]["placements"] = [deepcopy(row)
            for row in timeline["initial_hierarchy_basis"]["placements"] if row["board_id"] == "board-main"]
        rehash_receipt(returned["return_hierarchy_receipt"])
    else:
        returned["action"]["expected_object_state_versions"][layout["objects"][1]["object_id"]] += 1
    with pytest.raises(ValueError):
        consumer_clock(layout, timeline)
