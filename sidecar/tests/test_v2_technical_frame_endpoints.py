"""Technical endpoint consumers use native physical anchors, never generic boxes."""

import xml.etree.ElementTree as ET
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from socket import socket

import pytest
from test_v2_connector_svg import connector_documents
from test_v2_technical_frame_compositor import (
    action_row,
    composite_documents,
    set_actions,
)
from test_v2_technical_frame_world import pose, sampled
from v2_fixtures import digest

from atme.render import v2_state
from atme.render.style_bundle import registry_endpoint_inputs_for_objects
from atme.render.v2_connector import connector_route
from atme.render.v2_registry import registry_relationship_anchor
from atme.render.v2_split_paint import verify_split_paint_inputs
from atme.render.v2_state import FrameObject, FrameTransform
from atme.render.v2_svg import (
    _compose_validated_svg_frame,
    _rasterize_svg_frame,
    compose_png_frame,
    compose_svg_frame,
)
from atme.store.contracts_v2 import (
    ClipContainer,
    ConnectorObject,
    ExecutableLayoutV2,
    MaskContainer,
    ResolvedVisualTimelineV2,
)


def test_native_endpoint_has_literal_sampled_world_position_without_io(monkeypatch):
    obj, objects, transforms = sampled()
    transforms["list-group"] = pose(10., 20., 2., 3., 90.)
    original = deepcopy((objects, transforms))
    def forbidden(*args, **kwargs):
        raise AssertionError("pure technical endpoint attempted live IO")
    monkeypatch.setattr(Path, "read_bytes", forbidden)
    monkeypatch.setattr(socket, "connect", forbidden)
    assert registry_relationship_anchor(obj, "chrome-top", objects, transforms) == (795., 370.)
    assert (objects, transforms) == original


@pytest.mark.parametrize("fault", ["anchor", "amplified_anchor", "part_fit", "missing_pose", "foreign_chrome"])
def test_shared_resolver_cannot_bypass_native_world_authentication(fault):
    obj, objects, transforms = sampled()
    if fault == "anchor":
        obj.anchors[0].point.x += .01
    elif fault == "amplified_anchor":
        obj.anchors[0].point.x += .00000001
        transforms["list-group"] = pose(sx=1000., sy=1000.)
    elif fault == "part_fit":
        transforms["part-content"] = pose(500., 0.)
    elif fault == "missing_pose":
        transforms.pop("part-content")
    else:
        objects[obj.object_id] = deepcopy(obj)
        objects[obj.object_id].geometry.bounds.x += 1.
    with pytest.raises(ValueError, match="technical_frame"):
        registry_relationship_anchor(obj, "chrome-top", objects, transforms)


@pytest.mark.parametrize("kind", ["clip", "mask", "clip_id"])
def test_native_endpoint_refuses_sampled_aperture_ancestry(kind):
    obj, objects, transforms = sampled()
    outer = objects["list-group"].model_dump(mode="json")
    outer.update(object_id="outer-aperture", parent_id=None, child_ids=["list-group"])
    outer["object_type"] = "clip" if kind == "clip_id" else kind
    cls = MaskContainer if kind == "mask" else ClipContainer
    objects["outer-aperture"] = cls.model_validate(outer)
    objects["list-group"].parent_id = "outer-aperture"
    transforms["outer-aperture"] = FrameTransform.from_contract(objects["outer-aperture"].transform)
    if kind == "clip_id":
        obj.clip_id = "outer-aperture"
    with pytest.raises(ValueError, match="technical_frame.*sampled aperture"):
        registry_relationship_anchor(obj, "chrome-top", objects, transforms)


def route_scene():
    obj, objects, transforms = sampled()
    raw = deepcopy(connector_documents()[0]["objects"][-1])
    raw.update(source_object_id=obj.object_id, source_anchor_id="chrome-top",
        destination_object_id="object-label", destination_anchor_id="center")
    raw["geometry"]["bounds"] = {"x": 0., "y": 0., "width": 1200., "height": 1000.}
    arrow = ConnectorObject.model_validate(raw)
    objects[arrow.object_id] = arrow
    transforms[arrow.object_id] = FrameTransform.from_contract(arrow.transform)
    states = {key: FrameObject(key, item.board_id, "visible", True, 1., 1.,
        transforms[key] if isinstance(transforms[key], FrameTransform) else FrameTransform.from_contract(transforms[key]))
        for key, item in objects.items()}
    return obj, arrow, objects, transforms, states


