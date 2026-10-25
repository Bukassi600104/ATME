"""One verified registry endpoint path for actual frame and lifecycle consumers."""

import xml.etree.ElementTree as ET
from copy import deepcopy
from pathlib import Path

import pytest
from atme.render import v2_state
from atme.render.style_bundle import registry_endpoint_inputs_for_objects
from atme.render.v2_connector import connector_route
from atme.render.v2_hierarchy import HierarchySnapshot
from atme.render.v2_split_paint import verify_split_paint_inputs
from atme.render.v2_svg import (
    _compose_validated_svg_frame,
    _rasterize_svg_frame,
    compose_png_frame,
    compose_svg_frame,
)
from atme.store.contracts_v2 import (
    ClipContainer,
    ExecutableLayoutV2,
    MaskContainer,
    ResolvedVisualTimelineV2,
)
from test_v2_annotation_contract import grouped_annotation_documents
from test_v2_callout_compositor import add_action, compositor_documents
from test_v2_connection_actions import relationship_documents
from test_v2_connection_geometry import (
    append_endpoint_move,
    grouped_connection_documents,
)
from test_v2_connector_svg import connector_documents
from test_v2_group_hierarchy import grouped_documents
from test_v2_mask_contract import MASK_FIELDS
from test_v2_registry_binding import registry_object
from test_v2_registry_runtime import bound_art_documents
from test_v2_registry_world import literal_transform
from v2_fixtures import digest


def rebind(layout, timeline):
    timeline["actions"].sort(key=lambda row: row["start_ms"])
    for coverage in timeline["coverage"]:
        coverage["action_ids"] = [row["action"]["action_id"] for row in timeline["actions"]
            if row["action"]["coverage_id"] == coverage["coverage_id"]]
    timeline["layout_sha256"] = digest(layout)


def replace_with_bound_actor(layout, key, *, retain_geometry=False):
    original = next(row for row in layout["objects"] if row["object_id"] == key)
    actor = registry_object()
    actor.update({field: deepcopy(original[field]) for field in
        ("object_id", "board_id", "beat_id", "visible", "initial_state", "z_index", "parent_id", "transform")})
    if retain_geometry:
        box = deepcopy(original["geometry"]["bounds"])
        actor["geometry"]["bounds"] = box
        # Independent literal 300x220 metadata, centered meet. Preserve receipt pivots.
        fit = min(box["width"] / 300, box["height"] / 220)
        actor["anchors"][0]["point"] = {
            "x": ((box["width"] - 300 * fit) / 2 + 90 * fit) / box["width"],
            "y": ((box["height"] - 220 * fit) / 2 + 105.6 * fit) / box["height"]}
    layout["objects"][layout["objects"].index(original)] = actor
    return actor


def bound_relationship_documents(portrait=False, *, grouped=False, regroup=False):
    if grouped:
        layout, timeline = grouped_connection_documents(portrait=portrait, regroup=regroup)
    else:
        layout, timeline = relationship_documents()
        if portrait:
            profile = {"profile_id": "SHORT_FORM_9_16", "width": 720, "height": 1280, "fps": 30}
            layout["output_profile"] = timeline["output_profile"] = profile
            layout["canvas"].update(width=720, height=1280)
        layout["objects"][3]["geometry"]["bounds"] = deepcopy(layout["canvas"])
    timeline["resolved_assets"] = []
    replace_with_bound_actor(layout, "object-system", retain_geometry=grouped)
    layout["objects"][3]["source_anchor_id"] = "actor-left"
    for row in timeline["actions"]:
        if row["action"]["verb"] in {"connect", "disconnect"}:
            row["action"]["source_anchor_id"] = "actor-left"
    rebind(layout, timeline)
    return layout, timeline


def frozen_context(layout, timeline):
    typed, resolved = ExecutableLayoutV2.model_validate(layout), ResolvedVisualTimelineV2.model_validate(timeline)
    inputs = verify_split_paint_inputs(typed, {})
    registry_inputs = registry_endpoint_inputs_for_objects({obj.object_id: obj for obj in typed.objects},
        frozen_files={name: payload for name, _, payload in inputs.bundle_bytes})
    return typed, resolved, inputs, registry_inputs


