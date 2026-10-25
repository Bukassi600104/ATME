"""Canonical connect/disconnect changes only the bound relationship."""

from __future__ import annotations

from copy import deepcopy

import pytest
from atme.render.v2_state import V2FrameError, evaluate_frame
from atme.render.v2_svg import compose_png_frame, compose_svg_frame
from test_v2_connector_svg import connector_documents
from v2_fixtures import common_action, digest


def relationship_documents():
    layout, timeline = connector_documents()
    arrow = layout["objects"][3]
    arrow["initial_state"] = "disconnected"
    timeline["initial_object_states"][3]["state"] = "disconnected"
    first = timeline["actions"][2]
    first["action"].pop("target_ids")
    first["action"].pop("annotation")
    first["action"].update(
        verb="connect", connector_id="object-arrow",
        source_object_id="object-system", source_anchor_id="center",
        destination_object_id="object-label", destination_anchor_id="center",
        expected_state="disconnected", post_state="connected",
    )
    second = deepcopy(first)
    second["action"] = {
        **common_action("action-4", "instruction-3"),
        "verb": "disconnect", "connector_id": "object-arrow",
        "source_object_id": "object-system", "source_anchor_id": "center",
        "destination_object_id": "object-label", "destination_anchor_id": "center",
        "expected_state": "connected", "post_state": "disconnected",
        "fallback": {"fallback_id": "fallback-3", "on_failure": "block"},
        "coverage_id": "coverage-3",
    }
    second["start_ms"] = 6000
    second["end_ms"] = 6900
    second["resolved_trigger"]["alignment_anchor_ms"] = 6000
    second["resolved_trigger"]["resolved_at_ms"] = 6000
    timeline["actions"].append(second)
    timeline["coverage"][2]["action_ids"] = ["action-3", "action-4"]
    timeline["layout_sha256"] = digest(layout)
    return layout, timeline


def test_connect_and_disconnect_are_random_access_inverse_relationships():
    layout, timeline = relationship_documents()
    before = evaluate_frame(layout, timeline, 3999)
    connecting = evaluate_frame(layout, timeline, 4450)
    connected = evaluate_frame(layout, timeline, 4900)
    disconnecting = evaluate_frame(layout, timeline, 6450)
    after = evaluate_frame(layout, timeline, 6900)
    assert before.object("object-arrow").state == "disconnected"
    assert not before.object("object-arrow").visible
    assert 0 < connecting.object("object-arrow").reveal_fraction < 1
    assert connected.object("object-arrow").state == "connected"
    assert connected.object("object-arrow").visible
    assert connected.object("object-arrow").reveal_fraction == 1
    assert 0 < disconnecting.object("object-arrow").reveal_fraction < 1
    assert after.object("object-arrow").state == "disconnected"
    assert not after.object("object-arrow").visible
    assert after.object("object-arrow").reveal_fraction == 0
    assert all(snapshot.object("object-label").state == "visible"
               for snapshot in (connecting, connected, disconnecting, after))
    assert evaluate_frame(layout, timeline, 4450) == connecting


def test_connect_and_disconnect_render_shaft_without_generic_wipe():
    layout, timeline = relationship_documents()
    during_connect = compose_svg_frame(layout, timeline, 4450).svg
    connected = compose_svg_frame(layout, timeline, 4900).svg
    during_disconnect = compose_svg_frame(layout, timeline, 6450).svg
    disconnected = compose_svg_frame(layout, timeline, 6900).svg
    for partial in (during_connect, during_disconnect):
        assert 'data-object-id="object-arrow"' in partial
        assert "stroke-dasharray=" in partial
        assert "<polygon points=" not in partial
        assert 'clip-path="url(#' not in partial
    assert "<polygon points=" in connected
    assert 'data-object-id="object-arrow"' not in disconnected
    png = compose_png_frame(layout, timeline, 4450).png
    compose_png_frame(layout, timeline, 6900)
    assert compose_png_frame(layout, timeline, 4450).png == png


