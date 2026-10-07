"""Hierarchy focus keeps protected ancestry and dims each context subtree once."""

import xml.etree.ElementTree as ET
from copy import deepcopy
from dataclasses import replace
from io import BytesIO

import pytest
from PIL import Image
from test_v2_group_annotation import consumer_clock, private_svg
from test_v2_group_annotation_project import stored_group_annotation_return_basis
from test_v2_group_hierarchy import grouped_documents
from test_v2_group_replacement import grouped_replacement_documents
from test_v2_mask_contract import masked_documents
from v2_fixtures import digest

from atme.narrative_source import describe
from atme.project_service import ProjectError, _resolved_compilation_fingerprint
from atme.render import v2_svg
from atme.render.v2_hierarchy import HierarchySnapshot
from atme.render.v2_hierarchy_replay import completed_hierarchy_basis
from atme.render.v2_isolation import UnsupportedIsolation, isolation_context_roots
from atme.render.v2_state import UnsupportedVisualAction, V2FrameError, evaluate_frame
from atme.store.contracts_v2 import TargetAction


def nested_isolate_documents(*, focus="object-system", mask=False):
    layout, timeline = masked_documents()[1:] if mask else grouped_documents()
    target = layout["objects"][2]
    target.update(initial_state="visible", visible=True)
    timeline["initial_object_states"][2].update(state="visible", visible=True)
    timeline["actions"][2]["action"].update(verb="isolate", target_ids=[focus],
        expected_state="visible", post_state="visible", easing="linear")
    group = next(obj for obj in layout["objects"] if obj["object_id"] == "object-group")
    group.update(parent_id="isolate-outer", opacity=.8)
    group["transform"].update(position={"x": 15, "y": 10}, scale_x=.95,
                              scale_y=1.05, rotation_degrees=3, origin={"x": 0, "y": 0})
    outer = deepcopy(group)
    outer.update(object_id="isolate-outer", parent_id=None, child_ids=["object-group"], opacity=.7)
    if mask:
        source = next(obj for obj in layout["objects"] if obj["object_id"] == "mask-source")
        source["parent_id"] = "isolate-outer"
        outer["child_ids"].append("mask-source")
        outer["object_type"] = "group"
        for key in ("mask_mode", "mask_source_object_id", "mask_coordinate_space", "invert", "feather_px"):
            outer.pop(key)
    outer["transform"].update(position={"x": 25, "y": 20}, scale_x=1,
                              scale_y=1, rotation_degrees=-2)
    layout["objects"].append(outer)
    layout["boards"][0]["object_ids"].append("isolate-outer")
    layout["boards"][0]["density_limit"] = len(layout["objects"])
    timeline["initial_object_states"].append({"object_id": "isolate-outer", "state": "visible",
                                               "visible": True, "state_version": 1})
    timeline["layout_sha256"] = digest(layout)
    return layout, timeline


@pytest.mark.parametrize("mask", [False, True])
@pytest.mark.parametrize("focus", ["object-system", "object-evidence"])
def test_nested_isolate_protects_focus_and_dims_maximal_context_once(mask, focus):
    layout, timeline = nested_isolate_documents(focus=focus, mask=mask)
    original = deepcopy((layout, timeline))
    before = evaluate_frame(layout, timeline, 3999)
    middle = evaluate_frame(layout, timeline, 4450)
    after = evaluate_frame(layout, timeline, 4900)
    assert middle.object(focus) == before.object(focus)
    if focus == "object-system":
        assert middle.object("object-group").opacity == .8
        assert middle.object("isolate-outer").opacity == .7
        assert middle.object("object-label").opacity == pytest.approx(.35)
        assert middle.object("object-evidence").opacity == pytest.approx(.35)
    else:
        assert middle.object("isolate-outer").opacity == pytest.approx(.7 * .35)
        assert middle.object("object-group").opacity == .8
        assert middle.object("object-label").opacity == 1
        assert middle.object("object-system").opacity == 1
    if mask:
        assert middle.object("mask-source") == before.object("mask-source")
    assert after.objects == before.objects
    assert evaluate_frame(layout, timeline, 4450) == middle
    assert (layout, timeline) == original


