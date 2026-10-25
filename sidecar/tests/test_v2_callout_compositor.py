"""Callout body and its separate pointer consume the real shared chronology."""

import io
import xml.etree.ElementTree as ET
from copy import deepcopy
from pathlib import Path

import pytest
import resvg_py
from atme.render.style_bundle import load_bundle
from atme.render.v2_split_paint import verify_split_paint_inputs
from atme.render.v2_state import evaluate_frame
from atme.render.v2_svg import (
    _compose_validated_svg_frame,
    _rasterize_svg_frame,
    compose_png_frame,
    compose_svg_frame,
)
from atme.store.contracts_v2 import ExecutableLayoutV2, ResolvedVisualTimelineV2
from PIL import Image
from test_v2_callout_contract import callout_documents
from v2_fixtures import digest

BODY, LEADER, TARGET = "annotation-note", "annotation-leader", "object-system"


def add_action(timeline, verb, target, start, end, expected="visible", post="visible"):
    row = deepcopy(timeline["actions"][0])
    trigger = {"kind": "absolute", "at_ms": start}
    row["action"].update(action_id=f"{verb}-{target}-{start}", verb=verb, target_ids=[target],
        trigger=trigger, easing="linear", expected_state=expected, post_state=post)
    row["action"].pop("annotation_policy", None)
    if verb in {"move", "scale", "rotate", "fade"}:
        row["action"].pop("annotation", None)
    row["resolved_trigger"].update(source=trigger, alignment_anchor_ms=start, resolved_at_ms=start,
        matched_text=None, matched_occurrence=None, confidence=1., exact=True)
    row.update(start_ms=start, end_ms=end)
    timeline["actions"].append(row)
    return row


def rebind(layout, timeline):
    timeline["actions"].sort(key=lambda row: row["start_ms"])
    timeline["coverage"][0]["action_ids"] = [row["action"]["action_id"] for row in timeline["actions"]]
    timeline["layout_sha256"] = digest(layout)


def compositor_documents(portrait=False, boxed=False):
    _, layout, timeline = callout_documents()
    ids = {BODY, LEADER, TARGET}
    layout["objects"] = [obj for obj in layout["objects"] if obj["object_id"] in ids]
    layout["boards"][0]["object_ids"] = [obj["object_id"] for obj in layout["objects"]]
    objects = {obj["object_id"]: obj for obj in layout["objects"]}
    target, body, leader = (objects[key] for key in (TARGET, BODY, LEADER))
    target.update(object_type="rectangle", style={"stroke": "ink.primary", "fill": "surface.paper",
        "text": None, "effect": None},
        geometry={"bounds": {"x": 160., "y": 100., "width": 160., "height": 160.},
                  "points": [], "corner_radius": None})
    body.update(text="A\u0301B", items=[], style={"stroke": "ink.primary" if boxed else None,
        "fill": "surface.paper" if boxed else None, "text": "text.body", "effect": None},
        geometry={"bounds": {"x": 80., "y": 420., "width": 320., "height": 100.},
                  "points": [], "corner_radius": 8. if boxed else None})
    leader["style"]["stroke"] = "ink.primary"
    leader["geometry"]["bounds"] = {"x": 50., "y": 50., "width": 400., "height": 600.}
    timeline["initial_object_states"] = [s for s in timeline["initial_object_states"] if s["object_id"] in ids]
    timeline["actions"] = [timeline["actions"][0]]
    timeline["actions"][0]["action"]["easing"] = "linear"
    add_action(timeline, "write", BODY, 2000, 3000, "hidden")
    add_action(timeline, "draw", LEADER, 3000, 4000, "hidden")
    timeline["coverage"] = [timeline["coverage"][0]]
    timeline["fallbacks"] = [timeline["fallbacks"][0]]
    timeline["resolved_assets"] = []
    if portrait:
        profile = {"profile_id": "SHORT_FORM_9_16", "width": 720, "height": 1280, "fps": 30}
        layout["output_profile"] = timeline["output_profile"] = profile
        layout["canvas"].update(width=720, height=1280)
    rebind(layout, timeline)
    return layout, timeline


def rgba(payload):
    with Image.open(io.BytesIO(payload)) as image:
        return image.convert("RGBA").tobytes()


