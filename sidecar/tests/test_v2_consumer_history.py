"""Preview and receipt writes must share consumer guards, not just replay."""

from copy import deepcopy

import pytest
from test_v2_annotation_action import append_target
from test_v2_annotation_contract import grouped_annotation_documents
from test_v2_evidence_lifecycle import grouped_evidence_documents
from test_v2_group_return_project import stored_group_return_basis
from test_v2_resolved_project import stored_v2_basis
from test_v2_return_hierarchy import return_receipt_documents
from v2_fixtures import digest

from atme.project_service import ProjectError, _resolved_compilation_fingerprint
from atme.render import v2_state
from atme.store.contracts_v2 import ExecutableLayoutV2, ResolvedVisualTimelineV2


def validate_history(layout, timeline):
    v2_state.validate_resolved_return_history(
        ExecutableLayoutV2.model_validate(layout), ResolvedVisualTimelineV2.model_validate(timeline),
        layout_sha256=digest(layout))


@pytest.mark.parametrize("start", [6500, 7500])
def test_history_validator_cannot_drop_annotation_ancestor_hold_guard(start):
    _, layout, timeline = grouped_annotation_documents()
    append_target(timeline, "annotation-group", "fade", start, start + 100, opacity=.5)
    timeline["layout_sha256"] = digest(layout)
    original = deepcopy((layout, timeline))
    with pytest.raises(v2_state.V2FrameError, match="uninterrupted construction and hold"):
        validate_history(layout, timeline)
    assert (layout, timeline) == original


def test_no_return_history_runs_real_evidence_lifecycle_without_public_group(tmp_path, monkeypatch):
    layout, timeline = grouped_evidence_documents(tmp_path)
    observed = []
    original = v2_state.validate_evidence_reading

    def observe(item, layout, objects, treatment, sample, viewport):
        observed.append(sample.at_ms)
        return original(item, layout, objects, treatment, sample, viewport)

    monkeypatch.setattr(v2_state, "validate_evidence_reading", observe)
    validate_history(layout, timeline)
    assert 5499 in observed and 5500 in observed
    with pytest.raises(v2_state.UnsupportedVisualAction, match="no frame implementation"):
        v2_state.evaluate_frame(layout, timeline, 5500)


def test_receipt_history_runs_temporal_consumers_only_through_last_return(monkeypatch):
    layout, timeline = return_receipt_documents()
    observed = []
    original = v2_state._validate_pair_temporal

    def observe(context, replay, camera_plan):
        observed.append(tuple(item.action.action_id for item in context.timeline.actions))
        return original(context, replay, camera_plan)

    monkeypatch.setattr(v2_state, "_validate_pair_temporal", observe)
    validate_history(layout, timeline)
    expected = tuple(item["action"]["action_id"] for item in timeline["actions"][:3])
    assert observed == [expected]
    v2_state.evaluate_frame(layout, timeline, 5000)
    assert observed[-1] == tuple(item["action"]["action_id"] for item in timeline["actions"])


@pytest.mark.parametrize("regroup", [False, True])
def test_project_receipt_write_invokes_shared_temporal_history(tmp_path, monkeypatch, regroup):
    service, project, timeline = stored_group_return_basis(tmp_path, regroup)
    observed = []
    original = v2_state._validate_pair_temporal

    def observe(context, replay, camera_plan):
        observed.append(tuple(item.action.action_id for item in context.timeline.actions))
        return original(context, replay, camera_plan)

    monkeypatch.setattr(v2_state, "_validate_pair_temporal", observe)
    try:
        service.write(project["project_id"], "resolved_timeline", timeline, project["revision"])
        assert observed == [tuple(item["action"]["action_id"] for item in timeline["actions"])]
        assert service.artifact(project["project_id"], "resolved_timeline")["document"] == timeline
    finally:
        service.store.close()


def stored_annotation_hold(tmp_path):
    service, project, plan, layout, timeline = stored_v2_basis(tmp_path, real_evidence=True)
    pid = project["project_id"]
    project = service.write(pid, "resolved_timeline", timeline, project["revision"])
    _, annotation_layout, annotation_timeline = grouped_annotation_documents()
    extra = deepcopy(annotation_layout["objects"][-2:])
    fields = plan["objects"][0].keys()
    plan["objects"].extend({key: obj[key] for key in fields} for obj in extra)
    plan["boards"][0]["object_ids"].extend(obj["object_id"] for obj in extra)
    plan["boards"][0]["density_limit"] = len(plan["boards"][0]["object_ids"])
    plan["beats"][0]["object_ids"].extend(obj["object_id"] for obj in extra)
    annotation = deepcopy(annotation_timeline["actions"][-1])
    annotation.update(start_ms=8000, end_ms=9000)
    trigger = {"kind": "absolute", "at_ms": 8000}
    annotation["action"].update(trigger=trigger)
    annotation["resolved_trigger"].update(source=trigger, alignment_anchor_ms=8000, resolved_at_ms=8000)
    timeline["actions"].append(annotation)
    timeline["coverage"][0]["action_ids"].append(annotation["action"]["action_id"])
    append_target(timeline, "annotation-group", "fade", 8500, 8600, opacity=.5)
    plan["actions"].extend(deepcopy(item["action"]) for item in timeline["actions"][-2:])
    plan["beats"][0]["action_ids"].extend(item["action"]["action_id"] for item in timeline["actions"][-2:])
    plan["coverage"] = deepcopy(timeline["coverage"])
    plan["project_revision"] = project["revision"]
    project = service.write(pid, "storyboard", plan, project["revision"])
    layout["objects"].extend(extra)
    layout["boards"] = deepcopy(plan["boards"])
    layout.update(project_revision=project["revision"], plan_revision=project["artifacts"]["storyboard"],
                  plan_sha256=digest(plan))
    project = service.write(pid, "layout", layout, project["revision"])
    timeline["initial_object_states"].extend(deepcopy(annotation_timeline["initial_object_states"][-2:]))
    timeline.update(project_revision=project["revision"], plan_revision=project["artifacts"]["storyboard"],
                    layout_revision=project["artifacts"]["layout"], plan_sha256=digest(plan), layout_sha256=digest(layout))
    timeline["compilation_fingerprint"] = _resolved_compilation_fingerprint(timeline)
    return service, project, timeline


