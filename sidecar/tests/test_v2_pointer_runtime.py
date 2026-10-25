"""P3-28 native authored points/edges, not inferred source objects or graphs."""

import io
import math
import xml.etree.ElementTree as ET
from copy import deepcopy

import pytest
from PIL import Image
from test_v2_connection_actions import relationship_documents
from test_v2_connector_svg import connector_documents
from test_v2_group_hierarchy import grouped_documents
from v2_fixtures import common_action, digest

from atme.render.v2_state import V2FrameError, evaluate_frame
from atme.render.v2_svg import compose_png_frame, compose_svg_frame


def pointer_runtime_documents(*, kind="pointer", routing="straight", portrait=False, managed=False):
    layout, timeline = relationship_documents() if managed else connector_documents(routing)
    connector = layout["objects"][3]
    connector.update(routing=routing)
    if kind == "pointer":
        connector.update(role="pointer", source_object_id=None, source_anchor_id=None,
                         source_point={"x": 80.5, "y": 60.25})
        for row in timeline["actions"]:
            if row["action"]["verb"] in {"connect", "disconnect"}:
                row["action"].update(source_object_id=None, source_anchor_id=None)
    else:
        connector["object_type"] = "network"
    if portrait:
        profile = {"profile_id": "SHORT_FORM_9_16", "width": 720, "height": 1280, "fps": 30}
        layout["output_profile"] = deepcopy(profile)
        timeline["output_profile"] = deepcopy(profile)
        layout["canvas"].update(width=720, height=1280)
    connector["geometry"]["bounds"] = {"x": 0, "y": 0,
        "width": layout["canvas"]["width"], "height": layout["canvas"]["height"]}
    timeline["layout_sha256"] = digest(layout)
    return layout, timeline


def connector_path(svg):
    group = next(node for node in ET.fromstring(svg).iter()
                 if node.attrib.get("data-object-id") == "object-arrow")
    return group, next(node for node in group if node.tag.endswith("path"))


def add_pointer_parent(layout, timeline):
    group = deepcopy(grouped_documents()[0]["objects"][3])
    group.update(object_id="pointer-parent", child_ids=["object-arrow"], initial_state="visible")
    group["geometry"]["bounds"] = deepcopy(layout["objects"][3]["geometry"]["bounds"])
    group["transform"].update(position={"x": 20, "y": 10}, origin={"x": 0, "y": 0},
                              scale_x=1.2, scale_y=.8, rotation_degrees=0)
    layout["objects"][3]["parent_id"] = group["object_id"]
    layout["objects"].append(group)
    layout["boards"][0]["object_ids"].append(group["object_id"])
    timeline["initial_object_states"].append({"object_id": group["object_id"], "state": "visible",
                                              "visible": True, "state_version": 1})
    timeline["layout_sha256"] = digest(layout)
    return group


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("kind", ["pointer", "network"])
@pytest.mark.parametrize("routing", ["straight", "elbow", "curve"])
def test_native_explicit_points_and_network_edges_draw_without_fake_sources(tmp_path, portrait, kind, routing):
    layout, timeline = pointer_runtime_documents(kind=kind, routing=routing, portrait=portrait)
    original = deepcopy((layout, timeline))
    partial = compose_svg_frame(layout, timeline, 4450).svg
    complete = compose_svg_frame(layout, timeline, 4900).svg
    group, path = connector_path(partial)
    assert path.attrib["d"].startswith("M 80.5 60.25" if kind == "pointer" else "M 320 330")
    assert path.attrib["d"].endswith("300 250")
    assert "stroke-dasharray" in path.attrib
    assert not any(node.tag.endswith("polygon") for node in group)
    assert any(node.tag.endswith("polygon") for node in connector_path(complete)[0])
    assert (" Q " in path.attrib["d"]) == (routing == "curve")
    partial_png = compose_png_frame(layout, timeline, 4450).png
    complete_png = compose_png_frame(layout, timeline, 4900).png
    assert partial_png != complete_png
    image = Image.open(io.BytesIO(complete_png)).convert("RGB")
    assert image.size == ((720, 1280) if portrait else (1280, 720))
    if kind == "pointer":
        assert image.getpixel((81, 61)) != (250, 248, 241)
    (tmp_path / f"{kind}-{routing}-complete.png").write_bytes(complete_png)
    for at in (6900, 0, 4900, 2000, 4450):
        actual = compose_png_frame(layout, timeline, at).png
        if at == 4450:
            assert actual == partial_png
        if at == 4900:
            assert actual == complete_png
    assert (layout, timeline) == original


