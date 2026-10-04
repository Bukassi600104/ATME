"""Paired hierarchy/annotation consumers; public Group admission stays separate."""

import socket
import xml.etree.ElementTree as ET
from copy import deepcopy
from dataclasses import replace
from io import BytesIO

import pytest
from PIL import Image
from test_v2_annotation_action import append_target
from test_v2_annotation_contract import grouped_annotation_documents
from test_v2_hierarchy_contract import rehash
from test_v2_timeline_replay import resolved
from v2_fixtures import digest

from atme.render import v2_state
from atme.render.v2_hierarchy import HierarchySnapshot, changed_hierarchy_objects
from atme.render.v2_world import world_anchor, world_bounds
from atme.store.contracts_v2 import (
    ExecutableLayoutV2,
    GroupAction,
    HierarchyBasis,
    ResolvedVisualTimelineV2,
)


def annotation_group_documents(shell_id="target-group", start=5000, end=6000, *, nested=False, portrait=False):
    """Exact translated ungroup receipt with real authored notes and pointer."""
    _, layout, timeline = grouped_annotation_documents(leader=True)
    template = next(obj for obj in layout["objects"] if obj["object_id"] == "annotation-group")
    if shell_id == "annotation-group":
        shell = template
        members = ["annotation-note"]
    else:
        shell = deepcopy(template)
        members = ["object-system", "object-label"] if shell_id == "target-group" else ["unrelated-a", "unrelated-b"]
        shell.update(object_id=shell_id, child_ids=members, z_index=1 if shell_id == "target-group" else 4)
        shell["transform"]["position"] = {"x": 20, "y": 10}
        shell["transform"]["origin"] = {"x": 0, "y": 0}
        layout["objects"].append(shell)
        if shell_id == "unrelated-group":
            for index, key in enumerate(members):
                leaf = deepcopy(layout["objects"][0])
                leaf.update(object_id=key, initial_state="visible", visible=True, z_index=index)
                leaf["geometry"]["bounds"] = {"x": 980 + index * 70, "y": 580, "width": 45, "height": 40}
                leaf["geometry"]["corner_radius"] = 8
                layout["objects"].append(leaf)
                timeline["initial_object_states"].append({"object_id": key, "state": "visible", "visible": True,
                                                         "state_version": 1})
        timeline["initial_object_states"].append({"object_id": shell_id, "state": "grouped", "visible": True,
                                                 "state_version": 1})
    shell["initial_state"] = "grouped"
    next(row for row in timeline["initial_object_states"] if row["object_id"] == shell_id)["state"] = "grouped"
    for obj in layout["objects"]:
        if obj["object_id"] in members:
            obj["parent_id"] = shell_id
    if nested:
        outer = deepcopy(template)
        outer.update(object_id="outer-group", child_ids=[shell_id], z_index=1)
        outer["transform"].update(position={"x": 60, "y": -20}, scale_x=.9, scale_y=1.1,
                                  rotation_degrees=5, origin={"x": 0, "y": 0})
        shell["parent_id"] = outer["object_id"]
        layout["objects"].append(outer)
        timeline["initial_object_states"].append({"object_id": outer["object_id"], "state": "visible",
                                                 "visible": True, "state_version": 1})
    board = layout["boards"][0]
    board["object_ids"] = [obj["object_id"] for obj in layout["objects"]]
    board["density_limit"] = len(board["object_ids"])
    if portrait:
        profile = {"profile_id": "SHORT_FORM_9_16", "width": 720, "height": 1280, "fps": 30}
        layout["output_profile"] = deepcopy(profile)
        timeline["output_profile"] = deepcopy(profile)
        layout["canvas"].update(width=720, height=1280)
        bounds = {
            "object-system": (60, 220, 560, 400), "object-replacement": (60, 220, 560, 400),
            "object-label": (100, 270, 480, 80), "object-evidence": (90, 800, 540, 220),
            "annotation-note": (80, 660, 500, 80), "annotation-leader": (0, 0, 720, 1280),
            "unrelated-a": (100, 1100, 45, 40), "unrelated-b": (200, 1100, 45, 40),
        }
        for obj in layout["objects"]:
            rect = (0, 0, 720, 1280) if obj["object_type"] == "group" else bounds[obj["object_id"]]
            obj["geometry"]["bounds"] = dict(zip(("x", "y", "width", "height"), rect, strict=True))
    parsed = ExecutableLayoutV2.model_validate(layout)
    objects = {obj.object_id: obj for obj in parsed.objects}
    before = HierarchySnapshot.from_objects(objects)
    source = HierarchyBasis(placements=[{
        "object_id": node.object_id, "board_id": node.board_id, "parent_id": node.parent_id,
        "sibling_ordinal": node.sibling_ordinal, "local_transform": objects[node.object_id].transform,
    } for node in before.nodes])
    parent = shell["parent_id"]
    siblings = list(before.children("board-main", parent))
    index = siblings.index(shell_id) + 1
    siblings[index:index] = members
    ordinals = {key: ordinal for ordinal, key in enumerate(siblings)}
    after = HierarchySnapshot(tuple(replace(node, parent_id=parent, sibling_ordinal=ordinals[node.object_id])
                                    if node.object_id in ordinals else node for node in before.nodes))
    destination = deepcopy(source.model_dump(mode="json"))
    nodes = {node.object_id: node for node in after.nodes}
    for placement in destination["placements"]:
        node = nodes[placement["object_id"]]
        placement.update(parent_id=node.parent_id, sibling_ordinal=node.sibling_ordinal)
        if node.object_id in members:
            for axis in ("x", "y"):
                placement["local_transform"]["position"][axis] += shell["transform"]["position"][axis]
    action = deepcopy(timeline["actions"][0]["action"])
    action.pop("annotation", None)
    action.update(action_id="ungroup-annotation-fixture", verb="ungroup", target_ids=members, container_id=shell_id,
                  expected_state="grouped", post_state="ungrouped", easing="step", hierarchy_policy={
                      "member_root_ids": members, "source_basis": source.model_dump(mode="json"),
                      "destination_basis": destination, "source_basis_sha256": source.checksum(),
                      "destination_basis_sha256": "0" * 64,
                      "changed_object_ids": list(changed_hierarchy_objects(before, after, objects)),
                      "preserve_world_transform": True,
                  })
    rehash(action)
    timeline["actions"].append(resolved(GroupAction.model_validate(action), start, end).model_dump(mode="json"))
    timeline["actions"].sort(key=lambda row: row["start_ms"])
    timeline["coverage"][0]["action_ids"].append(action["action_id"])
    timeline["initial_hierarchy_basis"] = source.model_dump(mode="json")
    timeline["initial_hierarchy_basis_sha256"] = source.checksum()
    timeline["layout_sha256"] = digest(layout)
    return layout, timeline


