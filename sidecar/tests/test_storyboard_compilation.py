from copy import deepcopy

import pytest

from atme.project_service import ProjectError
from test_v2_resolved_project import stored_v2_basis


def queue_plan(plan, return_trigger, evidence_trigger):
    opening, inspection = plan["beats"]
    model, label, source = plan["objects"]
    draw, highlight, insert = plan["actions"]
    board = plan["boards"][0]
    board.update(object_ids=[model["object_id"], label["object_id"]], expected_prior_state="queue_established",
                 template="flow", creation_reason="Show the order of requests")
    evidence_board = {**board, "board_id": "measurements", "template": "evidence_annotation",
                      "object_ids": [source["object_id"]], "expected_prior_state": None,
                      "creation_reason": "Read the observed queue depth", "activation_policy": "once"}
    plan["boards"].append(evidence_board)
    draw.update(verb="write", trigger={"kind": "absolute", "at_ms": 0})
    model.update(object_type="text", description="First in: A")
    label.update(beat_id="revisit", description="Waiting: B", initial_state="visible")
    source["board_id"] = "measurements"
    opening.update(object_ids=[model["object_id"]], action_ids=[draw["action_id"]],
                   coverage_ids=["coverage-1"], fallback_ids=["fallback-1"])
    inspection.update(board_id="measurements", rhetorical_role="evidence", narration_summary="Read the observed depth")
    inspection["continuity"].update(keep=[], expected_state_versions={}, return_from_board_id=None,
                                    developed_return_state=None, hook_resolution_role="none")
    inspection["attention"].update(secondary_context=[], dimmed_targets=[])
    inspection["evidence"].update(destination_board_id="measurements", claim="One request remains after A is taken",
                                  source_label="Queue event log", annotation="One request remains",
                                  focus_region={"x": 50, "y": 320, "width": 790, "height": 100},
                                  readable_hold_intent_ms=2200)
    insert.update(board_id="measurements", destination_board_id="measurements", trigger=evidence_trigger)
    highlight.update(verb="highlight", expected_state="visible", post_state="highlighted",
                     trigger={"kind": "prior_action", "action_id": "return-1", "offset_ms": 0})
    returned = {"action_id": "return-1", "verb": "return_board", "board_id": board["board_id"],
                "destination_board_id": board["board_id"], "easing": "step", "semantic_reason": "Revisit the queue",
                "prior_destination_activation_id": "queue-opening", "destination_activation_id": "activation-return",
                "post_state": "waiting_explained", "destination_state": "waiting_explained"}
    returned.update(source_board_id="measurements", source_activation_id="measurement-visit",
                    trigger=return_trigger, expected_state="queue_established",
                    expected_object_states={model["object_id"]: "visible", label["object_id"]: "visible"},
                    expected_object_state_versions={model["object_id"]: 2, label["object_id"]: 1},
                    source_instruction_id=highlight["source_instruction_id"], fallback=deepcopy(highlight["fallback"]),
                    coverage_id=highlight["coverage_id"])
    plan["actions"] = [draw, insert, returned, highlight]
    plan["coverage"][1]["action_ids"] = ["return-1", highlight["action_id"]]
    ending = deepcopy(opening)
    ending.update(beat_id="revisit", rhetorical_role="conclusion", narration_summary="Return to the waiting request",
                  object_ids=[label["object_id"]], action_ids=["return-1", highlight["action_id"]],
                  coverage_ids=["coverage-2"], fallback_ids=["fallback-2"])
    ending["attention"].update(primary_targets=[label["object_id"]], secondary_context=[model["object_id"]])
    ending["camera_intent"].update(target_ids=[label["object_id"]])
    ending["continuity"].update(return_from_board_id="measurements", developed_return_state=returned["destination_state"],
                                expected_state_versions=returned["expected_object_state_versions"],
                                hook_resolution_role="resolves_hook")
    plan["conclusion_beat_id"] = ending["beat_id"]
    plan["beats"].append(ending)
    return plan


