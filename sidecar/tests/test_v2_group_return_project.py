"""Private Group history can be stored without advertising public Group frames."""

from copy import deepcopy

import pytest
from test_v2_resolved_project import stored_v2_basis
from test_v2_return_hierarchy import group_return_documents
from test_v2_timeline_replay import resolved
from v2_fixtures import digest

from atme.project_service import ProjectError, _resolved_compilation_fingerprint


def stored_group_return_basis(tmp_path, regroup):
    service, project, plan, _, _ = stored_v2_basis(tmp_path)
    layout, timeline = group_return_documents(regroup=regroup)
    layout["objects"][-1].update(beat_id="beat-interlude", coverage_ids=["coverage-interlude"])
    action = deepcopy(timeline["actions"][3]["action"])
    action.pop("container_id")
    action.pop("hierarchy_policy")
    action.update(action_id="interlude-move", verb="move", board_id="board-interlude",
                  source_instruction_id="instruction-interlude", coverage_id="coverage-interlude",
                  target_ids=["object-interlude"], easing="linear", expected_state="visible", post_state="visible",
                  destination=deepcopy(layout["objects"][-1]["transform"]), opacity=None)
    action["destination"]["position"]["x"] = 120
    timeline["actions"].insert(-1, resolved(action, 6500, 7000).model_dump(mode="json"))
    timeline["coverage"].append({"coverage_id": "coverage-interlude", "instruction_id": "instruction-interlude",
                                "status": "executed", "action_ids": ["interlude-move"], "fallback_id": None})
    timeline["fallbacks"][2]["affected_ids"].append("instruction-interlude")
    fields = plan["objects"][0].keys()
    plan["objects"] = [{key: obj[key] for key in fields} for obj in layout["objects"]]
    plan["assets"] = []
    timeline["resolved_assets"] = []
    plan["boards"] = deepcopy(layout["boards"])
    plan["actions"] = [deepcopy(item["action"]) for item in timeline["actions"]]
    plan["coverage"] = deepcopy(timeline["coverage"])
    plan["fallbacks"] = deepcopy(timeline["fallbacks"])
    returned = timeline["actions"][-1]["action"]
    for beat in plan["beats"]:
        beat["object_ids"] = [obj["object_id"] for obj in plan["objects"] if obj["beat_id"] == beat["beat_id"]]
        beat["evidence"] = None
    plan["beats"][1]["action_ids"] = [item["action_id"] for item in plan["actions"]
                                         if item["coverage_id"] == "coverage-3"]
    plan["beats"][1]["continuity"].update(return_from_board_id="board-interlude",
                                           expected_state_versions=returned["expected_object_state_versions"],
                                           developed_return_state=returned["destination_state"])
    beat = deepcopy(plan["beats"][1])
    beat.update(beat_id="beat-interlude", board_id="board-interlude", object_ids=["object-interlude"],
                action_ids=["interlude-move"], coverage_ids=["coverage-interlude"], rhetorical_role="example")
    beat["attention"].update(primary_targets=["object-interlude"], secondary_context=[], dimmed_targets=[])
    beat["continuity"].update(keep=[], change=[], remove=[], replacements={}, return_from_board_id=None,
                              expected_state_versions={}, developed_return_state=None)
    beat["camera_intent"]["target_ids"] = ["object-interlude"]
    plan["beats"].append(beat)
    timeline["beat_anchors"].append({"beat_id": "beat-interlude", "start_ms": 6500})
    plan["project_revision"] = project["revision"]
    try:
        project = service.write(project["project_id"], "storyboard", plan, project["revision"])
    except ProjectError as exc:
        raise AssertionError(exc.errors) from exc
    layout.update(project_id=project["project_id"], project_revision=project["revision"],
                  plan_revision=project["artifacts"]["storyboard"], plan_sha256=digest(plan))
    try:
        project = service.write(project["project_id"], "layout", layout, project["revision"])
    except ProjectError as exc:
        raise AssertionError(exc.errors) from exc
    source = service.source_timeline.get(project["project_id"])
    timeline.update(project_id=project["project_id"], project_revision=project["revision"],
                    plan_revision=project["artifacts"]["storyboard"], plan_sha256=digest(plan),
                    layout_revision=project["artifacts"]["layout"], layout_sha256=digest(layout),
                    cleaned_timeline_revision=source["timeline_revision"],
                    cleaned_timeline_fingerprint=digest(source["document"]))
    timeline["compilation_fingerprint"] = _resolved_compilation_fingerprint(timeline)
    return service, project, timeline


@pytest.mark.parametrize("regroup", [False, True])
def test_new_write_stores_exact_group_and_ungroup_a_b_a_receipts_without_public_playback(tmp_path, regroup):
    service, project, timeline = stored_group_return_basis(tmp_path, regroup)
    try:
        project = service.write(project["project_id"], "resolved_timeline", timeline, project["revision"])
        assert service.artifact(project["project_id"], "resolved_timeline")["document"] == timeline
        copy = service.duplicate(project["project_id"])
        copied = service.artifact(copy["project_id"], "resolved_timeline")["document"]
        assert copied["actions"][-1]["return_hierarchy_receipt"] == timeline["actions"][-1]["return_hierarchy_receipt"]
        assert copied["compilation_fingerprint"] == _resolved_compilation_fingerprint(copied)
        with pytest.raises(ProjectError, match="cannot be previewed") as failure:
            service.runner.preview_v2_source(project["project_id"], project["revision"], 7000)
        assert failure.value.code == "preview_unavailable"
        assert "no frame implementation" in failure.value.errors[0]["message"]
        assert service.capabilities()["visual_contracts"]["renderer_versions"] == ["1"]
    finally:
        service.store.close()
