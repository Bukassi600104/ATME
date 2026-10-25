"""Evidence needs true permitted source-local containment, not AABB overlap."""

from copy import deepcopy
from dataclasses import replace

import pytest
from atme.render.v2_camera import CameraViewport
from atme.render.v2_evidence_reading import validate_evidence_reading
from atme.render.v2_state import evaluate_frame
from test_v2_mask_contract import MASK_FIELDS
from test_v2_return_hierarchy import private_clock
from v2_fixtures import digest, executable_layout_v2, resolved_timeline_v2


def aperture_documents(shape="rectangle", *, rotation=23, clip=False, documents=None):
    layout, timeline = documents or (executable_layout_v2(), resolved_timeline_v2())
    evidence = layout["objects"][2]
    root = deepcopy(evidence)
    root.update(object_id="evidence-aperture", object_type="clip" if clip else "mask",
                child_ids=["object-evidence"], initial_state="visible", visible=True,
                asset_id=None, anchors=[], style={"stroke": None, "fill": None, "text": None, "effect": None})
    root.pop("variant")
    root["geometry"]["corner_radius"] = None
    root["transform"]["rotation_degrees"] = rotation
    evidence["parent_id"] = root["object_id"]
    added = [root]
    intent = layout["evidence_treatments"][0]["intent"]
    permissions = ["crop", "scale", "annotate", "color_treatment", "mask", "rotate"]
    layout["evidence_treatments"][0]["allowed_transformations"] = permissions.copy()
    timeline["resolved_assets"][0]["allowed_transformations"] = permissions.copy()
    if not clip:
        root.update(MASK_FIELDS)
        source = deepcopy(layout["objects"][0])
        source.update(object_id="mask-source", object_type=shape, parent_id=None,
                      beat_id=evidence["beat_id"], coverage_ids=deepcopy(evidence["coverage_ids"]),
                      initial_state="visible", visible=True, anchors=[], z_index=4,
                      style={"stroke": None, "fill": None, "text": None, "effect": None})
        # Sibling source rotates independently: its centre equals the card's.
        bx, by = evidence["geometry"]["bounds"]["x"], evidence["geometry"]["bounds"]["y"]
        sx, sy = bx - 200, by - 200
        source["geometry"] = {"bounds": {"x": sx, "y": sy, "width": 900, "height": 820},
                                  "points": [], "corner_radius": 80 if shape == "rounded_rectangle" else None}
        source["transform"]["rotation_degrees"] = rotation
        if shape == "polygon":
            # Concave but the notch lies outside the entire card.
            source["geometry"]["points"] = [{"x": x, "y": y} for x, y in (
                (sx, sy), (sx + 900, sy), (sx + 900, sy + 820), (sx + 760, sy + 820),
                (sx + 760, sy + 720), (sx + 670, sy + 720), (sx + 670, sy + 820), (sx, sy + 820))]
        intent["mask_object_id"] = root["object_id"]
        added.append(source)
    layout["objects"].extend(added)
    layout["boards"][0]["object_ids"].extend(obj["object_id"] for obj in added)
    for obj in added:
        timeline["initial_object_states"].append({
            "object_id": obj["object_id"], "state": "visible", "visible": True, "state_version": 1})
    timeline["evidence_treatments"] = deepcopy(layout["evidence_treatments"])
    timeline["layout_sha256"] = digest(layout)
    return layout, timeline


@pytest.mark.parametrize("shape", ["rectangle", "rounded_rectangle", "ellipse", "polygon"])
def test_permitted_rotated_mask_proves_full_card_in_actual_source_geometry(shape):
    layout, timeline = aperture_documents(shape)
    original = deepcopy((layout, timeline))
    frame = evaluate_frame(layout, timeline, 4900)
    assert frame.object("object-evidence").state == "evidence_visible"
    assert frame.object("object-evidence").visible
    for at in (9000, 4750, 0, 4900):
        evaluate_frame(layout, timeline, at)
    assert evaluate_frame(layout, timeline, 4900) == frame
    assert (layout, timeline) == original


def test_permitted_rotated_clip_uses_inverse_parent_not_world_aabb():
    layout, timeline = aperture_documents(clip=True)
    assert evaluate_frame(layout, timeline, 4900).object("object-evidence").visible


def test_clip_requires_actual_asset_mask_permission_even_without_mask_id():
    layout, timeline = aperture_documents(clip=True, rotation=0)
    for permissions in (layout["evidence_treatments"][0]["allowed_transformations"],
                        timeline["resolved_assets"][0]["allowed_transformations"]):
        permissions.remove("mask")
    timeline["evidence_treatments"] = deepcopy(layout["evidence_treatments"])
    timeline["layout_sha256"] = digest(layout)
    with pytest.raises(ValueError, match="mask permission"):
        evaluate_frame(layout, timeline, 4900)


