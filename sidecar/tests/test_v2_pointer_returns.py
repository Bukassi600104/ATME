"""Real A/B/A relationship history, not a synthetic final-frame return claim."""

import hashlib
from copy import deepcopy

import pytest
from atme.project_service import ProjectError, _resolved_compilation_fingerprint
from atme.render.v2_hierarchy import HierarchySnapshot
from atme.render.v2_hierarchy_replay import completed_hierarchy_basis
from atme.render.v2_state import evaluate_frame
from atme.render.v2_svg import compose_png_frame
from test_v2_group_annotation import consumer_clock
from test_v2_pointer_project import persist_relationship, stored_relationship
from test_v2_registry_project import history
from test_v2_return_board import return_documents
from test_v2_timeline_replay import resolved
from v2_fixtures import common_action, digest


def stored_relationship_return(tmp_path, kind="pointer", portrait=False, *, persist=True):
    service, project, plan, layout, clock = stored_relationship(tmp_path, kind, portrait, persist=False)
    # Keep the relationship connected while A is away. It must return with the
    # same coordinates, named anchors and relationship version, not be redrawn.
    clock["actions"] = clock["actions"][:3]
    clock["coverage"][2]["action_ids"].remove("action-4")
    layout["boards"][0]["expected_prior_state"] = "system_established"
    layout["activations"][0]["end_ms"] = 8000
    interlude = deepcopy(layout["objects"][0])
    interlude.update(object_id="object-interlude", board_id="board-interlude", beat_id="beat-interlude",
                     coverage_ids=["coverage-interlude"], initial_state="visible", visible=True,
                     object_type="rectangle", geometry={"bounds": {"x": 180, "y": 400, "width": 300, "height": 220},
                     "points": [], "corner_radius": None})
    layout["objects"].append(interlude)
    board = deepcopy(layout["boards"][0])
    board.update(board_id="board-interlude", object_ids=["object-interlude"], density_limit=1,
                 persistence_policy="single_beat", activation_policy="once", expected_prior_state=None)
    layout["boards"].append(board)
    layout["activations"].extend([
        {"activation_id": "activation-interlude", "board_id": "board-interlude", "start_ms": 8000,
         "end_ms": 9000, "reason": "Inspect a second board"},
        {"activation_id": "activation-return", "board_id": "board-main", "start_ms": 9000,
         "end_ms": 10000, "reason": "Return to the same connected relationship"},
    ])
    clock["initial_object_states"].append({"object_id": "object-interlude", "state": "visible",
                                          "state_version": 1, "visible": True})
    destination = deepcopy(interlude["transform"])
    destination["position"]["x"] += 10
    move = {**common_action("interlude-move", "instruction-interlude", "board-interlude"),
            "verb": "move", "target_ids": ["object-interlude"], "coverage_id": "coverage-interlude",
            "expected_state": "visible", "post_state": "visible", "destination": destination, "opacity": None,
            "fallback": {"fallback_id": "fallback-3", "on_failure": "block"}}
    clock["actions"].append(resolved(move, 8200, 8500).model_dump(mode="json"))
    clock["coverage"].append({"coverage_id": "coverage-interlude", "instruction_id": "instruction-interlude",
                              "status": "executed", "action_ids": ["interlude-move"], "fallback_id": None})
    clock["fallbacks"][2]["affected_ids"].append("instruction-interlude")
    clock["layout_sha256"] = digest(layout)
    _, replay, _ = consumer_clock(layout, clock)
    sample = replay.at(9000)
    owned = {obj.object_id: obj for obj in sample.objects if obj.board_id == "board-main"}
    retained = completed_hierarchy_basis(HierarchySnapshot(tuple(
        node for node in sample.hierarchy.nodes if node.board_id == "board-main")), owned)
    _, sample = return_documents()
    returned = deepcopy(sample["actions"][2])
    trigger = {"kind": "absolute", "at_ms": 9000}
    returned.update(start_ms=9000, end_ms=9001)
    returned["resolved_trigger"].update(source=trigger, alignment_anchor_ms=9000, resolved_at_ms=9000)
    returned["action"].update(trigger=trigger, source_board_id="board-interlude",
                               source_activation_id="activation-interlude",
                               expected_object_states={"object-system": "visible", "object-label": "visible",
                                                       "object-evidence": "hidden", "object-arrow": "connected"},
                               expected_object_state_versions={"object-system": 2, "object-label": 2,
                                                               "object-evidence": 1, "object-arrow": 2})
    returned["return_hierarchy_receipt"] = {
        "action_id": "return-1", "destination_board_id": "board-main",
        "destination_activation_id": "activation-return", "hierarchy_basis": retained.model_dump(mode="json"),
        "hierarchy_basis_sha256": retained.checksum(),
    }
    clock["actions"].append(returned)
    clock["coverage"][2]["action_ids"].append("return-1")
    plan["objects"].append({key: deepcopy(value) for key, value in interlude.items()
                            if key in plan["objects"][0]})
    plan["boards"] = deepcopy(layout["boards"])
    plan["actions"] = [deepcopy(row["action"]) for row in clock["actions"]]
    plan["coverage"] = deepcopy(clock["coverage"])
    plan["fallbacks"] = deepcopy(clock["fallbacks"])
    plan["beats"][1]["action_ids"] = ["action-3", "return-1"]
    plan["beats"][1]["continuity"].update(return_from_board_id="board-interlude",
        expected_state_versions=deepcopy(returned["action"]["expected_object_state_versions"]),
        developed_return_state=returned["action"]["destination_state"])
    beat = deepcopy(plan["beats"][1])
    beat.update(beat_id="beat-interlude", board_id="board-interlude", object_ids=["object-interlude"],
                action_ids=["interlude-move"], coverage_ids=["coverage-interlude"], rhetorical_role="example")
    beat["attention"].update(primary_targets=["object-interlude"], secondary_context=[], dimmed_targets=[])
    beat["camera_intent"]["target_ids"] = ["object-interlude"]
    beat["continuity"].update(keep=[], return_from_board_id=None, expected_state_versions={}, developed_return_state=None)
    plan["beats"].append(beat)
    clock["beat_anchors"].append({"beat_id": "beat-interlude", "start_ms": 8000})
    if persist:
        project = persist_relationship(service, project, plan, layout, clock)
    return service, project, plan, layout, clock


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("kind", ["pointer", "network"])
def test_stored_connected_return_duplicate_keeps_relationship_and_read_only_endpoints(tmp_path, portrait, kind):
    service, project, plan, layout, clock = stored_relationship_return(tmp_path, kind, portrait)
    try:
        pid = project["project_id"]
        before = deepcopy((history(service, pid), service.source_timeline.get(pid)))
        expected = {at: compose_png_frame(layout, clock, at).png for at in (4900, 7999, 8500, 9000, 9500)}
        assert expected[4900] == expected[7999] == expected[9000] == expected[9500] != expected[8500]
        prior = evaluate_frame(layout, clock, 7999)
        returned = evaluate_frame(layout, clock, 9500)
        for key in ("object-system", "object-label", "object-arrow"):
            assert prior.object(key) == returned.object(key)
        copy = service.duplicate(pid)
        copied_layout = service.artifact(copy["project_id"], "layout")["document"]
        copied_clock = service.artifact(copy["project_id"], "resolved_timeline")["document"]
        assert copied_layout["objects"] == layout["objects"]
        assert copied_clock["actions"] == clock["actions"]
        for at in (9500, 4900, 8500, 9000, 7999, 4900):
            assert compose_png_frame(copied_layout, copied_clock, at).png == expected[at]
        assert (history(service, pid), service.source_timeline.get(pid)) == before
        assert service.artifact(pid, "storyboard")["document"] == plan
    finally:
        service.store.close()


