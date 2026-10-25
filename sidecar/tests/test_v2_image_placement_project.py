"""Authored image permissions retain real ownership, revisions and preview wiring."""

from __future__ import annotations

import hashlib
import io
import socket
from copy import deepcopy
from pathlib import Path

import pytest
from PIL import Image
from test_v2_image_placement_runtime import placement_documents, source_pixels
from test_v2_registry_project import history
from test_v2_resolved_project import stored_v2_basis
from v2_fixtures import digest

from atme.project_assets import read_verified_split_asset_bytes
from atme.project_service import (
    ProjectError,
    ProjectService,
    _resolved_compilation_fingerprint,
)
from atme.render import v2_state
from atme.render.style_bundle import registry_endpoint_inputs_for_objects
from atme.render.v2_split_paint import verify_split_paint_inputs
from atme.render.v2_svg import (
    _compose_validated_svg_frame,
    _rasterize_svg_frame,
    compose_png_frame,
)
from atme.store.contracts_v2 import ExecutableLayoutV2, ResolvedVisualTimelineV2
from atme.store.db import JobStore


def stored_placement(tmp_path, portrait=False, *, persist=True):
    profile = "SHORT_FORM_9_16" if portrait else "LONG_FORM_16_9"
    service, project, plan, layout, clock = stored_v2_basis(tmp_path, real_image=True, profile=profile)
    asset = next(row for row in clock["resolved_assets"] if row["kind"] == "image")
    asset["allowed_transformations"] = ["scale", "crop", "rotate", "mask"]
    placement = {"version": "1.0.0", "source_revision": asset["revision"],
        "source_sha256": asset["checksum_sha256"], "source_width": 80, "source_height": 40,
        "crop": {"x": 20, "y": 10, "width": 40, "height": 20}, "fit": "contain",
        "focal_point": {"x": 0.0, "y": 1.0},
        "allowed_transformations": asset["allowed_transformations"][:]}
    next(row for row in plan["assets"] if row["asset_id"] == asset["asset_id"])[
        "allowed_transformations"] = asset["allowed_transformations"][:]
    for document in (plan, layout):
        next(obj for obj in document["objects"] if obj["object_id"] == "object-image")[
            "image_placement"] = deepcopy(placement)
    if portrait:
        # The shared legacy fixture is authored in landscape; keep its real
        # attested evidence readable rather than weakening evidence validation.
        layout["objects"][2]["geometry"]["bounds"] = {"x": 80, "y": 520, "width": 560, "height": 320}
    if not persist:
        return service, project, plan, layout, clock
    plan["project_revision"] = project["revision"]
    project = service.write(project["project_id"], "storyboard", plan, project["revision"])
    layout.update(project_revision=project["revision"], plan_revision=project["artifacts"]["storyboard"],
                  plan_sha256=digest(plan))
    project = service.write(project["project_id"], "layout", layout, project["revision"])
    clock.update(project_revision=project["revision"], plan_revision=project["artifacts"]["storyboard"],
                 plan_sha256=digest(plan), layout_revision=project["artifacts"]["layout"],
                 layout_sha256=digest(layout))
    clock["compilation_fingerprint"] = _resolved_compilation_fingerprint(clock)
    project = service.write(project["project_id"], "resolved_timeline", clock, project["revision"])
    return service, project, plan, layout, clock


def verified_assets(service, pid, layout, clock):
    typed = ExecutableLayoutV2.model_validate(layout)
    treatments = {row.object_id: row for row in typed.evidence_treatments}
    assets = {row["asset_id"]: row for row in clock["resolved_assets"]}
    supplied = {}
    for obj in typed.objects:
        if obj.object_type == "image":
            supplied[obj.asset_id] = service.render_image_bytes(pid, assets[obj.asset_id], layout=typed).payload
        elif obj.object_type == "evidence":
            supplied[obj.asset_id] = service.render_evidence_bytes(pid, assets[obj.asset_id], treatments[obj.object_id])
    return supplied


def owned_placement(tmp_path):
    """Permission negatives need actual ownership, not repeated unrelated evidence setup."""
    service = ProjectService(JobStore(tmp_path / "image.db"))
    project = service.create("Image", "LONG_FORM_16_9", "idea-first")
    source = tmp_path / "upload.png"
    raw = source_pixels()
    source.write_bytes(raw)
    imported = service.attach_asset_file(project["project_id"], source, source.name, project["revision"])
    layout, clock, _ = placement_documents(permissions=["scale", "crop", "rotate", "mask"])
    asset_id = imported["asset"]["asset_id"]
    layout["objects"][2]["asset_id"] = asset_id
    asset = clock["resolved_assets"][0]
    owned = service.list_assets(project["project_id"])[0]
    asset.update(asset_id=asset_id, managed_ref=owned["managed_ref"])
    clock["layout_sha256"] = digest(layout)
    assert service.render_image_bytes(project["project_id"], asset, layout=layout).payload == raw
    return service, imported["project"], layout, clock


