"""Real stored hierarchy/annotation projects retain exact authored return history."""

from copy import deepcopy

import pytest
from test_v2_annotation_action import append_target
from test_v2_group_annotation import (
    annotation_group_documents,
    consumer_clock,
    private_svg,
    regroup_first_documents,
)
from test_v2_hierarchy_contract import rehash
from test_v2_resolved_project import stored_v2_basis
from test_v2_return_board import return_documents
from test_v2_timeline_replay import resolved
from v2_fixtures import digest

from atme.project_service import ProjectError, _resolved_compilation_fingerprint
from atme.render.v2_hierarchy import HierarchySnapshot
from atme.render.v2_hierarchy_replay import completed_hierarchy_basis
from atme.store.contracts_v2 import HierarchyBasis


def stored_group_annotation_return_basis(tmp_path, *, regroup, stale=None, mutate=None, portrait=False,
                                         document_builder=None):
    """Use the real project/WAV/cleaned timing store and exact authored hierarchy."""
    profile = "SHORT_FORM_9_16" if portrait else "LONG_FORM_16_9"
    service, project, plan, _, _ = stored_v2_basis(tmp_path, profile=profile)
    if document_builder is None:
        builder = regroup_first_documents if regroup else annotation_group_documents
        layout, timeline = builder(portrait=portrait)
    else:
        layout, timeline = document_builder(regroup=regroup, portrait=portrait)
    layout["boards"][0]["expected_prior_state"] = "system_established"
    layout["activations"][0]["end_ms"] = 8000
    interlude = deepcopy(layout["objects"][0])
    interlude.update(object_id="object-interlude", board_id="board-interlude", beat_id="beat-interlude",
                     coverage_ids=["coverage-interlude"], parent_id=None, z_index=0,
                     initial_state="visible", visible=True)
    layout["objects"].append(interlude)
    board = deepcopy(layout["boards"][0])
    board.update(board_id="board-interlude", object_ids=["object-interlude"], density_limit=1,
                 persistence_policy="single_beat", activation_policy="once", expected_prior_state=None)
    layout["boards"].append(board)
    layout["activations"].extend([
        {"activation_id": "activation-interlude", "board_id": "board-interlude", "start_ms": 8000,
         "end_ms": 9000, "reason": "Inspect another explanation"},
        {"activation_id": "activation-return", "board_id": "board-main", "start_ms": 9000,
         "end_ms": 10000, "reason": "Return to developed annotated work"},
    ])
    timeline["initial_object_states"].append({"object_id": "object-interlude", "state": "visible",
                                              "visible": True, "state_version": 1})
    placement = {"object_id": "object-interlude", "board_id": "board-interlude", "parent_id": None,
                 "sibling_ordinal": 0, "local_transform": deepcopy(interlude["transform"])}
    group = next(row["action"] for row in timeline["actions"] if row["action"]["verb"] in {"group", "ungroup"})
    for side in ("source", "destination"):
        group["hierarchy_policy"][f"{side}_basis"]["placements"].append(deepcopy(placement))
        group["hierarchy_policy"][f"{side}_basis"]["placements"].sort(key=lambda row: row["object_id"])
    rehash(group)
    if regroup:
        layout["initial_empty_group_ownership"][0]["owner_source_basis_sha256"] = group["hierarchy_policy"]["source_basis_sha256"]
    timeline["initial_hierarchy_basis"]["placements"].append(deepcopy(placement))
    timeline["initial_hierarchy_basis"]["placements"].sort(key=lambda row: row["object_id"])
    timeline["initial_hierarchy_basis_sha256"] = HierarchyBasis.model_validate(timeline["initial_hierarchy_basis"]).checksum()
    action = deepcopy(timeline["actions"][0]["action"])
    action.pop("annotation", None)
    action.update(action_id="interlude-move", verb="move", board_id="board-interlude",
                  source_instruction_id="instruction-interlude", coverage_id="coverage-interlude",
                  target_ids=["object-interlude"], easing="linear", expected_state="visible", post_state="visible",
                  destination=deepcopy(interlude["transform"]), fallback={"fallback_id": "fallback-3", "on_failure": "block"})
    action["destination"]["position"]["x"] += 120
    timeline["actions"].append(resolved(action, 8200, 8500).model_dump(mode="json"))
    timeline["coverage"].append({"coverage_id": "coverage-interlude", "instruction_id": "instruction-interlude",
                                "status": "executed", "action_ids": ["interlude-move"], "fallback_id": None})
    timeline["fallbacks"][2]["affected_ids"].append("instruction-interlude")
    timeline["layout_sha256"] = digest(layout)
    _, replay, _ = consumer_clock(layout, timeline)
    sample = replay.at(9000)
    owned = {obj.object_id: obj for obj in sample.objects if obj.board_id == "board-main"}
    retained = completed_hierarchy_basis(HierarchySnapshot(tuple(
        node for node in sample.hierarchy.nodes if node.board_id == "board-main")), owned)
    _, return_timeline = return_documents()
    returned = deepcopy(return_timeline["actions"][2])
    trigger = {"kind": "absolute", "at_ms": 9000}
    returned.update(start_ms=9000, end_ms=9001)
    returned["resolved_trigger"].update(source=trigger, alignment_anchor_ms=9000, resolved_at_ms=9000)
    returned["action"].update(trigger=trigger, source_board_id="board-interlude",
                               source_activation_id="activation-interlude",
                               expected_object_states={key: obj.state for key, obj in owned.items()},
                               expected_object_state_versions={key: dict(sample.state_versions)[key] for key in owned})
    returned["return_hierarchy_receipt"] = {
        "action_id": "return-1", "destination_board_id": "board-main",
        "destination_activation_id": "activation-return", "hierarchy_basis": retained.model_dump(mode="json"),
        "hierarchy_basis_sha256": retained.checksum(),
    }
    if stale:
        key, field = stale
        values = returned["action"][f"expected_object_{field}"]
        values[key] = "hidden" if field == "states" else values[key] + 1
    timeline["actions"].append(returned)
    timeline["coverage"][2]["action_ids"].append("return-1")
    if mutate:
        mutate(layout, timeline)
    fields = plan["objects"][0].keys()
    plan["objects"] = [{key: obj[key] for key in fields} for obj in layout["objects"]]
    plan["assets"] = []
    timeline["resolved_assets"] = []
    plan["boards"] = deepcopy(layout["boards"])
    plan["actions"] = [deepcopy(item["action"]) for item in timeline["actions"]]
    plan["coverage"] = deepcopy(timeline["coverage"])
    plan["fallbacks"] = deepcopy(timeline["fallbacks"])
    for beat in plan["beats"]:
        beat["object_ids"] = [obj["object_id"] for obj in plan["objects"] if obj["beat_id"] == beat["beat_id"]]
        beat["action_ids"] = [item["action_id"] for item in plan["actions"] if item["coverage_id"] in beat["coverage_ids"]]
        beat["evidence"] = None
    if any(item["action"]["verb"] == "return_board" for item in timeline["actions"]):
        plan["beats"][1]["continuity"].update(return_from_board_id="board-interlude",
            expected_state_versions=returned["action"]["expected_object_state_versions"],
            developed_return_state=returned["action"]["destination_state"])
    beat = deepcopy(plan["beats"][1])
    beat.update(beat_id="beat-interlude", board_id="board-interlude", object_ids=["object-interlude"],
                action_ids=["interlude-move"], coverage_ids=["coverage-interlude"], rhetorical_role="example")
    beat["attention"].update(primary_targets=["object-interlude"], secondary_context=[], dimmed_targets=[])
    beat["continuity"].update(keep=[], change=[], remove=[], replacements={}, return_from_board_id=None,
                              expected_state_versions={}, developed_return_state=None)
    beat["camera_intent"]["target_ids"] = ["object-interlude"]
    plan["beats"].append(beat)
    timeline["beat_anchors"].append({"beat_id": "beat-interlude", "start_ms": 8200})
    plan["project_revision"] = project["revision"]
    project = service.write(project["project_id"], "storyboard", plan, project["revision"])
    layout.update(project_id=project["project_id"], project_revision=project["revision"],
                  plan_revision=project["artifacts"]["storyboard"], plan_sha256=digest(plan))
    project = service.write(project["project_id"], "layout", layout, project["revision"])
    source = service.source_timeline.get(project["project_id"])
    timeline.update(project_id=project["project_id"], project_revision=project["revision"],
                    plan_revision=project["artifacts"]["storyboard"], plan_sha256=digest(plan),
                    layout_revision=project["artifacts"]["layout"], layout_sha256=digest(layout),
                    cleaned_timeline_revision=source["timeline_revision"],
                    cleaned_timeline_fingerprint=digest(source["document"]))
    timeline["compilation_fingerprint"] = _resolved_compilation_fingerprint(timeline)
    return service, project, timeline


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("regroup", [False, True])
def test_real_stored_pair_admits_exact_return_receipt_and_keeps_source_immutable(tmp_path, regroup, portrait):
    service, project, timeline = stored_group_annotation_return_basis(tmp_path, regroup=regroup, portrait=portrait)
    original = deepcopy((project, timeline, service.source_timeline.get(project["project_id"])))
    try:
        updated = service.write(project["project_id"], "resolved_timeline", timeline, project["revision"])
        assert updated["revision"] == project["revision"] + 1
        assert service.artifact(project["project_id"], "resolved_timeline")["document"] == timeline
        plan = service.artifact(project["project_id"], "storyboard")["document"]
        layout = service.artifact(project["project_id"], "layout")["document"]
        assert updated["profile"] == plan["output_profile"]["profile_id"] == timeline["output_profile"]["profile_id"]
        assert timeline["plan_sha256"] == layout["plan_sha256"] == digest(plan)
        assert timeline["layout_sha256"] == digest(layout)
        assert timeline["cleaned_timeline_revision"] == original[2]["timeline_revision"] == plan["narrative_authority"]["cleaned_timeline_revision"]
        assert timeline["cleaned_timeline_fingerprint"] == digest(original[2]["document"]) == plan["narrative_authority"]["cleaned_timeline_fingerprint"]
        prefix = deepcopy(timeline)
        returned = prefix["actions"].pop()
        prefix["coverage"][2]["action_ids"].remove("return-1")
        _, replay, _ = consumer_clock(layout, prefix)
        sample = replay.at(9000)
        claimed = returned["action"]
        for key in ("annotation-note", "annotation-leader"):
            assert sample.object(key).visible
            assert sample.object(key).state == claimed["expected_object_states"][key] == "visible"
            assert dict(sample.state_versions)[key] == claimed["expected_object_state_versions"][key]
            assert key in {row["object_id"] for row in returned["return_hierarchy_receipt"]["hierarchy_basis"]["placements"]}
        assert plan["beats"][1]["continuity"]["expected_state_versions"] == claimed["expected_object_state_versions"]
        assert service.source_timeline.get(project["project_id"]) == original[2]
        assert (project, timeline) == original[:2]
    finally:
        service.store.close()


