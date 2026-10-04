"""Evidence holds use sampled geometry; public Group frames remain separate."""

from copy import deepcopy
from dataclasses import replace

import pytest
from test_v2_evidence_compositor import evidence_documents
from test_v2_hierarchy_contract import rehash
from test_v2_hierarchy_replay import prepared
from test_v2_return_hierarchy import private_clock
from test_v2_timeline_replay import resolved
from v2_fixtures import digest

from atme.render import v2_state
from atme.render.v2_camera import CameraViewport, camera_segments
from atme.render.v2_evidence_reading import validate_evidence_reading
from atme.render.v2_state import UnsupportedVisualAction, evaluate_frame
from atme.store.contracts_v2 import GroupAction


def grouped_evidence_documents(tmp_path, start=5000, end=5500):
    _service, layout, timeline, _verified = evidence_documents(tmp_path)
    action, objects, _, _, _ = prepared()
    shell = objects["object-group"].model_dump(mode="json")
    shell.update(initial_state="grouped")
    layout["objects"].append(shell)
    layout["objects"][0]["parent_id"] = shell["object_id"]
    layout["objects"][1]["parent_id"] = shell["object_id"]
    layout["boards"][0]["object_ids"].append(shell["object_id"])
    timeline["initial_object_states"].append({"object_id": shell["object_id"], "state": "grouped",
                                               "visible": True, "state_version": 1})
    document = action.model_dump(mode="json")
    document["action_id"] = "ungroup-sibling"
    by_id = {obj["object_id"]: obj for obj in layout["objects"]}
    for side in ("source", "destination"):
        for placement in document["hierarchy_policy"][f"{side}_basis"]["placements"]:
            placement["local_transform"] = deepcopy(by_id[placement["object_id"]]["transform"])
    rehash(document)
    group = resolved(GroupAction.model_validate(document), start, end)
    timeline["initial_hierarchy_basis"] = deepcopy(document["hierarchy_policy"]["source_basis"])
    timeline["initial_hierarchy_basis_sha256"] = document["hierarchy_policy"]["source_basis_sha256"]
    timeline["actions"].append(group.model_dump(mode="json"))
    timeline["actions"].sort(key=lambda row: row["start_ms"])
    next(row for row in timeline["coverage"] if row["coverage_id"] == group.action.coverage_id)["action_ids"].append(
        group.action.action_id)
    timeline["layout_sha256"] = digest(layout)
    return layout, timeline


def test_unrelated_group_during_evidence_hold_preserves_reading_geometry(tmp_path):
    layout, timeline = grouped_evidence_documents(tmp_path)
    original = deepcopy((layout, timeline))
    context, trace = private_clock(layout, timeline)
    camera_plan = camera_segments(context.layout, context.timeline, trace)
    v2_state._validate_pair_temporal(context, trace, camera_plan)
    assert trace.at(5500).object("object-evidence") == trace.at(4999).object("object-evidence")
    assert trace.at(5500).hierarchy.children("board-main", "object-group") == ()
    assert (layout, timeline) == original
    with pytest.raises(UnsupportedVisualAction):
        evaluate_frame(layout, timeline, 5500)


@pytest.mark.parametrize("field,value,match", [("visible", False, "fully visible"),
                                               ("opacity", .5, "opaque"),
                                               ("reveal_fraction", .5, "fully visible")])
def test_evidence_reading_checks_actual_held_sample_not_captured_hidden_source(tmp_path, field, value, match):
    _service, layout, timeline, _verified = evidence_documents(tmp_path)
    context, trace = private_clock(layout, timeline)
    item = context.timeline.actions[2]
    sample = trace.at(6000)
    sampled = replace(sample, objects=tuple(replace(frame, **{field: value}) if frame.object_id == "object-evidence"
                                           else frame for frame in sample.objects))
    with pytest.raises(ValueError, match=match):
        validate_evidence_reading(item, context.layout, context.objects, context.layout.evidence_treatments[0],
                                  sampled, CameraViewport(0, 0, 1280, 720))


@pytest.mark.parametrize("mutation,match", [("position", "not fully readable"),
                                            ("rotation", "undeclared rotation")])
def test_evidence_reading_uses_actual_sampled_world_transform(tmp_path, mutation, match):
    _service, layout, timeline, _verified = evidence_documents(tmp_path)
    context, trace = private_clock(layout, timeline)
    sample = trace.at(6000)
    evidence = sample.object("object-evidence")
    transform = (replace(evidence.transform, position=replace(evidence.transform.position, x=2000))
                 if mutation == "position" else replace(evidence.transform, rotation_degrees=45))
    sampled = replace(sample, objects=tuple(replace(frame, transform=transform) if frame.object_id == "object-evidence"
                                           else frame for frame in sample.objects))
    with pytest.raises(ValueError, match=match):
        validate_evidence_reading(context.timeline.actions[2], context.layout, context.objects,
                                  context.layout.evidence_treatments[0], sampled, CameraViewport(0, 0, 1280, 720))


def test_real_evidence_consumer_samples_structural_boundary_and_hold_end(tmp_path, monkeypatch):
    layout, timeline = grouped_evidence_documents(tmp_path)
    context, trace = private_clock(layout, timeline)
    observed = []
    original = v2_state.validate_evidence_reading
    def observe(item, layout, objects, treatment, sample, viewport):
        observed.append(sample.at_ms)
        return original(item, layout, objects, treatment, sample, viewport)
    monkeypatch.setattr(v2_state, "validate_evidence_reading", observe)
    v2_state._validate_pair_temporal(context, trace, camera_segments(context.layout, context.timeline, trace))
    assert 5499 in observed and 5500 in observed
    item = context.timeline.actions[2]
    assert item.start_ms in observed and item.end_ms in observed
    assert item.end_ms + context.layout.evidence_treatments[0].intent.readable_hold_intent_ms - 1 in observed
