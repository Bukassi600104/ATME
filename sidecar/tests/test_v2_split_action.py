"""Phase paint must stay distinct from the single outer semantic commit."""

from copy import deepcopy
from dataclasses import FrozenInstanceError, dataclass, fields

import pytest
from test_v2_split_capture import capture_module, geometry_boundary


def sampler():
    module = capture_module()
    assert hasattr(module, "sample_split"), "Split phase sampler is not implemented"
    return module.sample_split


def attributed_capture(layout, before, resolved):
    from atme.render.v2_timeline_replay import _capture_split_from_history

    wrapped = _capture_split_from_history(layout, before, (resolved,), 0, 2000, {})
    assert wrapped.split_capture.action_id == wrapped.resolved.action.action_id
    return wrapped.split_capture


@pytest.mark.parametrize("at,source_alpha,result_reveal,committed", [
    (0, 1.0, 0.0, False), (200, 1.0, 1 / 3, False),
    (500, 0.5, 5 / 6, False), (600, 1 / 3, 1.0, False),
    (800, 0.0, 1.0, False), (999, 0.0, 1.0, False), (1000, 0.0, 1.0, True),
])
def test_phase_end_is_not_semantic_commit(at, source_alpha, result_reveal, committed):
    sample = sampler()
    layout, before, resolved = geometry_boundary()
    resolved = resolved.model_copy(update={"end_ms": 1000})
    assert (resolved.start_ms, resolved.end_ms) == (0, 1000)
    capture = attributed_capture(layout, before, resolved)
    observed = sample(capture, at)
    frames = {row.object_id: row for row in observed.objects}
    assert set(frames) == set(capture.owned_object_ids)
    assert frames["source"].opacity == pytest.approx(source_alpha)
    assert frames["source"].state == ("removed" if committed else "visible")
    assert frames["source"].reveal_fraction == (0.0 if committed else 1.0)
    for key in ("part-1", "part-2"):
        assert frames[key].state == ("visible" if committed else "hidden")
        assert frames[key].reveal_fraction == pytest.approx(result_reveal)
        assert frames[key].opacity == 1.0
        assert frames[key].visible == (result_reveal > 0)
        assert frames[key].transform == before.object(key).transform
    assert len(observed.envelopes) == 2
    assert tuple(row.root_id for row in observed.envelopes) == ("part-1", "part-2")
    assert all(row.action_id == resolved.action.action_id for row in observed.envelopes)
    assert all(row.mode == "reveal" and row.construction_fraction == pytest.approx(result_reveal)
               for row in observed.envelopes)
    with pytest.raises(FrozenInstanceError):
        observed.envelopes[0].mode = "draw"


def test_phase_sampling_is_random_access_and_does_not_mutate_capture():
    sample = sampler()
    layout, before, resolved = geometry_boundary()
    resolved = resolved.model_copy(update={"end_ms": 1000})
    capture = attributed_capture(layout, before, resolved)
    original = repr(capture)
    times = [0, 1, 199, 200, 201, 599, 600, 601, 799, 800, 801, 999, 1000]
    expected = {time: sample(capture, time) for time in times}
    for time in [1000, 601, 0, 799, 201, 999, 1, 800, 599, 200, 801, 600, 199]:
        assert sample(capture, time) == expected[time]
    assert repr(capture) == original


def test_split_version_targets_are_ordered_roots_not_read_dependencies():
    from atme.render.v2_timeline_replay import version_targets
    from test_v2_split_capture import ancestor_boundary

    _, _, resolved = ancestor_boundary(aperture=True)
    assert version_targets(resolved.action) == ("source", "part-1", "part-2")


def test_sampling_rejects_unattributed_base_and_unknown_subclasses():
    sample = sampler()
    module = capture_module()
    layout, before, resolved = geometry_boundary()
    base = module.capture_split(resolved, layout, before, {})
    with pytest.raises(ValueError, match="attributed"):
        sample(base, 100)
    attributed = attributed_capture(layout, before, resolved)

    @dataclass(frozen=True)
    class Unknown(type(attributed)):
        extra: str = "untrusted"

    unknown = Unknown(**{field.name: getattr(attributed, field.name) for field in fields(attributed)})
    with pytest.raises(ValueError, match="attributed"):
        sample(unknown, 100)


