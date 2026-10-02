"""Authored annotation constructs real notes and pointers, not target mutations."""

from __future__ import annotations

import socket
import xml.etree.ElementTree as ET
from copy import deepcopy
from io import BytesIO

import pytest
from PIL import Image
from test_v2_annotation_contract import (
    annotation_documents,
    grouped_annotation_documents,
    leader_documents,
)
from test_v2_camera_action import append_camera
from test_v2_morph_action import morph_documents
from test_v2_resolved_project import stored_v2_basis
from v2_fixtures import digest

from atme.project_service import _resolved_compilation_fingerprint
from atme.render.v2_state import evaluate_frame
from atme.render.v2_svg import compose_png_frame, compose_svg_frame
from atme.store.contracts_v2 import ExecutableLayoutV2, ResolvedVisualTimelineV2


def rebind(layout, timeline):
    timeline["layout_sha256"] = digest(layout)


def append_target(timeline, object_id, verb, start, end, *, opacity=None, destination=None):
    action = deepcopy(timeline["actions"][0])
    action["action"].update(action_id=f"{verb}-{object_id}", target_ids=[object_id], verb=verb,
                             expected_state="visible", post_state="removed" if verb == "exit" else "visible",
                             trigger={"kind": "absolute", "at_ms": start}, easing="linear")
    if opacity is not None:
        action["action"].pop("annotation", None)
        action["action"]["opacity"] = opacity
    if destination is not None:
        action["action"].pop("annotation", None)
        action["action"]["destination"] = destination
    action.update(start_ms=start, end_ms=end)
    action["resolved_trigger"].update(source=action["action"]["trigger"], alignment_anchor_ms=start,
                                      resolved_at_ms=start, matched_text=None, matched_occurrence=None)
    timeline["actions"].append(action)
    timeline["actions"].sort(key=lambda item: item["start_ms"])
    timeline["coverage"][0]["action_ids"].append(action["action"]["action_id"])


def test_note_and_leader_exact_phases_persistence_and_read_only_target():
    _, layout, timeline = leader_documents()
    original = deepcopy((layout, timeline))
    target = evaluate_frame(layout, timeline, 5999).object("object-system")
    for at, note_fraction, pointer_fraction in ((5999, 0, 0), (6000, 0, 0), (6250, .5, 0),
                                               (6500, 1, 0), (6750, 1, .5), (7000, 1, 1),
                                               (7999, 1, 1), (9000, 1, 1)):
        frame = evaluate_frame(layout, timeline, at)
        assert frame.object("object-system") == target
        assert frame.object("annotation-note").reveal_fraction == note_fraction
        assert frame.object("annotation-leader").reveal_fraction == pointer_fraction
        assert frame.object("annotation-note").visible == (note_fraction > 0)
        assert frame.object("annotation-leader").visible == (pointer_fraction > 0)
    assert (layout, timeline) == original


@pytest.mark.parametrize("easing,expected", [("linear", .25), ("ease_in", .0625),
                                              ("ease_out", .4375), ("ease_in_out", .15625)])
def test_annotation_easing_is_local_to_each_authored_phase(easing, expected):
    _, layout, timeline = leader_documents()
    timeline["actions"][-1]["action"]["easing"] = easing
    assert evaluate_frame(layout, timeline, 6125).object("annotation-note").reveal_fraction == expected
    assert evaluate_frame(layout, timeline, 6625).object("annotation-leader").reveal_fraction == expected


def test_write_and_pointer_render_real_pixels_with_no_generic_wipe_or_target_edit():
    _, layout, timeline = leader_documents()
    snapshots = [compose_png_frame(layout, timeline, at).png for at in (5999, 6250, 6500, 6750, 7000)]
    assert len(set(snapshots)) == 5
    prefix = compose_svg_frame(layout, timeline, 6250).svg
    middle = compose_svg_frame(layout, timeline, 6750).svg
    end = compose_svg_frame(layout, timeline, 7000).svg
    assert "A stable" in prefix and "A stable boundary" not in prefix
    assert 'data-object-id="annotation-leader"' not in prefix
    root = ET.fromstring(middle)
    leader = next(n for n in root.iter() if n.attrib.get("data-object-id") == "annotation-leader")
    assert any("stroke-dashoffset" in n.attrib for n in leader.iter())
    assert not any(n.tag.endswith("polygon") for n in leader.iter())
    leader = next(n for n in ET.fromstring(end).iter()
                  if n.attrib.get("data-object-id") == "annotation-leader")
    assert any(n.tag.endswith("polygon") for n in leader.iter())
    assert not any("clip-path" in n.attrib for n in leader.iter())
    for at in (7000, 6100, 7999, 5999, 6750):
        compose_png_frame(layout, timeline, at)
    assert compose_png_frame(layout, timeline, 6750).png == snapshots[3]