def test_no_return_project_write_rejects_ancestor_hold_edit_atomically(tmp_path):
    service, project, timeline = stored_annotation_hold(tmp_path)
    pid = project["project_id"]
    before = deepcopy(service.open(pid))
    artifact = deepcopy(service.artifact(pid, "resolved_timeline"))
    try:
        with pytest.raises(ProjectError) as failure:
            service.write(pid, "resolved_timeline", timeline, project["revision"])
        assert failure.value.code == "invalid_artifact"
        assert "uninterrupted construction and hold" in str(failure.value)
        assert service.open(pid) == before
        assert service.artifact(pid, "resolved_timeline") == artifact
    finally:
        service.store.close()


def test_no_return_project_write_reaches_real_evidence_reading(tmp_path, monkeypatch):
    service, project, _, _, timeline = stored_v2_basis(tmp_path, real_evidence=True)
    observed = []
    original = v2_state.validate_evidence_reading

    def observe(item, layout, objects, treatment, sample, viewport):
        observed.append(sample.at_ms)
        return original(item, layout, objects, treatment, sample, viewport)

    monkeypatch.setattr(v2_state, "validate_evidence_reading", observe)
    try:
        service.write(project["project_id"], "resolved_timeline", timeline, project["revision"])
        assert 4900 in observed
        assert service.artifact(project["project_id"], "resolved_timeline")["document"] == timeline
    finally:
        service.store.close()


@pytest.mark.parametrize("before_return", [False, True])
def test_noncausal_static_consumer_checks_follow_same_time_resolved_order(before_return):
    layout, timeline = return_receipt_documents()
    later = deepcopy(timeline["actions"][1])
    later["action"].update(action_id="future-highlight", verb="highlight", expected_state="visible",
                           post_state="highlighted", trigger={"kind": "absolute", "at_ms": 5000})
    later.update(start_ms=5000, end_ms=5100)
    later["resolved_trigger"].update(source=later["action"]["trigger"], alignment_anchor_ms=5000,
                                     resolved_at_ms=5000, matched_text=None, matched_occurrence=None)
    timeline["actions"].insert(2 if before_return else 3, later)
    timeline["coverage"][1]["action_ids"].append("future-highlight")
    if before_return:
        with pytest.raises(v2_state.V2FrameError, match="untouched visible"):
            validate_history(layout, timeline)
    else:
        validate_history(layout, timeline)
        with pytest.raises(v2_state.V2FrameError, match="untouched visible"):
            v2_state.evaluate_frame(layout, timeline, 5000)


def test_causal_receipt_keeps_future_evidence_metadata_without_executing_it(tmp_path, monkeypatch):
    service, _, _, layout, timeline = stored_v2_basis(tmp_path, real_evidence=True)
    returned_layout, returned_timeline = return_receipt_documents()
    layout["boards"][0]["expected_prior_state"] = "system_established"
    layout["activations"] = deepcopy(returned_layout["activations"])
    future = timeline["actions"][-1]
    future.update(start_ms=6000, end_ms=6900)
    trigger = {"kind": "absolute", "at_ms": 6000}
    future["action"].update(trigger=trigger)
    future["resolved_trigger"].update(source=trigger, alignment_anchor_ms=6000, resolved_at_ms=6000,
                                     matched_text=None, matched_occurrence=None)
    timeline["actions"].insert(2, deepcopy(returned_timeline["actions"][2]))
    timeline["coverage"][2]["action_ids"].append("return-1")
    timeline["layout_sha256"] = digest(layout)
    before = deepcopy((layout, timeline))
    observed = []
    original = v2_state.validate_evidence_reading

    def observe(item, layout, objects, treatment, sample, viewport):
        observed.append(sample.at_ms)
        return original(item, layout, objects, treatment, sample, viewport)

    monkeypatch.setattr(v2_state, "validate_evidence_reading", observe)
    try:
        validate_history(layout, timeline)
        assert observed == []
        v2_state.evaluate_frame(layout, timeline, 6900)
        assert 6900 in observed
        assert (layout, timeline) == before
    finally:
        service.store.close()