def consumer_clock(layout, timeline):
    parsed_layout = ExecutableLayoutV2.model_validate(layout)
    parsed_timeline = ResolvedVisualTimelineV2.model_validate(timeline)
    hierarchy = HierarchySnapshot.from_objects({obj.object_id: obj for obj in parsed_layout.objects})
    context = v2_state._validate_pair_static(parsed_layout, parsed_timeline, digest(layout), hierarchy)
    replay, camera = v2_state._validate_consumer_history(context)
    return context, replay, camera


def regroup_first_documents(*, nested=False, portrait=False):
    layout, timeline = annotation_group_documents(nested=nested, portrait=portrait)
    group = next(row for row in timeline["actions"] if row["action"]["verb"] == "ungroup")
    action = group["action"]
    policy = action["hierarchy_policy"]
    policy["source_basis"], policy["destination_basis"] = policy["destination_basis"], policy["source_basis"]
    action.update(verb="group", expected_state="ungrouped", post_state="grouped")
    rehash(action)
    placements = {row["object_id"]: row for row in policy["source_basis"]["placements"]}
    for obj in layout["objects"]:
        placement = placements[obj["object_id"]]
        obj.update(parent_id=placement["parent_id"], z_index=placement["sibling_ordinal"] * 10,
                   transform=deepcopy(placement["local_transform"]))
        if obj["object_type"] == "group":
            obj["child_ids"] = [row["object_id"] for row in sorted(placements.values(),
                key=lambda row: row["sibling_ordinal"]) if row["parent_id"] == obj["object_id"]]
        if obj["object_id"] == "target-group":
            obj["initial_state"] = "ungrouped"
    next(row for row in timeline["initial_object_states"] if row["object_id"] == "target-group")["state"] = "ungrouped"
    layout["initial_empty_group_ownership"] = [{"shell_object_id": "target-group",
        "owner_group_action_id": action["action_id"], "owner_source_basis_sha256": policy["source_basis_sha256"]}]
    timeline["initial_hierarchy_basis"] = deepcopy(policy["source_basis"])
    timeline["initial_hierarchy_basis_sha256"] = policy["source_basis_sha256"]
    timeline["layout_sha256"] = digest(layout)
    return layout, timeline


