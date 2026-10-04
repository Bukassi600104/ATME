"""Each return observes its own chronological board history, never the initial pose."""

from copy import deepcopy

import pytest
from test_v2_hierarchy_replay import reverse
from test_v2_return_hierarchy import (
    group_return_documents,
    private_clock,
    rehash_receipt,
)
from test_v2_timeline_replay import resolved
from v2_fixtures import digest

from atme.render.v2_hierarchy import HierarchySnapshot
from atme.render.v2_hierarchy_replay import completed_hierarchy_basis
from atme.render.v2_timeline_replay import ReplayError
from atme.store.contracts_v2 import GroupAction, ResolvedVisualTimelineV2


def multiple_return_documents():
    layout, timeline = group_return_documents()
    layout["activations"][2]["end_ms"] = 8000
    layout["boards"][1].update(persistence_policy="returnable", activation_policy="returnable")
    layout["activations"].extend([
        {"activation_id": "activation-interlude-2", "board_id": "board-interlude",
         "start_ms": 8000, "end_ms": 8500, "reason": "Inspect context again"},
        {"activation_id": "activation-return-2", "board_id": "board-main",
         "start_ms": 8500, "end_ms": 10000, "reason": "Return to revised grouping"},
    ])
    group = reverse(GroupAction.model_validate(timeline["actions"][3]["action"]))
    group.action_id = "regroup-later"
    timeline["actions"].append(resolved(group, 7300, 7500).model_dump(mode="json"))
    timeline["coverage"][2]["action_ids"].append("regroup-later")
    timeline["layout_sha256"] = digest(layout)
    _, prefix = private_clock(layout, timeline)
    sample = prefix.at(8500)
    owned = {obj.object_id: obj for obj in sample.objects if obj.board_id == "board-main"}
    basis = completed_hierarchy_basis(
        HierarchySnapshot(tuple(node for node in sample.hierarchy.nodes if node.board_id == "board-main")), owned)
    returned = deepcopy(timeline["actions"][4])
    returned.update(start_ms=8500, end_ms=8501)
    trigger = {"kind": "absolute", "at_ms": 8500}
    returned["resolved_trigger"].update(source=trigger, alignment_anchor_ms=8500, resolved_at_ms=8500)
    returned["action"].update(action_id="return-2", trigger=trigger,
                               source_activation_id="activation-interlude-2",
                               prior_destination_activation_id="activation-return",
                               destination_activation_id="activation-return-2",
                               expected_object_states={key: obj.state for key, obj in owned.items()},
                               expected_object_state_versions={key: dict(sample.state_versions)[key] for key in owned})
    returned["return_hierarchy_receipt"].update(action_id="return-2", destination_activation_id="activation-return-2",
                                               hierarchy_basis=basis.model_dump(mode="json"),
                                               hierarchy_basis_sha256=basis.checksum())
    timeline["actions"].append(returned)
    timeline["coverage"][2]["action_ids"].append("return-2")
    return layout, timeline


def test_two_returns_capture_distinct_group_history_without_reset_or_version_increment():
    layout, timeline = multiple_return_documents()
    original = deepcopy((layout, timeline))
    _, replay = private_clock(layout, timeline)
    first, second = replay.before_action("return-1"), replay.before_action("return-2")
    assert first.hierarchy.ancestors("object-system") == ()
    assert second.hierarchy.ancestors("object-system") == ("object-group",)
    for before, during, after in ((6999, 7000, 7001), (8499, 8500, 8501)):
        assert replay.at(before).objects == replay.at(during).objects == replay.at(after).objects
        assert replay.at(before).state_versions == replay.at(during).state_versions == replay.at(after).state_versions
        assert replay.at(before).hierarchy == replay.at(during).hierarchy == replay.at(after).hierarchy
    assert dict(second.state_versions)["object-group"] == dict(first.state_versions)["object-group"] + 1
    assert dict(second.state_versions)["object-evidence"] == dict(first.state_versions)["object-evidence"] + 1
    for at in (9999, 7000, 7500, 8500, 6000, 8501, 6999):
        assert replay.at(at) == private_clock(layout, timeline)[1].at(at)
    assert (layout, timeline) == original


def test_second_return_cannot_reuse_first_hierarchy_with_fresh_identity_and_hash():
    layout, timeline = multiple_return_documents()
    first, second = timeline["actions"][4], timeline["actions"][-1]
    receipt = second["return_hierarchy_receipt"]
    receipt["hierarchy_basis"] = deepcopy(first["return_hierarchy_receipt"]["hierarchy_basis"])
    rehash_receipt(receipt)
    ResolvedVisualTimelineV2.model_validate(timeline)
    with pytest.raises(ReplayError, match="retained board hierarchy"):
        private_clock(layout, timeline)
