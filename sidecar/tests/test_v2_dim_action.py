"""A bounded dim cue temporarily subdues visible context without editing its opacity."""

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
from v2_fixtures import digest


def dim_documents(kind="ellipse"):
    layout, timeline = highlight_documents(kind)
    timeline["actions"][2]["action"].update(
        verb="dim", easing="linear", expected_state="visible", post_state="visible",
    )
    return layout, timeline


def _target_opacity(svg):
    return float(next(node for node in ET.fromstring(svg).iter()
                      if node.attrib.get("data-object-id") == "object-evidence").attrib["opacity"])


@pytest.mark.parametrize("kind", ["ellipse", "text"])
def test_dim_fades_context_then_restores_exact_authored_opacity(kind):
    layout, timeline = dim_documents(kind)
    layout["objects"][2]["opacity"] = .8
    timeline["layout_sha256"] = digest(layout)
    times = (3999, 4000, 4090, 4450, 4810, 4900, 6000)
    states = [evaluate_frame(layout, timeline, at_ms).object("object-evidence")
              for at_ms in times]
    authored = layout["objects"][2]["opacity"]
    assert [state.opacity for state in states] == pytest.approx(
        [authored, authored, authored * .675, authored * .35,
         authored * .675, authored, authored]
    )
    assert all(state.state == "visible" and state.visible and state.reveal_fraction == 1
               for state in states)
    assert all(state.transform == states[0].transform for state in states)
    svg = [compose_svg_frame(layout, timeline, at_ms).svg for at_ms in times]
    assert [_target_opacity(item) for item in svg] == pytest.approx(
        [authored, authored, authored * .675, authored * .35,
         authored * .675, authored, authored], abs=1e-4
    )
    assert 'clip-path="url(#' not in svg[3]
    assert ("THE MECHANISM" if kind == "text" else "<ellipse") in svg[3]
    before = Image.open(io.BytesIO(compose_png_frame(layout, timeline, 3999).png)).convert("RGB")
    mid = Image.open(io.BytesIO(compose_png_frame(layout, timeline, 4450).png)).convert("RGB")
    after = Image.open(io.BytesIO(compose_png_frame(layout, timeline, 4900).png)).convert("RGB")
    assert ImageChops.difference(before, mid).getbbox()
    assert ImageChops.difference(before, after).getbbox() is None
    assert evaluate_frame(layout, timeline, 4450).object("object-evidence") == states[3]
    assert compose_svg_frame(layout, timeline, 4450).svg == svg[3]


@pytest.mark.parametrize("change", [
    {"expected_state": None},
    {"post_state": "dimmed"},
    {"post_state": "removed"},
])
def test_dim_requires_canonical_transient_state(change):
    layout, timeline = dim_documents()
    timeline["actions"][2]["action"].update(change)
    with pytest.raises(V2FrameError, match="canonical visible-to-visible states"):
        evaluate_frame(layout, timeline, 0)


def test_dim_rejects_hidden_or_zero_opacity_context():
    layout, timeline = dim_documents()
    layout["objects"][2].update(visible=False, initial_state="hidden")
    timeline["initial_object_states"][2].update(visible=False, state="hidden")
    timeline["actions"][2]["action"]["expected_state"] = "hidden"
    timeline["layout_sha256"] = digest(layout)
    with pytest.raises(V2FrameError, match="visible context without prior edits"):
        evaluate_frame(layout, timeline, 0)
    layout, timeline = dim_documents()
    layout["objects"][2]["opacity"] = 0
    timeline["layout_sha256"] = digest(layout)
    with pytest.raises(V2FrameError, match="visible context without prior edits"):
        evaluate_frame(layout, timeline, 0)


def test_dim_rejects_unsupported_visual_target():
    layout, timeline = supported_documents()
    layout["objects"][2].update(visible=True, initial_state="visible")
    timeline["initial_object_states"][2].update(visible=True, state="visible")
    timeline["actions"][2]["action"].update(
        verb="dim", expected_state="visible", post_state="visible",
    )
    timeline["layout_sha256"] = digest(layout)
    with pytest.raises(V2FrameError, match="supported mark or text target"):
        evaluate_frame(layout, timeline, 0)


def test_dim_rejects_prior_edits_and_step_easing():
    layout, timeline = dim_documents()
    prior = timeline["actions"][0]["action"]
    prior.pop("annotation")
    prior.update(
        verb="move", target_ids=["object-evidence"],
        expected_state="visible", post_state="visible",
        destination=layout["objects"][2]["transform"], opacity=None,
    )
    with pytest.raises(V2FrameError, match="visible context without prior edits"):
        evaluate_frame(layout, timeline, 0)
    layout, timeline = dim_documents()
    timeline["actions"][2]["action"]["easing"] = "step"
    with pytest.raises(V2FrameError, match="cannot use step easing"):
        evaluate_frame(layout, timeline, 0)


def test_dim_requires_one_active_board_window_and_unique_targets():
    layout, timeline = dim_documents()
    layout["activations"][0]["end_ms"] = 4000
    timeline["layout_sha256"] = digest(layout)
    with pytest.raises(V2FrameError, match="needs an active board"):
        evaluate_frame(layout, timeline, 0)
    layout, timeline = dim_documents()
    timeline["actions"][2]["action"]["target_ids"] = ["object-evidence", "object-evidence"]
    with pytest.raises(V2FrameError, match="duplicate targets"):
        evaluate_frame(layout, timeline, 0)


def test_non_overlapping_repeated_dim_cues_restore_between_windows():
    layout, timeline = dim_documents()
    later = deepcopy(timeline["actions"][2])
    later["action"].update(action_id="action-4")
    later["start_ms"] = 6000
    later["end_ms"] = 6900
    later["resolved_trigger"]["alignment_anchor_ms"] = 6000
    later["resolved_trigger"]["resolved_at_ms"] = 6000
    timeline["actions"].append(later)
    timeline["coverage"][2]["action_ids"] = ["action-3", "action-4"]
    assert evaluate_frame(layout, timeline, 5500).object("object-evidence").opacity == 1
    assert evaluate_frame(layout, timeline, 6450).object("object-evidence").opacity == pytest.approx(.35)
    assert evaluate_frame(layout, timeline, 6900).object("object-evidence").opacity == 1


def test_one_dim_action_can_subdue_multiple_context_objects_without_compounding():
    layout, timeline = dim_documents()
    second = deepcopy(layout["objects"][2])
    second["object_id"] = "object-secondary"
    second["z_index"] = second["z_index"] + 1
    layout["objects"].append(second)
    layout["boards"][0]["object_ids"].append("object-secondary")
    secondary_state = deepcopy(timeline["initial_object_states"][2])
    secondary_state["object_id"] = "object-secondary"
    timeline["initial_object_states"].append(secondary_state)
    timeline["actions"][2]["action"]["target_ids"].append("object-secondary")
    timeline["layout_sha256"] = digest(layout)
    middle = evaluate_frame(layout, timeline, 4450)
    assert middle.object("object-evidence").opacity == pytest.approx(.35)
    assert middle.object("object-secondary").opacity == pytest.approx(.35)
    complete = evaluate_frame(layout, timeline, 4900)
    assert complete.object("object-evidence").opacity == 1
    assert complete.object("object-secondary").opacity == 1
