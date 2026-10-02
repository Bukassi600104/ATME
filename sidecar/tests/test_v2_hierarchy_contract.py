"""Authored hierarchy receipt contract; action execution is still a separate gate."""

from copy import deepcopy

import pytest
from conftest import load_schema
from jsonschema import Draft202012Validator
from pydantic import ValidationError
from test_v2_hierarchy_snapshot import basis, ungrouped
from v2_fixtures import visual_plan_v2

from atme.render.v2_hierarchy import (
    UnsupportedHierarchy,
    changed_hierarchy_objects,
    validate_authored_hierarchy,
)
from atme.store.contracts_v2 import (
    GroupAction,
    HierarchyBasis,
    HierarchyTransitionPolicy,
    VisualPlanV2,
    validate_plan_evidence_completeness,
    validate_plan_layout,
)


def receipt_documents():
    layout, timeline, objects, before = basis()
    after = ungrouped(before)
    bases = [HierarchyBasis(placements=[{
        "object_id": node.object_id, "board_id": node.board_id, "parent_id": node.parent_id,
        "sibling_ordinal": node.sibling_ordinal, "local_transform": objects[node.object_id].transform,
    } for node in snapshot.nodes]) for snapshot in (before, after)]
    action = deepcopy(timeline["actions"][-1]["action"])
    action.pop("annotation", None)
    action.update(verb="ungroup", target_ids=["object-system", "object-label"], container_id="object-group",
                  expected_state="grouped", post_state="ungrouped", easing="step", hierarchy_policy={
                      "member_root_ids": ["object-system", "object-label"],
                      "source_basis": bases[0].model_dump(mode="json"),
                      "destination_basis": bases[1].model_dump(mode="json"),
                      "source_basis_sha256": bases[0].checksum(), "destination_basis_sha256": bases[1].checksum(),
                      "changed_object_ids": list(changed_hierarchy_objects(before, after, objects)),
                      "preserve_world_transform": True,
                  })
    plan = visual_plan_v2()
    fields = plan["objects"][0].keys()
    plan["objects"] = [{key: obj[key] for key in fields} for obj in layout["objects"]]
    plan["assets"] = []
    plan["boards"] = deepcopy(layout["boards"])
    plan["actions"] = [deepcopy(item["action"]) for item in timeline["actions"]]
    plan["actions"][-1] = action
    plan["coverage"] = deepcopy(timeline["coverage"])
    for beat in plan["beats"]:
        beat["object_ids"] = [obj["object_id"] for obj in plan["objects"] if obj["beat_id"] == beat["beat_id"]]
        beat["evidence"] = None
    return plan, layout, objects


def rehash(action):
    policy = action["hierarchy_policy"]
    for key in ("source", "destination"):
        policy[f"{key}_basis_sha256"] = HierarchyBasis.model_validate(policy[f"{key}_basis"]).checksum()


def test_full_authored_receipt_schema_and_layout_roundtrip_without_executing_group():
    plan, layout, objects = receipt_documents()
    Draft202012Validator(load_schema("visual-plan-v2")).validate(plan)
    parsed = VisualPlanV2.model_validate(plan)
    action = parsed.actions[-1]
    assert isinstance(action, GroupAction)
    assert GroupAction.model_validate(action.model_dump(mode="json")) == action
    validate_plan_evidence_completeness(plan)
    validate_plan_layout(plan, layout)
    before, after = validate_authored_hierarchy(action, objects)
    assert before.paint_order(objects, "board-main") == after.paint_order(objects, "board-main")


