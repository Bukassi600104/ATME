"""Real item progression must use one owned, captured chronological operator."""

import io
from copy import deepcopy

import pytest
import resvg_py
from atme.render.style_bundle import load_bundle
from atme.render.v2_state import evaluate_frame
from atme.render.v2_svg import (
    _compose_validated_svg_frame,
    _rasterize_svg_frame,
    compose_png_frame,
    compose_svg_frame,
)
from PIL import Image
from test_v2_group_annotation import consumer_clock
from test_v2_progressive_list import list_documents
from test_v2_structured_list_compositor import native_documents
from test_v2_structured_list_contract import payload
from test_v2_structured_list_policy import action
from v2_fixtures import digest


def runtime_documents(portrait=False):
    layout, timeline = native_documents(portrait)
    for obj in layout["objects"]:
        if obj["object_id"] == "object-evidence":
            obj.update(visible=True, initial_state="visible")
        elif obj["object_type"] == "text":
            obj.update(visible=False, initial_state="hidden")
    row = deepcopy(list_documents()[1]["actions"][2])
    row["action"] = action()
    timeline["actions"] = [row]
    timeline["initial_object_states"] = [{"object_id": obj["object_id"], "state": obj["initial_state"],
        "state_version": 1, "visible": obj["visible"]} for obj in layout["objects"]]
    timeline["layout_sha256"] = digest(layout)
    return layout, timeline


@pytest.mark.parametrize("portrait", [False, True])
def test_whole_item_steps_and_outer_commit_use_one_shared_replay_clock(portrait):
    layout, timeline = runtime_documents(portrait)
    _, replay, _ = consumer_clock(layout, timeline)
    expected = {4000: (), 4224: (), 4225: ("list-item-a",), 4674: ("list-item-a",),
        4675: ("list-item-a", "list-item-b"), 4899: ("list-item-a", "list-item-b"),
        4900: tuple(payload()["item_object_ids"])}
    retained = {}
    for at_ms, visible in expected.items():
        sample = replay.at(at_ms)
        states = {obj.object_id: obj for obj in sample.objects}
        versions = dict(sample.state_versions)
        for key in payload()["item_object_ids"]:
            assert states[key].visible == (key in visible)
            assert states[key].reveal_fraction == (1 if key in visible else 0)
            assert states[key].state == ("visible" if at_ms == 4900 else "hidden")
            assert versions[key] == (2 if at_ms == 4900 else 1)
        assert versions["object-evidence"] == versions["list-group"] == 1
        assert states["object-evidence"].visible and states["list-group"].visible
        public = evaluate_frame(layout, timeline, at_ms)
        assert {obj.object_id: obj.visible for obj in public.objects} == {
            key: obj.visible for key, obj in states.items()}
        retained[at_ms] = sample
    for at_ms in (4900, 4000, 4675, 4224, 4899, 4225, 4674, 4900):
        assert replay.at(at_ms) == retained[at_ms]


def add_move(timeline, layout, target, start_ms, end_ms, *, expected_state="hidden"):
    obj = next(obj for obj in layout["objects"] if obj["object_id"] == target)
    destination = deepcopy(obj["transform"])
    destination["position"]["x"] = 20
    raw = action()
    for name in ("structured_list_policy", "annotation"):
        raw.pop(name)
    raw.update(action_id="move-one", verb="move", target_ids=[target], expected_state=expected_state,
        post_state=expected_state or "visible", destination=destination, opacity=None)
    row = deepcopy(timeline["actions"][0])
    row.update(action=raw, start_ms=start_ms, end_ms=end_ms)
    row["resolved_trigger"].update(resolved_at_ms=0, alignment_anchor_ms=0,
        matched_text=None, matched_occurrence=None)
    raw["trigger"] = row["resolved_trigger"]["source"] = {"kind": "absolute", "at_ms": 0}
    timeline["actions"].append(row)
    timeline["actions"].sort(key=lambda item: item["start_ms"])
    timeline["coverage"][0]["action_ids"].append(raw["action_id"])


