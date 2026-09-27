"""A mask must declare a dedicated, static geometry source before execution."""

from __future__ import annotations

from copy import deepcopy

import pytest
from atme.render.v2_state import V2FrameError, evaluate_frame
from atme.store.contracts_v2 import (
    ExecutableLayoutV2,
    VisualPlanV2,
    validate_plan_layout,
)
from conftest import load_schema
from jsonschema import Draft202012Validator
from pydantic import ValidationError
from test_v2_connector_svg import connector_documents
from test_v2_group_hierarchy import grouped_documents
from v2_fixtures import digest, visual_plan_v2

MASK_FIELDS = {
    "mask_mode": "alpha", "mask_source_object_id": "mask-source",
    "mask_coordinate_space": "parent_local", "invert": False, "feather_px": 0,
}


def masked_documents():
    plan = visual_plan_v2()
    layout, timeline = grouped_documents()
    plan["objects"][2]["object_type"] = "ellipse"
    plan["objects"][2]["asset_id"] = None
    mask = layout["objects"][3]
    mask["object_type"] = "mask"
    mask.update(MASK_FIELDS)
    source = deepcopy(layout["objects"][0])
    source.update({"object_id": "mask-source", "parent_id": None,
                   "initial_state": "visible", "visible": True,
                   "description": "Dedicated alpha geometry"})
    layout["objects"].append(source)
    layout["boards"][0]["object_ids"].append("mask-source")
    layout["boards"][0]["density_limit"] = 6
    plan["objects"].extend([
        {"object_id": "object-group", "object_type": "mask", "board_id": "board-main",
         "beat_id": "beat-001", "semantic_role": mask["semantic_role"],
         "description": mask["description"], "asset_id": None,
         "initial_state": "visible", "coverage_ids": ["coverage-1"], **MASK_FIELDS},
        {"object_id": "mask-source", "object_type": "rounded_rectangle",
         "board_id": "board-main", "beat_id": "beat-001",
         "semantic_role": source["semantic_role"], "description": source["description"],
         "asset_id": None, "initial_state": "visible", "coverage_ids": ["coverage-1"]},
    ])
    plan["beats"][0]["object_ids"].extend(["object-group", "mask-source"])
    plan["boards"][0]["object_ids"].extend(["object-group", "mask-source"])
    plan["boards"][0]["density_limit"] = 6
    timeline["initial_object_states"].append(
        {"object_id": "mask-source", "state": "visible", "state_version": 1,
         "visible": True})
    timeline["layout_sha256"] = digest(layout)
    return plan, layout, timeline


def test_explicit_static_alpha_mask_passes_plan_layout_and_schema_but_not_renderer():
    plan, layout, timeline = masked_documents()
    Draft202012Validator(load_schema("visual-plan-v2")).validate(plan)
    Draft202012Validator(load_schema("executable-layout-v2")).validate(layout)
    parsed_plan = VisualPlanV2.model_validate(plan)
    parsed_layout = ExecutableLayoutV2.model_validate(layout)
    dumped_plan = parsed_plan.model_dump(mode="json")
    dumped_layout = parsed_layout.model_dump(mode="json")
    Draft202012Validator(load_schema("visual-plan-v2")).validate(dumped_plan)
    Draft202012Validator(load_schema("executable-layout-v2")).validate(dumped_layout)
    VisualPlanV2.model_validate(dumped_plan)
    ExecutableLayoutV2.model_validate(dumped_layout)
    validate_plan_layout(plan, layout)
    with pytest.raises(V2FrameError, match="no composition semantics"):
        evaluate_frame(layout, timeline, 100)


def test_mixed_null_and_explicit_mask_fields_are_rejected():
    plan, layout, _ = masked_documents()
    plan["objects"][3]["mask_mode"] = None
    layout["objects"][3]["mask_mode"] = None
    assert list(Draft202012Validator(load_schema("visual-plan-v2")).iter_errors(plan))
    assert list(Draft202012Validator(load_schema("executable-layout-v2")).iter_errors(layout))
    with pytest.raises(ValidationError):
        VisualPlanV2.model_validate(plan)
    with pytest.raises(ValidationError):
        ExecutableLayoutV2.model_validate(layout)