@pytest.mark.parametrize("routing,expected", [
    ("straight", ((350., 205.), (300., 250.))),
    ("elbow", ((350., 205.), (300., 205.), (300., 250.))),
    ("curve", ((350., 205.), (325., 205.), (300., 250.))),
])
def test_actual_connector_routes_follow_native_physical_endpoint(routing, expected):
    _, arrow, objects, _, states = route_scene()
    arrow = arrow.model_copy(update={"routing": routing})
    assert connector_route(arrow, objects, states, 2.6667).points == expected


def test_generic_arrow_keeps_existing_positive_endpoint_rule_not_new_complete_rule():
    obj, arrow, objects, _, states = route_scene()
    states[obj.object_id] = replace(states[obj.object_id], state="hidden", opacity=.5, reveal_fraction=.25)
    for role in obj.technical_frame.roles:
        states[role.object_id] = replace(states[role.object_id], state="hidden", visible=False, reveal_fraction=0.)
    assert connector_route(arrow, objects, states, 2.6667).points == ((350., 205.), (300., 250.))


def test_route_consumer_also_rejects_native_anchor_mismatch():
    obj, arrow, objects, _, states = route_scene()
    obj.anchors[0].point.x += .01
    with pytest.raises(ValueError, match="technical_frame.*physical"):
        connector_route(arrow, objects, states, 2.6667)


def test_unknown_native_placed_anchor_is_never_inferred_from_center():
    obj, objects, transforms = sampled()
    with pytest.raises(ValueError, match="unknown.*anchor"):
        registry_relationship_anchor(obj, "not-authored", objects, transforms)


def native_relation_documents(*, portrait=False, managed=False):
    layout, timeline = composite_documents(portrait=portrait)
    timeline["actions"][0]["action"]["opacity"] = 1.
    source = connector_documents()[0]
    label, arrow = deepcopy(source["objects"][1]), deepcopy(source["objects"][-1])
    label.update(object_id="endpoint-label", text="Next", initial_state="visible", visible=True,
        parent_id=None, z_index=10, style={"stroke": None, "fill": None, "text": "text.label", "effect": None})
    label["geometry"]["bounds"] = {"x": 150., "y": 620., "width": 250., "height": 60.}
    arrow.update(source_object_id="object-evidence", source_anchor_id="chrome-top",
        destination_object_id="endpoint-label", destination_anchor_id="center", z_index=20,
        initial_state="disconnected" if managed else "hidden", visible=False)
    arrow["geometry"]["bounds"] = deepcopy(layout["canvas"])
    layout["objects"].extend([label, arrow])
    layout["boards"][0]["object_ids"] = [obj["object_id"] for obj in layout["objects"]]
    layout["boards"][0]["density_limit"] = len(layout["objects"])
    for obj in (label, arrow):
        timeline["initial_object_states"].append({"object_id": obj["object_id"],
            "state": obj["initial_state"], "visible": obj["visible"], "state_version": 1})
    base = deepcopy(timeline["actions"][0])
    base["action"].pop("opacity")
    base["action"].pop("destination")
    if managed:
        base["action"].pop("target_ids")
        payload = {"verb": "connect", "connector_id": arrow["object_id"],
            "source_object_id": arrow["source_object_id"], "source_anchor_id": arrow["source_anchor_id"],
            "destination_object_id": arrow["destination_object_id"], "destination_anchor_id": arrow["destination_anchor_id"],
            "expected_state": "disconnected", "post_state": "connected"}
    else:
        payload = {"verb": "draw", "target_ids": [arrow["object_id"]], "annotation": None,
            "expected_state": "hidden", "post_state": "visible"}
    row = action_row(base, payload, 2000, 3000, "native-relationship")
    set_actions(timeline, [timeline["actions"][0], row])
    timeline["layout_sha256"] = digest(layout)
    return layout, timeline


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("managed", [False, True])
def test_actual_both_profile_connector_histories_paint_native_anchor_and_seek(portrait, managed):
    layout, timeline = native_relation_documents(portrait=portrait, managed=managed)
    original = deepcopy((layout, timeline))
    tree = ET.fromstring(compose_svg_frame(layout, timeline, 3000).svg)
    node = next(row for row in tree.iter() if row.attrib.get("data-object-id") == "object-arrow")
    path = next(row for row in node if row.tag.endswith("path"))
    assert path.attrib["d"] == "M 350 205 L 275 650"
    pixels = {at: compose_png_frame(layout, timeline, at).png for at in (1500, 2500, 3000)}
    assert len(set(pixels.values())) == 3
    for at in (3000, 1500, 2500, 3000):
        assert compose_png_frame(layout, timeline, at).png == pixels[at]
    assert (layout, timeline) == original