@pytest.mark.parametrize("stale", [False, True])
def test_policy_authenticates_actual_start_versions_after_valid_prior_pose_history(stale):
    layout, timeline = runtime_documents()
    add_move(timeline, layout, "list-item-a", 100, 200)
    policy = next(row for row in timeline["actions"] if row["action"]["verb"] == "progressive_reveal")[
        "action"]["structured_list_policy"]
    policy["expected_item_state_versions"]["list-item-a"] = 1 if stale else 2
    if stale:
        with pytest.raises(ValueError, match="version"):
            consumer_clock(layout, timeline)
    else:
        _, replay, _ = consumer_clock(layout, timeline)
        sample = replay.at(4900)
        assert dict(sample.state_versions)["list-item-a"] == 3
        assert next(obj for obj in sample.objects if obj.object_id == "list-item-a").transform.position.x == 20


@pytest.mark.parametrize("target", ["list-item-a", "object-evidence", "list-group"])
def test_policy_reserves_items_and_read_dependencies_for_the_whole_outer_interval(target):
    layout, timeline = runtime_documents()
    add_move(timeline, layout, target, 4100, 4200, expected_state=None)
    with pytest.raises(ValueError, match="overlap|reserved|dependency"):
        consumer_clock(layout, timeline)


def test_independent_item_edit_after_outer_completion_uses_same_id_pose_and_next_version():
    layout, timeline = runtime_documents()
    add_move(timeline, layout, "list-item-b", 4900, 5000, expected_state="visible")
    _, replay, _ = consumer_clock(layout, timeline)
    sample = replay.at(5000)
    versions = dict(sample.state_versions)
    assert versions["list-item-b"] == 3
    assert versions["list-item-a"] == versions["list-item-c"] == 2
    assert versions["object-evidence"] == versions["list-group"] == 1
    assert next(obj for obj in sample.objects if obj.object_id == "list-item-b").transform.position.x == 20


def rgba(png):
    with Image.open(io.BytesIO(png)) as image:
        return image.convert("RGBA").tobytes()


@pytest.mark.parametrize("portrait", [False, True])
def test_structured_steps_have_literal_whole_item_pixels_and_seek_parity(portrait):
    layout, timeline = runtime_documents(portrait)
    _, _, root = load_bundle()
    width, height = (720, 1280) if portrait else (1280, 720)
    x, y = (90, 280) if portrait else (80, 100)
    frames = {}
    for at_ms, count in ((4000, 0), (4224, 0), (4225, 1), (4674, 1), (4675, 2), (4900, 3)):
        values = ("The process", "Gather evidence", "Explain the change", "Return to the model")[:1+count]
        text = "".join(f'<text x="{x}" y="{y+40*index+21.3333:.4f}" fill="#172033" '
            'font-family="Atkinson Hyperlegible" font-weight="400" font-size="21.3333" '
            f'xml:space="preserve">{value}</text>' for index, value in enumerate(values))
        literal = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">'
            f'<rect width="{width}" height="{height}" fill="#FAF8F1"/>{text}</svg>')
        expected = bytes(resvg_py.svg_to_bytes(svg_string=literal,
            font_files=[str(root / "fonts/AtkinsonHyperlegible-Regular.otf")], skip_system_fonts=True))
        png = compose_png_frame(layout, timeline, at_ms).png
        assert rgba(png) == rgba(expected)
        svg = compose_svg_frame(layout, timeline, at_ms).svg
        assert 'clip-path="url(#' not in svg
        frames[at_ms] = (svg, png)
    for at_ms in (4900, 4000, 4675, 4224, 4674, 4225, 4900):
        assert (compose_svg_frame(layout, timeline, at_ms).svg,
            compose_png_frame(layout, timeline, at_ms).png) == frames[at_ms]


