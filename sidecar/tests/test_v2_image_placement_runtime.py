"""Authored supporting pixels use the real native crop/fit and permission path."""

from __future__ import annotations

import base64
import hashlib
import io
import xml.etree.ElementTree as ET
from copy import deepcopy
from dataclasses import replace

import pytest
from PIL import Image, ImageDraw
from test_v2_camera_action import append_camera
from test_v2_composition_contract import composition_definition
from test_v2_external_aperture_runtime import runtime_documents
from test_v2_frame_state import supported_documents
from test_v2_group_hierarchy import grouped_documents
from test_v2_project_image import _documents
from v2_fixtures import digest

from atme.render.v2_state import V2FrameError, evaluate_frame
from atme.render.v2_svg import (
    UnsupportedVisualObject,
    _compose_validated_svg_frame,
    _rasterize_svg_frame,
    compose_png_frame,
    compose_svg_frame,
)
from atme.store.contracts_v2 import (
    CompositionDefinition,
    ExecutableLayoutV2,
    ResolvedVisualTimelineV2,
)

RED = (220, 30, 30)
GREEN = (20, 190, 40)
BLUE = (25, 50, 220)
YELLOW = (240, 210, 20)


def source_pixels():
    image = Image.new("RGBA", (80, 40), (231, 20, 180, 255))
    draw = ImageDraw.Draw(image)
    for box, color in (((20, 10, 39, 19), RED), ((40, 10, 59, 19), GREEN),
                       ((20, 20, 39, 29), BLUE), ((40, 20, 59, 29), YELLOW)):
        draw.rectangle(box, fill=(*color, 255))
    draw.rectangle((30, 12, 33, 15), fill=(0, 0, 0, 0))
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def placement_documents(*, portrait=False, fit="contain", focal=(0.5, 0.5), permissions=None):
    raw = source_pixels()
    layout, clock = _documents("a" * 32, raw, 1, 1)
    for other in layout["objects"][:2]:
        other["opacity"] = 0
    obj = layout["objects"][2]
    obj["geometry"]["bounds"] = {"x": 200, "y": 200, "width": 200, "height": 200}
    permissions = permissions or ["scale", "crop"]
    obj["image_placement"] = {
        "version": "1.0.0", "source_revision": 1,
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "source_width": 80, "source_height": 40,
        "crop": {"x": 20, "y": 10, "width": 40, "height": 20},
        "fit": fit, "focal_point": {"x": focal[0], "y": focal[1]},
        "allowed_transformations": permissions,
    }
    clock["resolved_assets"][0]["allowed_transformations"] = permissions[:]
    if portrait:
        profile = {"profile_id": "SHORT_FORM_9_16", "width": 720, "height": 1280, "fps": 30}
        layout["output_profile"] = deepcopy(profile)
        clock["output_profile"] = deepcopy(profile)
        layout["canvas"].update(width=720, height=1280)
    clock["layout_sha256"] = digest(layout)
    return layout, clock, {"a" * 32: raw}


def rgb(frame):
    return Image.open(io.BytesIO(frame.png)).convert("RGB")


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("fit,focal,checks", [
    ("contain", (0.5, 0.5), [(225, 265, RED), (375, 265, GREEN),
                             (225, 335, BLUE), (375, 335, YELLOW)]),
    ("contain", (0.0, 0.0), [(225, 315, RED), (375, 385, YELLOW)]),
    ("contain", (1.0, 1.0), [(225, 215, RED), (375, 285, YELLOW)]),
    ("cover", (0.5, 0.5), [(230, 275, RED), (375, 270, GREEN),
                           (225, 380, BLUE), (375, 380, YELLOW)]),
    ("cover", (0.0, 0.0), [(225, 220, RED), (375, 380, BLUE)]),
    ("cover", (1.0, 1.0), [(225, 220, GREEN), (375, 380, YELLOW)]),
])
def test_native_crop_fit_focal_pixels_and_shuffled_seek(portrait, fit, focal, checks, tmp_path):
    layout, clock, supplied = placement_documents(portrait=portrait, fit=fit, focal=focal)
    frame = compose_png_frame(layout, clock, 5000, supplied)
    image = rgb(frame)
    assert image.size == ((720, 1280) if portrait else (1280, 720))
    for x, y, color in checks:
        assert image.getpixel((x, y)) == color
    assert image.getpixel((199, 300)) not in (RED, GREEN, BLUE, YELLOW, (231, 20, 180))
    assert (231, 20, 180) not in set(image.crop((200, 200, 400, 400)).get_flattened_data())
    if fit == "contain" and focal == (0.5, 0.5):
        # Transparent source pixels stay transparent; contain retains paper padding.
        assert image.getpixel((258, 268)) == image.getpixel((210, 210))
    (tmp_path / f"image-{fit}-{focal[0]}-{portrait}.png").write_bytes(frame.png)
    for at in (8000, 5000, 0, 5000):
        actual = compose_png_frame(layout, clock, at, supplied)
        if at == 5000:
            assert actual.png == frame.png


