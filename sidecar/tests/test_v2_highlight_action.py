"""A bounded highlight action accents a visible object without hiding its content."""

from __future__ import annotations

import io
import xml.etree.ElementTree as ET
from copy import deepcopy

import pytest
from atme.render.v2_state import V2FrameError, evaluate_frame
from atme.render.v2_svg import compose_png_frame, compose_svg_frame
from PIL import Image, ImageChops
from test_v2_connector_svg import connector_documents
from test_v2_frame_state import supported_documents
from test_v2_svg import primitive_documents
from v2_fixtures import digest


def highlight_documents(kind="ellipse"):
    layout, timeline = primitive_documents()
    target = layout["objects"][2]
    if kind == "text":
        target.pop("path_data")
        target.update(
            object_type="text", text="THE MECHANISM", items=[],
            style={"stroke": None, "fill": None, "text": "text.body", "effect": None},
        )
    target["visible"] = True
    target["initial_state"] = "visible"
    timeline["initial_object_states"][2].update(state="visible", visible=True)
    timeline["actions"][2]["action"].update(
        verb="highlight", easing="linear",
        expected_state="visible", post_state="highlighted",
    )
    timeline["layout_sha256"] = digest(layout)
    return layout, timeline


@pytest.mark.parametrize("kind", ["ellipse", "text"])
def test_highlight_draws_over_the_unchanged_target_and_persists(kind):
    layout, timeline = highlight_documents(kind)
    before = evaluate_frame(layout, timeline, 3999).object("object-evidence")
    start = evaluate_frame(layout, timeline, 4000).object("object-evidence")
    middle = evaluate_frame(layout, timeline, 4450).object("object-evidence")
    after = evaluate_frame(layout, timeline, 4900).object("object-evidence")
    assert before.state == "visible" and before.visible and before.emphasis_fraction == 0
    assert start.emphasis_fraction == 0
    assert middle.state == "visible" and middle.visible
    assert middle.reveal_fraction == before.reveal_fraction == 1
    assert middle.emphasis_fraction == pytest.approx(0.5)
    assert after.state == "highlighted" and after.visible and after.emphasis_fraction == 1
    before_svg = compose_svg_frame(layout, timeline, 3999).svg
    middle_svg = compose_svg_frame(layout, timeline, 4450).svg
    after_svg = compose_svg_frame(layout, timeline, 4900).svg
    assert 'data-attention-action="highlight"' not in before_svg
    target_group = next(node for node in ET.fromstring(middle_svg).iter()
                        if node.attrib.get("data-object-id") == "object-evidence")
    overlay = next(node for node in target_group
                   if node.attrib.get("data-attention-action") == "highlight")
    assert overlay.attrib["stroke"] == "#B93838"
    assert overlay.attrib["fill"] == "none"
    assert "stroke-dasharray" in overlay.attrib
    assert "stroke-dasharray" not in next(node for node in ET.fromstring(after_svg).iter()
                                           if node.attrib.get("data-attention-action") == "highlight").attrib
    assert 'clip-path="url(#' not in middle_svg
    assert ("THE MECHANISM" if kind == "text" else "<ellipse") in middle_svg
    images = [Image.open(io.BytesIO(compose_png_frame(layout, timeline, at_ms).png)).convert("RGB")
              for at_ms in (3999, 4450, 4900)]
    assert ImageChops.difference(images[0], images[1]).getbbox()
    assert ImageChops.difference(images[1], images[2]).getbbox()
    assert compose_svg_frame(layout, timeline, 4450).svg == middle_svg
    assert evaluate_frame(layout, timeline, 4450) == evaluate_frame(layout, timeline, 4450)


@pytest.mark.parametrize("change", [
    {"expected_state": None},
    {"post_state": "visible"},
    {"post_state": "removed"},
])
def test_highlight_requires_canonical_visible_to_highlighted_state(change):
    layout, timeline = highlight_documents()
    timeline["actions"][2]["action"].update(change)
    with pytest.raises(V2FrameError, match="canonical visible-to-highlighted states"):
        evaluate_frame(layout, timeline, 0)


def test_highlight_rejects_hidden_or_zero_opacity_target():
    layout, timeline = highlight_documents()
    layout["objects"][2].update(visible=False, initial_state="hidden")
    timeline["initial_object_states"][2].update(visible=False, state="hidden")
    timeline["actions"][2]["action"]["expected_state"] = "hidden"
    timeline["layout_sha256"] = digest(layout)
    with pytest.raises(V2FrameError, match="untouched visible target"):
        evaluate_frame(layout, timeline, 0)
    layout, timeline = highlight_documents()
    layout["objects"][2]["opacity"] = 0
    timeline["layout_sha256"] = digest(layout)
    with pytest.raises(V2FrameError, match="untouched visible target"):
        evaluate_frame(layout, timeline, 0)


def test_highlight_rejects_connector_target_even_if_visible():
    layout, timeline = connector_documents()
    arrow = layout["objects"][3]
    arrow.update(visible=True, initial_state="visible")
    timeline["initial_object_states"][3].update(visible=True, state="visible")
    timeline["actions"][2]["action"].update(
        verb="highlight", expected_state="visible", post_state="highlighted",
    )
    timeline["layout_sha256"] = digest(layout)
    with pytest.raises(V2FrameError, match="supported mark or text target"):
        evaluate_frame(layout, timeline, 0)


def test_highlight_rejects_prior_action_on_target():
    layout, timeline = highlight_documents()
    prior = timeline["actions"][0]["action"]
    prior.pop("annotation")
    prior.update(
        verb="move", target_ids=["object-evidence"],
        expected_state="visible", post_state="visible",
        destination=layout["objects"][2]["transform"], opacity=None,
    )
    with pytest.raises(V2FrameError, match="untouched visible target"):
        evaluate_frame(layout, timeline, 0)


def test_highlight_rejects_unsupported_visual_target():
    layout, timeline = supported_documents()
    layout["objects"][2].update(visible=True, initial_state="visible")
    timeline["initial_object_states"][2].update(visible=True, state="visible")
    timeline["actions"][2]["action"].update(
        verb="highlight", expected_state="visible", post_state="highlighted",
    )
    timeline["layout_sha256"] = digest(layout)
    with pytest.raises(V2FrameError, match="supported mark or text target"):
        evaluate_frame(layout, timeline, 0)


def test_highlight_must_be_within_an_active_board_window():
    layout, timeline = highlight_documents()
    layout["activations"][0]["end_ms"] = 4000
    timeline["layout_sha256"] = digest(layout)
    with pytest.raises(V2FrameError, match="needs an active board"):
        evaluate_frame(layout, timeline, 0)


def test_highlight_is_terminal_for_its_target_in_this_bounded_slice():
    layout, timeline = highlight_documents()
    later = deepcopy(timeline["actions"][2])
    later["action"].update(
        action_id="action-4", verb="reveal",
        expected_state="highlighted", post_state="visible",
    )
    later["start_ms"] = 6000
    later["end_ms"] = 6900
    later["resolved_trigger"]["alignment_anchor_ms"] = 6000
    later["resolved_trigger"]["resolved_at_ms"] = 6000
    timeline["actions"].append(later)
    timeline["coverage"][2]["action_ids"] = ["action-3", "action-4"]
    with pytest.raises(V2FrameError, match="highlighted target.*cannot receive another action"):
        evaluate_frame(layout, timeline, 0)
