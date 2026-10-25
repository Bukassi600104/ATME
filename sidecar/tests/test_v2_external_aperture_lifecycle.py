"""Aperture readiness and read intervals use actual shared chronological state."""
from copy import deepcopy
from dataclasses import replace

import pytest
from atme.render.v2_external_aperture import (
    UnsupportedExternalAperture,
    external_aperture_projections,
)
from atme.render.v2_state import V2FrameError, evaluate_frame
from atme.store import contracts_v2 as contracts
from test_v2_camera_action import append_camera
from test_v2_external_aperture_runtime import runtime_documents, unclipped_documents
from test_v2_timeline_replay import resolved
from v2_fixtures import digest


def add_action(clock, action, start, end):
    clock["actions"].append(resolved(action, start, end).model_dump(mode="json"))
    clock["actions"].sort(key=lambda row: row["start_ms"])
    clock["coverage"][0]["action_ids"].append(action["action_id"])


def initial_state(layout, clock, key, state, visible):
    obj = next(obj for obj in layout["objects"] if obj["object_id"] == key)
    obj.update(initial_state=state, visible=visible)
    row = next(row for row in clock["initial_object_states"] if row["object_id"] == key)
    row.update(state=state, visible=visible)
    clock["layout_sha256"] = digest(layout)


def pure_sample(kind):
    _plan, layout, clock, ids = runtime_documents(kind)
    plain, timing = unclipped_documents(layout, clock)
    sample = evaluate_frame(plain, timing, 0)
    objects = sample.hierarchy.object_map({obj.object_id: obj for obj in contracts.ExecutableLayoutV2.model_validate(layout).objects})
    frames = {frame.object_id: frame for frame in sample.objects}
    versions = {row["object_id"]: row["state_version"] for row in clock["initial_object_states"]}
    return layout, clock, ids, objects, frames, versions


@pytest.mark.parametrize("kind", ["clip", "mask"])
@pytest.mark.parametrize("fault", ["hidden", "removed", "invisible", "partial_reveal", "opacity", "zero_opacity"])
def test_positive_consumer_requires_the_actual_exclusive_aperture_branch_to_be_ready(kind, fault):
    _layout, _clock, ids, objects, frames, versions = pure_sample(kind)
    assert external_aperture_projections(objects, frames, active_board=objects[ids["receiver"]].board_id,
                                         state_versions=versions)[0].live
    before = frames[ids["aperture"]]
    changes = {"hidden": {"state": "hidden"}, "removed": {"state": "removed"},
               "invisible": {"visible": False}, "partial_reveal": {"reveal_fraction": .5},
               "opacity": {"opacity": .5}, "zero_opacity": {"opacity": 0.}}[fault]
    frames[ids["aperture"]] = replace(before, **changes)
    with pytest.raises(UnsupportedExternalAperture, match="fully ready opaque exclusive read branches"):
        external_aperture_projections(objects, frames, active_board=before.board_id, state_versions=versions)


@pytest.mark.parametrize("kind", ["clip", "mask"])
@pytest.mark.parametrize("channel", ["opacity", "reveal_fraction"])
def test_common_ancestor_partial_construction_or_fade_is_not_mistaken_for_an_exclusive_read(kind, channel):
    _layout, _clock, ids, objects, frames, versions = pure_sample(kind)
    expected = external_aperture_projections(objects, frames, active_board=objects[ids["receiver"]].board_id,
                                              state_versions=versions)[0]
    assert ids["root"] not in expected.read_ids
    frames[ids["root"]] = replace(frames[ids["root"]], **{channel: .5})
    actual = external_aperture_projections(objects, frames, active_board=objects[ids["receiver"]].board_id,
                                            state_versions=versions)[0]
    assert actual.live and actual.relative == expected.relative


@pytest.mark.parametrize("kind", ["clip", "mask"])
@pytest.mark.parametrize("group", [False, True])
@pytest.mark.parametrize("prior", [False, True])
def test_read_lifetime_rejects_overlapping_owner_motion_but_samples_completed_motion(kind, group, prior):
    _plan, layout, clock, ids = runtime_documents(kind, group=group)
    evaluate_frame(layout, clock, 0)
    owner = next(obj for obj in layout["objects"] if obj["object_id"] == ids["aperture"])
    move = deepcopy(clock["actions"][1]["action"])
    destination = deepcopy(owner["transform"])
    destination["position"]["x"] += 20.
    move.update(action_id="move-exclusive-owner", target_ids=[ids["aperture"]], destination=destination)
    add_action(clock, move, 1000, 2000)
    if prior:
        initial_state(layout, clock, "external-receiver", "hidden", False)
        reveal = deepcopy(clock["actions"][0]["action"])
        reveal.update(action_id="construct-consumer", target_ids=["external-receiver"])
        add_action(clock, reveal, 2000, 2500)
        sample = evaluate_frame(layout, clock, 2999)
        assert sample.object(ids["aperture"]).transform.position.x == destination["position"]["x"]
        assert sample.object("external-receiver").visible
    else:
        with pytest.raises(V2FrameError, match="external aperture.*read lifetime conflicts"):
            evaluate_frame(layout, clock, 5000)  # A late seek cannot evade an earlier bad read.


@pytest.mark.parametrize("kind", ["clip", "mask"])
@pytest.mark.parametrize("mode", ["fade", "enter"])
def test_real_common_ancestor_lifecycle_uses_normal_existing_actions(kind, mode):
    _plan, layout, clock, ids = runtime_documents(kind)
    if mode == "fade":
        action = deepcopy(clock["actions"][1]["action"])
        action.update(action_id="fade-common-root", verb="fade", destination=None, opacity=.5)
        add_action(clock, action, 1000, 2000)
        assert evaluate_frame(layout, clock, 1500).object(ids["root"]).opacity == .75
    else:
        original = clock["actions"][0]
        clock["actions"][0] = resolved(original["action"], 1000, 1900).model_dump(mode="json")
        initial_state(layout, clock, ids["root"], "hidden", False)
        action = deepcopy(original["action"])
        action.update(action_id="enter-common-root", verb="enter", target_ids=[ids["root"]])
        add_action(clock, action, 0, 900)
        sample = evaluate_frame(layout, clock, 450)
        assert sample.object(ids["root"]).visible
        assert sample.object("external-receiver").visible


@pytest.mark.parametrize("kind", ["clip", "mask"])
@pytest.mark.parametrize("fault", ["missing", "zero", "bool"])
def test_supplied_sample_must_have_exact_positive_current_version_inventory(kind, fault):
    _layout, _clock, ids, objects, frames, versions = pure_sample(kind)
    if fault == "missing":
        versions.pop(ids["aperture"])
    else:
        versions[ids["aperture"]] = 0 if fault == "zero" else True
    with pytest.raises(UnsupportedExternalAperture, match="exact current state-version inventory"):
        external_aperture_projections(objects, frames, active_board=objects[ids["receiver"]].board_id,
                                     state_versions=versions)


@pytest.mark.parametrize("group", [False, True])
def test_camera_does_not_silently_use_preclip_bounds_for_direct_or_group_clipped_subject(group):
    _plan, layout, clock, _ids = runtime_documents("clip", group=group)
    append_camera(clock, "focus-external", "camera_cut", 6000, 6500, target="external-receiver")
    with pytest.raises(V2FrameError, match="post-clip visible focus geometry"):
        evaluate_frame(layout, clock, 7000)
