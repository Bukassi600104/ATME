"""P3-28 authored relationship authority through the real project boundary."""

from __future__ import annotations

import builtins
import hashlib
import io
import socket
from copy import deepcopy
from pathlib import Path

import pytest
from atme.project_assets import read_verified_split_asset_bytes
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
from PIL import Image
from test_v2_pointer_runtime import pointer_runtime_documents
from test_v2_registry_project import history
from test_v2_resolved_project import stored_v2_basis
from v2_fixtures import digest


def stored_relationship(tmp_path, kind="pointer", portrait=False, *, persist=True):
    profile = "SHORT_FORM_9_16" if portrait else "LONG_FORM_16_9"
    service, project, plan, _, _ = stored_v2_basis(tmp_path, profile=profile)
    layout, clock = pointer_runtime_documents(kind=kind, portrait=portrait, managed=True)
    connector = layout["objects"][3]
    connector["beat_id"] = "beat-002"
    shared = {"object_id", "object_type", "board_id", "beat_id", "semantic_role",
              "description", "asset_id", "initial_state", "coverage_ids"}
    plan["objects"] = [{key: deepcopy(value) for key, value in obj.items() if key in shared}
                       for obj in layout["objects"]]
    binding_keys = {"source_object_id", "source_anchor_id", "destination_object_id",
                    "destination_anchor_id", "role", "routing", "allow_self_loop", "source_point"}
    plan["objects"][3]["connector_binding"] = {
        key: deepcopy(value) for key, value in connector.items() if key in binding_keys}
    plan["assets"] = []
    plan["boards"] = deepcopy(layout["boards"])
    plan["actions"] = [deepcopy(row["action"]) for row in clock["actions"]]
    plan["coverage"] = deepcopy(clock["coverage"])
    plan["fallbacks"] = deepcopy(clock["fallbacks"])
    for beat in plan["beats"]:
        beat["evidence"] = None
        beat["object_ids"] = [obj["object_id"] for obj in plan["objects"]
                              if obj["beat_id"] == beat["beat_id"]]
        beat["action_ids"] = [action["action_id"] for action in plan["actions"]
                              if action["coverage_id"] in beat["coverage_ids"]]
    second = plan["beats"][1]
    second["attention"]["primary_targets"] = ["object-arrow"]
    second["camera_intent"]["target_ids"] = ["object-arrow"]
    second["continuity"].update(return_from_board_id=None, expected_state_versions={},
                                 developed_return_state=None)
    clock["resolved_assets"] = []
    if not persist:
        return service, project, plan, layout, clock
    project = persist_relationship(service, project, plan, layout, clock)
    return service, project, plan, layout, clock