def post_group_isolate_documents(*, regroup=False, portrait=False):
    layout, timeline = grouped_replacement_documents(regroup=regroup, portrait=portrait)
    row = next(item for item in timeline["actions"] if item["action"]["verb"] == "replace")
    action = row["action"]
    for key in ("from_object_id", "to_object_id", "replace_policy", "morph_policy"):
        action.pop(key, None)
    action.update(verb="isolate", target_ids=["object-system"], expected_state="visible",
                  post_state="visible", easing="linear")
    row["action"] = TargetAction.model_validate(action).model_dump(mode="json")
    timeline["layout_sha256"] = digest(layout)
    return layout, timeline


@pytest.mark.parametrize("regroup", [False, True])
@pytest.mark.parametrize("portrait", [False, True])
def test_post_group_isolate_captures_actual_parentage_and_restores_context(regroup, portrait):
    layout, timeline = post_group_isolate_documents(regroup=regroup, portrait=portrait)
    original = deepcopy((layout, timeline))
    context, replay, camera = consumer_clock(layout, timeline)
    before, middle, after = (replay.at(time) for time in (5999, 6500, 7000))
    focus = "object-system"
    assert before.hierarchy == middle.hierarchy == after.hierarchy
    assert middle.object(focus) == before.object(focus)
    for parent in before.hierarchy.ancestors(focus):
        assert middle.object(parent) == before.object(parent)
    assert middle.object("object-label").opacity == pytest.approx(.35)
    assert middle.object("object-replacement") == before.object("object-replacement")
    assert after.objects == before.objects
    before_versions, after_versions = dict(before.state_versions), dict(after.state_versions)
    assert after_versions == {key: value + (key == focus) for key, value in before_versions.items()}
    svg = private_svg(context, replay, camera, 6500)
    nodes = {node.attrib["data-object-id"]: node for node in ET.fromstring(svg.svg).iter()
             if "data-object-id" in node.attrib}
    assert float(nodes[focus].attrib["opacity"]) == 1
    assert float(nodes["object-label"].attrib["opacity"]) == pytest.approx(.35)
    assert private_svg(context, replay, camera, 7000).svg == private_svg(context, replay, camera, 5999).svg
    assert replay.at(6500) == middle
    assert (layout, timeline) == original


@pytest.mark.parametrize("mask", [False, True])
@pytest.mark.parametrize("parent", ["object-group", "isolate-outer"])
@pytest.mark.parametrize("change", ["hidden", "transparent"])
def test_isolate_rejects_focus_with_unavailable_ancestor(mask, parent, change):
    layout, timeline = nested_isolate_documents(mask=mask)
    obj = next(obj for obj in layout["objects"] if obj["object_id"] == parent)
    if change == "hidden":
        obj.update(visible=False, initial_state="hidden")
        next(row for row in timeline["initial_object_states"] if row["object_id"] == parent).update(
            visible=False, state="hidden")
    else:
        obj["opacity"] = 0
    timeline["layout_sha256"] = digest(layout)
    with pytest.raises(V2FrameError, match="visible focus content and parents"):
        evaluate_frame(layout, timeline, 0)


@pytest.mark.parametrize("mask", [False, True])
def test_containers_and_mask_source_alone_are_not_secondary_paint(mask):
    layout, timeline = nested_isolate_documents(mask=mask)
    timeline["actions"][2]["action"]["target_ids"] = ["object-system", "object-label", "object-evidence"]
    with pytest.raises(V2FrameError, match="visible secondary context"):
        evaluate_frame(layout, timeline, 0)


@pytest.mark.parametrize("mask", [False, True])
def test_repeated_nested_isolates_restore_exact_authored_alpha_and_versions(mask):
    layout, timeline = nested_isolate_documents(mask=mask)
    row = deepcopy(timeline["actions"][2])
    row["action"].update(action_id="isolate-repeat", trigger={"kind": "absolute", "at_ms": 6000})
    row.update(start_ms=6000, end_ms=6900)
    row["resolved_trigger"].update(source=row["action"]["trigger"], alignment_anchor_ms=6000, resolved_at_ms=6000,
                                     matched_text=None, matched_occurrence=None)
    timeline["actions"].append(row)
    timeline["coverage"][2]["action_ids"].append("isolate-repeat")
    context, replay, _ = consumer_clock(layout, timeline)
    before, second, after = (replay.at(time) for time in (3999, 6450, 6900))
    assert second.object("object-group").opacity == .8
    assert second.object("isolate-outer").opacity == .7
    assert second.object("object-label").opacity == pytest.approx(.35)
    assert after.objects == before.objects
    assert dict(after.state_versions) == {
        key: value + 2 * (key == "object-system") for key, value in before.state_versions}
    assert context.layout.objects


