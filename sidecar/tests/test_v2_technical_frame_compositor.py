"""Native chrome and real authored role objects share one normal/frozen tree."""

import xml.etree.ElementTree as ET
from copy import deepcopy
from io import BytesIO
from pathlib import Path
from socket import socket

import pytest
from PIL import Image
from test_v2_progressive_list import list_documents
from test_v2_technical_frame_contract import CASES, documents
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
from atme.render.v2_technical_frame import technical_frame_geometry
from atme.store.contracts_v2 import (
    ExecutableLayoutV2,
    ResolvedVisualTimelineV2,
    VisualObject,
)


def composite_documents(kind="browser", state="ready", roles=None, *, portrait=False):
    roles = roles or ["title", "address", "content"]
    _, layout = documents(kind, state, roles)
    layout["objects"] = [obj for obj in layout["objects"] if obj["object_id"] not in {"object-system", "object-label"}]
    objects = {obj["object_id"]: obj for obj in layout["objects"]}
    chrome = objects["object-evidence"]
    chrome["geometry"]["bounds"] = {"x": 100., "y": 200., "width": 500., "height": 300.}
    chrome["style"] = {"stroke": "ink", "fill": None, "text": None, "effect": None}
    for obj in objects.values():
        obj.update(initial_state="visible", visible=True, opacity=1.)
    geometry = technical_frame_geometry(VisualObject.model_validate(chrome))
    _, ax, ay = geometry.anchors[0]
    chrome["anchors"][0]["point"] = {"x": (ax - 100)/500, "y": (ay - 200)/300}
    for role, x, y, width, height in geometry.regions:
        part = objects["part-" + role]
        part["geometry"]["bounds"] = {"x": x, "y": y, "width": width, "height": height}
        part.update(text=role.replace("_", " "), style={"stroke": None, "fill": None, "text": "text.label", "effect": None})
    objects["list-group"]["geometry"]["bounds"] = deepcopy(chrome["geometry"]["bounds"])
    layout["boards"][0]["object_ids"] = list(objects)
    _, timeline = list_documents()
    row = deepcopy(timeline["actions"][2])
    row["action"] = {key: row["action"][key] for key in ("action_id", "source_instruction_id", "board_id",
        "semantic_reason", "trigger", "easing", "expected_state", "post_state", "fallback", "coverage_id")}
    row["action"].update(verb="fade", target_ids=["list-group"], opacity=.5, destination=None,
        expected_state="visible", post_state="visible", easing="linear")
    row.update(start_ms=0, end_ms=1000)
    row["resolved_trigger"].update(alignment_anchor_ms=0, resolved_at_ms=0)
    timeline.update(actions=[row], resolved_assets=[], coverage=[timeline["coverage"][2]], fallbacks=[timeline["fallbacks"][2]])
    timeline["initial_object_states"] = [{"object_id": obj["object_id"], "state": obj["initial_state"],
        "visible": obj["visible"], "state_version": 1} for obj in objects.values()]
    if portrait:
        layout["output_profile"] = {"profile_id": "SHORT_FORM_9_16", "width": 720, "height": 1280, "fps": 30}
        layout["canvas"] = {"x": 0, "y": 0, "width": 720, "height": 1280}
        timeline["output_profile"] = deepcopy(layout["output_profile"])
    timeline["layout_sha256"] = digest(layout)
    timeline["plan_sha256"] = layout["plan_sha256"]
    # These are real strict paired artifacts, not bypassed frame records.
    ExecutableLayoutV2.model_validate(layout)
    ResolvedVisualTimelineV2.model_validate(timeline)
    return layout, timeline


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("kind,states,roles", CASES)
def test_all_native_kinds_paint_real_roles_once_through_actual_group_fade(kind, states, roles, portrait):
    layout, timeline = composite_documents(kind, states[0], roles, portrait=portrait)
    before = deepcopy((layout, timeline))
    first = compose_svg_frame(layout, timeline, 0).svg
    tree = ET.fromstring(first)
    ids = [node.attrib["data-object-id"] for node in tree.iter() if "data-object-id" in node.attrib]
    for obj in layout["objects"]:
        assert ids.count(obj["object_id"]) == 1
    for role in roles:
        assert role.replace("_", " ") in "".join(tree.itertext())
    pixels = {time: compose_png_frame(layout, timeline, time).png for time in (0, 500, 1000)}
    assert pixels[0] != pixels[500] != pixels[1000]
    assert compose_png_frame(layout, timeline, 500).png == pixels[500]
    assert (layout, timeline) == before


