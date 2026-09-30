"""Forensic evidence intent must survive every v2 execution boundary."""

from __future__ import annotations

from copy import deepcopy

import pytest
from atme.project_service import ProjectError
from atme.render.v2_state import UnsupportedVisualAction, V2FrameError, evaluate_frame
from atme.render.v2_svg import compose_svg_frame
from atme.store.contracts_v2 import (
    ExecutableLayoutV2,
    ResolvedVisualTimelineV2,
    VisualPlanV2,
    validate_plan_evidence_completeness,
    validate_plan_layout,
)
from pydantic import ValidationError
from test_visual_contracts_v2 import _store_v2_plan
from v2_fixtures import (
    digest,
    executable_layout_v2,
    resolved_timeline_v2,
    visual_plan_v2,
)


def test_exact_evidence_treatment_is_preserved_and_drives_frame_state():
    plan = visual_plan_v2()
    layout = executable_layout_v2(plan)
    timeline = resolved_timeline_v2(plan, layout)
    assert VisualPlanV2.model_validate(plan).beats[1].evidence is not None
    assert ExecutableLayoutV2.model_validate(layout).evidence_treatments
    assert ResolvedVisualTimelineV2.model_validate(timeline).evidence_treatments
    validate_plan_layout(plan, layout)
    before = evaluate_frame(layout, timeline, 3999).object("object-evidence")
    during = evaluate_frame(layout, timeline, 4450).object("object-evidence")
    after = evaluate_frame(layout, timeline, 4900).object("object-evidence")
    assert not before.visible
    assert during.visible and 0 < during.opacity < 1
    assert after.visible and after.state == "evidence_visible" and after.opacity == 1
    assert evaluate_frame(layout, timeline, 4000).object("object-evidence").opacity == 0
    assert evaluate_frame(layout, timeline, 7000).object("object-evidence") == after


def test_layout_cannot_omit_or_rewrite_plan_evidence():
    plan = visual_plan_v2()
    layout = executable_layout_v2(plan)
    missing = deepcopy(layout)
    missing["evidence_treatments"] = []
    ExecutableLayoutV2.model_validate(missing)  # old 2.0.0 remains loadable
    with pytest.raises(ValueError, match="preserve every evidence treatment"):
        validate_plan_layout(plan, missing)
    modified = deepcopy(layout)
    modified["evidence_treatments"][0]["intent"]["source_label"] = "Invented source"
    with pytest.raises(ValueError, match="preserve every evidence treatment"):
        validate_plan_layout(plan, modified)


def test_timeline_cannot_change_evidence_treatment_or_asset_snapshot():
    plan = visual_plan_v2()
    layout = executable_layout_v2(plan)
    timeline = resolved_timeline_v2(plan, layout)
    changed = deepcopy(timeline)
    changed["evidence_treatments"][0]["intent"]["readable_hold_intent_ms"] = 3000
    with pytest.raises(V2FrameError, match="same composition"):
        evaluate_frame(layout, changed, 4500)
    changed = deepcopy(timeline)
    changed["resolved_assets"][0]["kind"] = "image"
    with pytest.raises(ValidationError, match="resolved evidence changes"):
        ResolvedVisualTimelineV2.model_validate(changed)
    changed = deepcopy(timeline)
    changed["resolved_assets"][0]["checksum_sha256"] = "b" * 64
    with pytest.raises(ValidationError, match="resolved evidence changes"):
        ResolvedVisualTimelineV2.model_validate(changed)


@pytest.mark.parametrize("mutate,problem", [
    (lambda p: p["assets"][0].update(kind="image"), "supporting image"),
    (lambda p: p["beats"][1]["evidence"].update(source_label=""), "source_label"),
    (lambda p: p["beats"][1]["evidence"].update(source_label="   "), "source label"),
    (lambda p: p["beats"][1]["evidence"]["crop"].update(x=-1), "crop"),
    (lambda p: p["beats"][1]["evidence"]["crop"].update(x=0.5), "whole source pixels"),
    (lambda p: p["beats"][1]["evidence"]["focus_region"].update(x=880), "focus"),
])
def test_evidence_rejects_substitution_missing_attribution_and_bad_geometry(mutate, problem):
    plan = visual_plan_v2()
    mutate(plan)
    if problem in {"supporting image", "source_label", "source label"}:
        with pytest.raises(ValidationError, match=problem):
            VisualPlanV2.model_validate(plan)
    else:
        layout = executable_layout_v2(plan)
        with pytest.raises(ValueError, match=problem):
            validate_plan_layout(plan, layout)


def test_old_evidence_documents_remain_loadable_but_fail_closed():
    plan = visual_plan_v2()
    layout = executable_layout_v2(plan)
    timeline = resolved_timeline_v2(plan, layout)
    layout.pop("evidence_treatments")
    timeline.pop("evidence_treatments")
    timeline["layout_sha256"] = digest(layout)
    ExecutableLayoutV2.model_validate(layout)
    ResolvedVisualTimelineV2.model_validate(timeline)
    with pytest.raises(UnsupportedVisualAction, match="insert_evidence"):
        evaluate_frame(layout, timeline, 4500)
    with pytest.raises(UnsupportedVisualAction, match="insert_evidence"):
        compose_svg_frame(layout, timeline, 4500)