@pytest.mark.parametrize("regroup", [False, True])
@pytest.mark.parametrize("object_id", ["annotation-note", "annotation-leader"])
@pytest.mark.parametrize("field", ["states", "state_versions"])
def test_coherently_authored_false_note_or_leader_return_claim_rejects_atomically(tmp_path, regroup, object_id, field):
    service, project, timeline = stored_group_annotation_return_basis(tmp_path, regroup=regroup, stale=(object_id, field))
    original = deepcopy((service.open(project["project_id"]), timeline))
    try:
        with pytest.raises(ProjectError, match="retained board state") as failure:
            service.write(project["project_id"], "resolved_timeline", timeline, project["revision"])
        assert failure.value.code == "invalid_artifact"
        assert service.open(project["project_id"]) == original[0]
        with pytest.raises(ProjectError):
            service.artifact(project["project_id"], "resolved_timeline")
        assert timeline == original[1]
    finally:
        service.store.close()


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("regroup", [False, True])
def test_real_no_return_stored_pair_proves_valid_full_history(tmp_path, regroup, portrait):
    def without_return(layout, timeline):
        timeline["actions"].pop()
        timeline["coverage"][2]["action_ids"].remove("return-1")
    service, project, timeline = stored_group_annotation_return_basis(
        tmp_path, regroup=regroup, portrait=portrait, mutate=without_return)
    source = deepcopy(service.source_timeline.get(project["project_id"]))
    try:
        service.write(project["project_id"], "resolved_timeline", timeline, project["revision"])
        assert not any(row["action"]["verb"] == "return_board" for row in timeline["actions"])
        assert service.artifact(project["project_id"], "resolved_timeline")["document"] == timeline
        context, replay, _ = consumer_clock(service.artifact(project["project_id"], "layout")["document"], timeline)
        assert context.timeline.output_profile.profile_id == project["profile"]
        assert replay.at(9999).object("annotation-note").visible
        assert replay.at(9999).object("annotation-leader").visible
        assert service.source_timeline.get(project["project_id"]) == source
    finally:
        service.store.close()