@pytest.mark.parametrize("target,change", [
    ("object-evidence", {"visible": False, "initial_state": "hidden"}),
    ("object-evidence", {"visible": True, "initial_state": "hidden"}),
    ("object-evidence", {"opacity": 0}),
    ("list-group", {"visible": False, "initial_state": "hidden"}),
    ("list-group", {"opacity": 0}),
    ("list-item-a", {"visible": True, "initial_state": "visible"}),
    ("list-item-a", {"opacity": 0}),
])
def test_structured_capture_rejects_unready_heading_ancestors_or_items(target, change):
    layout, timeline = runtime_documents()
    obj = next(obj for obj in layout["objects"] if obj["object_id"] == target)
    obj.update(change)
    initial = next(row for row in timeline["initial_object_states"] if row["object_id"] == target)
    initial.update(visible=obj["visible"], state=obj["initial_state"])
    timeline["layout_sha256"] = digest(layout)
    with pytest.raises(ValueError, match="structured list|precondition"):
        consumer_clock(layout, timeline)


def outer_documents():
    layout, timeline = runtime_documents()
    root = next(obj for obj in layout["objects"] if obj["object_id"] == "list-group")
    outer = deepcopy(root)
    outer.update(object_id="outer-group", child_ids=["list-group"], parent_id=None)
    root["parent_id"] = "outer-group"
    layout["objects"].append(outer)
    layout["boards"][0]["object_ids"].append(outer["object_id"])
    layout["boards"][0]["density_limit"] = 6
    timeline["initial_object_states"].append({"object_id": outer["object_id"], "state": "visible",
        "visible": True, "state_version": 1})
    timeline["layout_sha256"] = digest(layout)
    return layout, timeline


def test_outer_ancestor_read_reservation_covers_the_entire_policy_interval():
    layout, timeline = outer_documents()
    add_move(timeline, layout, "outer-group", 4100, 4200, expected_state=None)
    with pytest.raises(ValueError, match="reserved|dependency"):
        consumer_clock(layout, timeline)


@pytest.mark.parametrize("portrait", [False, True])
def test_structured_step_source_and_frozen_compositors_have_exact_parity(portrait):
    from atme.render.v2_split_paint import verify_split_paint_inputs

    raw, resolved = runtime_documents(portrait)
    context, _, _ = consumer_clock(raw, resolved)
    inputs = verify_split_paint_inputs(context.layout, {})
    for at_ms in (4000, 4225, 4675, 4900):
        snapshot = evaluate_frame(raw, resolved, at_ms)
        frozen = _compose_validated_svg_frame(context.layout, context.timeline, snapshot, {}, split_inputs=inputs)
        assert frozen == compose_svg_frame(raw, resolved, at_ms)
        assert _rasterize_svg_frame(context.layout, frozen, split_inputs=inputs) == compose_png_frame(raw, resolved, at_ms)


@pytest.mark.parametrize("fault", ["subclass", "unknown_field"])
def test_private_replay_cannot_discard_bypass_constructed_policy_phase_data(fault):
    from atme.render.v2_timeline_replay import replay_chronology
    from atme.store.contracts_v2 import StructuredListPhase

    layout, timeline = runtime_documents()
    context, _, _ = consumer_clock(layout, timeline)
    phase = context.timeline.actions[0].action.structured_list_policy.phases[0]
    if fault == "subclass":
        class UnknownPhase(StructuredListPhase):
            pass
        context.timeline.actions[0].action.structured_list_policy.phases[0] = UnknownPhase.model_validate(
            phase.model_dump(mode="json"))
    else:
        phase.__dict__["invented_part"] = "not authored"
    with pytest.raises(ValueError, match="unknown|stored fields"):
        replay_chronology(context.objects, context.hierarchy,
            {frame.object_id: frame for frame in context.frames},
            {key: initial.state_version for key, initial in context.initial.items()},
            tuple(context.timeline.actions), (("board-main", 0, 10000),), 10000)


def test_private_replay_requires_one_authoritative_active_board_interval():
    from atme.render.v2_timeline_replay import replay_chronology

    layout, timeline = runtime_documents()
    context, _, _ = consumer_clock(layout, timeline)
    with pytest.raises(ValueError, match="active board"):
        replay_chronology(context.objects, context.hierarchy,
            {frame.object_id: frame for frame in context.frames},
            {key: initial.state_version for key, initial in context.initial.items()},
            tuple(context.timeline.actions), (("board-main", 0, 4225), ("board-main", 4225, 10000)), 10000)