def test_draw_annotation_uses_authored_stroke_construction():
    _, layout, timeline = annotation_documents()
    note = layout["objects"][-1]
    for key in ("text", "items", "number_value", "unit"):
        note.pop(key, None)
    note.update(object_type="underline", path_data=None)
    note["style"].update(text=None, stroke="ink.accent")
    timeline["actions"][-1]["action"]["annotation_policy"]["phases"][0]["mode"] = "draw"
    rebind(layout, timeline)
    svg = ET.fromstring(compose_svg_frame(layout, timeline, 6500).svg)
    node = next(n for n in svg.iter() if n.attrib.get("data-object-id") == "annotation-note")
    assert any(n.attrib.get("stroke-dashoffset") for n in node.iter())
    assert compose_png_frame(layout, timeline, 6500).png != compose_png_frame(layout, timeline, 7000).png


@pytest.mark.parametrize("kind", ["camera", "note", "target", "ancestor", "isolate", "replace"])
@pytest.mark.parametrize("start", [6500, 7500])
def test_construction_and_reading_hold_reject_conflicting_actions_before_any_frame(kind, start):
    _, layout, timeline = grouped_annotation_documents() if kind == "ancestor" else annotation_documents()
    if kind == "camera":
        append_camera(timeline, "camera-during", "camera_cut", start, start+100)
    elif kind == "replace":
        other = deepcopy(morph_documents()[1]["actions"][-1])
        other["action"].update(action_id="replacement-during", verb="replace", trigger={"kind": "absolute", "at_ms": start})
        other["action"].pop("morph_policy")
        other.update(start_ms=start, end_ms=start+100)
        other["resolved_trigger"].update(source=other["action"]["trigger"], alignment_anchor_ms=start,
                                         resolved_at_ms=start)
        timeline["actions"].append(other)
        timeline["actions"].sort(key=lambda item: item["start_ms"])
        timeline["coverage"][0]["action_ids"].append(other["action"]["action_id"])
    else:
        target = ("annotation-note" if kind == "note" else "annotation-group"
                  if kind == "ancestor" else "object-system")
        append_target(timeline, target, "isolate" if kind == "isolate" else "fade", start, start+100,
                      opacity=None if kind == "isolate" else .5)
    rebind(layout, timeline)
    with pytest.raises(ValueError, match="uninterrupted construction and hold|isolate.*overlaps"):
        evaluate_frame(layout, timeline, 100)


@pytest.mark.parametrize("change,match", [
    (lambda l,t: l["activations"][0].update(end_ms=7999), "hold outlasts"),
    (lambda l,t: l["objects"][-1]["transform"].update(scale_y=.1), "too small"),
    (lambda l,t: l["objects"][-1]["transform"]["position"].update(x=1000), "outside"),
    (lambda l,t: l["objects"][-1].update(opacity=.01), "opaque"),
    (lambda l,t: l["objects"][0].update(opacity=.01), "opaque"),
])
def test_hold_bounds_readability_and_effective_opacity_fail_before_sampling(change, match):
    _, layout, timeline = annotation_documents()
    change(layout, timeline)
    rebind(layout, timeline)
    with pytest.raises(ValueError, match=match):
        evaluate_frame(layout, timeline, 100)


def test_group_ancestor_visibility_opacity_and_world_pointer_are_effective():
    _, layout, timeline = grouped_annotation_documents(leader=True)
    rebind(layout, timeline)
    assert compose_png_frame(layout, timeline, 6750).png.startswith(b"\x89PNG")
    layout["objects"][-1]["opacity"] = .01
    rebind(layout, timeline)
    with pytest.raises(ValueError, match="opaque"):
        evaluate_frame(layout, timeline, 100)
    layout["objects"][-1].update(opacity=1, visible=False, initial_state="hidden")
    timeline["initial_object_states"][-1].update(visible=False, state="hidden")
    rebind(layout, timeline)
    with pytest.raises(ValueError, match="fully visible"):
        evaluate_frame(layout, timeline, 100)