@pytest.mark.parametrize("portrait", [False, True])
def test_stored_duplicate_source_preview_and_frozen_offline_pixels(tmp_path, portrait, monkeypatch):
    service, project, plan, layout, clock = stored_placement(tmp_path, portrait)
    try:
        pid = project["project_id"]
        original_history = history(service, pid)
        media = {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                 for path in tmp_path.rglob("*") if path.suffix in {".png", ".wav"}}
        supplied = verified_assets(service, pid, layout, clock)
        expected = {at: compose_png_frame(layout, clock, at, supplied).png for at in (4100, 4900, 5000)}
        # A literal visible source pixel also proves that parity is not two blank frames.
        assert Image.open(io.BytesIO(expected[5000])).convert("RGB").getpixel((170, 600)) == (40, 105, 210)
        assert service.runner.preview_v2_source(pid, project["revision"], 5000)["png"] == expected[5000]
        duplicate = service.duplicate(pid)
        copy_id = duplicate["project_id"]
        copied_plan = service.artifact(copy_id, "storyboard")["document"]
        copied_layout = service.artifact(copy_id, "layout")["document"]
        copied_clock = service.artifact(copy_id, "resolved_timeline")["document"]
        assert service.artifact(pid, "storyboard")["document"] == plan
        assert service.artifact(pid, "layout")["document"] == layout
        assert service.artifact(pid, "resolved_timeline")["document"] == clock
        assert copied_plan["narrative_authority"] == plan["narrative_authority"]
        assert copied_layout["objects"] == layout["objects"]
        assert copied_clock["cleaned_timeline_fingerprint"] == clock["cleaned_timeline_fingerprint"]
        assert copied_clock["layout_sha256"] == digest(copied_layout)
        assert copied_clock["plan_sha256"] == digest(copied_plan)
        assert copied_clock["compilation_fingerprint"] == _resolved_compilation_fingerprint(copied_clock)
        copied_bytes = verified_assets(service, copy_id, copied_layout, copied_clock)
        assert service.runner.preview_v2_source(copy_id, duplicate["revision"], 5000)["png"] == expected[5000]
        typed = ExecutableLayoutV2.model_validate(copied_layout)
        resolved = ResolvedVisualTimelineV2.model_validate(copied_clock)
        # Existing frozen bundle; no new Split family or public admission.
        pins = [{"asset_id": row["asset_id"], "revision": row["revision"],
                 "resource_uri": row["resource_uri"], "checksum_sha256": row["sha256"]}
                for row in service.list_assets(copy_id)]
        frozen_assets = read_verified_split_asset_bytes(service, typed, resolved.resolved_assets, pins)
        inputs = verify_split_paint_inputs(typed, frozen_assets)
        registry = registry_endpoint_inputs_for_objects({obj.object_id: obj for obj in typed.objects},
            frozen_files={name: raw for name, _, raw in inputs.bundle_bytes})
        assert history(service, pid) == original_history
        assert media == {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                         for path in tmp_path.rglob("*") if path.suffix in {".png", ".wav"}}
        monkeypatch.setattr(Path, "read_bytes", lambda *_: pytest.fail("frozen image reopened a file"))
        monkeypatch.setattr(socket, "create_connection", lambda *_a, **_k: pytest.fail("image used network"))
        monkeypatch.setattr(socket.socket, "connect", lambda *_a, **_k: pytest.fail("image used network"))
        for at in (5000, 4100, 4900, 4100):
            snapshot = v2_state._evaluate_frame_with_registry_inputs(copied_layout, copied_clock, at, registry)
            frame = _compose_validated_svg_frame(typed, resolved, snapshot, {}, copied_bytes, split_inputs=inputs)
            assert _rasterize_svg_frame(typed, frame, split_inputs=inputs).png == expected[at]
        assert service.capabilities()["visual_contracts"]["renderer_versions"] == ["1"]
    finally:
        service.store.close()


@pytest.mark.parametrize("fault", ["no-layout", "wrong-project", "no-owner", "bare-sibling", "pin", "permissions"])
def test_resolver_needs_full_matching_layout_and_exact_owner_inventory(tmp_path, fault):
    service, project, layout, clock = owned_placement(tmp_path)
    try:
        pid = project["project_id"]
        asset = next(row for row in clock["resolved_assets"] if row["kind"] == "image")
        candidate = deepcopy(layout)
        obj = next(row for row in candidate["objects"] if row["object_type"] == "image")
        if fault == "wrong-project":
            candidate["project_id"] += 1
        elif fault == "no-owner":
            obj.pop("image_placement")
            obj.update(object_type="icon", asset_id=None)
        elif fault == "bare-sibling":
            sibling = deepcopy(obj)
            sibling.update(object_id="bare-image", z_index=20)
            sibling.pop("image_placement")
            candidate["objects"].append(sibling)
            candidate["boards"][0]["object_ids"].append("bare-image")
        elif fault == "pin":
            asset["revision"] += 1
        elif fault == "permissions":
            asset["allowed_transformations"] = ["scale", "crop"]
        with pytest.raises(ProjectError):
            service.render_image_bytes(pid, asset, **({} if fault == "no-layout" else {"layout": candidate}))
    finally:
        service.store.close()


def test_layout_context_does_not_bypass_actual_managed_byte_integrity(tmp_path):
    service, project, layout, clock = owned_placement(tmp_path)
    try:
        pid = project["project_id"]
        asset = clock["resolved_assets"][0]
        path, _ = service.asset(pid, asset["asset_id"])
        path.write_bytes(b"tampered owned image")
        with pytest.raises(ProjectError, match="integrity"):
            service.render_image_bytes(pid, asset, layout=layout)
    finally:
        service.store.close()


def test_invalid_authored_pin_write_is_atomic_and_preserves_immutable_versions(tmp_path):
    service, project, _, layout, _ = stored_placement(tmp_path)
    try:
        pid = project["project_id"]
        previous = history(service, pid)
        layout["project_revision"] = project["revision"]
        next(obj for obj in layout["objects"] if obj["object_type"] == "image")[
            "image_placement"]["focal_point"]["x"] = 1.0
        with pytest.raises(ProjectError) as error:
            service.write(pid, "layout", layout, project["revision"])
        assert error.value.code == "invalid_artifact"
        assert service.open(pid)["revision"] == project["revision"]
        assert history(service, pid) == previous
    finally:
        service.store.close()
