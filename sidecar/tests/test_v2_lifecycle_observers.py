"""Shared replay boundaries and hierarchy proof, with no alternate state ledger."""

from copy import deepcopy
from dataclasses import replace

import pytest
from test_v2_annotation_contract import annotation_documents
from test_v2_hierarchy_replay import prepared
from test_v2_return_hierarchy import private_clock
from test_v2_timeline_replay import moving, resolved, run

from atme.render.v2_annotation import validate_annotation_geometry
from atme.render.v2_camera import CameraViewport
from atme.render.v2_hierarchy import HierarchySnapshot
from atme.render.v2_lifecycle import (
    UnsupportedLifecycle,
    geometry_dependencies,
    group_affects_geometry,
    lifecycle_samples,
    validate_group_lifetime,
)


def test_lifecycle_samples_exact_captured_start_and_group_boundary_without_reset():
    action, objects, hierarchy, frames, versions = prepared()
    item = resolved(action, 1000, 3000)
    trace = run([item])
    original = deepcopy((trace, objects, frames, versions))
    samples = lifecycle_samples(trace, item, 4000)
    assert [sample.at_ms for sample in samples] == [1000, 2999, 3000, 3999]
    assert samples[0] == trace.before_action(item.action.action_id)
    assert samples[1].hierarchy == hierarchy
    assert samples[2].hierarchy.children("board-main", "object-group") == ()
    assert samples[2] == trace.at(3000)
    assert samples[3] == trace.at(3999)
    assert (trace, objects, frames, versions) == original


@pytest.mark.parametrize("hold_end", [True, 3000, 2999, 10001, 1.5])
def test_lifecycle_rejects_empty_unbounded_or_noninteger_holds(hold_end):
    action = prepared()[0]
    item = resolved(action, 1000, 3000)
    with pytest.raises(UnsupportedLifecycle, match="bounded positive readable hold"):
        lifecycle_samples(run([item]), item, hold_end)


def test_group_completion_at_lifecycle_start_is_consumed_before_start_capture():
    action, _, _, frames, _ = prepared()
    group = resolved(action, 1000, 3000)
    item = moving(action, frames, start=3000, end=3500)
    trace = run([group, item])
    samples = lifecycle_samples(trace, item, 4000)
    assert samples[0].at_ms == 3000
    assert samples[0].hierarchy.children("board-main", "object-group") == ()
    assert samples[0] == trace.before_action(item.action.action_id)


def test_geometric_closure_does_not_confuse_unrelated_ordinal_version_shift():
    action, objects, _, frames, versions = prepared()
    trace = run([resolved(action, 1000, 3000)])
    assert dict(trace.at(3000).state_versions)["object-evidence"] == versions["object-evidence"] + 1
    assert not group_affects_geometry(action, objects, ["object-evidence"])
    assert group_affects_geometry(action, objects, ["object-system"])
    assert group_affects_geometry(action, objects, ["object-label"])
    assert geometry_dependencies(trace.at(3000).hierarchy, ["object-evidence"]) == {"object-evidence"}
    validate_group_lifetime(objects, [resolved(action, 1000, 3000)], ["object-evidence"],
                            2000, 4000, description="annotation reading hold")
    assert trace.at(3000).object("object-evidence") == frames["object-evidence"]


@pytest.mark.parametrize("start,end,allowed", [(3000, 4000, True), (2999, 4000, False),
                                               (0, 1000, True), (0, 1001, False)])
def test_geometric_group_lifetimes_are_half_open(start, end, allowed):
    action, objects, _, _, _ = prepared()
    args = (objects, [resolved(action, 1000, 3000)], ["object-system"], start, end)
    if allowed:
        validate_group_lifetime(*args, description="annotation")
    else:
        with pytest.raises(UnsupportedLifecycle, match="geometric hierarchy edit"):
            validate_group_lifetime(*args, description="annotation")


def test_annotation_samples_preserve_hidden_captured_notes_and_completed_reading_state():
    _, layout, timeline = annotation_documents()
    context, trace = private_clock(layout, timeline)
    item = context.timeline.actions[-1]
    samples = lifecycle_samples(trace, item, 8000)
    assert not samples[0].object("annotation-note").visible
    assert samples[0].object("annotation-note").reveal_fraction == 0
    assert samples[-1].object("annotation-note").reveal_fraction == 1
    assert samples[-1].object("annotation-note").visible


def test_runtime_annotation_geometry_reads_sampled_order_not_authored_layer_sort():
    _, layout, timeline = annotation_documents()
    context, trace = private_clock(layout, timeline)
    sample = trace.before_action(context.timeline.actions[-1].action.action_id)
    order = list(sample.hierarchy.children("board-main", None))
    a, b = order.index("annotation-note"), order.index("object-system")
    order[a], order[b] = order[b], order[a]
    bad = HierarchySnapshot(tuple(replace(node, sibling_ordinal=order.index(node.object_id))
                                  for node in sample.hierarchy.nodes))
    objects = bad.object_map(context.objects)
    transforms = {frame.object_id: frame.transform for frame in sample.objects}
    action = context.timeline.actions[-1].action
    with pytest.raises(ValueError, match="paint above"):
        validate_annotation_geometry(action, context.layout, objects, transforms,
                                     [CameraViewport(0, 0, 1280, 720)], hierarchy=bad)
    validate_annotation_geometry(action, context.layout, sample.hierarchy.object_map(context.objects),
                                 transforms, [CameraViewport(0, 0, 1280, 720)], hierarchy=sample.hierarchy)