@pytest.mark.parametrize("mutate", [
    lambda p: p["actions"][2].pop("target_object_id"),
    lambda p: p["actions"][2].update(target_object_id="object-label"),
    lambda p: p["actions"][2].update(post_state="visible"),
    lambda p: p["actions"][2].update(expected_state="visible"),
])
def test_new_evidence_plan_requires_exact_target_and_state(mutate):
    plan = visual_plan_v2()
    mutate(plan)
    with pytest.raises(ValueError, match="bind its hidden object"):
        validate_plan_evidence_completeness(plan)


@pytest.mark.parametrize("mutate,problem", [
    (lambda p: p["beats"][1]["evidence"].update(provenance_verified=False), "verified"),
    (lambda p: p["beats"][1]["evidence"].update(checksum_verified=False), "verified"),
    (lambda p: p["assets"][0].update(allowed_transformations=["scale", "annotate", "color_treatment"]), "permissions"),
    (lambda p: p["assets"][0].update(allowed_transformations=["crop", "scale", "color_treatment"]), "permissions"),
    (lambda p: p["assets"][0].update(allowed_transformations=["crop", "scale", "annotate"]), "permissions"),
    (lambda p: p["beats"][1]["evidence"].update(annotation_omission_reason="Not needed"), "omission"),
    (lambda p: p["beats"][1]["evidence"].update(annotation=None), "omission"),
])
def test_plan_rejects_unverified_unpermitted_or_ambiguous_evidence(mutate, problem):
    plan = visual_plan_v2()
    mutate(plan)
    with pytest.raises(ValidationError, match=problem):
        VisualPlanV2.model_validate(plan)


@pytest.mark.parametrize("key,value", [
    ("width", 899), ("height", 499), ("media_type", "image/jpeg"),
    ("byte_length", None), ("orientation", None),
    ("allowed_transformations", ["crop", "scale"]),
])
def test_resolved_evidence_requires_attested_raster_metadata(key, value):
    timeline = resolved_timeline_v2()
    timeline["resolved_assets"][0][key] = value
    with pytest.raises(ValidationError, match="resolved evidence changes"):
        ResolvedVisualTimelineV2.model_validate(timeline)


def test_evidence_readable_hold_must_fit_destination_board_activation():
    plan = visual_plan_v2()
    layout = executable_layout_v2(plan)
    layout["activations"][0]["end_ms"] = 6500
    timeline = resolved_timeline_v2(plan, layout)
    with pytest.raises(V2FrameError, match="readable hold outlasts"):
        evaluate_frame(layout, timeline, 4500)


def test_evidence_insert_and_hold_reject_other_visual_actions_on_same_board():
    plan = visual_plan_v2()
    layout = executable_layout_v2(plan)
    timeline = resolved_timeline_v2(plan, layout)
    timeline["actions"][1]["end_ms"] = 4100
    with pytest.raises(V2FrameError, match="uninterrupted readable insert and hold"):
        evaluate_frame(layout, timeline, 4500)


def test_evidence_insert_is_random_seek_deterministic():
    layout = executable_layout_v2()
    timeline = resolved_timeline_v2(layout=layout)
    first = evaluate_frame(layout, timeline, 4450)
    evaluate_frame(layout, timeline, 7000)
    evaluate_frame(layout, timeline, 0)
    assert evaluate_frame(layout, timeline, 4450) == first


def test_legacy_unsnapshotted_evidence_plan_loads_but_cannot_be_newly_written():
    plan = visual_plan_v2()
    for field in ("managed_ref", "width", "height"):
        plan["assets"][0][field] = None
    VisualPlanV2.model_validate(plan)
    with pytest.raises(ValueError, match="immutable source snapshot"):
        validate_plan_evidence_completeness(plan)


@pytest.mark.parametrize("field,value", [
    ("fabrication_prohibited", False), ("originality_status", "unresolved"),
    ("originality_status", "transformed"),
])
def test_evidence_provenance_rejects_fabricated_or_non_reference_sources(field, value):
    plan = visual_plan_v2()
    plan["assets"][0]["provenance"][field] = value
    with pytest.raises(ValidationError, match="prohibit fabrication and remain reference-only"):
        VisualPlanV2.model_validate(plan)


def test_evidence_treatment_identity_is_unique():
    layout = executable_layout_v2()
    duplicate = deepcopy(layout["evidence_treatments"][0])
    duplicate["object_id"] = "object-other"
    layout["evidence_treatments"].append(duplicate)
    with pytest.raises(ValidationError, match="beat_id values must be unique"):
        ExecutableLayoutV2.model_validate(layout)


@pytest.mark.parametrize("orphan", ["both", "object", "action"])
def test_project_write_rejects_missing_evidence_intent_and_orphans(tmp_path, orphan):
    service, project, plan = _store_v2_plan(tmp_path)
    invalid = deepcopy(plan)
    invalid["project_revision"] = project["revision"]
    invalid["beats"][1]["evidence"] = None
    if orphan == "object":
        invalid["actions"] = [action for action in invalid["actions"]
                              if action["verb"] != "insert_evidence"]
        invalid["beats"][1]["action_ids"] = []
        invalid["coverage"][2]["action_ids"] = []
    elif orphan == "action":
        invalid["objects"] = [obj for obj in invalid["objects"]
                              if obj["object_type"] != "evidence"]
        invalid["boards"][0]["object_ids"].remove("object-evidence")
        invalid["beats"][1]["object_ids"].remove("object-evidence")
        invalid["beats"][1]["attention"]["primary_targets"].remove("object-evidence")
        invalid["beats"][1]["camera_intent"]["target_ids"].remove("object-evidence")
    with pytest.raises(ProjectError) as failure:
        service.write(project["project_id"], "storyboard", invalid, project["revision"])
    assert failure.value.code == "invalid_artifact"
