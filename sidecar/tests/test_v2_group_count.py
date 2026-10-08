"""Stored Count preserves exact numbers and display through authored hierarchy."""

import socket
import xml.etree.ElementTree as ET
from copy import deepcopy
from dataclasses import dataclass, fields
from io import BytesIO

import pytest
from PIL import Image
from test_v2_count_contract import count_action, count_policy
from test_v2_group_annotation import consumer_clock, private_svg
from test_v2_group_annotation_project import stored_group_annotation_return_basis
from test_v2_group_replacement import grouped_replacement_documents
from v2_fixtures import digest

from atme.narrative_source import describe
from atme.project_service import ProjectError, _resolved_compilation_fingerprint
from atme.render import v2_svg
from atme.render.v2_count import MAX_COUNT_DENOMINATOR
from atme.render.v2_hierarchy import HierarchySnapshot, UnsupportedHierarchy
from atme.render.v2_hierarchy_replay import completed_hierarchy_basis
from atme.render.v2_state import (
    CountFrameObject,
    FrameObject,
    UnsupportedVisualAction,
    V2FrameError,
)


def group_count_documents(*, regroup=False, portrait=False):
    layout, timeline = grouped_replacement_documents(regroup=regroup, portrait=portrait)
    source = next(obj for obj in layout["objects"] if obj["object_id"] == "object-system")
    source.pop("path_data", None)
    policy = count_policy(text_object_id="object-system")
    source.update(object_type="text", text=policy["start_text"], items=[],
                  style={"stroke": None, "fill": None, "text": "text.body", "effect": None})
    source["geometry"].update(points=[], corner_radius=None)
    row = next(row for row in timeline["actions"] if row["action"]["verb"] == "replace")
    previous = row["action"]
    action = count_action(policy)
    for key in ("action_id", "source_instruction_id", "board_id", "coverage_id", "fallback", "trigger"):
        action[key] = deepcopy(previous[key])
    action["target_ids"] = [source["object_id"]]
    row["action"] = action
    second = deepcopy(row)
    second["action"].update(action_id="count-2", trigger={"kind": "absolute", "at_ms": 7000},
        count_policy=count_policy(text_object_id="object-system", start_value="10.0", end_value="20",
                                  start_text="10 widgets", end_text="20 widgets"))
    second.update(start_ms=7000, end_ms=7900)
    second["resolved_trigger"].update(source=second["action"]["trigger"], alignment_anchor_ms=7000,
                                      resolved_at_ms=7000, matched_text=None, matched_occurrence=None)
    timeline["actions"].append(second)
    timeline["coverage"][0]["action_ids"].append("count-2")
    timeline["layout_sha256"] = digest(layout)
    return layout, timeline


@pytest.mark.parametrize("regroup", [False, True])
@pytest.mark.parametrize("portrait", [False, True])
def test_count_after_group_has_exact_captured_pose_numeric_versions_and_pixels(regroup, portrait, monkeypatch):
    layout, timeline = group_count_documents(regroup=regroup, portrait=portrait)
    original = deepcopy((layout, timeline))
    context, replay, camera = consumer_clock(layout, timeline)
    before = replay.before_action("replace-1")
    assert not isinstance(before.object("object-system"), CountFrameObject)
    middle, complete = replay.at(6500), replay.at(7900)
    assert middle.object("object-system").display_text == "5 widgets"
    assert middle.object("object-system").count_value == (5, 1)
    assert complete.object("object-system").display_text == "20 widgets"
    assert complete.object("object-system").count_value == (20, 1)
    for key in ("object-system", *before.hierarchy.ancestors("object-system")):
        assert complete.object(key).transform == before.object(key).transform
    assert dict(complete.state_versions) == {
        key: version + 2 * (key == "object-system") for key, version in before.state_versions}
    assert complete.hierarchy == before.hierarchy
    root = ET.fromstring(private_svg(context, replay, camera, 7900).svg)
    node = root.find(".//{*}g[@data-object-id='object-system']")
    assert "20 widgets" in "".join(node.itertext())
    monkeypatch.setattr(socket, "socket", lambda *a, **kw: pytest.fail("Count attempted network access"))
    monkeypatch.setattr(socket, "create_connection", lambda *a, **kw: pytest.fail("Count attempted network access"))
    pixels = {at: v2_svg._rasterize_svg_frame(context.layout, private_svg(context, replay, camera, at)).png
              for at in (5999, 6500, 7000, 7450, 7900)}
    assert len(set(pixels.values())) == 5
    assert Image.open(BytesIO(pixels[7900])).size == ((720, 1280) if portrait else (1280, 720))
    for at in (7450, 5999, 7900, 6500):
        assert v2_svg._rasterize_svg_frame(context.layout, private_svg(context, replay, camera, at)).png == pixels[at]
    with pytest.raises(UnsupportedVisualAction):
        v2_svg.compose_png_frame(layout, timeline, 7900)
    assert (layout, timeline) == original