def test_annotation_after_prior_camera_requires_whole_readable_composition():
    _, layout, timeline = annotation_documents()
    append_camera(timeline, "camera-before", "camera_cut", 5500, 5600)
    with pytest.raises(ValueError, match="reading viewport"):
        evaluate_frame(layout, timeline, 100)
    timeline["actions"][3]["action"]["target_ids"] = ["object-system", "object-label", "object-evidence"]
    timeline["actions"][3]["action"]["framing"] = "wide"
    assert compose_png_frame(layout, timeline, 6500).png.startswith(b"\x89PNG")


def test_camera_can_focus_constructed_note_after_hold_and_exit_is_not_blocked_forever():
    _, layout, timeline = annotation_documents()
    append_camera(timeline, "camera-after", "camera_cut", 8000, 8100, target="annotation-note")
    assert evaluate_frame(layout, timeline, 8100).camera.width < 1280
    _, layout, timeline = annotation_documents()
    append_target(timeline, "annotation-note", "exit", 8000, 8500)
    assert evaluate_frame(layout, timeline, 8250).object("annotation-note").opacity == .5
    assert evaluate_frame(layout, timeline, 8500).object("annotation-note").state == "removed"


def test_pointer_is_only_allowed_when_owned_by_exact_annotation_policy():
    _, layout, timeline = leader_documents()
    timeline["actions"][-1]["action"]["annotation_policy"].update(leader_connector_id=None)
    timeline["actions"][-1]["action"]["annotation_policy"]["phases"].pop()
    with pytest.raises(ValueError, match="pointer semantics"):
        compose_svg_frame(layout, timeline, 100)


def test_pointer_head_is_preflighted_before_the_annotation_is_visible():
    _, layout, timeline = leader_documents()
    layout["objects"][-1]["geometry"]["bounds"].update(x=320, width=580)
    rebind(layout, timeline)
    with pytest.raises(ValueError, match="head exceeds authored bounds"):
        compose_svg_frame(layout, timeline, 100)


def test_multiple_notes_have_independent_ordered_construction_and_persistent_paint():
    _, layout, timeline = annotation_documents()
    second = deepcopy(layout["objects"][-1])
    second.update(object_id="second-note", text="Another observation", z_index=7)
    second["geometry"]["bounds"].update(x=630)
    layout["objects"].append(second)
    layout["boards"][0]["object_ids"].append(second["object_id"])
    timeline["initial_object_states"].append({"object_id": second["object_id"], "state": "hidden",
                                               "state_version": 1, "visible": False})
    policy = timeline["actions"][-1]["action"]["annotation_policy"]
    policy["annotation_object_ids"].append(second["object_id"])
    policy["phases"].append({"object_id": second["object_id"], "mode": "write", "weight": 1})
    rebind(layout, timeline)
    frame = evaluate_frame(layout, timeline, 6250)
    assert frame.object("annotation-note").reveal_fraction == .5
    assert not frame.object("second-note").visible
    frame = evaluate_frame(layout, timeline, 6750)
    assert frame.object("annotation-note").reveal_fraction == 1
    assert frame.object("second-note").reveal_fraction == .5
    svg = compose_svg_frame(layout, timeline, 7999).svg
    assert "A stable boundary" in svg and "Another observation" in svg


def test_prior_transform_changes_pointer_world_binding_without_moving_authored_notes():
    _, layout, timeline = leader_documents()
    destination = deepcopy(layout["objects"][0]["transform"])
    destination["position"] = {"x": 40, "y": 10}
    append_target(timeline, "object-system", "move", 5000, 5500, destination=destination)
    frame = evaluate_frame(layout, timeline, 6750)
    assert frame.object("object-system").transform.position.x == 40
    assert frame.object("annotation-note").transform.position.x == 0
    assert compose_png_frame(layout, timeline, 6750).png.startswith(b"\x89PNG")
    destination["position"]["x"] = 700
    with pytest.raises(ValueError, match="reading viewport|world endpoints"):
        evaluate_frame(layout, timeline, 100)


