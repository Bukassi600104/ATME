"""Resolved return receipts bind retained hierarchy without resetting a board."""

from copy import deepcopy

import pytest
from test_v2_return_board import return_documents
from v2_fixtures import digest

from atme.render.v2_hierarchy_replay import completed_hierarchy_basis
from atme.render.v2_state import V2FrameError, evaluate_frame
from atme.store.contracts_v2 import HierarchyBasis, ResolvedVisualTimelineV2


def private_clock(layout, timeline):
    """Exercise real preflight/chronology consumers, not the closed public gate."""
    from atme.render import v2_state
    from atme.render.v2_hierarchy import HierarchySnapshot
    from atme.render.v2_timeline_replay import replay_chronology
    from atme.store.contracts_v2 import ExecutableLayoutV2

    parsed_layout = ExecutableLayoutV2.model_validate(layout)
    parsed_timeline = ResolvedVisualTimelineV2.model_validate(timeline)
    hierarchy = HierarchySnapshot.from_objects({obj.object_id: obj for obj in parsed_layout.objects})
    context = v2_state._validate_pair_static(parsed_layout, parsed_timeline, digest(layout), hierarchy)
    replay = replay_chronology(
        context.objects, hierarchy, {obj.object_id: obj for obj in context.frames},
        {key: state.state_version for key, state in context.initial.items()},
        tuple(parsed_timeline.actions),
        tuple((a.board_id, a.start_ms, a.end_ms) for a in parsed_layout.activations),
        parsed_timeline.duration_ms,
    )
    return context, replay


def group_return_documents(*, regroup=False):
    from test_v2_hierarchy_replay import prepared, reverse
    from test_v2_hierarchy_snapshot import basis
    from test_v2_timeline_replay import resolved

    from atme.render.v2_hierarchy import HierarchySnapshot

    layout, timeline, _, _ = basis()
    action, _, _, _, _ = prepared()
    layout["objects"][3]["initial_state"] = "grouped"
    timeline["initial_object_states"][3]["state"] = "grouped"
    layout["boards"][0]["expected_prior_state"] = "system_established"
    layout["activations"][0]["end_ms"] = 6500
    interlude = deepcopy(layout["objects"][2])
    interlude.update(object_id="object-interlude", board_id="board-interlude",
                     initial_state="visible", visible=True)
    layout["objects"].append(interlude)
    board = deepcopy(layout["boards"][0])
    board.update(board_id="board-interlude", object_ids=["object-interlude"],
                 density_limit=1, persistence_policy="single_beat", activation_policy="once",
                 expected_prior_state=None)
    layout["boards"].append(board)
    layout["activations"].extend([
        {"activation_id": "activation-interlude", "board_id": "board-interlude",
         "start_ms": 6500, "end_ms": 7000, "reason": "Inspect another explanation"},
        {"activation_id": "activation-return", "board_id": "board-main",
         "start_ms": 7000, "end_ms": 10000, "reason": "Return to developed work"},
    ])
    timeline["initial_object_states"].append({"object_id": "object-interlude", "state": "visible",
                                              "visible": True, "state_version": 1})
    from test_v2_hierarchy_contract import rehash

    from atme.store.contracts_v2 import GroupAction

    action_doc = action.model_dump(mode="json")
    for side in ("source", "destination"):
        action_doc["hierarchy_policy"][f"{side}_basis"]["placements"].append({
            "object_id": "object-interlude", "board_id": "board-interlude", "parent_id": None,
            "sibling_ordinal": 0, "local_transform": deepcopy(interlude["transform"]),
        })
        action_doc["hierarchy_policy"][f"{side}_basis"]["placements"].sort(key=lambda p: p["object_id"])
    rehash(action_doc)
    action = GroupAction.model_validate(action_doc)
    steps = [resolved(action.model_copy(update={"action_id": "ungroup"}), 5000, 6000)]
    if regroup:
        steps.append(resolved(reverse(action).model_copy(update={"action_id": "regroup"}), 6100, 6400))
    timeline["actions"].extend(item.model_dump(mode="json") for item in steps)
    timeline["coverage"][2]["action_ids"].extend(item.action.action_id for item in steps)
    from atme.store.contracts_v2 import ExecutableLayoutV2

    objects = {obj.object_id: obj for obj in ExecutableLayoutV2.model_validate(layout).objects}
    hierarchy = HierarchySnapshot.from_objects(objects)
    initial_basis = HierarchyBasis(placements=[{
        "object_id": node.object_id, "board_id": node.board_id, "parent_id": node.parent_id,
        "sibling_ordinal": node.sibling_ordinal, "local_transform": objects[node.object_id].transform,
    } for node in hierarchy.nodes])
    timeline["initial_hierarchy_basis"] = initial_basis.model_dump(mode="json")
    timeline["initial_hierarchy_basis_sha256"] = initial_basis.checksum()
    timeline["layout_sha256"] = digest(layout)
    _, prefix = private_clock(layout, timeline)
    sample = prefix.at(7000)
    owned = {obj.object_id: obj for obj in sample.objects if obj.board_id == "board-main"}
    retained = completed_hierarchy_basis(
        HierarchySnapshot(tuple(node for node in sample.hierarchy.nodes if node.board_id == "board-main")), owned)
    _, return_timeline = return_documents()
    returned = deepcopy(return_timeline["actions"][2])
    returned.update(start_ms=7000, end_ms=7001)
    returned["resolved_trigger"].update(source={"kind": "absolute", "at_ms": 7000},
                                         alignment_anchor_ms=7000, resolved_at_ms=7000)
    returned["action"].update(trigger={"kind": "absolute", "at_ms": 7000},
                               source_board_id="board-interlude", source_activation_id="activation-interlude",
                               expected_object_states={key: obj.state for key, obj in owned.items()},
                               expected_object_state_versions={key: dict(sample.state_versions)[key] for key in owned})
    returned["return_hierarchy_receipt"] = {
        "action_id": "return-1", "destination_board_id": "board-main",
        "destination_activation_id": "activation-return",
        "hierarchy_basis": retained.model_dump(mode="json"), "hierarchy_basis_sha256": retained.checksum(),
    }
    timeline["actions"].append(returned)
    timeline["coverage"][2]["action_ids"].append("return-1")
    return layout, timeline


