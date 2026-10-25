"""Authored annotation contracts and compatibility boundaries."""

from __future__ import annotations

from copy import deepcopy

import pytest
from conftest import load_schema
from jsonschema import Draft202012Validator
from pydantic import ValidationError
from test_v2_connector_svg import connector_documents
from test_v2_morph_action import semantic_plan
from test_v2_replace_action import documents
from v2_fixtures import digest

from atme.render.v2_state import UnsupportedVisualAction, evaluate_frame
from atme.store.contracts_v2 import (
    AnnotationPolicy,
    ResolvedVisualTimelineV2,
    TargetAction,
    VisualPlanV2,
    _action_object_references,
    _annotation_phase_windows,
    validate_plan_evidence_completeness,
    validate_plan_layout,
)


def annotation_documents():
    layout, timeline = documents()
    note = deepcopy(layout["objects"][1])
    note.update(object_id="annotation-note", text="A stable boundary", initial_state="hidden", visible=False,
                z_index=6, coverage_ids=["coverage-1"])
    note["geometry"]["bounds"] = {"x": 140, "y": 540, "width": 420, "height": 80}
    layout["objects"].append(note)
    layout["boards"][0]["object_ids"].append(note["object_id"])
    timeline["initial_object_states"].append({"object_id": note["object_id"], "state": "hidden",
                                               "state_version": 1, "visible": False})
    action = timeline["actions"][-1]["action"]
    action.pop("from_object_id")
    action.pop("to_object_id")
    action.update(verb="annotate", target_ids=["object-system"], annotation=None,
                  annotation_policy={"annotation_object_ids": [note["object_id"]], "leader_connector_id": None,
                                     "phases": [{"object_id": note["object_id"], "mode": "write", "weight": 1}],
                                     "readable_hold_ms": 1000, "retention": "retain"})
    timeline["layout_sha256"] = digest(layout)
    plan = deepcopy(semantic_plan(layout, timeline))
    plan["beats"][0]["object_ids"].append(note["object_id"])
    layout["plan_sha256"] = timeline["plan_sha256"] = digest(plan)
    timeline["layout_sha256"] = digest(layout)
    return plan, layout, timeline


def test_authored_annotation_round_trips_plan_layout_resolved_and_schema():
    plan, layout, timeline = annotation_documents()
    for name, document, model in (("visual-plan-v2", plan, VisualPlanV2),
                                  ("resolved-visual-timeline-v2", timeline, ResolvedVisualTimelineV2)):
        Draft202012Validator(load_schema(name)).validate(document)
        parsed = model.model_validate(document)
        reparsed = model.model_validate(parsed.model_dump(mode="json"))
        assert reparsed == parsed
    validate_plan_evidence_completeness(plan)
    validate_plan_layout(plan, layout)
    action = VisualPlanV2.model_validate(plan).actions[-1]
    assert _action_object_references(action) == ["object-system", "annotation-note"]
    frame = evaluate_frame(layout, timeline, 6500)
    assert frame.object("annotation-note").reveal_fraction == 0.5
    assert frame.object("object-system").state == "visible"


@pytest.mark.parametrize("change", [
    lambda p: p.update(annotation_object_ids=[]),
    lambda p: p["annotation_object_ids"].append("annotation-note"),
    lambda p: p["phases"].append(deepcopy(p["phases"][0])),
    lambda p: p["phases"][0].update(object_id="not-declared"),
    lambda p: p["phases"][0].update(weight=0),
    lambda p: p.update(readable_hold_ms=0),
    lambda p: p.update(retention="discard"),
    lambda p: p.update(leader_connector_id="annotation-note"),
])
def test_annotation_policy_rejects_missing_duplicate_ignored_or_unbounded_fields(change):
    policy = annotation_documents()[0]["actions"][-1]["annotation_policy"]
    change(policy)
    with pytest.raises(ValidationError):
        AnnotationPolicy.model_validate(policy)


@pytest.mark.parametrize("change", [
    lambda a: a.update(annotation="Invent a note"),
    lambda a: a.update(expected_state="hidden"),
    lambda a: a.update(post_state="annotated"),
    lambda a: a.update(easing="step"),
    lambda a: a.update(target_ids=["annotation-note"]),
    lambda a: a.update(target_ids=["object-system", "object-label"]),
    lambda a: a.update(verb="reveal"),
])
def test_annotation_action_rejects_unfaithful_semantics(change):
    action = annotation_documents()[0]["actions"][-1]
    change(action)
    with pytest.raises(ValidationError):
        TargetAction.model_validate(action)


