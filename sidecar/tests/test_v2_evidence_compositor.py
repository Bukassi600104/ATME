"""Evidence frame pixels come from attested source bytes and exact authored treatment."""

from __future__ import annotations

import base64
import hashlib
import io
import re
from copy import deepcopy

import pytest
from atme.project_service import ProjectService
from atme.render.v2_state import V2FrameError, evaluate_frame
from atme.render.v2_svg import (
    UnsupportedVisualObject,
    compose_png_frame,
    compose_svg_frame,
)
from atme.store.contracts_v2 import ExecutableLayoutV2, ResolvedVisualTimelineV2
from atme.store.db import JobStore
from PIL import Image
from v2_fixtures import (
    digest,
    executable_layout_v2,
    resolved_timeline_v2,
    visual_plan_v2,
)


def evidence_documents(tmp_path, *, crop=None, focus=None, darkening=None,
                       annotation="Key mechanism", source_label="Example Source",
                       permissions=None, portrait=False):
    service = ProjectService(JobStore(tmp_path / "evidence-compositor.db"))
    pid = service.create("Evidence compositor", "LONG_FORM_16_9", "idea-first")["project_id"]
    source = Image.new("RGBA", (900, 500), (235, 30, 40, 255))
    source.paste((25, 185, 50, 255), (450, 0, 900, 250))
    source.paste((35, 60, 220, 255), (0, 250, 450, 500))
    source.paste((225, 190, 30, 255), (450, 250, 900, 500))
    output = io.BytesIO()
    source.save(output, format="PNG")
    raw = output.getvalue()
    staged = tmp_path / "external-original.png"
    staged.write_bytes(raw)
    provenance = {
        "category": "external_evidence", "source_uri": "https://example.com/source",
        "checksum_sha256": hashlib.sha256(raw).hexdigest(),
        "license_status": "licensed", "fabrication_prohibited": True,
        "originality_status": "reference_only",
    }
    permissions = permissions or ["crop", "scale", "annotate", "color_treatment"]
    asset = service.attach_evidence_file(pid, staged, "external-original.png", 0,
                                         provenance, permissions)["asset"]
    plan = visual_plan_v2()
    plan["project_id"] = pid
    if portrait:
        plan["output_profile"] = {
            "profile_id": "SHORT_FORM_9_16", "width": 720, "height": 1280, "fps": 30,
        }
    plan["assets"][0].update(
        asset_id=asset["asset_id"], revision=asset["revision"],
        managed_ref=asset["resource_uri"], checksum_sha256=asset["sha256"],
        width=asset["width"], height=asset["height"], provenance=asset["provenance"],
        allowed_transformations=permissions,
    )
    plan["objects"][2]["asset_id"] = asset["asset_id"]
    plan["actions"][2]["evidence_asset_id"] = asset["asset_id"]
    intent = plan["beats"][1]["evidence"]
    intent["evidence_asset_id"] = asset["asset_id"]
    if crop is not None:
        intent["crop"] = crop
    if focus is not None:
        intent["focus_region"] = focus
    if darkening is not None:
        intent["darkening"] = darkening
    intent["source_label"] = source_label
    intent["annotation"] = annotation
    if annotation is None:
        intent["annotation_target_id"] = None
        intent["annotation_omission_reason"] = "No callout is needed"
    layout = executable_layout_v2(plan)
    layout["objects"][2]["asset_id"] = asset["asset_id"]
    if portrait:
        layout["output_profile"] = deepcopy(plan["output_profile"])
        layout["canvas"] = {"x": 0, "y": 0, "width": 720, "height": 1280}
        layout["objects"][2]["geometry"]["bounds"]["x"] = 110
        layout["objects"][2]["geometry"]["bounds"]["y"] = 540
    timeline = resolved_timeline_v2(plan, layout)
    if portrait:
        timeline["output_profile"] = deepcopy(plan["output_profile"])
    timeline["resolved_assets"][0].update(
        asset_id=asset["asset_id"], revision=asset["revision"],
        managed_ref=asset["resource_uri"], checksum_sha256=asset["sha256"],
        byte_length=asset["bytes"], width=asset["width"], height=asset["height"],
        allowed_transformations=permissions,
    )
    verified = service.render_evidence_bytes(
        pid, timeline["resolved_assets"][0], layout["evidence_treatments"][0],
    )
    return service, layout, timeline, verified


