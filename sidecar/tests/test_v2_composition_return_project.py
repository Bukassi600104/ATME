"""Stored authored A/B/A preserves current topology, not definition expansion."""
from copy import deepcopy

import pytest
from atme.project_service import ProjectError, _resolved_compilation_fingerprint
from atme.render import v2_state
from atme.render.v2_split_paint import verify_split_paint_inputs
from atme.render.v2_svg import _compose_validated_svg_frame, _rasterize_svg_frame
from atme.store import contracts_v2 as contracts
from test_v2_composition_project import stored_composition_basis
from test_v2_composition_return import structural_return_documents
from test_v2_group_annotation import consumer_clock
from test_v2_registry_project import history
from test_v2_return_hierarchy import rehash_receipt
from v2_fixtures import digest


def stored_return_basis(tmp_path, *, portrait=False, regroup=False):
    service, project, prior, _layout = stored_composition_basis(tmp_path, portrait=portrait)
    layout, timeline = structural_return_documents(portrait=portrait, regroup=regroup)
    plan = deepcopy(prior)
    fields = set(contracts.SemanticStandardObjectSpec.model_fields)
    plan["objects"] = [{key: deepcopy(value) for key, value in obj.items() if key in fields} for obj in layout["objects"]]
    plan["objects"][0]["object_type"] = "instance"
    plan.update(boards=deepcopy(layout["boards"]), actions=[deepcopy(row["action"]) for row in timeline["actions"]],
                coverage=deepcopy(timeline["coverage"]), fallbacks=deepcopy(timeline["fallbacks"]))
    returned = timeline["actions"][-1]["action"]
    first = plan["beats"][0]
    first.update(object_ids=[obj["object_id"] for obj in plan["objects"] if obj["board_id"] == "board-main"],
                 action_ids=[obj["action_id"] for obj in plan["actions"] if obj["board_id"] == "board-main"])
    first["continuity"].update(return_from_board_id="board-between",
        expected_state_versions=deepcopy(returned["expected_object_state_versions"]),
        developed_return_state=returned["destination_state"])
    between = deepcopy(first)
    between.update(beat_id="beat-between", board_id="board-between", rhetorical_role="example",
                   object_ids=["between-boards"], action_ids=["between-move"], coverage_ids=["coverage-between"],
                   fallback_ids=["fallback-1"])
    between["attention"].update(primary_targets=["between-boards"], secondary_context=[], dimmed_targets=[])
    between["camera_intent"]["target_ids"] = ["between-boards"]
    between["continuity"].update(keep=[], change=[], remove=[], replacements={}, return_from_board_id=None,
                                  expected_state_versions={}, developed_return_state=None)
    plan["beats"].append(between)
    pid = project["project_id"]
    plan.update(project_id=pid, project_revision=project["revision"])
    project = service.write(pid, "storyboard", plan, project["revision"])
    layout.update(project_id=pid, project_revision=project["revision"],
                  plan_revision=project["artifacts"]["storyboard"], plan_sha256=digest(plan))
    project = service.write(pid, "layout", layout, project["revision"])
    timing = service.source_timeline.get(pid)
    timeline.update(project_id=pid, project_revision=project["revision"],
                    plan_revision=project["artifacts"]["storyboard"], plan_sha256=digest(plan),
                    layout_revision=project["artifacts"]["layout"], layout_sha256=digest(layout),
                    cleaned_timeline_revision=timing["timeline_revision"],
                    cleaned_timeline_fingerprint=digest(timing["document"]))
    timeline["compilation_fingerprint"] = _resolved_compilation_fingerprint(timeline)
    project = service.write(pid, "resolved_timeline", timeline, project["revision"])
    return service, project, plan, layout, timeline


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("regroup", [False, True])
def test_real_stored_composition_structural_return_duplicate_preserves_receipts_authority_and_pixels(tmp_path, portrait, regroup):
    service, project, plan, layout, timeline = stored_return_basis(tmp_path, portrait=portrait, regroup=regroup)
    try:
        pid = project["project_id"]
        before = history(service, pid)
        timing = deepcopy(service.source_timeline.get(pid))
        copy = service.duplicate(pid)
        copied = {}
        for kind, original in (("storyboard", plan), ("layout", layout), ("resolved_timeline", timeline)):
            assert service.artifact(pid, kind)["document"] == original
            record = service.artifact(copy["project_id"], kind)
            copied[kind] = record["document"]
            assert record["duplicate_derivation"]["source_sha256"] == digest(original)
            assert record["duplicate_derivation"]["copied_sha256"] == digest(copied[kind])
        assert copied["layout"]["objects"] == layout["objects"]
        assert copied["resolved_timeline"]["actions"] == timeline["actions"]
        assert copied["resolved_timeline"]["initial_hierarchy_basis"] == timeline["initial_hierarchy_basis"]
        assert copied["resolved_timeline"]["actions"][-1]["return_hierarchy_receipt"] == timeline["actions"][-1]["return_hierarchy_receipt"]
        assert copied["storyboard"]["narrative_authority"] == plan["narrative_authority"]
        assert copied["resolved_timeline"]["plan_sha256"] == digest(copied["storyboard"])
        assert copied["resolved_timeline"]["layout_sha256"] == digest(copied["layout"])
        assert copied["resolved_timeline"]["compilation_fingerprint"] == _resolved_compilation_fingerprint(copied["resolved_timeline"])
        assert copied["resolved_timeline"]["cleaned_timeline_fingerprint"] == digest(service.source_timeline.get(copy["project_id"])["document"])
        assert history(service, pid) == before
        assert service.source_timeline.get(pid) == timing

        def frames(document, clock_document):
            context, replay, camera = consumer_clock(document, clock_document)
            inputs = verify_split_paint_inputs(context.layout, {})
            owner = document["objects"][0]
            returned = replay.at(7001)
            assert returned.hierarchy.children("board-main", owner["object_id"]) == (tuple(owner["child_ids"]) if regroup else ())
            result = {}
            for at in (6499, 6750, 7001, 5000, 7001):
                sample = v2_state._sample_validated_frame(context.layout, context.timeline, replay, camera, at)
                svg = _compose_validated_svg_frame(context.layout, context.timeline, sample, {}, split_inputs=inputs)
                raw = _rasterize_svg_frame(context.layout, svg, split_inputs=inputs).png
                if at in result:
                    assert result[at] == raw
                result[at] = raw
            return result

        original_frames = frames(layout, timeline)
        assert original_frames[6499] == original_frames[7001] == original_frames[5000]
        assert original_frames[6750] != original_frames[7001]
        assert frames(copied["layout"], copied["resolved_timeline"]) == original_frames
    finally:
        service.store.close()


@pytest.mark.parametrize("portrait", [False, True])
def test_coherently_rehashed_initial_definition_cannot_replace_stored_current_return_history(tmp_path, portrait):
    service, project, _plan, _layout, timeline = stored_return_basis(tmp_path, portrait=portrait)
    try:
        pid = project["project_id"]
        candidate = deepcopy(timeline)
        candidate["project_revision"] = project["revision"]
        receipt = candidate["actions"][-1]["return_hierarchy_receipt"]
        receipt["hierarchy_basis"]["placements"] = [deepcopy(row)
            for row in candidate["initial_hierarchy_basis"]["placements"] if row["board_id"] == "board-main"]
        rehash_receipt(receipt)
        candidate["compilation_fingerprint"] = _resolved_compilation_fingerprint(candidate)
        original = deepcopy(candidate)
        before = deepcopy((service.open(pid), history(service, pid), service.source_timeline.get(pid)))
        with pytest.raises(ProjectError) as failure:
            service.write(pid, "resolved_timeline", candidate, project["revision"])
        assert failure.value.code == "invalid_artifact"
        assert candidate == original
        assert (service.open(pid), history(service, pid), service.source_timeline.get(pid)) == before
    finally:
        service.store.close()
