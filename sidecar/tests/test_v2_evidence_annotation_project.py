"""P3-36 owning evidence through actual immutable project and native boundaries."""

import builtins
import socket
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

import pytest
from atme.project_assets import read_verified_split_asset_bytes
from atme.project_service import ProjectError
from atme.render import v2_state
from atme.render.style_bundle import registry_endpoint_inputs_for_objects
from atme.render.v2_hierarchy import HierarchySnapshot
from atme.render.v2_hierarchy_replay import completed_hierarchy_basis
from atme.render.v2_split_paint import verify_split_paint_inputs
from atme.render.v2_svg import (
    _compose_validated_svg_frame,
    _rasterize_svg_frame,
    compose_png_frame,
)
from atme.store.contracts_v2 import ExecutableLayoutV2, ResolvedVisualTimelineV2
from test_v2_evidence_annotation_objects import cross_annotation_documents
from test_v2_evidence_apertures import aperture_documents
from test_v2_group_annotation import consumer_clock
from test_v2_mask_contract import MASK_FIELDS
from test_v2_pointer_project import persist_relationship
from test_v2_registry_project import history
from test_v2_resolved_project import stored_v2_basis
from test_v2_return_board import return_documents
from test_v2_timeline_replay import resolved
from v2_fixtures import digest, executable_layout_v2, resolved_timeline_v2


def add_evidence_return(plan, layout, clock):
    """Author A/B/A explicitly; derive its receipt from the real prefix history."""
    layout["boards"][0]["expected_prior_state"] = "system_established"
    layout["activations"][0]["end_ms"] = 8000
    interlude = deepcopy(layout["objects"][0])
    interlude.update(object_id="object-interlude", board_id="board-interlude", beat_id="beat-interlude",
                     coverage_ids=["coverage-interlude"], initial_state="visible", visible=True, z_index=0)
    layout["objects"].append(interlude)
    board = deepcopy(layout["boards"][0])
    board.update(board_id="board-interlude", object_ids=["object-interlude"], density_limit=1,
                 persistence_policy="single_beat", activation_policy="once", expected_prior_state=None)
    layout["boards"].append(board)
    layout["activations"].extend([
        {"activation_id": "activation-interlude", "board_id": "board-interlude", "start_ms": 8000,
             "end_ms": 9000, "reason": "Inspect a separate authored example"},
        {"activation_id": "activation-return", "board_id": "board-main", "start_ms": 9000,
             "end_ms": 10000, "reason": "Return to the retained evidence and annotation"},
    ])
    clock["initial_object_states"].append({"object_id": "object-interlude", "state": "visible",
                                               "visible": True, "state_version": 1})
    action = deepcopy(clock["actions"][0]["action"])
    action.pop("annotation", None)
    action.update(action_id="interlude-move", source_instruction_id="instruction-interlude", verb="move",
                  board_id="board-interlude", coverage_id="coverage-interlude", target_ids=["object-interlude"],
                  easing="linear", expected_state="visible", post_state="visible",
                  destination=deepcopy(interlude["transform"]), fallback={"fallback_id": "fallback-3", "on_failure": "block"})
    action["destination"]["position"]["x"] += 120
    clock["actions"].append(resolved(action, 8200, 8500).model_dump(mode="json"))
    clock["coverage"].append({"coverage_id": "coverage-interlude", "instruction_id": "instruction-interlude",
                                  "status": "executed", "action_ids": ["interlude-move"], "fallback_id": None})
    clock["fallbacks"][2]["affected_ids"].append("instruction-interlude")
    clock["layout_sha256"] = digest(layout)
    _, replay, _ = consumer_clock(layout, clock)
    sample = replay.at(9000)
    owned = {f.object_id: f for f in sample.objects if f.board_id == "board-main"}
    retained = completed_hierarchy_basis(HierarchySnapshot(tuple(
        n for n in sample.hierarchy.nodes if n.board_id == "board-main")), owned)
    returned = deepcopy(return_documents()[1]["actions"][2])
    trigger = {"kind": "absolute", "at_ms": 9000}
    returned.update(start_ms=9000, end_ms=9001)
    returned["resolved_trigger"].update(source=trigger, alignment_anchor_ms=9000, resolved_at_ms=9000)
    returned["action"].update(trigger=trigger, source_board_id="board-interlude",
        source_activation_id="activation-interlude", expected_object_states={key: f.state for key, f in owned.items()},
        expected_object_state_versions={key: dict(sample.state_versions)[key] for key in owned})
    returned["return_hierarchy_receipt"] = {"action_id": "return-1", "destination_board_id": "board-main",
        "destination_activation_id": "activation-return", "hierarchy_basis": retained.model_dump(mode="json"),
        "hierarchy_basis_sha256": retained.checksum()}
    clock["actions"].append(returned)
    clock["coverage"][2]["action_ids"].append("return-1")
    second = plan["beats"][1]
    mask_sources = {obj["mask_source_object_id"] for obj in layout["objects"] if obj["object_type"] == "mask"}
    second["continuity"].update(return_from_board_id="board-interlude",
        # Semantic continuity directs visible content, not nonpainting mask shapes.
        # The actual return action and hierarchy receipt retain their full inventory.
        expected_state_versions={key: value for key, value in returned["action"]["expected_object_state_versions"].items()
                                 if key not in mask_sources},
        developed_return_state=returned["action"]["destination_state"])
    beat = deepcopy(second)
    beat.update(beat_id="beat-interlude", board_id="board-interlude", object_ids=["object-interlude"],
                action_ids=["interlude-move"], coverage_ids=["coverage-interlude"], evidence=None,
                rhetorical_role="example")
    beat["attention"].update(primary_targets=["object-interlude"], secondary_context=[], dimmed_targets=[])
    beat["continuity"].update(keep=[], change=[], remove=[], replacements={}, return_from_board_id=None,
                              expected_state_versions={}, developed_return_state=None)
    beat["camera_intent"]["target_ids"] = ["object-interlude"]
    plan["beats"].append(beat)
    clock["beat_anchors"].append({"beat_id": "beat-interlude", "start_ms": 8200})


