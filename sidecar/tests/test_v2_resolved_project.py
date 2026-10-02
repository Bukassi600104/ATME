"""Stored v2 compiler results are immutable, paired, and never sent to v1."""

from __future__ import annotations

import hashlib
import io
from copy import deepcopy

import pytest
from PIL import Image
from test_project_runner import wav_bytes
from test_visual_contracts_v2 import _store_v2_plan
from v2_fixtures import digest, executable_layout_v2, resolved_timeline_v2

from atme.narrative_source import describe
from atme.project_service import ProjectError, _resolved_compilation_fingerprint


def stored_v2_basis(tmp_path, *, real_evidence=False, real_image=False,
                    image_object_asset_id="valid"):
    service, project, plan = _store_v2_plan(tmp_path)
    project_id = project["project_id"]
    imported = service.attach_wav(project_id, wav_bytes(seconds=10), project["revision"])
    project = imported["project"]
    placed = service.source_timeline.command(
        project_id, "insert", {"media_id": imported["media"]["media_id"], "at_ms": 0},
        project["revision"], 0,
    )
    project = placed["project"]
    timing = placed["timeline"]
    media = describe(service, project_id)["timing_authority"]["media"]
    plan["project_revision"] = project["revision"]
    plan["narrative_authority"].update(
        timing_media_id=media["media_id"], timing_media_sha256=media["sha256"],
        cleaned_timeline_revision=timing["timeline_revision"],
        cleaned_timeline_fingerprint=digest(timing["document"]),
    )
    project = service.write(project_id, "storyboard", plan, project["revision"])
    asset = None
    image_asset = None
    real_evidence = real_evidence or real_image
    if real_evidence:
        source = Image.new("RGB", (900, 500), (225, 210, 180))
        output = io.BytesIO()
        source.save(output, format="PNG")
        raw = output.getvalue()
        staged = tmp_path / "source-evidence.png"
        staged.write_bytes(raw)
        provenance = {"category": "external_evidence",
                      "source_uri": "https://example.com/visual-source",
                      "checksum_sha256": hashlib.sha256(raw).hexdigest(),
                      "license_status": "licensed", "fabrication_prohibited": True,
                      "originality_status": "reference_only"}
        permissions = ["crop", "scale", "annotate", "color_treatment"]
        asset = service.attach_evidence_file(
            project_id, staged, staged.name, project["revision"], provenance, permissions,
        )["asset"]
        project = service.open(project_id)
        plan = deepcopy(plan)
        plan["project_revision"] = project["revision"]
        plan["assets"][0].update(
            asset_id=asset["asset_id"], revision=asset["revision"],
            managed_ref=asset["resource_uri"], checksum_sha256=asset["sha256"],
            width=asset["width"], height=asset["height"],
            provenance=asset["provenance"], allowed_transformations=permissions,
        )
        plan["objects"][2]["asset_id"] = asset["asset_id"]
        plan["actions"][2]["evidence_asset_id"] = asset["asset_id"]
        plan["beats"][1]["evidence"]["evidence_asset_id"] = asset["asset_id"]
    if real_image:
        output = io.BytesIO()
        Image.new("RGB", (80, 40), (40, 105, 210)).save(output, format="PNG")
        staged = tmp_path / "supporting.png"
        staged.write_bytes(output.getvalue())
        image_asset = service.attach_asset_file(
            project_id, staged, staged.name, project["revision"],
        )["asset"]
        project = service.open(project_id)
        image_id = image_asset["asset_id"]
        image_ref = f"atme://projects/{project_id}/assets/{image_id}"
        plan["assets"].append({
            "asset_id": image_id, "revision": image_asset["revision"],
            "kind": "image", "semantic_role": "Supporting illustration",
            "managed_ref": image_ref, "checksum_sha256": image_asset["sha256"],
            "width": 80, "height": 40, "duration_ms": None,
            "provenance": {"category": "user_owned", "source_uri": None,
                           "checksum_sha256": image_asset["sha256"],
                           "license_status": "owned", "fabrication_prohibited": False,
                           "originality_status": "original"},
            "style_family": None, "style_version": None,
            "allowed_transformations": ["scale"], "fallback_id": None,
        })
        image_object = deepcopy(plan["objects"][0])
        image_object.update(object_id="object-image", object_type="image",
                            beat_id="beat-002", semantic_role="Supporting visual context",
                            description="Attached project image",
                            asset_id=(image_id if image_object_asset_id == "valid"
                                      else image_object_asset_id),
                            initial_state="visible", coverage_ids=["coverage-3"])
        plan["objects"].append(image_object)
        plan["boards"][0]["object_ids"].append("object-image")
        plan["beats"][1]["object_ids"].append("object-image")
        plan["beats"][1]["attention"]["secondary_context"].append("object-image")
    if real_evidence:
        plan["project_revision"] = project["revision"]
        project = service.write(project_id, "storyboard", plan, project["revision"])
    layout = executable_layout_v2(plan)
    if asset is not None:
        layout["objects"][2]["asset_id"] = asset["asset_id"]
    if image_asset is not None:
        image_object = deepcopy(layout["objects"][2])
        image_object.update(object_id="object-image", object_type="image",
                            semantic_role="Supporting visual context", z_index=4,
                            asset_id=(image_asset["asset_id"] if image_object_asset_id == "valid"
                                      else image_object_asset_id),
                            description="Attached project image",
                            geometry={"bounds": {"x": 80, "y": 510, "width": 380,
                                                 "height": 150},
                                      "points": [], "corner_radius": None},
                            style={"stroke": None, "fill": None, "text": None, "effect": None},
                            variant=None, initial_state="visible", visible=True)
        layout["objects"].append(image_object)
    layout.update(project_id=project_id, project_revision=project["revision"],
                  plan_revision=project["artifacts"]["storyboard"],
                  plan_sha256=digest(plan))
    try:
        project = service.write(project_id, "layout", layout, project["revision"])
    except ProjectError as exc:
        raise AssertionError(exc.errors) from exc
    timeline = resolved_timeline_v2(plan, layout)
    if asset is not None:
        timeline["resolved_assets"][0].update(
            asset_id=asset["asset_id"], revision=asset["revision"],
            managed_ref=asset["resource_uri"], checksum_sha256=asset["sha256"],
            byte_length=asset["bytes"], width=asset["width"], height=asset["height"],
            allowed_transformations=permissions,
        )
    if image_asset is not None:
        image_id = image_asset["asset_id"]
        timeline["resolved_assets"].append({
            "asset_id": image_id, "revision": image_asset["revision"],
            "managed_ref": f"atme://projects/{project_id}/assets/{image_id}",
            "checksum_sha256": image_asset["sha256"], "provenance_verified": False,
            "kind": "image", "media_type": "image/png", "byte_length": image_asset["bytes"],
            "width": 80, "height": 40, "orientation": "upright",
            "allowed_transformations": ["scale"],
        })
        image_state = next(item for item in timeline["initial_object_states"]
                           if item["object_id"] == "object-image")
        image_state.update(state="visible", visible=True)
    source = service.source_timeline.get(project_id)
    timeline.update(project_id=project_id, project_revision=project["revision"],
                    plan_revision=project["artifacts"]["storyboard"],
                    layout_revision=project["artifacts"]["layout"],
                    plan_sha256=digest(plan), layout_sha256=digest(layout),
                    cleaned_timeline_revision=source["timeline_revision"],
                    cleaned_timeline_fingerprint=digest(source["document"]))
    timeline["compilation_fingerprint"] = _resolved_compilation_fingerprint(timeline)
    return service, project, plan, layout, timeline


