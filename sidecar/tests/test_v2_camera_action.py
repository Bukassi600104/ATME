"""Camera commands change the same deterministic frame used by SVG and PNG."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from copy import deepcopy
from io import BytesIO

import pytest
from atme.render.v2_state import V2FrameError, evaluate_frame
from atme.render.v2_svg import compose_png_frame, compose_svg_frame
from PIL import Image
from test_v2_svg import primitive_documents
from v2_fixtures import digest


def documents():
    layout, timeline = primitive_documents()
    return layout, timeline


def append_camera(timeline, action_id, verb, start, end, target="object-system",
                  framing="medium", easing="step"):
    trigger = {"kind": "absolute", "at_ms": start}
    timeline["actions"].append({
        "action": {
            "action_id": action_id, "source_instruction_id": "instruction-1",
            "board_id": "board-main", "semantic_reason": "Guide attention to the current model",
            "trigger": trigger, "easing": easing, "expected_state": None,
            "post_state": "framed", "fallback": {"fallback_id": "fallback-1", "on_failure": "block"},
            "coverage_id": "coverage-1", "verb": verb, "target_ids": [target],
            "framing": framing, "movement_purpose": "emphasize",
        },
        "start_ms": start, "end_ms": end,
        "resolved_trigger": {"source": trigger, "alignment_anchor_ms": start,
                             "matched_text": None, "matched_occurrence": None,
                             "resolved_at_ms": start, "confidence": 1, "exact": True},
    })
    timeline["coverage"][0]["action_ids"].append(action_id)
    timeline["actions"].sort(key=lambda item: item["start_ms"])


def viewbox(layout, timeline, at_ms):
    return tuple(float(n) for n in ET.fromstring(
        compose_svg_frame(layout, timeline, at_ms).svg).attrib["viewBox"].split())


def test_cut_is_immediate_and_persists_without_mutating_target_state():
    layout, timeline = documents()
    append_camera(timeline, "camera-1", "camera_cut", 6000, 6500)
    before = evaluate_frame(layout, timeline, 5999)
    at_start = evaluate_frame(layout, timeline, 6000)
    after = evaluate_frame(layout, timeline, 8000)
    assert before.camera.width == 1280
    assert at_start.camera.width < 1280
    assert at_start.camera == after.camera
    assert at_start.object("object-system").state == "visible"
    assert viewbox(layout, timeline, 6000)[2] < 1280
    assert compose_png_frame(layout, timeline, 6000).png != compose_png_frame(layout, timeline, 5999).png


def test_hold_preserves_framing_and_can_retarget_visible_context():
    layout, timeline = documents()
    append_camera(timeline, "camera-1", "camera_cut", 6000, 6100)
    append_camera(timeline, "camera-2", "camera_hold", 7000, 7500)
    assert viewbox(layout, timeline, 7400) == viewbox(layout, timeline, 6500)


@pytest.mark.parametrize("verb", ["camera_pan", "camera_zoom", "camera_reframe"])
def test_continuous_camera_moves_seek_stably(verb):
    layout, timeline = documents()
    if verb == "camera_pan":
        # Equal-size targets permit a same-scale pan from one visual to another.
        layout["objects"][2]["geometry"]["bounds"] = {"x": 680, "y": 130,
                                                       "width": 480, "height": 340}
        timeline["layout_sha256"] = digest(layout)
    first_target = "object-label" if verb == "camera_zoom" else "object-system"
    first_framing = "medium" if verb == "camera_zoom" else "close"
    append_camera(timeline, "camera-1", "camera_cut", 6000, 6100,
                  target=first_target, framing=first_framing)
    if verb == "camera_pan":
        target, framing = "object-evidence", "close"
    elif verb == "camera_zoom":
        target, framing = "object-label", "detail"
    else:
        target, framing = "object-evidence", "medium"
    append_camera(timeline, "camera-2", verb, 7000, 8000,
                  target=target, framing=framing, easing="linear")
    start = evaluate_frame(layout, timeline, 7000).camera
    middle = evaluate_frame(layout, timeline, 7500).camera
    end = evaluate_frame(layout, timeline, 8000).camera
    assert middle != start and middle != end
    assert middle.x == pytest.approx((start.x + end.x) / 2)
    assert middle.width == pytest.approx((start.width + end.width) / 2)
    if verb == "camera_pan":
        assert middle.width == start.width == end.width
    if verb == "camera_zoom":
        assert middle.x + middle.width / 2 == pytest.approx(start.x + start.width / 2)
    evaluate_frame(layout, timeline, 8500)
    assert evaluate_frame(layout, timeline, 7500).camera == middle
    assert compose_svg_frame(layout, timeline, 7500).svg == compose_svg_frame(layout, timeline, 7500).svg
    start_png = compose_png_frame(layout, timeline, 7000).png
    middle_png = compose_png_frame(layout, timeline, 7500).png
    end_png = compose_png_frame(layout, timeline, 8000).png
    assert start_png != middle_png != end_png
    assert compose_png_frame(layout, timeline, 7500).png == middle_png
    assert Image.open(BytesIO(middle_png)).size == (1280, 720)


def test_hidden_unsupported_and_overlapping_camera_targets_fail_closed():
    layout, timeline = documents()
    append_camera(timeline, "camera-1", "camera_cut", 3000, 3500,
                  target="object-evidence")
    with pytest.raises(V2FrameError, match="revealed visible focus"):
        evaluate_frame(layout, timeline, 100)
    layout, timeline = documents()
    append_camera(timeline, "camera-1", "camera_cut", 6000, 7500)
    append_camera(timeline, "camera-2", "camera_cut", 7000, 7900)
    with pytest.raises(V2FrameError, match="overlapping camera actions"):
        evaluate_frame(layout, timeline, 100)
    layout, timeline = documents()
    append_camera(timeline, "camera-1", "camera_cut", 6000, 6500)
    layout["objects"][0]["object_type"] = "evidence"
    layout["objects"][0]["asset_id"] = "asset-evidence"
    layout["objects"][0]["variant"] = "annotated_crop"
    layout["objects"][0]["style"]["fill"] = None
    timeline["layout_sha256"] = digest(layout)
    with pytest.raises((V2FrameError, ValueError)):
        evaluate_frame(layout, timeline, 100)


def test_camera_does_not_silently_replace_legacy_no_camera_viewbox():
    layout, timeline = documents()
    original = compose_svg_frame(layout, timeline, 5000).svg
    modified = deepcopy(timeline)
    append_camera(modified, "camera-1", "camera_cut", 6000, 6500)
    assert compose_svg_frame(layout, modified, 5000).svg == original


def test_camera_uses_completed_transformed_geometry_at_action_start():
    layout, timeline = documents()
    edit = timeline["actions"][2]["action"]
    edit.update({"verb": "move", "target_ids": ["object-system"],
                 "expected_state": "visible", "post_state": "visible",
                 "destination": {"position": {"x": 250, "y": 20}, "scale_x": 1,
                                 "scale_y": 1, "rotation_degrees": 0,
                                 "origin": {"x": 0.5, "y": 0.5}},
                 "opacity": None})
    edit.pop("annotation")
    append_camera(timeline, "camera-1", "camera_cut", 6000, 6500)
    viewport = evaluate_frame(layout, timeline, 6000).camera
    assert viewport.x > 0
    assert viewport.x <= 330
    assert viewport.x + viewport.width >= 810


def test_camera_rejects_concurrent_focus_transform_and_wrong_easing():
    layout, timeline = documents()
    append_camera(timeline, "camera-1", "camera_cut", 2000, 2600,
                  target="object-label")
    with pytest.raises(V2FrameError, match="overlaps a focus-object edit"):
        evaluate_frame(layout, timeline, 100)
    layout, timeline = documents()
    append_camera(timeline, "camera-1", "camera_cut", 6000, 6500,
                  easing="linear")
    with pytest.raises(V2FrameError, match="requires step easing"):
        evaluate_frame(layout, timeline, 100)


def test_portrait_camera_keeps_output_aspect_and_focus_in_frame():
    layout, timeline = documents()
    layout["canvas"] = {"x": 0, "y": 0, "width": 720, "height": 1280}
    layout["output_profile"] = {"profile_id": "SHORT_FORM_9_16",
                                "width": 720, "height": 1280, "fps": 30}
    timeline["output_profile"] = layout["output_profile"]
    timeline["layout_sha256"] = digest(layout)
    append_camera(timeline, "camera-1", "camera_cut", 6000, 6500,
                  framing="close")
    x, y, width, height = viewbox(layout, timeline, 6000)
    assert width < 720
    assert width / height == pytest.approx(720 / 1280, rel=1e-5)
    assert x <= 80 and x + width >= 560
    assert y <= 160 and y + height >= 500


def test_small_focus_cannot_become_unbounded_fullscreen_zoom():
    layout, timeline = documents()
    layout["objects"][0]["geometry"]["bounds"] = {"x": 600, "y": 300,
                                                   "width": 24, "height": 24}
    layout["objects"][0]["geometry"]["corner_radius"] = 6
    timeline["layout_sha256"] = digest(layout)
    append_camera(timeline, "camera-1", "camera_cut", 6000, 6500,
                  framing="detail")
    viewport = evaluate_frame(layout, timeline, 6000).camera
    assert viewport.width >= 1280 * 0.30


def test_hold_and_pan_reject_framing_that_would_be_ignored():
    layout, timeline = documents()
    append_camera(timeline, "camera-1", "camera_cut", 6000, 6100,
                  framing="medium")
    append_camera(timeline, "camera-2", "camera_hold", 7000, 7500,
                  framing="detail")
    with pytest.raises(V2FrameError, match="camera_hold framing disagrees"):
        evaluate_frame(layout, timeline, 7000)
    layout, timeline = documents()
    append_camera(timeline, "camera-1", "camera_cut", 6000, 6100,
                  framing="close")
    append_camera(timeline, "camera-2", "camera_pan", 7000, 8000,
                  target="object-evidence", framing="detail", easing="linear")
    with pytest.raises(V2FrameError, match="camera_pan framing needs"):
        evaluate_frame(layout, timeline, 7000)


def test_safe_area_rejects_focus_touching_output_edge():
    layout, timeline = documents()
    layout["objects"][0]["geometry"]["bounds"]["x"] = 0
    timeline["layout_sha256"] = digest(layout)
    append_camera(timeline, "camera-1", "camera_cut", 6000, 6500,
                  framing="safe_area")
    with pytest.raises(V2FrameError, match="safe_area camera framing"):
        evaluate_frame(layout, timeline, 6000)
    layout, timeline = documents()
    append_camera(timeline, "camera-1", "camera_cut", 6000, 6500,
                  framing="safe_area")
    x, y, width, height = viewbox(layout, timeline, 6000)
    assert 80 >= x + width * 0.08
    assert 160 >= y + height * 0.08
    assert 560 <= x + width * 0.92
    assert 500 <= y + height * 0.92


def test_safe_area_is_checked_on_actual_zoom_destination():
    layout, timeline = documents()
    append_camera(timeline, "camera-1", "camera_cut", 6000, 6100,
                  framing="medium")
    append_camera(timeline, "camera-2", "camera_zoom", 7000, 8000,
                  framing="safe_area", easing="linear")
    with pytest.raises(V2FrameError, match="cannot maintain the safe_area inset"):
        evaluate_frame(layout, timeline, 7500)


def test_camera_bounds_include_completed_scale_and_rotation():
    layout, timeline = documents()
    scale = timeline["actions"][2]["action"]
    scale.update({"verb": "scale", "target_ids": ["object-label"],
                  "expected_state": "visible", "post_state": "visible",
                  "destination": {"position": {"x": 0, "y": 0},
                                  "scale_x": 1.1, "scale_y": 1.1,
                                  "rotation_degrees": 0,
                                  "origin": {"x": 0.5, "y": 0.5}}, "opacity": None})
    scale.pop("annotation")
    trigger = {"kind": "absolute", "at_ms": 5000}
    timeline["actions"].append({
        "action": {"action_id": "rotate-1", "source_instruction_id": "instruction-2",
                   "board_id": "board-main", "semantic_reason": "Turn a concept toward its relation",
                   "trigger": trigger, "easing": "linear", "expected_state": "visible",
                   "post_state": "visible", "fallback": {"fallback_id": "fallback-2",
                                                          "on_failure": "block"},
                   "coverage_id": "coverage-2", "verb": "rotate",
                   "target_ids": ["object-label"],
                   "destination": {"position": {"x": 0, "y": 0},
                                   "scale_x": 1.1, "scale_y": 1.1,
                                   "rotation_degrees": 20,
                                   "origin": {"x": 0.5, "y": 0.5}}, "opacity": None},
        "start_ms": 5000, "end_ms": 5900,
        "resolved_trigger": {"source": trigger, "alignment_anchor_ms": 5000,
                             "matched_text": None, "matched_occurrence": None,
                             "resolved_at_ms": 5000, "confidence": 1, "exact": True},
    })
    timeline["coverage"][1]["action_ids"].append("rotate-1")
    append_camera(timeline, "camera-1", "camera_cut", 6500, 6900,
                  target="object-label", framing="detail")
    viewport = evaluate_frame(layout, timeline, 6500).camera
    # Rotated/scaled geometry is larger than the untransformed text bounds.
    assert viewport.x <= 111
    assert viewport.y <= 150
    assert viewport.x + viewport.width >= 489
    assert viewport.y + viewport.height >= 350
