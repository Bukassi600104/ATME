"""P3-37 initial Clip/Mask semantic ownership, never public/action admission."""
from copy import deepcopy

import pytest
from atme.store import contracts_v2 as contracts
from jsonschema import Draft202012Validator
from test_v2_composition_native import native_documents
from test_v2_mask_contract import MASK_FIELDS, masked_documents
from v2_fixtures import digest, visual_plan_v2


def aperture_plan_documents(kind, *, portrait=False, bound=True):
    layout, timeline, ids = native_documents(kind, portrait=portrait)
    if not bound:
        layout["objects"][0].pop("composition_binding")
    plan = visual_plan_v2()
    plan.update(assets=[], output_profile=deepcopy(layout["output_profile"]),
                boards=deepcopy(layout["boards"]), actions=[deepcopy(row["action"]) for row in timeline["actions"]],
                coverage=deepcopy(timeline["coverage"]), fallbacks=deepcopy(timeline["fallbacks"]))
    plan["beats"] = plan["beats"][:1]
    plan["conclusion_beat_id"] = plan["opening_beat_id"]
    fields = set(contracts.SemanticStandardObjectSpec.model_fields) | set(contracts.SemanticMaskObjectSpec.model_fields)
    # Explicitly authored even before the missing Mask contract exists.
    fields.add("child_ids")
    plan["objects"] = [{key: deepcopy(value) for key, value in obj.items()
                        if key in fields and (key != "clip_id" or value is not None)}
                       for obj in layout["objects"]]
    if bound:
        plan["objects"][0]["object_type"] = "instance"
    beat = plan["beats"][0]
    beat.update(object_ids=list(ids.values()), action_ids=[row["action_id"] for row in plan["actions"]],
                fallback_ids=["fallback-1"], coverage_ids=["coverage-1"])
    beat["attention"].update(primary_targets=[ids["art"]], secondary_context=[])
    beat["camera_intent"]["target_ids"] = [ids["art"]]
    layout["plan_sha256"] = digest(plan)
    timeline.update(plan_sha256=digest(plan), layout_sha256=digest(layout))
    return plan, layout, timeline, ids


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("kind", ["clip", "mask"])
@pytest.mark.parametrize("bound", [False, True])
def test_explicit_semantic_aperture_membership_matches_real_initial_layout(kind, portrait, bound):
    plan, layout, timeline, ids = aperture_plan_documents(kind, portrait=portrait, bound=bound)
    before = deepcopy((plan, layout, timeline))
    contracts.validate_plan_layout(plan, layout)
    parsed = contracts.VisualPlanV2.model_validate(plan)
    aperture = next(obj for obj in parsed.objects if obj.object_id == ids["aperture"])
    assert aperture.child_ids == [ids["art"]]
    Draft202012Validator(contracts.VisualPlanV2.model_json_schema()).validate(plan)
    contracts.validate_resolved_structure(parsed, contracts.ExecutableLayoutV2.model_validate(layout),
        contracts.ResolvedVisualTimelineV2.model_validate(timeline), timeline["duration_ms"])
    assert (plan, layout, timeline) == before


@pytest.mark.parametrize("kind", ["clip", "mask"])
@pytest.mark.parametrize("fault", ["empty", "duplicate", "self", "blank", "unknown", "cross_board", "two_parents", "cycle"])
def test_explicit_membership_rejects_bad_inventory_or_ownership_at_its_own_boundary(kind, fault):
    plan, _layout, _timeline, ids = aperture_plan_documents(kind, bound=False)
    contracts.VisualPlanV2.model_validate(plan)  # A missing positive contract is not negative evidence.
    root, art, aperture = plan["objects"][:3]
    if fault == "empty":
        aperture["child_ids"] = []
    elif fault == "duplicate":
        aperture["child_ids"].append(ids["art"])
    elif fault == "self":
        aperture["child_ids"] = [ids["aperture"]]
    elif fault == "blank":
        aperture["child_ids"] = [" "]
    elif fault == "unknown":
        aperture["child_ids"] = ["absent"]
    elif fault == "cross_board":
        art["board_id"] = "elsewhere"
    elif fault == "two_parents":
        root["child_ids"].append(ids["art"])
    else:
        aperture["child_ids"] = [ids["root"]]
    with pytest.raises(ValueError):
        contracts.VisualPlanV2.model_validate(plan)


