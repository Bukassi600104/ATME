"""One evidence insert owns persistent authored note construction on one clock."""

from copy import deepcopy
from dataclasses import replace

import pytest
from atme.render.v2_state import evaluate_frame
from atme.render.v2_timeline_replay import CapturedAction, CapturedEvidenceAction
from atme.store.contracts_v2 import ResolvedVisualTimelineV2
from test_v2_annotation_action import append_target
from test_v2_camera_action import append_camera
from test_v2_evidence_annotation_objects import cross_annotation_documents
from test_v2_group_annotation import consumer_clock
from v2_fixtures import digest


def runtime_documents():
    _, layout, timeline = cross_annotation_documents()
    timeline["actions"][2]["action"]["easing"] = "linear"
    return layout, timeline


def test_evidence_insert_constructs_persistent_notes_and_leader_on_its_existing_clock():
    layout, timeline = runtime_documents()
    original = deepcopy((layout, timeline))
    _, replay, _ = consumer_clock(layout, timeline)
    target = replay.at(3999).object("object-system")
    # Hand-derived: 900ms insert, 2:1 policy => 600ms note then 300ms leader.
    for at, note, leader in ((3999, 0, 0), (4000, 0, 0), (4300, .5, 0),
                              (4600, 1, 0), (4750, 1, .5), (4900, 1, 1),
                              (7399, 1, 1), (9000, 1, 1)):
        sample = replay.at(at)
        assert sample.object("evidence-note").reveal_fraction == note
        assert sample.object("evidence-leader").reveal_fraction == leader
        assert sample.object("evidence-note").visible == (note > 0)
        assert sample.object("evidence-leader").visible == (leader > 0)
        assert sample.object("object-system") == target
    assert evaluate_frame(layout, timeline, 4750).object("evidence-leader").reveal_fraction == .5
    assert (layout, timeline) == original


def test_evidence_owned_state_versions_commit_atomically_without_mutating_the_target():
    layout, timeline = runtime_documents()
    _, replay, _ = consumer_clock(layout, timeline)
    before = dict(replay.at(4899).state_versions)
    after = dict(replay.at(4900).state_versions)
    assert before == {"object-system": 2, "object-label": 2, "object-evidence": 1,
                      "evidence-note": 1, "evidence-leader": 1}
    assert after == {"object-system": 2, "object-label": 2, "object-evidence": 2,
                     "evidence-note": 2, "evidence-leader": 2}
    assert replay.at(4900).object("evidence-note").state == "visible"
    assert replay.at(4900).object("evidence-leader").state == "visible"
    assert replay.at(4900).object("object-evidence").state == "evidence_visible"


def test_evidence_random_seeks_and_caller_mutation_cannot_change_captured_authority():
    layout, timeline = runtime_documents()
    _, replay, _ = consumer_clock(layout, timeline)
    first = replay.at(4750)
    timeline["evidence_treatments"][0]["intent"]["annotation_policy"]["phases"][0]["weight"] = 99
    layout["objects"][0]["geometry"]["bounds"]["x"] = -9000
    for at in (9000, 0, 4900, 4000):
        replay.at(at)
    assert replay.at(4750) == first
    assert first.object("evidence-leader").reveal_fraction == .5


def test_evidence_annotation_phase_weights_cannot_collapse_inside_insert():
    _, timeline = runtime_documents()
    timeline["actions"][2]["end_ms"] = 4001
    with pytest.raises(ValueError, match="collapse"):
        ResolvedVisualTimelineV2.model_validate(timeline)


def test_camera_observation_during_cross_annotation_hold_remains_available():
    layout, timeline = runtime_documents()
    append_camera(timeline, "observe-evidence", "camera_hold", 5000, 5500, framing="wide")
    _, replay, _ = consumer_clock(layout, timeline)
    assert replay.at(5200).object("evidence-note").reveal_fraction == 1


def test_retained_evidence_leader_requires_removal_before_target_edit():
    layout, timeline = runtime_documents()
    destination = deepcopy(layout["objects"][0]["transform"])
    destination["position"]["x"] = 5
    append_target(timeline, "object-system", "move", 7600, 7800, destination=destination)
    with pytest.raises(ValueError, match="retained.*pointer|annotation.*target"):
        consumer_clock(layout, timeline)


