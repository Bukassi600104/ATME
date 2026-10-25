"""Original layered illustration states through the shared native paint path.

The two authored examples per family are finite verification fixtures, not a
universal state inventory or substitutes for final narrative-video acceptance.
"""

from copy import deepcopy
from io import BytesIO
from pathlib import Path
from socket import socket
from xml.etree import ElementTree as ET

import pytest
from PIL import Image
from test_v2_code_contract import code_object
from test_v2_connector_svg import connector_documents
from test_v2_count_contract import count_action, count_policy
from test_v2_group_annotation import consumer_clock
from test_v2_illustration_assembly_runtime import runtime_documents
from v2_fixtures import digest

from atme.render import v2_state
from atme.render.style_bundle import registry_endpoint_inputs_for_objects
from atme.render.v2_split_paint import verify_split_paint_inputs
from atme.render.v2_svg import (
    _compose_validated_svg_frame,
    _rasterize_svg_frame,
    compose_png_frame,
    compose_svg_frame,
)
from atme.store.contracts_v2 import ExecutableLayoutV2, ResolvedVisualTimelineV2

# Authored absolute path coordinates: silhouettes and state ink actually differ.
ARTWORK = {
    "icon": (
        "M 325 420 L 325 405 Q 285 375 290 325 Q 295 270 360 265 Q 425 270 430 325 Q 435 375 395 405 L 395 420 L 325 420",
        ["M 325 432 L 395 432 L 395 452 L 325 452 L 325 432"],
        "M 340 350 Q 360 370 380 350", "M 365 295 L 342 345 L 367 345 L 350 390 L 390 331 L 365 331 L 380 295",
        "Light off", "Light on", (360, 345)),
    "pictogram": (
        "M 290 350 Q 290 315 255 315 Q 220 315 220 350 Q 220 385 255 385 Q 290 385 290 350",
        ["M 500 350 Q 500 315 465 315 Q 430 315 430 350 Q 430 385 465 385 Q 500 385 500 350",
         "M 290 350 L 430 350"],
        "M 340 330 L 380 370 L 360 350 L 380 330 L 340 370", "M 290 330 Q 360 250 430 330",
        "Disconnected", "Connected", (360, 290)),
    "device": (
        "M 220 245 Q 215 240 215 255 L 215 425 Q 215 435 230 435 L 500 435 Q 510 435 510 420 L 510 255 Q 510 242 495 245 L 220 245",
        ["M 235 265 L 490 265 L 490 410 L 235 410 L 235 265",
         "M 345 435 L 345 475 L 300 490 L 425 490 L 380 475 L 380 435"],
        "M 290 345 Q 315 305 340 345 Q 365 385 390 345 Q 415 305 440 345", "M 310 340 L 350 380 L 420 300",
        "Working", "Ready", (350, 380)),
    "document": (
        "M 265 225 L 395 225 L 455 285 L 455 485 L 265 485 L 265 225",
        ["M 395 225 L 395 285 L 455 285"],
        "M 310 430 L 370 370 L 390 390 L 330 450 L 310 450 L 310 430", "M 305 410 L 340 445 L 410 365",
        "Draft notes", "Approved notes", (340, 445)),
    "terminal": (
        "M 205 245 L 520 245 L 520 465 L 205 465 L 205 245",
        ["M 205 280 L 520 280"],
        "M 465 405 L 495 435 L 480 420 L 495 405 L 465 435", "M 450 420 L 470 440 L 505 400",
        "> test\nfailed", "> build\npassed", (470, 440)),
}