@pytest.mark.parametrize("target,verb", [("annotation-note", "exit"), ("object-system", "exit"),
                                           ("annotation-note", "fade"), ("object-system", "move"),
                                           ("annotation-note", "scale"), ("annotation-group", "fade"),
                                           ("annotation-leader", "move")])
def test_retained_pointer_blocks_later_endpoint_and_ancestor_edits_before_any_frame(target, verb):
    _, layout, timeline = grouped_annotation_documents(leader=True) if target == "annotation-group" else leader_documents()
    obj = next(obj for obj in layout["objects"] if obj["object_id"] == target)
    destination = deepcopy(obj["transform"]) if verb in {"move", "scale"} else None
    if verb == "move":
        destination["position"]["x"] = 700
    elif verb == "scale":
        destination["scale_y"] = .1
    append_target(timeline, target, verb, 8000, 8500, opacity=0 if verb == "fade" else None,
                  destination=destination)
    rebind(layout, timeline)
    for at in (100, 7999, 8250, 8500):
        with pytest.raises(ValueError, match="completed explicit removal"):
            evaluate_frame(layout, timeline, at)
        with pytest.raises(ValueError, match="completed explicit removal"):
            compose_png_frame(layout, timeline, at)


def test_pointer_removal_must_complete_before_an_endpoint_changes():
    _, layout, timeline = leader_documents()
    append_target(timeline, "annotation-leader", "exit", 8000, 8250)
    append_target(timeline, "annotation-note", "exit", 8250, 8500)
    assert compose_png_frame(layout, timeline, 8100).png.startswith(b"\x89PNG")
    assert not evaluate_frame(layout, timeline, 8250).object("annotation-leader").visible
    assert not evaluate_frame(layout, timeline, 8500).object("annotation-note").visible
    assert compose_png_frame(layout, timeline, 8500).png.startswith(b"\x89PNG")
    _, layout, timeline = leader_documents()
    append_target(timeline, "annotation-leader", "exit", 8000, 8250)
    append_target(timeline, "annotation-note", "exit", 8100, 8500)
    with pytest.raises(ValueError, match="completed explicit removal"):
        compose_svg_frame(layout, timeline, 100)