@pytest.mark.parametrize("shape", ["rectangle", "rounded_rectangle", "ellipse", "polygon"])
def test_mask_bbox_containment_cannot_hide_clipped_corners_or_concave_edge(shape):
    layout, timeline = aperture_documents(shape, rotation=0)
    source = layout["objects"][-1]
    if shape == "rectangle":
        # Source AABB contains the card but its 35-degree aperture does not.
        source["geometry"]["bounds"] = {"x": 680, "y": 130, "width": 500, "height": 420}
        source["transform"]["rotation_degrees"] = 35
    elif shape == "polygon":
        # All four card corners lie inside; notch crosses the right card edge.
        source["geometry"]["points"] = [{"x": x, "y": y} for x, y in (
            (480, -70), (1380, -70), (1380, 250), (1000, 250),
            (1000, 400), (1380, 400), (1380, 750), (480, 750))]
    else:
        source["geometry"]["bounds"] = {"x": 680, "y": 130, "width": 500, "height": 420}
        assert layout["objects"][2]["geometry"]["bounds"] == source["geometry"]["bounds"]
    timeline["layout_sha256"] = digest(layout)
    with pytest.raises(ValueError, match="clipped by.*mask"):
        evaluate_frame(layout, timeline, 4900)


def test_each_actual_ancestor_aperture_intersects_the_declared_mask():
    layout, timeline = aperture_documents()
    inner = deepcopy(layout["objects"][3])
    for key in MASK_FIELDS:
        inner.pop(key)
    inner.update(object_id="inner-clip", object_type="clip", parent_id="evidence-aperture")
    inner["transform"]["rotation_degrees"] = 0
    inner["geometry"]["bounds"]["width"] = 490
    layout["objects"][3]["child_ids"] = ["inner-clip"]
    layout["objects"][2]["parent_id"] = "inner-clip"
    layout["objects"].append(inner)
    layout["boards"][0]["object_ids"].append("inner-clip")
    timeline["initial_object_states"].append({"object_id": "inner-clip", "state": "visible",
                                                 "visible": True, "state_version": 1})
    timeline["layout_sha256"] = digest(layout)
    with pytest.raises(ValueError, match="clipped by.*parent"):
        evaluate_frame(layout, timeline, 4900)


def test_reading_uses_current_sampled_mask_pose_not_authored_pose():
    layout, timeline = aperture_documents("ellipse", rotation=0)
    context, replay = private_clock(layout, timeline)
    sample = replay.at(6000)
    source = sample.object("mask-source")
    moved = replace(source, transform=replace(source.transform,
                    position=replace(source.transform.position, x=700)))
    sample = replace(sample, objects=tuple(moved if f.object_id == moved.object_id else f
                                           for f in sample.objects))
    with pytest.raises(ValueError, match="clipped by.*mask"):
        validate_evidence_reading(context.timeline.actions[2], context.layout, context.objects,
                                  context.layout.evidence_treatments[0], sample,
                                  CameraViewport(0, 0, 1280, 720))


@pytest.mark.parametrize("displaced", [False, True])
def test_reading_uses_current_sampled_clip_and_child_pose(displaced):
    layout, timeline = aperture_documents(clip=True, rotation=0)
    context, replay = private_clock(layout, timeline)
    sample = replay.at(6000)
    frames = []
    for frame in sample.objects:
        if frame.object_id == "evidence-aperture":
            frame = replace(frame, transform=replace(frame.transform, rotation_degrees=23))
        if frame.object_id == "object-evidence" and displaced:
            frame = replace(frame, transform=replace(frame.transform,
                            position=replace(frame.transform.position, x=10)))
        frames.append(frame)
    sample = replace(sample, objects=tuple(frames))
    def validate():
        validate_evidence_reading(context.timeline.actions[2], context.layout, context.objects,
                                  context.layout.evidence_treatments[0], sample,
                                  CameraViewport(0, 0, 1280, 720))
    if displaced:
        with pytest.raises(ValueError, match="clipped by.*parent"):
            validate()
    else:
        validate()


def test_independently_rotated_mask_source_requires_rotation_permission():
    layout, timeline = aperture_documents(rotation=0)
    layout["objects"][-1]["transform"]["rotation_degrees"] = 4
    layout["evidence_treatments"][0]["allowed_transformations"].remove("rotate")
    timeline["resolved_assets"][0]["allowed_transformations"].remove("rotate")
    timeline["evidence_treatments"] = deepcopy(layout["evidence_treatments"])
    timeline["layout_sha256"] = digest(layout)
    with pytest.raises(ValueError, match="undeclared rotation"):
        evaluate_frame(layout, timeline, 4900)