def original_illustration_documents(family="device", *, active=True, portrait=False):
    layout, timeline = runtime_documents()
    objects = {obj["object_id"]: obj for obj in layout["objects"]}
    group, mark, label = (deepcopy(objects[key]) for key in ("illustration-group", "device-shell", "device-label"))
    group["geometry"]["bounds"] = {"x": 180., "y": 200., "width": 360., "height": 400.}
    role = deepcopy(group)
    role.pop("illustration_assembly")
    role.update(object_id="artwork-role", parent_id=group["object_id"], z_index=0)
    main, supports, inactive, enabled, off_label, on_label, _ = ARTWORK[family]
    paths = [main, *supports]
    leaves = []
    for index, path in enumerate(paths):
        leaf = deepcopy(mark)
        leaf.update(object_id=f"original-ink-{index}", parent_id=role["object_id"], object_type="freehand",
                    z_index=index, path_data=path, description=f"Original authored {family} silhouette stroke {index}")
        leaf["geometry"] = {"bounds": {"x": 180., "y": 200., "width": 360., "height": 320.},
                            "points": [], "corner_radius": None}
        leaf["style"].update(stroke="ink.primary", fill=None)
        leaf["anchors"] = [{"anchor_id": "authored-center", "point": {"x": .5, "y": .5}}] if index == 0 else []
        leaves.append(leaf)
    role["child_ids"] = [obj["object_id"] for obj in leaves]
    state = deepcopy(leaves[0])
    state.update(object_id="state-ink", parent_id=group["object_id"], z_index=2, anchors=[],
                 path_data=enabled if active else inactive, description="Explicit separately authored state ink")
    state["style"]["stroke"] = "ink.accent"
    label.update(z_index=1, text=on_label if active else off_label)
    label["geometry"]["bounds"] = {"x": 200., "y": 520., "width": 340., "height": 70.}
    label["style"].update(stroke=None, fill=None, text="text.label")
    if family == "terminal":
        code = code_object()
        code.update({field: deepcopy(label[field]) for field in
            ("object_id", "parent_id", "board_id", "beat_id", "coverage_ids", "z_index", "initial_state", "visible", "geometry", "style")})
        code.update(text=label["text"], anchors=[])
        code["style"].update(stroke=None, fill=None, text="text.code", effect=None)
        code["geometry"].update(points=[], corner_radius=None)
        code["geometry"]["bounds"] = {"x": 225., "y": 300., "width": 285., "height": 95.}
        code["code_payload"]["lines"] = [{"line_id": f"line-{index}", "spans": [
            {"span_id": f"span-{index}", "role": "plain", "text": text}]} for index, text in enumerate(code["text"].split("\n"))]
        label = code
    group["child_ids"] = [role["object_id"], label["object_id"], state["object_id"]]
    group["illustration_assembly"].update(family=family, content_state_id="enabled" if active else "inactive",
        roles=[{"role_id": "artwork", "kind": "artwork", "object_id": role["object_id"]},
               {"role_id": "content", "kind": "content" if family == "terminal" else "label", "object_id": label["object_id"]},
               {"role_id": "status", "kind": "state", "object_id": state["object_id"]}],
        semantic_anchors=[{"semantic_name": {"icon": "filament", "pictogram": "left_node", "device": "display",
            "document": "page", "terminal": "prompt"}[family], "role_id": "artwork",
            "object_id": leaves[0]["object_id"], "anchor_id": "authored-center"}])
    layout["objects"] = [group, role, *leaves, label, state]
    layout["boards"][0].update(object_ids=[obj["object_id"] for obj in layout["objects"]], density_limit=12)
    timeline["initial_object_states"] = [{"object_id": obj["object_id"], "state": obj["initial_state"],
        "visible": obj["visible"], "state_version": 1} for obj in layout["objects"]]
    if portrait:
        layout["output_profile"] = {"profile_id": "SHORT_FORM_9_16", "width": 720, "height": 1280, "fps": 30}
        layout["canvas"].update(width=720, height=1280)
        timeline["output_profile"] = deepcopy(layout["output_profile"])
    timeline["layout_sha256"] = digest(layout)
    ExecutableLayoutV2.model_validate(layout)
    return layout, timeline


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("family", list(ARTWORK))
def test_original_state_art_is_real_compact_layered_and_profile_native(family, portrait, tmp_path):
    outputs = []
    paper, ink, accent = (250, 248, 241, 255), (23, 32, 51, 255), (36, 87, 214, 255)
    for active in (False, True):
        layout, timeline = original_illustration_documents(family, active=active, portrait=portrait)
        before = deepcopy((layout, timeline))
        raw = compose_png_frame(layout, timeline, 0).png
        outputs.append(raw)
        (tmp_path / (family + ("-enabled.png" if active else "-inactive.png"))).write_bytes(raw)
        image = Image.open(BytesIO(raw)).convert("RGBA")
        assert image.size == ((720, 1280) if portrait else (1280, 720))
        assert image.getpixel((100, 100)) == paper
        assert image.getpixel((650, 650)) == paper
        assert image.getpixel(ARTWORK[family][-1]) == (accent if active else paper)
        crop = image.crop((210, 225, 525, 495))
        assert any(crop.getpixel((x, y)) == ink for x in range(crop.width) for y in range(crop.height))
        root = ET.fromstring(compose_svg_frame(layout, timeline, 0).svg)
        width, height = image.size
        assert root.attrib["viewBox"] == f"0 0 {width} {height}"
        ids = [node.attrib["data-object-id"] for node in root.iter() if "data-object-id" in node.attrib]
        assert len(ids) == len(set(ids)) == len(layout["objects"])
        assert ids.count("state-ink") == ids.count("device-label") == 1
        assert compose_png_frame(layout, timeline, 0).png == raw
        assert (layout, timeline) == before
    assert outputs[0] != outputs[1]


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("family", list(ARTWORK))
def test_original_state_shared_paint_is_frozen_offline_and_random_seekable(family, portrait, monkeypatch):
    layout, timeline = original_illustration_documents(family, portrait=portrait)
    typed, clock = ExecutableLayoutV2.model_validate(layout), ResolvedVisualTimelineV2.model_validate(timeline)
    expected = {at: compose_png_frame(layout, timeline, at).png for at in (0, 500, 999, 1000)}
    assert len({expected[at] for at in (0, 500, 1000)}) == 3  # real whole-assembly fade, not static frame substitution
    inputs = verify_split_paint_inputs(typed, {})
    registry = registry_endpoint_inputs_for_objects({obj.object_id: obj for obj in typed.objects},
        frozen_files={name: raw for name, _, raw in inputs.bundle_bytes})
    monkeypatch.setattr(Path, "read_bytes", lambda *_: pytest.fail("frozen illustration reopened a file"))
    opened = Path.open
    def frozen_font_write_only(path, mode="r", *args, **kwargs):
        # The accepted rasterizer materializes authenticated frozen font bytes
        # into its own temporary directory. That is not a live resource read.
        if not mode.startswith(("w", "x", "a")) or "+" in mode:
            pytest.fail("frozen illustration opened a live file for reading")
        return opened(path, mode, *args, **kwargs)
    monkeypatch.setattr(Path, "open", frozen_font_write_only)
    monkeypatch.setattr(socket, "connect", lambda *_: pytest.fail("offline illustration used network"))
    for at in (1000, 0, 999, 500, 0):
        sample = v2_state._evaluate_frame_with_registry_inputs(layout, timeline, at, registry)
        frame = _compose_validated_svg_frame(typed, clock, sample, {}, split_inputs=inputs)
        png = _rasterize_svg_frame(typed, frame, split_inputs=inputs).png
        assert png == expected[at]