@pytest.mark.parametrize("change", [
    lambda a: a.update(easing="linear"),
    lambda a: a.update(verb="split"),
    lambda a: a.update(expected_state="visible"),
    lambda a: a.update(post_state="visible"),
    lambda a: a.update(container_id=None),
    lambda a: a.update(target_ids=["object-label", "object-system"]),
    lambda a: a["hierarchy_policy"].update(source_basis_sha256="0" * 64),
    lambda a: a["hierarchy_policy"].update(destination_basis_sha256="0" * 64),
    lambda a: a["hierarchy_policy"].update(preserve_world_transform=False),
    lambda a: a["hierarchy_policy"]["member_root_ids"].append("object-system"),
    lambda a: a["hierarchy_policy"]["changed_object_ids"].append("object-group"),
    lambda a: a["hierarchy_policy"]["source_basis"]["placements"].reverse(),
    lambda a: a["hierarchy_policy"]["source_basis"]["placements"][0].update(parent_id="absent"),
    lambda a: a["hierarchy_policy"]["source_basis"]["placements"][0].update(sibling_ordinal=True),
])
def test_policy_rejects_incomplete_ambiguous_or_ignored_parameters(change):
    action = receipt_documents()[0]["actions"][-1]
    change(action)
    with pytest.raises(ValidationError):
        GroupAction.model_validate(action)


def test_legacy_shape_retains_exact_fields_but_new_write_and_layout_gate_reject():
    plan, layout, _ = receipt_documents()
    action = plan["actions"][-1]
    action.pop("hierarchy_policy")
    assert GroupAction.model_validate(action).model_dump(mode="json") == action
    with pytest.raises(ValueError, match="hierarchy policy"):
        validate_plan_evidence_completeness(plan)
    with pytest.raises(ValueError, match="hierarchy policy"):
        validate_plan_layout(plan, layout)


def test_layout_gate_rejects_omitted_shifted_sibling_version_receipt():
    plan, _, objects = receipt_documents()
    action = plan["actions"][-1]
    action["hierarchy_policy"]["changed_object_ids"].remove("object-evidence")
    with pytest.raises(UnsupportedHierarchy, match="version changes"):
        validate_authored_hierarchy(GroupAction.model_validate(action), objects)


def test_layout_gate_rejects_unrelated_transform_change_even_with_valid_new_hash():
    plan, _, objects = receipt_documents()
    action = plan["actions"][-1]
    placement = next(item for item in action["hierarchy_policy"]["destination_basis"]["placements"]
                     if item["object_id"] == "object-evidence")
    placement["local_transform"]["position"]["x"] += 99
    rehash(action)
    with pytest.raises(UnsupportedHierarchy, match="undeclared local transform"):
        validate_authored_hierarchy(GroupAction.model_validate(action), objects)


@pytest.mark.parametrize("change", [lambda shell: setattr(shell, "opacity", .5),
                                     lambda shell: setattr(shell, "visible", False),
                                     lambda shell: setattr(shell.style, "fill", "surface.accent")])
def test_layout_gate_rejects_hidden_translucent_or_painted_group_shell(change):
    plan, _, objects = receipt_documents()
    change(objects["object-group"])
    with pytest.raises(UnsupportedHierarchy, match="visible opaque nonpainting"):
        validate_authored_hierarchy(GroupAction.model_validate(plan["actions"][-1]), objects)


def test_hierarchy_policy_model_is_not_a_claim_of_runtime_readiness():
    action = GroupAction.model_validate(receipt_documents()[0]["actions"][-1])
    assert isinstance(action.hierarchy_policy, HierarchyTransitionPolicy)
    # Full snapshot receipts are schema data. Source-at-action binding,
    # empty-shell ownership and chronological conflicts are not inferred here.
    assert action.verb == "ungroup"


def test_layout_gate_rejects_a_leaf_paint_jump_with_identical_world_geometry():
    plan, _, objects = receipt_documents()
    action = plan["actions"][-1]
    for placement in action["hierarchy_policy"]["destination_basis"]["placements"]:
        if placement["object_id"] == "object-label":
            placement["sibling_ordinal"] = 1
        elif placement["object_id"] == "object-system":
            placement["sibling_ordinal"] = 2
    rehash(action)
    with pytest.raises(UnsupportedHierarchy, match="paint order"):
        validate_authored_hierarchy(GroupAction.model_validate(action), objects)
