"""Policy-bearing Group frames enter the same proven clock and native painter."""

import socket
from copy import deepcopy
from pathlib import Path

import pytest
from atme.render import v2_state, v2_svg
from atme.render.v2_hierarchy import HierarchySnapshot
from atme.render.v2_split_paint import verify_split_paint_inputs
from test_v2_group_annotation import (
    annotation_group_documents,
    consumer_clock,
    private_svg,
    regroup_first_documents,
)
from v2_fixtures import digest


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("regroup", [False, True])
def test_public_group_and_ungroup_share_exact_frames_pixels_boundaries_and_frozen_seek(portrait, regroup, monkeypatch):
    builder = regroup_first_documents if regroup else annotation_group_documents
    layout, timeline = builder(portrait=portrait)
    # This geometry-only fixture inherits an unused resolved-asset placeholder.
    # Freeze an exact empty inventory; do not fabricate trusted asset metadata.
    assert all(obj.get("asset_id") is None for obj in layout["objects"])
    timeline["resolved_assets"] = []
    original = deepcopy((layout, timeline))
    context, private_replay, private_camera = consumer_clock(layout, timeline)
    # First prove the already accepted paired history; public admission must
    # not substitute another state, hierarchy, camera, or paint implementation.
    expected = v2_state._sample_validated_frame(
        context.layout, context.timeline, private_replay, private_camera, 6750)
    assert v2_state.evaluate_frame(layout, timeline, 6750) == expected

    def no_network(*args, **kwargs):
        raise AssertionError("public Group frames must remain offline")

    monkeypatch.setattr(socket, "create_connection", no_network)
    monkeypatch.setattr(socket.socket, "connect", no_network)
    times = (9000, 5999, 6000, 6750, 7999, 6000)
    expected_pixels = {}
    for at in times:
        actual = v2_state.evaluate_frame(layout, timeline, at)
        assert actual == v2_state._sample_validated_frame(
            context.layout, context.timeline, private_replay, private_camera, at)
        expected_svg = private_svg(context, private_replay, private_camera, at)
        assert v2_svg.compose_svg_frame(layout, timeline, at) == expected_svg
        expected_pixels[at] = v2_svg._rasterize_svg_frame(context.layout, expected_svg).png
        assert v2_svg.compose_png_frame(layout, timeline, at).png == expected_pixels[at]
    assert expected_pixels[5999] == expected_pixels[6000]
    assert expected_pixels[6750] != expected_pixels[7999] == expected_pixels[9000]

    # Freeze AFTER the actual public admission/history proof. Cold validation
    # may verify local bundles; subsequent sampling/paint may not reopen them.
    inputs = verify_split_paint_inputs(context.layout, {})
    replay, camera = v2_state._validate_pair(
        context.layout, context.timeline, digest(layout),
        HierarchySnapshot.from_objects(context.objects))
    held = {item.action.action_id: v2_state._sample_validated_frame(
        context.layout, context.timeline, replay, camera, item.end_ms)
        for item in context.timeline.actions
        if getattr(item.action, "annotation_policy", None) is not None
        and item.action.annotation_policy.leader_connector_id is not None}
    original_open = Path.open

    def write_only(path, mode="r", *args, **kwargs):
        if "r" in mode or "+" in mode or not any(flag in mode for flag in ("w", "a", "x")):
            raise AssertionError("frozen public Group paint reopened an original file")
        return original_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", write_only)
    monkeypatch.setattr(Path, "read_bytes", lambda *a, **kw: pytest.fail("frozen Group source read"))
    for at in (7999, 6000, 9000, 5999, 6750, 6000):
        sample = v2_state._sample_validated_frame(context.layout, context.timeline, replay, camera, at)
        svg = v2_svg._compose_validated_svg_frame(
            context.layout, context.timeline, sample, held, split_inputs=inputs)
        assert v2_svg._rasterize_svg_frame(context.layout, svg, split_inputs=inputs).png == expected_pixels[at]
    assert (layout, timeline) == original
