"""Transient board context cannot rewrite retained pointers or evidence holds."""

from copy import deepcopy
from dataclasses import replace

import pytest
from test_v2_annotation_action import append_target
from test_v2_annotation_contract import leader_documents
from test_v2_evidence_compositor import evidence_documents
from test_v2_group_annotation import annotation_group_documents, consumer_clock
from v2_fixtures import digest

from atme.render import v2_state
from atme.render.v2_hierarchy import HierarchySnapshot
from atme.render.v2_state import V2FrameError, evaluate_frame
from atme.store.contracts_v2 import ExecutableLayoutV2, ResolvedVisualTimelineV2


@pytest.mark.parametrize("after_exit", [False, True])
@pytest.mark.parametrize("post_group", [False, True])
def test_unrelated_focus_isolate_waits_for_retained_pointer_completed_exit(after_exit, post_group):
    layout, timeline = annotation_group_documents(nested=True) if post_group else leader_documents()[1:]
    if after_exit:
        append_target(timeline, "annotation-leader", "exit", 8000, 8250)
    start = 8250 if after_exit else 8000
    append_target(timeline, "object-evidence", "isolate", start, start + 500)
    timeline["layout_sha256"] = digest(layout)
    if after_exit:
        _, replay, _ = consumer_clock(layout, timeline)
        assert not replay.at(start).object("annotation-leader").visible
        assert replay.at(start + 250).object("object-evidence").opacity == 1
    else:
        with pytest.raises(V2FrameError, match="completed explicit removal"):
            consumer_clock(layout, timeline)


@pytest.mark.parametrize("focus", ["object-evidence", "object-system"])
@pytest.mark.parametrize("after_hold", [False, True])
def test_evidence_hold_has_explicit_isolate_conflict_independent_of_opacity(tmp_path, focus, after_hold):
    service, layout, timeline, _ = evidence_documents(tmp_path)
    try:
        # Author the evidence's allowed completed state as canonical visible;
        # this does not make its primitive an admitted public Isolate focus.
        timeline["actions"][2]["action"]["post_state"] = "visible"
        timeline["actions"][2]["action"]["destination_state"] = "visible"
        for document in (layout, timeline):
            document["evidence_treatments"][0]["intent"]["destination_state"] = "visible"
        timeline["layout_sha256"] = digest(layout)
        parsed_layout = ExecutableLayoutV2.model_validate(layout)
        parsed_timeline = ResolvedVisualTimelineV2.model_validate(timeline)
        hierarchy = HierarchySnapshot.from_objects({obj.object_id: obj for obj in parsed_layout.objects})
        baseline = v2_state._validate_pair_static(parsed_layout, parsed_timeline, digest(layout), hierarchy)
        hold_end = (timeline["actions"][2]["end_ms"]
                    + layout["evidence_treatments"][0]["intent"]["readable_hold_intent_ms"])
        start = hold_end if after_hold else hold_end - 300
        original = deepcopy((layout, timeline))
        append_target(timeline, focus, "isolate", start, start + 200)
        # Evidence itself is not a public supported Isolate focus. Exercise the
        # temporal hold rule independently, without opening that static gate.
        context = replace(baseline, timeline=ResolvedVisualTimelineV2.model_validate(timeline))
        if after_hold:
            replay, _ = v2_state._validate_consumer_history(context)
            assert replay.at(start).object("object-evidence").opacity == 1
        else:
            with pytest.raises(V2FrameError, match="evidence.*readable.*hold.*isolate"):
                v2_state._validate_consumer_history(context)
        assert layout == original[0]
        if focus == "object-evidence":
            with pytest.raises(V2FrameError, match="supported focus object"):
                evaluate_frame(layout, timeline, 0)
    finally:
        service.store.close()
