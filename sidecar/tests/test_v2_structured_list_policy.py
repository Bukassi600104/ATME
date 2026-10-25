"""Whole-real-item progression is an exact policy, not inferred list contents."""

from copy import deepcopy

import pytest
from atme.render.v2_split_identity import _stored_value
from atme.store import contracts_v2 as contracts
from conftest import load_schema
from jsonschema import Draft202012Validator
from test_v2_progressive_list import list_documents
from test_v2_structured_list_contract import documents, payload
from v2_fixtures import digest


def policy():
    return {"version": "1.0.0", "list_object_id": "object-evidence", "container_group_id": "list-group",
        "item_object_ids": payload()["item_object_ids"],
        "phases": [{"object_id": key, "weight": weight} for key, weight in
            zip(payload()["item_object_ids"], (1, 2, 1), strict=True)],
        "expected_item_state_versions": {key: 1 for key in payload()["item_object_ids"]}}


def action():
    row = deepcopy(list_documents()[1]["actions"][2]["action"])
    row.update(target_ids=payload()["item_object_ids"], structured_list_policy=policy())
    return row


def model():
    assert hasattr(contracts, "StructuredListPolicy"), "exact whole-real-item progression policy is missing"
    return contracts.StructuredListPolicy


def test_structured_policy_exact_authored_fields_are_required_and_roundtrip():
    assert model().model_validate(policy()).model_dump(mode="json") == policy()
    for name in policy():
        raw = policy()
        raw.pop(name)
        with pytest.raises(ValueError):
            model().model_validate(raw)


@pytest.mark.parametrize("fault", ["order", "duplicate", "phase_order", "phase_missing", "weight_bool",
    "weight_fraction", "weight_zero", "version_bool", "version_zero", "missing_version", "extra_version",
    "self_heading", "self_group", "unknown_field"])
def test_structured_policy_cannot_infer_items_phases_versions_or_accept_ambiguous_types(fault):
    raw = policy()
    if fault == "order":
        raw["item_object_ids"].reverse()
    elif fault == "duplicate":
        raw["item_object_ids"][1] = "list-item-a"
    elif fault == "phase_order":
        raw["phases"].reverse()
    elif fault == "phase_missing":
        raw["phases"].pop()
    elif fault.startswith("weight"):
        raw["phases"][0]["weight"] = {"weight_bool": True, "weight_fraction": .5, "weight_zero": 0}[fault]
    elif fault in {"version_bool", "version_zero"}:
        raw["expected_item_state_versions"]["list-item-a"] = True if fault == "version_bool" else 0
    elif fault == "missing_version":
        raw["expected_item_state_versions"].pop("list-item-a")
    elif fault == "extra_version":
        raw["expected_item_state_versions"]["object-evidence"] = 1
    elif fault == "self_heading":
        raw["list_object_id"] = "list-item-a"
    elif fault == "self_group":
        raw["container_group_id"] = "list-item-a"
    else:
        raw["generated_strings"] = ["not authored"]
    with pytest.raises(ValueError):
        model().model_validate(raw)


@pytest.mark.parametrize("fault", ["verb", "target_order", "heading_target", "expected_state", "post_state",
    "easing", "annotation", "annotation_policy", "count_policy"])
def test_structured_progression_uses_only_exact_items_canonical_states_and_one_policy(fault):
    model()
    raw = action()
    if fault == "verb":
        raw["verb"] = "reveal"
    elif fault == "target_order":
        raw["target_ids"].reverse()
    elif fault == "heading_target":
        raw["target_ids"].append("object-evidence")
    elif fault == "expected_state":
        raw["expected_state"] = None
    elif fault == "post_state":
        raw["post_state"] = "removed"
    elif fault == "easing":
        raw["easing"] = "ease_out"
    elif fault == "annotation":
        raw["annotation"] = "inferred annotation"
    elif fault == "annotation_policy":
        from test_v2_annotation_action import annotation_documents
        raw["annotation_policy"] = annotation_documents()[2]["actions"][-1]["action"]["annotation_policy"]
    else:
        from test_v2_count_contract import count_policy
        raw["count_policy"] = count_policy()
    with pytest.raises(ValueError):
        contracts.TargetAction.model_validate(raw)


def progression_documents():
    plan, layout = documents()
    plan["actions"][-1] = action()
    layout["plan_sha256"] = digest(plan)
    return plan, layout


