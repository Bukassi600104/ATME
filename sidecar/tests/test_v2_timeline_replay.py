"""Chronological local-state replay; public frame routing is a separate gate."""

from copy import deepcopy
from dataclasses import FrozenInstanceError, replace

import pytest
from test_v2_hierarchy_contract import rehash
from test_v2_hierarchy_replay import prepared, reverse

from atme.render.v2_hierarchy_replay import completed_hierarchy_basis
from atme.render.v2_state import FrameObject, FramePoint, FrameTransform, evaluate_frame
from atme.render.v2_timeline_replay import ReplayError, replay_chronology
from atme.store.contracts_v2 import (
    ExecutableLayoutV2,
    GroupAction,
    ResolvedAction,
    ResolvedVisualTimelineV2,
)


def resolved(action, start, end):
    document = action.model_dump(mode="json") if hasattr(action, "model_dump") else deepcopy(action)
    document["trigger"] = {"kind": "absolute", "at_ms": start}
    return ResolvedAction.model_validate({
        "action": document, "start_ms": start, "end_ms": end,
        "resolved_trigger": {"source": document["trigger"], "resolved_at_ms": start,
                             "alignment_anchor_ms": start, "confidence": 1, "exact": True},
    })


def moving(group, frames, target="object-evidence", start=3000, end=6000):
    document = group.model_dump(mode="json")
    for key in ("hierarchy_policy", "container_id"):
        document.pop(key)
    transform = completed_hierarchy_basis(prepared()[2], frames).model_dump(mode="json")
    destination = next(item["local_transform"] for item in transform["placements"] if item["object_id"] == target)
    destination["position"]["x"] += 300
    document.update(action_id="move-other", verb="move", target_ids=[target], easing="linear",
                    expected_state=frames[target].state, post_state=frames[target].state,
                    destination=destination, opacity=None)
    return resolved(document, start, end)


def with_other_pose(action, frames, progress):
    document = action.model_dump(mode="json")
    for side in ("source", "destination"):
        placement = next(p for p in document["hierarchy_policy"][f"{side}_basis"]["placements"]
                         if p["object_id"] == "object-evidence")
        placement["local_transform"]["position"]["x"] = frames["object-evidence"].transform.position.x + 300 * progress
    rehash(document)
    return GroupAction.model_validate(document)


def run(actions, prepared_input=None, end=10000):
    _action, objects, hierarchy, frames, versions = prepared_input or prepared()
    return replay_chronology(objects, hierarchy, frames, versions, tuple(actions),
                             (("board-main", 0, end),), end)


def test_end_boundary_samples_later_started_unrelated_motion_without_double_interpolation():
    action, objects, hierarchy, frames, versions = prepared()
    group = with_other_pose(action, frames, 2 / 3)
    original = deepcopy((objects, hierarchy, frames, versions, group))
    trace = run([resolved(group, 1000, 5000), moving(group, frames)],
                (action, objects, hierarchy, frames, versions))
    assert trace.at(4999).hierarchy == hierarchy
    assert trace.at(5000).hierarchy.children("board-main", "object-group") == ()
    before_x = frames["object-evidence"].transform.position.x
    assert trace.at(5000).object("object-evidence").transform.position.x == pytest.approx(before_x + 200)
    assert trace.at(5500).object("object-evidence").transform.position.x == pytest.approx(before_x + 250)
    assert trace.at(6000).object("object-evidence").transform.position.x == pytest.approx(before_x + 300)
    assert dict(trace.at(5000).state_versions)["object-evidence"] == versions["object-evidence"] + 1
    assert dict(trace.at(6000).state_versions)["object-evidence"] == versions["object-evidence"] + 2
    assert (objects, hierarchy, frames, versions, group) == original


