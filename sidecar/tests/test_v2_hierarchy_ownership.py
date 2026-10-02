"""Owned initial shells and exact initial resolved receipts; execution is separate."""

from copy import deepcopy

import pytest
from conftest import load_schema
from jsonschema import Draft202012Validator
from pydantic import ValidationError
from test_v2_hierarchy_contract import receipt_documents, rehash
from test_v2_hierarchy_snapshot import basis
from v2_fixtures import digest, executable_layout_v2, resolved_timeline_v2

from atme.render.v2_hierarchy import (
    HierarchyNode,
    HierarchySnapshot,
    changed_hierarchy_objects,
)
from atme.render.v2_state import UnsupportedVisualAction, V2FrameError, evaluate_frame
from atme.store.contracts_v2 import (
    ExecutableLayoutV2,
    HierarchyBasis,
    ResolvedVisualTimelineV2,
    VisualPlanV2,
    validate_plan_layout,
    validate_resolved_structure,
)


def documents():
    plan, layout, _ = receipt_documents()
    action = plan["actions"][-1]
    policy = action["hierarchy_policy"]
    policy["source_basis"], policy["destination_basis"] = policy["destination_basis"], policy["source_basis"]
    action.update(verb="group", expected_state="ungrouped", post_state="grouped")
    rehash(action)
    layout["initial_empty_group_ownership"] = [{
        "shell_object_id": "object-group", "owner_group_action_id": action["action_id"],
        "owner_source_basis_sha256": policy["source_basis_sha256"],
    }]
    for obj in layout["objects"]:
        obj["parent_id"] = None
        if obj["object_id"] == "object-group":
            obj.update(child_ids=[], initial_state="ungrouped")
    semantic_fields = plan["objects"][0].keys()
    plan["objects"] = [{key: obj[key] for key in semantic_fields} for obj in layout["objects"]]
    _, timeline, _, _ = basis()
    for state in timeline["initial_object_states"]:
        if state["object_id"] == "object-group":
            state["state"] = "ungrouped"
    timeline["actions"][-1]["action"] = deepcopy(action)
    timeline["initial_hierarchy_basis"] = deepcopy(policy["source_basis"])
    timeline["initial_hierarchy_basis_sha256"] = policy["source_basis_sha256"]
    timeline["layout_sha256"] = digest(layout)
    return plan, layout, timeline


def paired(plan, layout, timeline):
    validate_plan_layout(plan, layout)
    parsed = ResolvedVisualTimelineV2.model_validate(timeline)
    validate_resolved_structure(VisualPlanV2.model_validate(plan), ExecutableLayoutV2.model_validate(layout),
                                parsed, parsed.duration_ms)
    return parsed


def test_owned_empty_shell_and_initial_basis_roundtrip_preserve_member_semantic_states():
    plan, layout, timeline = documents()
    original = deepcopy((plan, layout, timeline))
    resolved = paired(plan, layout, timeline)
    parsed_layout = ExecutableLayoutV2.model_validate(layout)
    Draft202012Validator(load_schema("executable-layout-v2")).validate(layout)
    Draft202012Validator(load_schema("resolved-visual-timeline-v2")).validate(timeline)
    assert ExecutableLayoutV2.model_validate(parsed_layout.model_dump(mode="json")) == parsed_layout
    assert ResolvedVisualTimelineV2.model_validate(resolved.model_dump(mode="json")) == resolved
    assert resolved.actions[-1].action.expected_state == "ungrouped"
    # Neither accepting these contracts nor ownership enables unverified playback.
    with pytest.raises(UnsupportedVisualAction, match="group"):
        evaluate_frame(layout, timeline, 5000)
    assert (plan, layout, timeline) == original


@pytest.mark.parametrize("factory,model,fields,baseline_hash", [
    (executable_layout_v2, ExecutableLayoutV2, ["initial_empty_group_ownership"],
     "4041bc027a52675f4398095ccf0f876047517b98cd2bf16110bdbc1947153c3d"),
    (resolved_timeline_v2, ResolvedVisualTimelineV2, ["initial_hierarchy_basis", "initial_hierarchy_basis_sha256"],
     "5a3a2430d1bbe21aa4010d2b7e2775107f30135630a28a22b04664a410ebd32f"),
])
def test_legacy_serialization_omits_absent_receipts_and_preserves_hash(factory, model, fields, baseline_hash):
    document = factory()
    parsed = model.model_validate(document)
    dumped = parsed.model_dump(mode="json")
    assert not set(fields).intersection(dumped)
    # Captured from the pre-ownership model at7ea4d0b, not the raw fixture:
    # existing normalization/default insertion is part of legacy serialization.
    assert digest(dumped) == baseline_hash


