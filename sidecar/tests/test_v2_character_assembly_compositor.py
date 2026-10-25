"""Original authored pose ink through the native, shared production tree."""

import xml.etree.ElementTree as ET
from copy import deepcopy
from io import BytesIO

import pytest
from PIL import Image
from test_v2_character_assembly_runtime import nested_role, runtime_documents
from v2_fixtures import digest

from atme.render.v2_svg import compose_png_frame, compose_svg_frame
from atme.store.contracts_v2 import ExecutableLayoutV2


def original_pose_documents(pose="neutral", *, portrait=False):
    layout, timeline = runtime_documents(pose=pose, portrait=portrait)
    head, silhouette = nested_role(layout, "head")
    face = deepcopy(silhouette)
    face.update(object_id="actor-face-ink", object_type="freehand", z_index=1, anchors=[],
        path_data="M 349 256 Q 356 250 362 256 L 357 264 L 357 267 "
                  "L 368 278 L 375 278 L 371 266 Q 375 255 379 256 "
                  "Q 386 250 393 256 L 385 264 L 385 267",
        description="Original separately authored continuous portrait face ink")
    mouth = deepcopy(face)
    mouth.update(object_id="actor-smile-ink", z_index=2, path_data="M 358 287 Q 370 295 384 286")
    head["child_ids"].extend([face["object_id"], mouth["object_id"]])
    # Paint order is explicit, independent of object-array order or alpha.
    layout["objects"].extend([face, mouth])
    objects = {obj["object_id"]: obj for obj in layout["objects"]}
    objects["actor-torso"]["path_data"] = (
        "M 350 315 L 330 330 L 323 416 L 340 420 L 335 500 L 360 500 L 371 438 "
        "L 384 500 L 385 507 L 417 507 L 409 500 L 399 420 L 418 416 "
        "L 411 330 L 391 315 Q 370 336 350 315")
    # A freehand Mark is one continuous stroke. Fingers remain explicitly
    # authored in that same real arm stroke; never weaken path admission.
    for key in ("actor-left_arm", "actor-right_arm"):
        objects[key]["path_data"] = objects[key]["path_data"].replace(" M ", " L ")
    # Existing non-character objects are hidden rather than deleted/relabelled.
    for obj in layout["objects"]:
        if not obj["object_id"].startswith("actor-"):
            obj.update(initial_state="hidden", visible=False)
    layout["boards"][0]["object_ids"] = [obj["object_id"] for obj in layout["objects"]]
    timeline["initial_object_states"] = [{"object_id": obj["object_id"], "state": obj["initial_state"],
        "visible": obj["visible"], "state_version": 1} for obj in layout["objects"]]
    timeline["layout_sha256"] = digest(layout)
    ExecutableLayoutV2.model_validate(layout)
    return layout, timeline


@pytest.mark.parametrize("portrait", [False, True])
def test_original_pose_ink_is_distinct_compact_layered_and_native(portrait, tmp_path):
    outputs = {}
    for pose in ("neutral", "point_right", "open_hands"):
        layout, timeline = original_pose_documents(pose, portrait=portrait)
        before = deepcopy((layout, timeline))
        raw = compose_png_frame(layout, timeline, 0).png
        outputs[pose] = raw
        (tmp_path / (pose + ".png")).write_bytes(raw)
        image = Image.open(BytesIO(raw)).convert("RGBA")
        # Native ink at literal authored facial and body coordinates, with
        # genuine paper between distinct parts and outside compact figure.
        paper, ink = (250, 248, 241, 255), (23, 32, 51, 255)
        assert image.getpixel((220, 200)) == paper
        for box in ((346, 248, 396, 296), (325, 328, 419, 508)):
            crop = image.crop(box)
            assert any(crop.getpixel((x, y)) != paper for x in range(crop.width) for y in range(crop.height))
        assert image.getpixel((220, 360)) == paper
        assert image.getpixel((580, 360)) == paper
        root = ET.fromstring(compose_svg_frame(layout, timeline, 0).svg)
        # Independent device mapping from this explicitly authored profile and
        # identity camera, not a renderer helper or a sampled bounds oracle.
        width, height = (720, 1280) if portrait else (1280, 720)
        view = (0, 0, 720, 1280) if portrait else (0, 0, 1280, 720)
        assert image.size == (width, height)
        assert root.attrib["viewBox"] == f"0 0 {width} {height}"
        def device(x, y, *, view=view, pixels=(width, height)):
            return round((x - view[0]) * pixels[0] / view[2]), round((y - view[1]) * pixels[1] / view[3])
        for point in ((335, 270), (370, 230), (357, 266), (370, 438)):
            assert image.getpixel(device(*point)) == ink
        positives = {"neutral": ((310, 440), (435, 440)),
            "point_right": ((310, 440), (500, 347)), "open_hands": ((260, 340), (495, 330))}
        negatives = {"neutral": ((500, 347), (260, 340)),
            "point_right": ((435, 440), (260, 340)), "open_hands": ((310, 440), (500, 347))}
        for point in positives[pose]:
            assert image.getpixel(device(*point)) == ink
        for point in negatives[pose]:
            assert image.getpixel(device(*point)) == paper
        ids = [node.attrib["data-object-id"] for node in root.iter() if "data-object-id" in node.attrib]
        assert len(ids) == len(set(ids)) == 8  # two real Groups and six real Marks
        for key in ("actor-head", "actor-face-ink", "actor-torso", "actor-left_arm", "actor-right_arm"):
            assert ids.count(key) == 1
        assert compose_png_frame(layout, timeline, 0).png == raw
        assert (layout, timeline) == before
    assert len(set(outputs.values())) == 3