def return_receipt_documents():
    layout, timeline = return_documents()
    timeline = ResolvedVisualTimelineV2.model_validate(timeline).model_dump(mode="json")
    before = evaluate_frame(layout, timeline, 3499)
    basis = completed_hierarchy_basis(before.hierarchy, {obj.object_id: obj for obj in before.objects})
    returned = timeline["actions"][2]
    returned["return_hierarchy_receipt"] = {
        "action_id": returned["action"]["action_id"],
        "destination_board_id": "board-main",
        "destination_activation_id": "activation-return",
        "hierarchy_basis": basis.model_dump(mode="json"),
        "hierarchy_basis_sha256": basis.checksum(),
    }
    return layout, timeline


def rehash_receipt(receipt):
    receipt["hierarchy_basis_sha256"] = HierarchyBasis.model_validate(receipt["hierarchy_basis"]).checksum()


def test_old_omitted_receipt_keeps_exact_document_and_hash():
    _, timeline = return_documents()
    parsed = ResolvedVisualTimelineV2.model_validate(timeline)
    assert "return_hierarchy_receipt" not in parsed.model_dump(mode="json")["actions"][2]
    assert digest(parsed.model_dump(mode="json")) == (
        "210edeae48762cae41594b7801c8f88701e2c9ec7020ff1e5f2ad451aeece244")


def test_return_receipt_roundtrips_and_preserves_retained_pose_on_random_seeks():
    layout, timeline = return_receipt_documents()
    original = deepcopy((layout, timeline))
    parsed = ResolvedVisualTimelineV2.model_validate(timeline)
    assert parsed.model_dump(mode="json") == timeline
    before = evaluate_frame(layout, timeline, 3499)
    after = evaluate_frame(layout, timeline, 5000)
    assert before.hierarchy == after.hierarchy
    assert [obj.transform for obj in before.objects] == [obj.transform for obj in after.objects]
    evaluate_frame(layout, timeline, 7999)
    assert evaluate_frame(layout, timeline, 5000) == after
    assert (layout, timeline) == original