@pytest.mark.parametrize("regroup", [False, True])
def test_coherent_group_source_basis_cannot_ignore_prior_source_motion(tmp_path, regroup):
    def move_before_group(layout, timeline):
        destination = deepcopy(next(obj for obj in layout["objects"] if obj["object_id"] == "object-system")["transform"])
        destination["position"]["x"] += 12
        append_target(timeline, "object-system", "move", 4500, 4700, destination=destination)
    service, project, timeline = stored_group_annotation_return_basis(tmp_path, regroup=regroup, mutate=move_before_group)
    original = deepcopy(service.open(project["project_id"]))
    try:
        with pytest.raises(ProjectError, match="source basis differs from the completed frame") as failure:
            service.write(project["project_id"], "resolved_timeline", timeline, project["revision"])
        assert failure.value.code == "invalid_artifact"
        assert service.open(project["project_id"]) == original
        with pytest.raises(ProjectError):
            service.artifact(project["project_id"], "resolved_timeline")
    finally:
        service.store.close()


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("regroup", [False, True])
def test_real_duplicate_rebind_preserves_receipt_and_private_offline_return_pixels(tmp_path, regroup, portrait, monkeypatch):
    import socket

    from atme.render import v2_svg

    service, project, timeline = stored_group_annotation_return_basis(tmp_path, regroup=regroup, portrait=portrait)
    try:
        project = service.write(project["project_id"], "resolved_timeline", timeline, project["revision"])
        pid = project["project_id"]
        originals = {kind: deepcopy(service.artifact(pid, kind)) for kind in ("storyboard", "layout", "resolved_timeline")}
        source = deepcopy(service.source_timeline.get(pid))
        copy = service.duplicate(pid)
        assert copy["profile"] == project["profile"] == ("SHORT_FORM_9_16" if portrait else "LONG_FORM_16_9")
        copied = {kind: service.artifact(copy["project_id"], kind)["document"] for kind in originals}
        assert copy["project_id"] != pid
        assert all(doc["project_id"] == copy["project_id"] for doc in copied.values())
        assert copied["layout"]["plan_sha256"] == copied["resolved_timeline"]["plan_sha256"] == digest(copied["storyboard"])
        assert copied["resolved_timeline"]["layout_sha256"] == digest(copied["layout"])
        assert copied["resolved_timeline"]["compilation_fingerprint"] == _resolved_compilation_fingerprint(copied["resolved_timeline"])
        assert copied["resolved_timeline"]["actions"] == timeline["actions"]
        assert copied["resolved_timeline"]["initial_hierarchy_basis"] == timeline["initial_hierarchy_basis"]
        assert copied["resolved_timeline"]["cleaned_timeline_revision"] == timeline["cleaned_timeline_revision"]
        assert copied["resolved_timeline"]["cleaned_timeline_fingerprint"] == timeline["cleaned_timeline_fingerprint"]
        assert service.source_timeline.get(copy["project_id"])["document"] == source["document"]

        def no_network(*args, **kwargs):
            raise AssertionError("stored private paint must remain offline")
        monkeypatch.setattr(socket, "socket", no_network)
        monkeypatch.setattr(socket, "create_connection", no_network)
        pixels = []
        for layout, resolved_doc in ((originals["layout"]["document"], timeline),
                                     (copied["layout"], copied["resolved_timeline"])):
            context, replay, camera = consumer_clock(layout, resolved_doc)
            frames = {at: v2_svg._rasterize_svg_frame(context.layout, private_svg(context, replay, camera, at)).png
                      for at in (5999, 6000, 6750, 7999, 8500, 9000)}
            assert frames[5999] == frames[6000]
            assert frames[7999] == frames[9000] != frames[8500]
            assert frames[6750] != frames[7999]
            assert v2_svg._rasterize_svg_frame(context.layout, private_svg(context, replay, camera, 6750)).png == frames[6750]
            pixels.append(frames)
        assert pixels[0] == pixels[1]
        for current in (project, copy):
            with pytest.raises(ProjectError, match="cannot be previewed") as failure:
                service.runner.preview_v2_source(current["project_id"], current["revision"], 9000)
            assert failure.value.code == "preview_unavailable"
            assert "no frame implementation" in failure.value.errors[0]["message"]
        assert service.capabilities()["visual_contracts"]["renderer_versions"] == ["1"]
        assert {kind: service.artifact(pid, kind) for kind in originals} == originals
        assert service.source_timeline.get(pid) == source
    finally:
        service.store.close()


