"""Bounded cross-out is a persistent, non-destructive two-stroke correction cue."""

from __future__ import annotations

import io
import xml.etree.ElementTree as ET
from copy import deepcopy
from itertools import pairwise

import pytest
from atme.render.v2_state import V2FrameError, evaluate_frame
from atme.render.v2_svg import compose_png_frame, compose_svg_frame
from PIL import Image, ImageChops
from test_v2_frame_state import supported_documents
from test_v2_highlight_action import highlight_documents
from v2_fixtures import digest


def cross_out_documents(kind="ellipse"):
    layout, timeline = highlight_documents(kind)
    timeline["actions"][2]["action"].update(
        verb="cross_out", expected_state="visible", post_state="crossed_out",
    )
    return layout, timeline


def _strokes(svg):
    return [node for node in ET.fromstring(svg).iter()
            if node.attrib.get("data-attention-action") == "cross_out"]


@pytest.mark.parametrize("kind", ["ellipse", "text"])
def test_cross_out_draws_two_distinct_strokes_over_unchanged_content(kind):
    layout, timeline = cross_out_documents(kind)
    times = (3999, 4225, 4450, 4675, 4900)
    states = [evaluate_frame(layout, timeline, at_ms).object("object-evidence")
              for at_ms in times]
    assert [state.cross_out_fraction for state in states] == pytest.approx([0, .25, .5, .75, 1])
    assert all(state.visible and state.reveal_fraction == 1 for state in states)
    assert states[0].state == states[1].state == states[3].state == "visible"
    assert states[-1].state == "crossed_out"
    assert all(state.transform == states[0].transform for state in states)
    svg = [compose_svg_frame(layout, timeline, at_ms).svg for at_ms in times]
    assert [len(_strokes(item)) for item in svg] == [0, 1, 1, 2, 2]
    assert _strokes(svg[1])[0].attrib["data-stroke"] == "1"
    assert "stroke-dasharray" in _strokes(svg[1])[0].attrib
    assert "stroke-dasharray" not in _strokes(svg[2])[0].attrib
    assert _strokes(svg[3])[1].attrib["data-stroke"] == "2"
    assert "stroke-dasharray" in _strokes(svg[3])[1].attrib
    assert all("stroke-dasharray" not in node.attrib for node in _strokes(svg[-1]))
    assert all(node.attrib["stroke"] == "#B93838" for node in _strokes(svg[-1]))
    assert 'clip-path="url(#' not in svg[1]
    assert ("THE MECHANISM" if kind == "text" else "<ellipse") in svg[3]
    images = [Image.open(io.BytesIO(compose_png_frame(layout, timeline, at_ms).png)).convert("RGB")
              for at_ms in times]
    assert all(ImageChops.difference(left, right).getbbox()
               for left, right in pairwise(images))
    assert compose_svg_frame(layout, timeline, 4675).svg == svg[3]
    assert evaluate_frame(layout, timeline, 4225).object("object-evidence") == states[1]


@pytest.mark.parametrize("change", [
    {"expected_state": None},
    {"post_state": "visible"},
    {"post_state": "removed"},
])
def test_cross_out_requires_canonical_state(change):
    layout, timeline = cross_out_documents()
    timeline["actions"][2]["action"].update(change)
    with pytest.raises(V2FrameError, match="canonical visible-to-crossed_out states"):
        evaluate_frame(layout, timeline, 0)


def test_cross_out_rejects_hidden_or_zero_opacity_target():
    layout, timeline = cross_out_documents()
    layout["objects"][2].update(visible=False, initial_state="hidden")
    timeline["initial_object_states"][2].update(visible=False, state="hidden")
    timeline["actions"][2]["action"]["expected_state"] = "hidden"
    timeline["layout_sha256"] = digest(layout)
    with pytest.raises(V2FrameError, match="untouched visible target"):
        evaluate_frame(layout, timeline, 0)
    layout, timeline = cross_out_documents()
    layout["objects"][2]["opacity"] = 0
    timeline["layout_sha256"] = digest(layout)
    with pytest.raises(V2FrameError, match="untouched visible target"):
        evaluate_frame(layout, timeline, 0)


def test_cross_out_rejects_unsupported_visual_target():
    layout, timeline = supported_documents()
    layout["objects"][2].update(visible=True, initial_state="visible")
    timeline["initial_object_states"][2].update(visible=True, state="visible")
    timeline["actions"][2]["action"].update(
        verb="cross_out", expected_state="visible", post_state="crossed_out",
    )
    timeline["layout_sha256"] = digest(layout)
    with pytest.raises(V2FrameError, match="supported mark or text target"):
        evaluate_frame(layout, timeline, 0)


def test_cross_out_rejects_prior_action_on_target():
    layout, timeline = cross_out_documents()
    prior = timeline["actions"][0]["action"]
    prior.pop("annotation")
    prior.update(
        verb="move", target_ids=["object-evidence"],
        expected_state="visible", post_state="visible",
        destination=layout["objects"][2]["transform"], opacity=None,
    )
    with pytest.raises(V2FrameError, match="untouched visible target"):
        evaluate_frame(layout, timeline, 0)


def test_cross_out_must_be_inside_active_board_window():
    layout, timeline = cross_out_documents()
    layout["activations"][0]["end_ms"] = 4000
    timeline["layout_sha256"] = digest(layout)
    with pytest.raises(V2FrameError, match="needs an active board"):
        evaluate_frame(layout, timeline, 0)


def test_crossed_out_target_cannot_be_mutated_later():
    layout, timeline = cross_out_documents()
    later = deepcopy(timeline["actions"][2])
    later["action"].update(
        action_id="action-4", verb="reveal",
        expected_state="crossed_out", post_state="visible",
    )
    later["start_ms"] = 6000
    later["end_ms"] = 6900
    later["resolved_trigger"]["alignment_anchor_ms"] = 6000
    later["resolved_trigger"]["resolved_at_ms"] = 6000
    timeline["actions"].append(later)
    timeline["coverage"][2]["action_ids"] = ["action-3", "action-4"]
    with pytest.raises(V2FrameError, match="crossed-out target.*cannot receive another action"):
        evaluate_frame(layout, timeline, 0)