def test_resolved_timeline_is_stored_as_a_versioned_project_artifact(tmp_path):
    service, project, _, _, timeline = stored_v2_basis(tmp_path)
    project_id = project["project_id"]
    project = service.write(project_id, "resolved_timeline", timeline, project["revision"])
    stored = service.artifact(project_id, "resolved_timeline")
    assert stored["contract_version"] == "2.0.0"
    assert stored["document"] == timeline
    assert project["artifacts"]["resolved_timeline"] == stored["revision"]
    assert stored["basis_timeline_revision"] == timeline["cleaned_timeline_revision"]
    service.store.close()


@pytest.mark.parametrize("mutation", [
    lambda d: d["initial_object_states"].pop(),
    lambda d: d.update(layout_sha256="0" * 64),
    lambda d: d.update(plan_revision=d["plan_revision"] - 1),
    lambda d: d.update(cleaned_timeline_fingerprint="0" * 64),
    lambda d: d["actions"][0]["action"].update(semantic_reason="Changed after planning"),
    lambda d: d["resolved_assets"][0].update(checksum_sha256="0" * 64),
])
def test_resolved_timeline_rejects_stale_or_changed_basis(tmp_path, mutation):
    service, project, _, _, timeline = stored_v2_basis(tmp_path)
    invalid = deepcopy(timeline)
    mutation(invalid)
    invalid["compilation_fingerprint"] = _resolved_compilation_fingerprint(invalid)
    before = service.open(project["project_id"])["revision"]
    with pytest.raises(ProjectError) as failure:
        service.write(project["project_id"], "resolved_timeline", invalid, before)
    assert failure.value.code in {"stale_contract_basis", "invalid_artifact"}
    assert service.open(project["project_id"])["revision"] == before
    service.store.close()