@pytest.mark.parametrize("move_end", [4000, 5000])
def test_ordinary_completions_are_applied_before_group_completions_at_the_same_time(move_end):
    action, _, _, frames, versions = prepared()
    group = with_other_pose(action, frames, 1)
    trace = run([resolved(group, 1000, 5000), moving(group, frames, end=move_end)])
    assert trace.at(5000).object("object-evidence").transform.position.x == frames["object-evidence"].transform.position.x + 300
    assert dict(trace.at(5000).state_versions)["object-evidence"] == versions["object-evidence"] + 2


def test_stale_full_group_source_is_not_silently_rebased_to_current_motion():
    action, _, _, frames, _ = prepared()
    with pytest.raises(ReplayError, match="source basis"):
        run([resolved(action, 1000, 5000), moving(action, frames)])


def test_end_before_start_captures_the_reparented_root_pose_for_later_motion():
    action, _, _, frames, _ = prepared()
    group = resolved(action, 1000, 5000)
    move = moving(action, frames, target="object-system", start=5000, end=7000)
    trace = run([group, move])
    assert trace.at(5000).object("object-system").transform.position == frames["object-system"].transform.position
    assert trace.at(6000).object("object-system").transform.position.x == frames["object-system"].transform.position.x + 150


@pytest.mark.parametrize("target", ["object-system", "object-label", "object-group"])
def test_member_and_shell_motion_during_structural_transition_rejects(target):
    action, _, _, frames, _ = prepared()
    with pytest.raises(ReplayError, match="hierarchy.*overlap"):
        run([resolved(action, 1000, 5000), moving(action, frames, target)])


def test_regroup_roundtrip_and_random_seeks_are_exact_and_immutable():
    action, _, hierarchy, frames, versions = prepared()
    regroup = reverse(action).model_copy(update={"action_id": "regroup"})
    trace = run([resolved(action, 1000, 3000), resolved(regroup, 4000, 5000)])
    end = trace.at(5000)
    assert end.hierarchy == hierarchy
    assert end.objects == tuple(frames[key] for key in sorted(frames))
    assert dict(end.state_versions) == {key: version + 2 for key, version in versions.items()}
    assert [trace.at(t) for t in (2999, 3000, 3001, 4999, 5000)] == [
        trace.at(t) for t in (2999, 3000, 3001, 4999, 5000)]
    with pytest.raises(FrozenInstanceError):
        end.at_ms = 7


def test_positive_faded_member_alpha_is_preserved_by_grouping():
    action, objects, hierarchy, frames, versions = prepared()
    frames["object-system"] = replace(frames["object-system"], opacity=.4)
    trace = run([resolved(action, 1000, 5000)], (action, objects, hierarchy, frames, versions))
    assert trace.at(5000).object("object-system").opacity == .4


@pytest.mark.parametrize("key,field,value", [
    ("object-system", "opacity", 0), ("object-group", "opacity", .5),
    ("object-label", "visible", False), ("object-system", "reveal_fraction", .5),
])
def test_atomic_group_readiness_is_not_inferred_or_normalized(key, field, value):
    action, objects, hierarchy, frames, versions = prepared()
    frames[key] = replace(frames[key], **{field: value})
    with pytest.raises(ReplayError, match="shell source state|participant chains"):
        run([resolved(action, 1000, 5000)], (action, objects, hierarchy, frames, versions))


@pytest.mark.parametrize("at", [True, -1, 10000, 1.5])
def test_random_access_time_has_the_existing_strict_frame_domain(at):
    action, *_ = prepared()
    trace = run([resolved(action, 1000, 5000)])
    with pytest.raises(ReplayError, match="integer.*duration"):
        trace.at(at)


@pytest.mark.parametrize("end", [5000, 6000])
def test_group_end_requires_an_actual_visible_destination_sample(end):
    action, *_ = prepared()
    with pytest.raises(ReplayError, match="destination sample"):
        run([resolved(action, 1000, end)], end=end)


