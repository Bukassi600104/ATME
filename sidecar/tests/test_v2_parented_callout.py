"""The approved parent-local Callout leader uses the same native SVG tree."""
import xml.etree.ElementTree as ET
from copy import deepcopy
from dataclasses import replace

import pytest
from atme.render.v2_svg import (
    _rasterize_svg_frame,
    compose_png_frame,
    compose_svg_frame,
)
from atme.render.v2_world import transform_svg
from atme.store import contracts_v2 as contracts
from test_v2_callout_compositor import (
    BODY,
    LEADER,
    TARGET,
    add_action,
    compositor_documents,
    rebind,
)
from test_v2_group_hierarchy import grouped_documents

SVG = "http://www.w3.org/2000/svg"


def parented_documents(portrait=False, initially_visible=True):
    plain, clock = compositor_documents(portrait, boxed=True)
    if initially_visible:
        for obj in plain["objects"]:
            obj.update(initial_state="visible", visible=True)
        for state in clock["initial_object_states"]:
            state.update(state="visible", visible=True)
        clock["actions"] = clock["actions"][:1]
        add_action(clock, "exit", LEADER, 8000, 9000, post="removed")
        clock["actions"].pop(0)
        rebind(plain, clock)
    layout, timeline = deepcopy(plain), deepcopy(clock)
    shell = deepcopy(grouped_documents()[0]["objects"][3])
    shell.update(object_id="callout-parent", child_ids=[TARGET, BODY, LEADER], z_index=0)
    shell["geometry"]["bounds"] = {"x": 0., "y": 0., "width": 500., "height": 650.}
    shell["transform"].update(position={"x": 30., "y": 20.}, scale_x=1.1, scale_y=.9,
                              rotation_degrees=7., origin={"x": .2, "y": .6})
    for obj in layout["objects"]:
        obj["parent_id"] = shell["object_id"]
    layout["objects"].append(shell)
    layout["boards"][0]["object_ids"].append(shell["object_id"])
    timeline["initial_object_states"].append({"object_id": shell["object_id"], "state": "visible",
                                             "visible": True, "state_version": 1})
    rebind(layout, timeline)
    return plain, clock, layout, timeline, shell


def native_parent_oracle(plain, clock, shell, at_ms):
    frame = compose_svg_frame(plain, clock, at_ms)
    tree = ET.fromstring(frame.svg)
    group = contracts.GroupContainer.model_validate(shell)
    wrapper = ET.Element(f"{{{SVG}}}g", {"transform": transform_svg(group, group.transform)})
    for child in list(tree):
        if child.attrib.get("data-object-id") in {TARGET, BODY, LEADER}:
            tree.remove(child)
            wrapper.append(child)
    tree.append(wrapper)
    return _rasterize_svg_frame(contracts.ExecutableLayoutV2.model_validate(plain),
        replace(frame, svg=ET.tostring(tree, encoding="unicode"))).png


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("initially_visible", [True, False])
def test_callout_owned_leader_can_paint_in_its_authored_nonidentity_group_parent(portrait, initially_visible):
    plain, clock, layout, timeline, shell = parented_documents(portrait, initially_visible)
    at_ms = 0 if initially_visible else 4000
    # The preexisting unparented leader is a genuine working baseline, not a
    # failing fixture whose contract would be weakened to obtain a green test.
    assert compose_png_frame(plain, clock, at_ms).png
    expected = native_parent_oracle(plain, clock, shell, at_ms)
    original = deepcopy((layout, timeline))
    contracts.ExecutableLayoutV2.model_validate(layout)
    assert compose_png_frame(layout, timeline, at_ms).png == expected
    assert (layout, timeline) == original


@pytest.mark.parametrize("validator", ["annotation", "owned_pointer"])
def test_callout_parent_admission_does_not_extend_generic_or_annotation_pointer_validation(validator):
    from atme.render.v2_callout_pointer import validate_callout_pointer
    from atme.render.v2_connector import validate_owned_pointer, validate_static_arrow

    _p, _c, layout, _t, _s = parented_documents()
    objects = {obj.object_id: obj for obj in contracts.ExecutableLayoutV2.model_validate(layout).objects}
    assert validate_callout_pointer(objects[LEADER], objects).object_id == BODY
    with pytest.raises(ValueError, match="ignored geometry or styling"):
        if validator == "annotation":
            validate_static_arrow(objects[LEADER], objects, annotation_pointer=True)
        else:
            validate_owned_pointer(objects[LEADER], objects)