@pytest.mark.parametrize("kind", ["clip", "mask"])
@pytest.mark.parametrize("value", [[], ["duplicate", "duplicate"]])
def test_schema_rejects_empty_or_duplicate_authored_children(kind, value):
    plan, _layout, _timeline, _ids = aperture_plan_documents(kind, bound=False)
    validator = Draft202012Validator(contracts.VisualPlanV2.model_json_schema())
    validator.validate(plan)
    plan["objects"][2]["child_ids"] = value
    assert list(validator.iter_errors(plan))


@pytest.mark.parametrize("fault", ["inside_content", "not_sibling", "hidden", "not_geometry", "foreign_beat", "asset"])
def test_explicit_semantic_mask_source_remains_a_dedicated_visible_geometry_sibling(fault):
    plan, _layout, _timeline, ids = aperture_plan_documents("mask", bound=False)
    contracts.VisualPlanV2.model_validate(plan)
    root, _art, aperture, source = plan["objects"]
    if fault == "inside_content":
        root["child_ids"].remove(ids["source"])
        aperture["child_ids"].append(ids["source"])
    elif fault == "not_sibling":
        root["child_ids"].remove(ids["source"])
    elif fault == "hidden":
        source["initial_state"] = "hidden"
    elif fault == "not_geometry":
        source["object_type"] = "icon"
    elif fault == "foreign_beat":
        source["beat_id"] = "foreign-beat"
    else:
        plan["assets"] = visual_plan_v2()["assets"]
        source["asset_id"] = plan["assets"][0]["asset_id"]
    with pytest.raises(ValueError, match="mask.*source"):
        contracts.VisualPlanV2.model_validate(plan)


def test_explicit_semantic_mask_geometry_has_unique_mask_ownership():
    plan, _layout, _timeline, ids = aperture_plan_documents("mask", bound=False)
    contracts.VisualPlanV2.model_validate(plan)
    second, content = deepcopy(plan["objects"][2]), deepcopy(plan["objects"][1])
    content.update(object_id="other-content", object_type="ellipse")
    content.pop("registry_binding")
    second.update(object_id="other-mask", child_ids=["other-content"])
    plan["objects"].extend([second, content])
    plan["objects"][0]["child_ids"].append("other-mask")
    for inventory in (plan["boards"][0]["object_ids"], plan["beats"][0]["object_ids"]):
        inventory.extend(["other-mask", "other-content"])
    assert second["mask_source_object_id"] == ids["source"]
    with pytest.raises(ValueError, match="exactly one mask"):
        contracts.VisualPlanV2.model_validate(plan)


@pytest.mark.parametrize("kind", ["clip", "mask"])
def test_membership_is_not_allowed_on_unrelated_semantic_leaves(kind):
    plan, _layout, _timeline, ids = aperture_plan_documents(kind, bound=False)
    contracts.VisualPlanV2.model_validate(plan)
    plan["objects"][1]["child_ids"] = [ids["aperture"]]
    with pytest.raises(ValueError, match="semantic child_ids"):
        contracts.VisualPlanV2.model_validate(plan)


def test_legacy_mask_plan_retains_exact_prior_dump_and_hash_when_membership_is_absent():
    plan = masked_documents()[0]
    parsed = contracts.VisualPlanV2.model_validate(plan).model_dump(mode="json")
    assert "child_ids" not in parsed["objects"][3]
    assert digest(parsed) == "fdb6633a9a69ea87c09624b86007a43baeac2d2cd2bd361074792ac031740bbc"
    raw = deepcopy(parsed["objects"][3])
    for field in MASK_FIELDS:
        raw.pop(field)
    legacy = contracts.SemanticMaskObjectSpec.model_validate(raw).model_dump(mode="json")
    assert "child_ids" not in legacy
    assert all(legacy[field] is None for field in MASK_FIELDS)