@pytest.mark.parametrize("portrait", [False, True])
def test_free_point_uses_current_parent_local_space_and_live_target(portrait):
    layout, timeline = pointer_runtime_documents(portrait=portrait)
    group = add_pointer_parent(layout, timeline)
    connector = layout["objects"][3]
    connector.update(initial_state="visible", visible=True)
    timeline["initial_object_states"][3].update(state="visible", visible=True)
    timeline["actions"][2]["action"].update(verb="reveal", target_ids=["object-evidence"])
    label = layout["objects"][1]
    label.update(initial_state="visible", visible=True)
    timeline["initial_object_states"][1].update(state="visible", visible=True)
    for row, target, destination in (
        (timeline["actions"][0], group, {"x": 44, "y": 10}),
        (timeline["actions"][1], label, {"x": 40, "y": 0}),
    ):
        transform = deepcopy(target["transform"])
        transform["position"] = destination
        row["action"] = {**common_action(row["action"]["action_id"], row["action"]["source_instruction_id"]),
            "verb": "move", "target_ids": [target["object_id"]], "expected_state": "visible",
            "destination": transform, "opacity": None}
    timeline["layout_sha256"] = digest(layout)
    first = compose_svg_frame(layout, timeline, 0).svg
    last = compose_svg_frame(layout, timeline, 3000).svg
    # Independent inverse of authored parent T(20,10)*S(1.2,.8), then T(44,10).
    assert connector_path(first)[1].attrib["d"] == "M 80.5 60.25 L 233.3333 300"
    assert connector_path(last)[1].attrib["d"] == "M 80.5 60.25 L 246.6667 300"
    before = evaluate_frame(layout, timeline, 0)
    after = evaluate_frame(layout, timeline, 3000)
    assert before.object("object-arrow").transform == after.object("object-arrow").transform
    assert before.object("object-system") == after.object("object-system")
    assert compose_svg_frame(layout, timeline, 0).svg == first


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("kind", ["pointer", "network"])
def test_managed_point_or_network_changes_only_relationship_state(portrait, kind):
    layout, timeline = pointer_runtime_documents(kind=kind, portrait=portrait, managed=True)
    before = evaluate_frame(layout, timeline, 3999)
    partial = evaluate_frame(layout, timeline, 4450)
    complete = evaluate_frame(layout, timeline, 4900)
    after = evaluate_frame(layout, timeline, 6900)
    assert not before.object("object-arrow").visible
    assert 0 < partial.object("object-arrow").reveal_fraction < 1
    assert complete.object("object-arrow").state == "connected"
    assert not after.object("object-arrow").visible
    for key in ("object-system", "object-label"):
        assert before.object(key) == partial.object(key) == complete.object(key) == after.object(key)
    image = compose_png_frame(layout, timeline, 4450).png
    compose_png_frame(layout, timeline, 6900)
    assert compose_png_frame(layout, timeline, 4450).png == image


@pytest.mark.parametrize("start_ms", [5000, 6900])
def test_managed_point_parent_cannot_move_until_disconnect_finishes(start_ms):
    layout, timeline = pointer_runtime_documents(managed=True)
    group = add_pointer_parent(layout, timeline)
    move = deepcopy(timeline["actions"][0])
    transform = deepcopy(group["transform"])
    transform["position"]["x"] += 10
    move["action"] = {**common_action("parent-move", "instruction-1"), "verb": "move",
        "target_ids": [group["object_id"]], "expected_state": "visible", "destination": transform,
        "opacity": None, "coverage_id": "coverage-1",
        "fallback": {"fallback_id": "fallback-1", "on_failure": "block"}}
    move.update(start_ms=start_ms, end_ms=start_ms + 500)
    move["resolved_trigger"].update(alignment_anchor_ms=start_ms, resolved_at_ms=start_ms)
    timeline["actions"].append(move)
    timeline["actions"].sort(key=lambda row: row["start_ms"])
    timeline["coverage"][0]["action_ids"].append("parent-move")
    if start_ms == 6900:
        evaluate_frame(layout, timeline, 7400)
        return
    with pytest.raises(V2FrameError, match="completed disconnect"):
        evaluate_frame(layout, timeline, 4450)