def test_compile_evidence_and_return_to_the_same_queue(tmp_path):
    service, state, plan, _, _ = stored_v2_basis(tmp_path, real_evidence=True)
    pid = state["project_id"]
    try:
        plan["project_revision"] = state["revision"]
        queue_plan(plan, {"kind": "absolute", "at_ms": 6100}, {"kind": "absolute", "at_ms": 1900})
        try:
            state = service.write(pid, "storyboard", plan, state["revision"])
        except ProjectError as exc:
            pytest.fail(str(exc.detail()))
        result = service.compile_storyboard(pid, state["revision"])
        layout = service.artifact(pid, "layout")["document"]
        clock = service.artifact(pid, "resolved_timeline")["document"]
        assert [v["board_id"] for v in layout["activations"]] == ["board-main", "measurements", "board-main"]
        label = next(obj for obj in layout["objects"] if obj["object_id"] == "object-label")
        assert label["geometry"]["bounds"]["width"] < 260 and label["geometry"]["bounds"]["height"] < 110
        assert label.get("text_inset_px", 0) >= 16
        assert clock["actions"][2]["return_hierarchy_receipt"]["destination_activation_id"] == "activation-return"
        report = service.compilation_report(pid, result["revision"])
        assert report["status"] == "verified" and report["timeline_revision"] == result["artifacts"]["resolved_timeline"]
        assert [beat["board_id"] for beat in report["beats"]] == ["board-main", "measurements", "board-main"]
        assert report["beats"][1]["evidence_hold_ms"] >= 2200
        assert all(len(beat["frame_sha256"]) == 64 and beat["covered_instructions"] for beat in report["beats"])
        from hashlib import sha256
        sampled = report["beats"][1]
        assert sha256(service.preview_project(pid, result["revision"], sampled["preview_at_ms"])["png"]).hexdigest() == sampled["frame_sha256"]
        from atme.render.v2_state import evaluate_frame
        assert evaluate_frame(layout, clock, 7500).object("object-label").state == "highlighted"
        assert evaluate_frame(layout, clock, 1050).object("object-label").state == "visible"
        pictures = [service.preview_project(pid, result["revision"], at)["png"] for at in (1050, 4000, 7500, 1050)]
        assert len(set(pictures)) == 3 and pictures[0] == pictures[3]
    finally:
        service.store.close()


def test_compile_semantic_plan_into_paired_project_artifacts(tmp_path):
    service, state, plan, _, _ = stored_v2_basis(tmp_path, real_evidence=True)
    pid = state["project_id"]
    try:
        # Changing the plan invalidates the previous layout. Only the new semantic plan is input.
        plan["project_revision"] = state["revision"]
        for action, at in zip(plan["actions"], (0, 700, 2000), strict=True):
            action["trigger"] = {"kind": "absolute", "at_ms": at}
        plan["beats"][1]["attention"]["dimmed_targets"] = []
        plan["beats"][1]["camera_intent"]["framing"] = "wide"
        state = service.write(pid, "storyboard", plan, state["revision"])
        rev = state["revision"]
        result = service.compile_storyboard(pid, rev)
        assert result["revision"] == rev + 2
        layout = service.artifact(pid, "layout")
        clock = service.artifact(pid, "resolved_timeline")["document"]
        assert clock["plan_revision"] == rev and clock["layout_revision"] == layout["revision"]
        assert [a["start_ms"] for a in clock["actions"]] == [0, 700, 2000]
        assert clock["evidence_treatments"][0]["asset_checksum_sha256"] == plan["assets"][0]["checksum_sha256"]
        assert len({service.preview_project(pid, result["revision"], t)["png"] for t in (0, 1600, 6000)}) == 3
        assert service.validate_project(pid)["ready"]
        assert service.compile_storyboard(pid, result["revision"])["revision"] == result["revision"]
        assert service.compile_storyboard(pid, result["revision"], "0" * 24)["revision"] == result["revision"]
        caps = service.capabilities()["storyboard_compiler"]
        assert "return_board" in caps["actions"] and "evidence" in caps["object_types"]
        original = deepcopy(layout["document"])
        plan["project_revision"] = result["revision"]
        plan["actions"][-1]["trigger"]["at_ms"] = 9999
        state = service.write(pid, "storyboard", plan, result["revision"])
        with pytest.raises(ProjectError) as caught:
            service.compile_storyboard(pid, state["revision"])
        assert "action-3" in str(caught.value.detail())
        assert service.open(pid)["revision"] == state["revision"]
        assert service.artifact(pid, "layout")["document"] == original
        plan["project_revision"] = state["revision"]
        plan["actions"][-1]["trigger"]["at_ms"] = 2000
        plan["beats"][1]["attention"]["dimmed_targets"] = ["object-label"]
        state = service.write(pid, "storyboard", plan, state["revision"])
        with pytest.raises(ProjectError, match="dim") as missed:
            service.compile_storyboard(pid, state["revision"])
        assert "beat-002" in str(missed.value.detail())
    finally:
        service.store.close()