@pytest.mark.parametrize("before_group", [False, True])
@pytest.mark.parametrize("regroup", [False, True])
def test_isolate_and_group_share_exact_completion_start_boundary(before_group, regroup):
    layout, timeline = post_group_isolate_documents(regroup=regroup)
    row = next(row for row in timeline["actions"] if row["action"]["verb"] == "isolate")
    start, end = (3000, 4000) if before_group else (5000, 6000)
    row["action"]["trigger"] = {"kind": "absolute", "at_ms": start}
    row.update(start_ms=start, end_ms=end)
    row["resolved_trigger"].update(source=row["action"]["trigger"], alignment_anchor_ms=start, resolved_at_ms=start)
    timeline["actions"].sort(key=lambda row: row["start_ms"])
    _, replay, _ = consumer_clock(layout, timeline)
    capture = replay.before_action(row["action"]["action_id"])
    assert ("replacement-shell" in capture.hierarchy.ancestors("object-system")) is (
        not regroup if before_group else regroup)
    assert replay.at(end).object("object-label").opacity == 1
    assert dict(replay.at(end).state_versions)["object-system"] == (3 if before_group else 4)


@pytest.mark.parametrize("regroup", [False, True])
def test_isolate_still_rejects_partial_group_overlap(regroup):
    layout, timeline = post_group_isolate_documents(regroup=regroup)
    row = next(row for row in timeline["actions"] if row["action"]["verb"] == "isolate")
    row.update(start_ms=4950, end_ms=5950)
    row["action"]["trigger"] = {"kind": "absolute", "at_ms": 4950}
    row["resolved_trigger"].update(source=row["action"]["trigger"], alignment_anchor_ms=4950, resolved_at_ms=4950)
    with pytest.raises(V2FrameError, match="overlaps"):
        consumer_clock(layout, timeline)


@pytest.mark.parametrize("mask", [False, True])
def test_multifocus_preserves_partial_alpha_and_dims_only_outside_context(mask):
    layout, timeline = nested_isolate_documents(mask=mask)
    next(obj for obj in layout["objects"] if obj["object_id"] == "object-label")["opacity"] = .6
    timeline["actions"][2]["action"]["target_ids"] = ["object-system", "object-label"]
    timeline["layout_sha256"] = digest(layout)
    before, middle, after = (evaluate_frame(layout, timeline, at) for at in (3999, 4450, 4900))
    for key in ("object-system", "object-label", "object-group", "isolate-outer"):
        assert middle.object(key) == before.object(key)
    assert middle.object("object-evidence").opacity == pytest.approx(.35)
    assert after.objects == before.objects


@pytest.mark.parametrize("mask", [False, True])
def test_mixed_container_scales_context_child_alpha_exactly_once(mask):
    layout, timeline = nested_isolate_documents(mask=mask)
    next(obj for obj in layout["objects"] if obj["object_id"] == "object-label")["opacity"] = .6
    timeline["layout_sha256"] = digest(layout)
    context, replay, _ = consumer_clock(layout, timeline)
    action = context.timeline.actions[2].action
    sample = replay.before_action(action.action_id)
    roots = isolation_context_roots(context.objects, sample.hierarchy,
        {obj.object_id: obj for obj in sample.objects}, action)
    assert set(roots) == {"object-label", "object-evidence"}
    assert replay.at(4450).object("object-label").opacity == pytest.approx(.6 * .35)
    assert replay.at(4900).object("object-label").opacity == .6
    captures = [capture for checkpoint in replay.checkpoints if checkpoint.at_ms == 4000
                for capture in checkpoint.active if capture.resolved.action.action_id == action.action_id]
    assert len(captures) == 1 and captures[0].context_root_ids == roots
    if mask:
        assert "mask-source" not in roots
        assert replay.at(4450).object("mask-source") == sample.object("mask-source")