def native_note_documents(kind, *, portrait=False):
    layout, timeline = native_relation_documents(portrait=portrait)
    objects = {obj["object_id"]: obj for obj in layout["objects"]}
    note, leader = objects["endpoint-label"], objects["object-arrow"]
    for item in (note, leader):
        item.update({key: deepcopy(objects["object-evidence"][key])
                     for key in ("board_id", "beat_id", "coverage_ids")})
    note.update(initial_state="hidden", visible=False, text="Look here")
    note["style"]["text"] = "text.body"
    leader.update(role="pointer", source_object_id=note["object_id"], source_anchor_id="center",
        destination_object_id="object-evidence", destination_anchor_id="chrome-top")
    next(row for row in timeline["initial_object_states"] if row["object_id"] == note["object_id"]).update(
        state="hidden", visible=False)
    base = deepcopy(timeline["actions"][1])
    if kind == "annotation":
        payload = {"verb": "annotate", "target_ids": ["object-evidence"], "expected_state": "visible",
            "annotation_policy": {"annotation_object_ids": [note["object_id"]],
                "leader_connector_id": leader["object_id"],
                "phases": [{"object_id": note["object_id"], "mode": "write", "weight": 2.},
                           {"object_id": leader["object_id"], "mode": "draw", "weight": 1.}],
                "readable_hold_ms": 500, "retention": "retain"}}
        rows = [action_row(base, payload, 2000, 4000, "native-annotation")]
    else:
        note.update(object_type="callout", callout_binding={"version": "1.0.0",
            "leader_connector_id": leader["object_id"], "callout_anchor_id": "center",
            "target_object_id": "object-evidence", "target_anchor_id": "chrome-top"})
        rows = [action_row(base, {"verb": "write", "target_ids": [note["object_id"]]}, 2000, 3000, "native-callout"),
                action_row(base, {"verb": "draw", "target_ids": [leader["object_id"]]}, 3000, 4000, "native-pointer")]
    set_actions(timeline, [timeline["actions"][0], *rows])
    timeline["layout_sha256"] = digest(layout)
    return layout, timeline


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("kind", ["annotation", "callout"])
def test_real_note_consumers_have_physical_native_pointer_and_seek_parity(kind, portrait):
    layout, timeline = native_note_documents(kind, portrait=portrait)
    original = deepcopy((layout, timeline))
    tree = ET.fromstring(compose_svg_frame(layout, timeline, 4500).svg)
    node = next(row for row in tree.iter() if row.attrib.get("data-object-id") == "object-arrow")
    path = next(row for row in node if row.tag.endswith("path"))
    assert path.attrib["d"] == "M 275 650 L 350 205"
    pixels = {at: compose_png_frame(layout, timeline, at).png for at in (1500, 2500, 3500, 4500)}
    assert len(set(pixels.values())) == 4
    for at in (4500, 1500, 3500, 2500, 4500):
        assert compose_png_frame(layout, timeline, at).png == pixels[at]
    assert (layout, timeline) == original