def test_resolved_timeline_requires_exact_compilation_fingerprint(tmp_path):
    service, project, _, _, timeline = stored_v2_basis(tmp_path)
    timeline["compilation_fingerprint"] = "0" * 64
    with pytest.raises(ProjectError, match="production basis"):
        service.write(project["project_id"], "resolved_timeline", timeline, project["revision"])
    service.store.close()


@pytest.mark.parametrize("mutation", [
    lambda d: d["initial_object_states"].append({
        "object_id": "unrelated", "state": "hidden", "state_version": 1, "visible": False,
    }),
    lambda d: d["initial_object_states"][0].update(visible=True),
    lambda d: d["initial_object_states"][0].update(state="visible"),
    lambda d: d["beat_anchors"].pop(),
    lambda d: d["beat_anchors"].append({"beat_id": "unrelated", "start_ms": 1000}),
    lambda d: d.update(duration_ms=d["duration_ms"] + 1000),
    lambda d: d.update(duration_ms=d["duration_ms"] - 1000),
])
def test_resolved_timeline_rejects_incomplete_structure_or_authoritative_duration(tmp_path, mutation):
    service, project, _, _, timeline = stored_v2_basis(tmp_path)
    mutation(timeline)
    timeline["compilation_fingerprint"] = _resolved_compilation_fingerprint(timeline)
    with pytest.raises(ProjectError) as failure:
        service.write(project["project_id"], "resolved_timeline", timeline, project["revision"])
    assert failure.value.code == "invalid_artifact"
    assert service.open(project["project_id"])["revision"] == project["revision"]
    service.store.close()


@pytest.mark.parametrize("missing_kind", ["evidence", "image"])
def test_resolved_timeline_rejects_missing_required_raster(tmp_path, missing_kind):
    service, project, _, _, timeline = stored_v2_basis(
        tmp_path, real_image=missing_kind == "image",
        real_evidence=missing_kind == "evidence",
    )
    incomplete = deepcopy(timeline)
    incomplete["resolved_assets"] = [item for item in incomplete["resolved_assets"]
                                     if item["kind"] != missing_kind]
    incomplete["compilation_fingerprint"] = _resolved_compilation_fingerprint(incomplete)
    with pytest.raises(ProjectError) as failure:
        service.write(project["project_id"], "resolved_timeline", incomplete,
                      project["revision"])
    assert failure.value.code == "invalid_artifact"
    if missing_kind == "image":
        assert "omits a required project raster" in str(failure.value)
    assert service.open(project["project_id"])["revision"] == project["revision"]
    service.store.close()


@pytest.mark.parametrize("missing_id", [None, ""])
def test_resolved_timeline_rejects_raster_without_asset_id(tmp_path, missing_id):
    service, project, _, _, timeline = stored_v2_basis(
        tmp_path, real_image=True, image_object_asset_id=missing_id,
    )
    with pytest.raises(ProjectError) as failure:
        service.write(project["project_id"], "resolved_timeline", timeline,
                      project["revision"])
    assert failure.value.code == "invalid_artifact"
    assert "no declared project asset" in str(failure.value)
    assert service.open(project["project_id"])["revision"] == project["revision"]
    service.store.close()


def test_duplicate_rebinds_resolved_timeline_without_mutating_source(tmp_path):
    service, project, _, _, timeline = stored_v2_basis(tmp_path)
    project_id = project["project_id"]
    service.write(project_id, "resolved_timeline", timeline, project["revision"])
    clone_id = service.duplicate(project_id)["project_id"]
    original = service.artifact(project_id, "resolved_timeline")["document"]
    copied = service.artifact(clone_id, "resolved_timeline")
    assert original == timeline
    assert copied["document"]["project_id"] == clone_id
    assert copied["document"]["compilation_fingerprint"] == _resolved_compilation_fingerprint(
        copied["document"]
    )
    assert copied["duplicate_derivation"]["source_project_id"] == project_id
    service.store.close()


