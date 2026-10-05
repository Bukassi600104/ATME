"""Post-Group replacement/morph consumers preserve stored authority and history."""

import xml.etree.ElementTree as ET
from copy import deepcopy
from dataclasses import replace
from functools import partial
from io import BytesIO

import pytest
from PIL import Image
from test_v2_annotation_contract import grouped_annotation_documents
from test_v2_group_annotation import consumer_clock, private_svg
from test_v2_group_annotation_project import stored_group_annotation_return_basis
from test_v2_hierarchy_contract import rehash
from test_v2_morph_action import morph_documents
from test_v2_replace_action import documents as replace_documents
from test_v2_timeline_replay import resolved
from v2_fixtures import digest

from atme.narrative_source import describe
from atme.project_service import ProjectError, _resolved_compilation_fingerprint
from atme.render import v2_svg
from atme.render.v2_hierarchy import HierarchySnapshot, changed_hierarchy_objects
from atme.render.v2_hierarchy_replay import completed_hierarchy_basis
from atme.render.v2_lifecycle import nonterminal_paint_order
from atme.render.v2_state import UnsupportedVisualAction
from atme.render.v2_world import world_bounds
from atme.store.contracts_v2 import ExecutableLayoutV2, GroupAction, HierarchyBasis


def grouped_replacement_documents(*, verb="replace", regroup=False, portrait=False, chain=False, intermediate=None):
    """Move a visible container; its untouched hidden destination is not a root."""
    layout, timeline = morph_documents() if verb == "morph" else replace_documents()
    _, template_layout, _ = grouped_annotation_documents()
    template = next(obj for obj in template_layout["objects"] if obj["object_type"] == "group")
    members = ["object-system", "object-replacement"]
    if intermediate:
        leaf = deepcopy(layout["objects"][-1])
        leaf.update(object_id="object-rz-intermediate", initial_state=intermediate,
                    visible=intermediate == "visible")
        layout["objects"].append(leaf)
        timeline["initial_object_states"].append({"object_id": leaf["object_id"], "state": intermediate,
                                                   "state_version": 1, "visible": leaf["visible"]})
        members.append(leaf["object_id"])
    if chain:
        third = deepcopy(layout["objects"][-1])
        third.update(object_id="object-z-third")
        if verb == "morph":
            third.update(object_type="rectangle")
            third["geometry"]["bounds"] = {"x": 120, "y": 240, "width": 380, "height": 160}
        else:
            third["style"]["fill"] = "surface.accent"
        layout["objects"].append(third)
        timeline["initial_object_states"].append({"object_id": "object-z-third", "state": "hidden",
                                                   "state_version": 1, "visible": False})
        second = deepcopy(timeline["actions"][-1])
        second["action"].update(action_id="replace-2", from_object_id="object-replacement",
                                to_object_id="object-z-third", trigger={"kind": "absolute", "at_ms": 7600})
        second.update(start_ms=7600, end_ms=7900)
        second["resolved_trigger"].update(source=second["action"]["trigger"], alignment_anchor_ms=7600,
                                           resolved_at_ms=7600)
        timeline["actions"].append(second)
        timeline["coverage"][0]["action_ids"].append("replace-2")
        members.append("object-z-third")
    for obj in layout["objects"]:
        if obj["object_id"] in members:
            obj["parent_id"] = "replacement-pair"
    containers = (
        ("replacement-pair", "replacement-shell", members, "visible", (30, 20)),
        ("replacement-shell", "replacement-outer", ["replacement-pair"], "grouped", (20, 10)),
        ("replacement-outer", None, ["replacement-shell"], "visible", (15, 10)),
    )
    for key, parent, children, state, position in containers:
        obj = deepcopy(template)
        obj.update(object_id=key, parent_id=parent, child_ids=children, initial_state=state,
                   visible=True, z_index=0)
        obj["geometry"]["bounds"] = {"x": 0, "y": 0, "width": 1280, "height": 720}
        obj["transform"].update(position=dict(zip(("x", "y"), position, strict=True)),
                                origin={"x": 0, "y": 0})
        if key == "replacement-outer":
            obj["transform"].update(scale_x=.95, scale_y=1.05, rotation_degrees=3)
        layout["objects"].append(obj)
        timeline["initial_object_states"].append({"object_id": key, "state": state,
                                                   "state_version": 1, "visible": True})
    board = layout["boards"][0]
    board["object_ids"] = [obj["object_id"] for obj in layout["objects"]]
    board["density_limit"] = len(board["object_ids"])
    if portrait:
        profile = {"profile_id": "SHORT_FORM_9_16", "width": 720, "height": 1280, "fps": 30}
        layout["output_profile"] = deepcopy(profile)
        timeline["output_profile"] = deepcopy(profile)
        layout["canvas"].update(width=720, height=1280)
        bounds = {"object-system": (60, 220, 500, 300), "object-replacement": (60, 220, 500, 300),
                  "object-label": (100, 600, 480, 80), "object-evidence": (90, 800, 540, 220)}
        if verb == "morph":
            bounds["object-replacement"] = (100, 340, 300, 240)
        if chain:
            bounds["object-z-third"] = (60, 220, 500, 300) if verb == "replace" else (100, 480, 380, 160)
        if intermediate:
            bounds["object-rz-intermediate"] = bounds["object-replacement"]
        for obj in layout["objects"]:
            rectangle = (0, 0, 720, 1280) if obj["object_type"] == "group" else bounds[obj["object_id"]]
            obj["geometry"]["bounds"] = dict(zip(("x", "y", "width", "height"), rectangle, strict=True))
    parsed = ExecutableLayoutV2.model_validate(layout)
    objects = {obj.object_id: obj for obj in parsed.objects}
    before = HierarchySnapshot.from_objects(objects)
    source = HierarchyBasis(placements=[{
        "object_id": node.object_id, "board_id": node.board_id, "parent_id": node.parent_id,
        "sibling_ordinal": node.sibling_ordinal, "local_transform": objects[node.object_id].transform,
    } for node in before.nodes])
    after = HierarchySnapshot(tuple(
        replace(node, parent_id="replacement-outer", sibling_ordinal=1)
        if node.object_id == "replacement-pair" else node for node in before.nodes))
    destination = source.model_dump(mode="json")
    for placement in destination["placements"]:
        if placement["object_id"] == "replacement-pair":
            placement.update(parent_id="replacement-outer", sibling_ordinal=1)
            placement["local_transform"]["position"].update(x=50, y=30)
    action = {
        "action_id": "group-replacement-fixture", "source_instruction_id": "instruction-1",
        "board_id": "board-main", "semantic_reason": "Preserve the replacement model while regrouping",
        "trigger": {"kind": "absolute", "at_ms": 4000}, "easing": "step",
        "expected_state": "grouped", "post_state": "ungrouped", "coverage_id": "coverage-1",
        "fallback": {"fallback_id": "fallback-1", "on_failure": "block"},
        "verb": "ungroup", "container_id": "replacement-shell", "target_ids": ["replacement-pair"],
        "hierarchy_policy": {
            "member_root_ids": ["replacement-pair"], "source_basis": source.model_dump(mode="json"),
            "destination_basis": destination, "source_basis_sha256": source.checksum(),
            "destination_basis_sha256": "0" * 64,
            "changed_object_ids": list(changed_hierarchy_objects(before, after, objects)),
            "preserve_world_transform": True,
        },
    }
    rehash(action)
    if regroup:
        policy = action["hierarchy_policy"]
        policy["source_basis"], policy["destination_basis"] = policy["destination_basis"], policy["source_basis"]
        action.update(verb="group", expected_state="ungrouped", post_state="grouped")
        rehash(action)
        placements = {row["object_id"]: row for row in policy["source_basis"]["placements"]}
        for obj in layout["objects"]:
            placement = placements[obj["object_id"]]
            obj.update(parent_id=placement["parent_id"], transform=deepcopy(placement["local_transform"]))
            if obj["object_id"] not in members:
                obj["z_index"] = placement["sibling_ordinal"] * 10
            if obj["object_type"] == "group":
                obj["child_ids"] = [row["object_id"] for row in sorted(placements.values(),
                    key=lambda row: row["sibling_ordinal"]) if row["parent_id"] == obj["object_id"]]
            if obj["object_id"] == "replacement-shell":
                obj["initial_state"] = "ungrouped"
        next(row for row in timeline["initial_object_states"]
             if row["object_id"] == "replacement-shell")["state"] = "ungrouped"
        layout["initial_empty_group_ownership"] = [{"shell_object_id": "replacement-shell",
            "owner_group_action_id": action["action_id"], "owner_source_basis_sha256": policy["source_basis_sha256"]}]
    timeline["actions"].append(resolved(GroupAction.model_validate(action), 4000, 5000).model_dump(mode="json"))
    timeline["actions"].sort(key=lambda row: row["start_ms"])
    timeline["coverage"][0]["action_ids"].append(action["action_id"])
    timeline["initial_hierarchy_basis"] = deepcopy(action["hierarchy_policy"]["source_basis"])
    timeline["initial_hierarchy_basis_sha256"] = action["hierarchy_policy"]["source_basis_sha256"]
    timeline["layout_sha256"] = digest(layout)
    return layout, timeline


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("regroup", [False, True])
@pytest.mark.parametrize("verb", ["replace", "morph"])
def test_grouped_replacement_captured_geometry_and_offline_pixels(verb, regroup, portrait, monkeypatch):
    import socket

    layout, timeline = grouped_replacement_documents(verb=verb, regroup=regroup, portrait=portrait)
    original = deepcopy((layout, timeline))
    context, replay, camera = consumer_clock(layout, timeline)
    group = next(row["action"] for row in timeline["actions"] if row["action"]["verb"] in {"group", "ungroup"})
    assert group["target_ids"] == group["hierarchy_policy"]["member_root_ids"] == ["replacement-pair"]
    for side in ("source", "destination"):
        placements = {row["object_id"]: row for row in group["hierarchy_policy"][f"{side}_basis"]["placements"]}
        assert placements.keys() == context.objects.keys()
        assert placements["object-replacement"]["parent_id"] == "replacement-pair"
    group_capture = replay.before_action(group["action_id"])
    assert not group_capture.object("object-replacement").visible
    ready = {"replacement-pair", "replacement-shell"}
    for key in tuple(ready):
        ready.update(group_capture.hierarchy.ancestors(key))
    assert all(group_capture.object(key).visible and group_capture.object(key).reveal_fraction == 1
               and group_capture.object(key).opacity > 0 for key in ready)
    capture = replay.before_action("replace-1")
    assert ("replacement-shell" in capture.hierarchy.ancestors("object-system")) is regroup
    assert capture.hierarchy.ancestors("object-system") == capture.hierarchy.ancestors("object-replacement")
    assert not capture.object("object-replacement").visible
    assert dict(capture.state_versions)["object-replacement"] == 2
    for key in ("object-system", "object-replacement"):
        old = replay.at(3999)
        old_objects = old.hierarchy.object_map(context.objects)
        new_objects = capture.hierarchy.object_map(context.objects)
        assert world_bounds(old_objects[key], old_objects, {f.object_id: f.transform for f in old.objects}) == pytest.approx(
            world_bounds(new_objects[key], new_objects, {f.object_id: f.transform for f in capture.objects}), abs=1e-4)
    def no_network(*args, **kwargs):
        raise AssertionError("post-Group replacement frames must be offline")
    monkeypatch.setattr(socket, "socket", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
    frames = {at: v2_svg._rasterize_svg_frame(context.layout, private_svg(context, replay, camera, at)).png
              for at in (5999, 6000, 6500, 7000, 7999)}
    assert frames[5999] == frames[6000]
    assert frames[5999] != frames[6500] != frames[7000]
    assert frames[7000] == frames[7999]
    assert Image.open(BytesIO(frames[6500])).size == ((720, 1280) if portrait else (1280, 720))
    root = ET.fromstring(private_svg(context, replay, camera, 6500).svg)
    nodes = {node.attrib["data-object-id"]: node for node in root.iter() if "data-object-id" in node.attrib}
    assert "replacement-pair" in nodes
    if verb == "replace":
        assert nodes["object-system"].attrib["opacity"] == nodes["object-replacement"].attrib["opacity"] == "0.5"
    else:
        assert "object-system" in nodes and "object-replacement" not in nodes
        assert len([node for node in root.iter() if node.attrib.get("data-geometry-action") == "morph"]) == 1
    middle, end = replay.at(6500), replay.at(7000)
    assert middle.object("object-system").visible
    assert middle.object("object-replacement").visible is (verb == "replace")
    assert (middle.object("object-system").morph_geometry is not None) is (verb == "morph")
    assert end.object("object-system").state == "removed" and not end.object("object-system").visible
    assert end.object("object-replacement").state == "visible"
    assert dict(end.state_versions)["object-system"] == 4
    assert dict(end.state_versions)["object-replacement"] == 3
    for at in (7999, 6000, 7000, 6500):
        assert v2_svg._rasterize_svg_frame(context.layout, private_svg(context, replay, camera, at)).png == frames[at]
    with pytest.raises(UnsupportedVisualAction):
        v2_svg.compose_png_frame(layout, timeline, 6500)
    assert (layout, timeline) == original


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("regroup", [False, True])
@pytest.mark.parametrize("verb", ["replace", "morph"])
def test_post_group_chain_skips_only_terminal_hidden_source(verb, regroup, portrait):
    layout, timeline = grouped_replacement_documents(verb=verb, regroup=regroup, portrait=portrait, chain=True)
    context, replay, camera = consumer_clock(layout, timeline)
    group = next(row["action"] for row in timeline["actions"] if row["action"]["verb"] in {"group", "ungroup"})
    assert "object-z-third" in group["hierarchy_policy"]["changed_object_ids"]
    before_first = replay.before_action("replace-1")
    assert not before_first.object("object-z-third").visible
    assert dict(before_first.state_versions)["object-z-third"] == 2
    capture = replay.before_action("replace-2")
    assert capture.object("object-system").state == "removed"
    assert not capture.object("object-system").visible
    assert capture.object("object-replacement").visible
    assert not capture.object("object-z-third").visible
    assert set(capture.hierarchy.children("board-main", "replacement-pair")) == {
        "object-system", "object-replacement", "object-z-third"}
    order = capture.hierarchy.paint_order(context.objects, "board-main")
    assert order.index("object-system") == order.index("object-replacement") + 1
    assert order.index("object-z-third") == order.index("object-system") + 1
    effective = nonterminal_paint_order(capture, context.objects, "board-main")
    assert abs(effective.index("object-replacement") - effective.index("object-z-third")) == 1
    assert "object-system" not in effective
    end = replay.at(7900)
    assert end.object("object-replacement").state == "removed"
    assert not end.object("object-replacement").visible
    assert end.object("object-z-third").visible
    assert dict(end.state_versions)["object-replacement"] == 4
    assert dict(end.state_versions)["object-z-third"] == 3
    before = v2_svg._rasterize_svg_frame(context.layout, private_svg(context, replay, camera, 7599)).png
    middle = v2_svg._rasterize_svg_frame(context.layout, private_svg(context, replay, camera, 7750)).png
    after = v2_svg._rasterize_svg_frame(context.layout, private_svg(context, replay, camera, 7900)).png
    assert before != middle != after
    assert v2_svg._rasterize_svg_frame(context.layout, private_svg(context, replay, camera, 7750)).png == middle


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("regroup", [False, True])
@pytest.mark.parametrize("verb", ["replace", "morph"])
def test_real_stored_group_replacement_returns_and_duplicates(tmp_path, monkeypatch, verb, regroup, portrait):
    import socket

    service, project, timeline = stored_group_annotation_return_basis(
        tmp_path, regroup=regroup, portrait=portrait,
        document_builder=partial(grouped_replacement_documents, verb=verb, chain=True))
    pid = project["project_id"]
    source = deepcopy(service.source_timeline.get(pid))
    try:
        updated = service.write(pid, "resolved_timeline", timeline, project["revision"])
        assert updated["revision"] == project["revision"] + 1
        originals = {kind: deepcopy(service.artifact(pid, kind)["document"])
                     for kind in ("storyboard", "layout", "resolved_timeline")}
        returned = timeline["actions"][-1]
        return_sample = consumer_clock(originals["layout"], originals["resolved_timeline"])[1].before_action("return-1")
        owned = {obj.object_id: obj for obj in return_sample.objects if obj.board_id == "board-main"}
        assert returned["action"]["expected_object_states"] == {key: obj.state for key, obj in owned.items()}
        assert returned["action"]["expected_object_state_versions"] == {
            key: dict(return_sample.state_versions)[key] for key in owned}
        sampled_basis = completed_hierarchy_basis(HierarchySnapshot(tuple(
            node for node in return_sample.hierarchy.nodes if node.board_id == "board-main")), owned)
        assert returned["return_hierarchy_receipt"]["hierarchy_basis"] == sampled_basis.model_dump(mode="json")
        assert returned["return_hierarchy_receipt"]["hierarchy_basis_sha256"] == sampled_basis.checksum()
        assert returned["action"]["expected_object_states"]["object-system"] == "removed"
        assert returned["action"]["expected_object_states"]["object-replacement"] == "removed"
        assert returned["action"]["expected_object_states"]["object-z-third"] == "visible"
        assert returned["action"]["expected_object_state_versions"]["object-replacement"] == 4
        assert {row["object_id"] for row in returned["return_hierarchy_receipt"]["hierarchy_basis"]["placements"]} == owned.keys()
        duplicate = service.duplicate(pid)
        copied = {kind: service.artifact(duplicate["project_id"], kind)["document"] for kind in originals}
        assert duplicate["project_id"] != pid
        for current, documents in ((updated, originals), (duplicate, copied)):
            current_id = current["project_id"]
            assert all(doc["project_id"] == current_id for doc in documents.values())
            plan, current_layout, resolved_doc = (documents[kind] for kind in ("storyboard", "layout", "resolved_timeline"))
            current_source = service.source_timeline.get(current_id)
            actual_authority = describe(service, current_id)
            media = actual_authority["timing_authority"]["media"]
            authority = plan["narrative_authority"]
            assert authority["mode"] == "approved_script_plus_recording"
            assert authority["authority_id"] == f"script-revision-{actual_authority['semantic_structure']['revision']}"
            assert authority["timing_media_id"] == media["media_id"]
            assert authority["timing_media_sha256"] == media["sha256"]
            assert media["revision"] == describe(service, pid)["timing_authority"]["media"]["revision"]
            assert resolved_doc["plan_revision"] == current_layout["plan_revision"] == service.artifact(current_id, "storyboard")["revision"]
            assert resolved_doc["layout_revision"] == service.artifact(current_id, "layout")["revision"]
            assert resolved_doc["plan_id"] == current_layout["plan_id"] == plan["plan_id"]
            assert resolved_doc["layout_id"] == current_layout["layout_id"]
            assert resolved_doc["output_profile"] == current_layout["output_profile"] == plan["output_profile"]
            assert resolved_doc["output_profile"]["profile_id"] == current["profile"]
            assert resolved_doc["cleaned_timeline_revision"] == authority["cleaned_timeline_revision"] == current_source["timeline_revision"]
            assert resolved_doc["cleaned_timeline_fingerprint"] == authority["cleaned_timeline_fingerprint"] == digest(current_source["document"])
            assert current_layout["plan_sha256"] == resolved_doc["plan_sha256"] == digest(plan)
            assert resolved_doc["layout_sha256"] == digest(current_layout)
            assert resolved_doc["compilation_fingerprint"] == _resolved_compilation_fingerprint(resolved_doc)
            assert current_source["document"] == source["document"]
        assert copied["resolved_timeline"]["actions"] == originals["resolved_timeline"]["actions"]
        assert copied["resolved_timeline"]["plan_sha256"] == digest(copied["storyboard"])
        assert copied["resolved_timeline"]["layout_sha256"] == digest(copied["layout"])
        assert copied["resolved_timeline"]["cleaned_timeline_fingerprint"] == digest(
            service.source_timeline.get(duplicate["project_id"])["document"])
        def no_network(*args, **kwargs):
            raise AssertionError("stored replacement must render offline")
        monkeypatch.setattr(socket, "socket", no_network)
        monkeypatch.setattr(socket, "create_connection", no_network)
        pixels = []
        for documents in (originals, copied):
            context, replay, camera = consumer_clock(documents["layout"], documents["resolved_timeline"])
            frames = {at: v2_svg._rasterize_svg_frame(context.layout, private_svg(context, replay, camera, at)).png
                      for at in (6500, 7750, 7999, 8500, 9000)}
            assert frames[7999] == frames[9000] != frames[8500]
            # Two symmetric half-crossfades can legitimately have identical pixels.
            assert frames[6500] != frames[7999] and frames[7750] != frames[7999]
            assert v2_svg._rasterize_svg_frame(context.layout, private_svg(context, replay, camera, 7750)).png == frames[7750]
            pixels.append(frames)
        assert pixels[0] == pixels[1]
        assert service.source_timeline.get(pid) == source
        assert {kind: service.artifact(pid, kind)["document"] for kind in originals} == originals
    finally:
        service.store.close()


@pytest.mark.parametrize("verb", ["replace", "morph"])
@pytest.mark.parametrize("regroup", [False, True])
@pytest.mark.parametrize("intermediate", ["hidden", "visible", "removed"])
def test_group_replacement_adjacency_ignores_only_terminal_hidden_leaf(verb, regroup, intermediate):
    baseline = grouped_replacement_documents(verb=verb, regroup=regroup)
    consumer_clock(*baseline)
    layout, timeline = grouped_replacement_documents(verb=verb, regroup=regroup, intermediate=intermediate)
    if intermediate == "removed":
        _, replay, _ = consumer_clock(layout, timeline)
        assert replay.before_action("replace-1").object("object-rz-intermediate").state == "removed"
    else:
        with pytest.raises(ValueError, match="consecutive nonterminal paint slots"):
            consumer_clock(layout, timeline)


@pytest.mark.parametrize("verb", ["replace", "morph"])
@pytest.mark.parametrize("regroup", [False, True])
def test_group_cannot_overlap_descendant_replacement(verb, regroup):
    layout, timeline = grouped_replacement_documents(verb=verb, regroup=regroup)
    consumer_clock(layout, timeline)
    row = next(row for row in timeline["actions"] if row["action"]["verb"] in {"group", "ungroup"})
    row.update(start_ms=6200, end_ms=7200)
    row["action"]["trigger"] = {"kind": "absolute", "at_ms": 6200}
    row["resolved_trigger"].update(source=row["action"]["trigger"], alignment_anchor_ms=6200, resolved_at_ms=6200)
    timeline["actions"].sort(key=lambda row: row["start_ms"])
    with pytest.raises(ValueError, match="overlaps"):
        consumer_clock(layout, timeline)


@pytest.mark.parametrize("regroup", [False, True])
@pytest.mark.parametrize("channel", ["bounds", "transform"])
def test_post_group_replace_keeps_canonical_local_colocation(regroup, channel):
    layout, timeline = grouped_replacement_documents(regroup=regroup)
    consumer_clock(layout, timeline)
    destination = next(obj for obj in layout["objects"] if obj["object_id"] == "object-replacement")
    if channel == "bounds":
        destination["geometry"]["bounds"]["x"] += 5
    else:
        destination["transform"]["position"]["x"] += 5
        group = next(row["action"] for row in timeline["actions"] if row["action"]["verb"] in {"group", "ungroup"})
        for side in ("source", "destination"):
            next(row for row in group["hierarchy_policy"][f"{side}_basis"]["placements"]
                 if row["object_id"] == destination["object_id"])["local_transform"]["position"]["x"] += 5
        rehash(group)
        timeline["initial_hierarchy_basis"] = deepcopy(group["hierarchy_policy"]["source_basis"])
        timeline["initial_hierarchy_basis_sha256"] = group["hierarchy_policy"]["source_basis_sha256"]
        if regroup:
            layout["initial_empty_group_ownership"][0]["owner_source_basis_sha256"] = group["hierarchy_policy"]["source_basis_sha256"]
    timeline["layout_sha256"] = digest(layout)
    with pytest.raises(ValueError, match="co-located"):
        consumer_clock(layout, timeline)


@pytest.mark.parametrize("verb", ["replace", "morph"])
def test_hidden_destination_cannot_be_a_direct_group_member(verb):
    layout, timeline = grouped_replacement_documents(verb=verb)
    consumer_clock(layout, timeline)
    layout["objects"] = [obj for obj in layout["objects"] if obj["object_id"] != "replacement-pair"]
    layout["boards"][0]["object_ids"].remove("replacement-pair")
    timeline["initial_object_states"] = [row for row in timeline["initial_object_states"]
                                          if row["object_id"] != "replacement-pair"]
    for obj in layout["objects"]:
        if obj["object_id"] in {"object-system", "object-replacement"}:
            obj["parent_id"] = "replacement-shell"
        if obj["object_id"] == "replacement-shell":
            obj["child_ids"] = ["object-system", "object-replacement"]
    objects = {obj.object_id: obj for obj in ExecutableLayoutV2.model_validate(layout).objects}
    before = HierarchySnapshot.from_objects(objects)
    roots = list(before.children("board-main", "replacement-shell"))
    after = HierarchySnapshot(tuple(
        replace(node, parent_id="replacement-outer", sibling_ordinal=1 + roots.index(node.object_id))
        if node.object_id in roots else node for node in before.nodes))
    source = HierarchyBasis(placements=[{"object_id": node.object_id, "board_id": node.board_id,
        "parent_id": node.parent_id, "sibling_ordinal": node.sibling_ordinal,
        "local_transform": objects[node.object_id].transform} for node in before.nodes])
    destination = source.model_dump(mode="json")
    for placement in destination["placements"]:
        if placement["object_id"] in roots:
            placement.update(parent_id="replacement-outer", sibling_ordinal=1 + roots.index(placement["object_id"]))
            placement["local_transform"]["position"]["x"] += 20
            placement["local_transform"]["position"]["y"] += 10
    group = next(row["action"] for row in timeline["actions"] if row["action"]["verb"] == "ungroup")
    group["target_ids"] = roots
    group["hierarchy_policy"].update(member_root_ids=roots, source_basis=source.model_dump(mode="json"),
        destination_basis=destination, changed_object_ids=list(changed_hierarchy_objects(before, after, objects)))
    rehash(group)
    timeline["initial_hierarchy_basis"] = source.model_dump(mode="json")
    timeline["initial_hierarchy_basis_sha256"] = source.checksum()
    timeline["layout_sha256"] = digest(layout)
    with pytest.raises(ValueError, match="fully revealed visible participant chains"):
        consumer_clock(layout, timeline)


@pytest.mark.parametrize("verb", ["replace", "morph"])
@pytest.mark.parametrize("field", ["parent", "ordinal", "transform", "missing-destination", "missing-third"])
def test_coherent_false_post_group_return_hierarchy_rejects_atomically(tmp_path, verb, field):
    service, project, timeline = stored_group_annotation_return_basis(
        tmp_path, regroup=True,
        document_builder=partial(grouped_replacement_documents, verb=verb, chain=True))
    original = deepcopy(service.open(project["project_id"]))
    source = deepcopy(service.source_timeline.get(project["project_id"]))
    try:
        returned = timeline["actions"][-1]["return_hierarchy_receipt"]
        basis = returned["hierarchy_basis"]
        pair = next(row for row in basis["placements"] if row["object_id"] == "replacement-pair")
        if field == "parent":
            pair.update(parent_id="replacement-outer", sibling_ordinal=1)
        elif field == "transform":
            pair["local_transform"]["position"]["x"] += 5
        elif field == "ordinal":
            a, b = (next(row for row in basis["placements"] if row["object_id"] == key)
                    for key in ("object-system", "object-replacement"))
            a["sibling_ordinal"], b["sibling_ordinal"] = b["sibling_ordinal"], a["sibling_ordinal"]
        else:
            key = "object-replacement" if field == "missing-destination" else "object-z-third"
            basis["placements"] = [row for row in basis["placements"] if row["object_id"] != key]
            remaining = sorted((row for row in basis["placements"] if row["parent_id"] == "replacement-pair"),
                               key=lambda row: row["sibling_ordinal"])
            for index, row in enumerate(remaining):
                row["sibling_ordinal"] = index
        returned["hierarchy_basis_sha256"] = HierarchyBasis.model_validate(basis).checksum()
        timeline["compilation_fingerprint"] = _resolved_compilation_fingerprint(timeline)
        with pytest.raises(ProjectError) as failure:
            service.write(project["project_id"], "resolved_timeline", timeline, project["revision"])
        assert failure.value.code == "invalid_artifact"
        assert service.open(project["project_id"]) == original
        assert service.source_timeline.get(project["project_id"]) == source
        with pytest.raises(ProjectError):
            service.artifact(project["project_id"], "resolved_timeline")
    finally:
        service.store.close()


@pytest.mark.parametrize("verb", ["replace", "morph"])
@pytest.mark.parametrize("field", ["states", "state_versions"])
def test_coherent_false_replacement_return_claim_is_atomic(tmp_path, verb, field):
    service, project, timeline = stored_group_annotation_return_basis(
        tmp_path, regroup=True, stale=("object-replacement", field),
        document_builder=partial(grouped_replacement_documents, verb=verb))
    original = deepcopy(service.open(project["project_id"]))
    try:
        with pytest.raises(ProjectError, match="retained board state"):
            service.write(project["project_id"], "resolved_timeline", timeline, project["revision"])
        assert service.open(project["project_id"]) == original
        with pytest.raises(ProjectError):
            service.artifact(project["project_id"], "resolved_timeline")
    finally:
        service.store.close()