@pytest.mark.parametrize("fault", ["unowned", "source", "destination", "anchor", "own_transform", "clipped_parent", "nonreciprocal"])
def test_parented_pointer_reauthenticates_exact_owner_payload_and_ordinary_ancestry(fault):
    from atme.render.v2_callout_pointer import validate_callout_pointer

    _p, _c, layout, _t, shell = parented_documents()
    objects = {obj.object_id: obj for obj in contracts.ExecutableLayoutV2.model_validate(layout).objects}
    pointer = objects[LEADER]
    assert validate_callout_pointer(pointer, objects).object_id == BODY
    if fault == "unowned":
        objects[BODY].callout_binding = None
    elif fault == "source":
        pointer.source_object_id = TARGET
    elif fault == "destination":
        pointer.destination_object_id = BODY
    elif fault == "anchor":
        pointer.source_anchor_id = "not-the-bound-anchor"
    elif fault == "own_transform":
        pointer.transform.position.x = 1.
    elif fault == "clipped_parent":
        objects[shell["object_id"]].clip_id = "external-aperture"
    else:
        objects[shell["object_id"]].child_ids.remove(LEADER)
    with pytest.raises(ValueError, match="(?i)callout pointer|unsupported independent transform"):
        validate_callout_pointer(pointer, objects)


def only_leader_parent(layout, timeline, shell):
    for obj in layout["objects"]:
        if obj["object_id"] in {BODY, TARGET}:
            obj["parent_id"] = None
        if obj["object_id"] == LEADER:
            obj["geometry"]["bounds"] = {"x": -100., "y": -100., "width": 1200., "height": 1200.}
    shell.update(child_ids=[LEADER], z_index=100)
    rebind(layout, timeline)


@pytest.mark.parametrize("prior", [False, True])
def test_leader_only_parent_is_reserved_while_pointer_paints_but_may_move_before_construction(prior):
    from atme.render.v2_state import evaluate_frame

    _p, _c, layout, timeline, shell = parented_documents(initially_visible=not prior)
    only_leader_parent(layout, timeline, shell)
    evaluate_frame(layout, timeline, 4000)
    move = add_action(timeline, "move", shell["object_id"], 1000, 1500)
    move["action"]["destination"] = deepcopy(shell["transform"])
    move["action"]["destination"]["position"]["x"] += 15.
    rebind(layout, timeline)
    if prior:
        assert evaluate_frame(layout, timeline, 4000).object(LEADER).visible
        assert compose_png_frame(layout, timeline, 4000).png
    else:
        with pytest.raises(ValueError, match="callout.*pointer exit before endpoint edits"):
            evaluate_frame(layout, timeline, 0)


@pytest.mark.parametrize("fault", ["hidden", "opacity"])
def test_leader_only_ancestor_must_be_fully_ready_for_an_initially_visible_pointer(fault):
    from atme.render.v2_state import evaluate_frame

    _p, _c, layout, timeline, shell = parented_documents()
    only_leader_parent(layout, timeline, shell)
    evaluate_frame(layout, timeline, 0)
    if fault == "hidden":
        shell.update(initial_state="hidden", visible=False)
        timeline["initial_object_states"][-1].update(state="hidden", visible=False)
    else:
        shell["opacity"] = .5
    rebind(layout, timeline)
    with pytest.raises(ValueError, match="callout.*fully ready endpoints and parents"):
        evaluate_frame(layout, timeline, 0)