@pytest.mark.parametrize("position", ["before", "after", "no_return"])
@pytest.mark.parametrize("regroup", [False, True])
def test_stored_pair_causal_validation_uses_resolved_order_not_shared_timestamp(tmp_path, regroup, position):
    def add_same_time_fade(layout, timeline):
        append_target(timeline, "object-system", "fade", 9000, 9100, opacity=.5)
        fade = timeline["actions"].pop()
        return_index = next(index for index, row in enumerate(timeline["actions"]) if row["action"]["verb"] == "return_board")
        timeline["actions"].insert(return_index if position == "before" else return_index + 1, fade)
        if position == "no_return":
            timeline["actions"].pop(return_index)
            timeline["coverage"][2]["action_ids"].remove("return-1")
    service, project, timeline = stored_group_annotation_return_basis(tmp_path, regroup=regroup, mutate=add_same_time_fade)
    before = deepcopy((service.open(project["project_id"]), timeline))
    source = deepcopy(service.source_timeline.get(project["project_id"]))
    try:
        if position == "after":
            service.write(project["project_id"], "resolved_timeline", timeline, project["revision"])
            assert service.artifact(project["project_id"], "resolved_timeline")["document"] == timeline
            with pytest.raises(ValueError, match="completed explicit removal|retained board state"):
                consumer_clock(service.artifact(project["project_id"], "layout")["document"], timeline)
        else:
            with pytest.raises(ProjectError, match="completed explicit removal|retained board state") as failure:
                service.write(project["project_id"], "resolved_timeline", timeline, project["revision"])
            assert failure.value.code == "invalid_artifact"
            assert service.open(project["project_id"]) == before[0]
            with pytest.raises(ProjectError):
                service.artifact(project["project_id"], "resolved_timeline")
        assert timeline == before[1]
        assert service.source_timeline.get(project["project_id"]) == source
    finally:
        service.store.close()