def prior_group_documents():
    from dataclasses import replace

    from atme.render.v2_hierarchy import HierarchySnapshot, changed_hierarchy_objects
    from atme.render.v2_hierarchy_replay import completed_hierarchy_basis
    from atme.render.v2_state import FramePoint, FrameTransform

    layout, timeline = outer_documents()
    root = next(obj for obj in layout["objects"] if obj["object_id"] == "list-group")
    outer = next(obj for obj in layout["objects"] if obj["object_id"] == "outer-group")
    root["transform"]["position"]["x"] = -40
    outer["transform"]["position"]["x"] = 40
    outer["initial_state"] = "grouped"
    next(row for row in timeline["initial_object_states"] if row["object_id"] == "outer-group")["state"] = "grouped"
    timeline["layout_sha256"] = digest(layout)
    context, _, _ = consumer_clock(layout, timeline)
    frames = {obj.object_id: obj for obj in context.frames}
    before = context.hierarchy
    after = HierarchySnapshot(tuple(replace(node, parent_id=None, sibling_ordinal=0)
        if node.object_id == "list-group" else replace(node, sibling_ordinal=1)
        if node.object_id == "outer-group" else node for node in before.nodes))
    after_frames = dict(frames)
    after_frames["list-group"] = replace(frames["list-group"], transform=FrameTransform(
        FramePoint(0, 0), 1, 1, 0, FramePoint(.5, .5)))
    source = completed_hierarchy_basis(before, frames)
    destination = completed_hierarchy_basis(after, after_frames)
    raw = action()
    for name in ("structured_list_policy", "annotation"):
        raw.pop(name)
    raw.update(action_id="ungroup-list", verb="ungroup", target_ids=["list-group"],
        container_id="outer-group", expected_state="grouped", post_state="ungrouped", easing="step",
        trigger={"kind": "absolute", "at_ms": 0}, hierarchy_policy={"member_root_ids": ["list-group"],
            "source_basis": source.model_dump(mode="json"), "destination_basis": destination.model_dump(mode="json"),
            "source_basis_sha256": source.checksum(), "destination_basis_sha256": destination.checksum(),
            "changed_object_ids": list(changed_hierarchy_objects(before, after, context.objects)),
            "preserve_world_transform": True})
    row = deepcopy(timeline["actions"][0])
    row.update(action=raw, start_ms=100, end_ms=200,
        resolved_trigger={"source": raw["trigger"], "resolved_at_ms": 0, "alignment_anchor_ms": 0,
            "matched_text": None, "matched_occurrence": None, "confidence": 1, "exact": True})
    timeline["initial_hierarchy_basis"] = source.model_dump(mode="json")
    timeline["initial_hierarchy_basis_sha256"] = source.checksum()
    timeline["actions"].insert(0, row)
    timeline["coverage"][0]["action_ids"].append(raw["action_id"])
    timeline["actions"][1]["action"]["structured_list_policy"]["expected_item_state_versions"] = {
        key: 2 for key in payload()["item_object_ids"]}
    return layout, timeline


@pytest.mark.parametrize("stale", [False, True])
def test_structured_capture_uses_actual_post_group_hierarchy_pose_and_versions(stale):
    layout, timeline = prior_group_documents()
    if stale:
        timeline["actions"][1]["action"]["structured_list_policy"]["expected_item_state_versions"]["list-item-a"] = 1
        with pytest.raises(ValueError, match="version"):
            consumer_clock(layout, timeline)
    else:
        _, replay, _ = consumer_clock(layout, timeline)
        at_start, complete = replay.at(4000), replay.at(4900)
        assert at_start.hierarchy.ancestors("list-item-a") == ("list-group",)
        assert complete.hierarchy == at_start.hierarchy
        assert dict(complete.state_versions)["list-group"] == dict(complete.state_versions)["object-evidence"] == 2
        for key in payload()["item_object_ids"]:
            assert dict(at_start.state_versions)[key] == 2
            assert dict(complete.state_versions)[key] == 3