def test_policy_heading_and_container_are_read_refs_never_child_write_targets():
    parsed = contracts.TargetAction.model_validate(action())
    assert contracts._action_object_references(parsed) == [*payload()["item_object_ids"], "object-evidence", "list-group"]
    assert contracts._action_mutation_references(parsed) == payload()["item_object_ids"]
    plan, layout = progression_documents()
    contracts.validate_plan_evidence_completeness(plan)
    contracts.validate_plan_layout(plan, layout)


@pytest.mark.parametrize("fault", ["heading", "container", "item_order", "missing_policy"])
def test_policy_cannot_diverge_from_authoritative_structured_list_payload(fault):
    model()
    plan, layout = progression_documents()
    raw = plan["actions"][-1]
    if fault == "heading":
        raw["structured_list_policy"]["list_object_id"] = "object-system"
    elif fault == "container":
        raw["structured_list_policy"]["container_group_id"] = "object-system"
    elif fault == "item_order":
        raw["structured_list_policy"]["item_object_ids"].reverse()
        raw["structured_list_policy"]["phases"].reverse()
        raw["target_ids"].reverse()
    else:
        raw.pop("structured_list_policy")
    layout["plan_sha256"] = digest(plan)
    with pytest.raises(ValueError, match="structured|policy|binding"):
        contracts.validate_plan_layout(plan, layout)


def test_explicit_weighted_integer_windows_bind_exact_whole_item_phase_ends():
    model()
    resolved = deepcopy(list_documents()[1]["actions"][2])
    resolved["action"] = action()
    parsed = contracts.ResolvedAction.model_validate(resolved)
    windows = contracts._structured_list_phase_windows(parsed)
    assert [(row.object_id, start, end) for row, start, end in windows] == [
        ("list-item-a", 4000, 4225), ("list-item-b", 4225, 4675), ("list-item-c", 4675, 4900)]
    resolved["end_ms"] = 4002
    with pytest.raises(ValueError, match="collapse"):
        contracts.ResolvedAction.model_validate(resolved)


@pytest.mark.parametrize("level", ["policy", "phase"])
def test_structured_policy_unknown_subclasses_fail_identity_and_legacy_action_dump_is_unchanged(level):
    model()
    candidate = contracts.TargetAction.model_validate(action())
    if level == "policy":
        class UnknownPolicy(contracts.StructuredListPolicy):
            pass
        candidate.structured_list_policy = UnknownPolicy.model_validate(policy())
    else:
        class UnknownPhase(contracts.StructuredListPhase):
            pass
        candidate.structured_list_policy.phases[0] = UnknownPhase.model_validate(policy()["phases"][0])
    with pytest.raises(ValueError, match="unknown nested payload subclass"):
        _stored_value(candidate)
    legacy = list_documents()[1]["actions"][2]["action"]
    assert contracts.TargetAction.model_validate(legacy).model_dump(mode="json") == legacy


def resolved_documents():
    plan, layout = progression_documents()
    _, timeline = list_documents()
    timeline["actions"][-1]["action"] = action()
    timeline["initial_object_states"] = [{"object_id": obj["object_id"], "state": obj["initial_state"],
        "visible": obj["visible"], "state_version": 1} for obj in layout["objects"]]
    timeline["plan_sha256"] = layout["plan_sha256"]
    timeline["layout_sha256"] = digest(layout)
    return plan, layout, timeline


@pytest.mark.parametrize("fault", ["phases", "versions", "missing", "none"])
def test_resolved_structured_policy_inventory_is_exactly_bound_to_authoritative_plan(fault):
    model()
    plan, layout, timeline = resolved_documents()
    raw = timeline["actions"][-1]["action"]
    if fault == "phases":
        raw["structured_list_policy"]["phases"][0]["weight"] = 2
    elif fault == "versions":
        raw["structured_list_policy"]["expected_item_state_versions"]["list-item-a"] = 2
    elif fault == "missing":
        raw.pop("structured_list_policy")
    if fault == "none":
        contracts.validate_resolved_structure(contracts.VisualPlanV2.model_validate(plan),
            contracts.ExecutableLayoutV2.model_validate(layout),
            contracts.ResolvedVisualTimelineV2.model_validate(timeline), 10000)
    else:
        with pytest.raises(ValueError, match="structured list.*inventory|structured list.*policy"):
            contracts.validate_resolved_structure(contracts.VisualPlanV2.model_validate(plan),
                contracts.ExecutableLayoutV2.model_validate(layout),
                contracts.ResolvedVisualTimelineV2.model_validate(timeline), 10000)