@pytest.mark.parametrize("portrait", [False, True])
def test_frozen_same_composite_updates_from_same_history_without_live_reads(portrait, monkeypatch):
    layout, timeline = composite_documents(portrait=portrait)
    expected = {time: compose_png_frame(layout, timeline, time).png for time in (0, 500, 1000)}
    typed, resolved = ExecutableLayoutV2.model_validate(layout), ResolvedVisualTimelineV2.model_validate(timeline)
    inputs = verify_split_paint_inputs(typed, {})
    registry = registry_endpoint_inputs_for_objects({obj.object_id: obj for obj in typed.objects},
        frozen_files={name: raw for name, _, raw in inputs.bundle_bytes})
    def forbidden(*args, **kwargs):
        raise AssertionError("frozen native composite attempted live IO")
    monkeypatch.setattr(Path, "read_bytes", forbidden)
    monkeypatch.setattr(socket, "connect", forbidden)
    for time in (1000, 0, 500, 1000):
        sample = v2_state._evaluate_frame_with_registry_inputs(layout, timeline, time, registry)
        frame = _compose_validated_svg_frame(typed, resolved, sample, {}, split_inputs=inputs)
        assert _rasterize_svg_frame(typed, frame, split_inputs=inputs).png == expected[time]


@pytest.mark.parametrize("fault", ["hidden", "removed", "alpha", "chrome_local_fade", "chrome_local_move"])
def test_real_chronology_rejects_positive_parts_without_ready_stable_chrome(fault):
    layout, timeline = composite_documents()
    chrome = layout["objects"][0]
    initial = timeline["initial_object_states"][0]
    if fault in {"hidden", "removed"}:
        chrome.update(initial_state=fault, visible=False)
        initial.update(state=fault, visible=False)
    elif fault == "alpha":
        chrome["opacity"] = .5
    elif fault == "chrome_local_fade":
        timeline["actions"][0]["action"]["target_ids"] = [chrome["object_id"]]
    else:
        action = timeline["actions"][0]["action"]
        action.update(verb="move", target_ids=[chrome["object_id"]], opacity=None,
            destination={"position": {"x": 1., "y": 0.}, "scale_x": 1., "scale_y": 1.,
                         "rotation_degrees": 0., "origin": {"x": .5, "y": .5}})
    timeline["layout_sha256"] = digest(layout)
    with pytest.raises(ValueError, match="technical_frame.*chrome"):
        v2_state.evaluate_frame(layout, timeline, 0)


def test_parts_can_be_nonpainting_while_chrome_constructs():
    layout, timeline = composite_documents()
    for obj, initial in zip(layout["objects"], timeline["initial_object_states"], strict=True):
        if obj["object_id"].startswith("part-") or obj["object_id"] == "object-evidence":
            obj.update(initial_state="hidden", visible=False)
            initial.update(state="hidden", visible=False)
    action = timeline["actions"][0]["action"]
    action.pop("destination")
    action.pop("opacity")
    action.update(verb="reveal", target_ids=["object-evidence"], expected_state="hidden", post_state="visible", annotation=None)
    timeline["layout_sha256"] = digest(layout)
    assert "part-title" not in compose_svg_frame(layout, timeline, 500).svg
    assert "object-evidence" in compose_svg_frame(layout, timeline, 500).svg


def action_row(template, action, start, end, key):
    row = deepcopy(template)
    row["action"].update(action)
    row["action"]["action_id"] = key
    row["action"]["trigger"] = {"kind": "absolute", "at_ms": start}
    row.update(start_ms=start, end_ms=end)
    row["resolved_trigger"].update(source=deepcopy(row["action"]["trigger"]), alignment_anchor_ms=start,
        resolved_at_ms=start, matched_text=None, matched_occurrence=None, confidence=1., exact=True)
    return row


def set_actions(timeline, rows):
    timeline["actions"] = rows
    timeline["coverage"][0]["action_ids"] = [row["action"]["action_id"] for row in rows]


@pytest.mark.parametrize("overlap", [False, True])
def test_parts_must_finish_exit_before_chrome_teardown_boundary(overlap):
    layout, timeline = composite_documents()
    base = deepcopy(timeline["actions"][0])
    base["action"].pop("opacity")
    base["action"].pop("destination")
    roots = [obj["object_id"] for obj in layout["objects"] if obj["object_id"].startswith("part-")]
    first = action_row(base, {"verb": "exit", "target_ids": roots, "post_state": "removed", "annotation": None}, 0, 1000, "parts-out")
    second = action_row(timeline["actions"][0], {"target_ids": ["object-evidence"]},
                        999 if overlap else 1000, 2000, "chrome-out")
    set_actions(timeline, [first, second])
    if overlap:
        with pytest.raises(ValueError, match="technical_frame.*chrome"):
            v2_state.evaluate_frame(layout, timeline, 0)
    else:
        assert "part-title" in compose_svg_frame(layout, timeline, 500).svg
        assert "part-title" not in compose_svg_frame(layout, timeline, 1500).svg