@pytest.mark.parametrize("mode", ["reveal", "draw", "write", "enter"])
@pytest.mark.parametrize("easing", ["linear", "ease_in", "ease_out", "ease_in_out"])
def test_enter_move_endpoint_and_seek_parity(mode, easing):
    from atme.store.contracts_v2 import (
        ResolvedAction,
        SplitPolicy,
        _split_expected_completion,
        _split_packet_digest,
    )

    layout, before, resolved = geometry_boundary()
    raw = resolved.model_dump(mode="json")
    raw["end_ms"] = 1000
    policy = raw["action"]["split_policy"]
    result = policy["results"][0]
    origin = deepcopy(result["destination"])
    entering = deepcopy(origin)
    entering.update(position={"x": 12.125, "y": 30.25}, scale_x=2.0, scale_y=0.5,
                    rotation_degrees=15.5, origin={"x": 0.25, "y": 0.75})
    result["construction"].update(mode=mode, phase={"start_tick": 0, "end_tick": 4000, "easing": easing},
        enter_destination=entering if mode == "enter" else None)
    moving_from = entering if mode == "enter" else origin
    destination = deepcopy(moving_from)
    destination["position"] = {"x": 80.125, "y": 90.25}
    destination.update(scale_x=3.0, scale_y=2.0, rotation_degrees=40.5, origin={"x": 0.75, "y": 0.25})
    result.update(movement={"phase": {"start_tick": 4000, "end_tick": 8000, "easing": easing},
        "from_transform": moving_from, "destination": destination}, destination=destination)
    packet = _split_expected_completion(SplitPolicy.model_validate(policy))
    packet["completion_sha256"] = _split_packet_digest(packet)
    raw["split_completion_receipt"] = packet
    resolved = ResolvedAction.model_validate(raw)
    capture = attributed_capture(layout, before, resolved)
    sample = sampler()

    def frame(at):
        return next(row for row in sample(capture, at).objects if row.object_id == "part-1")

    from atme.render.v2_state import FrameTransform

    assert frame(0).transform == before.object("part-1").transform
    assert frame(400).transform == FrameTransform.from_contract(resolved.action.split_policy.results[0].movement.from_transform)
    assert frame(800).transform == FrameTransform.from_contract(resolved.action.split_policy.results[0].destination)
    assert frame(999).transform == frame(800).transform == frame(1000).transform
    p = {"linear": .5, "ease_in": .25, "ease_out": .75, "ease_in_out": .5}[easing]
    assert frame(600).transform.position.x == pytest.approx(moving_from["position"]["x"] * (1-p) + 80.125*p)
    times = [0, 1, 399, 400, 401, 799, 800, 801, 999, 1000]
    expected = {at: sample(capture, at) for at in times}
    for at in reversed(times):
        assert sample(capture, at) == expected[at]


def test_split_owned_delta_excludes_read_ancestor_from_operator_output():
    from atme.render.v2_timeline_replay import (
        _capture_split_from_history,
        _sample_operator,
    )
    from test_v2_split_capture import ancestor_boundary, peer_action
    from test_v2_split_identity import sample_for_layout
    from test_v2_timeline_replay import resolved as timed

    layout, _, resolved = ancestor_boundary(aperture=True)
    initial = sample_for_layout(layout)
    reveal = timed(peer_action("reveal", target_ids=["earlier"]).action, 0, 100)
    reveal.action.expected_state = "hidden"
    capture = _capture_split_from_history(layout, initial, (reveal, resolved), 1, 2000, {})
    objects = {row.object_id: row for row in layout.objects}
    delta = _sample_operator(capture, 800, objects)
    assert set(delta) == {"source", "part-1", "part-2"}
    assert "earlier" not in delta


def test_split_keeps_exact_completed_count_payload_through_removal():
    from atme.render.v2_timeline_replay import _capture_split_from_history
    from test_v2_split_capture import counted_boundary

    layout, initial, before, prior, resolved = counted_boundary(group_after_count=True)
    capture = _capture_split_from_history(layout, initial, (*prior, resolved), len(prior), 2000, {}).split_capture
    original = before.object("source")
    for at in [resolved.start_ms, resolved.end_ms - 1, resolved.end_ms]:
        source = next(row for row in sampler()(capture, at).objects if row.object_id == "source")
        assert type(source) is type(original)
        assert source.display_text == original.display_text
        assert source.count_value == original.count_value
        assert source.transform == original.transform
    assert source.state == "removed"