def test_annotations_render_in_both_profiles_offline_and_seeking_is_immutable(monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("annotation frames must not use the network")
    monkeypatch.setattr(socket, "socket", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
    _, layout, timeline = annotation_documents()
    landscape = compose_png_frame(layout, timeline, 6500).png
    for doc in (layout, timeline):
        doc["output_profile"] = {"profile_id": "SHORT_FORM_9_16", "width": 720, "height": 1280, "fps": 30}
    layout["canvas"].update(width=720, height=1280)
    rebind(layout, timeline)
    before = deepcopy((layout, timeline))
    portrait = compose_png_frame(layout, timeline, 6500).png
    assert Image.open(BytesIO(landscape)).size == (1280, 720)
    assert Image.open(BytesIO(portrait)).size == (720, 1280)
    compose_png_frame(layout, timeline, 7999)
    assert compose_png_frame(layout, timeline, 6500).png == portrait
    assert (layout, timeline) == before


def test_return_board_keeps_reference_version_unchanged_and_retains_annotations():
    _, layout, timeline = leader_documents()
    layout["boards"][0]["expected_prior_state"] = "model_annotated"
    layout["activations"][0]["end_ms"] = 8000
    layout["activations"].append({"activation_id": "activation-return", "board_id": "board-main",
                                   "start_ms": 9000, "end_ms": 10000, "reason": "Revisit annotated model"})
    returned = deepcopy(morph_documents()[1]["actions"][-1])
    trigger = {"kind": "absolute", "at_ms": 9000}
    returned["action"] = {"action_id": "return-annotation", "source_instruction_id": "instruction-1",
                          "board_id": "board-main", "semantic_reason": "Return to annotated model",
                          "trigger": trigger, "easing": "step", "expected_state": "model_annotated",
                          "post_state": "model_returned", "coverage_id": "coverage-1",
                          "fallback": {"fallback_id": "fallback-1", "on_failure": "block"},
                          "verb": "return_board", "destination_board_id": "board-main",
                          "destination_state": "model_returned", "source_board_id": "board-main",
                          "source_activation_id": "activation-1", "prior_destination_activation_id": "activation-1",
                          "destination_activation_id": "activation-return",
                          "expected_object_states": {state["object_id"]: "visible" if state["object_id"] != "object-replacement"
                                                     else "hidden" for state in timeline["initial_object_states"]},
                          "expected_object_state_versions": {state["object_id"]: 1 if state["object_id"] == "object-replacement"
                                                             else 2 for state in timeline["initial_object_states"]}}
    returned.update(start_ms=9000, end_ms=9001)
    returned["resolved_trigger"].update(source=trigger, alignment_anchor_ms=9000, resolved_at_ms=9000)
    timeline["actions"].append(returned)
    timeline["coverage"][0]["action_ids"].append("return-annotation")
    rebind(layout, timeline)
    assert compose_png_frame(layout, timeline, 7999).png == compose_png_frame(layout, timeline, 9000).png
    assert not evaluate_frame(layout, timeline, 8500).object("annotation-note").visible
    returned["action"]["expected_object_state_versions"]["object-system"] = 3
    with pytest.raises(ValueError, match="retained board state"):
        evaluate_frame(layout, timeline, 100)


def test_stored_project_annotation_uses_exact_compositor_and_cleaned_timing(tmp_path):
    service, project, plan, layout, timeline = stored_v2_basis(tmp_path, real_evidence=True)
    project_id = project["project_id"]
    _, note_layout, note_timeline = annotation_documents()
    note = deepcopy(plan["objects"][1])
    note.update(object_id="annotation-note", initial_state="hidden", coverage_ids=["coverage-1"])
    plan["objects"].append(note)
    plan["boards"][0]["object_ids"].append(note["object_id"])
    plan["beats"][0]["object_ids"].append(note["object_id"])
    action = deepcopy(note_timeline["actions"][-1]["action"])
    trigger = {"kind": "absolute", "at_ms": 8000}
    action.update(action_id="annotation-project", trigger=trigger)
    plan["actions"].append(action)
    plan["beats"][0]["action_ids"].append(action["action_id"])
    plan["coverage"][0]["action_ids"].append(action["action_id"])
    plan["project_revision"] = project["revision"]
    project = service.write(project_id, "storyboard", plan, project["revision"])
    layout["objects"].append(deepcopy(note_layout["objects"][-1]))
    layout["boards"] = deepcopy(plan["boards"])
    layout.update(project_revision=project["revision"], plan_revision=project["artifacts"]["storyboard"],
                  plan_sha256=digest(plan))
    project = service.write(project_id, "layout", layout, project["revision"])
    timeline["initial_object_states"].append({"object_id": "annotation-note", "state": "hidden",
                                               "state_version": 1, "visible": False})
    timeline["actions"].append({"action": action, "start_ms": 8000, "end_ms": 9000,
                                 "resolved_trigger": {"source": trigger, "alignment_anchor_ms": 8000,
                                                      "matched_text": None, "matched_occurrence": None,
                                                      "resolved_at_ms": 8000, "confidence": 1, "exact": True}})
    timeline["coverage"] = deepcopy(plan["coverage"])
    timeline.update(project_revision=project["revision"], plan_revision=project["artifacts"]["storyboard"],
                    layout_revision=project["artifacts"]["layout"], plan_sha256=digest(plan), layout_sha256=digest(layout))
    timeline["compilation_fingerprint"] = _resolved_compilation_fingerprint(timeline)
    project = service.write(project_id, "resolved_timeline", timeline, project["revision"])
    parsed = ResolvedVisualTimelineV2.model_validate(timeline)
    treatment = ExecutableLayoutV2.model_validate(layout).evidence_treatments[0]
    asset = parsed.resolved_assets[0]
    verified = service.render_evidence_bytes(project_id, asset, treatment)
    preview = service.runner.preview_v2_source(project_id, project["revision"], 8500)
    assert preview["png"] == compose_png_frame(layout, timeline, 8500, {asset.asset_id: verified}).png
    assert timeline["duration_ms"] == service.source_timeline.get(project_id)["document"]["duration_ms"]
    service.store.close()
