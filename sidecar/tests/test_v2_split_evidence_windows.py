"""Resolved Task8 treatment/time authority; not captured-history/native proof."""

from copy import deepcopy

import pytest
from test_v2_split_evidence_contract import evidence_completion_document
from test_v2_split_evidence_layout import evidence_layout_documents
from v2_fixtures import digest, resolved_timeline_v2

from atme.store.contracts_v2 import (
    EvidenceTreatment,
    ExecutableLayoutV2,
    ResolvedVisualTimelineV2,
    VisualPlanV2,
    validate_resolved_structure,
)


def rehash_window_receipt(item):
    receipt = item["split_completion_receipt"]
    receipt["evidence_windows"] = deepcopy(item["split_evidence_windows"])
    receipt["completion_sha256"] = digest({key: value for key, value in receipt.items()
                                           if key != "completion_sha256"})


def evidence_window_documents(*, movement="before", ordinary=False, portrait=False):
    plan, layout = evidence_layout_documents(ordinary=ordinary, same_beat=ordinary, portrait=portrait)
    item = evidence_completion_document(two_results=True)
    action = deepcopy(plan["actions"][0])
    policy = action["split_policy"]
    movement_end = {"before": 1400, "after": 1800, "absent": 1600}[movement]
    for result in policy["results"]:
        if movement == "after":
            result["movement"]["phase"]["end_tick"] = 8000
        elif movement == "absent":
            result["movement"] = None
    plan["actions"][0] = deepcopy(action)
    item["action"] = action
    item["split_completion_receipt"]["policy_sha256"] = digest(policy)
    treatments = [EvidenceTreatment.model_validate(row).model_dump(mode="json")
                  for row in layout["evidence_treatments"]]
    layout["evidence_treatments"] = deepcopy(treatments)
    hold_start = 1800 if movement == "after" else 1600
    for window, treatment in zip(item["split_evidence_windows"], treatments[:2], strict=True):
        # Hand-derived: start1000/end2000, construction ticks0..6000;
        # movement0..4000/8000, or construction-completion sentinel if absent.
        window.update(treatment_sha256=digest(treatment), construction_complete_ms=1600,
                      movement_complete_ms=movement_end, readable_hold_start_ms=hold_start,
                      readable_hold_end_ms=hold_start + 2500)
    rehash_window_receipt(item)
    layout["plan_sha256"] = digest(plan)
    clock = resolved_timeline_v2()  # Ordinary source metadata; no Split/window compiler helper.
    clock.update(actions=[item], evidence_treatments=deepcopy(treatments),
                 plan_id=plan["plan_id"], plan_sha256=digest(plan), layout_sha256=digest(layout),
                 output_profile=deepcopy(plan["output_profile"]), coverage=deepcopy(plan["coverage"]),
                 fallbacks=deepcopy(plan["fallbacks"]), beat_anchors=[{"beat_id": "beat-001", "start_ms": 0}],
                 initial_object_states=[{"object_id": obj["object_id"], "state": obj["initial_state"],
                                         "state_version": 1, "visible": obj["visible"]} for obj in layout["objects"]])
    if ordinary:
        ordinary_item = deepcopy(resolved_timeline_v2()["actions"][2])
        ordinary_item["action"] = deepcopy(plan["actions"][1])
        clock["actions"].append(ordinary_item)
    return plan, layout, clock


@pytest.mark.parametrize("ordinary,portrait", [(False, False), (True, False), (False, True), (True, True)])
@pytest.mark.parametrize("stage", ["semantic", "layout", "resolved"])
def test_published_schema_carries_actual_split_evidence_authority_and_windows(ordinary, portrait, stage):
    from conftest import load_schema
    from jsonschema import Draft202012Validator

    plan, layout, clock = evidence_window_documents(ordinary=ordinary, portrait=portrait)
    document, model, name = {
        "semantic": (plan, VisualPlanV2, "visual-plan-v2"),
        "layout": (layout, ExecutableLayoutV2, "executable-layout-v2"),
        "resolved": (clock, ResolvedVisualTimelineV2, "resolved-visual-timeline-v2"),
    }[stage]
    model.model_validate(document)
    schema = load_schema(name)
    Draft202012Validator.check_schema(schema)
    failures = [(list(error.absolute_path), error.validator)
                for error in Draft202012Validator(schema).iter_errors(document)]
    assert not failures


