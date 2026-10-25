"""Cross-board retained pointers and nested apertures preserve focus authority."""

import xml.etree.ElementTree as ET
from copy import deepcopy

import pytest
from test_v2_annotation_action import append_target
from test_v2_annotation_contract import leader_documents
from test_v2_group_annotation import (
    annotation_group_documents,
    consumer_clock,
    private_svg,
)
from test_v2_hierarchy_contract import rehash
from test_v2_hierarchy_isolate import nested_isolate_documents
from test_v2_mask_contract import MASK_FIELDS
from v2_fixtures import digest

from atme.render import v2_svg
from atme.render.v2_hierarchy import HierarchySnapshot
from atme.store.contracts_v2 import ExecutableLayoutV2, HierarchyBasis


@pytest.mark.parametrize("post_group", [False, True])
def test_retained_a_pointer_does_not_reserve_later_b_isolation(post_group):
    layout, timeline = annotation_group_documents(nested=True) if post_group else leader_documents()[1:]
    new_objects = []
    for key, x in (("b-focus", 180), ("b-context", 700)):
        obj = deepcopy(layout["objects"][2])
        obj.update(object_id=key, board_id="board-interlude", parent_id=None,
                   visible=True, initial_state="visible", z_index=len(new_objects))
        obj["geometry"]["bounds"] = {"x": x, "y": 180, "width": 240, "height": 180}
        new_objects.append(obj)
        timeline["initial_object_states"].append({"object_id": key, "state": "visible",
                                                   "visible": True, "state_version": 1})
    layout["objects"].extend(new_objects)
    board = deepcopy(layout["boards"][0])
    board.update(board_id="board-interlude", object_ids=[obj["object_id"] for obj in new_objects], density_limit=2)
    layout["boards"].append(board)
    layout["activations"][0]["end_ms"] = 8000
    layout["activations"].append({"activation_id": "activation-interlude", "board_id": "board-interlude",
                                  "start_ms": 8000, "end_ms": 10000, "reason": "Review the independent second board"})
    if post_group:
        objects = {obj.object_id: obj for obj in ExecutableLayoutV2.model_validate(layout).objects}
        hierarchy = HierarchySnapshot.from_objects(objects)
        placements = [{"object_id": node.object_id, "board_id": node.board_id, "parent_id": node.parent_id,
                       "sibling_ordinal": node.sibling_ordinal, "local_transform": objects[node.object_id].transform}
                      for node in hierarchy.nodes if node.board_id == "board-interlude"]
        group = next(row["action"] for row in timeline["actions"] if row["action"]["verb"] == "ungroup")
        for side in ("source", "destination"):
            group["hierarchy_policy"][f"{side}_basis"]["placements"].extend(deepcopy(placements))
            group["hierarchy_policy"][f"{side}_basis"]["placements"].sort(key=lambda row: row["object_id"])
        rehash(group)
        timeline["initial_hierarchy_basis"] = deepcopy(group["hierarchy_policy"]["source_basis"])
        timeline["initial_hierarchy_basis_sha256"] = HierarchyBasis.model_validate(
            timeline["initial_hierarchy_basis"]).checksum()
    append_target(timeline, "b-focus", "isolate", 8200, 8700)
    next(row["action"] for row in timeline["actions"]
         if row["action"]["action_id"] == "isolate-b-focus")["board_id"] = "board-interlude"
    timeline["layout_sha256"] = digest(layout)
    original = deepcopy((layout, timeline))
    context, replay, camera = consumer_clock(layout, timeline)
    before, middle, after = (replay.at(at) for at in (7999, 8450, 8700))
    for at in (8200, 8450, 8700, 9999):
        sample = replay.at(at)
        assert {obj.object_id: obj for obj in sample.objects if obj.board_id == "board-main"} == {
            obj.object_id: obj for obj in before.objects if obj.board_id == "board-main"}
        assert {key: value for key, value in sample.state_versions if key not in {"b-focus", "b-context"}} == {
            key: value for key, value in before.state_versions if key not in {"b-focus", "b-context"}}
    assert middle.object("annotation-leader").visible
    assert middle.object("b-focus") == before.object("b-focus")
    assert middle.object("b-context").opacity == pytest.approx(.35)
    assert after.object("b-context") == before.object("b-context")
    assert dict(after.state_versions)["b-focus"] == 2
    assert dict(after.state_versions)["b-context"] == 1
    svg = private_svg(context, replay, camera, 8450).svg
    assert 'data-object-id="b-focus"' in svg and 'data-object-id="annotation-leader"' not in svg
    assert (layout, timeline) == original


def test_nested_focus_masks_protect_both_aperture_sources_and_all_ancestry():
    layout, timeline = nested_isolate_documents(mask=True)
    outer = next(obj for obj in layout["objects"] if obj["object_id"] == "isolate-outer")
    outer.update(object_type="mask", **MASK_FIELDS)
    outer["mask_source_object_id"] = "outer-mask-source"
    source = deepcopy(next(obj for obj in layout["objects"] if obj["object_id"] == "mask-source"))
    source.update(object_id="outer-mask-source", parent_id=None)
    source["geometry"]["bounds"] = {"x": 0, "y": 0, "width": 1280, "height": 720}
    source["transform"]["position"] = {"x": 0, "y": 0}
    layout["objects"].append(source)
    layout["boards"][0]["object_ids"].append(source["object_id"])
    layout["boards"][0]["density_limit"] = len(layout["objects"])
    timeline["initial_object_states"].append({"object_id": source["object_id"], "state": "visible",
                                               "visible": True, "state_version": 1})
    timeline["layout_sha256"] = digest(layout)
    original = deepcopy((layout, timeline))
    _, replay, _ = consumer_clock(layout, timeline)
    before, middle, after = (replay.at(at) for at in (3999, 4450, 4900))
    for key in ("object-system", "object-group", "isolate-outer", "mask-source", "outer-mask-source"):
        assert middle.object(key) == before.object(key)
    assert middle.object("object-evidence").opacity == pytest.approx(.35)
    assert middle.object("object-label").opacity == pytest.approx(.35)
    assert after.objects == before.objects
    root = ET.fromstring(v2_svg.compose_svg_frame(layout, timeline, 4450).svg)
    assert len([node for node in root.iter() if node.tag.endswith("mask")]) == 2
    assert all(node.attrib.get("data-object-id") not in {"mask-source", "outer-mask-source"}
               for node in root.iter())
    pixels = {at: v2_svg.compose_png_frame(layout, timeline, at).png for at in (3999, 4450, 4900)}
    assert pixels[3999] == pixels[4900] != pixels[4450]
    assert v2_svg.compose_png_frame(layout, timeline, 4450).png == pixels[4450]
    assert (layout, timeline) == original