@pytest.mark.parametrize("change", [
    lambda l: l.pop("initial_empty_group_ownership"),
    lambda l: l["initial_empty_group_ownership"].append(deepcopy(l["initial_empty_group_ownership"][0])),
    lambda l: l["initial_empty_group_ownership"][0].update(shell_object_id="object-label"),
    lambda l: l["objects"][3].update(object_type="clip"),
    lambda l: l["objects"][3].update(object_type="mask"),
    lambda l: l["objects"][3].update(visible=False),
    lambda l: l["objects"][3].update(opacity=.5),
    lambda l: l["objects"][3].update(initial_state="grouped"),
    lambda l: l["objects"][3]["style"].update(stroke="ink.primary"),
    lambda l: l["objects"][3]["geometry"]["points"].append({"x": 50, "y": 100}),
])
def test_empty_shell_requires_exact_nonpainting_ownership_inventory(change):
    _, layout, _ = documents()
    change(layout)
    with pytest.raises(ValidationError):
        ExecutableLayoutV2.model_validate(layout)


def test_nonempty_group_cannot_claim_empty_ownership():
    _, layout, _ = documents()
    layout["objects"][3]["child_ids"] = ["object-label"]
    layout["objects"][1]["parent_id"] = "object-group"
    with pytest.raises(ValidationError, match="nonempty"):
        ExecutableLayoutV2.model_validate(layout)


@pytest.mark.parametrize("change", [
    lambda l: l["initial_empty_group_ownership"][0].update(owner_group_action_id="unknown-action"),
    lambda l: l["initial_empty_group_ownership"][0].update(owner_group_action_id="action-1"),
    lambda l: l["initial_empty_group_ownership"][0].update(owner_source_basis_sha256="0" * 64),
])
def test_plan_binding_rejects_missing_wrong_owner_or_wrong_hash(change):
    plan, layout, _ = documents()
    change(layout)
    with pytest.raises(ValueError, match="ownership"):
        validate_plan_layout(plan, layout)


@pytest.mark.parametrize("change", [
    lambda t: t.pop("initial_hierarchy_basis"),
    lambda t: t.pop("initial_hierarchy_basis_sha256"),
    lambda t: (t.pop("initial_hierarchy_basis"), t.pop("initial_hierarchy_basis_sha256")),
    lambda t: t.update(initial_hierarchy_basis_sha256="0" * 64),
    lambda t: t["initial_hierarchy_basis"]["placements"].pop(),
])
def test_resolved_hierarchy_requires_complete_canonical_initial_receipt(change):
    _, _, timeline = documents()
    change(timeline)
    with pytest.raises(ValidationError):
        ResolvedVisualTimelineV2.model_validate(timeline)


@pytest.mark.parametrize("change", [
    lambda p: p["local_transform"]["position"].update(x=12),
    lambda p: p.update(sibling_ordinal=2),
])
def test_pair_rejects_initial_transform_or_order_changed_from_layout(change):
    plan, layout, timeline = documents()
    placement = next(p for p in timeline["initial_hierarchy_basis"]["placements"] if p["object_id"] == "object-group")
    change(placement)
    if placement["sibling_ordinal"] == 2:
        other = next(p for p in timeline["initial_hierarchy_basis"]["placements"] if p["object_id"] == "object-label")
        other["sibling_ordinal"] = 0
    timeline["initial_hierarchy_basis_sha256"] = HierarchyBasis.model_validate(timeline["initial_hierarchy_basis"]).checksum()
    with pytest.raises(ValueError, match="initial hierarchy"):
        paired(plan, layout, timeline)
    with pytest.raises(V2FrameError, match="initial hierarchy"):
        evaluate_frame(layout, timeline, 5000)


def test_pair_rejects_owner_absent_from_resolved_actions():
    plan, layout, timeline = documents()
    removed = timeline["actions"].pop()["action"]
    timeline["coverage"] = [row for row in timeline["coverage"] if removed["action_id"] not in row["action_ids"]]
    timeline["fallbacks"] = [row for row in timeline["fallbacks"] if row["fallback_id"] != removed["fallback"]["fallback_id"]]
    resolved = ResolvedVisualTimelineV2.model_validate(timeline)
    with pytest.raises(ValueError, match="earliest"):
        validate_resolved_structure(VisualPlanV2.model_validate(plan), ExecutableLayoutV2.model_validate(layout),
                                    resolved, resolved.duration_ms)
    with pytest.raises(V2FrameError, match="earliest"):
        evaluate_frame(layout, timeline, 5000)