@pytest.mark.parametrize("change", [
    lambda p: p["actions"][-1]["annotation_policy"]["phases"][0].update(mode="draw"),
    lambda p: p["objects"][-1].update(initial_state="visible"),
    lambda p: (p["objects"][2].update(object_type="evidence"),
               p["actions"][-1].update(target_ids=["object-evidence"])),
])
def test_new_plan_write_checks_authored_semantic_inventory(change):
    plan, _, _ = annotation_documents()
    change(plan)
    with pytest.raises(ValueError):
        validate_plan_evidence_completeness(plan)


def test_resolved_annotation_mutates_only_authored_notes_not_its_visible_target():
    _, _, timeline = annotation_documents()
    later = deepcopy(timeline["actions"][0])
    later["action"].update(action_id="target-after", verb="highlight", expected_state="visible",
                           post_state="emphasized", trigger={"kind": "absolute", "at_ms": 8500})
    later.update(start_ms=8500, end_ms=9000)
    later["resolved_trigger"].update(source=later["action"]["trigger"], alignment_anchor_ms=8500,
                                     resolved_at_ms=8500, matched_text=None, matched_occurrence=None)
    timeline["actions"].append(later)
    timeline["coverage"][0]["action_ids"].append("target-after")
    ResolvedVisualTimelineV2.model_validate(timeline)
    timeline["initial_object_states"][-1].update(state="visible", visible=True)
    with pytest.raises(ValueError, match="hidden authored"):
        ResolvedVisualTimelineV2.model_validate(timeline)


def test_legacy_bare_annotation_loads_but_new_writes_and_execution_reject_it():
    plan, layout, timeline = annotation_documents()
    for action in (plan["actions"][-1], timeline["actions"][-1]["action"]):
        action.pop("annotation_policy")
        action["annotation"] = "Legacy unplaced note"
    VisualPlanV2.model_validate(plan)
    ResolvedVisualTimelineV2.model_validate(timeline)
    with pytest.raises(ValueError, match="authored objects"):
        validate_plan_evidence_completeness(plan)
    with pytest.raises(UnsupportedVisualAction):
        evaluate_frame(layout, timeline, 6500)


def leader_documents():
    plan, layout, timeline = annotation_documents()
    leader = deepcopy(connector_documents()[0]["objects"][-1])
    leader.update(object_id="annotation-leader", role="pointer", source_object_id="annotation-note",
                  source_anchor_id="center", destination_object_id="object-system", destination_anchor_id="center",
                  initial_state="hidden", visible=False, z_index=7, coverage_ids=["coverage-1"])
    leader["geometry"]["bounds"] = {"x": 100, "y": 150, "width": 800, "height": 500}
    layout["objects"].append(leader)
    layout["boards"][0]["object_ids"].append(leader["object_id"])
    timeline["initial_object_states"].append({"object_id": leader["object_id"], "state": "hidden",
                                               "state_version": 1, "visible": False})
    policy = timeline["actions"][-1]["action"]["annotation_policy"]
    policy.update(leader_connector_id=leader["object_id"])
    policy["phases"].append({"object_id": leader["object_id"], "mode": "draw", "weight": 1})
    plan = deepcopy(semantic_plan(layout, timeline))
    plan["beats"][0]["object_ids"].extend(["annotation-note", "annotation-leader"])
    layout["plan_sha256"] = timeline["plan_sha256"] = digest(plan)
    timeline["layout_sha256"] = digest(layout)
    return plan, layout, timeline


def test_annotation_leader_declares_exact_named_pointer_binding():
    plan, layout, timeline = leader_documents()
    validate_plan_evidence_completeness(plan)
    validate_plan_layout(plan, layout)
    action = ResolvedVisualTimelineV2.model_validate(timeline).actions[-1]
    assert [(start, end) for _, start, end in _annotation_phase_windows(action)] == [(6000, 6500), (6500, 7000)]
    for phase in timeline["actions"][-1]["action"]["annotation_policy"]["phases"]:
        phase["weight"] *= 100
    action = ResolvedVisualTimelineV2.model_validate(timeline).actions[-1]
    assert [(start, end) for _, start, end in _annotation_phase_windows(action)] == [(6000, 6500), (6500, 7000)]
    timeline["actions"][-1]["end_ms"] = 6001
    with pytest.raises(ValueError, match="collapse"):
        ResolvedVisualTimelineV2.model_validate(timeline)