def consumer_documents(kind, portrait=False):
    return (native_note_documents(kind, portrait=portrait) if kind in {"annotation", "callout"}
            else native_relation_documents(portrait=portrait, managed=kind == "managed"))


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("kind", ["generic", "managed", "annotation", "callout"])
def test_all_actual_native_consumers_frozen_history_and_paint_have_no_live_io(kind, portrait, monkeypatch):
    layout, timeline = consumer_documents(kind, portrait)
    times = (2500, 3500, 4500) if kind in {"annotation", "callout"} else (1500, 2500, 3000)
    expected = {at: compose_png_frame(layout, timeline, at).png for at in times}
    typed, resolved = ExecutableLayoutV2.model_validate(layout), ResolvedVisualTimelineV2.model_validate(timeline)
    inputs = verify_split_paint_inputs(typed, {})
    registry = registry_endpoint_inputs_for_objects({obj.object_id: obj for obj in typed.objects},
        frozen_files={name: raw for name, _, raw in inputs.bundle_bytes})
    def forbidden(*args, **kwargs):
        raise AssertionError("frozen technical consumer attempted live IO")
    monkeypatch.setattr(Path, "read_bytes", forbidden)
    monkeypatch.setattr(socket, "connect", forbidden)
    held = {row.action.action_id: v2_state._evaluate_frame_with_registry_inputs(layout, timeline, row.end_ms, registry)
        for row in resolved.actions if getattr(row.action, "annotation_policy", None) is not None}
    for at in (*reversed(times), times[0]):
        sample = v2_state._evaluate_frame_with_registry_inputs(layout, timeline, at, registry)
        frame = _compose_validated_svg_frame(typed, resolved, sample, held, split_inputs=inputs)
        assert _rasterize_svg_frame(typed, frame, split_inputs=inputs).png == expected[at]


@pytest.mark.parametrize("kind", ["generic", "managed", "annotation", "callout"])
def test_actual_native_consumer_rejects_physical_anchor_tamper_before_first_frame(kind):
    layout, timeline = consumer_documents(kind)
    chrome = next(obj for obj in layout["objects"] if obj["object_id"] == "object-evidence")
    chrome["anchors"][0]["point"]["x"] += .01
    timeline["layout_sha256"] = digest(layout)
    with pytest.raises(ValueError, match="physical native anchor"):
        compose_svg_frame(layout, timeline, 0)


def add_native_aperture(layout, timeline, kind):
    group = next(obj for obj in layout["objects"] if obj["object_id"] == "list-group")
    outer = deepcopy(group)
    outer.update(object_id="outer-aperture", object_type=kind, child_ids=["list-group"], parent_id=None)
    outer["geometry"]["bounds"] = deepcopy(layout["canvas"])
    group["parent_id"] = outer["object_id"]
    rows = [outer]
    if kind == "mask":
        outer.update(mask_mode="alpha", mask_source_object_id="native-mask-source",
            mask_coordinate_space="parent_local", invert=False, feather_px=0)
        source = deepcopy(connector_documents()[0]["objects"][0])
        source.update(object_id="native-mask-source", object_type="rectangle", path_data=None,
            board_id=outer["board_id"], beat_id=outer["beat_id"], coverage_ids=deepcopy(outer["coverage_ids"]),
            initial_state="visible", visible=True, anchors=[], parent_id=None,
            style={"stroke": None, "fill": None, "text": None, "effect": None},
            geometry={"bounds": deepcopy(layout["canvas"]), "points": [], "corner_radius": None})
        rows.append(source)
    layout["objects"].extend(rows)
    layout["boards"][0]["object_ids"] = [obj["object_id"] for obj in layout["objects"]]
    layout["boards"][0]["density_limit"] = len(layout["objects"])
    for obj in rows:
        timeline["initial_object_states"].append({"object_id": obj["object_id"], "state": obj["initial_state"],
            "visible": obj["visible"], "state_version": 1})
    timeline["layout_sha256"] = digest(layout)


@pytest.mark.parametrize("kind", ["generic", "managed", "annotation", "callout"])
@pytest.mark.parametrize("aperture", ["clip", "mask"])
def test_actual_consumer_refuses_native_aperture_context_at_its_existing_gate(kind, aperture):
    layout, timeline = consumer_documents(kind)
    add_native_aperture(layout, timeline, aperture)
    if kind == "callout":
        with pytest.raises(ValueError, match="callout pointer endpoints require unclipped"):
            ExecutableLayoutV2.model_validate(layout)
        return
    ExecutableLayoutV2.model_validate(layout)
    ResolvedVisualTimelineV2.model_validate(timeline)
    with pytest.raises(ValueError, match="aperture|unclipped|clipped-endpoint"):
        compose_svg_frame(layout, timeline, 4500)