@pytest.mark.parametrize("field,value", [
    ("revision", 2), ("checksum_sha256", "b" * 64), ("width", 81), ("height", 41),
    ("allowed_transformations", ["scale", "crop", "rotate"]),
])
def test_resolved_image_cannot_change_authored_pins_or_permission_inventory(field, value):
    layout, clock, supplied = placement_documents()
    clock["resolved_assets"][0][field] = value
    with pytest.raises(UnsupportedVisualObject, match="image_placement"):
        compose_svg_frame(layout, clock, 0, supplied)


def image_parent(layout, clock, *, kind="group", rotation=0):
    group = deepcopy(grouped_documents()[0]["objects"][3])
    group.update(object_id="image-parent", object_type=kind, child_ids=["object-evidence"])
    group["geometry"]["bounds"] = {"x": 200, "y": 200, "width": 100, "height": 200}
    group["transform"]["rotation_degrees"] = rotation
    layout["objects"][2]["parent_id"] = group["object_id"]
    layout["objects"].append(group)
    layout["boards"][0]["object_ids"].append(group["object_id"])
    clock["initial_object_states"].append({"object_id": group["object_id"], "state": "visible",
                                            "state_version": 1, "visible": True})
    clock["layout_sha256"] = digest(layout)
    return group


@pytest.mark.parametrize("rotation_owner", ["local", "ancestor"])
def test_rotation_requires_explicit_permission_even_when_image_hidden(rotation_owner):
    layout, clock, supplied = placement_documents()
    if rotation_owner == "local":
        layout["objects"][2]["transform"]["rotation_degrees"] = 20
    else:
        image_parent(layout, clock, rotation=20)
    clock["layout_sha256"] = digest(layout)
    with pytest.raises((UnsupportedVisualObject, V2FrameError), match="rotate"):
        compose_svg_frame(layout, clock, 0, supplied)


def test_authored_clip_requires_mask_permission_but_internal_reveal_does_not():
    layout, clock, supplied = placement_documents()
    compose_svg_frame(layout, clock, 0, supplied)
    image_parent(layout, clock, kind="clip")
    with pytest.raises((UnsupportedVisualObject, V2FrameError), match="mask permission"):
        compose_svg_frame(layout, clock, 0, supplied)


@pytest.mark.parametrize("portrait", [False, True])
def test_permitted_rotation_and_clip_use_the_same_native_hierarchy(portrait):
    layout, clock, supplied = placement_documents(portrait=portrait,
                                                  permissions=["scale", "crop", "rotate", "mask"])
    parent = image_parent(layout, clock, kind="clip", rotation=180)
    # A literal 180-degree pivot maps the retained left half to the right half.
    parent["transform"]["origin"] = {"x": 0.5, "y": 0.5}
    clock["layout_sha256"] = digest(layout)
    frame = compose_png_frame(layout, clock, 5000, supplied)
    image = rgb(frame)
    assert image.getpixel((225, 275)) == BLUE
    assert image.getpixel((215, 335)) == RED
    assert image.getpixel((325, 325)) not in (RED, GREEN, BLUE, YELLOW)