@pytest.mark.parametrize("movement", ["before", "after", "absent"])
@pytest.mark.parametrize("ordinary,portrait", [(False, False), (True, False), (False, True), (True, True)])
def test_resolved_split_windows_derive_exact_treatment_and_parallel_phase_boundaries(movement, ordinary, portrait):
    plan, layout, clock = evidence_window_documents(movement=movement, ordinary=ordinary, portrait=portrait)
    before = deepcopy(clock)
    parsed = ResolvedVisualTimelineV2.model_validate(clock)
    validate_resolved_structure(VisualPlanV2.model_validate(plan), ExecutableLayoutV2.model_validate(layout),
                                parsed, 10000)
    assert clock == before
    expected = (1600, 1800, 1800, 4300) if movement == "after" else (
        1600, 1400 if movement == "before" else 1600, 1600, 4100)
    assert [(window.construction_complete_ms, window.movement_complete_ms,
             window.readable_hold_start_ms, window.readable_hold_end_ms)
            for window in parsed.actions[0].split_evidence_windows] == [expected, expected]
    assert [row.action_id for row in parsed.evidence_treatments] == (
        ["split-1", "split-1", "action-3"] if ordinary else ["split-1", "split-1"])


@pytest.mark.parametrize("fault", ["treatment_hash", "construction_time", "movement_time", "late_hold",
    "short_hold", "long_hold", "false_treatment", "false_permissions", "wrong_beat", "wrong_asset_revision",
    "wrong_asset_ref", "missing_treatment", "all_missing", "orphan_treatment", "duplicate_ordinary_writer",
    "hold_outlasts_timeline"])
def test_resolved_split_rederives_authority_not_self_attested_rehashed_windows(fault):
    _plan, _layout, clock = evidence_window_documents(ordinary=fault == "duplicate_ordinary_writer")
    item = clock["actions"][0]
    window = item["split_evidence_windows"][0]
    treatment = clock["evidence_treatments"][0]
    if fault == "treatment_hash":
        window["treatment_sha256"] = "d" * 64
    elif fault == "construction_time":
        for field in ("construction_complete_ms", "readable_hold_start_ms", "readable_hold_end_ms"):
            window[field] += 1
    elif fault == "movement_time":
        window["movement_complete_ms"] += 1
    elif fault == "late_hold":
        window["readable_hold_start_ms"] += 1
        window["readable_hold_end_ms"] += 1
    elif fault in {"short_hold", "long_hold"}:
        window["readable_hold_end_ms"] += -1 if fault == "short_hold" else 1
    elif fault == "false_treatment":
        treatment["intent"]["source_label"] = "Reauthored source"
    elif fault == "false_permissions":
        clock["resolved_assets"][0]["allowed_transformations"].reverse()
        for row in clock["evidence_treatments"]:
            row["allowed_transformations"].reverse()
    elif fault == "wrong_beat":
        treatment["beat_id"] = "not-owning-beat"
    elif fault == "wrong_asset_revision":
        for row in clock["evidence_treatments"]:
            row["asset_revision"] += 1
        clock["resolved_assets"][0]["revision"] += 1
    elif fault == "wrong_asset_ref":
        for row in clock["evidence_treatments"]:
            row["asset_managed_ref"] = "replacement.png"
    elif fault == "hold_outlasts_timeline":
        clock["duration_ms"] = 4000
    elif fault == "missing_treatment":
        clock["evidence_treatments"].pop(0)
    elif fault == "all_missing":
        clock["evidence_treatments"] = []
    else:
        extra = deepcopy(clock["evidence_treatments"][-1 if fault == "duplicate_ordinary_writer" else 0])
        extra["object_id"] = "unowned-evidence"
        extra["intent"].update(claim_id="unowned-claim", annotation_target_id="unowned-evidence")
        clock["evidence_treatments"].append(extra)
        clock["initial_object_states"].append(
            {"object_id": "unowned-evidence", "state": "hidden", "state_version": 1, "visible": False})
    if fault in {"false_treatment", "false_permissions", "wrong_beat", "wrong_asset_revision", "wrong_asset_ref"}:
        for row, bound_window in zip(clock["evidence_treatments"][:2], item["split_evidence_windows"], strict=True):
            bound_window["treatment_sha256"] = digest(row)
    rehash_window_receipt(item)
    diagnostic = "resolved evidence changes treatment, asset, action, or hold" if fault == "wrong_asset_ref" else None
    with pytest.raises(ValueError, match=diagnostic):
        ResolvedVisualTimelineV2.model_validate(clock)