def append_group_move(layout, timeline, start=4000, end=5000):
    group = next(obj for obj in layout["objects"] if obj["object_id"] == "list-group")
    destination = deepcopy(group["transform"])
    destination["position"] = {"x": 20., "y": 10.}
    move = action_row(timeline["actions"][0], {"verb": "move", "target_ids": ["list-group"],
        "opacity": None, "destination": destination}, start, end, "move-native-group")
    rows = sorted([*timeline["actions"], move], key=lambda row: row["start_ms"])
    set_actions(timeline, rows)


@pytest.mark.parametrize("portrait", [False, True])
def test_generic_arrow_tracks_actual_native_group_motion_without_stale_endpoint(portrait):
    layout, timeline = native_relation_documents(portrait=portrait)
    append_group_move(layout, timeline)
    for at, point in ((4500, "360 210"), (5000, "370 215"), (4500, "360 210")):
        tree = ET.fromstring(compose_svg_frame(layout, timeline, at).svg)
        arrow = next(row for row in tree.iter() if row.attrib.get("data-object-id") == "object-arrow")
        assert next(row for row in arrow if row.tag.endswith("path")).attrib["d"] == f"M {point} L 275 650"


@pytest.mark.parametrize("overlap", [False, True])
def test_managed_native_connection_keeps_disconnect_before_endpoint_edit_boundary(overlap):
    layout, timeline = native_relation_documents(managed=True)
    disconnect = action_row(timeline["actions"][1], {"verb": "disconnect", "expected_state": "connected",
        "post_state": "disconnected"}, 3500, 4000, "native-disconnect")
    set_actions(timeline, [*timeline["actions"], disconnect])
    append_group_move(layout, timeline, 3999 if overlap else 4000, 5000)
    if overlap:
        with pytest.raises(ValueError, match="completed disconnect"):
            v2_state.evaluate_frame(layout, timeline, 0)
    else:
        assert not v2_state.evaluate_frame(layout, timeline, 4500).object("object-arrow").visible


@pytest.mark.parametrize("kind", ["annotation", "callout"])
@pytest.mark.parametrize("overlap", [False, True])
def test_native_note_pointer_exit_remains_required_before_target_group_motion(kind, overlap):
    layout, timeline = native_note_documents(kind)
    base = deepcopy(timeline["actions"][0])
    base["action"].pop("opacity")
    base["action"].pop("destination")
    removal = action_row(base, {"verb": "exit", "target_ids": ["object-arrow"],
        "expected_state": "visible", "post_state": "removed", "annotation": None}, 5000, 5500, "native-pointer-out")
    set_actions(timeline, [*timeline["actions"], removal])
    append_group_move(layout, timeline, 5499 if overlap else 5500, 6500)
    if overlap:
        with pytest.raises(ValueError, match="completed explicit.*(removal|exit)"):
            v2_state.evaluate_frame(layout, timeline, 0)
    else:
        assert not v2_state.evaluate_frame(layout, timeline, 6000).object("object-arrow").visible


def test_actual_generic_partial_chrome_retains_positive_endpoint_semantics():
    layout, timeline = native_relation_documents()
    for obj in layout["objects"]:
        if obj["object_id"] == "object-evidence" or obj["object_id"].startswith("part-"):
            obj.update(initial_state="hidden", visible=False)
            next(row for row in timeline["initial_object_states"] if row["object_id"] == obj["object_id"]).update(
                state="hidden", visible=False)
    first = deepcopy(timeline["actions"][1])
    first = action_row(first, {"verb": "reveal", "target_ids": ["object-evidence"]}, 0, 4000, "native-chrome-in")
    second = action_row(timeline["actions"][1], {}, 1000, 2000, "native-arrow-in")
    set_actions(timeline, [first, second])
    timeline["layout_sha256"] = digest(layout)
    tree = ET.fromstring(compose_svg_frame(layout, timeline, 1500).svg)
    arrow = next(row for row in tree.iter() if row.attrib.get("data-object-id") == "object-arrow")
    assert next(row for row in arrow if row.tag.endswith("path")).attrib["d"] == "M 350 205 L 275 650"