def world_geometry(context, sample):
    objects = sample.hierarchy.object_map(context.objects)
    transforms = {frame.object_id: frame.transform for frame in sample.objects}
    return (world_bounds(objects["object-system"], objects, transforms),
            world_anchor(objects["object-system"], "center", objects, transforms),
            world_anchor(objects["annotation-note"], "center", objects, transforms))


@pytest.mark.parametrize("nested", [False, True])
def test_completed_group_commits_before_annotation_capture_and_preserves_world_geometry(nested):
    layout, timeline = annotation_group_documents(nested=nested)
    original = deepcopy((layout, timeline))
    context, replay, _ = consumer_clock(layout, timeline)
    capture = replay.before_action("replace-1")
    assert "target-group" not in capture.hierarchy.ancestors("object-system")
    assert capture.object("target-group").state == "ungrouped"
    assert not capture.object("annotation-note").visible
    for before, after in zip(world_geometry(context, replay.at(5999)), world_geometry(context, capture), strict=True):
        assert before == pytest.approx(after, abs=1e-4)
    assert replay.at(6250).object("annotation-note").reveal_fraction == .5
    assert replay.at(6750).object("annotation-leader").reveal_fraction == .5
    assert replay.at(7000).object("annotation-leader").visible
    assert replay.at(9000).object("annotation-note").visible
    assert (layout, timeline) == original


@pytest.mark.parametrize("nested", [False, True])
def test_completed_regroup_establishes_actual_new_annotation_target_parent(nested):
    layout, timeline = regroup_first_documents(nested=nested)
    context, replay, _ = consumer_clock(layout, timeline)
    captured = replay.before_action("replace-1")
    assert captured.hierarchy.ancestors("object-system")[0] == "target-group"
    assert captured.object("target-group").state == "grouped"
    for before, after in zip(world_geometry(context, replay.at(5999)), world_geometry(context, captured), strict=True):
        assert before == pytest.approx(after, abs=1e-4)
    assert replay.at(9000).object("annotation-leader").visible


@pytest.mark.parametrize("start,match", [(6200, "uninterrupted"), (7200, "uninterrupted"),
                                       (8500, "completed explicit removal")])
def test_new_regrouped_target_ancestor_is_observed_during_construction_hold_and_retention(start, match):
    layout, timeline = regroup_first_documents()
    append_target(timeline, "target-group", "fade", start, start + 100, opacity=.5)
    next(row for row in timeline["actions"] if row["action"]["verb"] == "fade")["action"]["expected_state"] = "grouped"
    with pytest.raises(ValueError, match=match):
        consumer_clock(layout, timeline)


@pytest.mark.parametrize("start,end", [(6200, 6400), (7200, 7500), (8400, 8700)])
def test_unrelated_group_during_construction_hold_or_retained_pointer_preserves_consumers(start, end):
    layout, timeline = annotation_group_documents("unrelated-group", start, end)
    context, replay, _ = consumer_clock(layout, timeline)
    assert world_geometry(context, replay.at(end - 1)) == world_geometry(context, replay.at(end))
    assert replay.at(end).hierarchy.children("board-main", "unrelated-group") == ()
    for at in (7000, 7999, 9000):
        assert replay.at(at).object("annotation-note").visible
        assert replay.at(at).object("annotation-leader").reveal_fraction == 1
        order = replay.at(at).hierarchy.paint_order(context.objects, "board-main")
        assert order.index("object-system") < order.index("annotation-note") < order.index("annotation-leader")


@pytest.mark.parametrize("start,end", [(5900, 6200), (7200, 7500), (8400, 8700)])
def test_related_group_cannot_overlap_annotation_construction_hold_or_retained_pointer(start, end):
    layout, timeline = annotation_group_documents("target-group", start, end)
    with pytest.raises(ValueError, match="uninterrupted|geometric hierarchy edit|completed explicit removal"):
        consumer_clock(layout, timeline)