def test_verified_evidence_draws_crop_focus_attribution_and_annotation(tmp_path):
    service, layout, timeline, verified = evidence_documents(tmp_path)
    payload = {verified.asset_id: verified}
    svg = compose_svg_frame(layout, timeline, 4900, payload).svg
    assert 'data-evidence-crop="claim-1"' in svg
    assert 'data-evidence-focus="claim-1"' in svg
    assert 'data-evidence-darkening="outside-focus"' in svg
    assert 'data-evidence-source-label="claim-1"' in svg
    assert 'data-evidence-annotation="text"' in svg
    assert 'rx="12"' in svg and 'clip-path="url(#evidence-card-' in svg
    assert "Example Source" in svg and "Key mechanism" in svg
    assert "https://example.com/source" not in svg
    assert compose_png_frame(layout, timeline, 4900, payload).png.startswith(b"\x89PNG")
    assert compose_svg_frame(layout, timeline, 4900, payload).svg == svg
    service.store.close()


def test_insert_raster_is_deterministic_and_appears_after_action_start(tmp_path):
    service, layout, timeline, verified = evidence_documents(tmp_path)
    payload = {verified.asset_id: verified}
    before = compose_png_frame(layout, timeline, 3999, payload).png
    middle = compose_png_frame(layout, timeline, 4450, payload).png
    after = compose_png_frame(layout, timeline, 4900, payload).png
    assert len({before, middle, after}) == 3
    assert compose_png_frame(layout, timeline, 4900, payload).png == after
    with Image.open(io.BytesIO(after)) as frame:
        assert frame.convert("RGB").getpixel((930, 260)) != (255, 255, 255)
    service.store.close()


def test_tiny_focus_is_rejected_as_unreadable(tmp_path):
    service, layout, timeline, verified = evidence_documents(
        tmp_path, focus={"x": 100, "y": 100, "width": 1, "height": 1},
    )
    with pytest.raises(V2FrameError, match="not fully readable"):
        compose_svg_frame(layout, timeline, 4900, {verified.asset_id: verified})
    service.store.close()


def test_retained_camera_cannot_hide_evidence_hold(tmp_path):
    from test_v2_camera_action import append_camera

    service, layout, timeline, _ = evidence_documents(tmp_path)
    append_camera(timeline, "camera-before-evidence", "camera_cut", 3000, 3500,
                  target="object-label", framing="detail")
    with pytest.raises(V2FrameError, match="not fully readable"):
        evaluate_frame(layout, timeline, 4900)
    service.store.close()


def test_undeclared_rotation_after_hold_is_rejected(tmp_path):
    service, layout, timeline, _ = evidence_documents(tmp_path)
    trigger = {"kind": "absolute", "at_ms": 8500}
    timeline["actions"].append({
        "action": {
            "action_id": "rotate-evidence", "source_instruction_id": "instruction-3",
            "board_id": "board-main", "semantic_reason": "Turn the evidence card",
            "trigger": trigger, "easing": "linear", "expected_state": "evidence_visible",
            "post_state": "evidence_visible", "fallback": {"fallback_id": "fallback-3",
                                                       "on_failure": "block"},
            "coverage_id": "coverage-3", "verb": "rotate", "target_ids": ["object-evidence"],
            "destination": {"position": {"x": 0, "y": 0}, "scale_x": 1, "scale_y": 1,
                            "rotation_degrees": 20, "origin": {"x": 0.5, "y": 0.5}},
            "opacity": None,
        },
        "start_ms": 8500, "end_ms": 9000,
        "resolved_trigger": {"source": trigger, "alignment_anchor_ms": 8500,
                             "matched_text": None, "matched_occurrence": None,
                             "resolved_at_ms": 8500, "confidence": 1, "exact": True},
    })
    timeline["coverage"][2]["action_ids"].append("rotate-evidence")
    with pytest.raises(V2FrameError, match="undeclared rotation"):
        evaluate_frame(layout, timeline, 4900)
    service.store.close()