@pytest.mark.parametrize("field,value", [
    ("action_id", "not-return"),
    ("destination_board_id", "wrong-board"),
    ("destination_activation_id", "wrong-activation"),
    ("hierarchy_basis_sha256", "a" * 64),
])
def test_return_receipt_rejects_identity_and_hash_rebinding(field, value):
    _, timeline = return_receipt_documents()
    timeline["actions"][2]["return_hierarchy_receipt"][field] = value
    with pytest.raises(ValueError):
        ResolvedVisualTimelineV2.model_validate(timeline)


def test_receipt_is_not_permitted_on_an_ordinary_resolved_action():
    _, timeline = return_receipt_documents()
    receipt = timeline["actions"][2].pop("return_hierarchy_receipt")
    timeline["actions"][0]["return_hierarchy_receipt"] = receipt
    with pytest.raises(ValueError, match="only return_board"):
        ResolvedVisualTimelineV2.model_validate(timeline)


@pytest.mark.parametrize("kind", ["position", "scale", "rotation", "origin", "order", "parent"])
def test_well_formed_stale_hierarchy_receipt_cannot_reset_retained_work(kind):
    layout, timeline = return_receipt_documents()
    receipt = timeline["actions"][2]["return_hierarchy_receipt"]
    placements = receipt["hierarchy_basis"]["placements"]
    placement = next(item for item in placements if item["object_id"] == "object-system")
    if kind == "position":
        placement["local_transform"]["position"]["x"] += 12
    elif kind == "scale":
        placement["local_transform"]["scale_x"] *= 1.2
    elif kind == "rotation":
        placement["local_transform"]["rotation_degrees"] += 5
    elif kind == "origin":
        placement["local_transform"]["origin"]["x"] += 2
    elif kind == "order":
        other = next(item for item in placements if item["object_id"] == "object-label")
        placement["sibling_ordinal"], other["sibling_ordinal"] = (
            other["sibling_ordinal"], placement["sibling_ordinal"])
    else:
        placement["parent_id"] = "object-label"
        placement["sibling_ordinal"] = 0
        roots = sorted((item for item in placements if item["parent_id"] is None),
                       key=lambda item: item["sibling_ordinal"])
        for ordinal, root in enumerate(roots):
            root["sibling_ordinal"] = ordinal
    rehash_receipt(receipt)
    # A self-consistent contract is still not proof of the actual retained pose.
    ResolvedVisualTimelineV2.model_validate(timeline)
    with pytest.raises(V2FrameError, match="retained board hierarchy"):
        evaluate_frame(layout, timeline, 5000)


@pytest.mark.parametrize("regroup", [False, True])
def test_real_a_b_a_return_retains_completed_group_history_and_versions(regroup):
    from atme.render import v2_state
    from atme.render.v2_camera import camera_segments

    layout, timeline = group_return_documents(regroup=regroup)
    original = deepcopy((layout, timeline))
    context, replay = private_clock(layout, timeline)
    plan = camera_segments(context.layout, context.timeline, replay)
    v2_state._validate_pair_temporal(context, replay, plan)
    prior, returned = replay.at(6499), replay.at(7000)
    assert returned.hierarchy == prior.hierarchy
    assert returned.objects == prior.objects
    assert returned.state_versions == prior.state_versions
    assert returned.hierarchy.ancestors("object-system") == (("object-group",) if regroup else ())
    assert dict(returned.state_versions)["object-group"] == 1 + (2 if regroup else 1)
    assert dict(returned.state_versions)["object-interlude"] == 1
    for at in (9999, 6000, 6999, 7001, 6400, 7000, 5000):
        replay.at(at)
    assert replay.at(7000) == returned
    assert replay.before_action("return-1").hierarchy == returned.hierarchy
    assert (layout, timeline) == original
    with pytest.raises(v2_state.UnsupportedVisualAction, match="no frame implementation"):
        evaluate_frame(layout, timeline, 7000)