def literal_frame(portrait, boxed, at_ms, *, initially_visible=False, grouped=False, moved=False):
    style, _, root = load_bundle()
    width, height = (720, 1280) if portrait else (1280, 720)
    color, paper = style.colors["ink"], style.colors["paper"]
    target = (f'<rect x="160" y="100" width="160" height="160" fill="{paper}" '
        f'stroke="{color}" stroke-width="2.6667" stroke-linecap="round" stroke-linejoin="round"/>')
    body = ""
    if initially_visible or at_ms > 2000:
        text = "A\u0301B" if initially_visible or at_ms >= 3000 else "A\u0301" if at_ms >= 2500 else ""
        box = (f'<rect x="80" y="420" width="320" height="100" rx="8" fill="{paper}" '
            f'stroke="{color}" stroke-width="2.6667" stroke-linecap="round" stroke-linejoin="round"/>') if boxed else ""
        body = (box + f'<text x="{"90.6667" if boxed else "80"}" '
            f'y="{"452" if boxed else "441.3333"}" fill="{color}" font-family="Atkinson Hyperlegible" '
            f'font-size="21.3333" font-weight="400" xml:space="preserve">{text}</text>')
        if moved:
            body = f'<g transform="translate(0 20)">{body}</g>'
    if grouped:
        target, body = f'<g transform="matrix(1.25 0 0 0.8 40 30)">{target}{body}</g>', ""
    pointer = ""
    if initially_visible or at_ms > 3000:
        dash = ' stroke-dasharray="290 290" stroke-dashoffset="145"' if at_ms == 3500 and not initially_visible else ""
        points = "340,174 345.9999,187.9998 334.0001,187.9998" if grouped else "240,180 245.9999,193.9998 234.0001,193.9998"
        path = "M 340 406 L 340 174" if grouped else "M 240 490 L 240 180" if moved else "M 240 470 L 240 180"
        head = (f'<polygon points="{points}" fill="{color}"/>') if initially_visible or at_ms >= 4000 else ""
        pointer = (f'<path d="{path}" fill="none" stroke="{color}" stroke-width="2.6667" '
            f'stroke-linecap="round" stroke-linejoin="round"{dash}/>{head}')
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">'
        f'<rect width="{width}" height="{height}" fill="{paper}"/>{target}{body}{pointer}</svg>')
    return bytes(resvg_py.svg_to_bytes(svg_string=svg,
        font_files=[str(root / "fonts/AtkinsonHyperlegible-Regular.otf")], skip_system_fonts=True))


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("boxed", [False, True])
def test_callout_shared_compositor_has_literal_body_pointer_pixels_and_random_seek(portrait, boxed):
    layout, timeline = compositor_documents(portrait, boxed)
    frames = {}
    for time in [2000, 2500, 3000, 3500, 4000]:
        frame, png = compose_svg_frame(layout, timeline, time), compose_png_frame(layout, timeline, time)
        assert rgba(png.png) == rgba(literal_frame(portrait, boxed, time))
        nodes = list(ET.fromstring(frame.svg).iter())
        assert sum(n.attrib.get("data-object-id") == BODY for n in nodes) == (time > 2000)
        assert sum(n.attrib.get("data-object-id") == LEADER for n in nodes) == (time > 3000)
        assert sum(n.tag.endswith("polygon") for n in nodes) == (time >= 4000)
        frames[time] = frame, png
    for time in [4000, 2000, 3500, 2500, 3000, 4000, 2500]:
        assert (compose_svg_frame(layout, timeline, time), compose_png_frame(layout, timeline, time)) == frames[time]


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("boxed", [False, True])
def test_callout_shared_source_frozen_pixels_are_identical_without_source_reads(portrait, boxed, monkeypatch):
    raw_layout, raw_timeline = compositor_documents(portrait, boxed)
    layout = ExecutableLayoutV2.model_validate(raw_layout)
    timeline = ResolvedVisualTimelineV2.model_validate(raw_timeline)
    inputs = verify_split_paint_inputs(layout, {})
    samples = {t: evaluate_frame(raw_layout, raw_timeline, t) for t in [2000, 2500, 3000, 3500, 4000]}
    expected = {t: (compose_svg_frame(raw_layout, raw_timeline, t), compose_png_frame(raw_layout, raw_timeline, t))
        for t in samples}

    def no_source(path):
        raise AssertionError(f"frozen callout reopened original {path}")

    monkeypatch.setattr(Path, "read_bytes", no_source)
    for t, sample in samples.items():
        svg = _compose_validated_svg_frame(layout, timeline, sample, {}, split_inputs=inputs)
        assert (svg, _rasterize_svg_frame(layout, svg, split_inputs=inputs)) == expected[t]