def test_full_rectangle_mask_keeps_evidence_readable_and_clipping_mask_fails(tmp_path):
    permissions = ["crop", "scale", "mask", "annotate", "color_treatment"]
    service, layout, timeline, _ = evidence_documents(tmp_path, permissions=permissions)
    evidence = layout["objects"][2]
    evidence["parent_id"] = "evidence-mask"
    mask = {
        "object_id": "evidence-mask", "board_id": "board-main", "beat_id": "beat-002",
        "semantic_role": "Evidence aperture", "z_index": 2,
        "geometry": {"bounds": {"x": 650, "y": 100, "width": 560, "height": 500},
                     "points": [], "corner_radius": None},
        "transform": {"position": {"x": 0, "y": 0}, "scale_x": 1, "scale_y": 1,
                      "rotation_degrees": 0, "origin": {"x": 0.5, "y": 0.5}},
        "opacity": 1, "visible": True,
        "style": {"stroke": None, "fill": None, "text": None, "effect": None},
        "anchors": [], "parent_id": None, "clip_id": None,
        "initial_state": "visible", "asset_id": None,
        "description": "Full evidence mask", "coverage_ids": ["coverage-3"],
        "object_type": "mask", "child_ids": ["object-evidence"],
        "mask_mode": "alpha", "mask_source_object_id": "evidence-mask-source",
        "mask_coordinate_space": "parent_local", "invert": False, "feather_px": 0,
    }
    source = deepcopy(layout["objects"][0])
    source.update(object_id="evidence-mask-source", object_type="rectangle",
                  beat_id="beat-002", semantic_role="Evidence aperture geometry",
                  geometry={"bounds": {"x": 650, "y": 100, "width": 560, "height": 500},
                            "points": [], "corner_radius": None},
                  style={"stroke": None, "fill": None, "text": None, "effect": None},
                  visible=True, initial_state="visible", anchors=[], z_index=1,
                  coverage_ids=["coverage-3"])
    layout["objects"].extend((mask, source))
    layout["boards"][0]["object_ids"].extend(("evidence-mask", "evidence-mask-source"))
    layout["evidence_treatments"][0]["intent"]["mask_object_id"] = "evidence-mask"
    timeline["evidence_treatments"] = deepcopy(layout["evidence_treatments"])
    timeline["initial_object_states"].extend(
        {"object_id": object_id, "state": "visible", "state_version": 1, "visible": True}
        for object_id in ("evidence-mask", "evidence-mask-source")
    )
    timeline["layout_sha256"] = digest(layout)
    parsed_layout = ExecutableLayoutV2.model_validate(layout)
    parsed_timeline = ResolvedVisualTimelineV2.model_validate(timeline)
    verified = service.render_evidence_bytes(
        layout["project_id"], parsed_timeline.resolved_assets[0],
        parsed_layout.evidence_treatments[0],
    )
    assert compose_png_frame(layout, timeline, 4900, {verified.asset_id: verified}).png
    bad = deepcopy(layout)
    bad["objects"][-1]["geometry"]["bounds"]["width"] = 100
    bad_timeline = deepcopy(timeline)
    bad_timeline["layout_sha256"] = digest(bad)
    with pytest.raises(V2FrameError, match="clipped by its declared mask"):
        evaluate_frame(bad, bad_timeline, 4900)
    service.store.close()


def test_portrait_evidence_uses_same_verified_crop_and_frame_runtime(tmp_path):
    service, layout, timeline, verified = evidence_documents(tmp_path, portrait=True)
    payload = {verified.asset_id: verified}
    frame = compose_png_frame(layout, timeline, 4900, payload)
    with Image.open(io.BytesIO(frame.png)) as image:
        assert image.size == (720, 1280)
    assert 'data-evidence-crop="claim-1"' in compose_svg_frame(
        layout, timeline, 4900, payload,
    ).svg
    service.store.close()


def test_evidence_cannot_use_unverified_or_mismatched_bytes(tmp_path):
    service, layout, timeline, verified = evidence_documents(tmp_path)
    with pytest.raises(UnsupportedVisualObject, match="verified project evidence"):
        compose_svg_frame(layout, timeline, 4900, {verified.asset_id: verified.payload})
    changed = deepcopy(timeline)
    changed["resolved_assets"][0]["byte_length"] += 1
    with pytest.raises(UnsupportedVisualObject, match="integrity"):
        compose_svg_frame(layout, changed, 4900, {verified.asset_id: verified})
    service.store.close()


def test_evidence_crop_is_exact_source_pixels_without_distortion(tmp_path):
    service, layout, timeline, verified = evidence_documents(
        tmp_path,
        crop={"x": 450, "y": 0, "width": 450, "height": 500},
        focus={"x": 500, "y": 50, "width": 200, "height": 100},
        darkening=0,
    )
    svg = compose_svg_frame(layout, timeline, 4900, {verified.asset_id: verified}).svg
    match = re.search(r'data-evidence-crop="claim-1"[^>]*href="data:image/png;base64,([^"]+)"', svg)
    assert match is not None
    with Image.open(io.BytesIO(base64.b64decode(match.group(1)))) as crop:
        assert crop.size == (450, 500)
        assert crop.getpixel((0, 0)) == (25, 185, 50, 255)
        assert crop.getpixel((449, 499)) == (225, 190, 30, 255)
    assert 'preserveAspectRatio="xMidYMid meet"' in svg
    assert 'data-evidence-darkening="outside-focus"' not in svg
    service.store.close()


def test_omitted_annotation_and_xml_escaped_source_label(tmp_path):
    service, layout, timeline, verified = evidence_documents(
        tmp_path, annotation=None, source_label='Source <A> & "B"',
    )
    svg = compose_svg_frame(layout, timeline, 4900, {verified.asset_id: verified}).svg
    assert 'data-evidence-annotation=' not in svg
    assert 'Source &lt;A&gt; &amp; &quot;B&quot;' in svg
    service.store.close()