def private_clock(typed, resolved, checksum, registry_inputs):
    context = v2_state._validate_pair_static(typed, resolved, checksum,
        HierarchySnapshot.from_objects({obj.object_id: obj for obj in typed.objects}),
        registry_inputs=registry_inputs)
    replay, camera = v2_state._validate_consumer_history(context)
    return context, replay, camera


def add_aperture(layout, timeline, target, kind):
    shell = deepcopy(grouped_documents()[0]["objects"][3])
    shell.update(object_id="source-aperture", object_type="mask" if kind == "mask" else "clip",
        child_ids=[target["object_id"]], parent_id=None, z_index=target["z_index"],
        visible=True, initial_state="visible", transform=deepcopy(target["transform"]))
    shell["geometry"]["bounds"] = deepcopy(layout["canvas"])
    target["parent_id"] = shell["object_id"]
    rows = [shell]
    if kind == "clip_id":
        target["clip_id"] = shell["object_id"]
    if kind == "mask":
        shell.update(MASK_FIELDS)
        source = deepcopy(layout["objects"][0])
        source.update(object_id="mask-source", object_type="ellipse", parent_id=None,
            visible=True, initial_state="visible", path_data=None, anchors=[],
            style={"stroke": None, "fill": None, "text": None, "effect": None})
        source.pop("registry_binding", None)
        source.pop("variant", None)
        source["geometry"] = {"bounds": deepcopy(layout["canvas"]), "points": [], "corner_radius": None}
        rows.append(source)
    for row in rows:
        layout["objects"].append(row)
        layout["boards"][0]["object_ids"].append(row["object_id"])
        timeline["initial_object_states"].append({"object_id": row["object_id"], "state": "visible",
            "state_version": 1, "visible": True})
    layout["boards"][0]["density_limit"] = len(layout["objects"])
    rebind(layout, timeline)