@pytest.mark.parametrize("fault", ["valid", "nonlinear", "omitted_easing", "omitted_expected_state", "mixed_count"])
def test_distributable_policy_schemas_preserve_exact_contract_and_canonical_fields(fault):
    plan, _, timeline = resolved_documents()
    for document, name in ((plan, "visual-plan-v2"), (timeline, "resolved-visual-timeline-v2")):
        raw = document["actions"][-1] if name == "visual-plan-v2" else document["actions"][-1]["action"]
        if fault == "nonlinear":
            raw["easing"] = "ease_out"
        elif fault == "omitted_easing":
            raw.pop("easing")
        elif fault == "omitted_expected_state":
            raw.pop("expected_state")
        elif fault == "mixed_count":
            from test_v2_count_contract import count_policy
            raw["count_policy"] = count_policy()
        errors = list(Draft202012Validator(load_schema(name)).iter_errors(document))
        assert bool(errors) == (fault != "valid")


def test_policy_parsing_cannot_bypass_complete_readable_heading_prerequisite():
    from atme.render.v2_state import V2FrameError, evaluate_frame

    _, layout, timeline = resolved_documents()
    with pytest.raises(V2FrameError, match="readable heading"):
        evaluate_frame(layout, timeline, 0)


def test_private_chronology_has_dedicated_item_only_structured_operator():
    from atme.render.v2_timeline_replay import supports_operator, version_targets

    parsed = contracts.TargetAction.model_validate(action())
    assert supports_operator(parsed)
    assert version_targets(parsed) == tuple(payload()["item_object_ids"])


def legacy_plan_documents(*, multiple=False):
    plan, layout = documents()
    heading = next(obj for obj in layout["objects"] if obj["object_type"] == "list")
    heading.pop("structured_list")
    heading["items"] = ["Authored legacy item"]
    semantic = next(obj for obj in plan["objects"] if obj["object_type"] == "list")
    semantic.pop("structured_list")
    plan["actions"][-1]["verb"] = "progressive_reveal"
    if multiple:
        second = deepcopy(heading)
        second.update(object_id="second-flat-list", z_index=4, text="Another authored heading")
        layout["objects"].append(second)
        other = deepcopy(semantic)
        other["object_id"] = second["object_id"]
        plan["objects"].append(other)
        for document in (plan, layout):
            group = next(obj for obj in document["objects"] if obj["object_id"] == "list-group")
            group["child_ids"].append(second["object_id"])
            document["boards"][0]["object_ids"].append(second["object_id"])
            document["boards"][0]["density_limit"] = 8
        plan["beats"][1]["object_ids"].append(second["object_id"])
        plan["actions"][-1]["target_ids"].append(second["object_id"])
    layout["plan_sha256"] = digest(plan)
    return plan, layout


@pytest.mark.parametrize("multiple", [False, True])
def test_legacy_normal_writes_preserve_one_or_multiple_authored_flat_lists(multiple):
    plan, layout = legacy_plan_documents(multiple=multiple)
    contracts.validate_plan_evidence_completeness(plan)
    contracts.validate_plan_layout(plan, layout)
    assert contracts.TargetAction.model_validate(plan["actions"][-1]).model_dump(mode="json") == plan["actions"][-1]


@pytest.mark.parametrize("target", ["list-group", "object-label"])
@pytest.mark.parametrize("semantic", [False, True])
def test_policyless_normal_write_rejects_container_or_plain_text_but_legacy_parsing_is_unchanged(target, semantic):
    plan, layout = legacy_plan_documents()
    plan["actions"][-1]["target_ids"] = [target]
    layout["plan_sha256"] = digest(plan)
    assert contracts.VisualPlanV2.model_validate(plan).model_dump(mode="json")["actions"][-1] == plan["actions"][-1]
    with pytest.raises(ValueError, match="flat list|structured|policy"):
        if semantic:
            contracts.validate_plan_evidence_completeness(plan)
        else:
            contracts.validate_plan_layout(plan, layout)


def test_policyless_normal_write_cannot_mix_flat_and_nonflat_targets():
    plan, layout = legacy_plan_documents(multiple=True)
    plan["actions"][-1]["target_ids"].append("list-group")
    layout["plan_sha256"] = digest(plan)
    with pytest.raises(ValueError, match="flat list|structured|policy"):
        contracts.validate_plan_layout(plan, layout)


@pytest.mark.parametrize("items", [[], ["Two\nlines"], [" "]])
def test_policyless_layout_normal_write_reuses_exact_legacy_item_validation(items):
    plan, layout = legacy_plan_documents()
    next(obj for obj in layout["objects"] if obj["object_type"] == "list")["items"] = items
    with pytest.raises(ValueError, match="ordered-child list|one-line"):
        contracts.validate_plan_layout(plan, layout)
