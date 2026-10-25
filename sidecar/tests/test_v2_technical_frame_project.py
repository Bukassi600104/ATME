"""Real native composites preserve immutable project/timing authority and pixels."""

import socket
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

import pytest
from test_v2_registry_project import history
from test_v2_resolved_project import stored_v2_basis
from test_v2_technical_frame_compositor import action_row, composite_documents
from test_v2_technical_frame_contract import CASES
from v2_fixtures import digest

from atme.project_service import ProjectError, _resolved_compilation_fingerprint
from atme.render import v2_state
from atme.render.style_bundle import registry_endpoint_inputs_for_objects
from atme.render.v2_split_paint import verify_split_paint_inputs
from atme.render.v2_svg import (
    _compose_validated_svg_frame,
    _rasterize_svg_frame,
    compose_png_frame,
)
from atme.store.contracts_v2 import ExecutableLayoutV2, ResolvedVisualTimelineV2


def stored_native_basis(tmp_path, kind="browser", state="ready", roles=None, *, portrait=False,
                        later_invalid_move=False):
    profile = "SHORT_FORM_9_16" if portrait else "LONG_FORM_16_9"
    service, project, plan, old_layout, old_timeline = stored_v2_basis(tmp_path, profile=profile)
    pid = project["project_id"]
    layout, timeline = composite_documents(kind, state, roles, portrait=portrait)
    # Preserve the fixture's actual introductory beat and its two instructions;
    # native role identity/coverage belongs to the separate conclusion beat.
    layout["objects"].extend(deepcopy(old_layout["objects"][:2]))
    layout["boards"][0]["object_ids"] = [obj["object_id"] for obj in layout["objects"]]
    timeline["initial_object_states"].extend(deepcopy(old_timeline["initial_object_states"][:2]))
    timeline["actions"] = [*deepcopy(old_timeline["actions"][:2]), *timeline["actions"]]
    timeline["actions"].sort(key=lambda row: row["start_ms"])
    timeline["coverage"] = [*deepcopy(old_timeline["coverage"][:2]), *timeline["coverage"]]
    timeline["fallbacks"] = deepcopy(old_timeline["fallbacks"])
    if later_invalid_move:
        part = next(obj for obj in layout["objects"] if obj["object_id"] == "part-content")
        destination = deepcopy(part["transform"])
        destination["position"]["x"] += 500.
        row = action_row(timeline["actions"][1], {"verb": "move", "target_ids": [part["object_id"]],
            "destination": destination, "opacity": None, "easing": "linear"}, 4000, 5000, "part-outside")
        timeline["actions"].append(row)
        next(item for item in timeline["coverage"] if item["coverage_id"] == row["action"]["coverage_id"])[
            "action_ids"].append(row["action"]["action_id"])
    fields = {"object_id", "object_type", "board_id", "beat_id", "semantic_role", "description",
        "asset_id", "initial_state", "coverage_ids", "technical_frame", "child_ids"}
    plan["objects"] = [{key: deepcopy(value) for key, value in obj.items() if key in fields}
        for obj in layout["objects"]]
    plan["boards"] = deepcopy(layout["boards"])
    plan["assets"] = []
    plan["actions"] = [deepcopy(row["action"]) for row in timeline["actions"]]
    plan["coverage"] = deepcopy(timeline["coverage"])
    plan["fallbacks"] = deepcopy(timeline["fallbacks"])
    for beat in plan["beats"]:
        beat["object_ids"] = [obj["object_id"] for obj in plan["objects"] if obj["beat_id"] == beat["beat_id"]]
        beat["action_ids"] = [row["action_id"] for row in plan["actions"] if row["coverage_id"] in beat["coverage_ids"]]
        beat["evidence"] = None
    plan["project_revision"] = project["revision"]
    project = service.write(pid, "storyboard", plan, project["revision"])
    layout.update(project_id=pid, project_revision=project["revision"],
        plan_revision=project["artifacts"]["storyboard"], plan_sha256=digest(plan))
    project = service.write(pid, "layout", layout, project["revision"])
    source = service.source_timeline.get(pid)
    timeline.update(project_id=pid, project_revision=project["revision"],
        plan_revision=project["artifacts"]["storyboard"], plan_sha256=digest(plan),
        layout_revision=project["artifacts"]["layout"], layout_sha256=digest(layout),
        cleaned_timeline_revision=source["timeline_revision"], cleaned_timeline_fingerprint=digest(source["document"]))
    timeline["compilation_fingerprint"] = _resolved_compilation_fingerprint(timeline)
    return service, project, plan, layout, timeline


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("fault", ["anchor", "role_fit"])
def test_new_layout_write_rejects_initial_physical_incoherence_atomically(tmp_path, portrait, fault):
    service, project, _, layout, _ = stored_native_basis(tmp_path, portrait=portrait)
    try:
        pid = project["project_id"]
        before = deepcopy((service.open(pid), history(service, pid), service.source_timeline.get(pid)))
        candidate = deepcopy(layout)
        candidate["project_revision"] = project["revision"]
        objects = {obj["object_id"]: obj for obj in candidate["objects"]}
        if fault == "anchor":
            objects["object-evidence"]["anchors"][0]["point"]["x"] += .01
        else:
            objects["part-content"]["transform"]["position"]["x"] += 500.
        # Old contract parsing/migration remains lossless; only normal new writes
        # acquire the pure physical-coherence gate.
        ExecutableLayoutV2.model_validate(candidate)
        service._serialized_artifact("layout", candidate, legacy_migration=True)
        with pytest.raises(ProjectError) as failure:
            service.write(pid, "layout", candidate, project["revision"])
        assert failure.value.code == "invalid_artifact"
        assert "technical_frame" in str(failure.value.errors)
        assert (service.open(pid), history(service, pid), service.source_timeline.get(pid)) == before
    finally:
        service.store.close()


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("kind,states,roles", CASES)
def test_six_native_kinds_store_and_duplicate_exact_authored_identity(tmp_path, kind, states, roles, portrait):
    service, project, plan, layout, timeline = stored_native_basis(tmp_path, kind, states[0], roles, portrait=portrait)
    try:
        pid = project["project_id"]
        project = service.write(pid, "resolved_timeline", timeline, project["revision"])
        before = deepcopy((history(service, pid), service.source_timeline.get(pid)))
        media = {str(path): sha256(path.read_bytes()).hexdigest() for path in tmp_path.rglob("*.wav")}
        copy = service.duplicate(pid)
        copy_id = copy["project_id"]
        docs = {}
        assert copy["revision"] == project["revision"]
        for artifact_kind, original in (("storyboard", plan), ("layout", layout), ("resolved_timeline", timeline)):
            source_record = service.artifact(pid, artifact_kind)
            record = service.artifact(copy_id, artifact_kind)
            assert source_record["document"] == original
            docs[artifact_kind] = record["document"]
            assert docs[artifact_kind]["project_id"] == copy_id != pid
            # Counters are preserved in an independent project namespace. It is
            # the project identity, lineage and content hashes that are rebound.
            assert docs[artifact_kind]["project_revision"] == original["project_revision"]
            assert record["revision"] == source_record["revision"]
            assert record["duplicate_derivation"]["source_project_id"] == pid
            assert record["duplicate_derivation"]["source_sha256"] == digest(original)
            assert record["duplicate_derivation"]["copied_sha256"] == digest(docs[artifact_kind])
        assert docs["storyboard"]["objects"] == plan["objects"]
        assert docs["layout"]["objects"] == layout["objects"]
        assert docs["storyboard"]["narrative_authority"] == plan["narrative_authority"]
        assert docs["layout"]["plan_sha256"] == docs["resolved_timeline"]["plan_sha256"] == digest(docs["storyboard"])
        assert docs["resolved_timeline"]["layout_sha256"] == digest(docs["layout"])
        assert docs["resolved_timeline"]["compilation_fingerprint"] == _resolved_compilation_fingerprint(docs["resolved_timeline"])
        assert docs["resolved_timeline"]["cleaned_timeline_fingerprint"] == timeline["cleaned_timeline_fingerprint"]
        assert service.source_timeline.get(copy_id)["document"] == before[1]["document"]
        assert (history(service, pid), service.source_timeline.get(pid)) == before
        assert media == {str(path): sha256(path.read_bytes()).hexdigest() for path in tmp_path.rglob("*.wav")}
    finally:
        service.store.close()