@pytest.mark.parametrize("portrait", [False, True])
def test_state_layer_animates_independently_without_repainting_its_silhouette_or_label(portrait):
    layout, timeline = original_illustration_documents(portrait=portrait)
    timeline["actions"][0]["action"]["target_ids"] = ["state-ink"]
    before = deepcopy((layout, timeline))
    images = {at: Image.open(BytesIO(compose_png_frame(layout, timeline, at).png)).convert("RGBA") for at in (0, 500, 1000)}
    assert len({image.getpixel((350, 380)) for image in images.values()}) == 3
    assert images[0].getpixel((350, 380)) == (36, 87, 214, 255)
    for image in images.values():
        assert image.getpixel((215, 300)) == (23, 32, 51, 255)
        assert image.crop((200, 520, 540, 590)).tobytes() == images[0].crop((200, 520, 540, 590)).tobytes()
    assert (layout, timeline) == before


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("aperture", ["clip", "mask"])
def test_real_nested_illustration_uses_shared_aperture_without_duplicate_paint(portrait, aperture):
    layout, timeline = original_illustration_documents(portrait=portrait)
    group = layout["objects"][0]
    outer = deepcopy(group)
    outer.pop("illustration_assembly")
    outer.update(object_id="shared-aperture", object_type=aperture, child_ids=[group["object_id"]])
    outer["geometry"]["bounds"]["width"] = 200.
    group["parent_id"] = outer["object_id"]
    layout["objects"].append(outer)
    if aperture == "mask":
        source = deepcopy(next(obj for obj in layout["objects"] if obj["object_id"] == "original-ink-0"))
        source.pop("path_data")
        source.update(object_id="mask-source", object_type="rectangle", parent_id=None, anchors=[],
                      geometry=deepcopy(outer["geometry"]), style={"stroke": None, "fill": None, "text": None, "effect": None})
        outer.update(mask_mode="alpha", mask_source_object_id="mask-source", mask_coordinate_space="parent_local",
                     invert=False, feather_px=0)
        layout["objects"].append(source)
    layout["boards"][0]["object_ids"] = [obj["object_id"] for obj in layout["objects"]]
    timeline["initial_object_states"] = [{"object_id": obj["object_id"], "state": obj["initial_state"],
        "visible": obj["visible"], "state_version": 1} for obj in layout["objects"]]
    timeline["layout_sha256"] = digest(layout)
    images = {at: compose_png_frame(layout, timeline, at).png for at in (0, 500, 1000)}
    image = Image.open(BytesIO(images[0])).convert("RGBA")
    assert image.getpixel((215, 300)) == (23, 32, 51, 255)
    assert image.getpixel((510, 300)) == (250, 248, 241, 255)
    root = ET.fromstring(compose_svg_frame(layout, timeline, 0).svg)
    ids = [node.attrib["data-object-id"] for node in root.iter() if "data-object-id" in node.attrib]
    assert ids.count("original-ink-0") == ids.count("artwork-role") == ids.count("illustration-group") == 1
    assert "mask-source" not in ids
    assert len(set(images.values())) == 3
    for at in (1000, 0, 500):
        assert compose_png_frame(layout, timeline, at).png == images[at]