def test_group_does_not_overwrite_member_semantic_state_for_later_edit():
    _, _, timeline = documents()
    action = deepcopy(timeline["actions"][0])
    action["action"].update(action_id="later-exit", verb="exit", target_ids=["object-system"],
                            expected_state="visible", post_state="removed", trigger={"kind": "absolute", "at_ms": 8000})
    action.update(start_ms=8000, end_ms=9000)
    action["resolved_trigger"].update(source=action["action"]["trigger"], alignment_anchor_ms=8000,
                                       resolved_at_ms=8000, matched_text=None, matched_occurrence=None, exact=True)
    timeline["actions"].append(action)
    timeline["coverage"][0]["action_ids"].append("later-exit")
    assert ResolvedVisualTimelineV2.model_validate(timeline).actions[-1].action.expected_state == "visible"


def at_time(template, action_id, start, end):
    row = deepcopy(template)
    row["action"].update(action_id=action_id, trigger={"kind": "absolute", "at_ms": start})
    row.update(start_ms=start, end_ms=end)
    row["resolved_trigger"].update(source=row["action"]["trigger"], alignment_anchor_ms=start,
                                   resolved_at_ms=start, matched_text=None, matched_occurrence=None, exact=True)
    return row


def test_owner_cannot_be_a_later_regroup_even_when_its_id_and_hash_match_plan():
    plan, layout, timeline = documents()
    ungroup = at_time(timeline["actions"][-1], "ungroup-later", 6000, 6900)
    policy = ungroup["action"]["hierarchy_policy"]
    policy["source_basis"], policy["destination_basis"] = policy["destination_basis"], policy["source_basis"]
    ungroup["action"].update(verb="ungroup", expected_state="grouped", post_state="ungrouped")
    rehash(ungroup["action"])
    regroup = at_time(timeline["actions"][-1], "regroup-later", 8000, 8900)
    timeline["actions"].extend([ungroup, regroup])
    coverage = next(row for row in timeline["coverage"] if "action-3" in row["action_ids"])
    coverage["action_ids"].extend(["ungroup-later", "regroup-later"])
    plan["actions"].extend([ungroup["action"], regroup["action"]])
    plan["coverage"] = deepcopy(timeline["coverage"])
    plan["beats"][-1]["action_ids"].extend(["ungroup-later", "regroup-later"])
    owner = layout["initial_empty_group_ownership"][0]
    owner["owner_group_action_id"] = "regroup-later"
    timeline["layout_sha256"] = digest(layout)
    validate_plan_layout(plan, layout)
    with pytest.raises(ValueError, match="earliest"):
        paired(plan, layout, timeline)


def test_owner_source_basis_may_include_an_authored_prior_member_move_not_initial_transform():
    plan, layout, timeline = documents()
    policy = plan["actions"][-1]["hierarchy_policy"]
    initial = deepcopy(timeline["initial_hierarchy_basis"])
    for basis_key in ("source_basis", "destination_basis"):
        root = next(p for p in policy[basis_key]["placements"] if p["object_id"] == "object-system")
        root["local_transform"]["position"]["x"] = 12
    rehash(plan["actions"][-1])
    timeline["actions"][-1]["action"] = deepcopy(plan["actions"][-1])
    layout["initial_empty_group_ownership"][0]["owner_source_basis_sha256"] = policy["source_basis_sha256"]
    move = at_time(timeline["actions"][0], "prior-move", 1000, 1900)
    from_transform = deepcopy(layout["objects"][0]["transform"])
    to_transform = deepcopy(from_transform)
    to_transform["position"]["x"] = 12
    move["action"].pop("annotation", None)
    move["action"].update(verb="move", expected_state="visible", post_state="visible",
                           destination=to_transform)
    timeline["actions"].insert(1, move)
    coverage = next(row for row in timeline["coverage"] if "action-1" in row["action_ids"])
    coverage["action_ids"].append("prior-move")
    plan["actions"].insert(1, deepcopy(move["action"]))
    plan["beats"][0]["action_ids"].append("prior-move")
    plan["coverage"] = deepcopy(timeline["coverage"])
    timeline["layout_sha256"] = digest(layout)
    parsed = paired(plan, layout, timeline)
    assert parsed.initial_hierarchy_basis.model_dump(mode="json") == initial
    assert parsed.initial_hierarchy_basis != parsed.actions[-1].action.hierarchy_policy.source_basis