@pytest.mark.parametrize("fault", ["body_incomplete", "target_hidden", "target_faded", "body_exit",
    "body_move", "target_move", "pointer_fade", "during_exit", "simultaneous_exit"])
def test_callout_invalid_readiness_or_retained_lifetime_rejects_before_first_frame(fault):
    layout, timeline = compositor_documents()
    if fault == "body_incomplete":
        timeline["actions"][1]["end_ms"] = 3001
    elif fault == "target_hidden":
        timeline["actions"].pop(0)
    elif fault == "target_faded":
        next(o for o in layout["objects"] if o["object_id"] == TARGET)["opacity"] = .5
    elif fault == "pointer_fade":
        row = add_action(timeline, "fade", LEADER, 5000, 5500)
        row["action"]["opacity"] = 0.
    elif fault in {"body_move", "target_move"}:
        key = BODY if fault == "body_move" else TARGET
        row = add_action(timeline, "move", key, 5000, 5500)
        row["action"]["destination"] = deepcopy(layout["objects"][0]["transform"])
        row["action"]["destination"]["position"]["x"] = 20.
    else:
        if fault in {"during_exit", "simultaneous_exit"}:
            add_action(timeline, "exit", LEADER, 5000, 6000, post="removed")
        start = 5000 if fault != "during_exit" else 5999
        add_action(timeline, "exit", BODY, start, 7000, post="removed")
    rebind(layout, timeline)
    with pytest.raises(ValueError, match="callout"):
        evaluate_frame(layout, timeline, 0)


@pytest.mark.parametrize("portrait", [False, True])
def test_callout_explicit_pointer_exit_completion_allows_exact_boundary_body_exit(portrait):
    layout, timeline = compositor_documents(portrait, boxed=True)
    add_action(timeline, "exit", LEADER, 5000, 6000, post="removed")
    add_action(timeline, "exit", BODY, 6000, 7000, post="removed")
    rebind(layout, timeline)
    for time in [0, 5999, 6000, 6500, 7000, 5999]:
        states = {s.object_id: s for s in evaluate_frame(layout, timeline, time).objects}
        if time == 5999:
            assert states[LEADER].visible and states[BODY].opacity == 1.
        if time >= 6000:
            assert not states[LEADER].visible
        if time >= 7000:
            assert not states[BODY].visible
        compose_png_frame(layout, timeline, time)


@pytest.mark.parametrize("portrait", [False, True])
def test_callout_initially_visible_pair_needs_no_invented_construction(portrait):
    layout, timeline = compositor_documents(portrait)
    for obj in layout["objects"]:
        obj.update(visible=True, initial_state="visible")
    for state in timeline["initial_object_states"]:
        state.update(visible=True, state="visible")
    # The schema requires a real action; explicit later removal, not fake construction.
    timeline["actions"] = [timeline["actions"][0]]
    add_action(timeline, "exit", LEADER, 8000, 9000, post="removed")
    timeline["actions"].pop(0)
    rebind(layout, timeline)
    assert rgba(compose_png_frame(layout, timeline, 0).png) == rgba(literal_frame(portrait, False, 0, initially_visible=True))
    frames = {t: (evaluate_frame(layout, timeline, t), compose_png_frame(layout, timeline, t))
        for t in [0, 7999, 8000, 8500, 9000]}
    for t in [9000, 0, 8500, 7999, 8000, 8500]:
        assert (evaluate_frame(layout, timeline, t), compose_png_frame(layout, timeline, t)) == frames[t]