@pytest.mark.parametrize("start,accepted", [(8250, True), (8249, False)])
def test_completed_solo_pointer_exit_allows_related_note_ungroup_at_exact_boundary(start, accepted):
    layout, timeline = annotation_group_documents("annotation-group", start, 8700)
    append_target(timeline, "annotation-leader", "exit", 8000, 8250)
    timeline["layout_sha256"] = digest(layout)
    if accepted:
        context, replay, _ = consumer_clock(layout, timeline)
        assert not replay.at(8250).object("annotation-leader").visible
        assert replay.at(8700).hierarchy.ancestors("annotation-note") == ()
        assert world_geometry(context, replay.at(8699)) == world_geometry(context, replay.at(8700))
    else:
        with pytest.raises(ValueError, match="geometric hierarchy edit|completed explicit removal"):
            consumer_clock(layout, timeline)


@pytest.mark.parametrize("start", [6200, 7200])
def test_parent_fade_guard_survives_real_group_annotation_composition(start):
    layout, timeline = annotation_group_documents("unrelated-group", 5000, 5500)
    append_target(timeline, "annotation-group", "fade", start, start + 100, opacity=.5)
    with pytest.raises(ValueError, match="uninterrupted"):
        consumer_clock(layout, timeline)


def test_public_group_frame_admission_remains_closed():
    layout, timeline = annotation_group_documents()
    with pytest.raises(v2_state.UnsupportedVisualAction, match="no frame implementation"):
        v2_state.evaluate_frame(layout, timeline, 6500)


def test_kernel_pair_proof_does_not_silently_open_no_return_storage_admission():
    layout, timeline = annotation_group_documents()
    consumer_clock(layout, timeline)
    original = deepcopy((layout, timeline))
    with pytest.raises(v2_state.V2FrameError, match="stored hierarchy annotation productions"):
        v2_state.validate_resolved_return_history(
            ExecutableLayoutV2.model_validate(layout), ResolvedVisualTimelineV2.model_validate(timeline),
            layout_sha256=digest(layout))
    assert (layout, timeline) == original


