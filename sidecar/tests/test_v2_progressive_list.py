"""Ordered list disclosure renders complete authored items at exact action boundaries."""

from __future__ import annotations

import io
import xml.etree.ElementTree as ET

import pytest
from atme.render.v2_state import V2FrameError, evaluate_frame
from atme.render.v2_svg import (
    UnsupportedVisualObject,
    compose_png_frame,
    compose_svg_frame,
)
from PIL import Image, ImageChops
from test_v2_svg import primitive_documents
from v2_fixtures import digest


def list_documents():
    layout, timeline = primitive_documents()
    listing = layout["objects"][2]
    listing.pop("path_data")
    listing.update(
        object_type="list", text="The process", items=[
            "Gather evidence", "Explain the change", "Return to the model",
        ],
        style={"stroke": None, "fill": None, "text": "text.body", "effect": None},
    )
    timeline["actions"][2]["action"].update(verb="progressive_reveal", easing="linear")
    timeline["layout_sha256"] = digest(layout)
    return layout, timeline


@pytest.mark.parametrize("time_ms,present,absent", [
    (3999, (), ("The process", "Gather evidence")),
    (4000, (), ("The process", "Gather evidence")),
    (4001, ("The process",), ("Gather evidence",)),
    (4299, ("The process",), ("Gather evidence",)),
    (4300, ("The process", "Gather evidence"), ("Explain the change",)),
    (4599, ("Gather evidence",), ("Explain the change",)),
    (4600, ("Explain the change",), ("Return to the model",)),
    (4899, ("Explain the change",), ("Return to the model",)),
    (4900, ("The process", "Gather evidence", "Explain the change", "Return to the model"), ()),
])
def test_list_reveals_only_complete_ordered_items(time_ms, present, absent):
    layout, timeline = list_documents()
    svg = compose_svg_frame(layout, timeline, time_ms).svg
    ET.fromstring(svg)
    for value in present:
        assert value in svg
    for value in absent:
        assert value not in svg
    assert 'clip-path="url(#' not in svg
    assert compose_svg_frame(layout, timeline, time_ms).svg == svg


def test_progressive_list_raster_and_backward_seek_are_deterministic():
    layout, timeline = list_documents()
    first = compose_png_frame(layout, timeline, 4300).png
    second = compose_png_frame(layout, timeline, 4600).png
    third = compose_png_frame(layout, timeline, 4900).png
    images = [Image.open(io.BytesIO(value)).convert("RGB") for value in (first, second, third)]
    assert ImageChops.difference(images[0], images[1]).getbbox()
    assert ImageChops.difference(images[1], images[2]).getbbox()
    assert compose_png_frame(layout, timeline, 4300).png == first
    assert evaluate_frame(layout, timeline, 4300) == evaluate_frame(layout, timeline, 4300)


@pytest.mark.parametrize("change,match", [
    ({"object_type": "text"}, "ordered-child list"),
    ({"items": []}, "ordered-child list"),
    ({"visible": True, "initial_state": "visible"}, "previously untouched hidden list"),
])
def test_noncanonical_progressive_target_fails_before_action_start(change, match):
    layout, timeline = list_documents()
    layout["objects"][2].update(change)
    if "visible" in change:
        timeline["initial_object_states"][2].update(visible=True, state="visible")
        timeline["actions"][2]["action"]["expected_state"] = "visible"
    timeline["layout_sha256"] = digest(layout)
    with pytest.raises(V2FrameError, match=match):
        evaluate_frame(layout, timeline, 0)


def test_progressive_list_cannot_restart_after_an_earlier_action():
    layout, timeline = list_documents()
    prior = timeline["actions"][0]["action"]
    prior.pop("annotation")
    prior.update(
        verb="move", target_ids=["object-evidence"],
        expected_state="hidden", post_state="hidden",
        destination=layout["objects"][2]["transform"], opacity=None,
    )
    with pytest.raises(V2FrameError, match="previously untouched hidden list"):
        evaluate_frame(layout, timeline, 0)


@pytest.mark.parametrize("change", [
    {"expected_state": None},
    {"post_state": "hidden"},
    {"post_state": "removed"},
])
def test_progressive_list_requires_canonical_hidden_to_visible_states(change):
    layout, timeline = list_documents()
    timeline["actions"][2]["action"].update(change)
    with pytest.raises(V2FrameError, match="canonical hidden-to-visible list states"):
        evaluate_frame(layout, timeline, 4900)


@pytest.mark.parametrize("text,items", [
    ("Two\nheadings", ["One", "Two"]),
    ("Heading", ["One\ncontinued", "Two"]),
    ("Heading", ["One\u2028continued", "Two"]),
    ("Heading", ["", "Two"]),
    ("Heading", ["   ", "Two"]),
    ("\t", ["One", "Two"]),
])
def test_malformed_items_fail_state_and_svg_even_when_hidden(text, items):
    layout, timeline = list_documents()
    layout["objects"][2].update(text=text, items=items)
    timeline["layout_sha256"] = digest(layout)
    with pytest.raises(V2FrameError, match="nonblank, one-line heading and items"):
        evaluate_frame(layout, timeline, 0)
    with pytest.raises(V2FrameError, match="nonblank, one-line heading and items"):
        compose_svg_frame(layout, timeline, 0)
    timeline["actions"][2]["action"]["verb"] = "reveal"
    with pytest.raises(UnsupportedVisualObject, match="nonblank, one-line heading and items"):
        compose_svg_frame(layout, timeline, 0)


def test_full_list_must_fit_even_before_progression_begins():
    layout, timeline = list_documents()
    layout["objects"][2]["items"][2] = "A very long item that does not fit its authored text bounds"
    timeline["layout_sha256"] = digest(layout)
    with pytest.raises(UnsupportedVisualObject, match="authored line breaks|authored width"):
        compose_svg_frame(layout, timeline, 0)