@pytest.mark.parametrize("portrait", [False, True])
def test_real_illustration_relationship_tracks_named_leaves_through_root_motion(portrait):
    layout, timeline = original_illustration_documents(portrait=portrait)
    group = layout["objects"][0]
    action = timeline["actions"][0]["action"]
    action.update(verb="move", destination=deepcopy(group["transform"]))
    action.pop("opacity")
    action["destination"]["position"].update(x=40., y=20.)
    arrow_layout, _ = connector_documents()
    arrow = deepcopy(arrow_layout["objects"][-1])
    arrow.update(initial_state="visible", visible=True, source_object_id="original-ink-0", source_anchor_id="authored-center",
        destination_object_id="device-label", destination_anchor_id="center", z_index=11)
    arrow["geometry"]["bounds"] = {"x": 180., "y": 200., "width": 400., "height": 400.}
    layout["objects"].append(arrow)
    layout["boards"][0]["object_ids"].append(arrow["object_id"])
    timeline["initial_object_states"].append({"object_id": arrow["object_id"], "state": "visible", "visible": True, "state_version": 1})
    timeline["layout_sha256"] = digest(layout)
    before = deepcopy((layout, timeline))
    pngs = {}
    for at, expected in ((0, "M 360 360 L 370 555"), (500, "M 380 370 L 390 565"), (1000, "M 400 380 L 410 575")):
        root = ET.fromstring(compose_svg_frame(layout, timeline, at).svg)
        node = next(node for node in root.iter() if node.attrib.get("data-object-id") == "object-arrow")
        assert next(node for node in node if node.tag.endswith("path")).attrib["d"] == expected
        pngs[at] = compose_png_frame(layout, timeline, at).png
    assert len(set(pngs.values())) == 3
    assert compose_png_frame(layout, timeline, 500).png == pngs[500]
    assert (layout, timeline) == before


@pytest.mark.parametrize("portrait", [False, True])
def test_count_inside_real_authored_label_keeps_numeric_provenance_and_other_roles(portrait):
    layout, timeline = original_illustration_documents(portrait=portrait)
    label = next(obj for obj in layout["objects"] if obj["object_id"] == "device-label")
    policy = count_policy(text_object_id=label["object_id"])
    label["text"] = policy["start_text"]
    action = count_action(policy)
    previous = timeline["actions"][0]["action"]
    for field in ("action_id", "source_instruction_id", "board_id", "coverage_id", "fallback", "trigger"):
        action[field] = deepcopy(previous[field])
    action["target_ids"] = [label["object_id"]]
    timeline["actions"][0]["action"] = action
    timeline["layout_sha256"] = digest(layout)
    before = deepcopy((layout, timeline))
    middle = v2_state.evaluate_frame(layout, timeline, 500)
    end = v2_state.evaluate_frame(layout, timeline, 1000)
    assert middle.object(label["object_id"]).count_value == (5, 1)
    assert middle.object(label["object_id"]).display_text == "5 widgets"
    assert end.object(label["object_id"]).count_value == (10, 1)
    assert end.object(label["object_id"]).display_text == "10 widgets"
    _, replay, _ = consumer_clock(layout, timeline)
    assert dict(replay.at(1000).state_versions) == {obj["object_id"]: 2 if obj["object_id"] == label["object_id"] else 1
                                        for obj in layout["objects"]}
    images = {at: compose_png_frame(layout, timeline, at).png for at in (0, 500, 1000)}
    assert len(set(images.values())) == 3
    for at in (1000, 0, 500):
        assert compose_png_frame(layout, timeline, at).png == images[at]
    assert (layout, timeline) == before
