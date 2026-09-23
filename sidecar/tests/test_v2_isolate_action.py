"""Explicit focus isolation subdues board context and restores it deterministically."""

from __future__ import annotations

import io
import xml.etree.ElementTree as ET
from copy import deepcopy

import pytest
from atme.render.v2_state import V2FrameError, evaluate_frame
from atme.render.v2_svg import compose_png_frame, compose_svg_frame
from PIL import Image, ImageChops
from test_v2_frame_state import supported_documents
from test_v2_highlight_action import highlight_documents
from test_v2_registry_illustrations import illustration_documents
from v2_fixtures import digest


def isolate_documents(kind="ellipse"):
    layout, timeline = highlight_documents(kind)
    timeline["actions"][2]["action"].update(
        verb="isolate", easing="linear", expected_state="visible", post_state="visible",
    )
    return layout, timeline


def _opacities(svg):
    return {node.attrib["data-object-id"]: float(node.attrib["opacity"])
            for node in ET.fromstring(svg).iter() if "data-object-id" in node.attrib}


@pytest.mark.parametrize("kind", ["ellipse", "text"])
def test_isolate_preserves_focus_and_restores_all_visible_board_context(kind):
    layout, timeline = isolate_documents(kind)
    times = (3999, 4000, 4090, 4450, 4810, 4900, 6000)
    frames = [evaluate_frame(layout, timeline, at_ms) for at_ms in times]
    focus = [frame.object("object-evidence") for frame in frames]
    context = [frame.object("object-label") for frame in frames]
    assert [item.opacity for item in focus] == pytest.approx([1] * len(times))
    assert [item.opacity for item in context] == pytest.approx(
        [1, 1, .675, .35, .675, 1, 1]
    )
    assert all(item.visible and item.state == "visible" and item.reveal_fraction == 1
               for item in focus + context)
    assert all(item.transform == focus[0].transform for item in focus)
    svgs = [compose_svg_frame(layout, timeline, at_ms).svg for at_ms in times]
    assert [_opacities(svg)["object-evidence"] for svg in svgs] == pytest.approx([1] * len(times))
    assert [_opacities(svg)["object-label"] for svg in svgs] == pytest.approx(
        [1, 1, .675, .35, .675, 1, 1], abs=1e-4
    )
    assert 'clip-path="url(#' not in svgs[3]
    assert ("THE MECHANISM" if kind == "text" else "<ellipse") in svgs[3]
    before = Image.open(io.BytesIO(compose_png_frame(layout, timeline, 3999).png)).convert("RGB")
    middle = Image.open(io.BytesIO(compose_png_frame(layout, timeline, 4450).png)).convert("RGB")
    after = Image.open(io.BytesIO(compose_png_frame(layout, timeline, 4900).png)).convert("RGB")
    assert ImageChops.difference(before, middle).getbbox()
    assert ImageChops.difference(before, after).getbbox() is None
    assert evaluate_frame(layout, timeline, 4450) == frames[3]
    assert compose_svg_frame(layout, timeline, 4450).svg == svgs[3]


def test_isolate_can_focus_a_revealed_object_not_visible_at_project_start():
    layout, timeline = isolate_documents()
    timeline["actions"][2]["action"]["target_ids"] = ["object-label"]
    at_ms = 4450
    frame = evaluate_frame(layout, timeline, at_ms)
    assert frame.object("object-label").opacity == 1
    assert frame.object("object-evidence").opacity == pytest.approx(.35)
    assert frame.object("object-system").opacity == pytest.approx(.35)


def test_isolate_accepts_prior_visible_fade_and_preserves_focus_opacity():
    layout, timeline = isolate_documents()
    prior = timeline["actions"][0]["action"]
    prior.pop("annotation")
    prior.update(
        verb="fade", target_ids=["object-evidence"],
        expected_state="visible", post_state="visible",
        destination=None, opacity=.5,
    )
    middle = evaluate_frame(layout, timeline, 4450)
    assert middle.object("object-evidence").opacity == .5
    assert middle.object("object-label").opacity == pytest.approx(.35)
    complete = evaluate_frame(layout, timeline, 4900)
    assert complete.object("object-evidence").opacity == .5
    assert complete.object("object-label").opacity == 1


def test_isolate_rejects_hidden_focus_made_opaque_by_fade_without_reveal():
    layout, timeline = isolate_documents()
    layout["objects"][2].update(visible=False, initial_state="hidden")
    timeline["initial_object_states"][2].update(visible=False, state="hidden")
    timeline["layout_sha256"] = digest(layout)
    prior = timeline["actions"][0]["action"]
    prior.pop("annotation")
    prior.update(
        verb="fade", target_ids=["object-evidence"],
        expected_state="hidden", post_state="visible",
        destination=None, opacity=.5,
    )
    with pytest.raises(V2FrameError, match="visible focus content"):
        evaluate_frame(layout, timeline, 0)


def test_multiple_focus_objects_leave_only_secondary_context_dimmed():
    layout, timeline = isolate_documents()
    layout["objects"][1]["opacity"] = .8
    timeline["actions"][2]["action"]["target_ids"] = ["object-evidence", "object-system"]
    timeline["layout_sha256"] = digest(layout)
    middle = evaluate_frame(layout, timeline, 4450)
    assert middle.object("object-evidence").opacity == 1
    assert middle.object("object-system").opacity == 1
    assert middle.object("object-label").opacity == pytest.approx(.8 * .35)
    complete = evaluate_frame(layout, timeline, 4900)
    assert complete.object("object-label").opacity == .8