@pytest.mark.parametrize("fault,match", [
    ("bounds", "exceeds authored bounds"),
    ("coincident", "degenerate"),
    ("independent_transform", "independent transform"),
    ("parent_clip", "ordinary Group"),
    ("endpoint_clip", "clipped-endpoint"),
    ("hidden_target", "hidden endpoint"),
])
def test_free_pointer_never_fabricates_unsupported_or_unavailable_geometry(fault, match):
    layout, timeline = pointer_runtime_documents()
    pointer = layout["objects"][3]
    at_ms = 4450
    if fault == "bounds":
        pointer["geometry"]["bounds"].update(width=100, height=100)
    elif fault == "coincident":
        pointer["source_point"] = {"x": 300, "y": 250}
    elif fault == "independent_transform":
        pointer["transform"]["position"]["x"] = 1
    elif fault in {"parent_clip", "endpoint_clip"}:
        group = add_pointer_parent(layout, timeline)
        group["object_type"] = "clip"
        if fault == "endpoint_clip":
            pointer["parent_id"] = None
            layout["objects"][1]["parent_id"] = group["object_id"]
            group["child_ids"] = ["object-label"]
    else:
        pointer.update(visible=True, initial_state="visible")
        timeline["initial_object_states"][3].update(visible=True, state="visible")
        timeline["actions"][2]["action"].update(verb="reveal", target_ids=["object-evidence"])
        at_ms = 0
    timeline["layout_sha256"] = digest(layout)
    with pytest.raises(ValueError, match=match):
        compose_svg_frame(layout, timeline, at_ms)


@pytest.mark.parametrize("kind", ["pointer", "network"])
def test_connection_sampling_does_not_mutate_endpoint_versions(kind):
    from test_v2_group_annotation import consumer_clock

    layout, timeline = pointer_runtime_documents(kind=kind, managed=True)
    _context, replay, _camera = consumer_clock(layout, timeline)
    samples = [replay.at(at) for at in (3999, 4450, 4900, 6450, 6900, 4450)]
    for key in ("object-system", "object-label"):
        assert {dict(sample.state_versions)[key] for sample in samples} == {2}


@pytest.mark.parametrize("portrait", [False, True])
def test_rotated_nonuniform_parent_uses_independent_inverse_and_native_pixels(tmp_path, portrait):
    layout, timeline = pointer_runtime_documents(portrait=portrait)
    group = add_pointer_parent(layout, timeline)
    group["transform"]["rotation_degrees"] = 30
    pointer = layout["objects"][3]
    pointer.update(initial_state="visible", visible=True)
    timeline["initial_object_states"][3].update(state="visible", visible=True)
    timeline["actions"][2]["action"].update(verb="reveal", target_ids=["object-evidence"])
    label = layout["objects"][1]
    label.update(initial_state="visible", visible=True)
    timeline["initial_object_states"][1].update(state="visible", visible=True)
    for row, target, position in (
        (timeline["actions"][0], group, {"x": 44, "y": 10}),
        (timeline["actions"][1], label, {"x": 40, "y": 0}),
    ):
        destination = deepcopy(target["transform"])
        destination["position"] = position
        row["action"] = {**common_action(row["action"]["action_id"], row["action"]["source_instruction_id"]),
            "verb": "move", "target_ids": [target["object_id"]], "expected_state": "visible",
            "destination": destination, "opacity": None}
    timeline["layout_sha256"] = digest(layout)
    untouched = deepcopy((layout, timeline))
    angle = math.radians(30)
    frames = {}
    for at, parent_x, target_x in ((0, 20, 300), (3000, 44, 340)):
        # Analytic S^-1 R^-1 T^-1, independent of the runtime affine helper.
        dx, dy = target_x - parent_x, 250 - 10
        end = ((math.cos(angle) * dx + math.sin(angle) * dy) / 1.2,
               (-math.sin(angle) * dx + math.cos(angle) * dy) / .8)
        end_text = " ".join(f"{value:.4f}".rstrip("0").rstrip(".") for value in end)
        svg = compose_svg_frame(layout, timeline, at).svg
        assert connector_path(svg)[1].attrib["d"] == f"M 80.5 60.25 L {end_text}"
        parent = next(node for node in ET.fromstring(svg).iter()
                      if node.attrib.get("data-object-id") == group["object_id"])
        assert "rotate(30)" in parent.attrib["transform"]
        assert "scale(1.2 0.8)" in parent.attrib["transform"]
        frames[at] = compose_png_frame(layout, timeline, at).png
        world_start = (parent_x + math.cos(angle) * 1.2 * 80.5 - math.sin(angle) * .8 * 60.25,
                       10 + math.sin(angle) * 1.2 * 80.5 + math.cos(angle) * .8 * 60.25)
        image = Image.open(io.BytesIO(frames[at])).convert("RGB")
        assert image.getpixel(tuple(map(round, world_start))) != (250, 248, 241)
        (tmp_path / f"rotated-pointer-{at}.png").write_bytes(frames[at])
    assert frames[0] != frames[3000]
    for at in (3000, 0, 4900, 3000, 0):
        png = compose_png_frame(layout, timeline, at).png
        if at in frames:
            assert png == frames[at]
    assert (layout, timeline) == untouched