def add_parent(layout, timeline):
    from test_v2_group_hierarchy import grouped_documents

    shell = deepcopy(grouped_documents()[0]["objects"][3])
    shell.update(child_ids=[TARGET, BODY], z_index=4)
    # origin=(0,0) is the authored bounds' top-left, not the canvas origin.
    shell["geometry"]["bounds"] = {"x": 0., "y": 0., "width": 500., "height": 650.}
    shell["transform"].update(position={"x": 40., "y": 30.}, scale_x=1.25, scale_y=.8,
        origin={"x": 0., "y": 0.})
    for obj in layout["objects"]:
        if obj["object_id"] in {TARGET, BODY}:
            obj["parent_id"] = shell["object_id"]
    layout["objects"].append(shell)
    layout["boards"][0]["object_ids"].append(shell["object_id"])
    timeline["initial_object_states"].append({"object_id": shell["object_id"], "state": "visible",
        "visible": True, "state_version": 1})
    rebind(layout, timeline)
    return shell


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("boxed", [False, True])
def test_callout_group_nonidentity_uses_outer_world_anchor_and_literal_pixels(portrait, boxed):
    layout, timeline = compositor_documents(portrait, boxed)
    add_parent(layout, timeline)
    expected = literal_frame(portrait, boxed, 4000, grouped=True)
    assert rgba(compose_png_frame(layout, timeline, 4000).png) == rgba(expected)
    frame = compose_svg_frame(layout, timeline, 4000)
    assert 'd="M 340 406 L 340 174"' in frame.svg
    assert frame == compose_svg_frame(layout, timeline, 4000)
    expected_frames = {t: (compose_svg_frame(layout, timeline, t), compose_png_frame(layout, timeline, t))
        for t in [2500, 3000, 4000]}
    for t in [4000, 2500, 3000, 4000]:
        assert (compose_svg_frame(layout, timeline, t), compose_png_frame(layout, timeline, t)) == expected_frames[t]
    parsed = ExecutableLayoutV2.model_validate(layout)
    resolved = ResolvedVisualTimelineV2.model_validate(timeline)
    inputs = verify_split_paint_inputs(parsed, {})
    sample = evaluate_frame(layout, timeline, 4000)
    frozen = _compose_validated_svg_frame(parsed, resolved, sample, {}, split_inputs=inputs)
    assert (frozen, _rasterize_svg_frame(parsed, frozen, split_inputs=inputs)) == expected_frames[4000]


@pytest.mark.parametrize("fault", ["hidden_parent", "faded_parent", "moving_parent", "moving_route_outside_bounds"])
def test_callout_actual_ancestor_readiness_and_live_geometry_are_fail_closed(fault):
    layout, timeline = compositor_documents()
    shell = add_parent(layout, timeline)
    if fault == "hidden_parent":
        shell.update(visible=False, initial_state="hidden")
        timeline["initial_object_states"][-1].update(visible=False, state="hidden")
    elif fault == "faded_parent":
        shell["opacity"] = .5
    else:
        row = add_action(timeline, "move", shell["object_id"], 4500 if fault == "moving_parent" else 1000,
            5000 if fault == "moving_parent" else 2000)
        row["action"]["destination"] = deepcopy(shell["transform"])
        row["action"]["destination"]["position"]["x"] = 41. if fault == "moving_parent" else 800.
    rebind(layout, timeline)
    with pytest.raises(ValueError, match="callout"):
        evaluate_frame(layout, timeline, 0)


@pytest.mark.parametrize("portrait", [False, True])
def test_callout_endpoint_move_before_pointer_construction_binds_actual_ready_pose(portrait):
    layout, timeline = compositor_documents(portrait, boxed=True)
    pointer = timeline["actions"][2]
    pointer["start_ms"], pointer["end_ms"] = 3200, 4200
    pointer["action"]["trigger"]["at_ms"] = 3200
    pointer["resolved_trigger"].update(source={"kind": "absolute", "at_ms": 3200},
        alignment_anchor_ms=3200, resolved_at_ms=3200)
    row = add_action(timeline, "move", BODY, 3000, 3200)
    row["action"]["destination"] = deepcopy(layout["objects"][0]["transform"])
    row["action"]["destination"]["position"]["y"] = 20.
    rebind(layout, timeline)
    actual = compose_png_frame(layout, timeline, 4200)
    assert rgba(actual.png) == rgba(literal_frame(portrait, True, 4200, moved=True))
    assert 'd="M 240 490 L 240 180"' in compose_svg_frame(layout, timeline, 4200).svg
    before = evaluate_frame(layout, timeline, 3200).object(BODY)
    assert before.transform.position.y == 20.
    assert evaluate_frame(layout, timeline, 4500).object(BODY) == before