def stored_evidence_runtime(tmp_path, kind="cross", portrait=False, *, persist_clock=True):
    profile = "SHORT_FORM_9_16" if portrait else "LONG_FORM_16_9"
    service, project, plan, _, original_clock = stored_v2_basis(tmp_path, real_evidence=True, profile=profile)
    if kind == "aperture":
        permissions = ["crop", "scale", "annotate", "color_treatment", "mask", "rotate"]
        asset = service.attach_evidence_file(project["project_id"], tmp_path / "source-evidence.png",
            "source-evidence.png", project["revision"], plan["assets"][0]["provenance"], permissions)["asset"]
        project = service.open(project["project_id"])
        plan["assets"][0].update(asset_id=asset["asset_id"], revision=asset["revision"],
            managed_ref=asset["resource_uri"], checksum_sha256=asset["sha256"], width=asset["width"],
            height=asset["height"], provenance=asset["provenance"], allowed_transformations=permissions)
        plan["objects"][2]["asset_id"] = asset["asset_id"]
        plan["actions"][2]["evidence_asset_id"] = asset["asset_id"]
        plan["beats"][1]["evidence"]["evidence_asset_id"] = asset["asset_id"]
        original_clock["resolved_assets"][0].update(asset_id=asset["asset_id"], revision=asset["revision"],
            managed_ref=asset["resource_uri"], byte_length=asset["bytes"], allowed_transformations=permissions)
        layout = executable_layout_v2(plan)
        layout["objects"][2]["asset_id"] = asset["asset_id"]
        if portrait:
            layout["objects"][2]["geometry"]["bounds"].update(x=110, y=540)
        layout, clock = aperture_documents("ellipse", documents=(layout, resolved_timeline_v2(plan, layout)))
    else:
        template, layout, clock = cross_annotation_documents()
        plan["objects"] = deepcopy(template["objects"])
        plan["beats"] = deepcopy(template["beats"])
        asset_id = plan["assets"][0]["asset_id"]
        plan["objects"][2]["asset_id"] = asset_id
        plan["beats"][1]["evidence"]["evidence_asset_id"] = asset_id
        layout["objects"][2]["asset_id"] = asset_id
        layout["evidence_treatments"] = executable_layout_v2(plan)["evidence_treatments"]
        clock["actions"][2]["action"]["evidence_asset_id"] = asset_id
        clock["actions"][2]["action"]["easing"] = "linear"
        if portrait:
            layout["objects"][2]["geometry"]["bounds"].update(x=110, y=540)
            layout["objects"][-2]["geometry"]["bounds"].update(x=110, y=1000, width=500)
            layout["objects"][-1]["geometry"]["bounds"] = {"x": 0, "y": 0, "width": 720, "height": 1280}
    layout["output_profile"] = deepcopy(plan["output_profile"])
    layout["canvas"].update(width=plan["output_profile"]["width"], height=plan["output_profile"]["height"])
    clock.update(output_profile=deepcopy(plan["output_profile"]), resolved_assets=deepcopy(original_clock["resolved_assets"]),
                 evidence_treatments=deepcopy(layout["evidence_treatments"]))
    add_evidence_return(plan, layout, clock)
    fields = set(plan["objects"][0]) | {"child_ids", *MASK_FIELDS}
    plan["objects"] = [{key: deepcopy(value) for key, value in obj.items() if key in fields}
                       for obj in layout["objects"]]
    plan["boards"] = deepcopy(layout["boards"])
    plan["actions"] = [deepcopy(row["action"]) for row in clock["actions"]]
    plan["coverage"], plan["fallbacks"] = deepcopy(clock["coverage"]), deepcopy(clock["fallbacks"])
    for beat in plan["beats"]:
        beat["object_ids"] = [obj["object_id"] for obj in plan["objects"] if obj["beat_id"] == beat["beat_id"]]
        beat["action_ids"] = [row["action_id"] for row in plan["actions"] if row["coverage_id"] in beat["coverage_ids"]]
    project = persist_relationship(service, project, plan, layout, clock, persist_clock=persist_clock)
    return service, project, plan, layout, clock


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("kind", ["cross", "aperture"])
def test_stored_evidence_duplicate_return_preview_and_frozen_offline_pixels(tmp_path, kind, portrait, monkeypatch):
    service, project, plan, layout, clock = stored_evidence_runtime(tmp_path, kind, portrait)
    try:
        pid = project["project_id"]
        if kind == "aperture":
            mask_sources = {obj["mask_source_object_id"] for obj in layout["objects"] if obj["object_type"] == "mask"}
            returned = clock["actions"][-1]
            assert mask_sources
            assert mask_sources.isdisjoint(plan["beats"][1]["continuity"]["expected_state_versions"])
            assert mask_sources.issubset(returned["action"]["expected_object_states"])
            assert mask_sources.issubset(returned["action"]["expected_object_state_versions"])
            assert mask_sources.issubset({row["object_id"] for row in
                                         returned["return_hierarchy_receipt"]["hierarchy_basis"]["placements"]})
        original = history(service, pid)
        source = deepcopy(service.source_timeline.get(pid))
        media = {str(p): sha256(p.read_bytes()).hexdigest() for p in tmp_path.rglob("*.wav")}
        assert media
        original_assets = deepcopy(service.list_assets(pid))
        original_images = {str(p): sha256(p.read_bytes()).hexdigest() for p in tmp_path.rglob("*.png")}
        assert original_images
        verified = service.render_evidence_bytes(pid, clock["resolved_assets"][0], layout["evidence_treatments"][0])
        payload = {verified.asset_id: verified}
        times = (3999, 4300, 4750, 4900, 7999, 8500, 9000, 9500)
        expected = {at: compose_png_frame(layout, clock, at, payload).png for at in times}
        assert len({sha256(expected[at]).hexdigest() for at in (3999, 4300, 4900)}) == 3
        assert sha256(expected[4900]).hexdigest() == sha256(expected[9000]).hexdigest()
        assert service.runner.preview_v2_source(pid, project["revision"], 4750)["png"] == expected[4750]
        duplicate = service.duplicate(pid)
        copied_id = duplicate["project_id"]
        records = {name: service.artifact(copied_id, name) for name in ("storyboard", "layout", "resolved_timeline")}
        copied_plan, copied_layout, copied_clock = (row["document"] for row in records.values())
        for name, old in (("storyboard", plan), ("layout", layout), ("resolved_timeline", clock)):
            record = records[name]
            assert service.artifact(pid, name)["document"] == old
            assert record["document"]["project_id"] == copied_id != pid
            assert record["duplicate_derivation"]["source_project_id"] == pid
            assert record["duplicate_derivation"]["source_revision"] == project["artifacts"][name]
            assert record["duplicate_derivation"]["source_sha256"] == digest(old)
            assert record["duplicate_derivation"]["copied_sha256"] == digest(record["document"])
        assert copied_plan["narrative_authority"] == plan["narrative_authority"]
        assert copied_clock["actions"] == clock["actions"]
        assert service.runner.preview_v2_source(copied_id, duplicate["revision"], 9000)["png"] == expected[9000]
        typed = ExecutableLayoutV2.model_validate(copied_layout)
        resolved_clock = ResolvedVisualTimelineV2.model_validate(copied_clock)
        pins = [{"asset_id": row["asset_id"], "revision": row["revision"], "resource_uri": row["resource_uri"],
                     "checksum_sha256": row["sha256"]} for row in service.list_assets(copied_id)
                if row["asset_id"] in {obj.asset_id for obj in typed.objects}]
        assets = read_verified_split_asset_bytes(service, typed, resolved_clock.resolved_assets, pins)
        inputs = verify_split_paint_inputs(typed, assets)  # Frozen bytes only, no Split family admission.
        registry = registry_endpoint_inputs_for_objects({obj.object_id: obj for obj in typed.objects},
            frozen_files={name: raw for name, _, raw in inputs.bundle_bytes})
        assert history(service, pid) == original
        assert service.source_timeline.get(pid) == source
        assert media == {str(p): sha256(p.read_bytes()).hexdigest() for p in tmp_path.rglob("*.wav")}
        assert service.list_assets(pid) == original_assets
        assert all(sha256(Path(path).read_bytes()).hexdigest() == checksum
                   for path, checksum in original_images.items())
        assert service.render_evidence_bytes(pid, clock["resolved_assets"][0],
            layout["evidence_treatments"][0]).sha256 == verified.sha256
        path_open, builtin_open = Path.open, builtins.open
        def write_only(opener, path, mode="r", *args, **kwargs):
            if "r" in mode or "+" in mode or not any(flag in mode for flag in ("w", "a", "x")):
                pytest.fail("frozen evidence reopened a file for reading")
            return opener(path, mode, *args, **kwargs)
        monkeypatch.setattr(Path, "read_bytes", lambda *_: pytest.fail("frozen evidence reopened a file"))
        monkeypatch.setattr(Path, "open", lambda p, mode="r", *a, **kw: write_only(path_open, p, mode, *a, **kw))
        monkeypatch.setattr(builtins, "open", lambda p, mode="r", *a, **kw: write_only(builtin_open, p, mode, *a, **kw))
        monkeypatch.setattr(socket, "create_connection", lambda *_a, **_kw: pytest.fail("evidence used network"))
        monkeypatch.setattr(socket.socket, "connect", lambda *_a, **_kw: pytest.fail("evidence used network"))
        held = ({"action-3": v2_state._evaluate_frame_with_registry_inputs(copied_layout, copied_clock, 4900, registry)}
                if kind == "cross" else {})
        for at in (9500, 4300, 9000, 3999, 4750, 8500, 4900):
            snapshot = v2_state._evaluate_frame_with_registry_inputs(copied_layout, copied_clock, at, registry)
            frame = _compose_validated_svg_frame(typed, resolved_clock, snapshot, held, assets, split_inputs=inputs)
            actual = _rasterize_svg_frame(typed, frame, split_inputs=inputs).png
            assert sha256(actual).hexdigest() == sha256(expected[at]).hexdigest()
        assert service.capabilities()["visual_contracts"]["renderer_versions"] == ["1"]
    finally:
        service.store.close()


