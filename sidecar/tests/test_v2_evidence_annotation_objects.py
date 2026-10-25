"""Evidence annotations must bind real authored objects, not generated artwork."""

from copy import deepcopy

import pytest
from atme.store.contracts_v2 import (
    ExecutableLayoutV2,
    ResolvedVisualTimelineV2,
    VisualPlanV2,
    validate_plan_evidence_completeness,
    validate_plan_layout,
)
from test_v2_connector_svg import connector_documents
from test_v2_evidence_annotation_contract import authored_evidence_annotation
from v2_fixtures import (
    digest,
    executable_layout_v2,
    resolved_timeline_v2,
    visual_plan_v2,
)


def cross_annotation_documents():
    plan = visual_plan_v2()
    intent = plan["beats"][1]["evidence"]
    intent.update(annotation_target_id="object-system", annotation_policy=authored_evidence_annotation())
    layout = executable_layout_v2(plan)
    note = deepcopy(layout["objects"][1])
    note.update(object_id="evidence-note", beat_id="beat-002", text="Key mechanism",
                z_index=5, coverage_ids=["coverage-3"])
    note["geometry"]["bounds"] = {"x": 140, "y": 560, "width": 420, "height": 80}
    leader = deepcopy(connector_documents()[0]["objects"][-1])
    leader.update(object_id="evidence-leader", beat_id="beat-002", role="pointer",
                  source_object_id="object-evidence", destination_object_id="object-system",
                  source_anchor_id="center", destination_anchor_id="center", z_index=6,
                  coverage_ids=["coverage-3"])
    leader["geometry"]["bounds"] = {"x": 80, "y": 130, "width": 1100, "height": 510}
    layout["objects"].extend([note, leader])
    semantic_keys = plan["objects"][0].keys()
    plan["objects"].extend({key: obj[key] for key in semantic_keys} for obj in (note, leader))
    plan["beats"][1]["object_ids"].extend(["evidence-note", "evidence-leader"])
    plan["boards"][0]["object_ids"].extend(["evidence-note", "evidence-leader"])
    layout["plan_sha256"] = digest(plan)
    timeline = resolved_timeline_v2(plan, layout)
    return plan, layout, timeline


def test_cross_evidence_annotations_are_real_owned_plan_and_layout_objects():
    plan, layout, timeline = cross_annotation_documents()
    validate_plan_evidence_completeness(plan)
    validate_plan_layout(plan, layout)
    VisualPlanV2.model_validate(plan)
    ExecutableLayoutV2.model_validate(layout)
    ResolvedVisualTimelineV2.model_validate(timeline)
    assert plan["beats"][1]["action_ids"] == ["action-3"]
    assert len(layout["evidence_treatments"]) == 1
    assert layout["objects"][-1]["source_object_id"] == "object-evidence"


def test_legacy_cross_intent_loads_but_new_write_requires_authored_policy():
    plan = visual_plan_v2()
    plan["beats"][1]["evidence"]["annotation_target_id"] = "object-system"
    VisualPlanV2.model_validate(plan)
    with pytest.raises(ValueError, match="annotation.*policy"):
        validate_plan_evidence_completeness(plan)


@pytest.mark.parametrize("boundary", ["layout", "resolved"])
def test_executable_cross_treatment_requires_authored_policy(boundary):
    plan = visual_plan_v2()
    plan["beats"][1]["evidence"]["annotation_target_id"] = "object-system"
    layout = executable_layout_v2(plan)
    timeline = resolved_timeline_v2(plan, layout)
    model, raw = (ExecutableLayoutV2, layout) if boundary == "layout" else (ResolvedVisualTimelineV2, timeline)
    with pytest.raises(ValueError, match="annotation.*policy"):
        model.model_validate(raw)


@pytest.mark.parametrize("fault", ["text", "items", "visible", "opacity", "source", "destination",
                                  "role", "beat", "coverage", "stacking", "second-text"])
def test_cross_annotation_cannot_silently_change_or_hide_authored_participants(fault):
    plan, layout, _ = cross_annotation_documents()
    note, leader = layout["objects"][-2:]
    if fault == "text":
        note["text"] = "Invented interpretation"
    elif fault == "items":
        note["items"] = ["Hidden extra copy"]
    elif fault == "visible":
        note["visible"] = True
    elif fault == "opacity":
        note["opacity"] = 0
    elif fault == "source":
        leader["source_object_id"] = "object-label"
    elif fault == "destination":
        leader["destination_object_id"] = "object-label"
    elif fault == "role":
        leader["role"] = "semantic_connector"
    elif fault in {"beat", "coverage"}:
        for obj in (plan["objects"][-2], note):
            obj["beat_id" if fault == "beat" else "coverage_ids"] = "beat-001" if fault == "beat" else ["coverage-1"]
    elif fault == "stacking":
        note["z_index"] = 0
    else:
        extra = deepcopy(note)
        extra["object_id"] = "second-note"
        layout["objects"].append(extra)
        plan["objects"].append({key: extra[key] for key in plan["objects"][0]})
        plan["boards"][0]["object_ids"].append(extra["object_id"])
        plan["beats"][1]["object_ids"].append(extra["object_id"])
        policy = plan["beats"][1]["evidence"]["annotation_policy"]
        policy["annotation_object_ids"].append(extra["object_id"])
        policy["phases"].append({"object_id": extra["object_id"], "mode": "write", "weight": 1})
    # The legacy flag must not bypass forensic ownership/text validation.
    with pytest.raises(ValueError):
        validate_plan_layout(plan, layout, require_code_payloads=False)