@pytest.mark.parametrize("portrait", [False, True])
def test_stored_and_duplicate_native_pixels_match_frozen_offline_seek(tmp_path, portrait, monkeypatch):
    service, project, _, layout, timeline = stored_native_basis(tmp_path, portrait=portrait)
    try:
        pid = project["project_id"]
        project = service.write(pid, "resolved_timeline", timeline, project["revision"])
        copy = service.duplicate(pid)
        copy_id = copy["project_id"]
        before = (history(service, pid), history(service, copy_id))
        copy_layout = service.artifact(copy_id, "layout")["document"]
        copy_timeline = service.artifact(copy_id, "resolved_timeline")["document"]
        def forbidden(*args, **kwargs):
            raise AssertionError("native stored/frozen history attempted live IO or v1 fallback")
        monkeypatch.setattr(socket, "create_connection", forbidden)
        monkeypatch.setattr(socket.socket, "connect", forbidden)
        monkeypatch.setattr("atme.render.animator._FrameRenderer", forbidden)
        expected = {}
        for at in (0, 500, 1000):
            expected[at] = compose_png_frame(layout, timeline, at).png
            for target in (project, copy):
                frame = service.runner.preview_v2_source(target["project_id"], target["revision"], at)
                assert frame["png"] == expected[at]
                assert (frame["width"], frame["height"]) == ((720, 1280) if portrait else (1280, 720))
        assert len(set(expected.values())) == 3
        typed, resolved = ExecutableLayoutV2.model_validate(copy_layout), ResolvedVisualTimelineV2.model_validate(copy_timeline)
        inputs = verify_split_paint_inputs(typed, {})
        registry = registry_endpoint_inputs_for_objects({obj.object_id: obj for obj in typed.objects},
            frozen_files={name: raw for name, _, raw in inputs.bundle_bytes})
        monkeypatch.setattr(Path, "read_bytes", forbidden)
        for at in (1000, 0, 500, 1000):
            sample = v2_state._evaluate_frame_with_registry_inputs(copy_layout, copy_timeline, at, registry)
            frame = _compose_validated_svg_frame(typed, resolved, sample, {}, split_inputs=inputs)
            assert _rasterize_svg_frame(typed, frame, split_inputs=inputs).png == expected[at]
        assert (history(service, pid), history(service, copy_id)) == before
        assert service.capabilities()["visual_contracts"]["renderer_versions"] == ["1"]
    finally:
        service.store.close()