def replay_split(layout, initial, actions, duration=2000):
    from atme.render import v2_timeline_replay as replay

    assert hasattr(replay, "_replay_split_chronology"), "Private Split chronological integration missing"
    return replay._replay_split_chronology(layout, initial, tuple(actions), duration, {})


def test_outer_commit_changes_roots_once_and_envelopes_are_half_open():
    from atme.render.v2_timeline_replay import ReplaySample

    layout, initial, split = geometry_boundary()
    replay = replay_split(layout, initial, (split,))
    before = replay.at(split.end_ms - 1)
    assert before.object("source").state == "visible"
    assert before.object("part-1").state == "hidden"
    assert dict(before.state_versions) == dict(initial.state_versions)
    assert len(before.envelopes) == 2
    assert type(replay.before_action(split.action.action_id)) is ReplaySample
    for at in (split.end_ms, split.end_ms + 1, 1999):
        final = replay.at(at)
        assert type(final) is ReplaySample
        assert final.object("source").state == "removed"
        assert final.object("part-1").state == "visible"
        assert dict(final.state_versions) == {key: value + 1 for key, value in initial.state_versions}


def test_split_owned_delta_does_not_commit_unrelated_motion():
    from atme.store.contracts_v2 import ExecutableLayoutV2
    from test_v2_split_capture import peer_action
    from test_v2_split_identity import sample_for_layout
    from test_v2_timeline_replay import resolved as timed

    layout, _, split = geometry_boundary()
    raw = layout.model_dump(mode="json")
    obj = deepcopy(next(row for row in raw["objects"] if row["object_id"] == "source"))
    obj.update(object_id="unrelated", z_index=3)
    raw["objects"].append(obj)
    raw["boards"][0]["object_ids"].append("unrelated")
    destination = deepcopy(obj["transform"])
    destination["position"]["x"] = 150.0
    moving = timed(peer_action("move", target_ids=["unrelated"], destination=destination).action, 0, 1500)
    layout = ExecutableLayoutV2.model_validate(raw)
    initial = sample_for_layout(layout)
    replay = replay_split(layout, initial, (moving, split))
    expected = {}
    for at in (0, 450, 899, 900, 901, 1200, 1499, 1500, 1999):
        sample = replay.at(at)
        assert sample.object("unrelated").transform.position.x == pytest.approx(min(at, 1500) / 10)
        assert dict(sample.state_versions)["unrelated"] == (2 if at >= 1500 else 1)
        expected[at] = sample
    for at in reversed(expected):
        assert replay.at(at) == expected[at]


def test_later_reveal_cannot_resurrect_split_source_even_with_removed_precondition():
    from test_v2_split_capture import peer_action
    from test_v2_timeline_replay import resolved as timed

    layout, initial, split = geometry_boundary()
    later = peer_action("reveal", target_ids=["source"])
    later.action.expected_state = "removed"
    later = timed(later.action, 1000, 1200)
    with pytest.raises(ValueError, match="removed"):
        replay_split(layout, initial, (split, later))


def test_private_split_end_requires_sampleable_active_board_destination():
    layout, initial, split = geometry_boundary()
    with pytest.raises(ValueError, match="sample"):
        replay_split(layout, initial, (split,), duration=split.end_ms)


@pytest.mark.parametrize("order", ["count", "count_group", "group_count"])
def test_real_replay_count_origin_and_current_versions_survive_to_split_commit(order):
    from test_v2_split_capture import counted_boundary

    layout, initial, before, prior, split = counted_boundary(
        group_after_count=order == "count_group", group_first=order == "group_count")
    replay = replay_split(layout, initial, (*prior, split))
    source = before.object("source")
    for at in (split.start_ms, split.end_ms - 1, split.end_ms):
        observed = replay.at(at)
        assert observed.object("source").display_text == source.display_text
        assert observed.object("source").count_value == source.count_value
        assert dict(observed.state_versions)["source"] == dict(before.state_versions)["source"] + int(at == split.end_ms)