def test_two_empty_shells_bind_one_to_one_to_their_real_owners_not_swapped_receipts():
    plan, layout, _ = documents()
    second_shell = deepcopy(layout["objects"][3])
    second_shell["object_id"] = "object-other-group"
    layout["objects"].append(second_shell)
    for doc in (plan, layout):
        doc["boards"][0]["object_ids"].append(second_shell["object_id"])
        doc["boards"][0]["density_limit"] = 12
    plan["objects"].append({key: second_shell[key] for key in plan["objects"][0]})
    plan["beats"][0]["object_ids"].append(second_shell["object_id"])
    objects = {obj.object_id: obj for obj in ExecutableLayoutV2.model_validate({
        **layout, "initial_empty_group_ownership": layout["initial_empty_group_ownership"] + [{
            "shell_object_id": second_shell["object_id"], "owner_group_action_id": "second-group",
            "owner_source_basis_sha256": "0" * 64}]}).objects}
    source_ordinals = {"object-group": 0, "object-other-group": 1, "object-system": 2,
                       "object-label": 3, "object-evidence": 4}
    before = HierarchySnapshot(tuple(HierarchyNode(key, "board-main", None, source_ordinals[key])
                                     for key in sorted(objects)))
    source = HierarchyBasis(placements=[{
        "object_id": node.object_id, "board_id": node.board_id, "parent_id": node.parent_id,
        "sibling_ordinal": node.sibling_ordinal, "local_transform": objects[node.object_id].transform,
    } for node in before.nodes]).model_dump(mode="json")
    group_actions = []
    for action_id, shell_id in (("action-3", "object-group"), ("second-group", "object-other-group")):
        action = deepcopy(plan["actions"][-1])
        action.update(action_id=action_id, container_id=shell_id)
        destination = deepcopy(source)
        for item in destination["placements"]:
            key = item["object_id"]
            if key in {"object-system", "object-label"}:
                item.update(parent_id=shell_id, sibling_ordinal=0 if key == "object-system" else 1)
            elif key == "object-evidence":
                item["sibling_ordinal"] = 2
        after = HierarchySnapshot(tuple(HierarchyNode(p["object_id"], p["board_id"], p["parent_id"], p["sibling_ordinal"])
                                        for p in destination["placements"]))
        action["hierarchy_policy"].update(source_basis=deepcopy(source), destination_basis=destination,
                                            changed_object_ids=list(changed_hierarchy_objects(before, after, objects)))
        rehash(action)
        group_actions.append(action)
    ungroup = deepcopy(group_actions[0])
    ungroup.update(action_id="between-ungroup", verb="ungroup", expected_state="grouped", post_state="ungrouped")
    policy = ungroup["hierarchy_policy"]
    policy["source_basis"], policy["destination_basis"] = policy["destination_basis"], policy["source_basis"]
    rehash(ungroup)
    plan["actions"][-1:] = [group_actions[0], ungroup, group_actions[1]]
    plan["beats"][-1]["action_ids"].extend(["between-ungroup", "second-group"])
    next(row for row in plan["coverage"] if "action-3" in row["action_ids"])["action_ids"].extend(
        ["between-ungroup", "second-group"])
    layout["initial_empty_group_ownership"] = [{
        "shell_object_id": action["container_id"], "owner_group_action_id": action["action_id"],
        "owner_source_basis_sha256": action["hierarchy_policy"]["source_basis_sha256"],
    } for action in group_actions]
    validate_plan_layout(plan, layout)
    rows = layout["initial_empty_group_ownership"]
    rows[0]["owner_group_action_id"], rows[1]["owner_group_action_id"] = rows[1]["owner_group_action_id"], rows[0]["owner_group_action_id"]
    with pytest.raises(ValueError, match="ownership"):
        validate_plan_layout(plan, layout)


def test_owned_shell_source_cannot_secretly_contain_a_member_before_grouping():
    plan, _, _ = documents()
    action = plan["actions"][-1]
    source = action["hierarchy_policy"]["source_basis"]["placements"]
    next(p for p in source if p["object_id"] == "object-system").update(parent_id="object-group", sibling_ordinal=0)
    next(p for p in source if p["object_id"] == "object-label")["sibling_ordinal"] = 1
    next(p for p in source if p["object_id"] == "object-evidence")["sibling_ordinal"] = 2
    rehash(action)
    with pytest.raises(ValidationError, match="group"):
        VisualPlanV2.model_validate(plan)


def test_nonempty_ungroup_requires_initial_basis_but_no_empty_shell_owner():
    plan, layout, _ = receipt_documents()
    layout["objects"][3]["initial_state"] = "grouped"
    next(obj for obj in plan["objects"] if obj["object_id"] == "object-group")["initial_state"] = "grouped"
    _, timeline, _, _ = basis()
    timeline["initial_object_states"][3]["state"] = "grouped"
    timeline["actions"][-1]["action"] = deepcopy(plan["actions"][-1])
    timeline["initial_hierarchy_basis"] = deepcopy(plan["actions"][-1]["hierarchy_policy"]["source_basis"])
    timeline["initial_hierarchy_basis_sha256"] = plan["actions"][-1]["hierarchy_policy"]["source_basis_sha256"]
    timeline["layout_sha256"] = digest(layout)
    parsed = paired(plan, layout, timeline)
    assert parsed.actions[-1].action.verb == "ungroup"
    assert not ExecutableLayoutV2.model_validate(layout).initial_empty_group_ownership