def private_clock(layout, timeline):
    from atme.render.v2_hierarchy import HierarchySnapshot
    from atme.render.v2_state import FrameObject, FrameTransform
    from atme.render.v2_timeline_replay import replay_chronology
    from atme.store.contracts_v2 import ExecutableLayoutV2, ResolvedVisualTimelineV2

    parsed = ExecutableLayoutV2.model_validate(layout)
    resolved = ResolvedVisualTimelineV2.model_validate(timeline)
    objects = {obj.object_id: obj for obj in parsed.objects}
    return replay_chronology(objects, HierarchySnapshot.from_objects(objects),
        {key: FrameObject(key, obj.board_id, obj.initial_state, obj.visible, obj.opacity,
            1.0 if obj.visible else 0.0, FrameTransform.from_contract(obj.transform)) for key, obj in objects.items()},
        {row.object_id: row.state_version for row in resolved.initial_object_states},
        tuple(resolved.actions), tuple((row.board_id, row.start_ms, row.end_ms) for row in parsed.activations),
        resolved.duration_ms)


def add_object(layout, timeline, obj):
    layout["objects"].append(obj)
    layout["boards"][0]["object_ids"].append(obj["object_id"])
    layout["boards"][0]["density_limit"] = len(layout["objects"])
    timeline["initial_object_states"].append({"object_id": obj["object_id"], "state": obj["initial_state"],
        "visible": obj["visible"], "state_version": 1})
    timeline["layout_sha256"] = digest(layout)


def peer_read_documents(kind):
    from test_v2_annotation_contract import annotation_documents
    from test_v2_connector_svg import connector_documents

    layout, timeline = runtime_documents()
    row = deepcopy(timeline["actions"][0])
    if kind == "annotation":
        _, source, example = annotation_documents()
        note = deepcopy(next(obj for obj in source["objects"] if obj["object_id"] == "annotation-note"))
        note.update(beat_id="beat-002", coverage_ids=["coverage-3"])
        add_object(layout, timeline, note)
        raw = deepcopy(example["actions"][-1]["action"])
        raw.update(action_id="read-one-item", source_instruction_id="instruction-3", coverage_id="coverage-3",
            fallback={"fallback_id": "fallback-3", "on_failure": "block"}, target_ids=["list-item-a"])
    else:
        arrow = deepcopy(next(obj for obj in connector_documents()[0]["objects"] if obj["object_type"] == "arrow"))
        heading = next(obj for obj in layout["objects"] if obj["object_id"] == "object-evidence")
        arrow.update(beat_id="beat-002", coverage_ids=["coverage-3"], initial_state="disconnected", visible=False,
            source_object_id=heading["object_id"], source_anchor_id=heading["anchors"][0]["anchor_id"],
            destination_object_id="list-item-a", destination_anchor_id="item-center")
        arrow["geometry"]["bounds"] = {"x": 300, "y": 90, "width": 80, "height": 100}
        add_object(layout, timeline, arrow)
        raw = action()
        for name in ("structured_list_policy", "target_ids", "annotation"):
            raw.pop(name)
        raw.update(action_id="read-one-item", verb="connect", connector_id=arrow["object_id"],
            source_object_id=arrow["source_object_id"], source_anchor_id=arrow["source_anchor_id"],
            destination_object_id=arrow["destination_object_id"], destination_anchor_id=arrow["destination_anchor_id"],
            expected_state="disconnected", post_state="connected")
    raw["trigger"] = {"kind": "absolute", "at_ms": 4300}
    row.update(action=raw, start_ms=4300, end_ms=4400,
        resolved_trigger={"source": raw["trigger"], "resolved_at_ms": 4300, "alignment_anchor_ms": 4300,
            "matched_text": None, "matched_occurrence": None, "confidence": 1, "exact": True})
    timeline["actions"].append(row)
    timeline["coverage"][0]["action_ids"].append(raw["action_id"])
    return layout, timeline


@pytest.mark.parametrize("kind", ["annotation", "connector"])
def test_structured_owned_items_cannot_be_read_by_overlapping_retained_consumers(kind):
    layout, timeline = peer_read_documents(kind)
    with pytest.raises(ValueError, match="reserved|reservation"):
        private_clock(layout, timeline)