@pytest.mark.parametrize("kind", ["pointer", "network"])
@pytest.mark.parametrize("field", ["states", "state_versions"])
def test_stored_false_relationship_return_claim_is_atomic(tmp_path, kind, field):
    service, project, plan, layout, clock = stored_relationship_return(tmp_path, kind, persist=False)
    try:
        pid = project["project_id"]
        clock["actions"][-1]["action"][f"expected_object_{field}"]["object-arrow"] = (
            "disconnected" if field == "states" else 3)
        plan["actions"][-1] = deepcopy(clock["actions"][-1]["action"])
        if field == "state_versions":
            plan["beats"][1]["continuity"]["expected_state_versions"]["object-arrow"] = 3
        project = persist_relationship(service, project, plan, layout, clock, persist_clock=False)
        before = deepcopy((service.open(pid), history(service, pid), service.source_timeline.get(pid)))
        with pytest.raises(ProjectError, match="retained board state"):
            service.write(pid, "resolved_timeline", clock, project["revision"])
        assert (service.open(pid), history(service, pid), service.source_timeline.get(pid)) == before
    finally:
        service.store.close()


@pytest.mark.parametrize("kind", ["pointer", "network"])
def test_later_cleanup_invalidates_relationship_timing_without_rewriting_authored_history(tmp_path, kind):
    service, project, _, _, clock = stored_relationship(tmp_path, kind)
    try:
        pid = project["project_id"]
        before = history(service, pid)
        media = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in tmp_path.rglob("*.wav")}
        source = service.source_timeline.get(pid)
        changed = service.edit_source_timeline(pid, "ripple_delete", {"start_ms": 1000, "end_ms": 1100},
            project["revision"], source["timeline_revision"])
        with pytest.raises(ProjectError, match="resolved duration must match"):
            service.runner.preview_v2_source(pid, changed["project"]["revision"], 4450)
        clock.update(project_revision=changed["project"]["revision"],
                     duration_ms=changed["timeline"]["document"]["duration_ms"],
                     cleaned_timeline_revision=changed["timeline"]["timeline_revision"],
                     cleaned_timeline_fingerprint=digest(changed["timeline"]["document"]))
        clock["compilation_fingerprint"] = _resolved_compilation_fingerprint(clock)
        with pytest.raises(ProjectError) as failure:
            service.write(pid, "resolved_timeline", clock, changed["project"]["revision"])
        assert failure.value.code == "stale_contract_basis"
        assert history(service, pid) == before
        assert media == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in tmp_path.rglob("*.wav")}
    finally:
        service.store.close()