@pytest.mark.parametrize("regroup", [False, True])
@pytest.mark.parametrize("portrait", [False, True])
def test_real_stored_count_return_and_duplicate_rebind_exact_authority(tmp_path, monkeypatch, regroup, portrait):
    service, project, timeline = stored_group_annotation_return_basis(
        tmp_path, regroup=regroup, portrait=portrait, document_builder=group_count_documents)
    pid = project["project_id"]
    source = deepcopy(service.source_timeline.get(pid))
    try:
        updated = service.write(pid, "resolved_timeline", timeline, project["revision"])
        original = {kind: deepcopy(service.artifact(pid, kind)["document"])
                    for kind in ("storyboard", "layout", "resolved_timeline")}
        duplicate = service.duplicate(pid)
        copied = {kind: service.artifact(duplicate["project_id"], kind)["document"] for kind in original}
        assert duplicate["project_id"] != pid
        assert copied["resolved_timeline"]["actions"] == original["resolved_timeline"]["actions"]
        pixels = []
        monkeypatch.setattr(socket, "socket", lambda *a, **kw: pytest.fail("stored Count attempted network"))
        monkeypatch.setattr(socket, "create_connection", lambda *a, **kw: pytest.fail("stored Count attempted network"))
        for current, documents in ((updated, original), (duplicate, copied)):
            current_id = current["project_id"]
            plan, layout_doc, resolved = (documents[k] for k in ("storyboard", "layout", "resolved_timeline"))
            authority = describe(service, current_id)
            media = authority["timing_authority"]["media"]
            narrative = plan["narrative_authority"]
            cleaned = service.source_timeline.get(current_id)
            assert all(doc["project_id"] == current_id for doc in documents.values())
            assert narrative["mode"] == "approved_script_plus_recording"
            assert narrative["authority_id"] == f"script-revision-{authority['semantic_structure']['revision']}"
            assert narrative["timing_media_id"] == media["media_id"]
            assert narrative["timing_media_sha256"] == media["sha256"]
            assert media["revision"] == describe(service, pid)["timing_authority"]["media"]["revision"]
            assert resolved["plan_revision"] == layout_doc["plan_revision"] == service.artifact(current_id, "storyboard")["revision"]
            assert resolved["layout_revision"] == service.artifact(current_id, "layout")["revision"]
            assert resolved["plan_id"] == layout_doc["plan_id"] == plan["plan_id"]
            assert resolved["layout_id"] == layout_doc["layout_id"]
            assert resolved["plan_sha256"] == layout_doc["plan_sha256"] == digest(plan)
            assert resolved["layout_sha256"] == digest(layout_doc)
            assert resolved["output_profile"] == layout_doc["output_profile"] == plan["output_profile"]
            assert resolved["output_profile"]["profile_id"] == current["profile"]
            assert resolved["cleaned_timeline_revision"] == narrative["cleaned_timeline_revision"] == cleaned["timeline_revision"]
            assert resolved["cleaned_timeline_fingerprint"] == narrative["cleaned_timeline_fingerprint"] == digest(cleaned["document"])
            assert resolved["compilation_fingerprint"] == _resolved_compilation_fingerprint(resolved)
            assert cleaned["document"] == source["document"]
            context, replay, camera = consumer_clock(layout_doc, resolved)
            returned = replay.before_action("return-1")
            owned = {obj.object_id: obj for obj in returned.objects if obj.board_id == "board-main"}
            assert owned["object-system"].display_text == "20 widgets"
            assert owned["object-system"].count_value == (20, 1)
            assert owned["object-system"].state == "visible"
            assert dict(returned.state_versions)["object-system"] == 5
            receipt = resolved["actions"][-1]
            assert receipt["action"]["expected_object_states"] == {key: obj.state for key, obj in owned.items()}
            assert receipt["action"]["expected_object_state_versions"] == {
                key: dict(returned.state_versions)[key] for key in owned}
            basis = completed_hierarchy_basis(HierarchySnapshot(tuple(
                node for node in returned.hierarchy.nodes if node.board_id == "board-main")), owned)
            assert receipt["return_hierarchy_receipt"]["hierarchy_basis"] == basis.model_dump(mode="json")
            assert receipt["return_hierarchy_receipt"]["hierarchy_basis_sha256"] == basis.checksum()
            assert replay.at(9000).object("object-system") == returned.object("object-system")
            frames = {at: v2_svg._rasterize_svg_frame(context.layout, private_svg(context, replay, camera, at)).png
                      for at in (6500, 7450, 7999, 8500, 9000)}
            assert frames[7999] == frames[9000] != frames[8500]
            assert frames[6500] != frames[7450] != frames[7999]
            assert v2_svg._rasterize_svg_frame(context.layout, private_svg(context, replay, camera, 6500)).png == frames[6500]
            pixels.append(frames)
        assert pixels[0] == pixels[1]
        assert service.source_timeline.get(pid) == source
        assert {kind: service.artifact(pid, kind)["document"] for kind in original} == original
    finally:
        service.store.close()