@pytest.mark.parametrize("portrait", [False, True])
def test_callout_camera_observes_full_outer_geometry_without_mutating_endpoints(portrait):
    from test_v2_camera_action import append_camera

    layout, timeline = compositor_documents(portrait, boxed=True)
    append_camera(timeline, "callout-camera", "camera_cut", 6000, 6500, target=BODY, framing="close")
    timeline["actions"][-1]["action"].update(coverage_id="coverage-1", source_instruction_id="instruction-1",
        fallback={"fallback_id": "fallback-1", "on_failure": "block"})
    rebind(layout, timeline)
    before, after = evaluate_frame(layout, timeline, 5999), evaluate_frame(layout, timeline, 8000)
    assert before.objects == after.objects and before.camera != after.camera
    assert compose_png_frame(layout, timeline, 5999).png != compose_png_frame(layout, timeline, 8000).png
    root = ET.fromstring(compose_svg_frame(layout, timeline, 8000).svg)
    for key in (BODY, LEADER):
        assert sum(node.attrib.get("data-object-id") == key for node in root.iter()) == 1


def test_bare_legacy_callout_stays_parseable_but_cannot_paint_without_explicit_binding():
    layout, timeline = compositor_documents()
    next(obj for obj in layout["objects"] if obj["object_id"] == BODY).pop("callout_binding")
    layout["objects"] = [obj for obj in layout["objects"] if obj["object_id"] != LEADER]
    layout["boards"][0]["object_ids"].remove(LEADER)
    timeline["initial_object_states"] = [s for s in timeline["initial_object_states"] if s["object_id"] != LEADER]
    timeline["actions"].pop(2)
    rebind(layout, timeline)
    ExecutableLayoutV2.model_validate(layout)
    with pytest.raises(ValueError, match="callout_binding"):
        compose_svg_frame(layout, timeline, 0)


@pytest.mark.parametrize("target", [BODY, TARGET, "object-group"])
@pytest.mark.parametrize("start,valid", [(6000, True), (5999, False)])
def test_callout_pointer_exit_exact_boundary_gates_body_target_and_ancestor_edits(target, start, valid):
    layout, timeline = compositor_documents()
    if target == "object-group":
        add_parent(layout, timeline)
    add_action(timeline, "exit", LEADER, 5000, 6000, post="removed")
    row = add_action(timeline, "move", target, start, 6500)
    obj = next(obj for obj in layout["objects"] if obj["object_id"] == target)
    row["action"]["destination"] = deepcopy(obj["transform"])
    row["action"]["destination"]["position"]["y"] += 20.
    rebind(layout, timeline)
    if valid:
        assert not evaluate_frame(layout, timeline, 6500).object(LEADER).visible
        compose_png_frame(layout, timeline, 6500)
    else:
        with pytest.raises(ValueError, match="callout.*completed explicit pointer exit"):
            evaluate_frame(layout, timeline, 0)


def callout_group_transition(shell_id, start, end, portrait):
    from test_v2_callout_contract import binding
    from test_v2_group_annotation import annotation_group_documents

    layout, timeline = annotation_group_documents(shell_id, start, end, portrait=portrait)
    body = next(obj for obj in layout["objects"] if obj["object_id"] == BODY)
    body.update(object_type="callout", callout_binding=binding())
    write = next(row for row in timeline["actions"] if row["action"].get("annotation_policy"))
    write["action"].pop("annotation_policy")
    write["action"].update(verb="write", target_ids=[BODY], expected_state="hidden", post_state="visible")
    add_action(timeline, "draw", LEADER, 7000, 7500, "hidden")
    # Other fixture instructions keep their original coverage; append to the one we own.
    timeline["coverage"][0]["action_ids"].append(timeline["actions"][-1]["action"]["action_id"])
    timeline["actions"].sort(key=lambda row: row["start_ms"])
    timeline["layout_sha256"] = digest(layout)
    return layout, timeline


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("shell,start,end,valid", [
    ("target-group", 5000, 6000, True),
    ("target-group", 7000, 7100, False),
    ("target-group", 8000, 8100, False),
    ("unrelated-group", 7000, 7100, True),
    ("unrelated-group", 8000, 8100, True),
])
def test_callout_uses_real_structural_clock_for_public_group_frames(shell, start, end, valid, portrait):
    from atme.render.v2_connector import connector_route
    from test_v2_group_annotation import consumer_clock

    layout, timeline = callout_group_transition(shell, start, end, portrait)
    if not valid:
        with pytest.raises(ValueError, match="callout.*geometric hierarchy edit"):
            consumer_clock(layout, timeline)
        return
    context, replay, _ = consumer_clock(layout, timeline)
    sample = replay.before_action(next(row["action"]["action_id"] for row in timeline["actions"]
        if row["action"]["verb"] == "draw"))
    if shell == "target-group":
        assert shell not in sample.hierarchy.ancestors(TARGET)
    objects = sample.hierarchy.object_map(context.objects)
    states = {row.object_id: row for row in sample.objects}
    route = connector_route(objects[LEADER], objects, states, 8/3)
    # Target group's authored translation survives the actual ungroup commit.
    expected_end = (360., 430.) if portrait else (340., 340.)
    if shell == "unrelated-group":
        expected_end = (340., 420.) if portrait else (320., 330.)
    assert route.points[-1] == expected_end
    assert replay.at(9000).object(LEADER).visible
    assert replay.at(7000).object(BODY).reveal_fraction == 1.
    samples = {t: replay.at(t) for t in [6999, 7000, 7250, 7500, 9000]}
    for t in [9000, 6999, 7250, 7000, 7500, 7250]:
        assert replay.at(t) == samples[t]
    assert evaluate_frame(layout, timeline, 9000).at_ms == 9000