@pytest.mark.parametrize("change,match", [
    ({"source_anchor_id": "other"}, "disagrees with the authored connector"),
    ({"destination_object_id": "object-evidence"}, "disagrees with the authored connector"),
    ({"post_state": "visible"}, "canonical relationship states"),
])
def test_connection_cannot_rebind_or_change_noncanonical_state(change, match):
    layout, timeline = relationship_documents()
    timeline["actions"][2]["action"].update(change)
    if "post_state" in change:
        timeline["actions"][3]["action"]["expected_state"] = change["post_state"]
    with pytest.raises(V2FrameError, match=match):
        evaluate_frame(layout, timeline, 4450)


def test_connection_windows_cannot_overlap_other_connector_actions():
    layout, timeline = relationship_documents()
    timeline["actions"][3]["start_ms"] = 4500
    timeline["actions"][3]["resolved_trigger"]["alignment_anchor_ms"] = 4500
    timeline["actions"][3]["resolved_trigger"]["resolved_at_ms"] = 4500
    with pytest.raises(V2FrameError, match="overlapping actions"):
        evaluate_frame(layout, timeline, 4450)


@pytest.mark.parametrize("state,visible", [
    ("disconnected", True), ("connected", False),
])
def test_managed_relationship_initial_state_matches_visibility(state, visible):
    layout, timeline = relationship_documents()
    arrow = layout["objects"][3]
    arrow["initial_state"] = state
    arrow["visible"] = visible
    timeline["initial_object_states"][3].update(state=state, visible=visible)
    if state == "connected":
        timeline["actions"][2]["action"].update(
            verb="disconnect", expected_state="connected", post_state="disconnected",
        )
        timeline["actions"][3]["action"].update(
            verb="connect", expected_state="disconnected", post_state="connected",
        )
    timeline["layout_sha256"] = digest(layout)
    with pytest.raises(V2FrameError, match="inconsistent initial relationship visibility"):
        evaluate_frame(layout, timeline, 3999)


@pytest.mark.parametrize("verb", ["move", "draw"])
def test_other_actions_cannot_mutate_connection_managed_arrow(verb):
    layout, timeline = relationship_documents()
    action = timeline["actions"][3]["action"]
    for key in ("connector_id", "source_object_id", "source_anchor_id",
                "destination_object_id", "destination_anchor_id"):
        action.pop(key)
    action.update(verb=verb, target_ids=["object-arrow"],
                  expected_state="connected", post_state="connected")
    if verb == "move":
        destination = deepcopy(layout["objects"][3]["transform"])
        destination["position"] = {"x": 10, "y": 0}
        action.update(destination=destination, opacity=None)
    else:
        action["annotation"] = None
    with pytest.raises(V2FrameError, match="connection-managed connector"):
        evaluate_frame(layout, timeline, 6450)


@pytest.mark.parametrize("case,match", [
    ("self_loop", "loop back"),
    ("self_endpoint", "anchor to itself"),
    ("ignored_style", "ignored geometry or styling"),
])
def test_frame_evaluator_rejects_unsupported_connector_forms(case, match):
    layout, timeline = relationship_documents()
    arrow = layout["objects"][3]
    if case == "self_loop":
        arrow.update(source_object_id="object-label", allow_self_loop=True)
        for resolved in timeline["actions"][2:]:
            resolved["action"]["source_object_id"] = "object-label"
    elif case == "self_endpoint":
        arrow["source_object_id"] = "object-arrow"
        arrow["anchors"] = [{"anchor_id": "center", "point": {"x": 0.5, "y": 0.5}}]
        for resolved in timeline["actions"][2:]:
            resolved["action"]["source_object_id"] = "object-arrow"
    else:
        arrow["style"]["fill"] = "ink.accent"
    timeline["layout_sha256"] = digest(layout)
    with pytest.raises(V2FrameError, match=match):
        evaluate_frame(layout, timeline, 4450)
