"""Authored hidden Group roots do not require changing child-local paint state."""

from copy import deepcopy

import pytest
from atme.store.contracts_v2 import (
    ExecutableLayoutV2,
    SemanticStandardObjectSpec,
    VisualPlanV2,
    validate_plan_evidence_completeness,
    validate_plan_layout,
)
from conftest import load_schema
from jsonschema import Draft202012Validator
from test_v2_callout_contract import callout_documents
from test_v2_group_hierarchy import grouped_documents
from v2_fixtures import digest


def hidden_compound_documents():
    plan, layout, _ = callout_documents()
    body = next(obj for obj in layout["objects"] if obj["object_id"] == "annotation-note")
    body.update(visible=True, initial_state="visible", parent_id="callout-root")
    next(obj for obj in plan["objects"] if obj["object_id"] == body["object_id"])["initial_state"] = "visible"
    root = deepcopy(grouped_documents()[0]["objects"][3])
    root.update(object_id="callout-root", child_ids=[body["object_id"]], z_index=6,
        visible=False, initial_state="hidden")
    layout["objects"].append(root)
    spec = {name: deepcopy(root[name]) for name in SemanticStandardObjectSpec.model_fields if name in root}
    # This must remain explicitly authored even before the field is implemented.
    spec["child_ids"] = [body["object_id"]]
    plan["objects"].append(spec)
    for document in (plan, layout):
        document["boards"][0]["object_ids"].append(root["object_id"])
        document["boards"][0]["density_limit"] = 7
    plan["beats"][0]["object_ids"].append(root["object_id"])
    layout["plan_sha256"] = digest(plan)
    return plan, layout


def test_hidden_compound_callout_has_exact_semantic_membership_and_layout_ancestry():
    plan, layout = hidden_compound_documents()
    parsed = VisualPlanV2.model_validate(plan)
    assert next(obj for obj in parsed.objects if obj.object_id == "callout-root").child_ids == ["annotation-note"]
    validate_plan_evidence_completeness(plan)
    validate_plan_layout(plan, layout)
    assert next(obj for obj in ExecutableLayoutV2.model_validate(layout).objects
        if obj.object_id == "annotation-note").visible
    assert not next(obj for obj in ExecutableLayoutV2.model_validate(layout).objects
        if obj.object_id == "annotation-leader").visible


@pytest.mark.parametrize("field", ["visible", "initial_state", "opacity"])
def test_hidden_compound_exception_cannot_mask_a_nonhidden_root(field):
    _, layout = hidden_compound_documents()
    root = layout["objects"][-1]
    root[field] = True if field == "visible" else 0. if field == "opacity" else "visible"
    with pytest.raises(ValueError, match="callout|Callout"):
        ExecutableLayoutV2.model_validate(layout)


@pytest.mark.parametrize("fault", ["unknown", "duplicate", "self", "cross_board", "multiple_parent", "cycle", "non_group"])
def test_semantic_group_membership_is_explicit_unique_same_board_single_parent_and_acyclic(fault):
    plan, _ = hidden_compound_documents()
    root = plan["objects"][-1]
    if fault == "unknown":
        root["child_ids"] = ["unknown"]
    elif fault == "duplicate":
        root["child_ids"] *= 2
    elif fault == "self":
        root["child_ids"] = [root["object_id"]]
    elif fault == "cross_board":
        next(obj for obj in plan["objects"] if obj["object_id"] == "annotation-note")["board_id"] = "other-board"
    elif fault in {"multiple_parent", "cycle"}:
        other = deepcopy(root)
        other.update(object_id="other-root", child_ids=["annotation-note"] if fault == "multiple_parent" else [root["object_id"]])
        plan["objects"].append(other)
        if fault == "cycle":
            root["child_ids"] = ["other-root"]
    else:
        root["object_type"] = "text"
    with pytest.raises(ValueError, match="child_ids|membership|parent|ancestry|group|cycle"):
        VisualPlanV2.model_validate(plan)


@pytest.mark.parametrize("fault", ["omitted", "wrong_child", "root_state"])
def test_callout_hidden_semantic_ancestry_cannot_differ_from_layout(fault):
    plan, layout = hidden_compound_documents()
    if fault == "omitted":
        plan["objects"][-1].pop("child_ids")
    elif fault == "wrong_child":
        plan["objects"][-1]["child_ids"] = ["object-label"]
    else:
        plan["objects"][-1]["initial_state"] = "visible"
    layout["plan_sha256"] = digest(plan)
    with pytest.raises(ValueError, match="callout|Callout|child_ids|initial_state"):
        validate_plan_layout(plan, layout)


def test_semantic_group_legacy_absence_is_omitted_and_distributable_schema_accepts_explicit_membership():
    plan, _ = hidden_compound_documents()
    explicit = SemanticStandardObjectSpec.model_validate(plan["objects"][-1])
    assert explicit.model_dump(mode="json")["child_ids"] == ["annotation-note"]
    legacy = deepcopy(plan["objects"][-1])
    legacy.pop("child_ids")
    if legacy.get("clip_id") is None:
        legacy.pop("clip_id", None)
    assert SemanticStandardObjectSpec.model_validate(legacy).model_dump(mode="json") == legacy
    Draft202012Validator(load_schema("visual-plan-v2")).validate(plan)
    wrong_owner = deepcopy(plan)
    wrong_owner["objects"][-1]["object_type"] = "text"
    assert list(Draft202012Validator(load_schema("visual-plan-v2")).iter_errors(wrong_owner))