def test_started_action_configuration_cannot_be_mutated_through_input_or_trace():
    action, _, _, frames, _ = prepared()
    move = moving(action, frames, start=1000, end=3000)
    trace = run([move])
    expected = trace.at(2000)
    move.action.destination.position.x = 9999
    capture = trace.checkpoints[1].active[0]
    capture.resolved.action.destination.position.x = 9999
    assert trace.at(2000) == expected


def test_completed_dim_keeps_alpha_and_increments_legacy_version_history():
    action, _, _, frames, versions = prepared()
    document = action.model_dump(mode="json")
    for key in ("container_id", "hierarchy_policy"):
        document.pop(key)
    document.update(verb="dim", target_ids=["object-label"], easing="linear",
                    expected_state="visible", post_state="visible", annotation=None)
    trace = run([resolved(document, 1000, 3000)])
    assert trace.at(2000).object("object-label").opacity == pytest.approx(frames["object-label"].opacity * .35)
    assert trace.at(3000).object("object-label").opacity == frames["object-label"].opacity
    assert dict(trace.at(3000).state_versions)["object-label"] == versions["object-label"] + 1


def test_replay_rejects_an_unowned_or_missing_state_version_inventory():
    action, objects, hierarchy, frames, versions = prepared()
    versions.pop("object-label")
    with pytest.raises(ReplayError, match="version inventory"):
        run([resolved(action, 1000, 5000)], (action, objects, hierarchy, frames, versions))


def test_playback_preserves_unrelated_local_transform_channels():
    action, _, _, frames, _ = prepared()
    trace = run([moving(action, frames, start=1000, end=3000)])
    actual = trace.at(2000).object("object-evidence").transform
    original = frames["object-evidence"].transform
    assert actual.position == FramePoint(original.position.x + 150, original.position.y)
    assert (actual.scale_x, actual.scale_y, actual.rotation_degrees, actual.origin) == (
        original.scale_x, original.scale_y, original.rotation_degrees, original.origin)


def document_replay(layout, timeline):
    from atme.render.v2_hierarchy import HierarchySnapshot

    parsed_layout = ExecutableLayoutV2.model_validate(layout)
    parsed_timeline = ResolvedVisualTimelineV2.model_validate(timeline)
    objects = {item.object_id: item for item in parsed_layout.objects}
    states = {item.object_id: item for item in parsed_timeline.initial_object_states}
    frames = {key: FrameObject(key, obj.board_id, states[key].state, obj.visible, obj.opacity,
                               1 if obj.visible else 0, FrameTransform.from_contract(obj.transform))
              for key, obj in objects.items()}
    return replay_chronology(objects, HierarchySnapshot.from_objects(objects), frames,
                             {key: value.state_version for key, value in states.items()},
                             tuple(parsed_timeline.actions),
                             tuple((item.board_id, item.start_ms, item.end_ms) for item in parsed_layout.activations),
                             parsed_timeline.duration_ms)


@pytest.mark.parametrize("verb", ["reveal", "write", "draw", "enter", "exit", "move", "scale", "rotate", "fade"])
def test_existing_target_and_transform_operators_have_exact_frame_parity(verb):
    from test_v2_frame_state import supported_documents

    layout, timeline = supported_documents(verb)
    assert_frame_parity(layout, timeline)


def assert_frame_parity(layout, timeline):
    trace = document_replay(layout, timeline)
    original = deepcopy((layout, timeline))
    moments = parity_moments(timeline)
    for at in moments:
        actual = {item.object_id: item for item in trace.at(at).objects}
        expected = {item.object_id: item for item in evaluate_frame(layout, timeline, at).objects}
        assert actual == expected, (at, actual, expected)
    assert (layout, timeline) == original