@pytest.mark.parametrize("portrait", [False, True])
def test_foreign_origin_preserves_current_owner_but_cannot_rewrite_paired_provenance(portrait):
    plan, layout, clock = evidence_window_documents(portrait=portrait)
    asset = plan["assets"][0]
    origin = f"atme://projects/999/assets/{asset['asset_id']}"
    asset["managed_ref"] = origin
    clock["resolved_assets"][0]["managed_ref"] = origin
    for document in (layout, clock):
        for treatment in document["evidence_treatments"]:
            treatment["asset_managed_ref"] = origin
    item = clock["actions"][0]
    for treatment, window in zip(clock["evidence_treatments"], item["split_evidence_windows"], strict=True):
        window["treatment_sha256"] = digest(treatment)
    rehash_window_receipt(item)
    layout["plan_sha256"] = clock["plan_sha256"] = digest(plan)
    clock["layout_sha256"] = digest(layout)
    parsed_plan = VisualPlanV2.model_validate(plan)
    parsed_layout = ExecutableLayoutV2.model_validate(layout)
    parsed_clock = ResolvedVisualTimelineV2.model_validate(clock)
    pin = parsed_clock.actions[0].action.split_policy.source_basis.asset_pins[0]
    assert pin.resource_uri == f"atme://projects/{parsed_clock.project_id}/assets/{asset['asset_id']}"
    assert pin.resource_uri != origin
    assert parsed_clock.resolved_assets[0].managed_ref == origin
    assert all(row.asset_managed_ref == origin for row in parsed_clock.evidence_treatments)
    validate_resolved_structure(parsed_plan, parsed_layout, parsed_clock, 10000)

    replacement = f"atme://projects/998/assets/{asset['asset_id']}"
    clock["resolved_assets"][0]["managed_ref"] = replacement
    for treatment, window in zip(clock["evidence_treatments"], item["split_evidence_windows"], strict=True):
        treatment["asset_managed_ref"] = replacement
        window["treatment_sha256"] = digest(treatment)
    rehash_window_receipt(item)
    rewritten = ResolvedVisualTimelineV2.model_validate(clock)
    with pytest.raises(ValueError, match="resolved Split evidence must preserve exact plan and layout treatments"):
        validate_resolved_structure(parsed_plan, parsed_layout, rewritten, 10000)


@pytest.mark.parametrize("fault", ["hold_outlasts_activation", "split_crosses_activation", "borrow_later_activation",
                                     "layout_treatment_mismatch"])
def test_paired_split_window_requires_actual_uninterrupted_board_and_exact_layout_treatment(fault):
    plan, layout, clock = evidence_window_documents()
    if fault == "hold_outlasts_activation":
        layout["activations"][0]["end_ms"] = 4099
    elif fault == "split_crosses_activation":
        layout["activations"][0]["start_ms"] = 1001
    elif fault == "borrow_later_activation":
        layout["activations"][0]["end_ms"] = 2500
        layout["activations"].append({"activation_id": "later-return", "board_id": "board-main",
                                     "start_ms": 4000, "end_ms": 10000, "reason": "Later activation cannot lend a hold"})
    else:
        layout["evidence_treatments"][0]["intent"]["source_label"] = "Only layout changed"
    clock["layout_sha256"] = digest(layout)
    parsed_plan = VisualPlanV2.model_validate(plan)
    parsed_layout = ExecutableLayoutV2.model_validate(layout)
    parsed_clock = ResolvedVisualTimelineV2.model_validate(clock)
    with pytest.raises(ValueError):
        validate_resolved_structure(parsed_plan, parsed_layout, parsed_clock, 10000)


def test_paired_split_hold_may_end_exactly_at_half_open_board_boundary():
    plan, layout, clock = evidence_window_documents()
    layout["activations"][0]["end_ms"] = 4100
    clock["layout_sha256"] = digest(layout)
    validate_resolved_structure(VisualPlanV2.model_validate(plan), ExecutableLayoutV2.model_validate(layout),
                                ResolvedVisualTimelineV2.model_validate(clock), 10000)