def test_full_source_cover_only_requires_crop_when_it_discards_pixels():
    layout, clock, supplied = placement_documents(permissions=["scale", "crop"])
    placement = layout["objects"][2]["image_placement"]
    placement.update(crop={"x": 0, "y": 0, "width": 80, "height": 40},
                     fit="cover", allowed_transformations=["scale"])
    clock["resolved_assets"][0]["allowed_transformations"] = ["scale"]
    clock["layout_sha256"] = digest(layout)
    with pytest.raises((UnsupportedVisualObject, V2FrameError), match="crop permission"):
        compose_svg_frame(layout, clock, 0, supplied)
    layout["objects"][2]["geometry"]["bounds"]["height"] = 100
    clock["layout_sha256"] = digest(layout)
    compose_svg_frame(layout, clock, 5000, supplied)


@pytest.mark.parametrize("ancestor", [False, True])
@pytest.mark.parametrize("permitted", [False, True])
def test_authored_rotate_intent_checked_before_its_zero_progress_frame(ancestor, permitted):
    permissions = ["scale", "crop", "rotate"] if permitted else ["scale", "crop"]
    layout, clock, supplied = placement_documents(permissions=permissions)
    owner = image_parent(layout, clock) if ancestor else layout["objects"][2]
    rotate = deepcopy(supported_documents("rotate")[1]["actions"][2])
    rotate["action"]["target_ids"] = [owner["object_id"]]
    rotate["action"]["expected_state"] = "visible"
    layout["objects"][2].update(initial_state="visible", visible=True)
    clock["initial_object_states"][2].update(state="visible", visible=True)
    clock["actions"][2] = rotate
    clock["layout_sha256"] = digest(layout)
    if permitted:
        compose_svg_frame(layout, clock, 0, supplied)
        assert compose_png_frame(layout, clock, 5000, supplied).png != compose_png_frame(
            layout, clock, 0, supplied).png
    else:
        with pytest.raises((UnsupportedVisualObject, V2FrameError), match="rotate"):
            compose_svg_frame(layout, clock, 0, supplied)


def test_current_sampled_ancestor_rotation_cannot_bypass_permission():
    layout, clock, supplied = placement_documents()
    parent = image_parent(layout, clock)
    snapshot = evaluate_frame(layout, clock, 5000)
    current = snapshot.object(parent["object_id"])
    rotated = replace(current, transform=replace(current.transform, rotation_degrees=15))
    snapshot = replace(snapshot, objects=tuple(rotated if row.object_id == current.object_id else row
                                               for row in snapshot.objects))
    with pytest.raises(UnsupportedVisualObject, match="rotate"):
        _compose_validated_svg_frame(ExecutableLayoutV2.model_validate(layout),
            ResolvedVisualTimelineV2.model_validate(clock), snapshot, {}, supplied)