@pytest.mark.parametrize("portrait", [False, True])
def test_resolved_native_history_rejects_later_out_of_frame_content_atomically(tmp_path, portrait):
    service, project, _, _, timeline = stored_native_basis(tmp_path, portrait=portrait, later_invalid_move=True)
    try:
        pid = project["project_id"]
        before = deepcopy((service.open(pid), history(service, pid), service.source_timeline.get(pid)))
        with pytest.raises(ProjectError, match="technical_frame") as failure:
            service.write(pid, "resolved_timeline", timeline, project["revision"])
        assert failure.value.code == "invalid_artifact"
        assert (service.open(pid), history(service, pid), service.source_timeline.get(pid)) == before
    finally:
        service.store.close()


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("fault", ["semantic_binding", "parent", "order"])
def test_native_semantic_and_ownership_write_failures_are_atomic(tmp_path, portrait, fault):
    service, project, _, layout, _ = stored_native_basis(tmp_path, portrait=portrait)
    try:
        pid = project["project_id"]
        before = deepcopy((service.open(pid), history(service, pid), service.source_timeline.get(pid)))
        candidate = deepcopy(layout)
        candidate["project_revision"] = project["revision"]
        objects = {obj["object_id"]: obj for obj in candidate["objects"]}
        if fault == "semantic_binding":
            chrome = objects["object-evidence"]
            chrome["variant"] = chrome["technical_frame"]["display_state"] = "error"
            # This is a valid physical frame. Only the exact approved semantic
            # binding differs; rehashing the layout must not grant authority.
            service._serialized_artifact("layout", candidate)
        elif fault == "parent":
            objects["part-content"]["parent_id"] = None
        else:
            objects["list-group"]["child_ids"][1:3] = list(reversed(objects["list-group"]["child_ids"][1:3]))
        with pytest.raises(ProjectError) as failure:
            service.write(pid, "layout", candidate, project["revision"])
        assert failure.value.code == "invalid_artifact"
        expected_error = "disagree on parentage" if fault == "parent" else "technical_frame"
        assert expected_error in str(failure.value.errors)
        assert (service.open(pid), history(service, pid), service.source_timeline.get(pid)) == before
    finally:
        service.store.close()


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("fault", ["plan_hash", "layout_hash", "cleaned_hash", "cleaned_revision", "timing_changed", "script_changed"])
def test_coherently_rehashed_native_timeline_cannot_claim_stale_authority(tmp_path, portrait, fault):
    service, project, _, _, timeline = stored_native_basis(tmp_path, portrait=portrait)
    try:
        pid = project["project_id"]
        media = {str(path): sha256(path.read_bytes()).hexdigest() for path in tmp_path.rglob("*.wav")}
        if fault == "timing_changed":
            source = service.source_timeline.get(pid)
            edited = service.source_timeline.command(pid, "split",
                {"clip_id": source["document"]["clips"][0]["clip_id"], "at_ms": 5000},
                project["revision"], source["timeline_revision"])
            project = edited["project"]
        elif fault == "script_changed":
            script = service.artifact(pid, "script")["document"]
            project = service.write(pid, "script", script, project["revision"])
        candidate = deepcopy(timeline)
        candidate["project_revision"] = project["revision"]
        if fault in {"plan_hash", "layout_hash", "cleaned_hash"}:
            field = {"plan_hash": "plan_sha256", "layout_hash": "layout_sha256",
                "cleaned_hash": "cleaned_timeline_fingerprint"}[fault]
            candidate[field] = "0" * 64
        elif fault == "cleaned_revision":
            candidate["cleaned_timeline_revision"] += 1
        candidate["compilation_fingerprint"] = _resolved_compilation_fingerprint(candidate)
        ResolvedVisualTimelineV2.model_validate(candidate)
        before = deepcopy((service.open(pid), history(service, pid), service.source_timeline.get(pid)))
        with pytest.raises(ProjectError) as failure:
            service.write(pid, "resolved_timeline", candidate, project["revision"])
        assert failure.value.code == "stale_contract_basis"
        assert (service.open(pid), history(service, pid), service.source_timeline.get(pid)) == before
        assert media == {str(path): sha256(path.read_bytes()).hexdigest() for path in tmp_path.rglob("*.wav")}
    finally:
        service.store.close()