def parity_moments(timeline):
    return sorted({0, timeline["duration_ms"] - 1, *(max(0, item[edge] + offset)
                       for item in timeline["actions"] for edge in ("start_ms", "end_ms")
                       for offset in (-1, 0, 1)),
                      *((item["start_ms"] + item["end_ms"]) // 2 for item in timeline["actions"])}
                  .intersection(range(timeline["duration_ms"])))


@pytest.mark.parametrize("kind", ["replace", "morph", "highlight", "cross_out", "dim", "isolate",
                                  "connect", "annotation", "leader", "list", "static_group"])
def test_existing_composed_operators_have_exact_frame_parity(kind):
    assert_frame_parity(*legacy_parity_documents(kind))


def legacy_parity_documents(kind):
    from test_v2_annotation_contract import annotation_documents, leader_documents
    from test_v2_camera_action import append_camera
    from test_v2_camera_action import documents as camera_documents
    from test_v2_connection_actions import relationship_documents
    from test_v2_cross_out_action import cross_out_documents
    from test_v2_dim_action import dim_documents
    from test_v2_frame_state import supported_documents
    from test_v2_group_hierarchy import grouped_documents
    from test_v2_highlight_action import highlight_documents
    from test_v2_isolate_action import isolate_documents
    from test_v2_morph_action import morph_documents
    from test_v2_progressive_list import list_documents
    from test_v2_replace_action import documents
    from test_v2_return_board import return_documents

    if kind in {"reveal", "write", "draw", "enter", "exit", "move", "scale", "rotate", "fade"}:
        return supported_documents(kind)
    if kind == "return_board":
        return return_documents()
    if kind == "insert_evidence":
        from pathlib import Path
        from tempfile import TemporaryDirectory

        from test_v2_evidence_compositor import evidence_documents

        with TemporaryDirectory(prefix="atme-replay-evidence-oracle-") as directory:
            service, layout, timeline, _ = evidence_documents(Path(directory))
            service.store.close()
            return layout, timeline
    if kind.startswith("camera_"):
        layout, timeline = camera_documents()
        if kind == "camera_cut":
            append_camera(timeline, "camera-last", kind, 6000, 6500)
            return layout, timeline
        if kind == "camera_pan":
            from v2_fixtures import digest

            layout["objects"][2]["geometry"]["bounds"] = {"x": 680, "y": 130, "width": 480, "height": 340}
            timeline["layout_sha256"] = digest(layout)
        append_camera(timeline, "camera-cut", "camera_cut", 6000, 6100,
                      target="object-label" if kind == "camera_zoom" else "object-system",
                      framing="medium" if kind in {"camera_zoom", "camera_hold"} else "close")
        append_camera(timeline, "camera-last", kind, 7000, 8000,
                      target="object-label" if kind == "camera_zoom" else
                      "object-system" if kind == "camera_hold" else "object-evidence",
                      framing="detail" if kind == "camera_zoom" else "close" if kind == "camera_pan" else "medium",
                      easing="step" if kind == "camera_hold" else "linear")
        return layout, timeline

    factories = {"replace": documents, "morph": morph_documents, "highlight": highlight_documents,
                 "cross_out": cross_out_documents, "dim": dim_documents, "isolate": isolate_documents,
                 "connect": relationship_documents, "annotation": annotation_documents,
                 "leader": leader_documents, "list": list_documents, "static_group": grouped_documents}
    return factories[kind]()[-2:]


@pytest.mark.parametrize("case", ["reveal", "write", "draw", "enter", "exit", "move", "scale", "rotate", "fade",
                                  "replace", "morph", "highlight", "cross_out", "dim", "isolate", "connect",
                                  "annotation", "leader", "list", "static_group", "camera_cut", "camera_hold",
                                  "camera_zoom", "camera_pan", "camera_reframe", "insert_evidence", "return_board"])
def test_full_public_frame_and_pixels_match_independent_frozen_pre_route_goldens(case):
    import json
    from dataclasses import asdict
    from hashlib import sha256
    from pathlib import Path

    from atme.render.v2_svg import compose_png_frame, compose_svg_frame

    oracle = json.loads((Path(__file__).parent / "fixtures/v2-replay-legacy-goldens.json").read_text(encoding="utf-8"))
    assert oracle["source_commit"] == "965d27c"
    assert oracle["evaluator_sha256"] == "edd2fa7ef50faa4d54adc65efe3ee27c78121c02dd6b0e1c6a4d7e126987a8c5"
    record = oracle["cases"][case]
    layout, timeline = record["layout"], record["timeline"]
    for kind, document in (("layout", layout), ("timeline", timeline)):
        canonical = json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        assert sha256(canonical).hexdigest() == record[f"{kind}_sha256"]
    for at, expected in record["frames"].items():
        normalized = json.dumps(asdict(evaluate_frame(layout, timeline, int(at))), sort_keys=True,
                                separators=(",", ":"), allow_nan=False).encode()
        assert sha256(normalized).hexdigest() == expected, (case, at)
    for at, expected in record.get("pixels", {}).items():
        assert sha256(compose_svg_frame(layout, timeline, int(at)).svg.encode()).hexdigest() == expected["svg"], (case, at)
        assert sha256(compose_png_frame(layout, timeline, int(at)).png).hexdigest() == expected["png"], (case, at)


def test_isolate_context_restores_without_inventing_context_version_mutations():
    from test_v2_isolate_action import isolate_documents

    layout, timeline = isolate_documents()
    trace = document_replay(layout, timeline)
    action = timeline["actions"][-1]
    before = dict(trace.at(action["start_ms"]).state_versions)
    after = dict(trace.at(action["end_ms"]).state_versions)
    focus = action["action"]["target_ids"]
    assert after == {key: value + (key in focus) for key, value in before.items()}


def test_same_target_overlap_cannot_overwrite_another_captured_baseline():
    action, _, _, frames, _ = prepared()
    first = moving(action, frames, start=1000, end=6000)
    second = moving(action, frames, start=2000, end=4000)
    second.action.action_id = "second-move"
    with pytest.raises(ReplayError, match="overlapping.*object-evidence"):
        run([first, second])


def test_completed_fade_before_group_keeps_local_alpha_and_both_versions():
    action, _, _, frames, versions = prepared()
    fade = moving(action, frames, target="object-system", start=100, end=900)
    document = fade.action.model_dump(mode="json")
    document.update(verb="fade", destination=None, opacity=.4)
    trace = run([resolved(document, 100, 900), resolved(action, 1000, 5000)])
    assert trace.at(5000).object("object-system").opacity == .4
    assert dict(trace.at(5000).state_versions)["object-system"] == versions["object-system"] + 2


@pytest.mark.parametrize("verb", ["dim", "isolate"])
def test_attention_history_is_preserved_before_an_exact_retained_board_return(verb):
    from test_v2_dim_action import dim_documents
    from test_v2_isolate_action import isolate_documents
    from test_v2_return_board import return_documents
    from v2_fixtures import digest

    # Dim's approved target must be initially visible and untouched; do not use
    # a previously revealed label just to manufacture a passing ledger test.
    layout, timeline = (dim_documents if verb == "dim" else isolate_documents)()
    layout["boards"][0]["expected_prior_state"] = "system_established"
    layout["activations"] = [{**layout["activations"][0], "end_ms": 7000},
                             {**layout["activations"][0], "activation_id": "activation-return",
                              "start_ms": 8000, "reason": "Revisit attention history"}]
    return_action = deepcopy(return_documents()[1]["actions"][2]["action"])
    return_action["expected_object_states"] = {key: "visible" for key in return_action["expected_object_states"]}
    return_action["expected_object_state_versions"] = {key: 2 for key in return_action["expected_object_state_versions"]}
    timeline["actions"].append(resolved(return_action, 8000, 8001).model_dump(mode="json"))
    timeline["coverage"][2]["action_ids"].append(return_action["action_id"])
    timeline["layout_sha256"] = digest(layout)
    trace = document_replay(layout, timeline)
    assert dict(trace.at(8000).state_versions) == return_action["expected_object_state_versions"]
    assert evaluate_frame(layout, timeline, 8000).object("object-evidence").state == "visible"