@pytest.mark.parametrize("field,value", [
    ("mask_mode", "luminance"), ("mask_coordinate_space", "world"),
    ("invert", True), ("feather_px", 1),
])
def test_unsupported_mask_policies_fail_schema_and_model(field, value):
    plan, layout, _ = masked_documents()
    plan["objects"][3][field] = value
    layout["objects"][3][field] = value
    assert list(Draft202012Validator(load_schema("visual-plan-v2")).iter_errors(plan))
    with pytest.raises(ValidationError):
        VisualPlanV2.model_validate(plan)
    assert list(Draft202012Validator(load_schema("executable-layout-v2")).iter_errors(layout))
    with pytest.raises(ValidationError):
        ExecutableLayoutV2.model_validate(layout)


def test_mask_requires_explicit_source_and_policy_in_both_contracts():
    plan, layout, _ = masked_documents()
    del plan["objects"][3]["mask_source_object_id"]
    del layout["objects"][3]["mask_source_object_id"]
    assert list(Draft202012Validator(load_schema("visual-plan-v2")).iter_errors(plan))
    assert list(Draft202012Validator(load_schema("executable-layout-v2")).iter_errors(layout))
    with pytest.raises(ValidationError):
        VisualPlanV2.model_validate(plan)
    with pytest.raises(ValidationError):
        ExecutableLayoutV2.model_validate(layout)


def test_prior_v2_mask_documents_still_load_but_cannot_render():
    plan, layout, timeline = masked_documents()
    for field in MASK_FIELDS:
        del plan["objects"][3][field]
        del layout["objects"][3][field]
    plan["objects"].pop(4)
    layout["objects"].pop(4)
    plan["beats"][0]["object_ids"].remove("mask-source")
    plan["boards"][0]["object_ids"].remove("mask-source")
    layout["boards"][0]["object_ids"].remove("mask-source")
    timeline["initial_object_states"].pop()
    Draft202012Validator(load_schema("visual-plan-v2")).validate(plan)
    Draft202012Validator(load_schema("executable-layout-v2")).validate(layout)
    dumped_plan = VisualPlanV2.model_validate(plan).model_dump(mode="json")
    dumped_layout = ExecutableLayoutV2.model_validate(layout).model_dump(mode="json")
    Draft202012Validator(load_schema("visual-plan-v2")).validate(dumped_plan)
    Draft202012Validator(load_schema("executable-layout-v2")).validate(dumped_layout)
    VisualPlanV2.model_validate(dumped_plan)
    ExecutableLayoutV2.model_validate(dumped_layout)
    validate_plan_layout(plan, layout)
    timeline["layout_sha256"] = digest(layout)
    with pytest.raises(V2FrameError, match="no composition semantics"):
        evaluate_frame(layout, timeline, 100)


@pytest.mark.parametrize("mutate", [
    lambda p, l: l["objects"][4].update(parent_id="object-group"),
    lambda p, l: l["objects"][4].update(visible=False),
    lambda p, l: l["objects"][3].update(mask_source_object_id="object-group"),
    lambda p, l: l["objects"][3].update(mask_source_object_id="object-evidence"),
    lambda p, l: l["objects"][4].update(opacity=0.5),
    lambda p, l: l["objects"][4].update(initial_state="hidden"),
    lambda p, l: l["objects"][4].update(asset_id="asset-evidence"),
    lambda p, l: l["objects"][4].update(clip_id="object-group"),
])
def test_mask_source_is_dedicated_static_same_parent_geometry(mutate):
    plan, layout, _ = masked_documents()
    mutate(plan, layout)
    with pytest.raises(ValidationError):
        ExecutableLayoutV2.model_validate(layout)


def test_mask_plan_and_layout_semantics_cannot_diverge():
    plan, layout, _ = masked_documents()
    plan["objects"][3]["mask_source_object_id"] = "object-system"
    with pytest.raises(ValueError):
        validate_plan_layout(plan, layout)