@pytest.mark.parametrize("valid", [False, True])
@pytest.mark.parametrize("portrait", [False, True])
def test_callout_completed_regroup_checks_actual_effective_stacking(valid, portrait):
    from atme.render.v2_hierarchy import (
        HierarchyNode,
        HierarchySnapshot,
        changed_hierarchy_objects,
    )
    from atme.store.contracts_v2 import HierarchyBasis
    from test_v2_callout_contract import binding
    from test_v2_group_annotation import consumer_clock, regroup_first_documents
    from test_v2_hierarchy_contract import rehash

    layout, timeline = regroup_first_documents(portrait=portrait)
    body = next(obj for obj in layout["objects"] if obj["object_id"] == BODY)
    body.update(object_type="callout", callout_binding=binding())
    write = next(row for row in timeline["actions"] if row["action"].get("annotation_policy"))
    write["action"].pop("annotation_policy")
    write["action"].update(verb="write", target_ids=[BODY], expected_state="hidden", post_state="visible")
    add_action(timeline, "draw", LEADER, 7000, 7500, "hidden")
    timeline["coverage"][0]["action_ids"].append(timeline["actions"][-1]["action"]["action_id"])
    group = next(row["action"] for row in timeline["actions"] if row["action"]["verb"] == "group")
    policy = group["hierarchy_policy"]
    if not valid:
        # Initially empty shell is above the callout. A valid authored regroup
        # preserves world geometry but transfers the target into that higher slot.
        for side in ("source", "destination"):
            roots = sorted((p for p in policy[f"{side}_basis"]["placements"] if p["parent_id"] is None),
                key=lambda p: p["sibling_ordinal"])
            shell = next(p for p in roots if p["object_id"] == "target-group")
            roots.remove(shell)
            roots.append(shell)
            for index, row in enumerate(roots):
                row["sibling_ordinal"] = index
        source = {p["object_id"]: p for p in policy["source_basis"]["placements"]}
        for obj in layout["objects"]:
            obj["z_index"] = source[obj["object_id"]]["sibling_ordinal"] * 10

        def hierarchy(side):
            return HierarchySnapshot(tuple(HierarchyNode(p["object_id"], p["board_id"], p["parent_id"],
                p["sibling_ordinal"]) for p in policy[f"{side}_basis"]["placements"]))

        objects = {obj.object_id: obj for obj in ExecutableLayoutV2.model_validate(layout).objects}
        policy["changed_object_ids"] = list(changed_hierarchy_objects(hierarchy("source"), hierarchy("destination"), objects))
        rehash(group)
        layout["initial_empty_group_ownership"][0]["owner_source_basis_sha256"] = policy["source_basis_sha256"]
        timeline["initial_hierarchy_basis"] = deepcopy(policy["source_basis"])
        timeline["initial_hierarchy_basis_sha256"] = HierarchyBasis.model_validate(policy["source_basis"]).checksum()
    timeline["actions"].sort(key=lambda row: row["start_ms"])
    timeline["layout_sha256"] = digest(layout)
    if not valid:
        # The stronger structural contract rejects order-changing Groups before
        # replay; do not weaken it to reach the redundant Callout observer.
        with pytest.raises(ValueError, match="hierarchy transition changes effective leaf paint order"):
            consumer_clock(layout, timeline)
    else:
        context, replay, _ = consumer_clock(layout, timeline)
        sample = replay.at(7000)
        assert sample.hierarchy.ancestors(TARGET)[0] == "target-group"
        order = sample.hierarchy.paint_order(sample.hierarchy.object_map(context.objects), "board-main")
        assert order.index(TARGET) < order.index(BODY) and order.index(TARGET) < order.index(LEADER)
        assert replay.at(9000).object(LEADER).visible