def private_svg(context, replay, camera, at_ms):
    from atme.render import v2_svg

    sample = v2_state._sample_validated_frame(context.layout, context.timeline, replay, camera, at_ms)
    held = {item.action.action_id: v2_state._sample_validated_frame(
        context.layout, context.timeline, replay, camera, item.end_ms)
        for item in context.timeline.actions
        if getattr(item.action, "annotation_policy", None) is not None
        and item.action.annotation_policy.leader_connector_id is not None}
    return v2_svg._compose_validated_svg_frame(context.layout, context.timeline, sample, held)


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("nested", [False, True])
@pytest.mark.parametrize("regroup", [False, True])
def test_real_private_svg_png_both_authored_profiles_are_offline_immutable_and_seekable(portrait, nested, regroup, monkeypatch):
    from atme.render import v2_svg

    def no_network(*args, **kwargs):
        raise AssertionError("private Group/annotation paint must not use network")
    monkeypatch.setattr(socket, "socket", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
    builder = regroup_first_documents if regroup else annotation_group_documents
    layout, timeline = builder(nested=nested, portrait=portrait)
    original = deepcopy((layout, timeline))
    context, replay, camera = consumer_clock(layout, timeline)
    expected_size = (720, 1280) if portrait else (1280, 720)
    frames = {}
    for at_ms in (5999, 6000, 6250, 6750, 7000, 7999, 9000):
        svg = private_svg(context, replay, camera, at_ms)
        png = v2_svg._rasterize_svg_frame(context.layout, svg).png
        image = Image.open(BytesIO(png)).convert("RGB")
        assert image.size == expected_size
        assert len(image.getcolors(image.width * image.height)) > 10
        frames[at_ms] = png
        ids = [node.attrib["data-object-id"] for node in ET.fromstring(svg.svg).iter()
               if "data-object-id" in node.attrib]
        assert "target-group" in ids and "object-system" in ids
        if at_ms >= 7000:
            assert ids.index("object-system") < ids.index("annotation-note") < ids.index("annotation-leader")
            pointer = next(node for node in ET.fromstring(svg.svg).iter()
                           if node.attrib.get("data-object-id") == "annotation-leader")
            assert any(node.tag.endswith("path") for node in pointer.iter())
    assert frames[5999] == frames[6000]  # World-preserving hierarchy boundary paints identically.
    assert frames[6250] != frames[6750] != frames[7000]
    assert frames[7000] == frames[7999] == frames[9000]
    assert v2_svg._rasterize_svg_frame(context.layout, private_svg(context, replay, camera, 6750)).png == frames[6750]
    assert (layout, timeline) == original
    with pytest.raises(v2_state.UnsupportedVisualAction):
        v2_svg.compose_png_frame(layout, timeline, 6750)


@pytest.mark.parametrize("shell_id", ["annotation-group", "target-group"])
@pytest.mark.parametrize("portrait", [False, True])
def test_post_pointer_exit_related_group_uses_captured_held_and_current_paint_hierarchies(shell_id, portrait):
    from atme.render import v2_svg

    layout, timeline = annotation_group_documents(shell_id, 8250, 8700, portrait=portrait)
    append_target(timeline, "annotation-leader", "exit", 8000, 8250)
    original = deepcopy((layout, timeline))
    context, replay, camera = consumer_clock(layout, timeline)
    before = v2_svg._rasterize_svg_frame(context.layout, private_svg(context, replay, camera, 8250)).png
    after_svg = private_svg(context, replay, camera, 8700)
    after = v2_svg._rasterize_svg_frame(context.layout, after_svg).png
    assert before == after
    ids = [node.attrib["data-object-id"] for node in ET.fromstring(after_svg.svg).iter()
           if "data-object-id" in node.attrib]
    assert "annotation-leader" not in ids
    assert ids.index("object-system") < ids.index("annotation-note")
    member = "annotation-note" if shell_id == "annotation-group" else "object-system"
    assert replay.at(8700).hierarchy.ancestors(member) == ()
    assert world_geometry(context, replay.at(8699)) == world_geometry(context, replay.at(8700))
    assert (layout, timeline) == original
    # Ending the removal one millisecond too late is not a completed solo exit.
    exit_item = next(row for row in timeline["actions"] if row["action"]["verb"] == "exit")
    exit_item["end_ms"] = 8251
    with pytest.raises(ValueError, match="geometric hierarchy edit|completed explicit removal"):
        consumer_clock(layout, timeline)


@pytest.mark.parametrize("start,end", [(6200, 6400), (7200, 7500), (8400, 8700)])
def test_unrelated_group_boundary_paints_identically_during_live_annotation(start, end):
    from atme.render import v2_svg

    layout, timeline = annotation_group_documents("unrelated-group", start, end)
    context, replay, camera = consumer_clock(layout, timeline)
    frames = [Image.open(BytesIO(v2_svg._rasterize_svg_frame(
        context.layout, private_svg(context, replay, camera, at)).png)).convert("RGB")
        for at in (end - 1, end)]
    # Both are unmodified real samples. One millisecond of live note writing may
    # differ, but unrelated grouping cannot disturb the target/evidence/own leaves.
    for rect in ((0, 0, 1280, 535), (950, 550, 1280, 650)):
        assert frames[0].crop(rect).tobytes() == frames[1].crop(rect).tobytes()
    if start >= 7000:
        assert frames[0].tobytes() == frames[1].tobytes()


@pytest.mark.parametrize("start", [8100, 8300])
def test_duplicate_or_overlapping_pointer_exit_cannot_hide_a_later_invalid_lifetime(start):
    layout, timeline = annotation_group_documents("unrelated-group", 5000, 5500)
    append_target(timeline, "annotation-leader", "exit", 8000, 8250)
    first = next(row for row in timeline["actions"] if row["action"]["verb"] == "exit")
    second = resolved({**first["action"], "action_id": "exit-leader-again"}, start, 8500).model_dump(mode="json")
    timeline["actions"].append(second)
    timeline["actions"].sort(key=lambda row: row["start_ms"])
    timeline["coverage"][0]["action_ids"].append("exit-leader-again")
    with pytest.raises(ValueError):
        consumer_clock(layout, timeline)


def test_private_compositor_cannot_skip_or_mistime_completed_pointer_preflight():
    from atme.render import v2_svg

    layout, timeline = annotation_group_documents()
    context, replay, camera = consumer_clock(layout, timeline)
    sample = v2_state._sample_validated_frame(context.layout, context.timeline, replay, camera, 100)
    for held in ({}, {"replace-1": sample}):
        with pytest.raises(v2_svg.UnsupportedVisualObject, match="exact completed construction frame"):
            v2_svg._compose_validated_svg_frame(context.layout, context.timeline, sample, held)