def persist_relationship(service, project, plan, layout, clock, *, persist_clock=True):
    pid = project["project_id"]
    plan.update(project_id=pid, project_revision=project["revision"])
    project = service.write(pid, "storyboard", plan, project["revision"])
    layout.update(project_id=pid, project_revision=project["revision"],
                  plan_revision=project["artifacts"]["storyboard"], plan_sha256=digest(plan))
    project = service.write(pid, "layout", layout, project["revision"])
    timing = service.source_timeline.get(pid)
    clock.update(project_id=pid, project_revision=project["revision"],
                 plan_revision=project["artifacts"]["storyboard"], plan_sha256=digest(plan),
                 layout_revision=project["artifacts"]["layout"], layout_sha256=digest(layout),
                 cleaned_timeline_revision=timing["timeline_revision"],
                 cleaned_timeline_fingerprint=digest(timing["document"]))
    clock["compilation_fingerprint"] = _resolved_compilation_fingerprint(clock)
    return service.write(pid, "resolved_timeline", clock, project["revision"]) if persist_clock else project


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("kind", ["pointer", "network"])
def test_stored_relationship_duplicate_preview_and_frozen_offline_pixels(tmp_path, portrait, kind, monkeypatch):
    service, project, plan, layout, clock = stored_relationship(tmp_path, kind, portrait)
    try:
        pid = project["project_id"]
        original_history = history(service, pid)
        original_source = deepcopy(service.source_timeline.get(pid))
        media = {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                 for path in tmp_path.rglob("*.wav")}
        assert media, "This project must use a real source recording"
        expected = {at: compose_png_frame(layout, clock, at).png
                    for at in (3999, 4450, 4900, 6450, 6900)}
        assert expected[3999] != expected[4450] != expected[4900]
        assert expected[3999] == expected[6900]
        image = Image.open(io.BytesIO(expected[4900])).convert("RGB")
        assert image.size == ((720, 1280) if portrait else (1280, 720))
        if kind == "pointer":
            assert image.getpixel((81, 61)) != (250, 248, 241)
        (tmp_path / f"stored-{kind}-connected.png").write_bytes(expected[4900])
        assert service.runner.preview_v2_source(pid, project["revision"], 4450)["png"] == expected[4450]
        duplicate = service.duplicate(pid)
        copy_id = duplicate["project_id"]
        records = {name: service.artifact(copy_id, name)
                   for name in ("storyboard", "layout", "resolved_timeline")}
        copies = {name: record["document"] for name, record in records.items()}
        copied_plan, copied_layout, copied_clock = (copies[name] for name in copies)
        for name, original in (("storyboard", plan), ("layout", layout), ("resolved_timeline", clock)):
            assert service.artifact(pid, name)["document"] == original
            assert copies[name]["project_id"] == copy_id != pid
            lineage = records[name]["duplicate_derivation"]
            assert lineage["source_project_id"] == pid
            assert lineage["source_revision"] == project["artifacts"][name]
            assert lineage["source_sha256"] == digest(original)
            assert lineage["copied_sha256"] == digest(copies[name])
        assert copied_plan["objects"] == plan["objects"]
        assert copied_plan["narrative_authority"] == plan["narrative_authority"]
        assert copied_layout["objects"] == layout["objects"]
        assert copied_clock["actions"] == clock["actions"]
        assert copied_clock["cleaned_timeline_fingerprint"] == clock["cleaned_timeline_fingerprint"]
        assert copied_clock["plan_sha256"] == digest(copied_plan)
        assert copied_clock["layout_sha256"] == digest(copied_layout)
        assert copied_clock["compilation_fingerprint"] == _resolved_compilation_fingerprint(copied_clock)
        assert service.runner.preview_v2_source(copy_id, duplicate["revision"], 4900)["png"] == expected[4900]
        typed = ExecutableLayoutV2.model_validate(copied_layout)
        resolved = ResolvedVisualTimelineV2.model_validate(copied_clock)
        pins = [{"asset_id": row["asset_id"], "revision": row["revision"],
                 "resource_uri": row["resource_uri"], "checksum_sha256": row["sha256"]}
                for row in service.list_assets(copy_id)]
        assets = read_verified_split_asset_bytes(service, typed, resolved.resolved_assets, pins)
        inputs = verify_split_paint_inputs(typed, assets)
        registry = registry_endpoint_inputs_for_objects({obj.object_id: obj for obj in typed.objects},
            frozen_files={name: raw for name, _, raw in inputs.bundle_bytes})
        assert history(service, pid) == original_history
        assert service.source_timeline.get(pid) == original_source
        assert media == {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                         for path in tmp_path.rglob("*.wav")}
        path_open, builtin_open = Path.open, builtins.open

        def write_only(opener, path, mode="r", *args, **kwargs):
            if "r" in mode or "+" in mode or not any(flag in mode for flag in ("w", "a", "x")):
                pytest.fail("frozen relationship reopened a file for reading")
            return opener(path, mode, *args, **kwargs)

        monkeypatch.setattr(Path, "read_bytes", lambda *_: pytest.fail("frozen relationship reopened a file"))
        monkeypatch.setattr(Path, "open", lambda path, mode="r", *a, **kw: write_only(path_open, path, mode, *a, **kw))
        monkeypatch.setattr(builtins, "open", lambda path, mode="r", *a, **kw: write_only(builtin_open, path, mode, *a, **kw))
        monkeypatch.setattr(socket, "create_connection", lambda *_a, **_k: pytest.fail("relationship used network"))
        monkeypatch.setattr(socket.socket, "connect", lambda *_a, **_k: pytest.fail("relationship used network"))
        for at in (6900, 4450, 4900, 3999, 6450, 4450):
            snapshot = v2_state._evaluate_frame_with_registry_inputs(copied_layout, copied_clock, at, registry)
            frame = _compose_validated_svg_frame(typed, resolved, snapshot, {}, {}, split_inputs=inputs)
            assert _rasterize_svg_frame(typed, frame, split_inputs=inputs).png == expected[at]
        assert service.capabilities()["visual_contracts"]["renderer_versions"] == ["1"]
    finally:
        service.store.close()


@pytest.mark.parametrize("kind", ["pointer", "network"])
@pytest.mark.parametrize("fault", ["destination", "source", "routing", "foreign-project", "stale-revision"])
def test_stored_layout_cannot_reauthor_relationship_or_bypass_project_basis(tmp_path, kind, fault):
    service, project, _, layout, _ = stored_relationship(tmp_path, kind)
    try:
        pid = project["project_id"]
        original = history(service, pid)
        source = deepcopy(service.source_timeline.get(pid))
        invalid = deepcopy(layout)
        invalid["project_revision"] = project["revision"]
        connector = invalid["objects"][3]
        if fault == "destination":
            connector["destination_anchor_id"] = "different"
        elif fault == "source":
            if kind == "pointer":
                connector["source_point"]["x"] += 1
            else:
                connector["source_anchor_id"] = "different"
        elif fault == "routing":
            connector["routing"] = "curve"
        elif fault == "foreign-project":
            foreign = service.create("Other project", "LONG_FORM_16_9", "idea-first")
            invalid["project_id"] = foreign["project_id"]
        else:
            invalid["project_revision"] -= 1
        with pytest.raises(ProjectError):
            service.write(pid, "layout", invalid, project["revision"])
        assert history(service, pid) == original
        assert service.open(pid)["revision"] == project["revision"]
        assert service.artifact(pid, "layout")["document"] == layout
        assert service.source_timeline.get(pid) == source
    finally:
        service.store.close()


@pytest.mark.parametrize("kind,fault", [("network", "missing"), ("network", "null"), ("pointer", "null")])
def test_new_stored_storyboard_requires_exact_relationship_authority(tmp_path, kind, fault):
    service, project, plan, _, _ = stored_relationship(tmp_path, kind, persist=False)
    try:
        pid = project["project_id"]
        plan["project_revision"] = project["revision"]
        if fault == "missing":
            plan["objects"][3].pop("connector_binding")
        else:
            plan["objects"][3]["connector_binding"] = None
        before = deepcopy((service.open(pid), history(service, pid), service.source_timeline.get(pid)))
        with pytest.raises(ProjectError):
            service.write(pid, "storyboard", plan, project["revision"])
        assert (service.open(pid), history(service, pid), service.source_timeline.get(pid)) == before
    finally:
        service.store.close()