def test_split_completion_preserves_child_local_records_and_versions():
    from test_v2_split_capture import hidden_result_boundary

    layout, initial, split = hidden_result_boundary()
    replay = replay_split(layout, initial, (split,))
    for at in (0, 450, 899, 900, 1999):
        observed = replay.at(at)
        assert observed.object("child") == initial.object("child")
        assert dict(observed.state_versions)["child"] == 1
    assert replay.at(900).object("part-1").visible


def test_forged_private_context_cannot_authenticate_non_authored_initial_frame():
    from dataclasses import replace

    from atme.render.v2_timeline_replay import _SplitReplayContext, replay_chronology

    layout, initial, _split = geometry_boundary()
    altered = replace(initial, objects=tuple(replace(row, opacity=0.2) if row.object_id == "source" else row
                                             for row in initial.objects))
    context = _SplitReplayContext(layout.model_dump_json(), (), altered)
    with pytest.raises(ValueError, match="authored initial"):
        replay_chronology({row.object_id: row for row in layout.objects}, altered.hierarchy,
            {row.object_id: row for row in altered.objects}, dict(altered.state_versions), (),
            tuple((row.board_id, row.start_ms, row.end_ms) for row in layout.activations), 2000, _split_context=context)


def test_completion_rejects_actual_endpoint_tamper_before_accepting_replay(monkeypatch):
    from dataclasses import replace

    module = capture_module()
    layout, initial, split = geometry_boundary()
    real = module.sample_split

    def tampered(capture, at):
        observed = real(capture, at)
        if at == capture.end_ms:
            return replace(observed, objects=tuple(replace(row, opacity=.4) if row.object_id == "part-1" else row
                                                  for row in observed.objects))
        return observed

    monkeypatch.setattr(module, "sample_split", tampered)
    with pytest.raises(ValueError, match="sampled completion"):
        replay_split(layout, initial, (split,))


def test_private_frame_assembly_preserves_envelopes_without_changing_legacy_snapshot():
    from atme.render.v2_state import (
        FrameSnapshot,
        _sample_validated_frame,
        camera_segments,
    )
    from atme.store.contracts_v2 import ResolvedVisualTimelineV2
    from v2_split_fixtures import split_documents

    layout, initial, split = geometry_boundary()
    _, _, timeline = split_documents()
    timeline["actions"] = [split.model_dump(mode="json")]
    timeline = ResolvedVisualTimelineV2.model_validate(timeline)
    replay = replay_split(layout, initial, (split,), duration=timeline.duration_ms)
    camera = camera_segments(layout, timeline, replay)
    active = _sample_validated_frame(layout, timeline, replay, camera, 450)
    assert type(active).__name__ == "SplitFrameSnapshot"
    assert active.envelopes == replay.at(450).envelopes
    assert type(_sample_validated_frame(layout, timeline, replay, camera, 900)) is FrameSnapshot