@pytest.mark.parametrize("changes", [
    {"role": "semantic_connector"}, {"source_object_id": "object-label"},
    {"destination_object_id": "annotation-note"}, {"source_anchor_id": None},
    {"source_anchor_id": "unknown"}, {"destination_anchor_id": "unknown"},
    {"visible": True}, {"opacity": 0}, {"parent_id": "object-system"},
])
def test_annotation_leader_rejects_wrong_binding_or_ignored_payload(changes):
    plan, layout, _ = leader_documents()
    layout["objects"][-1].update(changes)
    with pytest.raises(ValueError):
        validate_plan_layout(plan, layout)


@pytest.mark.parametrize("changes", [{"visible": True}, {"opacity": 0}, {"text": "  "}, {"items": ["ignored"]}])
def test_annotation_note_must_be_hidden_paintable_and_exact_text(changes):
    plan, layout, _ = annotation_documents()
    layout["objects"][-1].update(changes)
    with pytest.raises(ValueError):
        validate_plan_layout(plan, layout)


def test_annotation_preserves_owning_beat_and_coverage():
    plan, _, _ = annotation_documents()
    note = plan["objects"][-1]
    note["beat_id"] = "beat-002"
    note["coverage_ids"] = ["coverage-3"]
    plan["beats"][0]["object_ids"].remove("annotation-note")
    plan["beats"][1]["object_ids"].append("annotation-note")
    VisualPlanV2.model_validate(plan)
    with pytest.raises(ValueError, match="beat and coverage"):
        validate_plan_evidence_completeness(plan)


def test_annotation_leader_cannot_construct_before_its_source_note():
    plan, layout, _ = leader_documents()
    plan["actions"][-1]["annotation_policy"]["phases"].reverse()
    with pytest.raises(ValueError, match="follow construction"):
        validate_plan_layout(plan, layout)


def test_annotation_requires_action_exact_coverage_and_above_target_paint():
    plan, layout, _ = annotation_documents()
    layout["objects"][-1]["z_index"] = -999
    with pytest.raises(ValueError, match="paint above"):
        validate_plan_layout(plan, layout)
    plan["objects"][-1]["coverage_ids"] = ["coverage-2"]
    with pytest.raises(ValueError, match="coverage ownership"):
        validate_plan_evidence_completeness(plan)


def grouped_annotation_documents(*, leader=False, group_type="group", group_z=8):
    _, layout, timeline = leader_documents() if leader else annotation_documents()
    group = deepcopy(layout["objects"][0])
    group.update(object_id="annotation-group", object_type=group_type, z_index=group_z,
                 child_ids=["annotation-note"], initial_state="visible", visible=True, anchors=[])
    group.pop("path_data")
    group["geometry"] = {"bounds": {"x": 0, "y": 0, "width": 1280, "height": 720},
                         "points": [], "corner_radius": None}
    group["style"] = {"fill": None, "stroke": None, "text": None, "effect": None}
    group["transform"]["position"] = {"x": 10, "y": 20}
    note = next(obj for obj in layout["objects"] if obj["object_id"] == "annotation-note")
    note.update(parent_id=group["object_id"], z_index=999)
    layout["objects"].append(group)
    layout["boards"][0]["object_ids"].append(group["object_id"])
    layout["boards"][0]["density_limit"] = len(layout["boards"][0]["object_ids"])
    timeline["initial_object_states"].append({"object_id": group["object_id"], "state": "visible",
                                               "state_version": 1, "visible": True})
    if leader:
        layout["objects"][-2]["z_index"] = 9
    plan = deepcopy(semantic_plan(layout, timeline))
    plan["beats"][0]["object_ids"].extend(["annotation-note", "annotation-group"])
    if leader:
        plan["beats"][0]["object_ids"].append("annotation-leader")
    return plan, layout, timeline


def test_annotation_order_uses_group_subtrees_not_raw_leaf_z():
    plan, layout, _ = grouped_annotation_documents(group_z=0)
    with pytest.raises(ValueError, match="effective stacking"):
        validate_plan_layout(plan, layout)
    plan, layout, _ = grouped_annotation_documents(group_z=8)
    validate_plan_layout(plan, layout)


def test_pointer_binds_transformed_group_world_anchors_and_rejects_clipped_endpoint():
    plan, layout, _ = grouped_annotation_documents(leader=True)
    validate_plan_layout(plan, layout)
    layout["objects"][-2]["geometry"]["bounds"]["width"] = 10
    with pytest.raises(ValueError, match="world endpoints"):
        validate_plan_layout(plan, layout)
    plan, layout, _ = grouped_annotation_documents(leader=True, group_type="clip")
    with pytest.raises(ValueError, match="unclipped"):
        validate_plan_layout(plan, layout)