def bound_consumer_documents(kind, portrait=False):
    if kind == "connector":
        layout, timeline = bound_art_documents(portrait)
        arrow = deepcopy(connector_documents()[0]["objects"][3])
        arrow.update(source_object_id="object-label", source_anchor_id="center",
            destination_object_id="object-evidence", destination_anchor_id="actor-left")
        arrow["geometry"]["bounds"] = deepcopy(layout["canvas"])
        layout["objects"].append(arrow)
        layout["boards"][0]["object_ids"].append(arrow["object_id"])
        timeline["initial_object_states"].append({"object_id": arrow["object_id"],
            "state": "hidden", "state_version": 1, "visible": False})
        add_action(timeline, "draw", arrow["object_id"], 5000, 5100, "hidden")
        endpoint, leader, at_ms = "object-evidence", "object-arrow", 5200
    elif kind == "callout":
        layout, timeline = compositor_documents(portrait)
        body = next(row for row in layout["objects"] if row["object_id"] == "annotation-note")
        body["callout_binding"]["target_anchor_id"] = "actor-left"
        endpoint, leader, at_ms = "object-system", "annotation-leader", 4500
    else:
        _, layout, timeline = grouped_annotation_documents(leader=True)
        if portrait:
            profile = {"profile_id": "SHORT_FORM_9_16", "width": 720, "height": 1280, "fps": 30}
            layout["output_profile"] = timeline["output_profile"] = profile
            layout["canvas"].update(width=720, height=1280)
        timeline["resolved_assets"] = []
        endpoint, leader, at_ms = "object-system", "annotation-leader", 9000
    if kind != "connector":
        original = next(row for row in layout["objects"] if row["object_id"] == endpoint)
        actor = registry_object()
        actor.update(object_id=endpoint, board_id=original["board_id"], beat_id=original["beat_id"],
            visible=original["visible"], initial_state=original["initial_state"],
            z_index=original["z_index"], parent_id=original["parent_id"])
        layout["objects"][layout["objects"].index(original)] = actor
        arrow = next(row for row in layout["objects"] if row["object_id"] == leader)
        arrow["destination_anchor_id"] = "actor-left"
        if portrait and kind == "annotation":
            arrow["geometry"]["bounds"] = deepcopy(layout["canvas"])
    timeline["actions"].sort(key=lambda row: row["start_ms"])
    for coverage in timeline["coverage"]:
        coverage["action_ids"] = [row["action"]["action_id"] for row in timeline["actions"]
            if row["action"]["coverage_id"] == coverage["coverage_id"]]
    timeline["layout_sha256"] = digest(layout)
    return layout, timeline, leader, at_ms


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("kind", ["connector", "callout", "annotation"])
def test_real_consumers_route_to_same_fitted_semantic_point_and_are_seekable(kind, portrait):
    layout, timeline, leader, at_ms = bound_consumer_documents(kind, portrait)
    before = deepcopy((layout, timeline))
    markup = compose_svg_frame(layout, timeline, at_ms).svg
    tree = ET.fromstring(markup)
    node = next(row for row in tree.iter() if row.attrib.get("data-object-id") == leader)
    path = next(row for row in node if row.tag.endswith("path"))
    assert path.attrib["d"].endswith("190 345.6")
    first = compose_png_frame(layout, timeline, at_ms).png
    compose_png_frame(layout, timeline, at_ms - 50)
    assert compose_png_frame(layout, timeline, at_ms).png == first
    assert (layout, timeline) == before


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("kind", ["connector", "callout", "annotation"])
def test_frozen_frame_consumers_use_verified_bytes_without_live_file_fallback(kind, portrait, monkeypatch):
    layout, timeline, _, at_ms = bound_consumer_documents(kind, portrait)
    typed, resolved = ExecutableLayoutV2.model_validate(layout), ResolvedVisualTimelineV2.model_validate(timeline)
    expected = compose_png_frame(layout, timeline, at_ms).png
    inputs = verify_split_paint_inputs(typed, {})
    registry_inputs = registry_endpoint_inputs_for_objects(
        {obj.object_id: obj for obj in typed.objects},
        frozen_files={name: payload for name, _, payload in inputs.bundle_bytes})
    monkeypatch.setattr(Path, "read_bytes", lambda *_: pytest.fail("frozen relationship reopened a resource"))
    snapshot = v2_state._evaluate_frame_with_registry_inputs(layout, timeline, at_ms, registry_inputs)
    held = {row.action.action_id: v2_state._evaluate_frame_with_registry_inputs(
        layout, timeline, row.end_ms, registry_inputs) for row in resolved.actions
        if getattr(row.action, "annotation_policy", None) is not None
        and row.action.annotation_policy.leader_connector_id is not None}
    v2_state.validate_resolved_return_history(typed, resolved,
        layout_sha256=digest(layout), registry_inputs=registry_inputs)
    frame = _compose_validated_svg_frame(typed, resolved, snapshot, held, split_inputs=inputs)
    assert _rasterize_svg_frame(typed, frame, split_inputs=inputs).png == expected