@pytest.mark.parametrize("field", ["states", "state_versions"])
def test_stale_count_return_claims_reject_atomically(tmp_path, field):
    service, project, timeline = stored_group_annotation_return_basis(tmp_path, regroup=True,
        stale=("object-system", field), document_builder=group_count_documents)
    before = deepcopy(service.open(project["project_id"]))
    source = deepcopy(service.source_timeline.get(project["project_id"]))
    try:
        with pytest.raises(ProjectError) as rejected:
            service.write(project["project_id"], "resolved_timeline", timeline, project["revision"])
        assert rejected.value.code == "invalid_artifact"
        assert service.open(project["project_id"]) == before
        assert service.source_timeline.get(project["project_id"]) == source
    finally:
        service.store.close()


def test_hierarchy_basis_accepts_only_known_exact_immutable_frame_types():
    @dataclass(frozen=True)
    class UnknownFrame(FrameObject):
        opaque: str = "not a supported frame payload"

    layout, timeline = group_count_documents()
    _, replay, _ = consumer_clock(layout, timeline)
    sample = replay.at(7900)
    frames = {obj.object_id: obj for obj in sample.objects}
    completed_hierarchy_basis(sample.hierarchy, frames)
    before = frames["object-system"]
    frames["object-system"] = UnknownFrame(**{item.name: getattr(before, item.name) for item in fields(FrameObject)})
    with pytest.raises(UnsupportedHierarchy, match="exact immutable frame inventory"):
        completed_hierarchy_basis(sample.hierarchy, frames)


@pytest.mark.parametrize("payload", [("", (1, 1)), ("value", (1, 0)), ("value", (4, 2)),
                                     ("value", (True, 1)), ("value", [1, 1]),
                                     ("\x00", (1, 1)), ("value\t", (1, 1)), ("value\u2028", (1, 1)),
                                     ("value", (1, 10 ** 10000)), ("value", (10 ** 10000, 1)),
                                     ("value", (1, -1))])
def test_count_frame_payload_cannot_be_mutable_or_noncanonical(payload):
    layout, timeline = group_count_documents()
    _, replay, _ = consumer_clock(layout, timeline)
    before = replay.at(7900).object("object-system")
    values = {item.name: getattr(before, item.name) for item in fields(FrameObject)}
    with pytest.raises(V2FrameError):
        CountFrameObject(**values, display_text=payload[0], count_value=payload[1])


def test_count_payload_admits_the_actual_authored_fractional_scale_boundary():
    layout, timeline = group_count_documents()
    _, replay, _ = consumer_clock(layout, timeline)
    sample = replay.at(7900)
    before = sample.object("object-system")
    values = {item.name: getattr(before, item.name) for item in fields(FrameObject)}
    boundary = CountFrameObject(**values, display_text="0", count_value=(1, MAX_COUNT_DENOMINATOR))
    frames = {item.object_id: item for item in sample.objects}
    frames[before.object_id] = boundary
    completed_hierarchy_basis(sample.hierarchy, frames)


@pytest.mark.parametrize("change", ["rounded-next-start", "rounded-prior-end"])
def test_coherently_bound_stored_numeric_discontinuity_rejects_atomically(tmp_path, change):
    def mutate(_layout, timeline):
        if change == "rounded-next-start":
            next(row for row in timeline["actions"] if row["action"]["action_id"] == "count-2")[
                "action"]["count_policy"]["start_value"] = "10.4"
        else:
            next(row for row in timeline["actions"] if row["action"]["action_id"] == "replace-1")[
                "action"]["count_policy"]["end_value"] = "9.6"

    service, project, timeline = stored_group_annotation_return_basis(tmp_path, regroup=True,
        document_builder=group_count_documents, mutate=mutate)
    before = deepcopy(service.open(project["project_id"]))
    source = deepcopy(service.source_timeline.get(project["project_id"]))
    plan = service.artifact(project["project_id"], "storyboard")["document"]
    assert [row["action"] for row in timeline["actions"]] == plan["actions"]
    assert timeline["plan_sha256"] == digest(plan)
    assert timeline["compilation_fingerprint"] == _resolved_compilation_fingerprint(timeline)
    try:
        with pytest.raises(ProjectError) as rejected:
            service.write(project["project_id"], "resolved_timeline", timeline, project["revision"])
        assert rejected.value.code == "invalid_artifact"
        assert "captured numeric value" in rejected.value.detail()["message"]
        assert service.open(project["project_id"]) == before
        assert service.source_timeline.get(project["project_id"]) == source
    finally:
        service.store.close()