@pytest.mark.parametrize("object_id,field", [("object-evidence", "versions"), ("evidence-note", "versions"),
                                             ("evidence-leader", "states")])
def test_stored_return_cannot_rehash_false_retained_evidence_annotation_history(tmp_path, object_id, field):
    service, project, _, _, clock = stored_evidence_runtime(tmp_path, persist_clock=False)
    try:
        pid = project["project_id"]
        before, source = history(service, pid), deepcopy(service.source_timeline.get(pid))
        values = clock["actions"][-1]["action"][f"expected_object_state_{field}" if field == "versions"
                                               else "expected_object_states"]
        values[object_id] = values[object_id] + 1 if field == "versions" else "hidden"
        from atme.project_service import _resolved_compilation_fingerprint
        clock["compilation_fingerprint"] = _resolved_compilation_fingerprint(clock)
        with pytest.raises(ProjectError):
            service.write(pid, "resolved_timeline", clock, project["revision"])
        assert history(service, pid) == before
        assert service.source_timeline.get(pid) == source
    finally:
        service.store.close()


def test_actual_project_write_rejects_legacy_cross_intent_without_authored_policy_atomically(tmp_path):
    service, project, plan, _, _ = stored_evidence_runtime(tmp_path, persist_clock=False)
    try:
        pid = project["project_id"]
        before, source = history(service, pid), deepcopy(service.source_timeline.get(pid))
        invalid = deepcopy(plan)
        invalid["project_revision"] = project["revision"]
        invalid["beats"][1]["evidence"].pop("annotation_policy")
        with pytest.raises(ProjectError):
            service.write(pid, "storyboard", invalid, project["revision"])
        assert history(service, pid) == before
        assert service.source_timeline.get(pid) == source
    finally:
        service.store.close()
