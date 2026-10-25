"""Technical leaves consume existing camera framing through actual Group poses."""

from copy import deepcopy

import pytest
from test_v2_technical_frame_compositor import (
    action_row,
    composite_documents,
    set_actions,
)
from test_v2_technical_frame_contract import CASES
from v2_fixtures import digest

from atme.render.v2_state import evaluate_frame
from atme.render.v2_svg import compose_png_frame


def camera_documents(kind="browser", state="ready", roles=None, *, portrait=False, target="object-evidence"):
    layout, timeline = composite_documents(kind, state, roles, portrait=portrait)
    group = next(obj for obj in layout["objects"] if obj["object_id"] == "list-group")
    group["transform"].update(position={"x": 10., "y": 20.}, scale_x=.9, scale_y=.9,
                              origin={"x": 0., "y": 0.})
    timeline["actions"][0]["action"]["opacity"] = 1.
    template = deepcopy(timeline["actions"][0])
    template["action"].pop("opacity")
    template["action"].pop("destination")
    row = action_row(template, {"verb": "camera_cut", "target_ids": [target], "framing": "close",
        "movement_purpose": "emphasize", "expected_state": None, "post_state": "framed", "easing": "step"},
        2000, 2100, "native-camera")
    set_actions(timeline, [timeline["actions"][0], row])
    timeline["layout_sha256"] = digest(layout)
    return layout, timeline


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("kind,states,roles", CASES)
def test_bound_native_leaf_uses_literal_current_group_bounds_and_seek_parity(kind, states, roles, portrait):
    layout, timeline = camera_documents(kind, states[0], roles, portrait=portrait)
    original = deepcopy((layout, timeline))
    camera = evaluate_frame(layout, timeline, 2200).camera
    expected = (46.5384615385, 0., 576.9230769231, 1025.6410256410) if portrait else (
        27.3076923077, 181.9230769231, 615.3846153846, 346.1538461538)
    assert (camera.x, camera.y, camera.width, camera.height) == pytest.approx(expected)
    images = {at: compose_png_frame(layout, timeline, at).png for at in (1500, 2200)}
    assert images[1500] != images[2200]
    for at in (2200, 1500, 2200):
        assert compose_png_frame(layout, timeline, at).png == images[at]
    assert (layout, timeline) == original


@pytest.mark.parametrize("portrait", [False, True])
def test_real_role_text_focus_preserves_ordinary_camera_path(portrait):
    layout, timeline = camera_documents(portrait=portrait, target="part-content")
    camera = evaluate_frame(layout, timeline, 2200).camera
    assert camera.width == pytest.approx(530.7692307692)
    # Native content region after the actual translated/scaled Group.
    assert camera.x <= 128. and camera.y <= 319.
    assert camera.x + camera.width >= 542. and camera.y + camera.height >= 472.


@pytest.mark.parametrize("portrait", [False, True])
def test_camera_uses_real_completed_group_motion_not_authored_start_pose(portrait):
    from test_v2_registry_consumers import private_clock

    from atme.store.contracts_v2 import ExecutableLayoutV2, ResolvedVisualTimelineV2

    layout, timeline = camera_documents(portrait=portrait)
    group = next(obj for obj in layout["objects"] if obj["object_id"] == "list-group")
    destination = deepcopy(group["transform"])
    group["transform"]["position"] = {"x": 0., "y": 0.}
    timeline["actions"][0]["action"].update(verb="move", destination=destination, opacity=None)
    timeline["layout_sha256"] = digest(layout)
    typed, resolved = ExecutableLayoutV2.model_validate(layout), ResolvedVisualTimelineV2.model_validate(timeline)
    _, replay, _ = private_clock(typed, resolved, digest(layout), None)
    capture = replay.before_action("native-camera")
    assert capture.object("list-group").transform.position.x == 10.
    assert capture.object("list-group").transform.position.y == 20.
    assert dict(capture.state_versions)["list-group"] == 2
    assert dict(capture.state_versions)["object-evidence"] == 1
    camera = evaluate_frame(layout, timeline, 2200).camera
    expected = (46.5384615385, 0., 576.9230769231, 1025.6410256410) if portrait else (
        27.3076923077, 181.9230769231, 615.3846153846, 346.1538461538)
    assert (camera.x, camera.y, camera.width, camera.height) == pytest.approx(expected)


def test_camera_admission_does_not_enable_native_target_morph():
    from atme.render.v2_morph import UnsupportedMorph, validate_morph_geometry
    from atme.store.contracts_v2 import ExecutableLayoutV2, MorphPolicy

    layout, _ = camera_documents()
    obj = next(obj for obj in ExecutableLayoutV2.model_validate(layout).objects if obj.object_id == "object-evidence")
    with pytest.raises(UnsupportedMorph, match="authored mark geometry"):
        validate_morph_geometry(obj, obj, MorphPolicy(mapping="canonical_outline"))


@pytest.mark.parametrize("fault", ["bare", "anchor", "part_fit", "hidden", "clip", "mask", "clip_id", "ancestor_motion", "group_target"])
def test_native_camera_rejects_unproven_or_unsupported_focus_before_first_frame(fault):
    layout, timeline = camera_documents()
    objects = {obj["object_id"]: obj for obj in layout["objects"]}
    chrome = objects["object-evidence"]
    if fault == "bare":
        chrome.pop("technical_frame")
    elif fault == "anchor":
        chrome["anchors"][0]["point"]["x"] += .01
    elif fault == "part_fit":
        objects["part-content"]["transform"]["position"]["x"] = 500.
    elif fault == "hidden":
        for obj in layout["objects"]:
            if obj["object_id"] != "list-group":
                obj.update(initial_state="hidden", visible=False)
                next(row for row in timeline["initial_object_states"] if row["object_id"] == obj["object_id"]).update(
                    state="hidden", visible=False)
    elif fault == "group_target":
        timeline["actions"][1]["action"]["target_ids"] = ["list-group"]
    elif fault == "mask":
        from test_v2_technical_frame_endpoints import add_native_aperture

        add_native_aperture(layout, timeline, "mask")
    elif fault == "ancestor_motion":
        motion = action_row(timeline["actions"][0], {"verb": "move", "target_ids": ["list-group"],
            "opacity": None, "destination": deepcopy(objects["list-group"]["transform"])}, 2000, 3000, "move-parent")
        motion["action"]["destination"]["position"]["x"] = 30.
        set_actions(timeline, [*timeline["actions"], motion])
    else:
        outer = deepcopy(objects["list-group"])
        outer.update(object_id="outer-clip", object_type="clip", child_ids=["list-group"], parent_id=None)
        outer["transform"].update(position={"x": 0., "y": 0.}, scale_x=1., scale_y=1.)
        objects["list-group"]["parent_id"] = outer["object_id"]
        layout["objects"].append(outer)
        layout["boards"][0]["object_ids"].append(outer["object_id"])
        timeline["initial_object_states"].append({"object_id": outer["object_id"], "state": "visible",
                                                "visible": True, "state_version": 1})
        if fault == "clip_id":
            chrome["clip_id"] = outer["object_id"]
    timeline["layout_sha256"] = digest(layout)
    with pytest.raises(ValueError, match="unsupported|physical|revealed visible|post-clip|clip_id|focus-object edit"):
        evaluate_frame(layout, timeline, 0)