def test_group_return_without_receipt_stays_closed_in_shared_kernel():
    from atme.render.v2_timeline_replay import ReplayError

    layout, timeline = group_return_documents()
    timeline["actions"][-1].pop("return_hierarchy_receipt")
    with pytest.raises(ReplayError, match="exact retained-board receipt"):
        private_clock(layout, timeline)


@pytest.mark.parametrize("kind", ["state", "version", "parent", "order", "transform"])
def test_group_return_rejects_well_formed_stale_completed_history(kind):
    from atme.render.v2_timeline_replay import ReplayError

    layout, timeline = group_return_documents()
    returned = timeline["actions"][-1]
    if kind == "state":
        returned["action"]["expected_object_states"]["object-group"] = "grouped"
    elif kind == "version":
        returned["action"]["expected_object_state_versions"]["object-group"] += 1
    else:
        receipt = returned["return_hierarchy_receipt"]
        placements = receipt["hierarchy_basis"]["placements"]
        item = next(p for p in placements if p["object_id"] == "object-system")
        if kind == "transform":
            item["local_transform"]["position"]["x"] += 1
        elif kind == "order":
            other = next(p for p in placements if p["object_id"] == "object-label")
            item["sibling_ordinal"], other["sibling_ordinal"] = other["sibling_ordinal"], item["sibling_ordinal"]
        else:
            item.update(parent_id="object-group", sibling_ordinal=0)
            for ordinal, root in enumerate(sorted((p for p in placements if p["parent_id"] is None),
                                                 key=lambda p: p["sibling_ordinal"])):
                root["sibling_ordinal"] = ordinal
        rehash_receipt(receipt)
    ResolvedVisualTimelineV2.model_validate(timeline)
    with pytest.raises(ReplayError, match="retained board"):
        private_clock(layout, timeline)


@pytest.mark.parametrize("kind", ["missing", "extra"])
def test_receipt_and_state_maps_cannot_together_invent_layout_inventory(kind):
    layout, timeline = return_receipt_documents()
    returned = timeline["actions"][2]
    receipt = returned["return_hierarchy_receipt"]
    placements = receipt["hierarchy_basis"]["placements"]
    if kind == "missing":
        placements[:] = [p for p in placements if p["object_id"] != "object-evidence"]
        for key in ("expected_object_states", "expected_object_state_versions"):
            returned["action"][key].pop("object-evidence")
        for ordinal, item in enumerate(sorted(placements, key=lambda p: p["sibling_ordinal"])):
            item["sibling_ordinal"] = ordinal
    else:
        item = deepcopy(placements[0])
        item.update(object_id="object-unowned", sibling_ordinal=len(placements))
        placements.append(item)
        placements.sort(key=lambda p: p["object_id"])
        returned["action"]["expected_object_states"]["object-unowned"] = "hidden"
        returned["action"]["expected_object_state_versions"]["object-unowned"] = 1
    rehash_receipt(receipt)
    ResolvedVisualTimelineV2.model_validate(timeline)
    with pytest.raises(V2FrameError, match="exact layout board inventory"):
        evaluate_frame(layout, timeline, 5000)


@pytest.mark.parametrize("kind", ["duplicate", "off_board", "unknown_parent", "cycle", "ordinal_gap", "ordinal_collision"])
def test_return_basis_rejects_incomplete_or_ambiguous_structure(kind):
    _, timeline = return_receipt_documents()
    receipt = timeline["actions"][2]["return_hierarchy_receipt"]
    placements = receipt["hierarchy_basis"]["placements"]
    if kind == "duplicate":
        placements.append(deepcopy(placements[0]))
    elif kind == "off_board":
        for item in placements:
            item["board_id"] = "board-elsewhere"
    elif kind == "unknown_parent":
        placements[0]["parent_id"] = "unknown-object"
    elif kind == "cycle":
        placements[0]["parent_id"] = placements[1]["object_id"]
        placements[1]["parent_id"] = placements[0]["object_id"]
    else:
        placements[0]["sibling_ordinal"] = len(placements) + 1 if kind == "ordinal_gap" else placements[1]["sibling_ordinal"]
    if kind == "off_board":
        rehash_receipt(receipt)
    with pytest.raises(ValueError):
        ResolvedVisualTimelineV2.model_validate(timeline)


