"""Actual private replay wires structural and board-wide read reservations."""
from copy import deepcopy
from dataclasses import replace

import pytest
from atme.render.v2_external_aperture import (
    external_aperture_projections,
    validate_external_aperture_history,
)
from atme.render.v2_hierarchy import (
    HierarchySnapshot,
    changed_hierarchy_objects,
    validate_authored_hierarchy,
)
from atme.render.v2_hierarchy_replay import completed_hierarchy_basis
from atme.render.v2_split import _reservation_footprint
from atme.render.v2_timeline_replay import replay_chronology
from atme.store import contracts_v2 as contracts
from test_v2_external_aperture_lifecycle import add_action, initial_state
from test_v2_external_aperture_runtime import runtime_documents
from test_v2_split_identity import sample_for_layout
from v2_fixtures import digest


@pytest.mark.parametrize("writer", ["group", "isolate"])
@pytest.mark.parametrize("prior", [False, True])
def test_real_structural_or_same_board_writer_is_reserved_only_during_positive_external_paint(writer, prior):
    _plan, layout, clock, ids = runtime_documents("clip")
    root = next(obj for obj in layout["objects"] if obj["object_id"] == ids["root"])
    shell = deepcopy(root)
    shell.update(object_id="unrelated-shell", child_ids=[], initial_state="ungrouped", visible=True, z_index=-2)
    shell["transform"].update(position={"x": 0., "y": 0.}, scale_x=1., scale_y=1., rotation_degrees=0., origin={"x": 0., "y": 0.})
    extra = deepcopy(next(obj for obj in layout["objects"] if obj["object_id"] == "external-receiver"))
    extra.update(object_id="unrelated-root", clip_id=None, parent_id=None, z_index=-1)
    additions = [shell, extra] if writer == "group" else [extra]
    layout["objects"].extend(additions)
    layout["boards"][0]["object_ids"].extend(obj["object_id"] for obj in additions)
    clock["initial_object_states"].extend({"object_id": obj["object_id"], "state": obj["initial_state"],
        "visible": obj["visible"], "state_version": 1} for obj in additions)
    if writer == "group":
        # Bootstrap the owned-shell shape, then replace its placeholder with
        # the actual completed basis below before constructing the replay.
        layout["initial_empty_group_ownership"] = [{"shell_object_id": shell["object_id"],
            "owner_group_action_id": "structural-writer", "owner_source_basis_sha256": "0" * 64}]
    if prior:
        initial_state(layout, clock, "external-receiver", "hidden", False)
        reveal = deepcopy(clock["actions"][0]["action"])
        reveal.update(action_id="receiver-becomes-live", target_ids=["external-receiver"])
        add_action(clock, reveal, 2000, 2500)
    typed = contracts.ExecutableLayoutV2.model_validate(layout)
    objects = {obj.object_id: obj for obj in typed.objects}
    initial = sample_for_layout(typed)
    frames = {row.object_id: row for row in initial.objects}
    action = deepcopy(clock["actions"][0]["action"])
    action.pop("annotation", None)
    if writer == "group":
        before = initial.hierarchy
        # Group an unrelated earlier sibling. No aperture/consumer/read pose
        # is edited, but the common root's actual sibling ordinal changes.
        after = HierarchySnapshot(tuple(replace(node, parent_id="unrelated-shell", sibling_ordinal=0)
            if node.object_id == "unrelated-root" else replace(node, sibling_ordinal=1)
            if node.object_id == ids["root"] else node for node in before.nodes))
        source, destination = (completed_hierarchy_basis(tree, frames) for tree in (before, after))
        action.update(action_id="structural-writer", verb="group", target_ids=["unrelated-root"],
            container_id="unrelated-shell", easing="step", expected_state="ungrouped", post_state="grouped",
            hierarchy_policy={"member_root_ids": ["unrelated-root"],
                "source_basis": source.model_dump(mode="json"), "source_basis_sha256": source.checksum(),
                "destination_basis": destination.model_dump(mode="json"), "destination_basis_sha256": destination.checksum(),
                "changed_object_ids": list(changed_hierarchy_objects(before, after, objects)), "preserve_world_transform": True})
        assert validate_authored_hierarchy(contracts.GroupAction.model_validate(action), objects) == (before, after)
        layout["initial_empty_group_ownership"][0]["owner_source_basis_sha256"] = source.checksum()
        clock.update(initial_hierarchy_basis=source.model_dump(mode="json"), initial_hierarchy_basis_sha256=source.checksum())
    else:
        action.update(action_id="board-writer", verb="isolate", target_ids=[ids["art"]] if prior else [ids["art"], ids["receiver"]],
                      expected_state="visible", post_state="visible", easing="linear")
    add_action(clock, action, 1000, 1500)
    clock["layout_sha256"] = digest(layout)
    typed = contracts.ExecutableLayoutV2.model_validate(layout)
    timeline = contracts.ResolvedVisualTimelineV2.model_validate(clock)
    replay = replay_chronology(objects, initial.hierarchy, frames, dict(initial.state_versions), tuple(timeline.actions),
        tuple((row.board_id, row.start_ms, row.end_ms) for row in typed.activations), timeline.duration_ms)
    if writer == "group":
        assert replay.at(1500).hierarchy == after
        assert replay.at(1500).object("unrelated-shell").state == "grouped"
        assert next(node for node in before.nodes if node.object_id == ids["root"]).sibling_ordinal == 2
        assert next(node for node in after.nodes if node.object_id == ids["root"]).sibling_ordinal == 1
        assert typed.initial_empty_group_ownership[0].owner_source_basis_sha256 == source.checksum()
    else:
        assert replay.at(1250).object("unrelated-root").opacity < frames["unrelated-root"].opacity
        assert replay.at(1250).object(ids["aperture"]).opacity == 1.
    # Demonstrate the dedicated branch, not an incidental exclusive-read write.
    projection = external_aperture_projections(objects, frames, active_board=root["board_id"])[0]
    writes, _reads = _reservation_footprint(next(row for row in timeline.actions if row.action.action_id == action["action_id"]).action)
    assert not projection.read_ids.intersection(writes)
    if writer == "group":
        assert projection.structural_ids.intersection(writes) == {ids["root"]}
    if prior:
        validate_external_aperture_history(typed, timeline, objects, replay)
        assert replay.at(2500).object("external-receiver").visible
    else:
        with pytest.raises(ValueError, match=f"read lifetime conflicts with action {action['action_id']}"):
            validate_external_aperture_history(typed, timeline, objects, replay)
