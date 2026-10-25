"""Real list headings/items share ordinary paint, state and frozen resources."""

import io
from copy import deepcopy

import pytest
import resvg_py
from atme.render.style_bundle import load_bundle
from atme.render.v2_split_paint import verify_split_paint_inputs
from atme.render.v2_state import V2FrameError, evaluate_frame
from atme.render.v2_svg import (
    _compose_validated_svg_frame,
    _rasterize_svg_frame,
    compose_png_frame,
    compose_svg_frame,
)
from atme.store.contracts_v2 import ExecutableLayoutV2, ResolvedVisualTimelineV2
from PIL import Image
from test_v2_group_annotation import consumer_clock
from test_v2_progressive_list import list_documents
from test_v2_structured_list_contract import documents, payload
from v2_fixtures import digest


def native_documents(portrait=False):
    _, layout = documents()
    _, timeline = list_documents()
    layout["objects"] = [obj for obj in layout["objects"]
        if obj["object_id"] in {"object-evidence", "list-group", *payload()["item_object_ids"]}]
    x, y = (90, 280) if portrait else (80, 100)
    for index, obj in enumerate(layout["objects"]):
        obj["geometry"]["bounds"] = {"x": x, "y": y + 40*index, "width": 500, "height": 40}
        if obj["object_type"] == "group":
            obj["geometry"]["bounds"] = {"x": 0, "y": 0, "width": 600, "height": 600}
        if obj["object_type"] == "text":
            obj.update(visible=True, initial_state="visible")
    layout["boards"][0].update(object_ids=[obj["object_id"] for obj in layout["objects"]], density_limit=5)
    timeline["actions"] = [timeline["actions"][2]]
    timeline["actions"][0]["action"]["verb"] = "reveal"
    timeline["coverage"] = [timeline["coverage"][2]]
    timeline["fallbacks"] = [timeline["fallbacks"][2]]
    timeline["initial_object_states"] = [{"object_id": obj["object_id"], "state": obj["initial_state"],
        "state_version": 1, "visible": obj["visible"]} for obj in layout["objects"]]
    timeline["resolved_assets"] = []
    timeline["plan_sha256"] = layout["plan_sha256"]
    if portrait:
        profile = {"profile_id": "SHORT_FORM_9_16", "width": 720, "height": 1280, "fps": 30}
        layout["output_profile"] = timeline["output_profile"] = profile
        layout["canvas"].update(width=720, height=1280)
    timeline["layout_sha256"] = digest(layout)
    return layout, timeline


def rgba(png):
    with Image.open(io.BytesIO(png)) as image:
        return image.convert("RGBA").tobytes()


@pytest.mark.parametrize("portrait", [False, True])
def test_structured_heading_only_and_real_item_pixels_are_literal_and_seek_independent(portrait):
    layout, timeline = native_documents(portrait)
    _, _, root = load_bundle()
    width, height = (720, 1280) if portrait else (1280, 720)
    x, y = (90, 280) if portrait else (80, 100)
    frames = {}
    for at_ms in (0, 4900):
        actual = compose_png_frame(layout, timeline, at_ms)
        rows = [(0, "The process")] if at_ms == 4900 else []
        rows += [(1, "Gather evidence"), (2, "Explain the change"), (3, "Return to the model")]
        text = "".join(f'<text x="{x}" y="{y+40*index+21.3333:.4f}" fill="#172033" '
            'font-family="Atkinson Hyperlegible" font-weight="400" font-size="21.3333" '
            f'xml:space="preserve">{value}</text>' for index, value in rows)
        literal = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">'
            f'<rect width="{width}" height="{height}" fill="#FAF8F1"/>{text}</svg>')
        expected = bytes(resvg_py.svg_to_bytes(svg_string=literal,
            font_files=[str(root / "fonts/AtkinsonHyperlegible-Regular.otf")], skip_system_fonts=True))
        assert rgba(actual.png) == rgba(expected)
        svg = compose_svg_frame(layout, timeline, at_ms).svg
        assert "•" not in svg
        for key in payload()["item_object_ids"]:
            assert f'data-object-id="{key}"' in svg
        frames[at_ms] = (svg, actual.png)
    for at_ms in (4900, 0, 4900, 0):
        assert (compose_svg_frame(layout, timeline, at_ms).svg,
            compose_png_frame(layout, timeline, at_ms).png) == frames[at_ms]


@pytest.mark.parametrize("portrait", [False, True])
def test_structured_native_source_and_frozen_compositor_share_identical_frames(portrait):
    raw, resolved = native_documents(portrait)
    layout = ExecutableLayoutV2.model_validate(raw)
    timeline = ResolvedVisualTimelineV2.model_validate(resolved)
    inputs = verify_split_paint_inputs(layout, {})
    for at_ms in (0, 4450, 4900):
        snapshot = evaluate_frame(raw, resolved, at_ms)
        frozen = _compose_validated_svg_frame(layout, timeline, snapshot, {}, split_inputs=inputs)
        assert frozen == compose_svg_frame(raw, resolved, at_ms)
        assert _rasterize_svg_frame(layout, frozen, split_inputs=inputs) == compose_png_frame(raw, resolved, at_ms)


@pytest.mark.parametrize("portrait", [False, True])
def test_structured_item_can_be_edited_by_its_real_id_without_rewriting_heading_or_siblings(portrait):
    layout, timeline = native_documents(portrait)
    row = deepcopy(timeline["actions"][0])
    row.update(start_ms=5000, end_ms=5100)
    row["action"].update(action_id="remove-one-item",
        verb="exit", target_ids=["list-item-b"], expected_state="visible", post_state="removed")
    timeline["actions"].append(row)
    timeline["coverage"][0]["action_ids"].append(row["action"]["action_id"])
    frame = evaluate_frame(layout, timeline, 5100)
    assert frame.object("list-item-b").state == "removed"
    _, replay, _ = consumer_clock(layout, timeline)
    versions = dict(replay.at(5100).state_versions)
    assert versions["list-item-a"] == versions["list-item-c"] == 1
    assert versions["list-item-b"] == 2
    svg = compose_svg_frame(layout, timeline, 5100).svg
    assert "Explain the change" not in svg
    assert all(value in svg for value in ("The process", "Gather evidence", "Return to the model"))


def test_structured_payload_does_not_repurpose_bare_legacy_progression():
    layout, timeline = native_documents()
    timeline["actions"][0]["action"]["verb"] = "progressive_reveal"
    with pytest.raises(V2FrameError, match="ordered-child list"):
        compose_svg_frame(layout, timeline, 0)