def test_regenerated_schema_accepts_receipt_only_as_resolved_compiler_data():
    from conftest import load_schema
    from jsonschema import Draft202012Validator

    _, timeline = return_receipt_documents()
    Draft202012Validator(load_schema("resolved-visual-timeline-v2")).validate(timeline)
    for name in ("visual-plan-v2", "executable-layout-v2"):
        assert "ReturnHierarchyReceipt" not in load_schema(name)["$defs"]


def test_group_must_complete_before_source_activation_end_even_with_return_receipt():
    from atme.render.v2_timeline_replay import ReplayError

    layout, timeline = group_return_documents()
    timeline["actions"][3]["end_ms"] = 6500
    ResolvedVisualTimelineV2.model_validate(timeline)
    with pytest.raises(ReplayError, match="active visible destination sample"):
        private_clock(layout, timeline)


def test_source_board_ordinary_end_commits_before_return_capture_without_polluting_destination_receipt():
    from test_v2_timeline_replay import resolved

    layout, timeline = group_return_documents()
    action = deepcopy(timeline["actions"][3]["action"])
    action.pop("hierarchy_policy")
    action.pop("container_id")
    destination = deepcopy(layout["objects"][-1]["transform"])
    destination["position"]["x"] = 120
    action.update(action_id="interlude-move", board_id="board-interlude", verb="move",
                  target_ids=["object-interlude"], easing="linear", expected_state="visible", post_state="visible",
                  destination=destination, opacity=None)
    timeline["actions"].insert(-1, resolved(action, 6500, 7000).model_dump(mode="json"))
    timeline["coverage"][2]["action_ids"].append("interlude-move")
    _, replay = private_clock(layout, timeline)
    before_return = replay.before_action("return-1")
    assert before_return.object("object-interlude").transform.position.x == 120
    assert dict(before_return.state_versions)["object-interlude"] == 2
    assert replay.at(7001).objects == before_return.objects
    assert replay.at(7001).state_versions == before_return.state_versions


@pytest.mark.parametrize("start,before_return,accepted", [
    (9000, False, True), (5000, False, True), (5000, True, False), (3000, False, False),
])
def test_return_history_validation_does_not_claim_future_operator_support(start, before_return, accepted):
    from test_v2_timeline_replay import resolved

    from atme.render.v2_state import validate_resolved_return_history
    from atme.store.contracts_v2 import ExecutableLayoutV2

    layout, timeline = return_receipt_documents()
    base = timeline["actions"][2]["action"]
    fields = ("action_id", "source_instruction_id", "board_id", "semantic_reason", "trigger",
              "easing", "expected_state", "post_state", "fallback", "coverage_id")
    sound = {key: deepcopy(base[key]) for key in fields}
    sound.update(action_id="future-silence", verb="purposeful_silence", state="silent")
    sound_resolved = resolved(sound, start, start + 100).model_dump(mode="json")
    if before_return:
        timeline["actions"].insert(2, sound_resolved)
    else:
        timeline["actions"].append(sound_resolved)
    timeline["actions"].sort(key=lambda item: item["start_ms"])
    timeline["coverage"][2]["action_ids"].append("future-silence")
    parsed_layout = ExecutableLayoutV2.model_validate(layout)
    parsed_timeline = ResolvedVisualTimelineV2.model_validate(timeline)
    if accepted:
        validate_resolved_return_history(parsed_layout, parsed_timeline, layout_sha256=digest(layout))
    else:
        with pytest.raises(V2FrameError, match="no chronological operator"):
            validate_resolved_return_history(parsed_layout, parsed_timeline, layout_sha256=digest(layout))