@pytest.mark.parametrize("portrait", [False, True])
def test_split_body_adapter_authenticates_parented_removed_source_and_hidden_result_leaders_without_painting_them(portrait):
    from atme.render.v2_split import capture_split
    from atme.render.v2_split_paint import (
        split_family_admission,
        verify_split_paint_inputs,
    )
    from test_v2_split_callout_family import callout_split_fixture

    layout, _initial, before, _prefix, split, _timeline, hashes = callout_split_fixture(portrait, leader_parent=True)
    capture = capture_split(split, layout, before, {})
    assert "leader-stage" in capture.read_dependency_ids
    assert before.object("leader-source").state == "removed"
    assert before.object("leader-part-1").state == "hidden"
    inputs = verify_split_paint_inputs(layout, {})
    for key in ("source", "part-1", "part-2"):
        admission = split_family_admission(key, capture, layout, inputs)
        assert admission.family == "text" and admission.content_sha256 == hashes[key]


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("prior_move", [False, True])
def test_noncommuting_nested_leader_parent_projects_actual_world_anchors_once(portrait, prior_move, tmp_path):
    from atme.render.v2_callout_pointer import callout_pointer_route
    from atme.render.v2_state import evaluate_frame

    _p, _c, layout, timeline, inner = parented_documents(portrait, initially_visible=not prior_move)
    only_leader_parent(layout, timeline, inner)
    inner.update(parent_id="pointer-outer", z_index=0)
    inner["transform"].update(position={"x": 20., "y": 10.}, scale_x=.5, scale_y=3.,
                              rotation_degrees=0., origin={"x": 0., "y": 0.})
    outer = deepcopy(inner)
    outer.update(object_id="pointer-outer", parent_id=None, child_ids=[inner["object_id"]], z_index=100)
    outer["transform"].update(position={"x": 100., "y": 50.}, scale_x=2., scale_y=1., rotation_degrees=90.)
    layout["objects"].append(outer)
    layout["boards"][0]["object_ids"].append(outer["object_id"])
    timeline["initial_object_states"].append({"object_id": outer["object_id"], "state": "visible", "visible": True, "state_version": 1})
    leader = next(obj for obj in layout["objects"] if obj["object_id"] == LEADER)
    leader["geometry"]["bounds"] = {"x": 50., "y": -100., "width": 500., "height": 200.}
    if prior_move:
        row = add_action(timeline, "move", outer["object_id"], 1000, 1500)
        row["action"]["destination"] = deepcopy(outer["transform"])
        row["action"]["destination"]["position"]["x"] += 30.
    rebind(layout, timeline)
    at_ms = 4000 if prior_move else 0
    frame = evaluate_frame(layout, timeline, at_ms)
    typed = contracts.ExecutableLayoutV2.model_validate(layout)
    objects = frame.hierarchy.object_map({obj.object_id: obj for obj in typed.objects})
    route = callout_pointer_route(objects[LEADER], objects, {row.object_id: row for row in frame.objects}, 2.6667)
    # Independent literal full-world map: (x,y) -> (90-3y,90+x),
    # with +30world-x after the actual completed outer move. The unparented
    # endpoint anchors are (240,470) and (240,180), not an AABB or local guess.
    y = -40. if prior_move else -50.
    assert route.points == ((380., y), (90., y))
    assert route.head == ((104., y-6.), (104., y+6.))
    svg = compose_svg_frame(layout, timeline, at_ms)
    assert f'd="M 380 {int(y)} L 90 {int(y)}"' in svg.svg
    (tmp_path / "nested-callout.png").write_bytes(compose_png_frame(layout, timeline, at_ms).png)


@pytest.mark.parametrize("portrait", [False, True])
def test_validated_callout_history_sampling_and_native_frozen_paint_have_offline_shuffled_pixel_parity(portrait, monkeypatch):
    import socket
    from pathlib import Path

    from atme.render.v2_hierarchy import HierarchySnapshot
    from atme.render.v2_split_paint import verify_split_paint_inputs
    from atme.render.v2_state import _sample_validated_frame, _validate_pair
    from atme.render.v2_svg import _compose_validated_svg_frame
    from v2_fixtures import digest

    _p, _c, layout, timeline, _s = parented_documents(portrait)
    original = deepcopy((layout, timeline))
    times = (0, 7999, 8500, 9000)
    expected = {at: compose_png_frame(layout, timeline, at).png for at in times}
    typed = contracts.ExecutableLayoutV2.model_validate(layout)
    clock = contracts.ResolvedVisualTimelineV2.model_validate(timeline)
    inputs = verify_split_paint_inputs(typed, {})
    replay, camera = _validate_pair(typed, clock, digest(layout),
        HierarchySnapshot.from_objects({obj.object_id: obj for obj in typed.objects}))

    def forbidden(*args, **kwargs):
        raise AssertionError("frozen Callout sample/paint reopened original files or network")

    original_open = Path.open

    def write_only(path, mode="r", *args, **kwargs):
        if "r" in mode or "+" in mode or not any(flag in mode for flag in ("w", "a", "x")):
            forbidden()
        return original_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", write_only)
    monkeypatch.setattr(Path, "read_bytes", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    for at in (9000, 0, 8500, 7999, 0):
        sample = _sample_validated_frame(typed, clock, replay, camera, at)
        svg = _compose_validated_svg_frame(typed, clock, sample, {}, split_inputs=inputs)
        assert _rasterize_svg_frame(typed, svg, split_inputs=inputs).png == expected[at]
    assert (layout, timeline) == original
