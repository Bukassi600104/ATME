"""History-independent authored readiness rejects before chronology construction."""

import pytest
from test_v2_highlight_action import highlight_documents
from test_v2_progressive_list import list_documents
from v2_fixtures import digest

from atme.render import v2_state
from atme.store.contracts_v2 import ExecutableLayoutV2, ResolvedVisualTimelineV2


@pytest.mark.parametrize("verb", ["highlight", "cross_out", "dim", "progressive_reveal"])
def test_initial_readiness_preserves_diagnostics_before_constructing_clock(verb, monkeypatch):
    if verb == "progressive_reveal":
        layout, timeline = list_documents()
        state, visible = "visible", True
        expected = "previously untouched hidden list"
    else:
        layout, timeline = highlight_documents()
        state, visible = "hidden", False
        action = timeline["actions"][2]["action"]
        action.update(verb=verb, post_state={"highlight": "highlighted", "cross_out": "crossed_out",
                                          "dim": "visible"}[verb])
        expected = "visible context without prior edits" if verb == "dim" else "untouched visible target"
    layout["objects"][2].update(initial_state=state, visible=visible)
    timeline["initial_object_states"][2].update(state=state, visible=visible)
    timeline["actions"][2]["action"]["expected_state"] = state
    timeline["layout_sha256"] = digest(layout)
    ExecutableLayoutV2.model_validate(layout)
    ResolvedVisualTimelineV2.model_validate(timeline)

    def forbidden_clock(*args, **kwargs):
        pytest.fail("invalid authored readiness reached chronology construction")

    monkeypatch.setattr(v2_state, "replay_chronology", forbidden_clock)
    with pytest.raises(v2_state.V2FrameError, match=expected):
        v2_state.evaluate_frame(layout, timeline, 0)