@pytest.mark.parametrize("field,value", [("visible", False), ("opacity", 0), ("reveal_fraction", .5)])
def test_planner_independently_rejects_unready_focus_mask_source(field, value):
    layout, timeline = nested_isolate_documents(mask=True)
    context, replay, _ = consumer_clock(layout, timeline)
    action = context.timeline.actions[2].action
    sample = replay.before_action(action.action_id)
    frames = {obj.object_id: obj for obj in sample.objects}
    frames["mask-source"] = replace(frames["mask-source"], **{field: value})
    with pytest.raises(UnsupportedIsolation, match="visible focus aperture"):
        isolation_context_roots(context.objects, sample.hierarchy, frames, action)


@pytest.mark.parametrize("regroup", [False, True])
def test_post_group_empty_shell_and_hidden_destination_are_not_secondary_context(regroup):
    layout, timeline = post_group_isolate_documents(regroup=regroup)
    next(row["action"] for row in timeline["actions"] if row["action"]["verb"] == "isolate")["target_ids"] = [
        "object-system", "object-label", "object-evidence"]
    with pytest.raises(V2FrameError, match="visible secondary context"):
        consumer_clock(layout, timeline)


@pytest.mark.parametrize("regroup", [False, True])
@pytest.mark.parametrize("portrait", [False, True])
def test_real_stored_isolate_return_and_duplicate_restore_exact_context(tmp_path, monkeypatch, regroup, portrait):
    import socket

    service, project, timeline = stored_group_annotation_return_basis(
        tmp_path, regroup=regroup, portrait=portrait, document_builder=post_group_isolate_documents)
    pid = project["project_id"]
    source = deepcopy(service.source_timeline.get(pid))
    try:
        updated = service.write(pid, "resolved_timeline", timeline, project["revision"])
        originals = {kind: deepcopy(service.artifact(pid, kind)["document"])
                     for kind in ("storyboard", "layout", "resolved_timeline")}
        context, replay, camera = consumer_clock(originals["layout"], originals["resolved_timeline"])
        before, returned = replay.at(7999), replay.before_action("return-1")
        owned = {obj.object_id: obj for obj in returned.objects if obj.board_id == "board-main"}
        receipt = timeline["actions"][-1]
        assert receipt["action"]["expected_object_states"] == {key: obj.state for key, obj in owned.items()}
        assert receipt["action"]["expected_object_state_versions"] == {
            key: dict(returned.state_versions)[key] for key in owned}
        basis = completed_hierarchy_basis(HierarchySnapshot(tuple(
            node for node in returned.hierarchy.nodes if node.board_id == "board-main")), owned)
        assert receipt["return_hierarchy_receipt"]["hierarchy_basis"] == basis.model_dump(mode="json")
        assert receipt["return_hierarchy_receipt"]["hierarchy_basis_sha256"] == basis.checksum()
        assert {key: obj for key, obj in owned.items()} == {
            obj.object_id: obj for obj in before.objects if obj.board_id == "board-main"}
        capture = replay.before_action("replace-1")
        complete = replay.at(7000)
        assert complete.objects == capture.objects
        assert dict(complete.state_versions) == {
            key: value + (key == "object-system") for key, value in capture.state_versions}
        duplicate = service.duplicate(pid)
        copied = {kind: service.artifact(duplicate["project_id"], kind)["document"] for kind in originals}
        assert duplicate["project_id"] != pid
        assert copied["resolved_timeline"]["actions"] == originals["resolved_timeline"]["actions"]
        for current, documents in ((updated, originals), (duplicate, copied)):
            plan, layout_doc, resolved_doc = (documents[kind] for kind in ("storyboard", "layout", "resolved_timeline"))
            current_id = current["project_id"]
            assert all(doc["project_id"] == current_id for doc in documents.values())
            current_source = service.source_timeline.get(current_id)
            actual_authority = describe(service, current_id)
            media = actual_authority["timing_authority"]["media"]
            authority = plan["narrative_authority"]
            assert authority["mode"] == "approved_script_plus_recording"
            assert authority["authority_id"] == f"script-revision-{actual_authority['semantic_structure']['revision']}"
            assert authority["timing_media_id"] == media["media_id"]
            assert authority["timing_media_sha256"] == media["sha256"]
            assert media["revision"] == describe(service, pid)["timing_authority"]["media"]["revision"]
            assert resolved_doc["plan_revision"] == layout_doc["plan_revision"] == service.artifact(current_id, "storyboard")["revision"]
            assert resolved_doc["layout_revision"] == service.artifact(current_id, "layout")["revision"]
            assert resolved_doc["plan_id"] == layout_doc["plan_id"] == plan["plan_id"]
            assert resolved_doc["layout_id"] == layout_doc["layout_id"]
            assert resolved_doc["output_profile"] == layout_doc["output_profile"] == plan["output_profile"]
            assert resolved_doc["output_profile"]["profile_id"] == current["profile"]
            assert resolved_doc["cleaned_timeline_revision"] == authority["cleaned_timeline_revision"] == current_source["timeline_revision"]
            assert resolved_doc["cleaned_timeline_fingerprint"] == authority["cleaned_timeline_fingerprint"] == digest(current_source["document"])
            assert resolved_doc["compilation_fingerprint"] == _resolved_compilation_fingerprint(resolved_doc)
            assert current_source["document"] == source["document"]
            assert layout_doc["plan_sha256"] == resolved_doc["plan_sha256"] == digest(plan)
            assert resolved_doc["layout_sha256"] == digest(layout_doc)
            assert resolved_doc["cleaned_timeline_fingerprint"] == digest(
                service.source_timeline.get(current["project_id"])["document"])
        copied_context, copied_replay, copied_camera = consumer_clock(copied["layout"], copied["resolved_timeline"])
        monkeypatch.setattr(socket, "socket", lambda *args, **kwargs: pytest.fail("isolate render used network"))
        monkeypatch.setattr(socket, "create_connection", lambda *args, **kwargs: pytest.fail("isolate render used network"))
        pixels = {}
        for at in (5999, 6500, 7000, 7999, 8500, 9000):
            raw = v2_svg._rasterize_svg_frame(context.layout, private_svg(context, replay, camera, at)).png
            assert v2_svg._rasterize_svg_frame(copied_context.layout,
                private_svg(copied_context, copied_replay, copied_camera, at)).png == raw
            assert Image.open(BytesIO(raw)).size == ((720, 1280) if portrait else (1280, 720))
            pixels[at] = raw
        assert pixels[5999] == pixels[7000] == pixels[7999] == pixels[9000]
        assert pixels[6500] != pixels[7000] != pixels[8500]
        assert v2_svg._rasterize_svg_frame(context.layout, private_svg(context, replay, camera, 6500)).png == pixels[6500]
        with pytest.raises(UnsupportedVisualAction):
            v2_svg.compose_png_frame(originals["layout"], originals["resolved_timeline"], 6500)
        assert service.source_timeline.get(pid) == source
        assert {kind: service.artifact(pid, kind)["document"] for kind in originals} == originals
    finally:
        service.store.close()


@pytest.mark.parametrize("field,key", [("states", "object-system"), ("state_versions", "object-label")])
@pytest.mark.parametrize("regroup", [False, True])
def test_stale_stored_isolate_return_rejects_atomically(tmp_path, regroup, field, key):
    service, project, timeline = stored_group_annotation_return_basis(
        tmp_path, regroup=regroup, stale=(key, field), document_builder=post_group_isolate_documents)
    try:
        source = deepcopy(service.source_timeline.get(project["project_id"]))
        with pytest.raises(ProjectError) as rejected:
            service.write(project["project_id"], "resolved_timeline", timeline, project["revision"])
        assert rejected.value.code == "invalid_artifact"
        assert service.open(project["project_id"])["revision"] == project["revision"]
        assert "resolved_timeline" not in service.open(project["project_id"])["artifacts"]
        assert service.source_timeline.get(project["project_id"]) == source
    finally:
        service.store.close()