@pytest.mark.parametrize("writer,conflicts", [
    ("current-parent", True), ("outer-parent", True), ("pointer-parent", False), (None, False),
])
def test_connection_observer_reserves_current_ancestry_not_former_parent(writer, conflicts):
    """Observer unit: a complete current hierarchy, not stored Group-history proof."""
    from types import SimpleNamespace

    from test_v2_timeline_replay import resolved

    from atme.render.v2_hierarchy import HierarchySnapshot
    from atme.render.v2_lifecycle import (
        UnsupportedLifecycle,
        validate_connection_lifetime,
    )
    from atme.store.contracts_v2 import ExecutableLayoutV2, ResolvedAction

    layout, timeline = pointer_runtime_documents(managed=True)
    former = add_pointer_parent(layout, timeline)
    current = deepcopy(former)
    current.update(object_id="current-parent", child_ids=["object-system"], parent_id="outer-parent", z_index=10)
    outer = deepcopy(former)
    outer.update(object_id="outer-parent", child_ids=["current-parent"], z_index=11)
    layout["objects"][0]["parent_id"] = "current-parent"
    layout["objects"].extend([current, outer])
    layout["boards"][0]["object_ids"].extend(["current-parent", "outer-parent"])
    layout["boards"][0]["density_limit"] = 7
    objects = {obj.object_id: obj for obj in ExecutableLayoutV2.model_validate(layout).objects}
    effective = dict(objects)
    effective["object-arrow"] = objects["object-arrow"].model_copy(update={"parent_id": "current-parent"})
    effective["pointer-parent"] = objects["pointer-parent"].model_copy(update={"child_ids": []})
    effective["current-parent"] = objects["current-parent"].model_copy(
        update={"child_ids": ["object-system", "object-arrow"]})
    sample = SimpleNamespace(hierarchy=HierarchySnapshot.from_objects(effective))
    actions = [ResolvedAction.model_validate(row) for row in timeline["actions"]]
    item = next(row for row in actions if row.action.verb == "connect")
    if writer:
        destination = objects[writer].transform.model_dump(mode="json")
        destination["position"]["x"] += 10
        action = {**common_action("writer-1", "instruction-1"), "verb": "move", "target_ids": [writer],
                  "expected_state": "visible", "destination": destination, "opacity": None}
        actions.append(resolved(action, 5000, 5500))
        actions.sort(key=lambda row: row.start_ms)
    if conflicts:
        with pytest.raises(UnsupportedLifecycle, match="completed disconnect"):
            validate_connection_lifetime(item, sample, objects, tuple(actions), 10000)
    else:
        validate_connection_lifetime(item, sample, objects, tuple(actions), 10000)
