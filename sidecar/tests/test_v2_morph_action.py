"""A morph paints one interpolated geometry and transfers authored object identity."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from copy import deepcopy
from io import BytesIO

import pytest
from PIL import Image
from pydantic import ValidationError
from test_v2_camera_action import append_camera
from test_v2_connector_svg import connector_documents
from test_v2_mask_contract import masked_documents
from test_v2_replace_action import documents as replace_documents
from test_v2_resolved_project import stored_v2_basis
from v2_fixtures import digest, visual_plan_v2

from atme.project_service import _resolved_compilation_fingerprint
from atme.render.v2_morph import interpolate_geometry
from atme.render.v2_state import evaluate_frame
from atme.render.v2_svg import compose_png_frame, compose_svg_frame
from atme.render.v2_world import world_bounds
from atme.store.contracts_v2 import (
    ExecutableLayoutV2,
    MorphPolicy,
    ResolvedVisualTimelineV2,
    validate_plan_evidence_completeness,
    validate_plan_layout,
)


def morph_documents(mapping="canonical_outline"):
    layout, timeline = replace_documents()
    source, destination = layout["objects"][0], layout["objects"][-1]
    source["style"]["fill"] = "surface.accent"
    destination["style"] = deepcopy(source["style"])
    destination.update(object_type="ellipse")
    destination["geometry"] = {"bounds": {"x": 680, "y": 190, "width": 300, "height": 220},
                               "points": [], "corner_radius": None}
    action = timeline["actions"][-1]["action"]
    action.update(verb="morph", morph_policy={"mapping": mapping, "paint": "shared_style",
                                             "transforms": "interpolate_all"})
    if mapping == "ordered_vertices":
        for obj, coords in ((source, [(100, 180), (500, 180), (300, 470)]),
                            (destination, [(690, 210), (970, 300), (740, 400)])):
            obj.update(object_type="polygon")
            obj["geometry"]["corner_radius"] = None
            obj["geometry"]["points"] = [{"x": x, "y": y} for x, y in coords]
        action["morph_policy"]["point_count"] = 3
    elif mapping == "matching_path_commands":
        for obj, path in ((source, "M 100 180 Q 300 190 500 470"),
                          (destination, "M 690 210 Q 970 300 740 400")):
            obj.update(object_type="freehand", path_data=path)
            obj["geometry"]["corner_radius"] = None
            obj["style"]["fill"] = None
        action["morph_policy"]["path_commands"] = ["M", "Q"]
    timeline["layout_sha256"] = digest(layout)
    return layout, timeline


def semantic_plan(layout, timeline):
    plan = visual_plan_v2()
    fields = plan["objects"][0].keys()
    plan["objects"] = [{key: obj[key] for key in fields} for obj in layout["objects"]]
    plan["assets"] = []
    plan["boards"] = layout["boards"]
    plan["actions"] = [item["action"] for item in timeline["actions"]]
    plan["coverage"] = timeline["coverage"]
    plan["beats"][0]["object_ids"].append("object-replacement")
    plan["beats"][0]["action_ids"].append("replace-1")
    plan["beats"][1]["evidence"] = None
    layout["plan_sha256"] = digest(plan)
    timeline["plan_sha256"] = digest(plan)
    timeline["layout_sha256"] = digest(layout)
    return plan


@pytest.mark.parametrize("mapping", ["canonical_outline", "ordered_vertices", "matching_path_commands"])
def test_morph_geometry_at_start_middle_end_and_random_seek(mapping):
    layout, timeline = morph_documents(mapping)
    original = deepcopy((layout, timeline))
    before = evaluate_frame(layout, timeline, 5999)
    start = evaluate_frame(layout, timeline, 6000)
    middle = evaluate_frame(layout, timeline, 6500)
    end = evaluate_frame(layout, timeline, 7000)
    source = middle.object("object-system")
    assert source.opacity == 1 and source.visible and source.reveal_fraction == 1
    assert not middle.object("object-replacement").visible
    assert source.morph_geometry is not None
    assert source.morph_geometry.bounds == (380, 175, 390, 280)
    assert start.object("object-system").morph_geometry is None
    assert before.object("object-system") == start.object("object-system")
    assert end.object("object-system").state == "removed"
    assert not end.object("object-system").visible
    assert end.object("object-replacement").visible
    assert end.object("object-replacement").opacity == 1
    first = compose_png_frame(layout, timeline, 6500).png
    for moment in (7999, 6200, 7000, 6000, 6500):
        evaluate_frame(layout, timeline, moment)
    assert evaluate_frame(layout, timeline, 6500) == middle
    assert compose_png_frame(layout, timeline, 6500).png == first
    assert (layout, timeline) == original
    root = ET.fromstring(compose_svg_frame(layout, timeline, 6500).svg)
    painted = [node for node in root.iter() if node.attrib.get("data-geometry-action") == "morph"]
    assert len(painted) == 1
    assert not any(node.attrib.get("data-object-id") == "object-replacement" for node in root.iter())


def test_morph_pixels_prove_geometry_between_disjoint_endpoints_without_crossfade():
    layout, timeline = morph_documents()
    frames = [Image.open(BytesIO(compose_png_frame(layout, timeline, moment).png)).convert("RGB")
              for moment in (5999, 6500, 7000)]
    background = frames[0].getpixel((600, 350))
    assert frames[2].getpixel((600, 350)) == background
    assert frames[1].getpixel((600, 350)) != background
    assert compose_png_frame(layout, timeline, 5999).png == compose_png_frame(layout, timeline, 6000).png
    # Native authored destination paint is used at the exact end.
    finished = ET.fromstring(compose_svg_frame(layout, timeline, 7000).svg)
    destination = next(node for node in finished.iter()
                       if node.attrib.get("data-object-id") == "object-replacement")
    assert destination[0].tag.endswith("ellipse")


@pytest.mark.parametrize("easing,expected", [("linear", .5), ("ease_in", .25),
                                            ("ease_out", .75), ("ease_in_out", .5)])
def test_morph_uses_authored_easing_and_all_transform_channels(easing, expected):
    layout, timeline = morph_documents()
    destination = layout["objects"][-1]
    destination["transform"].update(position={"x": 20, "y": 40}, scale_x=1.4, scale_y=.8,
                                     rotation_degrees=30, origin={"x": .2, "y": .8})
    timeline["actions"][-1]["action"]["easing"] = easing
    timeline["layout_sha256"] = digest(layout)
    frame = evaluate_frame(layout, timeline, 6500).object("object-system")
    assert frame.morph_geometry.bounds[0] == 80 + 600 * expected
    assert frame.transform.position.x == pytest.approx(20 * expected)
    assert frame.transform.position.y == pytest.approx(40 * expected)
    assert frame.transform.scale_x == pytest.approx(1 + .4 * expected)
    assert frame.transform.scale_y == pytest.approx(1 - .2 * expected)
    assert frame.transform.rotation_degrees == pytest.approx(30 * expected)
    assert frame.transform.origin.x == pytest.approx(.5 - .3 * expected)
    assert frame.transform.origin.y == pytest.approx(.5 + .3 * expected)
    assert compose_png_frame(layout, timeline, 6500).png.startswith(b"\x89PNG")


def test_new_plan_layout_preserves_explicit_morph_mapping():
    layout, timeline = morph_documents()
    plan = semantic_plan(layout, timeline)
    validate_plan_evidence_completeness(plan)
    validate_plan_layout(plan, layout)
    broken = deepcopy(plan)
    broken["actions"][-1].pop("morph_policy")
    with pytest.raises(ValueError, match="correspondence"):
        validate_plan_evidence_completeness(broken)
    layout["objects"][-1]["style"]["stroke"] = "ink.muted"
    with pytest.raises(ValueError, match="shared style"):
        validate_plan_layout(plan, layout)


@pytest.mark.parametrize("mapping,change,expected", [
    ("canonical_outline", lambda l, t: (
        l["objects"][-1].update(object_type="text", text="A", items=[]),
        l["objects"][-1].pop("path_data"),
    ), "mark geometry"),
    ("canonical_outline", lambda l, t: l["objects"][-1]["style"].update(fill="surface.paper"), "shared style"),
    ("canonical_outline", lambda l, t: l["objects"][-1].update(z_index=8), "ownership"),
    ("canonical_outline", lambda l, t: l["objects"][0]["geometry"].update(corner_radius=1000), "corner radius"),
    ("ordered_vertices", lambda l, t: l["objects"][-1]["geometry"]["points"].pop(), "point count"),
    ("ordered_vertices", lambda l, t: l["objects"][-1]["geometry"]["points"][0].update(x=0), "authored bounds"),
    ("matching_path_commands", lambda l, t: l["objects"][-1].update(path_data="M 690 210 L 740 400"), "command sequence"),
    ("matching_path_commands", lambda l, t: l["objects"][-1].update(path_data="M 690 210 Q 10 300 740 400"), "authored bounds"),
])
def test_incompatible_morph_rejects_before_any_frame(mapping, change, expected):
    layout, timeline = morph_documents(mapping)
    change(layout, timeline)
    timeline["layout_sha256"] = digest(layout)
    with pytest.raises(ValueError, match=expected):
        evaluate_frame(layout, timeline, 100)


def test_morph_policy_rejects_step_nonfinite_and_ignored_parameters():
    layout, timeline = morph_documents()
    timeline["actions"][-1]["action"]["easing"] = "step"
    with pytest.raises(ValueError, match="continuous easing"):
        evaluate_frame(layout, timeline, 100)
    with pytest.raises(ValidationError, match="ignored mapping"):
        MorphPolicy(mapping="canonical_outline", point_count=3)
    with pytest.raises(ValidationError):
        MorphPolicy(mapping="ordered_vertices", point_count=1)
    parsed = ExecutableLayoutV2.model_validate(layout)
    with pytest.raises(ValueError, match="finite"):
        interpolate_geometry(parsed.objects[0], parsed.objects[-1], MorphPolicy(mapping="canonical_outline"),
                             float("nan"))


def test_morph_camera_focus_is_valid_after_completion_but_not_during_edit():
    layout, timeline = morph_documents()
    append_camera(timeline, "after-morph", "camera_cut", 7500, 7700, target="object-replacement")
    assert evaluate_frame(layout, timeline, 7600).camera.width < 1280
    layout, timeline = morph_documents()
    append_camera(timeline, "during-morph", "camera_cut", 6500, 6700, target="object-replacement")
    with pytest.raises(ValueError, match="overlaps a focus-object edit"):
        evaluate_frame(layout, timeline, 100)


def test_morph_destination_can_move_and_source_cannot_resurrect():
    layout, timeline = morph_documents()
    move = deepcopy(timeline["actions"][-1])
    move["action"].update(action_id="move-after", verb="move", target_ids=["object-replacement"],
                           destination={**layout["objects"][-1]["transform"], "position": {"x": 50, "y": 0}})
    for key in ("from_object_id", "to_object_id", "morph_policy"):
        move["action"].pop(key)
    move["action"]["trigger"] = {"kind": "absolute", "at_ms": 8000}
    move.update(start_ms=8000, end_ms=8500)
    move["resolved_trigger"].update(source=move["action"]["trigger"], alignment_anchor_ms=8000,
                                     resolved_at_ms=8000)
    timeline["actions"].append(move)
    timeline["coverage"][0]["action_ids"].append("move-after")
    assert evaluate_frame(layout, timeline, 8500).object("object-replacement").transform.position.x == 50
    move["action"]["target_ids"] = ["object-system"]
    with pytest.raises(ValueError, match="resurrects removed"):
        ResolvedVisualTimelineV2.model_validate(timeline)


def test_morph_in_nested_group_and_portrait_uses_interpolated_world_bounds():
    layout, timeline = morph_documents()
    group = deepcopy(layout["objects"][0])
    group.update(object_id="group", object_type="group", visible=True, initial_state="visible",
                 child_ids=["object-system", "object-replacement"], anchors=[])
    group.pop("path_data")
    group["geometry"] = {"bounds": {"x": 0, "y": 0, "width": 1280, "height": 720},
                          "points": [], "corner_radius": None}
    group["style"] = {"stroke": None, "fill": None, "text": None, "effect": None}
    group["transform"].update(position={"x": 10, "y": 20}, scale_x=.5, scale_y=.5)
    for obj in (layout["objects"][0], layout["objects"][-1]):
        obj["parent_id"] = "group"
    layout["objects"].append(group)
    layout["boards"][0]["object_ids"].append("group")
    timeline["initial_object_states"].append({"object_id": "group", "state": "visible",
                                               "state_version": 1, "visible": True})
    timeline["layout_sha256"] = digest(layout)
    frame = evaluate_frame(layout, timeline, 6500)
    from atme.render.v2_morph import geometry_object

    parsed = ExecutableLayoutV2.model_validate(layout)
    objects = {obj.object_id: geometry_object(obj, frame.object(obj.object_id).morph_geometry)
               for obj in parsed.objects}
    rect = world_bounds(objects["object-system"], objects,
                        {obj.object_id: obj.transform for obj in frame.objects})
    assert rect == pytest.approx((520, 287.5, 715, 427.5))
    svg = compose_svg_frame(layout, timeline, 6500).svg
    assert 'data-geometry-action="morph"' in svg
    for document in (layout, timeline):
        document["output_profile"] = {"profile_id": "SHORT_FORM_9_16", "width": 720,
                                       "height": 1280, "fps": 30}
    layout["canvas"].update(width=720, height=1280)
    timeline["layout_sha256"] = digest(layout)
    assert Image.open(BytesIO(compose_png_frame(layout, timeline, 6500).png)).size == (720, 1280)


@pytest.mark.parametrize("source_type", ["rectangle", "rounded_rectangle", "ellipse"])
@pytest.mark.parametrize("destination_type", ["rectangle", "rounded_rectangle", "ellipse"])
def test_all_canonical_outline_pairs_use_exact_native_endpoint_paint(source_type, destination_type):
    layout, timeline = morph_documents()
    for obj, kind in ((layout["objects"][0], source_type), (layout["objects"][-1], destination_type)):
        obj["object_type"] = kind
        obj["geometry"]["corner_radius"] = 24 if kind == "rounded_rectangle" else None
    timeline["layout_sha256"] = digest(layout)
    assert compose_png_frame(layout, timeline, 5999).png == compose_png_frame(layout, timeline, 6000).png
    frame = compose_svg_frame(layout, timeline, 6500)
    assert frame.svg.count('data-geometry-action="morph"') == 1
    assert evaluate_frame(layout, timeline, 7000).object("object-replacement").morph_geometry is None


@pytest.mark.parametrize("kind", ["line", "freehand"])
def test_ordered_open_strokes_and_full_curve_command_topology(kind):
    layout, timeline = morph_documents("ordered_vertices")
    for obj in (layout["objects"][0], layout["objects"][-1]):
        obj["object_type"] = kind
        obj["style"]["fill"] = None
        obj["geometry"]["points"] = obj["geometry"]["points"][:2]
    timeline["actions"][-1]["action"]["morph_policy"]["point_count"] = 2
    timeline["layout_sha256"] = digest(layout)
    assert compose_svg_frame(layout, timeline, 6500).svg.count('data-geometry-action="morph"') == 1
    frames = [Image.open(BytesIO(compose_png_frame(layout, timeline, at).png)).convert("RGB")
              for at in (5999, 6500, 7000)]
    region = (560, 212, 570, 223)
    assert frames[0].crop(region).tobytes() == frames[2].crop(region).tobytes()
    assert frames[1].crop(region).tobytes() != frames[0].crop(region).tobytes()
    assert compose_png_frame(layout, timeline, 6500).png == compose_png_frame(layout, timeline, 6500).png
    layout, timeline = morph_documents("matching_path_commands")
    layout["objects"][0]["path_data"] = "M 100 180 L 200 200 Q 250 250 300 300 C 350 350 400 400 500 470"
    layout["objects"][-1]["path_data"] = "M 690 210 L 720 230 Q 740 250 760 280 C 800 300 820 340 900 400"
    timeline["actions"][-1]["action"]["morph_policy"]["path_commands"] = ["M", "L", "Q", "C"]
    timeline["layout_sha256"] = digest(layout)
    assert compose_png_frame(layout, timeline, 6500).png.startswith(b"\x89PNG")


@pytest.mark.parametrize("kind", ["clip", "mask"])
def test_morph_under_static_aperture_preserves_clipping_and_seek(kind):
    layout, timeline = morph_documents()
    _, masked, _ = masked_documents()
    container = deepcopy(masked["objects"][3])
    container["child_ids"] = ["object-system", "object-replacement"]
    container["geometry"]["bounds"] = {"x": 450, "y": 160, "width": 200, "height": 340}
    if kind == "clip":
        container["object_type"] = "clip"
        for field in ("mask_mode", "mask_source_object_id", "mask_coordinate_space", "invert", "feather_px"):
            container.pop(field)
    else:
        aperture = deepcopy(masked["objects"][4])
        aperture["object_type"] = "rectangle"
        aperture["geometry"] = deepcopy(container["geometry"])
        layout["objects"].append(aperture)
        layout["boards"][0]["object_ids"].append(aperture["object_id"])
        timeline["initial_object_states"].append({"object_id": aperture["object_id"], "state": "visible",
                                                   "state_version": 1, "visible": True})
    for obj in (layout["objects"][0], layout["objects"][-1 if kind == "clip" else -2]):
        obj["parent_id"] = container["object_id"]
    layout["objects"].append(container)
    layout["boards"][0]["object_ids"].append(container["object_id"])
    timeline["initial_object_states"].append({"object_id": container["object_id"], "state": "visible",
                                               "state_version": 1, "visible": True})
    timeline["layout_sha256"] = digest(layout)
    rendered = compose_png_frame(layout, timeline, 6500).png
    pixels = Image.open(BytesIO(rendered)).convert("RGB")
    assert pixels.getpixel((550, 350)) != pixels.getpixel((50, 350))
    assert pixels.getpixel((400, 350)) == pixels.getpixel((50, 350))
    compose_png_frame(layout, timeline, 7000)
    assert compose_png_frame(layout, timeline, 6500).png == rendered


def test_morph_rejects_a_stroke_that_disappears_between_endpoints():
    layout, timeline = morph_documents("ordered_vertices")
    source, destination = layout["objects"][0], layout["objects"][-1]
    source.update(object_type="line")
    source["style"]["fill"] = None
    source["geometry"]["points"] = [{"x": 100, "y": 180}, {"x": 500, "y": 470}]
    destination.update(object_type="line", geometry=deepcopy(source["geometry"]),
                        style=deepcopy(source["style"]))
    destination["geometry"]["points"].reverse()
    timeline["actions"][-1]["action"]["morph_policy"]["point_count"] = 2
    timeline["layout_sha256"] = digest(layout)
    with pytest.raises(ValueError, match="collapses the complete stroke"):
        evaluate_frame(layout, timeline, 100)


def test_return_board_retains_morph_identity_and_exact_state_versions():
    layout, timeline = morph_documents()
    layout["boards"][0]["expected_prior_state"] = "model_morphed"
    layout["activations"][0]["end_ms"] = 7500
    layout["activations"].append({"activation_id": "activation-return", "board_id": "board-main",
                                   "start_ms": 9000, "end_ms": 10000, "reason": "Revisit developed geometry"})
    trigger = {"kind": "absolute", "at_ms": 9000}
    timeline["actions"].append({
        "action": {
            "action_id": "return-morph", "source_instruction_id": "instruction-1", "board_id": "board-main",
            "semantic_reason": "Return to the retained developed shape", "trigger": trigger, "easing": "step",
            "expected_state": "model_morphed", "post_state": "model_returned", "coverage_id": "coverage-1",
            "fallback": {"fallback_id": "fallback-1", "on_failure": "block"}, "verb": "return_board",
            "destination_board_id": "board-main", "destination_state": "model_returned",
            "source_board_id": "board-main", "source_activation_id": "activation-1",
            "prior_destination_activation_id": "activation-1", "destination_activation_id": "activation-return",
            "expected_object_states": {"object-system": "removed", "object-label": "visible",
                                       "object-evidence": "visible", "object-replacement": "visible"},
            "expected_object_state_versions": {"object-system": 3, "object-label": 2,
                                               "object-evidence": 2, "object-replacement": 2},
        }, "start_ms": 9000, "end_ms": 9001,
        "resolved_trigger": {"source": trigger, "alignment_anchor_ms": 9000, "matched_text": None,
                             "matched_occurrence": None, "resolved_at_ms": 9000, "confidence": 1, "exact": True},
    })
    timeline["coverage"][0]["action_ids"].append("return-morph")
    timeline["layout_sha256"] = digest(layout)
    assert not evaluate_frame(layout, timeline, 8000).object("object-replacement").visible
    returned = evaluate_frame(layout, timeline, 9000)
    assert returned.object("object-system").state == "removed"
    assert returned.object("object-replacement").visible
    assert compose_png_frame(layout, timeline, 7400).png == compose_png_frame(layout, timeline, 9000).png
    timeline["actions"][-1]["action"]["expected_object_state_versions"]["object-system"] = 2
    with pytest.raises(ValueError, match="retained board state"):
        evaluate_frame(layout, timeline, 100)


@pytest.mark.parametrize("next_verb", ["morph", "replace"])
def test_morph_chains_into_authored_morph_or_replacement(next_verb):
    layout, timeline = morph_documents()
    third = deepcopy(layout["objects"][-1])
    third.update(object_id="object-third")
    if next_verb == "morph":
        third.update(object_type="rounded_rectangle")
        third["geometry"]["corner_radius"] = 16
    layout["objects"].append(third)
    layout["boards"][0]["object_ids"].append("object-third")
    timeline["initial_object_states"].append({"object_id": "object-third", "state": "hidden",
                                               "state_version": 1, "visible": False})
    action = deepcopy(timeline["actions"][-1])
    action["action"].update(action_id="second-change", verb=next_verb,
                             from_object_id="object-replacement", to_object_id="object-third",
                             trigger={"kind": "absolute", "at_ms": 8000})
    if next_verb == "replace":
        action["action"].pop("morph_policy")
    action.update(start_ms=8000, end_ms=8500)
    action["resolved_trigger"].update(source=action["action"]["trigger"],
                                      alignment_anchor_ms=8000, resolved_at_ms=8000)
    timeline["actions"].append(action)
    timeline["coverage"][0]["action_ids"].append("second-change")
    timeline["layout_sha256"] = digest(layout)
    assert evaluate_frame(layout, timeline, 8250).object("object-replacement").visible
    finished = evaluate_frame(layout, timeline, 8500)
    assert finished.object("object-replacement").state == "removed"
    assert finished.object("object-third").visible
    assert compose_png_frame(layout, timeline, 8250).png.startswith(b"\x89PNG")


def test_morph_cannot_silently_handoff_a_connector_anchor():
    layout, timeline = morph_documents()
    arrow = connector_documents()[0]["objects"][-1]
    layout["objects"].append(arrow)
    layout["boards"][0]["object_ids"].append(arrow["object_id"])
    timeline["initial_object_states"].append({"object_id": arrow["object_id"], "state": "hidden",
                                               "state_version": 1, "visible": False})
    timeline["layout_sha256"] = digest(layout)
    with pytest.raises(ValueError, match="distinct paintable objects"):
        evaluate_frame(layout, timeline, 100)


def test_stored_project_morph_uses_exact_source_compositor_and_cleaned_timing(tmp_path):
    service, project, plan, layout, timeline = stored_v2_basis(tmp_path, real_evidence=True)
    plan, layout, timeline = deepcopy(plan), deepcopy(layout), deepcopy(timeline)
    project_id = project["project_id"]
    semantic = deepcopy(plan["objects"][0])
    semantic.update(object_id="object-morphed", object_type="ellipse", initial_state="hidden")
    plan["objects"].append(semantic)
    plan["boards"][0]["object_ids"].append("object-morphed")
    plan["beats"][0]["object_ids"].append("object-morphed")
    trigger = {"kind": "absolute", "at_ms": 8000}
    action = deepcopy(morph_documents()[1]["actions"][-1]["action"])
    action.update(action_id="morph-project", from_object_id="object-system",
                   to_object_id="object-morphed", trigger=trigger)
    plan["actions"].append(action)
    plan["beats"][0]["action_ids"].append("morph-project")
    plan["coverage"][0]["action_ids"].append("morph-project")
    plan["project_revision"] = project["revision"]
    project = service.write(project_id, "storyboard", plan, project["revision"])
    destination = deepcopy(layout["objects"][0])
    destination.update(object_id="object-morphed", object_type="ellipse")
    destination["geometry"]["corner_radius"] = None
    layout["objects"].append(destination)
    layout["boards"] = deepcopy(plan["boards"])
    layout.update(project_revision=project["revision"],
                  plan_revision=project["artifacts"]["storyboard"], plan_sha256=digest(plan))
    project = service.write(project_id, "layout", layout, project["revision"])
    timeline["initial_object_states"].append({"object_id": "object-morphed", "state": "hidden",
                                               "state_version": 1, "visible": False})
    timeline["actions"].append({
        "action": action, "start_ms": 8000, "end_ms": 9000,
        "resolved_trigger": {"source": trigger, "alignment_anchor_ms": 8000, "matched_text": None,
                             "matched_occurrence": None, "resolved_at_ms": 8000, "confidence": 1, "exact": True},
    })
    timeline["coverage"] = deepcopy(plan["coverage"])
    timeline.update(project_revision=project["revision"], plan_revision=project["artifacts"]["storyboard"],
                    layout_revision=project["artifacts"]["layout"], plan_sha256=digest(plan),
                    layout_sha256=digest(layout))
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