def test_read_only_camera_can_observe_structured_progression_without_mutating_versions():
    from test_v2_camera_action import append_camera

    layout, timeline = runtime_documents()
    append_camera(timeline, "observe-list", "camera_cut", 4100, 4800,
        target="object-evidence", framing="wide")
    raw = next(row["action"] for row in timeline["actions"] if row["action"]["action_id"] == "observe-list")
    raw.update(coverage_id="coverage-3", source_instruction_id="instruction-3",
        fallback={"fallback_id": "fallback-3", "on_failure": "block"})
    _, replay, _ = consumer_clock(layout, timeline)
    assert dict(replay.at(4900).state_versions) == {key: 2 if key in payload()["item_object_ids"] else 1
        for key in dict(replay.at(0).state_versions)}


def aperture_documents(mask=False):
    from test_v2_mask_contract import masked_documents

    layout, timeline = runtime_documents()
    root = next(obj for obj in layout["objects"] if obj["object_id"] == "list-group")
    aperture = deepcopy(root)
    aperture.update(object_id="external-aperture", object_type="mask" if mask else "clip",
        child_ids=["aperture-spacer"], parent_id=None)
    spacer = deepcopy(next(obj for obj in layout["objects"] if obj["object_id"] == "list-item-a"))
    spacer.update(object_id="aperture-spacer", parent_id=aperture["object_id"], clip_id=None)
    if mask:
        source = deepcopy(masked_documents()[1]["objects"][-1])
        source.update(object_id="aperture-source", beat_id="beat-002", coverage_ids=["coverage-3"])
        source["geometry"]["bounds"] = {"x": 0, "y": 0, "width": 600, "height": 600}
        aperture.update(mask_mode="alpha", mask_source_object_id=source["object_id"],
            mask_coordinate_space="parent_local", invert=False, feather_px=0)
        add_object(layout, timeline, source)
    add_object(layout, timeline, aperture)
    add_object(layout, timeline, spacer)
    next(obj for obj in layout["objects"] if obj["object_id"] == "list-item-a")["clip_id"] = aperture["object_id"]
    timeline["layout_sha256"] = digest(layout)
    return layout, timeline


def add_fade(timeline, target):
    row = deepcopy(timeline["actions"][0])
    raw = action()
    for name in ("structured_list_policy", "annotation"):
        raw.pop(name)
    raw.update(action_id="fade-aperture", verb="fade", target_ids=[target], expected_state="visible",
        post_state="visible", opacity=0, destination=None, trigger={"kind": "absolute", "at_ms": 0})
    row.update(action=raw, start_ms=100, end_ms=200,
        resolved_trigger={"source": raw["trigger"], "resolved_at_ms": 0, "alignment_anchor_ms": 0,
            "matched_text": None, "matched_occurrence": None, "confidence": 1, "exact": True})
    timeline["actions"].insert(0, row)
    timeline["coverage"][0]["action_ids"].append(raw["action_id"])


@pytest.mark.parametrize("mask", [False, True])
def test_prior_unreadable_explicit_aperture_or_mask_source_rejects_at_capture(mask):
    layout, timeline = aperture_documents(mask)
    add_fade(timeline, "aperture-source" if mask else "external-aperture")
    with pytest.raises(ValueError, match="structured list|dependency|aperture"):
        private_clock(layout, timeline)


@pytest.mark.parametrize("mask", [False, True])
def test_explicit_aperture_and_mask_source_are_reserved_during_the_outer_interval(mask):
    layout, timeline = aperture_documents(mask)
    add_move(timeline, layout, "aperture-source" if mask else "external-aperture", 4100, 4200,
        expected_state="visible")
    with pytest.raises(ValueError, match="reserved|reservation"):
        private_clock(layout, timeline)


def test_geometric_group_edit_cannot_overlap_structured_item_construction():
    layout, timeline = prior_group_documents()
    group = timeline["actions"][0]
    group.update(start_ms=4100, end_ms=4200)
    timeline["actions"][1]["action"]["structured_list_policy"]["expected_item_state_versions"] = {
        key: 1 for key in payload()["item_object_ids"]}
    timeline["actions"].sort(key=lambda item: item["start_ms"])
    with pytest.raises(ValueError, match="overlap|hierarchy"):
        private_clock(layout, timeline)