@pytest.mark.parametrize("chained", [False, True])
def test_multiple_splits_share_one_scheduler_and_preserve_authored_envelope_order(chained):
    from atme.render.v2_split_identity import split_content_receipts
    from atme.store.contracts_v2 import (
        ExecutableLayoutV2,
        ResolvedAction,
        SplitPolicy,
        _split_expected_completion,
        _split_packet_digest,
    )
    from test_v2_split_identity import sample_for_layout

    layout, _, first = geometry_boundary()
    mapping = {"source": "part-1" if chained else "source-b", "part-1": "part-b1", "part-2": "part-b2"}

    def renamed(value):
        if isinstance(value, dict):
            return {key: renamed(item) for key, item in value.items()}
        if isinstance(value, list):
            return [renamed(item) for item in value]
        return mapping.get(value, value) if isinstance(value, str) else value

    raw = layout.model_dump(mode="json")
    ordinal = 3
    ordinals = {"part-1": 1} if chained else {}
    for obj in list(raw["objects"]):
        if chained and obj["object_id"] == "source":
            continue
        addition = renamed(obj)
        addition["z_index"] = ordinal
        ordinals[addition["object_id"]] = ordinal
        ordinal += 1
        raw["objects"].append(addition)
        raw["boards"][0]["object_ids"].append(addition["object_id"])
    layout = ExecutableLayoutV2.model_validate(raw)
    initial = sample_for_layout(layout)
    contents = {row.object_id: row.content_sha256 for row in split_content_receipts(layout, initial, {})}
    second = renamed(first.model_dump(mode="json"))
    second["action"]["action_id"] = "split-2"
    second.update(start_ms=900 if chained else 0, end_ms=1800 if chained else 900)
    policy = second["action"]["split_policy"]
    for row in policy["source_basis"]["placements"]:
        row.update(sibling_ordinal=ordinals[row["object_id"]], content_sha256=contents[row["object_id"]],
            state_version=2 if chained and row["object_id"] == "part-1" else 1)
    for row in policy["correspondences"]:
        row.update(source_content_sha256=contents[mapping["source"]], result_content_sha256=contents[row["result_object_id"]])
    policy["source_basis"]["placements"].sort(key=lambda row: row["object_id"])
    policy["source_basis_sha256"] = _split_packet_digest(policy["source_basis"])
    receipt = _split_expected_completion(SplitPolicy.model_validate(policy))
    receipt["completion_sha256"] = _split_packet_digest(receipt)
    second["split_completion_receipt"] = receipt
    second = ResolvedAction.model_validate(second)
    replay = replay_split(layout, initial, (first, second))
    if not chained:
        assert tuple(row.action_id for row in replay.at(450).envelopes) == ("split-1", "split-1", "split-2", "split-2")
    else:
        assert replay.at(899).object("part-1").state == "hidden"
        assert replay.at(900).object("part-1").state == "visible"
        assert replay.at(1800).object("part-1").state == "removed"
        assert dict(replay.at(1800).state_versions)["part-1"] == 3
    assert replay.at(1999).object("part-b1").state == "visible"
    expected = {at: replay.at(at) for at in (0, 450, 900, 1799, 1999)}
    for at in (1799, 900, 450, 0, 1999):
        assert replay.at(at) == expected[at]


@pytest.mark.parametrize("following_transform", [False, True])
def test_adversarial_q4_endpoint_is_exact_for_same_time_following_transform(following_transform):
    from atme.render.v2_state import FrameTransform
    from atme.store.contracts_v2 import (
        ResolvedAction,
        SplitPolicy,
        _split_expected_completion,
        _split_packet_digest,
    )
    from test_v2_split_capture import peer_action
    from test_v2_timeline_replay import resolved as timed

    layout, initial, split = geometry_boundary()
    raw = split.model_dump(mode="json")
    raw["end_ms"] = 1000
    result = raw["action"]["split_policy"]["results"][0]
    entering = deepcopy(result["destination"])
    entering["position"]["x"] = -1.0
    final = deepcopy(entering)
    final["position"]["x"] = -0.4894
    result["construction"].update(mode="enter", enter_destination=entering,
        phase={"start_tick": 0, "end_tick": 4000, "easing": "linear"})
    result.update(movement={"phase": {"start_tick": 4000, "end_tick": 8000, "easing": "linear"},
        "from_transform": entering, "destination": final}, destination=final)
    receipt = _split_expected_completion(SplitPolicy.model_validate(raw["action"]["split_policy"]))
    receipt["completion_sha256"] = _split_packet_digest(receipt)
    raw["split_completion_receipt"] = receipt
    split = ResolvedAction.model_validate(raw)
    actions = [split]
    if following_transform:
        destination = deepcopy(final)
        destination["rotation_degrees"] = 20.0
        actions.append(timed(peer_action("rotate", target_ids=["part-1"], destination=destination).action, 1000, 1500))
    replay = replay_split(layout, initial, actions)
    expected = FrameTransform.from_contract(split.action.split_policy.results[0].destination)
    assert replay.at(800).object("part-1").transform == expected
    assert replay.at(1000).object("part-1").transform == expected
    if following_transform:
        assert replay.at(1500).object("part-1").transform.rotation_degrees == 20.0
        assert dict(replay.at(1500).state_versions)["part-1"] == 3