def test_mask_source_has_unique_ownership_and_cannot_receive_actions():
    plan, layout, _ = masked_documents()
    duplicate = deepcopy(plan["objects"][3])
    duplicate["object_id"] = "second-mask"
    plan["objects"].append(duplicate)
    plan["beats"][0]["object_ids"].append("second-mask")
    plan["boards"][0]["object_ids"].append("second-mask")
    plan["boards"][0]["density_limit"] = 7
    with pytest.raises(ValidationError, match="exactly one mask"):
        VisualPlanV2.model_validate(plan)
    plan, layout, _ = masked_documents()
    plan["actions"][0]["target_ids"] = ["mask-source"]
    with pytest.raises(ValidationError, match="cannot animate a mask source"):
        VisualPlanV2.model_validate(plan)
    second = deepcopy(layout["objects"][3])
    second["object_id"] = "second-mask"
    layout["objects"].append(second)
    layout["boards"][0]["object_ids"].append("second-mask")
    layout["boards"][0]["density_limit"] = 7
    with pytest.raises(ValidationError, match="exactly one mask"):
        ExecutableLayoutV2.model_validate(layout)


@pytest.mark.parametrize("shape", ["rectangle", "rounded_rectangle", "ellipse", "polygon"])
def test_four_static_geometry_source_kinds_are_authorized(shape):
    plan, layout, _ = masked_documents()
    plan["objects"][4]["object_type"] = shape
    source = layout["objects"][4]
    source["object_type"] = shape
    if shape != "rounded_rectangle":
        source["geometry"]["corner_radius"] = None
    if shape == "polygon":
        source["geometry"]["points"] = [
            {"x": 80, "y": 160}, {"x": 560, "y": 160}, {"x": 320, "y": 500},
        ]
    VisualPlanV2.model_validate(plan)
    ExecutableLayoutV2.model_validate(layout)
    validate_plan_layout(plan, layout)


@pytest.mark.parametrize("change", [
    lambda p: p["objects"][4].update(board_id="other-board"),
    lambda p: p["objects"][4].update(beat_id="beat-002"),
    lambda p: p["objects"][4].update(initial_state="hidden"),
    lambda p: p["objects"][4].update(object_type="evidence"),
])
def test_plan_rejects_wrong_mask_source_authority(change):
    plan, _, _ = masked_documents()
    change(plan)
    with pytest.raises(ValidationError):
        VisualPlanV2.model_validate(plan)


def test_connector_cannot_bind_to_mask_only_geometry():
    _, layout, _ = masked_documents()
    connector_layout, _ = connector_documents()
    arrow = connector_layout["objects"][3]
    arrow["source_object_id"] = "mask-source"
    layout["objects"].append(arrow)
    layout["boards"][0]["object_ids"].append("object-arrow")
    layout["boards"][0]["density_limit"] = 7
    with pytest.raises(ValidationError, match="cannot bind to a mask source"):
        ExecutableLayoutV2.model_validate(layout)


def test_evidence_mask_must_reference_same_board_mask():
    plan, _, _ = masked_documents()
    plan["beats"][1]["evidence"]["mask_object_id"] = "object-system"
    with pytest.raises(ValidationError, match="same-board mask"):
        VisualPlanV2.model_validate(plan)


@pytest.mark.parametrize("place", [
    lambda p: p["beats"][0]["attention"]["secondary_context"].append("mask-source"),
    lambda p: p["beats"][0]["camera_intent"]["target_ids"].append("mask-source"),
    lambda p: p["beats"][0]["continuity"]["keep"].append("mask-source"),
    lambda p: p["beats"][0]["continuity"]["replacements"].update(
        {"object-system": "mask-source"}),
    lambda p: p["beats"][1]["evidence"].update(annotation_target_id="mask-source"),
])
def test_mask_only_source_cannot_be_directed_as_visible_content(place):
    plan, _, _ = masked_documents()
    place(plan)
    with pytest.raises(ValidationError, match="mask source"):
        VisualPlanV2.model_validate(plan)