@pytest.mark.parametrize("portrait", [False, True])
def test_bound_connect_disconnect_actual_lifetime_and_frozen_random_seek(portrait, monkeypatch):
    layout, timeline = bound_relationship_documents(portrait)
    before = deepcopy((layout, timeline))
    expected = {t: compose_png_frame(layout, timeline, t).png for t in (4450, 4900, 6450, 6900)}
    assert expected[4450] != expected[4900] != expected[6900]
    typed, resolved, inputs, registry_inputs = frozen_context(layout, timeline)
    monkeypatch.setattr(Path, "read_bytes", lambda *_: pytest.fail("frozen Connect validation reopened files"))
    _, replay, _ = private_clock(typed, resolved, digest(layout), registry_inputs)
    frames = {}
    for t in (6900, 4450, 4900, 6450, 4450):
        sample = v2_state._evaluate_frame_with_registry_inputs(layout, timeline, t, registry_inputs)
        arrow = sample.object("object-arrow")
        assert dict(replay.at(t).state_versions)["object-arrow"] == (3 if t == 6900 else 2 if t >= 4900 else 1)
        assert arrow.visible == (t != 6900)
        svg = _compose_validated_svg_frame(typed, resolved, sample, {}, split_inputs=inputs)
        assert _rasterize_svg_frame(typed, svg, split_inputs=inputs).png == expected[t]
        if t != 6900:
            node = next(row for row in ET.fromstring(svg.svg).iter()
                if row.attrib.get("data-object-id") == "object-arrow")
            assert next(row for row in node if row.tag.endswith("path")).attrib["d"].startswith("M 190 345.6 ")
        frames[t] = sample
    assert frames[4450] == v2_state._evaluate_frame_with_registry_inputs(layout, timeline, 4450, registry_inputs)
    assert (layout, timeline) == before


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("kind", ["connection", "callout", "annotation"])
def test_bound_target_motion_during_retained_pointer_rejects_before_first_frame(kind, portrait):
    if kind == "connection":
        layout, timeline = bound_relationship_documents(portrait)
        append_endpoint_move(layout, timeline, 5000, 5500)
        match = "connected lifetime"
    else:
        layout, timeline, _, _ = bound_consumer_documents(kind, portrait)
        start = 5000 if kind == "callout" else 9000
        row = add_action(timeline, "move", "object-system", start, start + 500)
        row["action"]["destination"] = deepcopy(layout["objects"][0]["transform"])
        row["action"]["destination"]["position"]["x"] = 20.
        match = "callout|retained|annotation"
    rebind(layout, timeline)
    before = deepcopy((layout, timeline))
    with pytest.raises(ValueError, match=match):
        v2_state.evaluate_frame(layout, timeline, 0)
    assert (layout, timeline) == before


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("regroup", [False, True])
def test_actual_group_receipt_routes_bound_anchor_from_current_hierarchy(portrait, regroup, monkeypatch):
    layout, timeline = bound_relationship_documents(portrait, grouped=True, regroup=regroup)
    original = deepcopy((layout, timeline))
    typed, resolved, inputs, registry_inputs = frozen_context(layout, timeline)
    monkeypatch.setattr(Path, "read_bytes", lambda *_: pytest.fail("Group endpoint validation reopened files"))
    context, replay, camera = private_clock(typed, resolved, digest(layout), registry_inputs)
    painted = {}
    for t in (7500, 6500, 6250, 7250, 6500):
        sample = v2_state._sample_validated_frame(typed, resolved, replay, camera, t)
        current = sample.hierarchy.object_map(context.objects)
        actor = current["object-system"]
        assert actor.parent_id == ("object-group" if regroup else "outer-group")
        assert actor.parent_id != context.objects[actor.object_id].parent_id
        states = {row.object_id: row for row in sample.objects}
        transforms = {key: row.transform for key, row in states.items()}
        # Independent metadata fit and literal affine math; do not ask runtime for expected endpoints.
        b = actor.geometry.bounds
        fit = min(b.width / 300, b.height / 220)
        point = (b.x + (b.width - 300 * fit) / 2 + 90 * fit,
                 b.y + (b.height - 220 * fit) / 2 + 105.6 * fit)
        key = actor.object_id
        while key is not None:
            point = literal_transform(point, current[key], transforms[key])
            key = current[key].parent_id
        want = tuple(float(f"{value:.4f}") for value in point)
        svg = _compose_validated_svg_frame(typed, resolved, sample, {}, split_inputs=inputs)
        if t < 7500:
            route = connector_route(current["object-arrow"], current, states, 2.6667, registry_inputs=registry_inputs)
            assert route.points[0] == want
            assert " ".join(format(value, ".4f").rstrip("0").rstrip(".") for value in want) in svg.svg
        png = _rasterize_svg_frame(typed, svg, split_inputs=inputs).png
        if t in painted:
            assert png == painted[t]
        painted[t] = png
    assert painted[6250] != painted[6500] != painted[7500]
    assert (layout, timeline) == original


@pytest.mark.parametrize("owner,kind", [("object-system", "clip_id"), ("outer-group", "clip"),
    ("outer-group", "mask"), ("outer-group", "clip_id")])