def test_encoder_reuses_only_unchanged_board_pictures():
    from atme.project_v2_render import picture_samples

    layout = {"objects": [{"object_type": "text"}], "activations": [
        {"start_ms": 0, "end_ms": 599}, {"start_ms": 599, "end_ms": 1000}]}
    clock = {"actions": [{"start_ms": 200, "end_ms": 475, "action": {"verb": "write"}}]}
    samples = list(picture_samples(layout, clock, 10, 10))
    assert samples == [0, 0, 200, 300, 400, 500, 600, 600, 600, 600]
    layout["objects"].append({"object_type": "video"})
    assert list(picture_samples(layout, clock, 10, 10)) == list(range(0, 1000, 100))


def test_compiler_connects_two_named_nodes_without_consuming_a_layout_cell(tmp_path):
    service, state, plan, _, _ = stored_v2_basis(tmp_path, real_evidence=True)
    pid = state["project_id"]
    try:
        plan["project_revision"] = state["revision"]
        for action, at in zip(plan["actions"], (0, 700, 4200), strict=True):
            action["trigger"] = {"kind":"absolute","at_ms":at}
        plan["beats"][1]["attention"]["dimmed_targets"] = []
        plan["beats"][1]["camera_intent"]["framing"] = "wide"
        opening = plan["beats"][0]
        node = plan["objects"][0]
        binding = {"source_object_id":node["object_id"],"source_anchor_id":"out",
                   "destination_object_id":"object-label","destination_anchor_id":"in",
                   "role":"semantic_connector","routing":"straight","allow_self_loop":False}
        link = {**node, "object_id":"flow-link", "object_type":"arrow", "connector_binding":binding,
                "initial_state":"disconnected"}
        plan["objects"].append(link)
        plan["boards"][0]["object_ids"].append("flow-link")
        opening["object_ids"].append("flow-link")
        action = {k:v for k,v in plan["actions"][0].items() if k not in ("target_ids","annotation")}
        action.update(action_id="connect-flow", verb="connect", expected_state="disconnected", post_state="connected", connector_id="flow-link",
                      trigger={"kind":"absolute","at_ms":1900},
                      **{key:binding[key] for key in ("source_object_id","source_anchor_id","destination_object_id","destination_anchor_id")})
        plan["actions"].insert(2, action)
        opening["action_ids"].append("connect-flow")
        plan["coverage"][0]["action_ids"].append("connect-flow")
        plan["fallbacks"][0]["affected_ids"].append("connect-flow")
        state = service.write(pid,"storyboard",plan,state["revision"])
        state = service.compile_storyboard(pid,state["revision"])
        layout = service.artifact(pid,"layout")["document"]
        source, dest = [next(o for o in layout["objects"] if o["object_id"] == key) for key in ("object-system","object-label")]
        assert source["anchors"] == [{"anchor_id":"out","point":{"x":1,"y":.5}}]
        assert dest["anchors"] == [{"anchor_id":"in","point":{"x":0,"y":.5}}]
        assert service.preview_project(pid,state["revision"],1800)["png"] != service.preview_project(pid,state["revision"],2800)["png"]
    finally:
        service.store.close()