def test_explicit_completed_leader_removal_allows_later_target_edit():
    layout, timeline = runtime_documents()
    append_target(timeline, "evidence-leader", "exit", 7400, 7500)
    destination = deepcopy(layout["objects"][0]["transform"])
    destination["position"]["x"] = 5
    append_target(timeline, "object-system", "move", 7600, 7800, destination=destination)
    _, replay, _ = consumer_clock(layout, timeline)
    assert not replay.at(9000).object("evidence-leader").visible
    assert replay.at(9000).object("evidence-note").reveal_fraction == 1
    assert replay.at(9000).object("object-system").transform.position.x == 5


def test_evidence_construction_requires_untouched_hidden_authored_notes():
    layout, timeline = runtime_documents()
    append_target(timeline, "evidence-note", "write", 1000, 1100)
    next(row for row in timeline["actions"] if row["action"]["action_id"] == "write-evidence-note")[
        "action"]["expected_state"] = "hidden"
    timeline["layout_sha256"] = digest(layout)
    with pytest.raises(ValueError, match="untouched.*note|untouched.*annotation"):
        consumer_clock(layout, timeline)


def test_captured_target_read_uses_actual_completed_state_version_and_hierarchy():
    layout, timeline = runtime_documents()
    _, replay, _ = consumer_clock(layout, timeline)
    capture = next(capture for checkpoint in replay.checkpoints for capture in checkpoint.active
                   if checkpoint.at_ms == 4000 and capture.resolved.action.action_id == "action-3")
    read = capture.target_read
    assert read.frame == replay.before_action("action-3").object("object-system")
    assert read.state_version == 2
    assert read.hierarchy == replay.before_action("action-3").hierarchy


@pytest.mark.parametrize("fault", ["treatment", "target-object", "target-frame", "target-version",
                                  "target-hierarchy", "missing-read"])
def test_forged_capture_cannot_replace_paired_treatment_or_target_receipt(fault):
    layout, timeline = runtime_documents()
    _, replay, _ = consumer_clock(layout, timeline)
    index, checkpoint = next((index, checkpoint) for index, checkpoint in enumerate(replay.checkpoints)
                              if checkpoint.at_ms == 4000)
    capture = checkpoint.active[0]
    read = capture.target_read
    if fault == "treatment":
        capture = replace(capture, treatment_json=capture.treatment_json.replace("Example Source", "Invented Source"))
    else:
        if fault == "target-object":
            read = replace(read, object_json="{}")
        elif fault == "target-frame":
            read = replace(read, frame=replace(read.frame, state="removed"))
        elif fault == "target-version":
            read = replace(read, state_version=read.state_version + 1)
        elif fault == "target-hierarchy":
            ordinals = {node.object_id: node.sibling_ordinal for node in read.hierarchy.nodes}
            swaps = {"object-system": ordinals["object-label"], "object-label": ordinals["object-system"]}
            nodes = tuple(replace(node, sibling_ordinal=swaps.get(node.object_id, node.sibling_ordinal))
                          for node in read.hierarchy.nodes)
            read = replace(read, hierarchy=replace(read.hierarchy, nodes=nodes))
        else:
            read = None
        capture = replace(capture, target_read=read)
    checkpoints = list(replay.checkpoints)
    checkpoints[index] = replace(checkpoint, active=(capture,))
    forged = replace(replay, checkpoints=tuple(checkpoints))
    with pytest.raises(ValueError):
        forged.at(4300)


@pytest.mark.parametrize("boundary", ["before", "sample"])
@pytest.mark.parametrize("fault", ["downgrade", "subclass", "missing-read-map"])
def test_bound_evidence_authority_cannot_be_bypassed_by_capture_type_or_missing_context(boundary, fault):
    layout, timeline = runtime_documents()
    _, replay, _ = consumer_clock(layout, timeline)
    index, checkpoint = next((index, row) for index, row in enumerate(replay.checkpoints) if row.at_ms == 4000)
    capture = checkpoint.active[0]
    if fault == "downgrade":
        capture = CapturedAction(capture.resolved_index, capture.resolved_json,
                                 capture.baseline, capture.context_root_ids)
    elif fault == "subclass":
        class UntrustedEvidence(CapturedEvidenceAction):
            pass
        capture = UntrustedEvidence(**capture.__dict__)
    checkpoints = list(replay.checkpoints)
    checkpoints[index] = replace(checkpoint, active=(capture,))
    forged = replace(replay, checkpoints=tuple(checkpoints),
                     evidence_reads_json=() if fault == "missing-read-map" else replay.evidence_reads_json)
    with pytest.raises(ValueError):
        forged.before_action("action-3") if boundary == "before" else forged.at(4300)
