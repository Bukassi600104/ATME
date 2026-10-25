"""Bound artwork uses the actual normal/frozen sampled tree, not local trust."""

from copy import deepcopy
from pathlib import Path

import pytest
from atme.render.v2_split_paint import verify_split_paint_inputs
from atme.render.v2_state import evaluate_frame
from atme.render.v2_svg import (
    _compose_validated_svg_frame,
    _rasterize_svg_frame,
    compose_png_frame,
    compose_svg_frame,
)
from atme.store.contracts_v2 import ExecutableLayoutV2, ResolvedVisualTimelineV2
from test_v2_connector_svg import connector_documents
from test_v2_group_hierarchy import grouped_documents
from test_v2_mask_contract import MASK_FIELDS
from test_v2_registry_binding import registry_object
from test_v2_registry_illustrations import illustration_documents
from v2_fixtures import digest


def bound_art_documents(portrait=False, aperture=None):
    layout, timeline = illustration_documents("person-collaborators", "character")
    layout["objects"][2] = registry_object()
    # The inherited kernel fixture lists a no-longer-used evidence asset.
    # Frozen inputs require the actual (empty) project-asset inventory.
    timeline["resolved_assets"] = []
    if portrait:
        layout["output_profile"] = {"profile_id": "SHORT_FORM_9_16", "width": 720, "height": 1280, "fps": 30}
        layout["canvas"] = {"x": 0, "y": 0, "width": 720, "height": 1280}
        timeline["output_profile"] = deepcopy(layout["output_profile"])
    if aperture:
        parent = deepcopy(grouped_documents()[0]["objects"][3])
        parent["child_ids"] = ["object-evidence"]
        parent["object_type"] = aperture
        parent["z_index"] = 4  # Do not hide the fixture art under its opaque background.
        parent["geometry"]["bounds"] = {"x": 140., "y": 285., "width": 95., "height": 110.}
        parent["transform"].update(position={"x": 17., "y": 9.}, scale_x=1.1, scale_y=.8)
        layout["objects"][2]["parent_id"] = parent["object_id"]
        layout["objects"].append(parent)
        layout["boards"][0]["object_ids"].append(parent["object_id"])
        timeline["initial_object_states"].append({"object_id": parent["object_id"], "state": "visible",
            "state_version": 1, "visible": True})
        if aperture == "mask":
            parent.update(MASK_FIELDS)
            source = deepcopy(layout["objects"][0])
            source.update(object_id="mask-source", parent_id=None, object_type="ellipse", anchors=[],
                initial_state="visible", visible=True, path_data=None,
                style={"stroke": None, "fill": None, "text": None, "effect": None})
            source["geometry"] = {"bounds": {"x": 150., "y": 275., "width": 130., "height": 130.},
                "points": [], "corner_radius": None}
            layout["objects"].append(source)
            layout["boards"][0]["object_ids"].append(source["object_id"])
            timeline["initial_object_states"].append({"object_id": source["object_id"], "state": "visible",
                "state_version": 1, "visible": True})
    timeline["layout_sha256"] = digest(layout)
    return layout, timeline


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("aperture", [None, "group", "clip", "mask"])
def test_bound_art_matches_existing_bare_pixels_through_requested_sample_tree(portrait, aperture):
    layout, timeline = bound_art_documents(portrait, aperture)
    bare = deepcopy(layout)
    bare["objects"][2].pop("registry_binding")
    bare_timeline = deepcopy(timeline)
    bare_timeline["layout_sha256"] = digest(bare)
    before = deepcopy((layout, timeline))
    frames = {}
    # At4250 the narrow apertures already expose all their eventual art.
    #4100 is inside the actual reveal interval before those apertures fill.
    for at_ms in (5000, 4100, 4900, 4100):
        actual = compose_png_frame(layout, timeline, at_ms).png
        expected = compose_png_frame(bare, bare_timeline, at_ms).png
        assert actual == expected
        if at_ms in frames:
            assert actual == frames[at_ms]
        frames[at_ms] = actual
    assert frames[4100] != frames[4900]  # Real progressive art, not a static placeholder.
    assert (layout, timeline) == before


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("aperture", [None, "group", "clip", "mask"])
def test_bound_art_frozen_paint_is_same_pixels_with_no_live_resource_reads(portrait, aperture, monkeypatch):
    layout, timeline = bound_art_documents(portrait, aperture)
    typed = ExecutableLayoutV2.model_validate(layout)
    resolved = ResolvedVisualTimelineV2.model_validate(timeline)
    expected = compose_png_frame(layout, timeline, 5000).png
    snapshot = evaluate_frame(layout, timeline, 5000)
    inputs = verify_split_paint_inputs(typed, {})
    monkeypatch.setattr(Path, "read_bytes", lambda *_: pytest.fail("frozen frame reopened a live resource"))
    frame = _compose_validated_svg_frame(typed, resolved, snapshot, {}, split_inputs=inputs)
    assert _rasterize_svg_frame(typed, frame, split_inputs=inputs).png == expected


@pytest.mark.parametrize("portrait", [False, True])
def test_actual_tree_rejects_local_equivalence_that_diverges_in_sampled_world(portrait):
    layout, timeline = bound_art_documents(portrait, "group")
    layout["objects"][2]["anchors"][0]["point"]["y"] = 145.60004 / 300
    layout["objects"][3]["transform"]["scale_y"] = 100.
    timeline["layout_sha256"] = digest(layout)
    with pytest.raises(ValueError, match="sampled world anchor"):
        compose_svg_frame(layout, timeline, 5000)


def test_bound_endpoint_consumer_uses_verified_context_and_rejects_malformed_binding():
    layout, timeline = bound_art_documents()
    pointer = deepcopy(connector_documents()[0]["objects"][3])
    pointer.update(source_object_id="object-label", source_anchor_id="center",
        destination_object_id="object-evidence", destination_anchor_id="actor-left",
        visible=True, initial_state="visible")
    pointer["geometry"]["bounds"] = {"x": 0., "y": 0., "width": 1280., "height": 720.}
    layout["objects"].append(pointer)
    layout["boards"][0]["object_ids"].append(pointer["object_id"])
    timeline["initial_object_states"].append({"object_id": pointer["object_id"],
        "state": "visible", "state_version": 1, "visible": True})
    timeline["layout_sha256"] = digest(layout)
    assert "190 345.6" in compose_svg_frame(layout, timeline, 5000).svg
    layout["objects"][2]["anchors"][0]["point"]["x"] = .31
    timeline["layout_sha256"] = digest(layout)
    with pytest.raises(ValueError, match="does not match fitted registry anchor"):
        compose_svg_frame(layout, timeline, 0)