def test_isolate_can_focus_a_pinned_registry_illustration():
    layout, timeline = illustration_documents()
    layout["objects"][2].update(visible=True, initial_state="visible")
    timeline["initial_object_states"][2].update(visible=True, state="visible")
    timeline["actions"][2]["action"].update(
        verb="isolate", expected_state="visible", post_state="visible",
    )
    timeline["layout_sha256"] = digest(layout)
    frame = evaluate_frame(layout, timeline, 4450)
    assert frame.object("object-evidence").opacity == 1
    assert frame.object("object-label").opacity < 1
    assert compose_png_frame(layout, timeline, 4450).png


def test_isolate_rejects_unsupported_evidence_focus_before_sampling():
    layout, timeline = supported_documents()
    layout["objects"][2].update(visible=True, initial_state="visible")
    timeline["initial_object_states"][2].update(visible=True, state="visible")
    timeline["actions"][2]["action"].update(
        verb="isolate", expected_state="visible", post_state="visible",
    )
    timeline["layout_sha256"] = digest(layout)
    with pytest.raises(V2FrameError, match="supported focus object"):
        evaluate_frame(layout, timeline, 0)


def test_isolate_requires_visible_non_focus_context():
    layout, timeline = isolate_documents()
    timeline["actions"][2]["action"]["target_ids"] = [
        "object-evidence", "object-system", "object-label",
    ]
    with pytest.raises(V2FrameError, match="visible secondary context"):
        evaluate_frame(layout, timeline, 0)
    layout, timeline = isolate_documents()
    for index in (0, 1):
        prior = timeline["actions"][index]["action"]
        prior.pop("annotation")
        prior.update(verb="fade", destination=None, opacity=0)
    with pytest.raises(V2FrameError, match="visible secondary context"):
        evaluate_frame(layout, timeline, 0)


@pytest.mark.parametrize("change", [
    {"expected_state": None},
    {"post_state": "isolated"},
    {"post_state": "removed"},
])
def test_isolate_requires_canonical_transient_state(change):
    layout, timeline = isolate_documents()
    timeline["actions"][2]["action"].update(change)
    with pytest.raises(V2FrameError, match="canonical visible-to-visible states"):
        evaluate_frame(layout, timeline, 0)


def test_isolate_rejects_hidden_or_zero_opacity_focus():
    layout, timeline = isolate_documents()
    layout["objects"][2]["visible"] = False
    timeline["initial_object_states"][2]["visible"] = False
    timeline["layout_sha256"] = digest(layout)
    with pytest.raises(V2FrameError, match="visible focus content"):
        evaluate_frame(layout, timeline, 0)
    layout, timeline = isolate_documents()
    layout["objects"][2]["opacity"] = 0
    timeline["layout_sha256"] = digest(layout)
    with pytest.raises(V2FrameError, match="visible focus content"):
        evaluate_frame(layout, timeline, 0)


def test_isolate_rejects_step_duplicate_and_outside_board():
    layout, timeline = isolate_documents()
    timeline["actions"][2]["action"]["easing"] = "step"
    with pytest.raises(V2FrameError, match="cannot use step easing"):
        evaluate_frame(layout, timeline, 0)
    layout, timeline = isolate_documents()
    timeline["actions"][2]["action"]["target_ids"] = ["object-evidence", "object-evidence"]
    with pytest.raises(V2FrameError, match="duplicate focus targets"):
        evaluate_frame(layout, timeline, 0)
    layout, timeline = isolate_documents()
    layout["activations"][0]["end_ms"] = 4000
    timeline["layout_sha256"] = digest(layout)
    with pytest.raises(V2FrameError, match="needs an active board"):
        evaluate_frame(layout, timeline, 0)


def test_isolate_rejects_any_overlapping_same_board_visual_action():
    layout, timeline = isolate_documents()
    timeline["actions"][1]["end_ms"] = 4500
    with pytest.raises(V2FrameError, match="overlaps another visual action"):
        evaluate_frame(layout, timeline, 0)
    layout, timeline = isolate_documents()
    later = deepcopy(timeline["actions"][2])
    later["action"].update(action_id="action-4", verb="reveal", target_ids=["object-label"])
    later["start_ms"] = 4500
    later["end_ms"] = 5400
    later["resolved_trigger"]["alignment_anchor_ms"] = 4500
    later["resolved_trigger"]["resolved_at_ms"] = 4500
    timeline["actions"].append(later)
    timeline["coverage"][2]["action_ids"] = ["action-3", "action-4"]
    with pytest.raises(V2FrameError, match="overlaps another visual action"):
        evaluate_frame(layout, timeline, 0)


def test_repeated_isolations_do_not_compound_or_leave_context_dimmed():
    layout, timeline = isolate_documents()
    later = deepcopy(timeline["actions"][2])
    later["action"]["action_id"] = "action-4"
    later["start_ms"] = 6000
    later["end_ms"] = 6900
    later["resolved_trigger"]["alignment_anchor_ms"] = 6000
    later["resolved_trigger"]["resolved_at_ms"] = 6000
    timeline["actions"].append(later)
    timeline["coverage"][2]["action_ids"] = ["action-3", "action-4"]
    assert evaluate_frame(layout, timeline, 5500).object("object-label").opacity == 1
    assert evaluate_frame(layout, timeline, 6450).object("object-label").opacity == pytest.approx(.35)
    assert evaluate_frame(layout, timeline, 6900).object("object-label").opacity == 1