def test_whole_group_enter_and_exit_preserve_local_chrome_readiness():
    layout, timeline = composite_documents()
    group = next(obj for obj in layout["objects"] if obj["object_id"] == "list-group")
    group.update(initial_state="hidden", visible=False)
    initial = next(obj for obj in timeline["initial_object_states"] if obj["object_id"] == "list-group")
    initial.update(state="hidden", visible=False)
    base = timeline["actions"][0]
    base["action"].pop("opacity")
    base["action"].pop("destination")
    first = action_row(base, {"verb": "enter", "expected_state": "hidden", "post_state": "visible", "annotation": None}, 0, 1000, "group-in")
    second = action_row(base, {"verb": "exit", "post_state": "removed", "annotation": None}, 2000, 3000, "group-out")
    set_actions(timeline, [first, second])
    timeline["layout_sha256"] = digest(layout)
    full = compose_png_frame(layout, timeline, 1000).png
    assert compose_png_frame(layout, timeline, 500).png != full
    assert compose_png_frame(layout, timeline, 2500).png != full
    assert "part-title" not in compose_svg_frame(layout, timeline, 3000).svg


@pytest.mark.parametrize("portrait", [False, True])
def test_all_sixteen_states_remain_distinct_in_actual_composite_pixels(portrait):
    for kind, states, roles in CASES:
        pixels = []
        for state in states:
            layout, timeline = composite_documents(kind, state, roles, portrait=portrait)
            with Image.open(BytesIO(compose_png_frame(layout, timeline, 0).png)) as image:
                pixels.append(image.convert("RGBA").tobytes())
        assert len(set(pixels)) == len(states)


def test_role_local_write_uses_real_text_after_ready_chrome():
    layout, timeline = composite_documents()
    title = next(obj for obj in layout["objects"] if obj["object_id"] == "part-title")
    title.update(initial_state="hidden", visible=False)
    initial = next(obj for obj in timeline["initial_object_states"] if obj["object_id"] == "part-title")
    initial.update(state="hidden", visible=False)
    row = timeline["actions"][0]
    row["action"].pop("opacity")
    row["action"].pop("destination")
    row["action"].update(verb="write", target_ids=["part-title"], expected_state="hidden", annotation=None)
    timeline["layout_sha256"] = digest(layout)
    partial = compose_svg_frame(layout, timeline, 500).svg
    assert "part-title" in partial and ">ti</tspan>" in partial
    assert ">title</tspan>" in compose_svg_frame(layout, timeline, 1000).svg


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("aperture", ["clip", "mask"])
def test_real_nested_role_and_shared_aperture_use_actual_native_tree(portrait, aperture):
    layout, timeline = composite_documents(portrait=portrait)
    objects = {obj["object_id"]: obj for obj in layout["objects"]}
    content = objects["part-content"]
    leaf = deepcopy(content)
    leaf.update(object_id="content-leaf", parent_id="part-content")
    content.pop("text")
    content.pop("items")
    content.update(object_type="group", child_ids=["content-leaf"], anchors=[],
        style={"stroke": None, "fill": None, "text": None, "effect": None})
    outer = deepcopy(objects["list-group"])
    outer.update(object_id="shared-aperture", object_type=aperture, child_ids=["list-group"])
    outer["geometry"]["bounds"].update(width=250.)
    objects["list-group"]["parent_id"] = outer["object_id"]
    layout["objects"].extend([leaf, outer])
    if aperture == "mask":
        source = deepcopy(leaf)
        source.pop("text")
        source.pop("items")
        source.update(object_id="mask-source", object_type="rectangle", parent_id=None, anchors=[],
            geometry=deepcopy(outer["geometry"]),
            style={"stroke": None, "fill": None, "text": None, "effect": None})
        outer.update(mask_mode="alpha", mask_source_object_id="mask-source",
            mask_coordinate_space="parent_local", invert=False, feather_px=0)
        layout["objects"].append(source)
    layout["boards"][0]["object_ids"] = [obj["object_id"] for obj in layout["objects"]]
    layout["boards"][0]["density_limit"] = len(layout["objects"])
    timeline["initial_object_states"] = [{"object_id": obj["object_id"], "state": obj["initial_state"],
        "visible": obj["visible"], "state_version": 1} for obj in layout["objects"]]
    timeline["layout_sha256"] = digest(layout)
    original = deepcopy((layout, timeline))
    images = {at: compose_png_frame(layout, timeline, at).png for at in (0, 500, 1000)}
    assert len(set(images.values())) == 3
    with Image.open(BytesIO(images[0])) as image:
        image = image.convert("RGB")
        # Literal browser side-strokes, left retained and right excluded.
        assert image.getpixel((105, 350)) != (250, 248, 241)
        assert image.getpixel((595, 350)) == (250, 248, 241)
    svg = compose_svg_frame(layout, timeline, 500).svg
    tree = ET.fromstring(svg)
    ids = [node.attrib["data-object-id"] for node in tree.iter() if "data-object-id" in node.attrib]
    assert ids.count("content-leaf") == ids.count("part-content") == ids.count("object-evidence") == 1
    assert "mask-source" not in ids
    for at in (1000, 0, 500):
        assert compose_png_frame(layout, timeline, at).png == images[at]
    assert (layout, timeline) == original