def test_stored_v2_preview_matches_direct_compositor_without_v1_fallback(tmp_path, monkeypatch):
    from atme.render.v2_svg import compose_png_frame
    from atme.store.contracts_v2 import ExecutableLayoutV2, ResolvedVisualTimelineV2

    service, project, _, layout, timeline = stored_v2_basis(tmp_path, real_evidence=True)
    project_id = project["project_id"]
    project = service.write(project_id, "resolved_timeline", timeline, project["revision"])

    def forbidden(*args, **kwargs):
        raise AssertionError("v1 frame renderer must not receive a v2 project")

    monkeypatch.setattr("atme.render.animator._FrameRenderer", forbidden)
    asset = ResolvedVisualTimelineV2.model_validate(timeline).resolved_assets[0]
    treatment = ExecutableLayoutV2.model_validate(layout).evidence_treatments[0]
    verified = service.render_evidence_bytes(project_id, asset, treatment)
    for at_ms in (0, 4900, 2500, 4900):
        preview = service.runner.preview_v2_source(project_id, project["revision"], at_ms)
        direct = compose_png_frame(layout, timeline, at_ms, {asset.asset_id: verified})
        assert preview["png"] == direct.png
        assert (preview["width"], preview["height"]) == (1280, 720)
    service.store.close()


def test_duplicate_preserves_verifiable_evidence_preview(tmp_path):
    service, project, _, _, timeline = stored_v2_basis(tmp_path, real_evidence=True)
    source_id = project["project_id"]
    service.write(source_id, "resolved_timeline", timeline, project["revision"])
    copy = service.duplicate(source_id)
    preview = service.runner.preview_v2_source(copy["project_id"], copy["revision"], 4900)
    assert preview["png"].startswith(b"\x89PNG")
    assert service.artifact(source_id, "resolved_timeline")["document"] == timeline
    service.store.close()


def test_duplicate_rebinds_ordinary_image_ref_and_preserves_visible_pixels(tmp_path):
    service, project, _, _, timeline = stored_v2_basis(tmp_path, real_image=True)
    source_id = project["project_id"]
    try:
        project = service.write(source_id, "resolved_timeline", timeline, project["revision"])
    except ProjectError as exc:
        raise AssertionError(exc.errors) from exc
    source_frame = service.runner.preview_v2_source(source_id, project["revision"], 4900)
    with Image.open(io.BytesIO(source_frame["png"])) as frame:
        assert frame.convert("RGB").getpixel((270, 585)) == (40, 105, 210)
    copy = service.duplicate(source_id)
    copy_id = copy["project_id"]
    plan = service.artifact(copy_id, "storyboard")["document"]
    resolved = service.artifact(copy_id, "resolved_timeline")["document"]
    image_id = next(item["asset_id"] for item in plan["assets"] if item["kind"] == "image")
    expected_ref = f"atme://projects/{copy_id}/assets/{image_id}"
    assert next(item for item in plan["assets"] if item["asset_id"] == image_id)["managed_ref"] == expected_ref
    assert next(item for item in resolved["resolved_assets"]
                if item["asset_id"] == image_id)["managed_ref"] == expected_ref
    copy_frame = service.runner.preview_v2_source(copy_id, copy["revision"], 4900)
    assert copy_frame["png"] == source_frame["png"]
    service.store.close()


def test_v2_preview_rejects_stale_script_or_invalid_time(tmp_path):
    service, project, _, _, timeline = stored_v2_basis(tmp_path, real_evidence=True)
    project_id = project["project_id"]
    project = service.write(project_id, "resolved_timeline", timeline, project["revision"])
    with pytest.raises(ProjectError) as failure:
        service.runner.preview_v2_source(project_id, project["revision"], timeline["duration_ms"])
    assert failure.value.code == "invalid_request"
    script = service.artifact(project_id, "script")["document"]
    project = service.write(project_id, "script", script, project["revision"])
    with pytest.raises(ProjectError) as failure:
        service.runner.preview_v2_source(project_id, project["revision"], 4900)
    assert failure.value.code == "stale_contract_basis"
    service.store.close()


def test_public_v2_preview_remains_closed_until_phase_three_exit(tmp_path):
    service, project, _, _, timeline = stored_v2_basis(tmp_path, real_evidence=True)
    project_id = project["project_id"]
    project = service.write(project_id, "resolved_timeline", timeline, project["revision"])
    with pytest.raises(ProjectError) as failure:
        service.preview_project(project_id, project["revision"], 4900)
    assert failure.value.code == "renderer_contract_unsupported"
    assert service.capabilities()["visual_contracts"]["renderer_versions"] == ["1"]
    service.store.close()