def causal_documents():
    layout, timeline = compositor_documents()
    body = deepcopy(next(obj for obj in layout["objects"] if obj["object_id"] == BODY))
    body.pop("callout_binding")
    body.update(object_id="later-note", object_type="text", text="Later evidence")
    pointer = deepcopy(next(obj for obj in layout["objects"] if obj["object_id"] == LEADER))
    pointer.update(object_id="later-leader", source_object_id="later-note", z_index=8)
    layout["objects"].extend((body, pointer))
    layout["boards"][0]["object_ids"].extend(("later-note", "later-leader"))
    for key in ("later-note", "later-leader"):
        timeline["initial_object_states"].append({"object_id": key, "state": "hidden", "visible": False,
            "state_version": 1})
    future = add_action(timeline, "annotate", TARGET, 7500, 8500)
    future["action"]["annotation_policy"] = {"annotation_object_ids": ["later-note"], "readable_hold_ms": 500,
        "leader_connector_id": "later-leader", "phases": [
            {"object_id": "later-note", "mode": "write", "weight": 1},
            {"object_id": "later-leader", "mode": "draw", "weight": 1}]}
    rebind(layout, timeline)
    return layout, timeline


def test_callout_causal_consumer_keeps_full_ownership_inventory_without_executing_future_annotation():
    from atme.render.v2_hierarchy import HierarchySnapshot
    from atme.render.v2_state import _validate_consumer_history, _validate_pair_static

    layout, timeline = causal_documents()
    parsed = ExecutableLayoutV2.model_validate(layout)
    full = ResolvedVisualTimelineV2.model_validate(timeline)
    prefix = full.model_copy(update={"actions": full.actions[:3]})
    hierarchy = HierarchySnapshot.from_objects({obj.object_id: obj for obj in parsed.objects})
    context = _validate_pair_static(parsed, prefix, digest(layout), hierarchy, structural_timeline=full)
    replay, _ = _validate_consumer_history(context)
    assert replay.at(9000).object(LEADER).visible
    assert not replay.at(9000).object("later-note").visible
    assert not replay.at(9000).object("later-leader").visible
    # Without a causal receipt prefix the actual later annotation does execute.
    final = evaluate_frame(layout, timeline, 9000)
    assert final.object(LEADER).visible and final.object("later-note").visible
    assert final.object("later-leader").visible


@pytest.mark.parametrize("fault", ["double_owner", "orphan"])
def test_callout_full_static_ownership_still_rejects_future_conflict_or_actual_orphan(fault):
    from atme.render.v2_hierarchy import HierarchySnapshot
    from atme.render.v2_state import _validate_pair_static

    layout, timeline = causal_documents()
    if fault == "double_owner":
        policy = timeline["actions"][-1]["action"]["annotation_policy"]
        policy.update(annotation_object_ids=[BODY], leader_connector_id=LEADER,
            phases=[{"object_id": BODY, "mode": "write", "weight": 1},
                    {"object_id": LEADER, "mode": "draw", "weight": 1}])
        # No unrelated orphan masks the exact future ownership conflict.
        layout["objects"] = [o for o in layout["objects"] if o["object_id"] not in {"later-note", "later-leader"}]
        layout["boards"][0]["object_ids"] = [o["object_id"] for o in layout["objects"]]
        timeline["initial_object_states"] = [s for s in timeline["initial_object_states"]
            if s["object_id"] not in {"later-note", "later-leader"}]
        # Keep the future annotation's notes genuinely hidden. The defect here
        # is dual declared ownership, not an already-constructed note precondition.
        timeline["actions"] = [timeline["actions"][0], timeline["actions"][-1]]
    else:
        timeline["actions"].pop()
    rebind(layout, timeline)
    parsed = ExecutableLayoutV2.model_validate(layout)
    full = ResolvedVisualTimelineV2.model_validate(timeline)
    prefix = full.model_copy(update={"actions": full.actions[:1]})
    hierarchy = HierarchySnapshot.from_objects({obj.object_id: obj for obj in parsed.objects})
    match = "callout and annotation cannot both own" if fault == "double_owner" else "pointer has no explicit"
    with pytest.raises(ValueError, match=match):
        _validate_pair_static(parsed, prefix, digest(layout), hierarchy, structural_timeline=full)