def test_composition_image_rotation_override_requires_authored_permission():
    layout, _, _ = placement_documents()
    definition = composition_definition()
    image = deepcopy(layout["objects"][2])
    image.update(object_id="node", parent_id="root", board_id="template-board",
                 beat_id="template-beat", coverage_ids=["coverage-1"], initial_state="visible", visible=True)
    definition["objects"][1] = image
    definition["parameters"] = [{"parameter_id": "angle", "value_type": "number",
        "targets": [{"object_id": "node", "field": "transform.rotation_degrees"}]}]
    with pytest.raises(ValueError):
        CompositionDefinition.model_validate(definition)
    image["image_placement"]["allowed_transformations"].append("rotate")
    assert CompositionDefinition.model_validate(definition).objects[1].image_placement is not None


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("fit,x,y,w,h", [("contain", 0, 50, 200, 100), ("cover", -100, 0, 400, 200)])
def test_native_crop_discards_outside_pixels_before_resampling(portrait, fit, x, y, w, h):
    layout, clock, supplied = placement_documents(portrait=portrait, fit=fit)
    frame = compose_svg_frame(layout, clock, 5000, supplied)
    tree = ET.fromstring(frame.svg)
    owner = tree.find(".//{*}g[@data-object-id='object-evidence']")
    for child in list(owner):
        owner.remove(child)
    with Image.open(io.BytesIO(supplied["a" * 32])) as source:
        output = io.BytesIO()
        source.crop((20, 10, 60, 30)).save(output, format="PNG")
    # Literal crop and placement oracle, independent of the production fit helper.
    ns = "{http://www.w3.org/2000/svg}"
    viewport = ET.SubElement(owner, ns + "svg", {"x": "200", "y": "200", "width": "200", "height": "200",
        "viewBox": "0 0 200 200", "overflow": "hidden"})
    ET.SubElement(viewport, ns + "image", {"x": str(x), "y": str(y), "width": str(w), "height": str(h),
        "preserveAspectRatio": "none", "href": "data:image/png;base64," + base64.b64encode(output.getvalue()).decode()})
    typed = ExecutableLayoutV2.model_validate(layout)
    expected = _rasterize_svg_frame(typed, replace(frame, svg=ET.tostring(tree, encoding="unicode")))
    actual = compose_png_frame(layout, clock, 5000, supplied)
    assert hashlib.sha256(rgb(actual).tobytes()).hexdigest() == hashlib.sha256(rgb(expected).tobytes()).hexdigest()


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("kind", ["clip", "mask"])
@pytest.mark.parametrize("group", [False, True])
def test_external_aperture_read_requires_permission_and_paints_checked_pixels(portrait, kind, group):
    _, layout, clock, ids = runtime_documents(kind, portrait=portrait, group=group)
    base, image_clock, supplied = placement_documents()
    image = next(obj for obj in layout["objects"] if obj["object_id"] == "external-receiver")
    image.update(object_type="image", asset_id="a" * 32,
                 image_placement=deepcopy(base["objects"][2]["image_placement"]),
                 style={"stroke": None, "fill": None, "text": None, "effect": None})
    image["geometry"].update(points=[], corner_radius=None)
    clock["resolved_assets"] = deepcopy(image_clock["resolved_assets"])
    clock["layout_sha256"] = digest(layout)
    with pytest.raises((UnsupportedVisualObject, V2FrameError), match="mask permission"):
        compose_svg_frame(layout, clock, 1000, supplied)
    image["image_placement"]["allowed_transformations"].append("mask")
    clock["resolved_assets"][0]["allowed_transformations"].append("mask")
    clock["layout_sha256"] = digest(layout)
    clipped = compose_png_frame(layout, clock, 1000, supplied)
    # Compare actual clipped pixels with the same owned scene without its explicit read.
    receiver = next(obj for obj in layout["objects"] if obj["object_id"] == ids["receiver"])
    receiver["clip_id"] = None
    clock["layout_sha256"] = digest(layout)
    plain = compose_png_frame(layout, clock, 1000, supplied)
    assert rgb(clipped).tobytes() != rgb(plain).tobytes()


@pytest.mark.parametrize("portrait", [False, True])
def test_authored_image_keeps_shared_camera_and_random_seek_behavior(portrait):
    layout, clock, supplied = placement_documents(portrait=portrait)
    # Exercise the existing global camera through its supported geometry focus.
    # P3-35 does not add a new image-focus family to the camera admission table.
    layout["objects"][0]["opacity"] = 1
    layout["objects"][0]["geometry"]["bounds"] = {"x": 200, "y": 200, "width": 200, "height": 200}
    clock["layout_sha256"] = digest(layout)
    append_camera(clock, "image-camera", "camera_cut", 6000, 6500, target="object-system")
    before = evaluate_frame(layout, clock, 5999)
    after = evaluate_frame(layout, clock, 6500)
    assert after.object("object-evidence").transform == before.object("object-evidence").transform
    assert after.camera.width < before.camera.width
    initial = compose_png_frame(layout, clock, 5999, supplied)
    framed = compose_png_frame(layout, clock, 6500, supplied)
    assert framed.png != initial.png
    assert {RED, GREEN, BLUE, YELLOW} <= set(rgb(framed).get_flattened_data())
    for at in (6500, 5999, 8000, 6500):
        frame = compose_png_frame(layout, clock, at, supplied)
        if at == 6500:
            assert frame.png == framed.png
