"""Static preflight rejects malformed operators before the replay clock executes."""

from copy import deepcopy

import pytest
from test_v2_camera_action import append_camera
from test_v2_connection_actions import relationship_documents
from test_v2_frame_state import supported_documents
from test_v2_hierarchy_replay import prepared, reverse
from test_v2_hierarchy_snapshot import basis
from test_v2_replace_action import documents as replacement_documents
from test_v2_timeline_replay import moving, resolved
from v2_fixtures import digest

from atme.render import v2_state
from atme.render.v2_camera import camera_segments
from atme.render.v2_hierarchy import HierarchySnapshot
from atme.render.v2_hierarchy_replay import completed_hierarchy_basis
from atme.render.v2_timeline_replay import replay_chronology
from atme.store.contracts_v2 import ExecutableLayoutV2, ResolvedVisualTimelineV2


@pytest.mark.parametrize("kind", ["connection", "fade", "annotation", "replace", "list", "managed"])
def test_invalid_operator_form_is_rejected_before_constructing_replay(kind, monkeypatch):
    if kind in {"connection", "managed"}:
        layout, timeline = relationship_documents()
        action = timeline["actions"][2]["action"]
        if kind == "connection":
            action["source_anchor_id"] = "different-anchor"
            expected = "disagrees with the authored connector"
        else:
            for field in ("connector_id", "source_object_id", "source_anchor_id",
                          "destination_object_id", "destination_anchor_id"):
                action.pop(field)
            action.update(verb="reveal", target_ids=["object-arrow"], annotation=None)
            expected = "mutates a connection-managed connector"
    elif kind == "replace":
        layout, timeline = replacement_documents()
        layout["objects"][0]["object_type"] = "bracket"
        timeline["layout_sha256"] = digest(layout)
        expected = "supported paintable leaves"
    else:
        layout, timeline = supported_documents("fade" if kind == "fade" else
                                               "progressive_reveal" if kind == "list" else "reveal")
        action = timeline["actions"][2]["action"]
        if kind == "fade":
            action["destination"] = deepcopy(layout["objects"][2]["transform"])
            expected = "fade cannot carry an ignored transform destination"
        elif kind == "annotation":
            action["annotation"] = "This text has no executable annotation objects"
            expected = "carries an annotation it cannot display"
        else:
            expected = "authored ordered-child list"
    # These are model-valid adversarial pairs: schema rejection alone would not
    # prove the preflight/runtime boundary this test is asserting.
    ExecutableLayoutV2.model_validate(layout)
    ResolvedVisualTimelineV2.model_validate(timeline)

    def forbidden_replay(*args, **kwargs):
        pytest.fail("malformed authored operator reached chronology construction")

    monkeypatch.setattr(v2_state, "replay_chronology", forbidden_replay)
    with pytest.raises(v2_state.V2FrameError, match=expected):
        v2_state.evaluate_frame(layout, timeline, 100)


def test_camera_consumes_regrouped_ancestry_and_later_collective_motion():
    layout, timeline, _, _ = basis()
    action, _, _, frames, _ = prepared()
    layout["objects"][3]["initial_state"] = "grouped"
    timeline["initial_object_states"][3]["state"] = "grouped"
    append_camera(timeline, "before-group", "camera_cut", 4900, 4950)
    ungroup = resolved(action.model_copy(update={"action_id": "ungroup-execute"}), 5000, 6000)
    regroup = resolved(reverse(action).model_copy(update={"action_id": "regroup"}), 6500, 7000)
    collective = moving(action, frames, target="object-group", start=7000, end=8000)
    timeline["actions"].extend(item.model_dump(mode="json") for item in (ungroup, regroup, collective))
    timeline["coverage"][2]["action_ids"].extend(item.action.action_id for item in (ungroup, regroup, collective))
    append_camera(timeline, "after-group", "camera_cut", 8000, 8500)
    parsed_layout = ExecutableLayoutV2.model_validate(layout)
    objects = {obj.object_id: obj for obj in parsed_layout.objects}
    hierarchy = HierarchySnapshot.from_objects(objects)
    initial_frames = {obj.object_id: v2_state.FrameObject(
        object_id=obj.object_id, board_id=obj.board_id, state=obj.initial_state,
        visible=obj.visible, opacity=obj.opacity, reveal_fraction=1.0 if obj.visible else 0.0,
        transform=v2_state.FrameTransform.from_contract(obj.transform),
    ) for obj in parsed_layout.objects}
    receipt = completed_hierarchy_basis(hierarchy, initial_frames)
    timeline["initial_hierarchy_basis"] = receipt.model_dump(mode="json")
    timeline["initial_hierarchy_basis_sha256"] = receipt.checksum()
    timeline["layout_sha256"] = digest(layout)
    parsed_timeline = ResolvedVisualTimelineV2.model_validate(timeline)
    context = v2_state._validate_pair_static(parsed_layout, parsed_timeline, digest(layout), hierarchy)
    replay = replay_chronology(
        context.objects, hierarchy, {frame.object_id: frame for frame in context.frames},
        {key: state.state_version for key, state in context.initial.items()}, tuple(parsed_timeline.actions),
        tuple((a.board_id, a.start_ms, a.end_ms) for a in parsed_layout.activations), parsed_timeline.duration_ms,
    )
    before, after = camera_segments(parsed_layout, parsed_timeline, replay)
    assert replay.at(6000).hierarchy.ancestors("object-system") == ()
    assert replay.at(8000).hierarchy.ancestors("object-system") == ("object-group",)
    assert replay.before_action("after-group").object("object-group").transform.position.x == 300
    assert after[2] == before[3]  # Exact previous camera viewport inheritance.
    assert after[3].x > before[3].x
    replay.at(9000)
    assert camera_segments(parsed_layout, parsed_timeline, replay) == (before, after)
    # This is a private camera/clock consumer proof, not public Group playback.
    with pytest.raises(v2_state.UnsupportedVisualAction, match="no frame implementation"):
        v2_state.evaluate_frame(layout, timeline, 8000)