def test_malformed_post_group_current_map_is_rejected_by_connection_observer(owner, kind, monkeypatch):
    layout, timeline = bound_relationship_documents(grouped=True)
    typed, resolved, _, registry_inputs = frozen_context(layout, timeline)
    context, replay, camera = private_clock(typed, resolved, digest(layout), registry_inputs)
    sample = v2_state._sample_validated_frame(typed, resolved, replay, camera, 6500)
    current = sample.hierarchy.object_map(context.objects)
    assert current["object-system"].parent_id == "outer-group"  # Actual completed receipt, not authored basis.
    original = deepcopy(context.objects)
    object_map = HierarchySnapshot.object_map

    def malformed_current_map(hierarchy, objects):
        result = object_map(hierarchy, objects)
        if result["object-system"].parent_id == "outer-group":
            raw = result[owner].model_dump(mode="json")
            if kind == "clip_id":
                result[owner] = result[owner].model_copy(update={"clip_id": "explicit-aperture"})
            elif kind == "clip":
                raw["object_type"] = "clip"
                result[owner] = ClipContainer.model_validate(raw)
            else:
                raw.update(object_type="mask", **MASK_FIELDS)
                result[owner] = MaskContainer.model_validate(raw)
        return result

    # Defense only: bypass upstream Group aperture invariants at the shared observer seam.
    monkeypatch.setattr(HierarchySnapshot, "object_map", malformed_current_map)
    with pytest.raises(ValueError, match="registry relationship anchor is unavailable under sampled aperture"):
        v2_state._validate_pair_temporal(context, replay, camera)
    assert context.objects == original  # No mutation of immutable authored records.


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("kind", ["connection", "callout", "annotation"])
@pytest.mark.parametrize("aperture", ["clip", "mask", "clip_id"])
def test_initial_aperture_endpoint_fails_real_consumer_at_existing_earliest_guard(kind, aperture, portrait):
    if kind == "connection":
        layout, timeline = bound_relationship_documents(portrait)
    else:
        layout, timeline, _, _ = bound_consumer_documents(kind, portrait)
    actor = next(row for row in layout["objects"] if row["object_id"] == "object-system")
    add_aperture(layout, timeline, actor, aperture)
    if kind != "callout":
        ExecutableLayoutV2.model_validate(layout)  # Model-valid connection/annotation aperture.
    else:
        # Callout's accepted contract intentionally rejects this before runtime.
        with pytest.raises(ValueError, match="unclipped [Gg]roup ancestry"):
            ExecutableLayoutV2.model_validate(layout)
    ResolvedVisualTimelineV2.model_validate(timeline)
    before = deepcopy((layout, timeline))
    with pytest.raises(ValueError, match="sampled aperture|clipped-endpoint geometry|unclipped [Gg]roup ancestry|unsupported clip_id"):
        v2_state.evaluate_frame(layout, timeline, 0)
    assert (layout, timeline) == before


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("kind", ["connector", "callout", "annotation"])
def test_unrelated_clipped_registry_art_remains_paintable_beside_real_relationship(kind, portrait, monkeypatch):
    layout, timeline, leader, at_ms = bound_consumer_documents(kind, portrait)
    actor = registry_object()
    actor.update(object_id="unrelated-art", visible=True, initial_state="visible", z_index=4)
    layout["objects"].append(actor)
    layout["boards"][0]["object_ids"].append(actor["object_id"])
    timeline["initial_object_states"].append({"object_id": actor["object_id"], "state": "visible",
        "state_version": 1, "visible": True})
    add_aperture(layout, timeline, actor, "clip")
    expected = compose_png_frame(layout, timeline, at_ms).png
    typed, resolved, inputs, registry_inputs = frozen_context(layout, timeline)
    monkeypatch.setattr(Path, "read_bytes", lambda *_: pytest.fail("unrelated clipped art forced live reads"))
    sample = v2_state._evaluate_frame_with_registry_inputs(layout, timeline, at_ms, registry_inputs)
    held = {row.action.action_id: v2_state._evaluate_frame_with_registry_inputs(
        layout, timeline, row.end_ms, registry_inputs) for row in resolved.actions
        if getattr(row.action, "annotation_policy", None) is not None
        and row.action.annotation_policy.leader_connector_id is not None}
    frame = _compose_validated_svg_frame(typed, resolved, sample, held, split_inputs=inputs)
    tree = ET.fromstring(frame.svg)
    assert any(row.attrib.get("data-object-id") == actor["object_id"] for row in tree.iter())
    node = next(row for row in tree.iter() if row.attrib.get("data-object-id") == leader)
    assert next(row for row in node if row.tag.endswith("path")).attrib["d"].endswith("190 345.6")
    assert _rasterize_svg_frame(typed, frame, split_inputs=inputs).png == expected
